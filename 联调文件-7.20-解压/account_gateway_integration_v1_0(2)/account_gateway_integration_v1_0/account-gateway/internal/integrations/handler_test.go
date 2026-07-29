package integrations

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"

	_ "github.com/mattn/go-sqlite3"
)

func TestIntegrationSyncRecordsStatus(t *testing.T) {
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := newIntegrationTestHandler(t, jwt)
	handler.now = func() time.Time {
		return time.Date(2026, 7, 10, 1, 2, 3, 0, time.UTC)
	}
	token := issueIntegrationAdminToken(t, jwt)

	syncReq := httptest.NewRequest(http.MethodPost, "/api/integrations/hr/sync", nil)
	syncReq.Header.Set("Authorization", "Bearer "+token)
	syncRec := httptest.NewRecorder()
	handler.ServeHTTP(syncRec, syncReq)
	if syncRec.Code != http.StatusOK {
		t.Fatalf("sync status = %d, body = %s", syncRec.Code, syncRec.Body.String())
	}
	var synced syncStatus
	if err := json.Unmarshal(syncRec.Body.Bytes(), &synced); err != nil {
		t.Fatalf("decode sync response: %v", err)
	}
	if synced.Provider != "hr" || synced.TenantID != "org-1" || synced.Mode != "mock" || synced.Status != "success" || !synced.Synced || synced.ActorID != "integration-admin" || synced.Summary["users"] != 3 || synced.Attempts != 1 {
		t.Fatalf("unexpected sync response: %+v", synced)
	}

	statusReq := httptest.NewRequest(http.MethodGet, "/api/integrations/hr/status", nil)
	statusReq.Header.Set("Authorization", "Bearer "+token)
	statusRec := httptest.NewRecorder()
	restarted := NewHandler(handler.db, jwt, handler.audit)
	restarted.ServeHTTP(statusRec, statusReq)
	if statusRec.Code != http.StatusOK {
		t.Fatalf("status status = %d, body = %s", statusRec.Code, statusRec.Body.String())
	}
	var status syncStatus
	if err := json.Unmarshal(statusRec.Body.Bytes(), &status); err != nil {
		t.Fatalf("decode status response: %v", err)
	}
	if status.SyncedAt != "2026-07-10T01:02:03Z" || status.Summary["users"] != 3 {
		t.Fatalf("unexpected status response: %+v", status)
	}
}

func TestIntegrationStatusIsTenantScoped(t *testing.T) {
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := newIntegrationTestHandler(t, jwt)
	tenantA, err := jwt.Issue("admin-a", "org-a", []string{"hanhe_admin"})
	if err != nil {
		t.Fatalf("issue tenant A token: %v", err)
	}
	tenantB, err := jwt.Issue("admin-b", "org-b", []string{"hanhe_admin"})
	if err != nil {
		t.Fatalf("issue tenant B token: %v", err)
	}

	syncReq := httptest.NewRequest(http.MethodPost, "/api/integrations/dingtalk/sync", nil)
	syncReq.Header.Set("Authorization", "Bearer "+tenantA)
	syncRec := httptest.NewRecorder()
	handler.ServeHTTP(syncRec, syncReq)
	if syncRec.Code != http.StatusOK {
		t.Fatalf("tenant A sync status = %d, body = %s", syncRec.Code, syncRec.Body.String())
	}

	statusReq := httptest.NewRequest(http.MethodGet, "/api/integrations/dingtalk/status", nil)
	statusReq.Header.Set("Authorization", "Bearer "+tenantB)
	statusRec := httptest.NewRecorder()
	handler.ServeHTTP(statusRec, statusReq)
	if statusRec.Code != http.StatusNotFound {
		t.Fatalf("tenant B status = %d, want 404, body = %s", statusRec.Code, statusRec.Body.String())
	}
}

func TestIntegrationStatusMissingAndUnsupportedProvider(t *testing.T) {
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := newIntegrationTestHandler(t, jwt)
	token := issueIntegrationAdminToken(t, jwt)

	missingReq := httptest.NewRequest(http.MethodGet, "/api/integrations/dingtalk/status", nil)
	missingReq.Header.Set("Authorization", "Bearer "+token)
	missingRec := httptest.NewRecorder()
	handler.ServeHTTP(missingRec, missingReq)
	if missingRec.Code != http.StatusNotFound {
		t.Fatalf("missing status = %d, body = %s", missingRec.Code, missingRec.Body.String())
	}

	unsupportedReq := httptest.NewRequest(http.MethodPost, "/api/integrations/slack/sync", nil)
	unsupportedReq.Header.Set("Authorization", "Bearer "+token)
	unsupportedRec := httptest.NewRecorder()
	handler.ServeHTTP(unsupportedRec, unsupportedReq)
	if unsupportedRec.Code != http.StatusNotFound {
		t.Fatalf("unsupported status = %d, body = %s", unsupportedRec.Code, unsupportedRec.Body.String())
	}
	if unsupportedRec.Body.String() != `{"error":"provider_not_supported"}`+"\n" {
		t.Fatalf("unsupported body = %s", unsupportedRec.Body.String())
	}
}

