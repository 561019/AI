package credentials

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/crypto"
	"hanhe.com/account-gateway/internal/policy"
)

type Handler struct {
	db    *sql.DB
	jwt   *auth.JWTManager
	audit *audit.Writer
}

type storeRequest struct {
	Name             string `json:"name"`
	Type             string `json:"type"`
	ExpiresInMinutes int    `json:"expires_in_minutes"`
	ExpiresAt        string `json:"expires_at"`
}

type credentialResponse struct {
	ID          int    `json:"id"`
	Name        string `json:"name"`
	Type        string `json:"type"`
	OwnerUserID string `json:"owner_user_id"`
	TenantID    string `json:"tenant_id,omitempty"`
	CreatedAt   string `json:"created_at"`
	ExpiresAt   string `json:"expires_at,omitempty"`
	Status      string `json:"status,omitempty"`
}

type listResponse struct {
	Credentials []credentialResponse `json:"credentials"`
}

func NewHandler(db *sql.DB, jwt *auth.JWTManager, auditWriter *audit.Writer) *Handler {
	return &Handler{db: db, jwt: jwt, audit: auditWriter}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}

	switch r.Method {
	case http.MethodPost:
		if r.URL.Path == "/api/credentials" {
			h.create(w, r, claims)
			return
		}
		h.use(w, r, claims)
	case http.MethodGet:
		if r.URL.Path != "/api/credentials" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		h.list(w, r, claims)
	case http.MethodDelete:
		h.delete(w, r, claims)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	var req storeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}

	rawValue := strings.TrimSpace(r.Header.Get("X-Credential-Value"))
	if rawValue == "" {
		writeError(w, http.StatusBadRequest, "missing_credential_value")
		return
	}
	expiresAt, ok := credentialExpiresAt(req.ExpiresInMinutes, req.ExpiresAt)
	if !ok {
		writeError(w, http.StatusBadRequest, "invalid_expires_at")
		return
	}

	encrypted, err := crypto.Encrypt(rawValue, encryptionKey())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "encryption_failed")
		return
	}

	now := time.Now().UTC().Format(time.RFC3339)
	result, err := h.insertCredential(req, encrypted, claims.UserID, claims.OrgID, now, expiresAt)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}

	id, _ := result.LastInsertId()
	if h.audit != nil {
		if err := h.audit.LogAction(r.Context(), "credentials.store", claims.UserID, "credential", strconv.FormatInt(id, 10), policy.Decision{Allow: true}, "", r.Header); err != nil {
			log.Printf("credentials store audit failed: %v", err)
		}
	}
	writeJSON(w, http.StatusCreated, credentialResponse{
		ID:          int(id),
		Name:        req.Name,
		Type:        req.Type,
		OwnerUserID: claims.UserID,
		TenantID:    claims.OrgID,
		CreatedAt:   now,
		ExpiresAt:   expiresAt,
		Status:      credentialStatus(expiresAt, time.Now().UTC()),
	})
}

func (h *Handler) insertCredential(req storeRequest, encryptedValue, ownerID, tenantID, now, expiresAt string) (sql.Result, error) {
	result, err := h.db.Exec(
		"INSERT INTO credentials (name, type, encrypted_value, owner_user_id, tenant_id, created_at, updated_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
		req.Name, req.Type, encryptedValue, ownerID, nullableTenantID(tenantID), now, now, nullableExpiresAt(expiresAt),
	)
	if err == nil {
		return result, err
	}
	if strings.Contains(err.Error(), "expires_at") {
		return h.db.Exec(
			"INSERT INTO credentials (name, type, encrypted_value, owner_user_id, tenant_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
			req.Name, req.Type, encryptedValue, ownerID, nullableTenantID(tenantID), now, now,
		)
	}
	if strings.Contains(err.Error(), "tenant_id") {
		return h.db.Exec(
			"INSERT INTO credentials (name, type, encrypted_value, owner_user_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
			req.Name, req.Type, encryptedValue, ownerID, now, now,
		)
	}
	if !strings.Contains(err.Error(), "updated_at") {
		return result, err
	}

	return h.db.Exec(
		"INSERT INTO credentials (name, type, encrypted_value, owner_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
		req.Name, req.Type, encryptedValue, ownerID, now,
	)
}

