package approvals

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/policy"

	_ "github.com/mattn/go-sqlite3"
)

func TestApprovePersistsRuntimePolicyAuditsPolicyIDAndRestores(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminToken := issueApprovalTestToken(t, jwt)

	createReq := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{
		"subject":"runtime-user",
		"object":"runtime-data-001",
		"resource_type":"data",
		"action":"read",
		"owner_user_id":"data-owner"
	}`))
	createReq.Header.Set("Authorization", "Bearer "+adminToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d body = %s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ID           int64  `json:"id"`
		ApprovalType string `json:"approval_type"`
	}
	if err := json.NewDecoder(createRec.Body).Decode(&created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ApprovalType != "data_release" {
		t.Fatalf("approval_type = %q, want data_release", created.ApprovalType)
	}

	approveReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	approveReq.Header.Set("Authorization", "Bearer "+adminToken)
	approveRec := httptest.NewRecorder()
	handler.ServeHTTP(approveRec, approveReq)
	if approveRec.Code != http.StatusOK {
		t.Fatalf("approve status = %d body = %s", approveRec.Code, approveRec.Body.String())
	}
	var approved struct {
		Status   string `json:"status"`
		PolicyID string `json:"policy_id"`
	}
	if err := json.NewDecoder(approveRec.Body).Decode(&approved); err != nil {
		t.Fatalf("decode approve response: %v", err)
	}
	expectedPolicyID := "runtime-user:runtime-data-001:data:read:org-1:allow"
	if approved.Status != "approved" || approved.PolicyID != expectedPolicyID {
		t.Fatalf("unexpected approve response: %+v", approved)
	}

	var storedPolicyID string
	if err := db.QueryRow("SELECT policy_id FROM runtime_policies WHERE approval_id = ?", created.ID).Scan(&storedPolicyID); err != nil {
		t.Fatalf("read runtime policy: %v", err)
	}
	if storedPolicyID != expectedPolicyID {
		t.Fatalf("stored policy_id = %q", storedPolicyID)
	}

	var auditPolicyID string
	if err := db.QueryRow(`
		SELECT policy_id
		FROM audit_logs
		WHERE action_type = 'approvals.approve'
		ORDER BY id DESC
		LIMIT 1
	`).Scan(&auditPolicyID); err != nil {
		t.Fatalf("read approval audit: %v", err)
	}
	if auditPolicyID != expectedPolicyID {
		t.Fatalf("audit policy_id = %q", auditPolicyID)
	}

	restoredEnforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new restored enforcer: %v", err)
	}
	restored, err := RestoreRuntimePolicies(db, restoredEnforcer)
	if err != nil {
		t.Fatalf("restore runtime policies: %v", err)
	}
	if restored != 1 {
		t.Fatalf("restored = %d", restored)
	}
	decision, err := restoredEnforcer.EnforceWithTenant("runtime-user", "runtime-data-001", "data", "read", "data-owner", "org-1")
	if err != nil {
		t.Fatalf("enforce restored policy: %v", err)
	}
	if !decision.Allow || decision.PolicyID != expectedPolicyID {
		t.Fatalf("restored decision = %+v", decision)
	}
}

func TestApprovalTemplateResolvesActivePositionAndRestrictsApprover(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminToken := issueApprovalTestToken(t, jwt)
	approverToken := issueApprovalTestUserToken(t, jwt, "template-approver")

	if _, err := db.Exec(`INSERT INTO positions (id, title, department_id, tenant_id, tags, created_by, created_at) VALUES ('pos-template-approver', '审批岗', 'dept-1', 'org-1', '[]', 'admin', '2026-07-14T00:00:00Z')`); err != nil {
		t.Fatalf("create position: %v", err)
	}
	if _, err := db.Exec(`INSERT INTO person_position_assignments (person_id, user_id, position_id, tenant_id, status, assigned_by, assigned_at) VALUES ('person-template-approver', 'template-approver', 'pos-template-approver', 'org-1', 'active', 'admin', '2026-07-14T00:00:00Z')`); err != nil {
		t.Fatalf("assign approver: %v", err)
	}

	template := httptest.NewRequest(http.MethodPost, "/api/approval-templates", bytes.NewBufferString(`{"id":"template-data-read","name":"数据读取审批","approval_type":"data_release","approver_position_id":"pos-template-approver"}`))
	template.Header.Set("Authorization", "Bearer "+adminToken)
	templateRec := httptest.NewRecorder()
	handler.ServeHTTP(templateRec, template)
	if templateRec.Code != http.StatusCreated {
		t.Fatalf("create template status=%d body=%s", templateRec.Code, templateRec.Body.String())
	}

	create := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{"template_id":"template-data-read","subject":"template-user","object":"template-data","resource_type":"data","action":"read","owner_user_id":"data-owner","approver_user_id":"ignored-admin"}`))
	create.Header.Set("Authorization", "Bearer "+adminToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, create)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create approval status=%d body=%s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ID             int64  `json:"id"`
		TemplateID     string `json:"template_id"`
		ApproverUserID string `json:"approver_user_id"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create: %v", err)
	}
	if created.TemplateID != "template-data-read" || created.ApproverUserID != "template-approver" {
		t.Fatalf("template resolution=%+v", created)
	}

	adminApprove := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	adminApprove.Header.Set("Authorization", "Bearer "+adminToken)
	adminApproveRec := httptest.NewRecorder()
	handler.ServeHTTP(adminApproveRec, adminApprove)
	if adminApproveRec.Code != http.StatusForbidden {
		t.Fatalf("admin bypass status=%d body=%s", adminApproveRec.Code, adminApproveRec.Body.String())
	}

	approve := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	approve.Header.Set("Authorization", "Bearer "+approverToken)
	approveRec := httptest.NewRecorder()
	handler.ServeHTTP(approveRec, approve)
	if approveRec.Code != http.StatusOK {
		t.Fatalf("position approver status=%d body=%s", approveRec.Code, approveRec.Body.String())
	}

	if _, err := db.Exec(`UPDATE person_position_assignments SET status='ended' WHERE position_id='pos-template-approver'`); err != nil {
		t.Fatalf("end assignment: %v", err)
	}
	second := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{"template_id":"template-data-read","subject":"template-user-2","object":"template-data-2","resource_type":"data","action":"read","owner_user_id":"data-owner"}`))
	second.Header.Set("Authorization", "Bearer "+adminToken)
	secondRec := httptest.NewRecorder()
	handler.ServeHTTP(secondRec, second)
	if secondRec.Code != http.StatusConflict || secondRec.Body.String() != `{"error":"template_approver_unassigned"}`+"\n" {
		t.Fatalf("unassigned template status=%d body=%s", secondRec.Code, secondRec.Body.String())
	}
}

