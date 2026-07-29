package breakglass

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"

	_ "github.com/mattn/go-sqlite3"
)

func TestAuditMiddlewareBlocksInactiveBreakglassOutsideManagement(t *testing.T) {
	db := openBreakglassTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	token := issueBreakglassTestToken(t, jwt)
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/api/ui-permissions", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()

	AuditMiddleware(db, jwt, audit.NewWriter(db), next).ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if rec.Body.String() != `{"error":"breakglass_inactive"}`+"\n" {
		t.Fatalf("body = %s", rec.Body.String())
	}
}

func TestAuditMiddlewareLetsBreakglassManagementReachHandler(t *testing.T) {
	db := openBreakglassTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	token := issueBreakglassTestToken(t, jwt)
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTeapot)
	})

	req := httptest.NewRequest(http.MethodPost, "/api/breakglass/enable", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()

	AuditMiddleware(db, jwt, audit.NewWriter(db), next).ServeHTTP(rec, req)

	if rec.Code != http.StatusTeapot {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
}

func TestAuditMiddlewareLogsActiveBreakglassAccess(t *testing.T) {
	db := openBreakglassTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	token := issueBreakglassTestToken(t, jwt)
	expiresAt := time.Now().UTC().Add(time.Hour).Format(time.RFC3339)
	if _, err := db.Exec("INSERT INTO breakglass_state (id, enabled, expires_at) VALUES (1, 1, ?)", expiresAt); err != nil {
		t.Fatalf("seed breakglass state: %v", err)
	}
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/api/ui-permissions", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()

	AuditMiddleware(db, jwt, audit.NewWriter(db), next).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var count int
	if err := db.QueryRow("SELECT COUNT(*) FROM audit_logs WHERE action_type = 'breakglass.access'").Scan(&count); err != nil {
		t.Fatalf("read audit count: %v", err)
	}
	if count != 1 {
		t.Fatalf("breakglass access audit count = %d", count)
	}
}

func TestBreakglassDualApprovalRequiresSecondAdmin(t *testing.T) {
	t.Setenv("BREAKGLASS_REQUIRE_APPROVAL", "1")
	t.Setenv("CREDENTIALS_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")
	db := openBreakglassTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt, audit.NewWriter(db))
	requesterToken := issueBreakglassAdminToken(t, jwt, "requester-admin")
	approverToken := issueBreakglassAdminToken(t, jwt, "approver-admin")

	enableReq := httptest.NewRequest(http.MethodPost, "/api/breakglass/enable", bytes.NewBufferString(`{"reason":"dual approval","ticket_id":"BG-2","expires_in_minutes":30}`))
	enableReq.Header.Set("Authorization", "Bearer "+requesterToken)
	enableRec := httptest.NewRecorder()
	handler.ServeHTTP(enableRec, enableReq)
	if enableRec.Code != http.StatusAccepted {
		t.Fatalf("enable status = %d, body = %s", enableRec.Code, enableRec.Body.String())
	}
	var requested map[string]interface{}
	if err := json.Unmarshal(enableRec.Body.Bytes(), &requested); err != nil {
		t.Fatalf("decode enable response: %v", err)
	}
	if requested["status"] != "pending_approval" || requested["token"] != nil {
		t.Fatalf("unexpected enable response: %+v", requested)
	}
	active, err := IsBreakglassActive(db)
	if err != nil {
		t.Fatalf("check active: %v", err)
	}
	if active {
		t.Fatalf("breakglass should not be active before second approval")
	}

	selfApproveReq := httptest.NewRequest(http.MethodPost, "/api/breakglass/approve", nil)
	selfApproveReq.Header.Set("Authorization", "Bearer "+requesterToken)
	selfApproveRec := httptest.NewRecorder()
	handler.ServeHTTP(selfApproveRec, selfApproveReq)
	if selfApproveRec.Code != http.StatusForbidden {
		t.Fatalf("self approve status = %d, body = %s", selfApproveRec.Code, selfApproveRec.Body.String())
	}

	approveReq := httptest.NewRequest(http.MethodPost, "/api/breakglass/approve", nil)
	approveReq.Header.Set("Authorization", "Bearer "+approverToken)
	approveRec := httptest.NewRecorder()
	handler.ServeHTTP(approveRec, approveReq)
	if approveRec.Code != http.StatusOK {
		t.Fatalf("approve status = %d, body = %s", approveRec.Code, approveRec.Body.String())
	}
	var approved map[string]interface{}
	if err := json.Unmarshal(approveRec.Body.Bytes(), &approved); err != nil {
		t.Fatalf("decode approve response: %v", err)
	}
	if approved["enabled"] != true || approved["token"] == "" || approved["activated_by"] != "requester-admin" || approved["approved_by"] != "approver-admin" {
		t.Fatalf("unexpected approve response: %+v", approved)
	}
	active, err = IsBreakglassActive(db)
	if err != nil {
		t.Fatalf("check active after approve: %v", err)
	}
	if !active {
		t.Fatalf("breakglass should be active after approval")
	}

	var requestedAudits int
	if err := db.QueryRow("SELECT COUNT(*) FROM audit_logs WHERE action_type IN ('breakglass.enable_requested', 'breakglass.approve')").Scan(&requestedAudits); err != nil {
		t.Fatalf("read audit count: %v", err)
	}
	if requestedAudits != 2 {
		t.Fatalf("dual approval audit count = %d", requestedAudits)
	}
}