func TestIntegrationSyncRequiresAdmin(t *testing.T) {
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := newIntegrationTestHandler(t, jwt)
	token, err := jwt.Issue("staff", "org-1", []string{"staff"})
	if err != nil {
		t.Fatalf("issue staff token: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/api/integrations/hr/sync", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
}

func TestIntegrationSyncFailurePersistsStatusAndAudit(t *testing.T) {
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := newIntegrationTestHandler(t, jwt)
	t.Setenv("INTEGRATION_FIXTURE_DIR", filepath.Join(t.TempDir(), "missing"))
	token := issueIntegrationAdminToken(t, jwt)

	req := httptest.NewRequest(http.MethodPost, "/api/integrations/hr/sync", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusInternalServerError || rec.Body.String() != `{"error":"fixture_error"}`+"\n" {
		t.Fatalf("sync status=%d body=%s", rec.Code, rec.Body.String())
	}

	statusReq := httptest.NewRequest(http.MethodGet, "/api/integrations/hr/status", nil)
	statusReq.Header.Set("Authorization", "Bearer "+token)
	statusRec := httptest.NewRecorder()
	handler.ServeHTTP(statusRec, statusReq)
	var status syncStatus
	if statusRec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", statusRec.Code, statusRec.Body.String())
	}
	if err := json.Unmarshal(statusRec.Body.Bytes(), &status); err != nil {
		t.Fatalf("decode status: %v", err)
	}
	if status.Status != "failed" || status.Synced || status.LastError != "fixture_error" || status.Attempts != 1 {
		t.Fatalf("failure status=%+v", status)
	}

	var decision, policyID string
	if err := handler.db.QueryRow(`SELECT policy_decision, policy_id FROM audit_logs WHERE action_type='integrations.sync'`).Scan(&decision, &policyID); err != nil {
		t.Fatalf("read sync audit: %v", err)
	}
	if decision != "deny" || policyID != "integration_sync:hr:failed" {
		t.Fatalf("audit decision=%s policy_id=%s", decision, policyID)
	}
}

func TestConcurrentIntegrationSyncAtomicallyCountsAttempts(t *testing.T) {
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := newIntegrationTestHandler(t, jwt)
	token := issueIntegrationAdminToken(t, jwt)
	var callers sync.WaitGroup
	for i := 0; i < 20; i++ {
		callers.Add(1)
		go func() {
			defer callers.Done()
			req := httptest.NewRequest(http.MethodPost, "/api/integrations/dingtalk/sync", nil)
			req.Header.Set("Authorization", "Bearer "+token)
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			if rec.Code != http.StatusOK {
				t.Errorf("sync status=%d body=%s", rec.Code, rec.Body.String())
			}
		}()
	}
	callers.Wait()
	status, err := handler.readStatus("org-1", "dingtalk")
	if err != nil {
		t.Fatalf("read status: %v", err)
	}
	if status.Attempts != 20 || status.Status != "success" {
		t.Fatalf("status=%+v", status)
	}
}

func newIntegrationTestHandler(t *testing.T, jwt *auth.JWTManager) *Handler {
	t.Helper()
	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	db.SetMaxOpenConns(1)
	t.Cleanup(func() { _ = db.Close() })
	if err := audit.EnsureSchema(db); err != nil {
		if strings.Contains(err.Error(), "go-sqlite3 requires cgo") {
			t.Skipf("sqlite tests require cgo: %v", err)
		}
		t.Fatalf("ensure schema: %v", err)
	}
	return NewHandler(db, jwt, audit.NewWriter(db))
}

func issueIntegrationAdminToken(t *testing.T, jwt *auth.JWTManager) string {
	t.Helper()
	token, err := jwt.Issue("integration-admin", "org-1", []string{"hanhe_admin"})
	if err != nil {
		t.Fatalf("issue admin token: %v", err)
	}
	return token
}