func TestMultiStageApprovalTemplateAdvancesBeforeFinalApproval(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminToken := issueApprovalTestToken(t, jwt)
	for _, position := range []struct{ id, user string }{{"pos-stage-one", "stage-one-user"}, {"pos-stage-two", "stage-two-user"}} {
		if _, err := db.Exec(`INSERT INTO positions (id, title, department_id, tenant_id, tags, created_by, created_at) VALUES (?, ?, 'dept-1', 'org-1', '[]', 'admin', '2026-07-14T00:00:00Z')`, position.id, position.id); err != nil {
			t.Fatalf("create position %s: %v", position.id, err)
		}
		if _, err := db.Exec(`INSERT INTO person_position_assignments (person_id, user_id, position_id, tenant_id, status, assigned_by, assigned_at) VALUES (?, ?, ?, 'org-1', 'active', 'admin', '2026-07-14T00:00:00Z')`, "person-"+position.id, position.user, position.id); err != nil {
			t.Fatalf("assign %s: %v", position.id, err)
		}
	}

	template := httptest.NewRequest(http.MethodPost, "/api/approval-templates", bytes.NewBufferString(`{"id":"template-two-stage","name":"两级数据读取","approval_type":"data_release","approver_position_ids":["pos-stage-one","pos-stage-two"]}`))
	template.Header.Set("Authorization", "Bearer "+adminToken)
	templateRec := httptest.NewRecorder()
	handler.ServeHTTP(templateRec, template)
	if templateRec.Code != http.StatusCreated {
		t.Fatalf("create template status=%d body=%s", templateRec.Code, templateRec.Body.String())
	}

	create := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{"template_id":"template-two-stage","subject":"two-stage-user","object":"two-stage-data","resource_type":"data","action":"read","owner_user_id":"data-owner"}`))
	create.Header.Set("Authorization", "Bearer "+adminToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, create)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create approval status=%d body=%s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ID int64 `json:"id"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode approval: %v", err)
	}

	first := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	first.Header.Set("Authorization", "Bearer "+issueApprovalTestUserToken(t, jwt, "stage-one-user"))
	firstRec := httptest.NewRecorder()
	handler.ServeHTTP(firstRec, first)
	if firstRec.Code != http.StatusOK || !strings.Contains(firstRec.Body.String(), `"current_stage":1`) || !strings.Contains(firstRec.Body.String(), `"approver_user_id":"stage-two-user"`) {
		t.Fatalf("first stage status=%d body=%s", firstRec.Code, firstRec.Body.String())
	}
	var policies int
	if err := db.QueryRow("SELECT COUNT(*) FROM runtime_policies WHERE approval_id=?", created.ID).Scan(&policies); err != nil || policies != 0 {
		t.Fatalf("runtime policy before final stage count=%d err=%v", policies, err)
	}

	final := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	final.Header.Set("Authorization", "Bearer "+issueApprovalTestUserToken(t, jwt, "stage-two-user"))
	finalRec := httptest.NewRecorder()
	handler.ServeHTTP(finalRec, final)
	if finalRec.Code != http.StatusOK || !strings.Contains(finalRec.Body.String(), `"status":"approved"`) {
		t.Fatalf("final stage status=%d body=%s", finalRec.Code, finalRec.Body.String())
	}
	if err := db.QueryRow("SELECT COUNT(*) FROM runtime_policies WHERE approval_id=?", created.ID).Scan(&policies); err != nil || policies != 1 {
		t.Fatalf("runtime policy after final stage count=%d err=%v", policies, err)
	}
}