func TestBreakglassReportSummarizesStateAndAudit(t *testing.T) {
	t.Setenv("CREDENTIALS_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")
	db := openBreakglassTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	writer := audit.NewWriter(db)
	handler := NewHandler(db, jwt, writer)
	adminToken := issueBreakglassAdminToken(t, jwt, "report-admin")

	enableReq := httptest.NewRequest(http.MethodPost, "/api/breakglass/enable", bytes.NewBufferString(`{"reason":"incident review","ticket_id":"BG-7","expires_in_minutes":30}`))
	enableReq.Header.Set("Authorization", "Bearer "+adminToken)
	enableRec := httptest.NewRecorder()
	handler.ServeHTTP(enableRec, enableReq)
	if enableRec.Code != http.StatusOK {
		t.Fatalf("enable status = %d, body = %s", enableRec.Code, enableRec.Body.String())
	}
	handler.LogBreakglassAccess(context.Background(), auth.Claims{UserID: "breakglass", OrgID: "org-1", RoleList: []string{"hanhe_admin"}, IsBreakglass: true}, http.Header{})
	handler.LogBreakglassAccess(context.Background(), auth.Claims{UserID: "other-breakglass", OrgID: "org-2", RoleList: []string{"hanhe_admin"}, IsBreakglass: true}, http.Header{})

	reportReq := httptest.NewRequest(http.MethodGet, "/api/breakglass/report", nil)
	reportReq.Header.Set("Authorization", "Bearer "+adminToken)
	reportRec := httptest.NewRecorder()
	handler.ServeHTTP(reportRec, reportReq)
	if reportRec.Code != http.StatusOK {
		t.Fatalf("report status = %d, body = %s", reportRec.Code, reportRec.Body.String())
	}

	var report map[string]interface{}
	if err := json.Unmarshal(reportRec.Body.Bytes(), &report); err != nil {
		t.Fatalf("decode report response: %v", err)
	}
	if report["enabled"] != true || report["status"] != "active" || report["access_count"].(float64) != 1 {
		t.Fatalf("unexpected report summary: %+v", report)
	}
	state := report["state"].(map[string]interface{})
	if state["reason"] != "incident review" || state["ticket_id"] != "BG-7" || state["activated_by"] != "report-admin" {
		t.Fatalf("unexpected report state: %+v", state)
	}

	var reviewAudits int
	if err := db.QueryRow("SELECT COUNT(*) FROM audit_logs WHERE action_type = 'breakglass.report'").Scan(&reviewAudits); err != nil {
		t.Fatalf("read report audit count: %v", err)
	}
	if reviewAudits != 1 {
		t.Fatalf("breakglass report audit count = %d", reviewAudits)
	}

	selfReviewReq := httptest.NewRequest(http.MethodGet, "/api/breakglass/report", nil)
	selfReviewReq.Header.Set("Authorization", "Bearer "+issueBreakglassTestToken(t, jwt))
	selfReviewRec := httptest.NewRecorder()
	handler.ServeHTTP(selfReviewRec, selfReviewReq)
	if selfReviewRec.Code != http.StatusForbidden {
		t.Fatalf("self review status = %d, body = %s", selfReviewRec.Code, selfReviewRec.Body.String())
	}
}

func openBreakglassTestDB(t *testing.T) *sql.DB {
	t.Helper()
	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	db.SetMaxOpenConns(1)
	t.Cleanup(func() {
		_ = db.Close()
	})
	if err := audit.EnsureSchema(db); err != nil {
		if strings.Contains(err.Error(), "go-sqlite3 requires cgo") {
			t.Skipf("sqlite tests require cgo: %v", err)
		}
		t.Fatalf("ensure audit schema: %v", err)
	}
	return db
}

func issueBreakglassTestToken(t *testing.T, jwt *auth.JWTManager) string {
	t.Helper()
	token, err := jwt.IssueBreakglass("breakglass", "org-1", []string{"hanhe_admin"})
	if err != nil {
		t.Fatalf("issue breakglass token: %v", err)
	}
	return token
}

func issueBreakglassAdminToken(t *testing.T, jwt *auth.JWTManager, userID string) string {
	t.Helper()
	token, err := jwt.Issue(userID, "org-1", []string{"hanhe_admin"})
	if err != nil {
		t.Fatalf("issue admin token: %v", err)
	}
	return token
}
