package auditapi

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/policy"

	_ "github.com/mattn/go-sqlite3"
)

func TestAuditStatusReportsWriterStats(t *testing.T) {
	db := openAuditAPITestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	writer := audit.NewWriter(db)
	handler := NewHandler(db, jwt).WithWriter(writer)
	headers := http.Header{
		"X-Request-ID":        []string{"audit-status"},
		"X-User-ID":           []string{"actor-status"},
		"X-Resource-Type":     []string{"tool"},
		"X-Resource-ID":       []string{"tool-status"},
		"X-Resource-Owner-ID": []string{"actor-status"},
		"X-Action":            []string{"use"},
		"X-Tenant-ID":         []string{"tenant-a"},
	}
	if err := writer.LogAction(context.Background(), "test.status", "actor-status", "tool", "tool-status", policy.Decision{Allow: true, PolicyID: "policy-status"}, "policy-status", headers); err != nil {
		t.Fatalf("write audit log: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/audit/status", nil)
	req.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var body struct {
		Configured bool              `json:"configured"`
		Writer     audit.WriterStats `json:"writer"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if !body.Configured || body.Writer.Mode != "sync" || body.Writer.Written != 1 || body.Writer.Failed != 0 || body.Writer.Pending != 0 {
		t.Fatalf("unexpected audit status: %+v", body)
	}

	forbidden := httptest.NewRequest(http.MethodGet, "/api/audit/status", nil)
	forbidden.Header.Set("Authorization", "Bearer "+issueAuditAPIUserToken(t, jwt, "tenant-a"))
	forbiddenRec := httptest.NewRecorder()
	handler.ServeHTTP(forbiddenRec, forbidden)
	if forbiddenRec.Code != http.StatusForbidden {
		t.Fatalf("non-admin status = %d, body = %s", forbiddenRec.Code, forbiddenRec.Body.String())
	}
}

func TestAuditLogsFlushAsyncWriterBeforeQuery(t *testing.T) {
	db := openAuditAPITestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	t.Setenv("AUDIT_MODE", "async")
	writer := audit.NewWriterFromEnv(db)
	defer writer.Close(time.Second)
	handler := NewHandler(db, jwt).WithWriter(writer)
	headers := make(http.Header)
	headers.Set("X-Tenant-ID", "tenant-a")
	if err := writer.LogAction(context.Background(), "test.async_query", "actor-async", "tool", "tool-async", policy.Decision{Allow: true}, "policy-async", headers); err != nil {
		t.Fatalf("enqueue audit log: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/audit/logs?action_type=test.async_query", nil)
	req.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	var body struct {
		Logs []auditLog `json:"logs"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(body.Logs) != 1 || body.Logs[0].ActorID != "actor-async" {
		t.Fatalf("logs=%+v", body.Logs)
	}
	if writer.Stats().Pending != 0 {
		t.Fatalf("writer not flushed: %+v", writer.Stats())
	}
}

func TestAuditLogsSupportFiltersAndTenantScope(t *testing.T) {
	db := openAuditAPITestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	firstID := insertAuditAPILog(t, db, "2026-07-10T01:00:00Z", "actor-a", "auth.validate", "data", "data-a", "allow", "tenant-a")
	insertAuditAPILog(t, db, "2026-07-10T01:01:00Z", "actor-b", "auth.validate", "data", "data-b", "allow", "tenant-b")
	insertAuditAPILog(t, db, "2026-07-10T01:02:00Z", "actor-a", "credentials.use", "credential", "cred-a", "deny", "tenant-a")
	targetID := insertAuditAPILog(t, db, "2026-07-10T01:03:00Z", "actor-a", "auth.validate", "data", "data-c", "allow", "tenant-a")

	req := httptest.NewRequest(http.MethodGet, "/api/audit/logs?after_id="+strconv.FormatInt(firstID, 10)+"&actor_id=actor-a&action_type=auth.validate&resource_type=data&decision=allow&from_ts=2026-07-10T01:00:00Z&to_ts=2026-07-10T01:04:00Z", nil)
	req.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var body struct {
		Logs        []auditLog `json:"logs"`
		NextAfterID int64      `json:"next_after_id"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(body.Logs) != 1 {
		t.Fatalf("logs = %+v", body.Logs)
	}
	if body.Logs[0].ID != targetID || body.Logs[0].ResourceID != "data-c" || body.NextAfterID != targetID {
		t.Fatalf("unexpected filtered response: %+v", body)
	}
}

func TestAuditExportUsesSameFilters(t *testing.T) {
	db := openAuditAPITestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	insertAuditAPILog(t, db, "2026-07-10T02:00:00Z", "actor-a", "auth.validate", "data", "data-a", "allow", "tenant-a")
	insertAuditAPILog(t, db, "2026-07-10T02:01:00Z", "actor-a", "auth.validate", "data", "data-b", "deny", "tenant-a")

	req := httptest.NewRequest(http.MethodGet, "/api/audit/export?action_type=auth.validate&decision=deny", nil)
	req.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "data-b") || strings.Contains(rec.Body.String(), "data-a") {
		t.Fatalf("unexpected csv body: %s", rec.Body.String())
	}
}

func TestAuditLogsSupportTraceIDFilter(t *testing.T) {
	db := openAuditAPITestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	insertAuditAPILogWithContext(t, db, "2026-07-10T02:00:00Z", "actor-a", "auth.validate", "data", "data-a", "allow", `{"x_tenant_id":"tenant-a","trace_id":"trace-a"}`)
	targetID := insertAuditAPILogWithContext(t, db, "2026-07-10T02:01:00Z", "actor-a", "auth.validate", "data", "data-b", "allow", `{"x_tenant_id":"tenant-a","trace_id":"trace-b"}`)

	req := httptest.NewRequest(http.MethodGet, "/api/audit/logs?trace_id=trace-b", nil)
	req.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var body struct {
		Logs []auditLog `json:"logs"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(body.Logs) != 1 || body.Logs[0].ID != targetID || body.Logs[0].ResourceID != "data-b" {
		t.Fatalf("unexpected trace-filtered response: %+v", body)
	}
}

func TestAuditLogsDoNotApplySecurityEventDefaultsWhenQueryOmitsThem(t *testing.T) {
	db := openAuditAPITestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	targetID := insertAuditAPILogWithContext(t, db, "2026-07-10T02:03:00Z", "actor-a", "auth.validate", "data", "data-default-filter", "allow", `{"x_tenant_id":"tenant-a","trace_id":"trace-default-filter"}`)

	req := httptest.NewRequest(http.MethodGet, "/api/audit/logs?trace_id=trace-default-filter", nil)
	req.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var body struct {
		Logs []auditLog `json:"logs"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(body.Logs) != 1 || body.Logs[0].ID != targetID {
		t.Fatalf("unexpected logs without severity filter: %+v", body.Logs)
	}
}

func TestAuditEventsRecordSecurityEvent(t *testing.T) {
	db := openAuditAPITestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)

	req := httptest.NewRequest(http.MethodPost, "/api/audit/events", bytes.NewBufferString(`{
		"action_type":"security.mask",
		"resource_type":"data",
		"resource_id":"data-1",
		"policy_decision":"deny",
		"policy_id":"mask-rule-1",
		"severity":"high",
		"disposition_status":"acknowledged",
		"ticket_id":"SEC-1",
		"context":{"module":"security-compliance","result":"masked","severity":"low"}
	}`))
	req.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	req.Header.Set("X-Trace-ID", "trace-security")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var created struct {
		ID                int64  `json:"id"`
		ActionType        string `json:"action_type"`
		Status            string `json:"status"`
		Severity          string `json:"severity"`
		DispositionStatus string `json:"disposition_status"`
		TicketID          string `json:"ticket_id"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if created.ID == 0 || created.ActionType != "security.mask" || created.Status != "recorded" || created.Severity != "high" || created.DispositionStatus != "acknowledged" || created.TicketID != "SEC-1" {
		t.Fatalf("unexpected create response: %+v", created)
	}

	var contextSnapshot string
	err := db.QueryRow(`
		SELECT context_snapshot
		FROM audit_logs
		WHERE id=?
	`, created.ID).Scan(&contextSnapshot)
	if err != nil {
		t.Fatalf("read event: %v", err)
	}
	if !strings.Contains(contextSnapshot, `"trace_id":"trace-security"`) ||
		!strings.Contains(contextSnapshot, `"module":"security-compliance"`) ||
		!strings.Contains(contextSnapshot, `"x_tenant_id":"tenant-a"`) ||
		!strings.Contains(contextSnapshot, `"severity":"high"`) ||
		!strings.Contains(contextSnapshot, `"disposition_status":"acknowledged"`) ||
		!strings.Contains(contextSnapshot, `"ticket_id":"SEC-1"`) {
		t.Fatalf("unexpected context snapshot: %s", contextSnapshot)
	}

	filterReq := httptest.NewRequest(http.MethodGet, "/api/audit/logs?severity=high&disposition_status=acknowledged&ticket_id=SEC-1", nil)
	filterReq.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	filterRec := httptest.NewRecorder()
	handler.ServeHTTP(filterRec, filterReq)
	if filterRec.Code != http.StatusOK {
		t.Fatalf("filter status = %d, body = %s", filterRec.Code, filterRec.Body.String())
	}
	var filtered struct {
		Logs []auditLog `json:"logs"`
	}
	if err := json.Unmarshal(filterRec.Body.Bytes(), &filtered); err != nil {
		t.Fatalf("decode filtered response: %v", err)
	}
	if len(filtered.Logs) != 1 || filtered.Logs[0].ID != created.ID {
		t.Fatalf("unexpected filtered logs: %+v", filtered.Logs)
	}
}

func TestAuditEventsRejectNonSecurityAction(t *testing.T) {
	db := openAuditAPITestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	req := httptest.NewRequest(http.MethodPost, "/api/audit/events", bytes.NewBufferString(`{"action_type":"auth.validate"}`))
	req.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if rec.Body.String() != `{"error":"invalid_action_type"}`+"\n" {
		t.Fatalf("body = %s", rec.Body.String())
	}
}

func TestAuditEventsRejectInvalidSeverityAndDisposition(t *testing.T) {
	db := openAuditAPITestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)

	invalidSeverity := httptest.NewRequest(http.MethodPost, "/api/audit/events", bytes.NewBufferString(`{"action_type":"security.mask","severity":"urgent"}`))
	invalidSeverity.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	invalidSeverityRec := httptest.NewRecorder()
	handler.ServeHTTP(invalidSeverityRec, invalidSeverity)
	if invalidSeverityRec.Code != http.StatusBadRequest || invalidSeverityRec.Body.String() != `{"error":"invalid_severity"}`+"\n" {
		t.Fatalf("invalid severity status=%d body=%s", invalidSeverityRec.Code, invalidSeverityRec.Body.String())
	}

	invalidDisposition := httptest.NewRequest(http.MethodPost, "/api/audit/events", bytes.NewBufferString(`{"action_type":"security.mask","disposition_status":"done"}`))
	invalidDisposition.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	invalidDispositionRec := httptest.NewRecorder()
	handler.ServeHTTP(invalidDispositionRec, invalidDisposition)
	if invalidDispositionRec.Code != http.StatusBadRequest || invalidDispositionRec.Body.String() != `{"error":"invalid_disposition_status"}`+"\n" {
		t.Fatalf("invalid disposition status=%d body=%s", invalidDispositionRec.Code, invalidDispositionRec.Body.String())
	}
}

func TestAuditLogsRejectInvalidQueryValues(t *testing.T) {
	db := openAuditAPITestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt)
	req := httptest.NewRequest(http.MethodGet, "/api/audit/logs?after_id=not-a-number", nil)
	req.Header.Set("Authorization", "Bearer "+issueAuditAPIAdminToken(t, jwt, "tenant-a"))
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if rec.Body.String() != `{"error":"invalid_after_id"}`+"\n" {
		t.Fatalf("body = %s", rec.Body.String())
	}
}

func openAuditAPITestDB(t *testing.T) *sql.DB {
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

func insertAuditAPILog(t *testing.T, db *sql.DB, ts, actorID, actionType, resourceType, resourceID, decision, tenantID string) int64 {
	t.Helper()
	return insertAuditAPILogWithContext(t, db, ts, actorID, actionType, resourceType, resourceID, decision, `{"x_tenant_id":"`+tenantID+`"}`)
}

func insertAuditAPILogWithContext(t *testing.T, db *sql.DB, ts, actorID, actionType, resourceType, resourceID, decision, contextSnapshot string) int64 {
	t.Helper()
	result, err := db.Exec(`
		INSERT INTO audit_logs (
			ts,
			actor_id,
			action_type,
			resource_type,
			resource_id,
			policy_decision,
			policy_id,
			context_snapshot,
			version
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, ts, actorID, actionType, resourceType, resourceID, decision, "policy-1", contextSnapshot, 1)
	if err != nil {
		t.Fatalf("insert audit log: %v", err)
	}
	id, err := result.LastInsertId()
	if err != nil {
		t.Fatalf("last insert id: %v", err)
	}
	return id
}

func issueAuditAPIAdminToken(t *testing.T, jwt *auth.JWTManager, orgID string) string {
	t.Helper()
	token, err := jwt.Issue("audit-admin", orgID, []string{"hanhe_admin"})
	if err != nil {
		t.Fatalf("issue admin token: %v", err)
	}
	return token
}

func issueAuditAPIUserToken(t *testing.T, jwt *auth.JWTManager, orgID string) string {
	t.Helper()
	token, err := jwt.Issue("audit-user", orgID, []string{"staff"})
	if err != nil {
		t.Fatalf("issue user token: %v", err)
	}
	return token
}