func TestBusinessApprovalDoesNotWriteRuntimePolicy(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminToken := issueApprovalTestToken(t, jwt)

	createReq := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{
		"approval_type":"business_approval",
		"subject":"business-user",
		"object":"payment-001",
		"resource_type":"data",
		"action":"approve",
		"owner_user_id":"finance-owner"
	}`))
	createReq.Header.Set("Authorization", "Bearer "+adminToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d body = %s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ID           int64  `json:"id"`
		ApprovalType string `json:"approval_type"`
	}
	if err := json.NewDecoder(createRec.Body).Decode(&created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ApprovalType != "business_approval" {
		t.Fatalf("approval_type = %q", created.ApprovalType)
	}

	approveReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	approveReq.Header.Set("Authorization", "Bearer "+adminToken)
	approveRec := httptest.NewRecorder()
	handler.ServeHTTP(approveRec, approveReq)
	if approveRec.Code != http.StatusOK {
		t.Fatalf("approve status = %d body = %s", approveRec.Code, approveRec.Body.String())
	}
	var approved struct {
		Status       string `json:"status"`
		ApprovalType string `json:"approval_type"`
		PolicyID     string `json:"policy_id"`
	}
	if err := json.NewDecoder(approveRec.Body).Decode(&approved); err != nil {
		t.Fatalf("decode approve response: %v", err)
	}
	if approved.Status != "approved" || approved.ApprovalType != "business_approval" || approved.PolicyID != "" {
		t.Fatalf("unexpected approve response: %+v", approved)
	}

	var runtimePolicies int
	if err := db.QueryRow("SELECT COUNT(*) FROM runtime_policies WHERE approval_id = ?", created.ID).Scan(&runtimePolicies); err != nil {
		t.Fatalf("count runtime policies: %v", err)
	}
	if runtimePolicies != 0 {
		t.Fatalf("business approval wrote runtime policies: %d", runtimePolicies)
	}
	decision, err := enforcer.Enforce("business-user", "payment-001", "data", "approve", "finance-owner")
	if err != nil {
		t.Fatalf("enforce business approval: %v", err)
	}
	if decision.Allow {
		t.Fatalf("business approval should not grant runtime access: %+v", decision)
	}
}

func TestListAndRejectApprovalDoesNotPersistRuntimePolicy(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminToken := issueApprovalTestToken(t, jwt)

	createReq := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{
		"subject":"reject-user",
		"object":"reject-data-001",
		"resource_type":"data",
		"action":"read",
		"owner_user_id":"data-owner"
	}`))
	createReq.Header.Set("Authorization", "Bearer "+adminToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d body = %s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ID int64 `json:"id"`
	}
	if err := json.NewDecoder(createRec.Body).Decode(&created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}

	listReq := httptest.NewRequest(http.MethodGet, "/api/approvals?status=pending", nil)
	listReq.Header.Set("Authorization", "Bearer "+adminToken)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)
	if listRec.Code != http.StatusOK {
		t.Fatalf("list status = %d body = %s", listRec.Code, listRec.Body.String())
	}
	var listed struct {
		Approvals []approvalResponse `json:"approvals"`
	}
	if err := json.NewDecoder(listRec.Body).Decode(&listed); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if len(listed.Approvals) != 1 || listed.Approvals[0].ID != created.ID || listed.Approvals[0].Status != "pending" {
		t.Fatalf("unexpected list response: %+v", listed.Approvals)
	}

	rejectReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/reject", created.ID), nil)
	rejectReq.Header.Set("Authorization", "Bearer "+adminToken)
	rejectRec := httptest.NewRecorder()
	handler.ServeHTTP(rejectRec, rejectReq)
	if rejectRec.Code != http.StatusOK {
		t.Fatalf("reject status = %d body = %s", rejectRec.Code, rejectRec.Body.String())
	}
	var rejected struct {
		Status string `json:"status"`
	}
	if err := json.NewDecoder(rejectRec.Body).Decode(&rejected); err != nil {
		t.Fatalf("decode reject response: %v", err)
	}
	if rejected.Status != "rejected" {
		t.Fatalf("reject response = %+v", rejected)
	}

	var runtimePolicies int
	if err := db.QueryRow("SELECT COUNT(*) FROM runtime_policies WHERE approval_id = ?", created.ID).Scan(&runtimePolicies); err != nil {
		t.Fatalf("count runtime policies: %v", err)
	}
	if runtimePolicies != 0 {
		t.Fatalf("runtime policies after reject = %d", runtimePolicies)
	}

	var auditPolicyID string
	if err := db.QueryRow(`
		SELECT policy_id
		FROM audit_logs
		WHERE action_type = 'approvals.reject'
		ORDER BY id DESC
		LIMIT 1
	`).Scan(&auditPolicyID); err != nil {
		t.Fatalf("read reject audit: %v", err)
	}
	if auditPolicyID != fmt.Sprintf("approval_rejected:%d", created.ID) {
		t.Fatalf("reject audit policy_id = %q", auditPolicyID)
	}

	approveRejectedReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	approveRejectedReq.Header.Set("Authorization", "Bearer "+adminToken)
	approveRejectedRec := httptest.NewRecorder()
	handler.ServeHTTP(approveRejectedRec, approveRejectedReq)
	if approveRejectedRec.Code != http.StatusConflict {
		t.Fatalf("approve rejected status = %d body = %s", approveRejectedRec.Code, approveRejectedRec.Body.String())
	}
}

