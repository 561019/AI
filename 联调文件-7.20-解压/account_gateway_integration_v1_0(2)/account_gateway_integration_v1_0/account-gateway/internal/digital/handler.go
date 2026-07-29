package digital

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
	db    *sql.DB
	jwt   *auth.JWTManager
	audit *audit.Writer
}

type DigitalEmployee struct {
	Name          string   `json:"name"`
	ParentUserID  string   `json:"parent_user_id"`
	TenantID      string   `json:"tenant_id,omitempty"`
	Roles         []string `json:"roles"`
	Status        string   `json:"status,omitempty"`
	TokenVersion  int      `json:"token_version,omitempty"`
	ExecutionMode string   `json:"execution_mode,omitempty"`
	ExpiresAt     string   `json:"expires_at,omitempty"`
}

type createRequest struct {
	Name             string   `json:"name"`
	ParentUserID     string   `json:"parent_user_id"`
	Roles            []string `json:"roles"`
	ExecutionMode    string   `json:"execution_mode"`
	ExpiresInMinutes int      `json:"expires_in_minutes"`
	ExpiresAt        string   `json:"expires_at"`
}

type executionModeRequest struct {
	ExecutionMode string `json:"execution_mode"`
}

func NewHandler(db *sql.DB, jwt *auth.JWTManager) *Handler {
	return &Handler{db: db, jwt: jwt}
}

func (h *Handler) WithAudit(writer *audit.Writer) *Handler {
	h.audit = writer
	return h
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}

	if claims.IsDigital {
		writeError(w, http.StatusForbidden, "digital_employee_cannot_create_digital")
		return
	}

	switch r.Method {
	case http.MethodPost:
		if r.URL.Path == "/api/digital-employees" {
			h.create(w, r, claims)
			return
		}
		if strings.HasSuffix(r.URL.Path, "/rotate-token") {
			h.rotateToken(w, r, claims)
			return
		}
		if strings.HasSuffix(r.URL.Path, "/disable") {
			h.disable(w, r, claims)
			return
		}
		if strings.HasSuffix(r.URL.Path, "/execution-mode") {
			h.setExecutionMode(w, r, claims)
			return
		}
		w.WriteHeader(http.StatusNotFound)
	case http.MethodGet:
		if strings.Count(r.URL.Path, "/") <= 2 {
			h.list(w, r, claims)
		} else {
			h.get(w, r, claims)
		}
	case http.MethodDelete:
		h.delete(w, r, claims)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	var req createRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "missing_name")
		return
	}
	if req.ParentUserID == "" {
		req.ParentUserID = claims.UserID
	}
	if req.ParentUserID != claims.UserID && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "unauthorized")
		return
	}
	req.Roles = normalizeRoles(req.Roles)
	req.ExecutionMode = normalizeExecutionMode(req.ExecutionMode)
	if !validExecutionMode(req.ExecutionMode) {
		writeError(w, http.StatusBadRequest, "invalid_execution_mode")
		return
	}
	expiresAt, ok := digitalExpiresAt(req.ExpiresInMinutes, req.ExpiresAt)
	if !ok {
		writeError(w, http.StatusBadRequest, "invalid_expires_at")
		return
	}

	rolesJSON, err := json.Marshal(req.Roles)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_roles")
		return
	}

	de := DigitalEmployee{
		Name:          req.Name,
		ParentUserID:  req.ParentUserID,
		TenantID:      claims.OrgID,
		Roles:         req.Roles,
		ExecutionMode: req.ExecutionMode,
		ExpiresAt:     expiresAt,
	}
	token, err := h.jwt.IssueDigitalWithVersion(req.Name, claims.OrgID, req.Roles, req.ParentUserID, 1)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "jwt_issue_failed")
		return
	}
	_, err = h.db.Exec(
		"INSERT INTO digital_employees (name, parent_user_id, roles, created_at, status, token_version, execution_mode, tenant_id, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
		de.Name, de.ParentUserID, string(rolesJSON), time.Now().UTC().Format(time.RFC3339), "active", 1, req.ExecutionMode, de.TenantID, de.ExpiresAt,
	)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}

	h.log(r, claims, "digital_employees.create", de.Name, "digital_employee_create")
	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"name":           de.Name,
		"parent_user_id": de.ParentUserID,
		"tenant_id":      de.TenantID,
		"roles":          de.Roles,
		"status":         "active",
		"token_version":  1,
		"execution_mode": req.ExecutionMode,
		"expires_at":     expiresAt,
		"token":          token,
	})
}

