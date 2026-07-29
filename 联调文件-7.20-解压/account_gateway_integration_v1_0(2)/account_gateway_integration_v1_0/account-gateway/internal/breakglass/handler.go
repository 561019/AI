package breakglass

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"io"
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

type enableRequest struct {
	Reason           string `json:"reason"`
	TicketID         string `json:"ticket_id"`
	ExpiresInMinutes int    `json:"expires_in_minutes"`
}

func NewHandler(db *sql.DB, jwt *auth.JWTManager, audit *audit.Writer) *Handler {
	return &Handler{db: db, jwt: jwt, audit: audit}
}

func AuditMiddleware(db *sql.DB, jwt *auth.JWTManager, auditWriter *audit.Writer, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if isBreakglassManagementPath(r.URL.Path) {
			next.ServeHTTP(w, r)
			return
		}

		claims, err := jwt.ValidateBearer(r.Header.Get("Authorization"))
		if err == nil && claims.IsBreakglass {
			active, checkErr := IsBreakglassActive(db)
			if checkErr != nil || !active {
				writeError(w, http.StatusForbidden, "breakglass_inactive")
				return
			}
			logBreakglassAccess(auditWriter, audit.WithSpan(r.Context(), r.Header), claims, r.Header)
		}
		next.ServeHTTP(w, r)
	})
}

func isBreakglassManagementPath(path string) bool {
	switch strings.TrimRight(path, "/") {
	case "/api/breakglass", "/api/breakglass/enable", "/api/breakglass/approve", "/api/breakglass/disable", "/api/breakglass/status", "/api/breakglass/report":
		return true
	default:
		return false
	}
}

func IsBreakglassActive(db *sql.DB) (bool, error) {
	var enabled int
	var expiresAt sql.NullString
	err := db.QueryRow("SELECT enabled, expires_at FROM breakglass_state WHERE id=1").Scan(&enabled, &expiresAt)
	if err == sql.ErrNoRows {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if enabled != 1 {
		return false, nil
	}
	if !expiresAt.Valid || expiresAt.String == "" {
		return true, nil
	}

	parsed, err := time.Parse(time.RFC3339, expiresAt.String)
	if err != nil {
		return false, nil
	}
	return time.Now().UTC().Before(parsed), nil
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodPost:
		if strings.HasSuffix(r.URL.Path, "/enable") {
			h.enable(w, r)
			return
		}
		if strings.HasSuffix(r.URL.Path, "/approve") {
			h.approve(w, r)
			return
		}
		if strings.HasSuffix(r.URL.Path, "/disable") {
			h.disable(w, r)
			return
		}
		w.WriteHeader(http.StatusNotFound)
	case http.MethodGet:
		if strings.HasSuffix(r.URL.Path, "/status") || r.URL.Path == "/api/breakglass" {
			h.status(w, r)
			return
		}
		if strings.HasSuffix(r.URL.Path, "/report") {
			h.report(w, r)
			return
		}
		w.WriteHeader(http.StatusNotFound)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}

}