func TestApprovedApprovalCannotBeRejected(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminToken := issueApprovalTestToken(t, jwt)

	createReq := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{
		"subject":"approved-user",
		"object":"approved-data-001",
		"resource_type":"data",
		"action":"read",
		"owner_user_id":"data-owner"
	}`))
	createReq.Header.Set("Authorization", "Bearer "+adminToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d body = %s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ID int64 `json:"id"`
	}
	if err := json.NewDecoder(createRec.Body).Decode(&created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}

	approveReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	approveReq.Header.Set("Authorization", "Bearer "+adminToken)
	approveRec := httptest.NewRecorder()
	handler.ServeHTTP(approveRec, approveReq)
	if approveRec.Code != http.StatusOK {
		t.Fatalf("approve status = %d body = %s", approveRec.Code, approveRec.Body.String())
	}

	rejectReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/reject", created.ID), nil)
	rejectReq.Header.Set("Authorization", "Bearer "+adminToken)
	rejectRec := httptest.NewRecorder()
	handler.ServeHTTP(rejectRec, rejectReq)
	if rejectRec.Code != http.StatusConflict {
		t.Fatalf("reject approved status = %d body = %s", rejectRec.Code, rejectRec.Body.String())
	}
	var body map[string]string
	if err := json.NewDecoder(rejectRec.Body).Decode(&body); err != nil {
		t.Fatalf("decode reject approved response: %v", err)
	}
	if body["error"] != "approval_already_approved" {
		t.Fatalf("reject approved error = %+v", body)
	}
}

func TestRevokeApprovedApprovalRemovesRuntimePolicyAndDeniesRestore(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminToken := issueApprovalTestToken(t, jwt)

	createReq := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{
		"subject":"revoke-user",
		"object":"revoke-data-001",
		"resource_type":"data",
		"action":"read",
		"owner_user_id":"data-owner"
	}`))
	createReq.Header.Set("Authorization", "Bearer "+adminToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d body = %s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ID int64 `json:"id"`
	}
	if err := json.NewDecoder(createRec.Body).Decode(&created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}

	approveReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	approveReq.Header.Set("Authorization", "Bearer "+adminToken)
	approveRec := httptest.NewRecorder()
	handler.ServeHTTP(approveRec, approveReq)
	if approveRec.Code != http.StatusOK {
		t.Fatalf("approve status = %d body = %s", approveRec.Code, approveRec.Body.String())
	}
	expectedPolicyID := "revoke-user:revoke-data-001:data:read:org-1:allow"
	allowed, err := enforcer.EnforceWithTenant("revoke-user", "revoke-data-001", "data", "read", "data-owner", "org-1")
	if err != nil {
		t.Fatalf("enforce approved policy: %v", err)
	}
	if !allowed.Allow || allowed.PolicyID != expectedPolicyID {
		t.Fatalf("approved decision = %+v", allowed)
	}

	revokeReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/revoke", created.ID), nil)
	revokeReq.Header.Set("Authorization", "Bearer "+adminToken)
	revokeRec := httptest.NewRecorder()
	handler.ServeHTTP(revokeRec, revokeReq)
	if revokeRec.Code != http.StatusOK {
		t.Fatalf("revoke status = %d body = %s", revokeRec.Code, revokeRec.Body.String())
	}
	var revoked struct {
		Status   string `json:"status"`
		PolicyID string `json:"policy_id"`
	}
	if err := json.NewDecoder(revokeRec.Body).Decode(&revoked); err != nil {
		t.Fatalf("decode revoke response: %v", err)
	}
	if revoked.Status != "revoked" || revoked.PolicyID != expectedPolicyID {
		t.Fatalf("unexpected revoke response: %+v", revoked)
	}

	var runtimePolicies int
	if err := db.QueryRow("SELECT COUNT(*) FROM runtime_policies WHERE approval_id = ?", created.ID).Scan(&runtimePolicies); err != nil {
		t.Fatalf("count runtime policies: %v", err)
	}
	if runtimePolicies != 0 {
		t.Fatalf("runtime policies after revoke = %d", runtimePolicies)
	}
	denied, err := enforcer.EnforceWithTenant("revoke-user", "revoke-data-001", "data", "read", "data-owner", "org-1")
	if err != nil {
		t.Fatalf("enforce revoked policy: %v", err)
	}
	if denied.Allow {
		t.Fatalf("revoked decision = %+v", denied)
	}

	var auditPolicyID string
	if err := db.QueryRow(`
		SELECT policy_id
		FROM audit_logs
		WHERE action_type = 'approvals.revoke'
		ORDER BY id DESC
		LIMIT 1
	`).Scan(&auditPolicyID); err != nil {
		t.Fatalf("read revoke audit: %v", err)
	}
	if auditPolicyID != expectedPolicyID {
		t.Fatalf("revoke audit policy_id = %q", auditPolicyID)
	}

	restoredEnforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new restored enforcer: %v", err)
	}
	restored, err := RestoreRuntimePolicies(db, restoredEnforcer)
	if err != nil {
		t.Fatalf("restore runtime policies: %v", err)
	}
	if restored != 0 {
		t.Fatalf("restored = %d", restored)
	}
}

