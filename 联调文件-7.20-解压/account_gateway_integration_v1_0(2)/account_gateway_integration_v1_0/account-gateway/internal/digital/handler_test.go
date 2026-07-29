package digital

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/auth"

	_ "github.com/mattn/go-sqlite3"
)

func TestDigitalEmployeeCRUDAndTokenClaims(t *testing.T) {
	db := openDigitalTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	ownerToken := issueDigitalTestToken(t, jwt, "owner-1", []string{"employee"})

	createReq := httptest.NewRequest(http.MethodPost, "/api/digital-employees", bytes.NewBufferString(`{"name":"agent-1","roles":["tool_runner"]}`))
	createReq.Header.Set("Authorization", "Bearer "+ownerToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)

	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d, body = %s", createRec.Code, createRec.Body.String())
	}
	var createResp struct {
		Name          string   `json:"name"`
		ParentUserID  string   `json:"parent_user_id"`
		TenantID      string   `json:"tenant_id"`
		Roles         []string `json:"roles"`
		ExecutionMode string   `json:"execution_mode"`
		Token         string   `json:"token"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &createResp); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if createResp.Name != "agent-1" || createResp.ParentUserID != "owner-1" || len(createResp.Roles) != 1 || createResp.Roles[0] != "tool_runner" || createResp.Token == "" {
		t.Fatalf("unexpected create response: %+v", createResp)
	}
	if createResp.TenantID != "org-1" {
		t.Fatalf("tenant id = %q", createResp.TenantID)
	}
	if createResp.ExecutionMode != "auto" {
		t.Fatalf("execution mode = %q", createResp.ExecutionMode)
	}

	digitalClaims, err := jwt.Validate(createResp.Token)
	if err != nil {
		t.Fatalf("validate issued digital token: %v", err)
	}
	if !digitalClaims.IsDigital || digitalClaims.ParentUserID != "owner-1" || digitalClaims.UserID != "agent-1" || digitalClaims.OrgID != "org-1" || digitalClaims.TokenVersion != 1 {
		t.Fatalf("unexpected digital token claims: %+v", digitalClaims)
	}

	listReq := httptest.NewRequest(http.MethodGet, "/api/digital-employees", nil)
	listReq.Header.Set("Authorization", "Bearer "+ownerToken)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)
	if listRec.Code != http.StatusOK {
		t.Fatalf("list status = %d, body = %s", listRec.Code, listRec.Body.String())
	}
	var listResp struct {
		DigitalEmployees []struct {
			Name         string   `json:"name"`
			ParentUserID string   `json:"parent_user_id"`
			Roles        []string `json:"roles"`
		} `json:"digital_employees"`
	}
	if err := json.Unmarshal(listRec.Body.Bytes(), &listResp); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if len(listResp.DigitalEmployees) != 1 || listResp.DigitalEmployees[0].Name != "agent-1" {
		t.Fatalf("unexpected list response: %+v", listResp)
	}

	getReq := httptest.NewRequest(http.MethodGet, "/api/digital-employees/agent-1", nil)
	getReq.Header.Set("Authorization", "Bearer "+ownerToken)
	getRec := httptest.NewRecorder()
	handler.ServeHTTP(getRec, getReq)
	if getRec.Code != http.StatusOK {
		t.Fatalf("get status = %d, body = %s", getRec.Code, getRec.Body.String())
	}

	deleteReq := httptest.NewRequest(http.MethodDelete, "/api/digital-employees/agent-1", nil)
	deleteReq.Header.Set("Authorization", "Bearer "+ownerToken)
	deleteRec := httptest.NewRecorder()
	handler.ServeHTTP(deleteRec, deleteReq)
	if deleteRec.Code != http.StatusNoContent {
		t.Fatalf("delete status = %d, body = %s", deleteRec.Code, deleteRec.Body.String())
	}
}

func TestDigitalEmployeeTenantIsolationForAdminAndOwner(t *testing.T) {
	db := openDigitalTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	ownerA := issueDigitalTestTokenForOrg(t, jwt, "owner-a", "org-a", []string{"employee"})
	adminA := issueDigitalTestTokenForOrg(t, jwt, "admin-a", "org-a", []string{"hanhe_admin"})
	adminB := issueDigitalTestTokenForOrg(t, jwt, "admin-b", "org-b", []string{"hanhe_admin"})

	createReq := httptest.NewRequest(http.MethodPost, "/api/digital-employees", bytes.NewBufferString(`{"name":"agent-tenant-a","roles":["tool_runner"]}`))
	createReq.Header.Set("Authorization", "Bearer "+ownerA)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d, body = %s", createRec.Code, createRec.Body.String())
	}

	listB := httptest.NewRequest(http.MethodGet, "/api/digital-employees", nil)
	listB.Header.Set("Authorization", "Bearer "+adminB)
	listBRec := httptest.NewRecorder()
	handler.ServeHTTP(listBRec, listB)
	if listBRec.Code != http.StatusOK {
		t.Fatalf("tenant b admin list status = %d, body = %s", listBRec.Code, listBRec.Body.String())
	}
	if got := listBRec.Body.String(); got != `{"digital_employees":[]}`+"\n" {
		t.Fatalf("tenant b admin list = %s", got)
	}

	for _, tc := range []struct {
		method string
		path   string
		body   string
	}{
		{http.MethodGet, "/api/digital-employees/agent-tenant-a", ""},
		{http.MethodPost, "/api/digital-employees/agent-tenant-a/disable", ""},
		{http.MethodPost, "/api/digital-employees/agent-tenant-a/rotate-token", ""},
		{http.MethodPost, "/api/digital-employees/agent-tenant-a/execution-mode", `{"execution_mode":"scope_reject"}`},
		{http.MethodDelete, "/api/digital-employees/agent-tenant-a", ""},
	} {
		req := httptest.NewRequest(tc.method, tc.path, bytes.NewBufferString(tc.body))
		req.Header.Set("Authorization", "Bearer "+adminB)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusNotFound {
			t.Fatalf("%s %s cross tenant status = %d, body = %s", tc.method, tc.path, rec.Code, rec.Body.String())
		}
	}

	getA := httptest.NewRequest(http.MethodGet, "/api/digital-employees/agent-tenant-a", nil)
	getA.Header.Set("Authorization", "Bearer "+adminA)
	getARec := httptest.NewRecorder()
	handler.ServeHTTP(getARec, getA)
	if getARec.Code != http.StatusOK {
		t.Fatalf("tenant a admin get status = %d, body = %s", getARec.Code, getARec.Body.String())
	}
}

func TestDigitalEmployeeListReturnsEmptyArray(t *testing.T) {
	db := openDigitalTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	ownerToken := issueDigitalTestToken(t, jwt, "owner-empty", []string{"employee"})

	listReq := httptest.NewRequest(http.MethodGet, "/api/digital-employees", nil)
	listReq.Header.Set("Authorization", "Bearer "+ownerToken)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)

	if listRec.Code != http.StatusOK {
		t.Fatalf("list status = %d, body = %s", listRec.Code, listRec.Body.String())
	}
	if got := listRec.Body.String(); got != `{"digital_employees":[]}`+"\n" {
		t.Fatalf("empty list response = %s", got)
	}
}

func TestDigitalEmployeeCannotCreateDigitalEmployee(t *testing.T) {
	db := openDigitalTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	digitalToken, err := jwt.IssueDigital("agent-parent", "org-1", []string{"tool_runner"}, "owner-1")
	if err != nil {
		t.Fatalf("issue digital token: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/api/digital-employees", bytes.NewBufferString(`{"name":"nested-agent"}`))
	req.Header.Set("Authorization", "Bearer "+digitalToken)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("create with digital token status = %d, body = %s", rec.Code, rec.Body.String())
	}
}

func TestDigitalEmployeeExecutionModeCanBeSetByOwner(t *testing.T) {
	db := openDigitalTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	ownerToken := issueDigitalTestToken(t, jwt, "owner-1", []string{"employee"})

	createReq := httptest.NewRequest(http.MethodPost, "/api/digital-employees", bytes.NewBufferString(`{"name":"agent-confirm","roles":["tool_runner"],"execution_mode":"require_confirmation"}`))
	createReq.Header.Set("Authorization", "Bearer "+ownerToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d, body = %s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ExecutionMode string `json:"execution_mode"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ExecutionMode != "require_confirmation" {
		t.Fatalf("create execution mode = %q", created.ExecutionMode)
	}

	setReq := httptest.NewRequest(http.MethodPost, "/api/digital-employees/agent-confirm/execution-mode", bytes.NewBufferString(`{"execution_mode":"scope_reject"}`))
	setReq.Header.Set("Authorization", "Bearer "+ownerToken)
	setRec := httptest.NewRecorder()
	handler.ServeHTTP(setRec, setReq)
	if setRec.Code != http.StatusOK {
		t.Fatalf("set mode status = %d, body = %s", setRec.Code, setRec.Body.String())
	}
	var setResp struct {
		ExecutionMode string `json:"execution_mode"`
	}
	if err := json.Unmarshal(setRec.Body.Bytes(), &setResp); err != nil {
		t.Fatalf("decode set response: %v", err)
	}
	if setResp.ExecutionMode != "scope_reject" {
		t.Fatalf("set execution mode = %q", setResp.ExecutionMode)
	}

	invalidReq := httptest.NewRequest(http.MethodPost, "/api/digital-employees/agent-confirm/execution-mode", bytes.NewBufferString(`{"execution_mode":"manual"}`))
	invalidReq.Header.Set("Authorization", "Bearer "+ownerToken)
	invalidRec := httptest.NewRecorder()
	handler.ServeHTTP(invalidRec, invalidReq)
	if invalidRec.Code != http.StatusBadRequest {
		t.Fatalf("invalid mode status = %d, body = %s", invalidRec.Code, invalidRec.Body.String())
	}
}

