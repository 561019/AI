package approvals

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/policy"
)

type Handler struct {
	db       *sql.DB
	jwt      *auth.JWTManager
	enforcer *policy.Enforcer
	audit    *audit.Writer
}

type approvalRequest struct {
	ApprovalType   string `json:"approval_type"`
	Subject        string `json:"subject"`
	Object         string `json:"object"`
	ResourceType   string `json:"resource_type"`
	Action         string `json:"action"`
	OwnerUserID    string `json:"owner_user_id"`
	TenantID       string `json:"tenant_id"`
	ApproverUserID string `json:"approver_user_id"`
	TemplateID     string `json:"template_id"`
	CurrentStage   int    `json:"-"`
}

type approvalResponse struct {
	ID             int64  `json:"id"`
	ApprovalType   string `json:"approval_type"`
	Subject        string `json:"subject"`
	Object         string `json:"object"`
	ResourceType   string `json:"resource_type"`
	Action         string `json:"action"`
	OwnerUserID    string `json:"owner_user_id"`
	TenantID       string `json:"tenant_id"`
	ApproverUserID string `json:"approver_user_id,omitempty"`
	TemplateID     string `json:"template_id,omitempty"`
	CurrentStage   int    `json:"current_stage,omitempty"`
	Status         string `json:"status"`
	RequestedBy    string `json:"requested_by"`
	ApprovedBy     string `json:"approved_by,omitempty"`
	CreatedAt      string `json:"created_at"`
	ApprovedAt     string `json:"approved_at,omitempty"`
}

type approvalTemplateRequest struct {
	ID                  string   `json:"id"`
	Name                string   `json:"name"`
	ApprovalType        string   `json:"approval_type"`
	ApproverPositionID  string   `json:"approver_position_id"`
	ApproverPositionIDs []string `json:"approver_position_ids"`
	TenantID            string   `json:"tenant_id"`
}

type approvalTemplate struct {
	ID                  string   `json:"id"`
	Name                string   `json:"name"`
	ApprovalType        string   `json:"approval_type"`
	ApproverPositionID  string   `json:"approver_position_id"`
	ApproverPositionIDs []string `json:"approver_position_ids"`
	TenantID            string   `json:"tenant_id"`
	Active              bool     `json:"active"`
	CreatedBy           string   `json:"created_by"`
	CreatedAt           string   `json:"created_at"`
}

func NewHandler(db *sql.DB, jwt *auth.JWTManager, enforcer *policy.Enforcer, auditWriter *audit.Writer) *Handler {
	return &Handler{db: db, jwt: jwt, enforcer: enforcer, audit: auditWriter}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}

	switch {
	case strings.TrimRight(r.URL.Path, "/") == "/api/approval-templates":
		if !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "admin_only")
			return
		}
		if r.Method == http.MethodGet {
			h.listTemplates(w, r, claims)
			return
		}
		if r.Method == http.MethodPost {
			h.createTemplate(w, r, claims)
			return
		}
		w.WriteHeader(http.StatusMethodNotAllowed)
	case r.Method == http.MethodGet && strings.TrimRight(r.URL.Path, "/") == "/api/approvals":
		if !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "admin_only")
			return
		}
		h.list(w, r, claims)
	case r.Method == http.MethodPost && strings.TrimRight(r.URL.Path, "/") == "/api/approvals":
		if !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "admin_only")
			return
		}
		h.create(w, r, claims)
	case r.Method == http.MethodPost && strings.HasSuffix(strings.TrimRight(r.URL.Path, "/"), "/approve"):
		h.approve(w, r, claims)
	case r.Method == http.MethodPost && strings.HasSuffix(strings.TrimRight(r.URL.Path, "/"), "/reject"):
		h.reject(w, r, claims)
	case r.Method == http.MethodPost && strings.HasSuffix(strings.TrimRight(r.URL.Path, "/"), "/revoke"):
		h.revoke(w, r, claims)
	default:
		w.WriteHeader(http.StatusNotFound)
	}
}