func (h *Handler) enable(w http.ResponseWriter, r *http.Request) {
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}
	if !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "admin_only")
		return
	}
	if claims.IsBreakglass {
		writeError(w, http.StatusForbidden, "breakglass_cannot_self_enable")
		return
	}

	var req enableRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil && !errors.Is(err, io.EOF) {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	req.Reason = strings.TrimSpace(req.Reason)
	req.TicketID = strings.TrimSpace(req.TicketID)

	ttl := breakglassTTL()
	if req.ExpiresInMinutes > 0 {
		ttl = time.Duration(req.ExpiresInMinutes) * time.Minute
	}
	expiresAt := time.Now().UTC().Add(ttl)
	token, err := h.jwt.IssueBreakglassWithTTL("breakglass", claims.OrgID, []string{"hanhe_admin"}, ttl)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "jwt_issue_failed")
		return
	}

	encrypted, err := crypto.Encrypt(token, encryptionKey())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "encryption_failed")
		return
	}

	activatedAt := time.Now().UTC().Format(time.RFC3339)
	expiresAtString := expiresAt.Format(time.RFC3339)
	if breakglassApprovalRequired() {
		requestedAt := time.Now().UTC().Format(time.RFC3339)
		if _, err := h.db.Exec(
			`INSERT INTO breakglass_state (id, enabled, credential_jwt, activated_at, expires_at, reason, ticket_id, activated_by, approval_required, requested_by, requested_at, approved_by, approved_at)
			 VALUES (1, 0, ?, NULL, ?, ?, ?, NULL, 1, ?, ?, NULL, NULL)
			 ON CONFLICT(id) DO UPDATE SET enabled=0, credential_jwt=?, activated_at=NULL, expires_at=?, reason=?, ticket_id=?, activated_by=NULL, approval_required=1, requested_by=?, requested_at=?, approved_by=NULL, approved_at=NULL`,
			encrypted, expiresAtString, req.Reason, req.TicketID, claims.UserID, requestedAt,
			encrypted, expiresAtString, req.Reason, req.TicketID, claims.UserID, requestedAt,
		); err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		h.log(r, "breakglass.enable_requested", claims, policy.Decision{Allow: true, PolicyID: "breakglass_enable_requested"}, "breakglass_enable_requested")
		writeJSON(w, http.StatusAccepted, map[string]interface{}{
			"enabled":           false,
			"approval_required": true,
			"status":            "pending_approval",
			"expires_at":        expiresAtString,
			"reason":            req.Reason,
			"ticket_id":         req.TicketID,
			"requested_by":      claims.UserID,
		})
		return
	}
	if _, err := h.db.Exec(
		`INSERT INTO breakglass_state (id, enabled, credential_jwt, activated_at, expires_at, reason, ticket_id, activated_by, approval_required, requested_by, requested_at, approved_by, approved_at)
		 VALUES (1, 1, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL, NULL)
		 ON CONFLICT(id) DO UPDATE SET enabled=1, credential_jwt=?, activated_at=?, expires_at=?, reason=?, ticket_id=?, activated_by=?, approval_required=0, requested_by=NULL, requested_at=NULL, approved_by=NULL, approved_at=NULL`,
		encrypted, activatedAt, expiresAtString, req.Reason, req.TicketID, claims.UserID,
		encrypted, activatedAt, expiresAtString, req.Reason, req.TicketID, claims.UserID,
	); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.log(r, "breakglass.enable", claims, policy.Decision{Allow: true, PolicyID: "breakglass_enable"}, "breakglass_enable")

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"enabled":      true,
		"expires_at":   expiresAtString,
		"reason":       req.Reason,
		"ticket_id":    req.TicketID,
		"activated_by": claims.UserID,
		"token":        token,
	})
}

func (h *Handler) approve(w http.ResponseWriter, r *http.Request) {
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}
	if !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "admin_only")
		return
	}
	if claims.IsBreakglass {
		writeError(w, http.StatusForbidden, "breakglass_cannot_self_enable")
		return
	}

	var encrypted string
	var expiresAt string
	var reason sql.NullString
	var ticketID sql.NullString
	var requestedBy sql.NullString
	err = h.db.QueryRow(`
		SELECT COALESCE(credential_jwt, ''), COALESCE(expires_at, ''), reason, ticket_id, requested_by
		FROM breakglass_state
		WHERE id=1 AND enabled=0 AND approval_required=1
	`).Scan(&encrypted, &expiresAt, &reason, &ticketID, &requestedBy)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "breakglass_request_not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if requestedBy.Valid && requestedBy.String == claims.UserID {
		writeError(w, http.StatusForbidden, "breakglass_approval_requires_second_admin")
		return
	}
	if encrypted == "" || expiresAt == "" {
		writeError(w, http.StatusConflict, "breakglass_request_invalid")
		return
	}
	if parsed, err := time.Parse(time.RFC3339, expiresAt); err != nil || !time.Now().UTC().Before(parsed) {
		writeError(w, http.StatusConflict, "breakglass_request_expired")
		return
	}
	token, err := crypto.Decrypt(encrypted, encryptionKey())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "decryption_failed")
		return
	}
	activatedAt := time.Now().UTC().Format(time.RFC3339)
	approvedAt := activatedAt
	if _, err := h.db.Exec(`
		UPDATE breakglass_state
		SET enabled=1, activated_at=?, activated_by=?, approved_by=?, approved_at=?
		WHERE id=1
	`, activatedAt, requestedBy.String, claims.UserID, approvedAt); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.log(r, "breakglass.approve", claims, policy.Decision{Allow: true, PolicyID: "breakglass_approve"}, "breakglass_approve")
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"enabled":      true,
		"expires_at":   expiresAt,
		"reason":       nullableStringValue(reason),
		"ticket_id":    nullableStringValue(ticketID),
		"activated_by": nullableStringValue(requestedBy),
		"approved_by":  claims.UserID,
		"token":        token,
	})
}