func TestDigitalEmployeeExpiryBlocksTokenRotation(t *testing.T) {
	db := openDigitalTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	ownerToken := issueDigitalTestToken(t, jwt, "owner-expiry", []string{"employee"})
	expiredAt := time.Now().UTC().Add(-time.Minute).Format(time.RFC3339)

	createReq := httptest.NewRequest(http.MethodPost, "/api/digital-employees", bytes.NewBufferString(`{"name":"agent-expired","roles":["tool_runner"],"expires_at":"`+expiredAt+`"}`))
	createReq.Header.Set("Authorization", "Bearer "+ownerToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d, body = %s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ExpiresAt string `json:"expires_at"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ExpiresAt != expiredAt {
		t.Fatalf("expires_at = %q, want %q", created.ExpiresAt, expiredAt)
	}

	rotateReq := httptest.NewRequest(http.MethodPost, "/api/digital-employees/agent-expired/rotate-token", nil)
	rotateReq.Header.Set("Authorization", "Bearer "+ownerToken)
	rotateRec := httptest.NewRecorder()
	handler.ServeHTTP(rotateRec, rotateReq)
	if rotateRec.Code != http.StatusConflict {
		t.Fatalf("rotate expired status = %d, body = %s", rotateRec.Code, rotateRec.Body.String())
	}
	var rotateResp map[string]string
	if err := json.Unmarshal(rotateRec.Body.Bytes(), &rotateResp); err != nil {
		t.Fatalf("decode rotate response: %v", err)
	}
	if rotateResp["error"] != "digital_employee_expired" {
		t.Fatalf("rotate error = %q", rotateResp["error"])
	}
}

func openDigitalTestDB(t *testing.T) *sql.DB {
	t.Helper()
	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	db.SetMaxOpenConns(1)
	t.Cleanup(func() {
		_ = db.Close()
	})

	_, err = db.Exec(`
        CREATE TABLE digital_employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            parent_user_id TEXT NOT NULL,
            roles TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            disabled_at TEXT,
            token_version INTEGER NOT NULL DEFAULT 1,
            execution_mode TEXT NOT NULL DEFAULT 'auto',
            tenant_id TEXT,
            expires_at TEXT
        )
	`)
	if err != nil {
		if strings.Contains(err.Error(), "go-sqlite3 requires cgo") {
			t.Skipf("sqlite tests require cgo: %v", err)
		}
		t.Fatalf("create digital employees table: %v", err)
	}

	return db
}

func issueDigitalTestToken(t *testing.T, jwt *auth.JWTManager, userID string, roles []string) string {
	t.Helper()
	return issueDigitalTestTokenForOrg(t, jwt, userID, "org-1", roles)
}

func issueDigitalTestTokenForOrg(t *testing.T, jwt *auth.JWTManager, userID string, orgID string, roles []string) string {
	t.Helper()
	token, err := jwt.Issue(userID, orgID, roles)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	return token
}