func (h *Handler) list(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	status := strings.TrimSpace(r.URL.Query().Get("status"))
	approvalType := strings.TrimSpace(r.URL.Query().Get("approval_type"))
	tenantID, ok := tenantScope(w, claims, r.URL.Query().Get("tenant_id"))
	if !ok {
		return
	}
	if approvalType != "" && !validApprovalType(approvalType) {
		writeError(w, http.StatusBadRequest, "invalid_approval_type")
		return
	}
	limit := 100
	if raw := strings.TrimSpace(r.URL.Query().Get("limit")); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed <= 0 || parsed > 500 {
			writeError(w, http.StatusBadRequest, "invalid_limit")
			return
		}
		limit = parsed
	}

	query := `
		SELECT id, COALESCE(approval_type, 'permission_grant'), subject, object, resource_type, action, owner_user_id, COALESCE(tenant_id, ''), approver_user_id, COALESCE(template_id, ''), COALESCE(current_stage, 0), status, requested_by, approved_by, created_at, approved_at
		FROM approvals
	`
	args := []interface{}{}
	conditions := []string{"COALESCE(tenant_id, '') = ?"}
	args = append(args, tenantID)
	if status != "" {
		conditions = append(conditions, "status = ?")
		args = append(args, status)
	}
	if approvalType != "" {
		conditions = append(conditions, "approval_type = ?")
		args = append(args, approvalType)
	}
	query += " WHERE " + strings.Join(conditions, " AND ")
	query += " ORDER BY id DESC LIMIT ?"
	args = append(args, limit)

	rows, err := h.db.Query(query, args...)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	defer rows.Close()

	approvals := []approvalResponse{}
	for rows.Next() {
		item, err := scanApproval(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		approvals = append(approvals, item)
	}
	if err := rows.Err(); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"approvals": approvals})
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	var req approvalRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	req = normalize(req)
	if !defaultTenant(w, claims, &req.TenantID) {
		return
	}
	if req.Subject == "" || req.Object == "" || req.ResourceType == "" || req.Action == "" || req.OwnerUserID == "" {
		writeError(w, http.StatusBadRequest, "missing_field")
		return
	}
	if !validApprovalType(req.ApprovalType) {
		writeError(w, http.StatusBadRequest, "invalid_approval_type")
		return
	}
	if !approvalTypeMatches(req) {
		writeError(w, http.StatusBadRequest, "approval_type_mismatch")
		return
	}
	if req.TemplateID != "" {
		template, err := h.templateForTenant(req.TemplateID, req.TenantID)
		if err == sql.ErrNoRows {
			writeError(w, http.StatusNotFound, "approval_template_not_found")
			return
		}
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		if template.ApprovalType != req.ApprovalType {
			writeError(w, http.StatusBadRequest, "approval_template_type_mismatch")
			return
		}
		if err := h.currentTemplateApprover(template, 0, req.TenantID, &req.ApproverUserID); err == sql.ErrNoRows {
			writeError(w, http.StatusConflict, "template_approver_unassigned")
			return
		} else if err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
	}
	now := time.Now().UTC().Format(time.RFC3339)
	result, err := h.db.Exec(`
		INSERT INTO approvals (approval_type, subject, object, resource_type, action, owner_user_id, tenant_id, approver_user_id, template_id, status, requested_by, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
	`, req.ApprovalType, req.Subject, req.Object, req.ResourceType, req.Action, req.OwnerUserID, req.TenantID, nullableString(req.ApproverUserID), nullableString(req.TemplateID), claims.UserID, now)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	id, _ := result.LastInsertId()
	response := map[string]interface{}{"id": id, "status": "pending", "approval_type": req.ApprovalType, "tenant_id": req.TenantID}
	if req.ApproverUserID != "" {
		response["approver_user_id"] = req.ApproverUserID
	}
	if req.TemplateID != "" {
		response["template_id"] = req.TemplateID
	}
	writeJSON(w, http.StatusCreated, response)
}