func (h *Handler) list(w http.ResponseWriter, _ *http.Request, claims auth.Claims) {
	var rows *sql.Rows
	var err error
	if isAdmin(claims) {
		rows, err = h.db.Query("SELECT name, parent_user_id, COALESCE(tenant_id, ''), roles, status, token_version, execution_mode, COALESCE(expires_at, '') FROM digital_employees WHERE tenant_id = ?", claims.OrgID)
	} else {
		rows, err = h.db.Query("SELECT name, parent_user_id, COALESCE(tenant_id, ''), roles, status, token_version, execution_mode, COALESCE(expires_at, '') FROM digital_employees WHERE parent_user_id = ? AND tenant_id = ?", claims.UserID, claims.OrgID)
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	defer rows.Close()

	result := make([]DigitalEmployee, 0)
	for rows.Next() {
		de, err := scanDigitalEmployee(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		result = append(result, de)
	}
	if err := rows.Err(); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"digital_employees": result})
}

func (h *Handler) get(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	name := strings.TrimPrefix(r.URL.Path, "/api/digital-employees/")
	name = strings.TrimSpace(name)
	de, err := h.getByName(name)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if !sameTenant(de.TenantID, claims.OrgID) {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if de.ParentUserID != claims.UserID && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "unauthorized")
		return
	}
	writeJSON(w, http.StatusOK, de)
}

func (h *Handler) delete(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	name := strings.TrimPrefix(r.URL.Path, "/api/digital-employees/")
	name = strings.TrimSpace(name)
	de, err := h.getByName(name)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if !sameTenant(de.TenantID, claims.OrgID) {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if de.ParentUserID != claims.UserID && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "unauthorized")
		return
	}
	if _, err := h.db.Exec("DELETE FROM digital_employees WHERE name = ? AND tenant_id = ?", name, claims.OrgID); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.log(r, claims, "digital_employees.delete", name, "digital_employee_delete")
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) disable(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	name := digitalNameFromActionPath(r.URL.Path, "/disable")
	de, err := h.getByName(name)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if !sameTenant(de.TenantID, claims.OrgID) {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if de.ParentUserID != claims.UserID && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "unauthorized")
		return
	}
	if _, err := h.db.Exec("UPDATE digital_employees SET status='disabled', disabled_at=? WHERE name=? AND tenant_id = ?", time.Now().UTC().Format(time.RFC3339), name, claims.OrgID); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.log(r, claims, "digital_employees.disable", name, "digital_employee_disable")
	writeJSON(w, http.StatusOK, map[string]interface{}{"name": name, "status": "disabled"})
}

func (h *Handler) setExecutionMode(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	name := digitalNameFromActionPath(r.URL.Path, "/execution-mode")
	de, err := h.getByName(name)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if !sameTenant(de.TenantID, claims.OrgID) {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if de.ParentUserID != claims.UserID && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "unauthorized")
		return
	}
	var req executionModeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	req.ExecutionMode = normalizeExecutionMode(req.ExecutionMode)
	if !validExecutionMode(req.ExecutionMode) {
		writeError(w, http.StatusBadRequest, "invalid_execution_mode")
		return
	}
	if _, err := h.db.Exec("UPDATE digital_employees SET execution_mode=? WHERE name=? AND tenant_id = ?", req.ExecutionMode, name, claims.OrgID); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.log(r, claims, "digital_employees.execution_mode", name, "digital_employee_execution_mode:"+req.ExecutionMode)
	writeJSON(w, http.StatusOK, map[string]interface{}{"name": name, "execution_mode": req.ExecutionMode})
}