func TestRevokePendingOrRejectedApprovalReturnsStableConflict(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminToken := issueApprovalTestToken(t, jwt)

	create := func(subject string) int64 {
		t.Helper()
		createReq := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(fmt.Sprintf(`{
			"subject":%q,
			"object":"conflict-data",
			"resource_type":"data",
			"action":"read",
			"owner_user_id":"data-owner"
		}`, subject)))
		createReq.Header.Set("Authorization", "Bearer "+adminToken)
		createRec := httptest.NewRecorder()
		handler.ServeHTTP(createRec, createReq)
		if createRec.Code != http.StatusCreated {
			t.Fatalf("create status = %d body = %s", createRec.Code, createRec.Body.String())
		}
		var created struct {
			ID int64 `json:"id"`
		}
		if err := json.NewDecoder(createRec.Body).Decode(&created); err != nil {
			t.Fatalf("decode create response: %v", err)
		}
		return created.ID
	}

	pendingID := create("pending-user")
	pendingRevoke := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/revoke", pendingID), nil)
	pendingRevoke.Header.Set("Authorization", "Bearer "+adminToken)
	pendingRec := httptest.NewRecorder()
	handler.ServeHTTP(pendingRec, pendingRevoke)
	if pendingRec.Code != http.StatusConflict {
		t.Fatalf("pending revoke status = %d body = %s", pendingRec.Code, pendingRec.Body.String())
	}

	rejectedID := create("rejected-user")
	rejectReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/reject", rejectedID), nil)
	rejectReq.Header.Set("Authorization", "Bearer "+adminToken)
	rejectRec := httptest.NewRecorder()
	handler.ServeHTTP(rejectRec, rejectReq)
	if rejectRec.Code != http.StatusOK {
		t.Fatalf("reject status = %d body = %s", rejectRec.Code, rejectRec.Body.String())
	}
	revokeRejectedReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/revoke", rejectedID), nil)
	revokeRejectedReq.Header.Set("Authorization", "Bearer "+adminToken)
	revokeRejectedRec := httptest.NewRecorder()
	handler.ServeHTTP(revokeRejectedRec, revokeRejectedReq)
	if revokeRejectedRec.Code != http.StatusConflict {
		t.Fatalf("rejected revoke status = %d body = %s", revokeRejectedRec.Code, revokeRejectedRec.Body.String())
	}
}