func (h *Handler) createTemplate(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	var req approvalTemplateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	req.ID = strings.TrimSpace(req.ID)
	req.Name = strings.TrimSpace(req.Name)
	req.ApprovalType = strings.TrimSpace(req.ApprovalType)
	req.ApproverPositionID = strings.TrimSpace(req.ApproverPositionID)
	stages := normalizeTemplateStages(req.ApproverPositionID, req.ApproverPositionIDs)
	if !defaultTenant(w, claims, &req.TenantID) {
		return
	}
	if req.ID == "" || req.Name == "" || len(stages) == 0 || !validApprovalType(req.ApprovalType) {
		writeError(w, http.StatusBadRequest, "missing_or_invalid_field")
		return
	}
	for _, positionID := range stages {
		var positionTenant string
		if err := h.db.QueryRow("SELECT tenant_id FROM positions WHERE id=?", positionID).Scan(&positionTenant); err == sql.ErrNoRows {
			writeError(w, http.StatusNotFound, "approver_position_not_found")
			return
		} else if err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		if positionTenant != req.TenantID {
			writeError(w, http.StatusNotFound, "approver_position_not_found")
			return
		}
	}
	stagesJSON, _ := json.Marshal(stages)
	now := time.Now().UTC().Format(time.RFC3339)
	_, err := h.db.Exec(`INSERT INTO approval_templates (id, name, approval_type, approver_position_id, tenant_id, active, created_by, created_at, stages_json) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)`, req.ID, req.Name, req.ApprovalType, stages[0], req.TenantID, claims.UserID, now, string(stagesJSON))
	if err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "unique") || strings.Contains(strings.ToLower(err.Error()), "primary key") {
			writeError(w, http.StatusConflict, "approval_template_exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.logTemplateAudit(r, claims, req.ID)
	writeJSON(w, http.StatusCreated, approvalTemplate{ID: req.ID, Name: req.Name, ApprovalType: req.ApprovalType, ApproverPositionID: stages[0], ApproverPositionIDs: stages, TenantID: req.TenantID, Active: true, CreatedBy: claims.UserID, CreatedAt: now})
}

func (h *Handler) listTemplates(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	tenantID, ok := tenantScope(w, claims, r.URL.Query().Get("tenant_id"))
	if !ok {
		return
	}
	rows, err := h.db.Query(`SELECT id, name, approval_type, approver_position_id, tenant_id, active, created_by, created_at, COALESCE(stages_json, '[]') FROM approval_templates WHERE tenant_id=? ORDER BY id`, tenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	defer rows.Close()
	templates := []approvalTemplate{}
	for rows.Next() {
		var item approvalTemplate
		var active int
		var stagesJSON string
		if err := rows.Scan(&item.ID, &item.Name, &item.ApprovalType, &item.ApproverPositionID, &item.TenantID, &active, &item.CreatedBy, &item.CreatedAt, &stagesJSON); err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		item.Active = active == 1
		item.ApproverPositionIDs = decodeTemplateStages(stagesJSON, item.ApproverPositionID)
		templates = append(templates, item)
	}
	if err := rows.Err(); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"approval_templates": templates})
}

func (h *Handler) templateForTenant(id, tenantID string) (approvalTemplate, error) {
	var item approvalTemplate
	var active int
	var stagesJSON string
	err := h.db.QueryRow(`SELECT id, name, approval_type, approver_position_id, tenant_id, active, created_by, created_at, COALESCE(stages_json, '[]') FROM approval_templates WHERE id=? AND tenant_id=? AND active=1`, strings.TrimSpace(id), strings.TrimSpace(tenantID)).Scan(&item.ID, &item.Name, &item.ApprovalType, &item.ApproverPositionID, &item.TenantID, &active, &item.CreatedBy, &item.CreatedAt, &stagesJSON)
	if err != nil {
		return approvalTemplate{}, err
	}
	item.Active = active == 1
	item.ApproverPositionIDs = decodeTemplateStages(stagesJSON, item.ApproverPositionID)
	return item, nil
}

func normalizeTemplateStages(first string, stages []string) []string {
	if len(stages) == 0 {
		stages = []string{first}
	}
	result := make([]string, 0, len(stages))
	seen := map[string]struct{}{}
	for _, stage := range stages {
		stage = strings.TrimSpace(stage)
		if stage == "" {
			return nil
		}
		if _, exists := seen[stage]; exists {
			return nil
		}
		seen[stage] = struct{}{}
		result = append(result, stage)
	}
	return result
}

func decodeTemplateStages(raw, fallback string) []string {
	var stages []string
	if json.Unmarshal([]byte(raw), &stages) != nil || len(stages) == 0 {
		return []string{fallback}
	}
	return stages
}

func (h *Handler) currentTemplateApprover(template approvalTemplate, stage int, tenantID string, approver *string) error {
	if stage < 0 || stage >= len(template.ApproverPositionIDs) {
		return sql.ErrNoRows
	}
	return h.db.QueryRow(`SELECT user_id FROM person_position_assignments WHERE position_id=? AND tenant_id=? AND status='active'`, template.ApproverPositionIDs[stage], tenantID).Scan(approver)
}

// advanceTemplateApproval moves a pending approval to its next template
// stage. The final stage is handled by the existing approval state machine.
func (h *Handler) advanceTemplateApproval(id int64, req approvalRequest, status, actorID string) (bool, string, int, string) {
	if status != "pending" {
		return false, "", 0, ""
	}
	template, err := h.templateForTenant(req.TemplateID, req.TenantID)
	if err != nil {
		return false, "", 0, "approval_template_not_found"
	}
	nextStage := req.CurrentStage + 1
	if nextStage >= len(template.ApproverPositionIDs) {
		return false, "", len(template.ApproverPositionIDs), ""
	}
	var nextApprover string
	if err := h.currentTemplateApprover(template, nextStage, req.TenantID, &nextApprover); err == sql.ErrNoRows {
		return false, "", len(template.ApproverPositionIDs), "template_next_approver_unassigned"
	} else if err != nil {
		return false, "", len(template.ApproverPositionIDs), "db_error"
	}
	result, err := h.db.Exec(`UPDATE approvals SET current_stage=?, approver_user_id=?, approved_by=NULL, approved_at=NULL WHERE id=? AND status='pending' AND current_stage=?`, nextStage, nextApprover, id, req.CurrentStage)
	if err != nil {
		return false, "", len(template.ApproverPositionIDs), "db_error"
	}
	affected, err := result.RowsAffected()
	if err != nil || affected != 1 {
		return false, "", len(template.ApproverPositionIDs), "approval_state_conflict"
	}
	return true, nextApprover, len(template.ApproverPositionIDs), ""
}