func (h *Handler) list(w http.ResponseWriter, _ *http.Request, claims auth.Claims) {
	var rows *sql.Rows
	var err error
	if isAdmin(claims) {
		rows, err = h.db.Query("SELECT id, name, type, owner_user_id, COALESCE(tenant_id, ''), created_at, COALESCE(expires_at, '') FROM credentials WHERE COALESCE(tenant_id, ?) = ?", claims.OrgID, claims.OrgID)
	} else {
		rows, err = h.db.Query("SELECT id, name, type, owner_user_id, COALESCE(tenant_id, ''), created_at, COALESCE(expires_at, '') FROM credentials WHERE owner_user_id = ? AND COALESCE(tenant_id, ?) = ?", claims.UserID, claims.OrgID, claims.OrgID)
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	defer rows.Close()

	creds := make([]credentialResponse, 0)
	for rows.Next() {
		var c credentialResponse
		if err := rows.Scan(&c.ID, &c.Name, &c.Type, &c.OwnerUserID, &c.TenantID, &c.CreatedAt, &c.ExpiresAt); err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		c.Status = credentialStatus(c.ExpiresAt, time.Now().UTC())
		creds = append(creds, c)
	}
	if err := rows.Err(); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}

	writeJSON(w, http.StatusOK, listResponse{Credentials: creds})
}

func (h *Handler) use(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	id, pathErr := credentialIDFromPath(r.URL.Path, true)
	if pathErr != "" {
		writeError(w, http.StatusBadRequest, pathErr)
		return
	}

	var encryptedValue, ownerID, tenantID, expiresAt string
	err := h.db.QueryRow("SELECT encrypted_value, owner_user_id, COALESCE(tenant_id, ''), COALESCE(expires_at, '') FROM credentials WHERE id = ?", id).Scan(&encryptedValue, &ownerID, &tenantID, &expiresAt)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "credential_not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}

	if !sameTenant(claims, tenantID) {
		writeError(w, http.StatusNotFound, "credential_not_found")
		return
	}
	if !isOwnerOrAdmin(claims, ownerID) {
		writeError(w, http.StatusForbidden, "unauthorized")
		return
	}
	if credentialExpired(expiresAt, time.Now().UTC()) {
		if h.audit != nil {
			policyID := "credential_expired:" + strconv.Itoa(id)
			if err := h.audit.LogAction(r.Context(), "credentials.use", claims.UserID, "credential", strconv.Itoa(id), policy.Decision{Allow: false, PolicyID: policyID}, policyID, r.Header); err != nil {
				log.Printf("credentials expired use audit failed: %v", err)
			}
		}
		writeError(w, http.StatusConflict, "credential_expired")
		return
	}

	if h.audit != nil {
		if err := h.audit.LogAction(r.Context(), "credentials.use", claims.UserID, "credential", strconv.Itoa(id), policy.Decision{Allow: true}, "", r.Header); err != nil {
			log.Printf("credentials use audit failed: %v", err)
		}
	}

	// The caller must never receive the external-tool secret.  A registered
	// connector will consume encrypted_value inside the gateway process; until
	// that connector is configured this compatibility endpoint fails closed.
	_ = encryptedValue
	writeError(w, http.StatusNotImplemented, "credential_proxy_required")
}