func TestAssignedApproverCanApproveAndUnauthorizedUserCannotHandle(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminToken := issueApprovalTestToken(t, jwt)
	approverToken := issueApprovalTestUserToken(t, jwt, "approver-1")
	otherToken := issueApprovalTestUserToken(t, jwt, "other-user")

	createReq := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{
		"subject":"assigned-user",
		"object":"assigned-data-001",
		"resource_type":"data",
		"action":"read",
		"owner_user_id":"data-owner",
		"approver_user_id":"approver-1"
	}`))
	createReq.Header.Set("Authorization", "Bearer "+adminToken)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d body = %s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ID             int64  `json:"id"`
		ApproverUserID string `json:"approver_user_id"`
	}
	if err := json.NewDecoder(createRec.Body).Decode(&created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ApproverUserID != "approver-1" {
		t.Fatalf("approver_user_id = %q", created.ApproverUserID)
	}

	otherApproveReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	otherApproveReq.Header.Set("Authorization", "Bearer "+otherToken)
	otherApproveRec := httptest.NewRecorder()
	handler.ServeHTTP(otherApproveRec, otherApproveReq)
	if otherApproveRec.Code != http.StatusForbidden {
		t.Fatalf("other approve status = %d body = %s", otherApproveRec.Code, otherApproveRec.Body.String())
	}

	approveReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	approveReq.Header.Set("Authorization", "Bearer "+approverToken)
	approveRec := httptest.NewRecorder()
	handler.ServeHTTP(approveRec, approveReq)
	if approveRec.Code != http.StatusOK {
		t.Fatalf("assigned approve status = %d body = %s", approveRec.Code, approveRec.Body.String())
	}
	var approved struct {
		Status string `json:"status"`
	}
	if err := json.NewDecoder(approveRec.Body).Decode(&approved); err != nil {
		t.Fatalf("decode approve response: %v", err)
	}
	if approved.Status != "approved" {
		t.Fatalf("approve response = %+v", approved)
	}

	otherRevokeReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/revoke", created.ID), nil)
	otherRevokeReq.Header.Set("Authorization", "Bearer "+otherToken)
	otherRevokeRec := httptest.NewRecorder()
	handler.ServeHTTP(otherRevokeRec, otherRevokeReq)
	if otherRevokeRec.Code != http.StatusForbidden {
		t.Fatalf("other revoke status = %d body = %s", otherRevokeRec.Code, otherRevokeRec.Body.String())
	}

	revokeReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/revoke", created.ID), nil)
	revokeReq.Header.Set("Authorization", "Bearer "+approverToken)
	revokeRec := httptest.NewRecorder()
	handler.ServeHTTP(revokeRec, revokeReq)
	if revokeRec.Code != http.StatusOK {
		t.Fatalf("assigned revoke status = %d body = %s", revokeRec.Code, revokeRec.Body.String())
	}
}

func TestApprovalsAreScopedToJWTOrg(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminOrg1 := issueApprovalTestOrgToken(t, jwt, "approval-admin-org-1", "org-1", []string{"hanhe_admin"})
	adminOrg2 := issueApprovalTestOrgToken(t, jwt, "approval-admin-org-2", "org-2", []string{"hanhe_admin"})

	createReq := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{
		"subject":"tenant-user",
		"object":"tenant-data-001",
		"resource_type":"data",
		"action":"read",
		"owner_user_id":"tenant-owner"
	}`))
	createReq.Header.Set("Authorization", "Bearer "+adminOrg1)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d body = %s", createRec.Code, createRec.Body.String())
	}
	var created struct {
		ID       int64  `json:"id"`
		TenantID string `json:"tenant_id"`
	}
	if err := json.NewDecoder(createRec.Body).Decode(&created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.TenantID != "org-1" {
		t.Fatalf("tenant_id = %q", created.TenantID)
	}

	listOrg1 := httptest.NewRequest(http.MethodGet, "/api/approvals", nil)
	listOrg1.Header.Set("Authorization", "Bearer "+adminOrg1)
	listOrg1Rec := httptest.NewRecorder()
	handler.ServeHTTP(listOrg1Rec, listOrg1)
	if listOrg1Rec.Code != http.StatusOK {
		t.Fatalf("list org1 status = %d body = %s", listOrg1Rec.Code, listOrg1Rec.Body.String())
	}
	var listed struct {
		Approvals []approvalResponse `json:"approvals"`
	}
	if err := json.NewDecoder(listOrg1Rec.Body).Decode(&listed); err != nil {
		t.Fatalf("decode list org1: %v", err)
	}
	if len(listed.Approvals) != 1 || listed.Approvals[0].TenantID != "org-1" {
		t.Fatalf("unexpected org1 list: %+v", listed.Approvals)
	}

	listOrg2 := httptest.NewRequest(http.MethodGet, "/api/approvals", nil)
	listOrg2.Header.Set("Authorization", "Bearer "+adminOrg2)
	listOrg2Rec := httptest.NewRecorder()
	handler.ServeHTTP(listOrg2Rec, listOrg2)
	if listOrg2Rec.Code != http.StatusOK {
		t.Fatalf("list org2 status = %d body = %s", listOrg2Rec.Code, listOrg2Rec.Body.String())
	}
	var listedOrg2 struct {
		Approvals []approvalResponse `json:"approvals"`
	}
	if err := json.NewDecoder(listOrg2Rec.Body).Decode(&listedOrg2); err != nil {
		t.Fatalf("decode list org2: %v", err)
	}
	if len(listedOrg2.Approvals) != 0 {
		t.Fatalf("org2 saw org1 approvals: %+v", listedOrg2.Approvals)
	}

	crossList := httptest.NewRequest(http.MethodGet, "/api/approvals?tenant_id=org-2", nil)
	crossList.Header.Set("Authorization", "Bearer "+adminOrg1)
	crossListRec := httptest.NewRecorder()
	handler.ServeHTTP(crossListRec, crossList)
	if crossListRec.Code != http.StatusForbidden {
		t.Fatalf("cross list status = %d body = %s", crossListRec.Code, crossListRec.Body.String())
	}

	crossApprove := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	crossApprove.Header.Set("Authorization", "Bearer "+adminOrg2)
	crossApproveRec := httptest.NewRecorder()
	handler.ServeHTTP(crossApproveRec, crossApprove)
	if crossApproveRec.Code != http.StatusNotFound {
		t.Fatalf("cross approve status = %d body = %s", crossApproveRec.Code, crossApproveRec.Body.String())
	}

	approveReq := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/approve", created.ID), nil)
	approveReq.Header.Set("Authorization", "Bearer "+adminOrg1)
	approveRec := httptest.NewRecorder()
	handler.ServeHTTP(approveRec, approveReq)
	if approveRec.Code != http.StatusOK {
		t.Fatalf("approve status = %d body = %s", approveRec.Code, approveRec.Body.String())
	}
	allowedOrg1, err := enforcer.EnforceWithTenant("tenant-user", "tenant-data-001", "data", "read", "tenant-owner", "org-1")
	if err != nil {
		t.Fatalf("enforce org1: %v", err)
	}
	if !allowedOrg1.Allow {
		t.Fatalf("org1 decision = %+v", allowedOrg1)
	}
	allowedOrg2, err := enforcer.EnforceWithTenant("tenant-user", "tenant-data-001", "data", "read", "tenant-owner", "org-2")
	if err != nil {
		t.Fatalf("enforce org2: %v", err)
	}
	if allowedOrg2.Allow {
		t.Fatalf("org2 decision = %+v", allowedOrg2)
	}
}