func (h *Handler) approve(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	id, err := approvalID(r.URL.Path, "/approve")
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_id")
		return
	}
	var req approvalRequest
	var status string
	err = h.db.QueryRow(`
		SELECT COALESCE(approval_type, 'permission_grant'), subject, object, resource_type, action, owner_user_id, COALESCE(tenant_id, ''), COALESCE(approver_user_id, ''), COALESCE(template_id, ''), COALESCE(current_stage, 0), status
		FROM approvals
		WHERE id = ?
	`, id).Scan(&req.ApprovalType, &req.Subject, &req.Object, &req.ResourceType, &req.Action, &req.OwnerUserID, &req.TenantID, &req.ApproverUserID, &req.TemplateID, &req.CurrentStage, &status)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "approval_not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if !sameTenant(claims, req.TenantID) {
		writeError(w, http.StatusNotFound, "approval_not_found")
		return
	}
	if !h.canHandleApproval(claims, req) {
		writeError(w, http.StatusForbidden, "approval_approver_required")
		return
	}
	if status == "rejected" {
		writeError(w, http.StatusConflict, "approval_rejected")
		return
	}
	if status == "revoked" {
		writeError(w, http.StatusConflict, "approval_revoked")
		return
	}
	if status == "approved" {
		if !approvalWritesRuntimePolicy(req.ApprovalType) {
			writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "approved", "approval_type": req.ApprovalType})
			return
		}
		policyItem := runtimePolicyFromApproval(req, id, claims.UserID, time.Now().UTC())
		if code := h.persistAndLoadRuntimePolicy(id, req, claims.UserID, false); code != "" {
			writeError(w, http.StatusInternalServerError, code)
			return
		}
		h.logApprovalAudit(r, claims, policyItem)
		writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "approved", "policy_id": policyItem.PolicyID})
		return
	}
	if req.TemplateID != "" {
		advanced, nextApprover, stageCount, code := h.advanceTemplateApproval(id, req, status, claims.UserID)
		if code != "" {
			writeError(w, http.StatusConflict, code)
			return
		}
		if advanced {
			h.logTemplateStageAudit(r, claims, id, req.CurrentStage)
			writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "pending", "current_stage": req.CurrentStage + 1, "stage_count": stageCount, "approver_user_id": nextApprover})
			return
		}
	}
	if !approvalWritesRuntimePolicy(req.ApprovalType) {
		if code := h.markApproved(id, claims.UserID); code != "" {
			writeError(w, http.StatusInternalServerError, code)
			return
		}
		h.logStateOnlyApprovalAudit(r, claims, id, req.ApprovalType)
		writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "approved", "approval_type": req.ApprovalType})
		return
	}
	policyItem := runtimePolicyFromApproval(req, id, claims.UserID, time.Now().UTC())
	if code := h.persistAndLoadRuntimePolicy(id, req, claims.UserID, true); code != "" {
		writeError(w, http.StatusInternalServerError, code)
		return
	}
	h.logApprovalAudit(r, claims, policyItem)
	writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "approved", "policy_id": policyItem.PolicyID})
}

func (h *Handler) reject(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	id, err := approvalID(r.URL.Path, "/reject")
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_id")
		return
	}
	var status string
	var req approvalRequest
	if err := h.db.QueryRow("SELECT COALESCE(tenant_id, ''), COALESCE(approver_user_id, ''), COALESCE(template_id, ''), COALESCE(current_stage, 0), status FROM approvals WHERE id = ?", id).Scan(&req.TenantID, &req.ApproverUserID, &req.TemplateID, &req.CurrentStage, &status); err != nil {
		if err == sql.ErrNoRows {
			writeError(w, http.StatusNotFound, "approval_not_found")
			return
		}
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if !sameTenant(claims, req.TenantID) {
		writeError(w, http.StatusNotFound, "approval_not_found")
		return
	}
	if !h.canHandleApproval(claims, req) {
		writeError(w, http.StatusForbidden, "approval_approver_required")
		return
	}
	switch status {
	case "approved":
		writeError(w, http.StatusConflict, "approval_already_approved")
		return
	case "rejected":
		writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "rejected"})
		return
	case "revoked":
		writeError(w, http.StatusConflict, "approval_revoked")
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	if _, err := h.db.Exec("UPDATE approvals SET status='rejected', approved_by=?, approved_at=? WHERE id=?", claims.UserID, now, id); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.logRejectAudit(r, claims, id)
	writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "rejected"})
}