func (h *Handler) disable(w http.ResponseWriter, r *http.Request) {
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}
	if !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "admin_only")
		return
	}
	if claims.IsBreakglass {
		writeError(w, http.StatusForbidden, "breakglass_cannot_self_disable")
		return
	}

	if _, err := h.db.Exec("UPDATE breakglass_state SET enabled=0, credential_jwt=NULL, approval_required=0, requested_by=NULL, requested_at=NULL, approved_by=NULL, approved_at=NULL WHERE id=1"); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.log(r, "breakglass.disable", claims, policy.Decision{Allow: true, PolicyID: "breakglass_disable"}, "breakglass_disable")

	writeJSON(w, http.StatusOK, map[string]bool{"enabled": false})
}

func (h *Handler) status(w http.ResponseWriter, _ *http.Request) {
	isEnabled, err := IsBreakglassActive(h.db)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}

	status := map[string]interface{}{"enabled": isEnabled}
	var requestedBy, requestedAt sql.NullString
	var approvalRequired int
	err = h.db.QueryRow("SELECT COALESCE(approval_required, 0), requested_by, requested_at FROM breakglass_state WHERE id=1").Scan(&approvalRequired, &requestedBy, &requestedAt)
	if err != nil && err != sql.ErrNoRows {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if !isEnabled && approvalRequired == 1 {
		status["approval_required"] = true
		status["status"] = "pending_approval"
		if requestedBy.Valid {
			status["requested_by"] = requestedBy.String
		}
		if requestedAt.Valid {
			status["requested_at"] = requestedAt.String
		}
	}
	writeJSON(w, http.StatusOK, status)
}

func (h *Handler) report(w http.ResponseWriter, r *http.Request) {
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}
	if !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "admin_only")
		return
	}
	if claims.IsBreakglass {
		writeError(w, http.StatusForbidden, "breakglass_cannot_self_review")
		return
	}
	if h.audit != nil && !h.audit.Flush(2*time.Second) {
		writeError(w, http.StatusServiceUnavailable, "audit_flush_timeout")
		return
	}

	active, err := IsBreakglassActive(h.db)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}

	state, err := h.breakglassState(active)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	accessCount, lastAccessAt, err := h.breakglassAccessSummary(claims.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	eventCounts, err := h.breakglassEventCounts(claims.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}

	h.log(r, "breakglass.report", claims, policy.Decision{Allow: true, PolicyID: "breakglass_report"}, "breakglass_report")
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"enabled":        active,
		"status":         state["status"],
		"state":          state,
		"access_count":   accessCount,
		"last_access_at": lastAccessAt,
		"event_counts":   eventCounts,
		"reviewed_by":    claims.UserID,
	})
}

func (h *Handler) breakglassState(active bool) (map[string]interface{}, error) {
	state := map[string]interface{}{
		"enabled":           active,
		"status":            "disabled",
		"approval_required": false,
		"reason":            "",
		"ticket_id":         "",
		"activated_by":      "",
		"activated_at":      "",
		"expires_at":        "",
		"requested_by":      "",
		"requested_at":      "",
		"approved_by":       "",
		"approved_at":       "",
	}

	var enabled int
	var approvalRequired int
	var activatedAt, expiresAt, reason, ticketID, activatedBy, requestedBy, requestedAt, approvedBy, approvedAt sql.NullString
	err := h.db.QueryRow(`
		SELECT enabled, activated_at, expires_at, reason, ticket_id, activated_by,
		       COALESCE(approval_required, 0), requested_by, requested_at, approved_by, approved_at
		FROM breakglass_state
		WHERE id=1
	`).Scan(&enabled, &activatedAt, &expiresAt, &reason, &ticketID, &activatedBy, &approvalRequired, &requestedBy, &requestedAt, &approvedBy, &approvedAt)
	if err == sql.ErrNoRows {
		return state, nil
	}
	if err != nil {
		return nil, err
	}

	state["reason"] = nullableStringValue(reason)
	state["ticket_id"] = nullableStringValue(ticketID)
	state["activated_by"] = nullableStringValue(activatedBy)
	state["activated_at"] = nullableStringValue(activatedAt)
	state["expires_at"] = nullableStringValue(expiresAt)
	state["requested_by"] = nullableStringValue(requestedBy)
	state["requested_at"] = nullableStringValue(requestedAt)
	state["approved_by"] = nullableStringValue(approvedBy)
	state["approved_at"] = nullableStringValue(approvedAt)
	state["approval_required"] = approvalRequired == 1

	switch {
	case active:
		state["status"] = "active"
	case enabled == 1:
		state["status"] = "expired"
	case approvalRequired == 1 && requestedBy.Valid:
		state["status"] = "pending_approval"
	default:
		state["status"] = "disabled"
	}
	return state, nil
}