func (h *Handler) rotateToken(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	name := digitalNameFromActionPath(r.URL.Path, "/rotate-token")
	de, err := h.getByName(name)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if !sameTenant(de.TenantID, claims.OrgID) {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if de.ParentUserID != claims.UserID && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "unauthorized")
		return
	}
	if de.Status != "" && de.Status != "active" {
		writeError(w, http.StatusConflict, "digital_employee_disabled")
		return
	}
	if digitalExpired(de.ExpiresAt, time.Now().UTC()) {
		writeError(w, http.StatusConflict, "digital_employee_expired")
		return
	}
	nextVersion := de.TokenVersion + 1
	if nextVersion <= 1 {
		nextVersion = 2
	}
	token, err := h.jwt.IssueDigitalWithVersion(de.Name, claims.OrgID, de.Roles, de.ParentUserID, nextVersion)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "jwt_issue_failed")
		return
	}
	if _, err := h.db.Exec("UPDATE digital_employees SET token_version=? WHERE name=? AND tenant_id = ?", nextVersion, name, claims.OrgID); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.log(r, claims, "digital_employees.rotate_token", name, "digital_employee_token_version:"+strconv.Itoa(nextVersion))
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"name":          de.Name,
		"token_version": nextVersion,
		"token":         token,
	})
}

type digitalEmployeeScanner interface {
	Scan(dest ...interface{}) error
}

func (h *Handler) getByName(name string) (DigitalEmployee, error) {
	return scanDigitalEmployee(h.db.QueryRow("SELECT name, parent_user_id, COALESCE(tenant_id, ''), roles, status, token_version, execution_mode, COALESCE(expires_at, '') FROM digital_employees WHERE name = ?", name))
}

func scanDigitalEmployee(scanner digitalEmployeeScanner) (DigitalEmployee, error) {
	var de DigitalEmployee
	var rolesJSON string
	if err := scanner.Scan(&de.Name, &de.ParentUserID, &de.TenantID, &rolesJSON, &de.Status, &de.TokenVersion, &de.ExecutionMode, &de.ExpiresAt); err != nil {
		return de, err
	}
	if err := json.Unmarshal([]byte(rolesJSON), &de.Roles); err != nil {
		return de, err
	}
	de.ExecutionMode = normalizeExecutionMode(de.ExecutionMode)
	return de, nil
}

func digitalExpiresAt(expiresInMinutes int, expiresAt string) (string, bool) {
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

func digitalExpired(expiresAt string, now time.Time) bool {
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

func sameTenant(recordTenantID, claimsOrgID string) bool {
	recordTenantID = strings.TrimSpace(recordTenantID)
	claimsOrgID = strings.TrimSpace(claimsOrgID)
	return recordTenantID != "" && recordTenantID == claimsOrgID
}

func digitalNameFromActionPath(path, suffix string) string {
	name := strings.TrimPrefix(path, "/api/digital-employees/")
	name = strings.TrimSuffix(name, suffix)
	return strings.Trim(name, "/ ")
}

func isAdmin(claims auth.Claims) bool {
	for _, role := range claims.RoleList {
		if role == "hanhe_admin" {
			return true
		}
	}
	return false
}

func normalizeExecutionMode(mode string) string {
	mode = strings.TrimSpace(mode)
	if mode == "" {
		return "auto"
	}
	return mode
}

func validExecutionMode(mode string) bool {
	switch mode {
	case "auto", "require_confirmation", "scope_reject":
		return true
	default:
		return false
	}
}

func normalizeRoles(roles []string) []string {
	result := make([]string, 0, len(roles))
	seen := make(map[string]struct{})
	for _, role := range roles {
		role = strings.TrimSpace(role)
		if role == "" {
			continue
		}
		if _, ok := seen[role]; ok {
			continue
		}
		seen[role] = struct{}{}
		result = append(result, role)
	}
	if len(result) == 0 {
		return []string{"digital_employee"}
	}
	return result
}

func (h *Handler) log(r *http.Request, claims auth.Claims, actionType, resourceID, policyID string) {
	if h.audit == nil {
		return
	}
	headers := r.Header.Clone()
	headers.Set("X-Tenant-ID", claims.OrgID)
	decision := policy.Decision{Allow: true, PolicyID: policyID}
	if err := h.audit.LogAction(audit.WithSpan(r.Context(), headers), actionType, claims.UserID, "digital_employee", resourceID, decision, policyID, headers); err != nil {
		log.Printf("digital employee audit failed action=%s name=%s: %v", actionType, resourceID, err)
	}
}

func writeJSON(w http.ResponseWriter, status int, response interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(response)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