func (h *Handler) revoke(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	id, err := approvalID(r.URL.Path, "/revoke")
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_id")
		return
	}
	var req approvalRequest
	var status string
	err = h.db.QueryRow(`
		SELECT COALESCE(approval_type, 'permission_grant'), subject, object, resource_type, action, owner_user_id, COALESCE(tenant_id, ''), COALESCE(approver_user_id, ''), COALESCE(template_id, ''), COALESCE(current_stage, 0), status
		FROM approvals
		WHERE id = ?
	`, id).Scan(&req.ApprovalType, &req.Subject, &req.Object, &req.ResourceType, &req.Action, &req.OwnerUserID, &req.TenantID, &req.ApproverUserID, &req.TemplateID, &req.CurrentStage, &status)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "approval_not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if !sameTenant(claims, req.TenantID) {
		writeError(w, http.StatusNotFound, "approval_not_found")
		return
	}
	if !h.canHandleApproval(claims, req) {
		writeError(w, http.StatusForbidden, "approval_approver_required")
		return
	}
	switch status {
	case "pending":
		writeError(w, http.StatusConflict, "approval_not_approved")
		return
	case "rejected":
		writeError(w, http.StatusConflict, "approval_rejected")
		return
	case "revoked":
		if !approvalWritesRuntimePolicy(req.ApprovalType) {
			writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "revoked", "approval_type": req.ApprovalType})
			return
		}
		policyItem := runtimePolicyFromApproval(req, id, claims.UserID, time.Now().UTC())
		writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "revoked", "policy_id": policyItem.PolicyID})
		return
	}
	if !approvalWritesRuntimePolicy(req.ApprovalType) {
		if code := h.markRevoked(id, claims.UserID); code != "" {
			writeError(w, http.StatusInternalServerError, code)
			return
		}
		h.logStateOnlyRevokeAudit(r, claims, id, req.ApprovalType)
		writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "revoked", "approval_type": req.ApprovalType})
		return
	}
	policyItem := runtimePolicyFromApproval(req, id, claims.UserID, time.Now().UTC())
	if code := h.revokeRuntimePolicy(id, req, claims.UserID); code != "" {
		writeError(w, http.StatusInternalServerError, code)
		return
	}
	h.logRevokeAudit(r, claims, policyItem)
	writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": "revoked", "policy_id": policyItem.PolicyID})
}

func (h *Handler) markApproved(approvalID int64, approvedBy string) string {
	now := time.Now().UTC().Format(time.RFC3339)
	if _, err := h.db.Exec("UPDATE approvals SET status='approved', approved_by=?, approved_at=? WHERE id=?", approvedBy, now, approvalID); err != nil {
		return "db_error"
	}
	return ""
}

func (h *Handler) markRevoked(approvalID int64, revokedBy string) string {
	now := time.Now().UTC().Format(time.RFC3339)
	if _, err := h.db.Exec("UPDATE approvals SET status='revoked', approved_by=?, approved_at=? WHERE id=?", revokedBy, now, approvalID); err != nil {
		return "db_error"
	}
	return ""
}

func (h *Handler) persistAndLoadRuntimePolicy(approvalID int64, req approvalRequest, approvedBy string, updateApproval bool) string {
	now := time.Now().UTC()
	item := runtimePolicyFromApproval(req, approvalID, approvedBy, now)
	tx, err := h.db.Begin()
	if err != nil {
		return "db_error"
	}
	defer tx.Rollback()

	inserted, err := insertRuntimePolicy(tx, item)
	if err != nil {
		return "db_error"
	}
	if updateApproval {
		if _, err := tx.Exec("UPDATE approvals SET status='approved', approved_by=?, approved_at=? WHERE id=?", approvedBy, now.Format(time.RFC3339), approvalID); err != nil {
			return "db_error"
		}
	}
	if err := tx.Commit(); err != nil {
		return "db_error"
	}
	if err := addRuntimePolicy(h.enforcer, item); err != nil {
		h.compensateApprovalPolicyInsert(item, inserted, updateApproval)
		return "policy_error"
	}
	return ""
}