func (h *Handler) delete(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	id, pathErr := credentialIDFromPath(r.URL.Path, false)
	if pathErr != "" {
		writeError(w, http.StatusBadRequest, pathErr)
		return
	}

	var ownerID, tenantID string
	err := h.db.QueryRow("SELECT owner_user_id, COALESCE(tenant_id, '') FROM credentials WHERE id = ?", id).Scan(&ownerID, &tenantID)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "credential_not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}

	if !sameTenant(claims, tenantID) {
		writeError(w, http.StatusNotFound, "credential_not_found")
		return
	}
	if !isOwnerOrAdmin(claims, ownerID) {
		writeError(w, http.StatusForbidden, "unauthorized")
		return
	}

	result, err := h.db.Exec("DELETE FROM credentials WHERE id = ?", id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if affected, err := result.RowsAffected(); err == nil && affected == 0 {
		writeError(w, http.StatusNotFound, "credential_not_found")
		return
	}

	if h.audit != nil {
		if err := h.audit.LogAction(r.Context(), "credentials.delete", claims.UserID, "credential", strconv.Itoa(id), policy.Decision{Allow: true}, "", r.Header); err != nil {
			log.Printf("credentials delete audit failed: %v", err)
		}
	}

	w.WriteHeader(http.StatusNoContent)
}

func credentialIDFromPath(path string, useAction bool) (int, string) {
	parts := strings.Split(strings.Trim(path, "/"), "/")
	if useAction {
		if len(parts) != 4 || parts[0] != "api" || parts[1] != "credentials" || parts[3] != "use" {
			return 0, "invalid_path"
		}
	} else if len(parts) != 3 || parts[0] != "api" || parts[1] != "credentials" {
		return 0, "invalid_path"
	}

	id, err := strconv.Atoi(parts[2])
	if err != nil {
		return 0, "invalid_id"
	}
	return id, ""
}

func isAdmin(claims auth.Claims) bool {
	for _, role := range claims.RoleList {
		if role == "hanhe_admin" {
			return true
		}
	}
	return false
}

func isOwnerOrAdmin(claims auth.Claims, ownerID string) bool {
	return claims.UserID == ownerID || isAdmin(claims)
}

func sameTenant(claims auth.Claims, tenantID string) bool {
	tenantID = strings.TrimSpace(tenantID)
	return tenantID == "" || claims.OrgID == "" || tenantID == claims.OrgID
}

func nullableTenantID(tenantID string) interface{} {
	tenantID = strings.TrimSpace(tenantID)
	if tenantID == "" {
		return nil
	}
	return tenantID
}

func nullableExpiresAt(expiresAt string) interface{} {
	expiresAt = strings.TrimSpace(expiresAt)
	if expiresAt == "" {
		return nil
	}
	return expiresAt
}

func credentialExpiresAt(expiresInMinutes int, expiresAt string) (string, bool) {
	expiresAt = strings.TrimSpace(expiresAt)
	if expiresAt != "" {
		parsed, err := time.Parse(time.RFC3339, expiresAt)
		if err != nil {
			return "", false
		}
		return parsed.UTC().Format(time.RFC3339), true
	}
	if expiresInMinutes < 0 {
		return "", false
	}
	if expiresInMinutes == 0 {
		return "", true
	}
	return time.Now().UTC().Add(time.Duration(expiresInMinutes) * time.Minute).Format(time.RFC3339), true
}

func credentialExpired(expiresAt string, now time.Time) bool {
	expiresAt = strings.TrimSpace(expiresAt)
	if expiresAt == "" {
		return false
	}
	parsed, err := time.Parse(time.RFC3339, expiresAt)
	if err != nil {
		return true
	}
	return !now.Before(parsed)
}

func credentialStatus(expiresAt string, now time.Time) string {
	if credentialExpired(expiresAt, now) {
		return "expired"
	}
	return "active"
}

func encryptionKey() string {
	key := os.Getenv("CREDENTIALS_ENCRYPTION_KEY")
	if key == "" {
		return "change-me-32-byte-encryption-key!!"
	}
	return key
}

func writeJSON(w http.ResponseWriter, status int, response interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(response)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