func TestDuplicateApprovedPermissionRemainsUntilLastApprovalIsRevoked(t *testing.T) {
	db := openApprovalsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	handler := NewHandler(db, jwt, enforcer, audit.NewWriter(db))
	adminToken := issueApprovalTestToken(t, jwt)

	create := func() int64 {
		t.Helper()
		req := httptest.NewRequest(http.MethodPost, "/api/approvals", bytes.NewBufferString(`{
			"approval_type":"permission_grant",
			"subject":"shared-user",
			"object":"shared-data",
			"resource_type":"data",
			"action":"read",
			"owner_user_id":"shared-owner"
		}`))
		req.Header.Set("Authorization", "Bearer "+adminToken)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("create status=%d body=%s", rec.Code, rec.Body.String())
		}
		var body struct {
			ID int64 `json:"id"`
		}
		if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
			t.Fatalf("decode create: %v", err)
		}
		return body.ID
	}
	handle := func(id int64, action string) {
		t.Helper()
		req := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/approvals/%d/%s", id, action), nil)
		req.Header.Set("Authorization", "Bearer "+adminToken)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("%s approval %d status=%d body=%s", action, id, rec.Code, rec.Body.String())
		}
	}

	firstID := create()
	secondID := create()
	handle(firstID, "approve")
	handle(secondID, "approve")

	policyID := "shared-user:shared-data:data:read:org-1:allow"
	var policyCount int
	if err := db.QueryRow("SELECT COUNT(*) FROM runtime_policies WHERE policy_id=?", policyID).Scan(&policyCount); err != nil {
		t.Fatalf("count shared policy: %v", err)
	}
	if policyCount != 1 {
		t.Fatalf("shared policy count=%d", policyCount)
	}

	handle(firstID, "revoke")
	var replacementID int64
	if err := db.QueryRow("SELECT approval_id FROM runtime_policies WHERE policy_id=?", policyID).Scan(&replacementID); err != nil {
		t.Fatalf("read replacement approval: %v", err)
	}
	if replacementID != secondID {
		t.Fatalf("replacement approval_id=%d want=%d", replacementID, secondID)
	}
	allowed, err := enforcer.EnforceWithTenant("shared-user", "shared-data", "data", "read", "shared-owner", "org-1")
	if err != nil {
		t.Fatalf("enforce shared policy after first revoke: %v", err)
	}
	if !allowed.Allow {
		t.Fatalf("shared policy removed while another approval remained: %+v", allowed)
	}

	handle(secondID, "revoke")
	if err := db.QueryRow("SELECT COUNT(*) FROM runtime_policies WHERE policy_id=?", policyID).Scan(&policyCount); err != nil {
		t.Fatalf("count final shared policy: %v", err)
	}
	if policyCount != 0 {
		t.Fatalf("shared policy remained after final revoke: %d", policyCount)
	}
	denied, err := enforcer.EnforceWithTenant("shared-user", "shared-data", "data", "read", "shared-owner", "org-1")
	if err != nil {
		t.Fatalf("enforce shared policy after final revoke: %v", err)
	}
	if denied.Allow {
		t.Fatalf("shared policy still allowed after final revoke: %+v", denied)
	}
}

func openApprovalsTestDB(t *testing.T) *sql.DB {
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
		t.Fatalf("ensure schema: %v", err)
	}
	return db
}

func issueApprovalTestToken(t *testing.T, jwt *auth.JWTManager) string {
	t.Helper()
	return issueApprovalTestOrgToken(t, jwt, "approval-admin", "org-1", []string{"hanhe_admin"})
}

func issueApprovalTestUserToken(t *testing.T, jwt *auth.JWTManager, userID string) string {
	t.Helper()
	return issueApprovalTestOrgToken(t, jwt, userID, "org-1", []string{"staff"})
}

func issueApprovalTestOrgToken(t *testing.T, jwt *auth.JWTManager, userID, orgID string, roles []string) string {
	t.Helper()
	token, err := jwt.Issue(userID, orgID, roles)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	return token
}