func (h *Handler) revokeRuntimePolicy(approvalID int64, req approvalRequest, revokedBy string) string {
	now := time.Now().UTC()
	item := runtimePolicyFromApproval(req, approvalID, revokedBy, now)
	tx, err := h.db.Begin()
	if err != nil {
		return "db_error"
	}
	defer tx.Rollback()

	if _, err := tx.Exec("UPDATE approvals SET status='revoked', approved_by=?, approved_at=? WHERE id=?", revokedBy, now.Format(time.RFC3339), approvalID); err != nil {
		return "db_error"
	}
	replacementID, err := replacementApprovalID(tx, approvalID, req)
	if err != nil {
		return "db_error"
	}
	if replacementID > 0 {
		result, err := tx.Exec("UPDATE runtime_policies SET approval_id=? WHERE policy_id=?", replacementID, item.PolicyID)
		if err != nil {
			return "db_error"
		}
		affected, err := result.RowsAffected()
		if err != nil {
			return "db_error"
		}
		if affected == 0 {
			item.ApprovalID = replacementID
			if _, err := insertRuntimePolicy(tx, item); err != nil {
				return "db_error"
			}
		}
		if err := tx.Commit(); err != nil {
			return "db_error"
		}
		return ""
	}
	if _, err := tx.Exec("DELETE FROM runtime_policies WHERE policy_id=?", item.PolicyID); err != nil {
		return "db_error"
	}
	if err := tx.Commit(); err != nil {
		return "db_error"
	}
	if err := removeRuntimePolicy(h.enforcer, item); err != nil {
		h.compensateApprovalPolicyRemoval(item)
		return "policy_error"
	}
	return ""
}

func replacementApprovalID(tx *sql.Tx, approvalID int64, req approvalRequest) (int64, error) {
	var replacementID int64
	err := tx.QueryRow(`
		SELECT id
		FROM approvals
		WHERE id<>?
		  AND status='approved'
		  AND approval_type IN ('data_release', 'permission_grant')
		  AND subject=?
		  AND object=?
		  AND resource_type=?
		  AND action=?
		  AND owner_user_id=?
		  AND COALESCE(tenant_id, '')=?
		ORDER BY id
		LIMIT 1
	`, approvalID, req.Subject, req.Object, req.ResourceType, req.Action, req.OwnerUserID, req.TenantID).Scan(&replacementID)
	if err == sql.ErrNoRows {
		return 0, nil
	}
	return replacementID, err
}

func (h *Handler) compensateApprovalPolicyInsert(item runtimePolicy, inserted, updateApproval bool) {
	tx, err := h.db.Begin()
	if err != nil {
		return
	}
	defer tx.Rollback()
	if inserted {
		if _, err := tx.Exec("DELETE FROM runtime_policies WHERE policy_id=? AND approval_id=?", item.PolicyID, item.ApprovalID); err != nil {
			return
		}
	}
	if updateApproval {
		if _, err := tx.Exec("UPDATE approvals SET status='pending', approved_by=NULL, approved_at=NULL WHERE id=?", item.ApprovalID); err != nil {
			return
		}
	}
	_ = tx.Commit()
}

func (h *Handler) compensateApprovalPolicyRemoval(item runtimePolicy) {
	tx, err := h.db.Begin()
	if err != nil {
		return
	}
	defer tx.Rollback()
	if _, err := insertRuntimePolicy(tx, item); err != nil {
		return
	}
	if _, err := tx.Exec("UPDATE approvals SET status='approved' WHERE id=?", item.ApprovalID); err != nil {
		return
	}
	if err := tx.Commit(); err != nil {
		return
	}
	_ = addRuntimePolicy(h.enforcer, item)
}

func (h *Handler) logApprovalAudit(r *http.Request, claims auth.Claims, item runtimePolicy) {
	if h.audit == nil {
		return
	}
	decision := policy.Decision{Allow: true, PolicyID: item.PolicyID}
	headers := approvalAuditHeaders(r, claims)
	if err := h.audit.LogAction(
		audit.WithSpan(r.Context(), headers),
		"approvals.approve",
		claims.UserID,
		"policy",
		item.PolicyID,
		decision,
		item.PolicyID,
		headers,
	); err != nil {
		log.Printf("approvals approve audit failed: %v", err)
	}
}

func (h *Handler) logRejectAudit(r *http.Request, claims auth.Claims, id int64) {
	if h.audit == nil {
		return
	}
	policyID := "approval_rejected:" + strconv.FormatInt(id, 10)
	decision := policy.Decision{Allow: false, PolicyID: policyID}
	headers := approvalAuditHeaders(r, claims)
	if err := h.audit.LogAction(
		audit.WithSpan(r.Context(), headers),
		"approvals.reject",
		claims.UserID,
		"approval",
		strconv.FormatInt(id, 10),
		decision,
		policyID,
		headers,
	); err != nil {
		log.Printf("approvals reject audit failed: %v", err)
	}
}