func (h *Handler) breakglassAccessSummary(tenantID string) (int, string, error) {
	var count int
	var lastAccessAt sql.NullString
	err := h.db.QueryRow(`
		SELECT COUNT(*), MAX(ts)
		FROM audit_logs
		WHERE action_type='breakglass.access' AND instr(context_snapshot, ?) > 0
	`, tenantContextFragment(tenantID)).Scan(&count, &lastAccessAt)
	if err != nil {
		return 0, "", err
	}
	return count, nullableStringValue(lastAccessAt), nil
}

func (h *Handler) breakglassEventCounts(tenantID string) (map[string]int, error) {
	counts := map[string]int{
		"breakglass.enable":           0,
		"breakglass.enable_requested": 0,
		"breakglass.approve":          0,
		"breakglass.disable":          0,
		"breakglass.access":           0,
		"breakglass.report":           0,
	}
	rows, err := h.db.Query(`
		SELECT action_type, COUNT(*)
		FROM audit_logs
		WHERE action_type IN (
			'breakglass.enable',
			'breakglass.enable_requested',
			'breakglass.approve',
			'breakglass.disable',
			'breakglass.access',
			'breakglass.report'
		)
		AND instr(context_snapshot, ?) > 0
		GROUP BY action_type
	`, tenantContextFragment(tenantID))
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	for rows.Next() {
		var actionType string
		var count int
		if err := rows.Scan(&actionType, &count); err != nil {
			return nil, err
		}
		counts[actionType] = count
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return counts, nil
}

func (h *Handler) LogBreakglassAccess(ctx context.Context, claims auth.Claims, headers http.Header) {
	logBreakglassAccess(h.audit, ctx, claims, headers)
}

func logBreakglassAccess(auditWriter *audit.Writer, ctx context.Context, claims auth.Claims, headers http.Header) {
	if auditWriter == nil {
		return
	}
	auditHeaders := headers.Clone()
	if strings.TrimSpace(auditHeaders.Get("X-Tenant-ID")) == "" {
		auditHeaders.Set("X-Tenant-ID", claims.OrgID)
	}
	_ = auditWriter.LogAction(ctx, "breakglass.access", claims.UserID, "breakglass", "emergency", policy.Decision{Allow: true, PolicyID: "breakglass_emergency"}, "breakglass_emergency", auditHeaders)
}

func isAdmin(claims auth.Claims) bool {
	for _, role := range claims.RoleList {
		if role == "hanhe_admin" {
			return true
		}
	}
	return false
}

func breakglassTTL() time.Duration {
	ttlStr := os.Getenv("BREAKGLASS_TTL")
	if ttlStr == "" {
		return time.Hour
	}
	minutes, err := strconv.Atoi(ttlStr)
	if err != nil || minutes <= 0 {
		return time.Hour
	}
	return time.Duration(minutes) * time.Minute
}

func breakglassApprovalRequired() bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv("BREAKGLASS_REQUIRE_APPROVAL")))
	return value == "1" || value == "true" || value == "yes"
}

func nullableStringValue(value sql.NullString) string {
	if value.Valid {
		return value.String
	}
	return ""
}

func (h *Handler) log(r *http.Request, actionType string, claims auth.Claims, decision policy.Decision, policyID string) {
	if h.audit == nil {
		return
	}
	headers := r.Header.Clone()
	if strings.TrimSpace(headers.Get("X-Tenant-ID")) == "" {
		headers.Set("X-Tenant-ID", claims.OrgID)
	}
	if err := h.audit.LogAction(audit.WithSpan(r.Context(), headers), actionType, claims.UserID, "breakglass", "emergency", decision, policyID, headers); err != nil {
		log.Printf("%s audit failed: %v", actionType, err)
	}
}

func tenantContextFragment(tenantID string) string {
	encoded, _ := json.Marshal(map[string]string{"x_tenant_id": strings.TrimSpace(tenantID)})
	return strings.TrimSuffix(strings.TrimPrefix(string(encoded), "{"), "}")
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
