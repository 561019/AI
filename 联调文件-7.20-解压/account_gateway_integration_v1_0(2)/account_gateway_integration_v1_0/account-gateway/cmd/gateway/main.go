package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"hanhe.com/account-gateway/internal/account"
	"hanhe.com/account-gateway/internal/approvals"
	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auditapi"
	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/breakglass"
	"hanhe.com/account-gateway/internal/credentials"
	"hanhe.com/account-gateway/internal/digital"
	"hanhe.com/account-gateway/internal/gateway"
	"hanhe.com/account-gateway/internal/identity"
	"hanhe.com/account-gateway/internal/integrations"
	"hanhe.com/account-gateway/internal/layerapi"
	"hanhe.com/account-gateway/internal/organization"
	"hanhe.com/account-gateway/internal/permissionclient"
	"hanhe.com/account-gateway/internal/policy"
	"hanhe.com/account-gateway/internal/tenants"

	_ "github.com/mattn/go-sqlite3"
)

func healthHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func retiredPermissionHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusGone)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error":   "permission_capability_moved",
		"message": "该权限能力已迁移到权限管理模块控制面或 L1 层接口。",
	})
}

func main() {
	if err := auth.ValidateProductionConfig(); err != nil {
		log.Fatal(err)
	}
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		log.Fatal(err)
	}
	auditDB, err := sql.Open("sqlite3", auditDBPath())
	if err != nil {
		log.Fatal(err)
	}
	defer auditDB.Close()
	if err := audit.EnsureSchema(auditDB); err != nil {
		log.Fatal(err)
	}
	organizationStore := organization.NewStore(auditDB)
	if restored, err := approvals.RestoreRuntimePolicies(auditDB, enforcer); err != nil {
		log.Fatal(err)
	} else if restored > 0 {
		log.Printf("restored %d runtime policies", restored)
	}
	auditWriter := audit.NewWriterFromEnv(auditDB)
	defer func() {
		if !auditWriter.Close(10 * time.Second) {
			log.Printf("audit writer shutdown timed out: %+v", auditWriter.Stats())
		}
	}()
	jwtManager := auth.NewJWTManagerFromEnv()
	permissionMode := permissionclient.ModeFromEnv()
	permissionClient := permissionclient.NewFromEnv()
	oidcClient := auth.NewOIDCClientFromEnv()

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/login", loginHandler(oidcClient))
	mux.HandleFunc("/callback", callbackHandler(oidcClient, jwtManager))
	validateHandler := gateway.NewValidateHandler(auditDB, enforcer, auditWriter, jwtManager).
		WithOrganizationStore(organizationStore).
		WithPermissionClient(permissionClient, permissionMode)
	mux.Handle("/auth/validate", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, validateHandler))
	// Account lifecycle changes only account identity state. Resource and data
	// custody are controlled by their owning modules through the L1 channel.
	accountHandler := breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, account.NewHandler(jwtManager, auditWriter))
	mux.Handle("/api/accounts", accountHandler)
	mux.Handle("/api/accounts/", accountHandler)
	mux.Handle("/api/identity/context", identity.NewHandler(organizationStore, jwtManager))
	mux.Handle("/api/layer/identity-context", layerapi.NewIdentityHandler(organizationStore))
	mux.Handle("/api/layer/permission-probe", layerapi.NewPermissionProbeHandler())
	mux.HandleFunc("/api/ui-permissions", retiredPermissionHandler)
	auditHandler := auditapi.NewHandler(auditDB, jwtManager).WithWriter(auditWriter)
	mux.Handle("/api/audit/logs", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, auditHandler))
	mux.Handle("/api/audit/export", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, auditHandler))
	mux.Handle("/api/audit/status", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, auditHandler))
	mux.Handle("/api/audit/events", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, auditHandler))
	credentialsHandler := credentials.NewHandler(auditDB, jwtManager, auditWriter)
	mux.Handle("/api/credentials", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, credentialsHandler))
	mux.Handle("/api/credentials/", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, credentialsHandler))
	digitalHandler := digital.NewHandler(auditDB, jwtManager).WithAudit(auditWriter)
	mux.Handle("/api/digital-employees", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, digitalHandler))
	mux.Handle("/api/digital-employees/", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, digitalHandler))
	tenantHandler := breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, tenants.NewHandler(auditDB, jwtManager).WithAudit(auditWriter))
	mux.Handle("/api/tenants", tenantHandler)
	mux.Handle("/api/tenants/", tenantHandler)
	// Approval templates and runtime policies are no longer exposed by the
	// identity gateway; authorization governance belongs to permission control.
	mux.HandleFunc("/api/approvals", retiredPermissionHandler)
	mux.HandleFunc("/api/approvals/", retiredPermissionHandler)
	mux.HandleFunc("/api/approval-templates", retiredPermissionHandler)
	organizationHandler := organization.NewHandler(organizationStore, jwtManager, auditWriter)
	// Permission and authorization-management facts have moved to the
	// permission module.  This endpoint remains only as a JWT compatibility
	// proxy; it never writes the account-gateway organization store.
	var aggregatePermissionHandler http.Handler = permissionclient.NewManagementProxy(permissionClient, jwtManager)
	mux.Handle("/api/org/commands", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, aggregatePermissionHandler))
	mux.Handle("/api/org/snapshot", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, aggregatePermissionHandler))
	mux.Handle("/api/permissions/commands", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, aggregatePermissionHandler))
	mux.Handle("/api/permissions/snapshot", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, aggregatePermissionHandler))
	mux.Handle("/api/positions", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, organizationHandler))
	mux.Handle("/api/person-position-assignments", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, organizationHandler))
	mux.Handle("/api/person-position-assignments/", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, organizationHandler))
	mux.Handle("/api/domains", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, organizationHandler))
	mux.Handle("/api/person-manager-edges", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, organizationHandler))
	mux.HandleFunc("/api/position-standard-resources", retiredPermissionHandler)
	mux.HandleFunc("/api/delegations", retiredPermissionHandler)
	mux.HandleFunc("/api/resources", retiredPermissionHandler)
	mux.HandleFunc("/api/resource-publications", retiredPermissionHandler)
	mux.HandleFunc("/api/resource-publications/", retiredPermissionHandler)
	integrationHandler := integrations.NewHandler(auditDB, jwtManager, auditWriter)
	mux.Handle("/api/integrations/", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, integrationHandler))
	breakglassHandler := breakglass.NewHandler(auditDB, jwtManager, auditWriter)
	mux.Handle("/api/breakglass", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, breakglassHandler))
	mux.Handle("/api/breakglass/", breakglass.AuditMiddleware(auditDB, jwtManager, auditWriter, breakglassHandler))

	server := &http.Server{
		Addr:              ":8080",
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	serverErrors := make(chan error, 1)
	go func() {
		log.Printf("account gateway listening on :8080 permission_mode=%s", permissionMode)
		serverErrors <- server.ListenAndServe()
	}()

	shutdownSignal, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	select {
	case err := <-serverErrors:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Printf("account gateway server failed: %v", err)
		}
	case <-shutdownSignal.Done():
		log.Println("account gateway shutting down")
		shutdownContext, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdownContext); err != nil {
			log.Printf("account gateway graceful shutdown failed: %v", err)
		}
	}
}

func auditDBPath() string {
	path := os.Getenv("AUDIT_DB_PATH")
	if path == "" {
		return "audit.db"
	}
	return path
}

func loginHandler(oidcClient *auth.OIDCClient) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		state := r.URL.Query().Get("state")
		if state == "" {
			state = "account-gateway"
		}
		http.Redirect(w, r, oidcClient.LoginURL(state), http.StatusFound)
	}
}

func callbackHandler(oidcClient *auth.OIDCClient, jwtManager *auth.JWTManager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}

		identity, err := oidcClient.ExchangeCode(r.URL.Query().Get("code"), r.URL.Query().Get("state"))
		if err != nil {
			writeAuthJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid_callback"})
			return
		}
		token, err := jwtManager.Issue(identity.UserID, identity.OrgID, identity.RoleList)
		if err != nil {
			writeAuthJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid_identity"})
			return
		}
		writeAuthJSON(w, http.StatusOK, map[string]string{"token": token})
	}
}

func writeAuthJSON(w http.ResponseWriter, status int, response map[string]string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(response)
}