func (h *Handler) logStateOnlyApprovalAudit(r *http.Request, claims auth.Claims, id int64, approvalType string) {
	if h.audit == nil {
		return
	}
	policyID := "approval:" + approvalType + ":" + strconv.FormatInt(id, 10)
	decision := policy.Decision{Allow: true, PolicyID: policyID}
	headers := approvalAuditHeaders(r, claims)
	if err := h.audit.LogAction(
		audit.WithSpan(r.Context(), headers),
		"approvals.approve",
		claims.UserID,
		"approval",
		strconv.FormatInt(id, 10),
		decision,
		policyID,
		headers,
	); err != nil {
		log.Printf("approvals approve audit failed: %v", err)
	}
}

func (h *Handler) logRevokeAudit(r *http.Request, claims auth.Claims, item runtimePolicy) {
	if h.audit == nil {
		return
	}
	decision := policy.Decision{Allow: false, PolicyID: item.PolicyID}
	headers := approvalAuditHeaders(r, claims)
	if err := h.audit.LogAction(
		audit.WithSpan(r.Context(), headers),
		"approvals.revoke",
		claims.UserID,
		"policy",
		item.PolicyID,
		decision,
		item.PolicyID,
		headers,
	); err != nil {
		log.Printf("approvals revoke audit failed: %v", err)
	}
}

func (h *Handler) logStateOnlyRevokeAudit(r *http.Request, claims auth.Claims, id int64, approvalType string) {
	if h.audit == nil {
		return
	}
	policyID := "approval:" + approvalType + ":" + strconv.FormatInt(id, 10)
	decision := policy.Decision{Allow: false, PolicyID: policyID}
	headers := approvalAuditHeaders(r, claims)
	if err := h.audit.LogAction(
		audit.WithSpan(r.Context(), headers),
		"approvals.revoke",
		claims.UserID,
		"approval",
		strconv.FormatInt(id, 10),
		decision,
		policyID,
		headers,
	); err != nil {
		log.Printf("approvals revoke audit failed: %v", err)
	}
}

func approvalAuditHeaders(r *http.Request, claims auth.Claims) http.Header {
	headers := r.Header.Clone()
	if strings.TrimSpace(headers.Get("X-Tenant-ID")) == "" {
		headers.Set("X-Tenant-ID", claims.OrgID)
	}
	return headers
}

func (h *Handler) logTemplateAudit(r *http.Request, claims auth.Claims, templateID string) {
	if h.audit == nil {
		return
	}
	policyID := "approval_template:" + templateID
	decision := policy.Decision{Allow: true, PolicyID: policyID}
	headers := r.Header.Clone()
	headers.Set("X-Tenant-ID", claims.OrgID)
	if err := h.audit.LogAction(audit.WithSpan(r.Context(), headers), "approval_templates.create", claims.UserID, "approval_template", templateID, decision, policyID, headers); err != nil {
		log.Printf("approval template audit failed: %v", err)
	}
}

func (h *Handler) logTemplateStageAudit(r *http.Request, claims auth.Claims, approvalID int64, completedStage int) {
	if h.audit == nil {
		return
	}
	policyID := "approval_stage:" + strconv.FormatInt(approvalID, 10) + ":" + strconv.Itoa(completedStage)
	decision := policy.Decision{Allow: true, PolicyID: policyID}
	headers := r.Header.Clone()
	headers.Set("X-Tenant-ID", claims.OrgID)
	if err := h.audit.LogAction(audit.WithSpan(r.Context(), headers), "approvals.stage_approve", claims.UserID, "approval", strconv.FormatInt(approvalID, 10), decision, policyID, headers); err != nil {
		log.Printf("approval stage audit failed: %v", err)
	}
}

func normalize(req approvalRequest) approvalRequest {
	req.ApprovalType = strings.TrimSpace(req.ApprovalType)
	req.Subject = strings.TrimSpace(req.Subject)
	req.Object = strings.TrimSpace(req.Object)
	req.ResourceType = strings.TrimSpace(req.ResourceType)
	req.Action = strings.TrimSpace(req.Action)
	req.OwnerUserID = strings.TrimSpace(req.OwnerUserID)
	req.TenantID = strings.TrimSpace(req.TenantID)
	req.ApproverUserID = strings.TrimSpace(req.ApproverUserID)
	req.TemplateID = strings.TrimSpace(req.TemplateID)
	if req.ApprovalType == "" {
		req.ApprovalType = inferApprovalType(req)
	}
	return req
}

func inferApprovalType(req approvalRequest) string {
	if req.ResourceType == "data" && isDataReleaseAction(req.Action) {
		return "data_release"
	}
	return "permission_grant"
}

