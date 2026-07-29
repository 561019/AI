package tenants

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	_ "github.com/mattn/go-sqlite3"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"
)

func TestTenantLifecycleMembershipAndAudit(t *testing.T) {
	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open database: %v", err)
	}
	db.SetMaxOpenConns(1)
	t.Cleanup(func() { _ = db.Close() })
	if err := audit.EnsureSchema(db); err != nil {
		if strings.Contains(err.Error(), "go-sqlite3 requires cgo") {
			t.Skipf("sqlite tests require cgo: %v", err)
		}
		t.Fatalf("ensure schema: %v", err)
	}

	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt).WithAudit(audit.NewWriter(db))
	admin := tenantToken(t, jwt, "platform-admin", "platform", []string{"hanhe_admin"})
	staff := tenantToken(t, jwt, "staff", "tenant-a", []string{"staff"})
	memberA := tenantToken(t, jwt, "member-a", "tenant-a", []string{"staff"})
	nonMember := tenantToken(t, jwt, "not-a-member", "tenant-a", []string{"staff"})

	mustTenantStatus(t, tenantRequest(handler, http.MethodGet, "/api/tenants", "", ""), http.StatusUnauthorized)
	mustTenantStatus(t, tenantRequest(handler, http.MethodPost, "/api/tenants", `{"id":"tenant-a"}`, staff), http.StatusForbidden)

	created := tenantRequest(handler, http.MethodPost, "/api/tenants", `{"id":"tenant-a","name":"Tenant A","users":["member-a"," member-a ",""]}`, admin)
	mustTenantStatus(t, created, http.StatusCreated)
	var createdBody tenant
	if err := json.Unmarshal(created.Body.Bytes(), &createdBody); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if createdBody.ID != "tenant-a" || createdBody.Name != "Tenant A" || len(createdBody.Users) != 1 || createdBody.Users[0] != "member-a" {
		t.Fatalf("unexpected create response: %+v", createdBody)
	}

	duplicate := tenantRequest(handler, http.MethodPost, "/api/tenants", `{"id":"tenant-a","name":"Overwritten","users":["other"]}`, admin)
	mustTenantStatus(t, duplicate, http.StatusConflict)
	if duplicate.Body.String() != `{"error":"tenant_exists"}`+"\n" {
		t.Fatalf("unexpected duplicate response: %s", duplicate.Body.String())
	}

	memberList := tenantRequest(handler, http.MethodGet, "/api/tenants", "", memberA)
	mustTenantStatus(t, memberList, http.StatusOK)
	var listBody struct {
		Tenants []tenant `json:"tenants"`
	}
	if err := json.Unmarshal(memberList.Body.Bytes(), &listBody); err != nil {
		t.Fatalf("decode member list: %v", err)
	}
	if len(listBody.Tenants) != 1 || listBody.Tenants[0].Name != "Tenant A" {
		t.Fatalf("unexpected member list: %+v", listBody.Tenants)
	}
	mustTenantStatus(t, tenantRequest(handler, http.MethodGet, "/api/tenants/tenant-a", "", memberA), http.StatusOK)

	nonMemberList := tenantRequest(handler, http.MethodGet, "/api/tenants", "", nonMember)
	mustTenantStatus(t, nonMemberList, http.StatusOK)
	if err := json.Unmarshal(nonMemberList.Body.Bytes(), &listBody); err != nil {
		t.Fatalf("decode non-member list: %v", err)
	}
	if len(listBody.Tenants) != 0 {
		t.Fatalf("non-member list leaked tenant: %+v", listBody.Tenants)
	}
	mustTenantStatus(t, tenantRequest(handler, http.MethodGet, "/api/tenants/tenant-a", "", nonMember), http.StatusNotFound)
	mustTenantStatus(t, tenantRequest(handler, http.MethodPatch, "/api/tenants/tenant-a", `{"users":["member-b"]}`, memberA), http.StatusForbidden)

	updated := tenantRequest(handler, http.MethodPatch, "/api/tenants/tenant-a", `{"name":"Tenant A Updated","users":["member-b","member-b"]}`, admin)
	mustTenantStatus(t, updated, http.StatusOK)
	var updatedBody tenant
	if err := json.Unmarshal(updated.Body.Bytes(), &updatedBody); err != nil {
		t.Fatalf("decode update response: %v", err)
	}
	if updatedBody.Name != "Tenant A Updated" || len(updatedBody.Users) != 1 || updatedBody.Users[0] != "member-b" {
		t.Fatalf("unexpected update response: %+v", updatedBody)
	}

	memberB := tenantToken(t, jwt, "member-b", "tenant-a", []string{"staff"})
	mustTenantStatus(t, tenantRequest(handler, http.MethodGet, "/api/tenants/tenant-a", "", memberA), http.StatusNotFound)
	mustTenantStatus(t, tenantRequest(handler, http.MethodGet, "/api/tenants/tenant-a", "", memberB), http.StatusOK)
	mustTenantStatus(t, tenantRequest(handler, http.MethodPatch, "/api/tenants/tenant-a", `{}`, admin), http.StatusBadRequest)

	var createAudit, updateAudit int
	if err := db.QueryRow("SELECT COUNT(*) FROM audit_logs WHERE action_type='tenants.create' AND resource_id='tenant-a'").Scan(&createAudit); err != nil {
		t.Fatalf("query create audit: %v", err)
	}
	if err := db.QueryRow("SELECT COUNT(*) FROM audit_logs WHERE action_type='tenants.update' AND resource_id='tenant-a'").Scan(&updateAudit); err != nil {
		t.Fatalf("query update audit: %v", err)
	}
	if createAudit != 1 || updateAudit != 1 {
		t.Fatalf("unexpected audit counts: create=%d update=%d", createAudit, updateAudit)
	}
}

func tenantRequest(handler http.Handler, method, path, body, bearer string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

func tenantToken(t *testing.T, jwt *auth.JWTManager, userID, orgID string, roles []string) string {
	t.Helper()
	token, err := jwt.Issue(userID, orgID, roles)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	return token
}

func mustTenantStatus(t *testing.T, rec *httptest.ResponseRecorder, want int) {
	t.Helper()
	if rec.Code != want {
		t.Fatalf("status=%d want=%d body=%s", rec.Code, want, rec.Body.String())
	}
}