func validApprovalType(approvalType string) bool {
	switch approvalType {
	case "data_release", "resource_publication", "business_approval", "permission_grant":
		return true
	default:
		return false
	}
}

func approvalTypeMatches(req approvalRequest) bool {
	if req.ApprovalType == "data_release" {
		return req.ResourceType == "data" && isDataReleaseAction(req.Action)
	}
	if req.ApprovalType == "resource_publication" {
		return req.ResourceType == "tool" || req.ResourceType == "skill" || req.ResourceType == "knowledge"
	}
	return true
}

func approvalWritesRuntimePolicy(approvalType string) bool {
	return approvalType == "data_release" || approvalType == "permission_grant"
}

func isDataReleaseAction(action string) bool {
	switch action {
	case "read", "fetch", "use", "export":
		return true
	default:
		return false
	}
}

func nullableString(value string) interface{} {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return strings.TrimSpace(value)
}

func approvalID(path string, suffix string) (int64, error) {
	trimmed := strings.Trim(strings.TrimSuffix(path, suffix), "/")
	parts := strings.Split(trimmed, "/")
	return strconv.ParseInt(parts[len(parts)-1], 10, 64)
}

type approvalScanner interface {
	Scan(dest ...interface{}) error
}

func scanApproval(row approvalScanner) (approvalResponse, error) {
	var item approvalResponse
	var approverUserID, templateID, approvedBy, approvedAt sql.NullString
	err := row.Scan(
		&item.ID,
		&item.ApprovalType,
		&item.Subject,
		&item.Object,
		&item.ResourceType,
		&item.Action,
		&item.OwnerUserID,
		&item.TenantID,
		&approverUserID,
		&templateID,
		&item.CurrentStage,
		&item.Status,
		&item.RequestedBy,
		&approvedBy,
		&item.CreatedAt,
		&approvedAt,
	)
	if approverUserID.Valid {
		item.ApproverUserID = approverUserID.String
	}
	if templateID.Valid {
		item.TemplateID = templateID.String
	}
	if approvedBy.Valid {
		item.ApprovedBy = approvedBy.String
	}
	if approvedAt.Valid {
		item.ApprovedAt = approvedAt.String
	}
	return item, err
}

func policyID(req approvalRequest) string {
	tenantID := normalizeTenant(req.TenantID)
	if tenantID != "*" {
		return strings.Join([]string{req.Subject, req.Object, req.ResourceType, req.Action, tenantID, "allow"}, ":")
	}
	return strings.Join([]string{req.Subject, req.Object, req.ResourceType, req.Action, "allow"}, ":")
}

func isAdmin(claims auth.Claims) bool {
	for _, role := range claims.RoleList {
		if role == "hanhe_admin" {
			return true
		}
	}
	return false
}

func (h *Handler) canHandleApproval(claims auth.Claims, req approvalRequest) bool {
	if !sameTenant(claims, req.TenantID) {
		return false
	}
	if req.TemplateID != "" {
		if claims.IsBreakglass {
			return true
		}
		template, err := h.templateForTenant(req.TemplateID, req.TenantID)
		if err != nil {
			return false
		}
		var currentApprover string
		if err := h.currentTemplateApprover(template, req.CurrentStage, req.TenantID, &currentApprover); err != nil {
			return false
		}
		return currentApprover == claims.UserID
	}
	return isAdmin(claims) || (req.ApproverUserID != "" && req.ApproverUserID == claims.UserID)
}

func tenantScope(w http.ResponseWriter, claims auth.Claims, requested string) (string, bool) {
	requested = strings.TrimSpace(requested)
	orgID := strings.TrimSpace(claims.OrgID)
	if requested == "" {
		return orgID, true
	}
	if claims.IsBreakglass || orgID == "" || requested == orgID {
		return requested, true
	}
	writeError(w, http.StatusForbidden, "tenant_mismatch")
	return "", false
}

func defaultTenant(w http.ResponseWriter, claims auth.Claims, tenantID *string) bool {
	scoped, ok := tenantScope(w, claims, *tenantID)
	if !ok {
		return false
	}
	if strings.TrimSpace(*tenantID) == "" {
		*tenantID = scoped
	}
	return true
}

func sameTenant(claims auth.Claims, tenantID string) bool {
	tenantID = strings.TrimSpace(tenantID)
	orgID := strings.TrimSpace(claims.OrgID)
	return claims.IsBreakglass || tenantID == "" || orgID == "" || tenantID == orgID
}

func normalizeTenant(tenantID string) string {
	tenantID = strings.TrimSpace(tenantID)
	if tenantID == "" {
		return "*"
	}
	return tenantID
}

func writeJSON(w http.ResponseWriter, status int, response interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(response)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
