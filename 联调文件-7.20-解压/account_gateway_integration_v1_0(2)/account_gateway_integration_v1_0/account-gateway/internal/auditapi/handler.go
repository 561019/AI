package auditapi

import (
	"database/sql"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"
)

type Handler struct {
	db     *sql.DB
	jwt    *auth.JWTManager
	writer *audit.Writer
}

const auditReadFlushTimeout = 2 * time.Second

type auditLog struct {
	ID              int64  `json:"id"`
	Timestamp       string `json:"ts"`
	ActorID         string `json:"actor_id"`
	ActionType      string `json:"action_type"`
	ResourceType    string `json:"resource_type"`
	ResourceID      string `json:"resource_id"`
	PolicyDecision  string `json:"policy_decision"`
	PolicyID        string `json:"policy_id,omitempty"`
	ContextSnapshot string `json:"context_snapshot"`
	Version         int    `json:"version"`
}

type auditEventRequest struct {
	ActionType        string            `json:"action_type"`
	ActorID           string            `json:"actor_id"`
	ResourceType      string            `json:"resource_type"`
	ResourceID        string            `json:"resource_id"`
	PolicyDecision    string            `json:"policy_decision"`
	PolicyID          string            `json:"policy_id"`
	Severity          string            `json:"severity"`
	DispositionStatus string            `json:"disposition_status"`
	TicketID          string            `json:"ticket_id"`
	Context           map[string]string `json:"context"`
}

type queryFilters struct {
	Limit          int
	AfterID        int64
	TraceID        string
	ActorID        string
	ActionType     string
	ResourceType   string
	ResourceID     string
	PolicyDecision string
	FromTS         string
	ToTS           string
	Severity       string
	Disposition    string
	TicketID       string
}

func NewHandler(db *sql.DB, jwt *auth.JWTManager) *Handler {
	return &Handler{db: db, jwt: jwt}
}

func (h *Handler) WithWriter(writer *audit.Writer) *Handler {
	h.writer = writer
	return h
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}
	if !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "admin_only")
		return
	}

	switch {
	case r.Method == http.MethodGet && strings.TrimRight(r.URL.Path, "/") == "/api/audit/logs":
		h.list(w, r, claims)
	case r.Method == http.MethodGet && strings.TrimRight(r.URL.Path, "/") == "/api/audit/export":
		h.exportCSV(w, r, claims)
	case r.Method == http.MethodGet && strings.TrimRight(r.URL.Path, "/") == "/api/audit/status":
		h.status(w)
	case r.Method == http.MethodPost && strings.TrimRight(r.URL.Path, "/") == "/api/audit/events":
		h.createEvent(w, r, claims)
	default:
		w.WriteHeader(http.StatusNotFound)
	}
}

func (h *Handler) status(w http.ResponseWriter) {
	if h.writer == nil {
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"configured": false,
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"configured": true,
		"writer":     h.writer.Stats(),
	})
}

func (h *Handler) list(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	filters, err := parseQueryFilters(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if !h.flushPending(w) {
		return
	}
	logs, err := h.query(filters, claims.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"logs":          logs,
		"next_after_id": nextAfterID(logs),
	})
}

func (h *Handler) exportCSV(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	filters, err := parseQueryFilters(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if !h.flushPending(w) {
		return
	}
	logs, err := h.query(filters, claims.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	w.Header().Set("Content-Type", "text/csv")
	w.Header().Set("Content-Disposition", `attachment; filename="audit_logs.csv"`)
	w.WriteHeader(http.StatusOK)
	writer := csv.NewWriter(w)
	_ = writer.Write([]string{"id", "ts", "actor_id", "action_type", "resource_type", "resource_id", "policy_decision", "policy_id", "context_snapshot", "version"})
	for _, log := range logs {
		_ = writer.Write([]string{
			strconv.FormatInt(log.ID, 10),
			log.Timestamp,
			log.ActorID,
			log.ActionType,
			log.ResourceType,
			log.ResourceID,
			log.PolicyDecision,
			log.PolicyID,
			log.ContextSnapshot,
			strconv.Itoa(log.Version),
		})
	}
	writer.Flush()
}

func (h *Handler) flushPending(w http.ResponseWriter) bool {
	if h.writer == nil || h.writer.Flush(auditReadFlushTimeout) {
		return true
	}
	writeError(w, http.StatusServiceUnavailable, "audit_flush_timeout")
	return false
}

func (h *Handler) createEvent(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	var req auditEventRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	req.ActionType = strings.TrimSpace(req.ActionType)
	req.ActorID = strings.TrimSpace(req.ActorID)
	req.ResourceType = strings.TrimSpace(req.ResourceType)
	req.ResourceID = strings.TrimSpace(req.ResourceID)
	req.PolicyDecision = strings.TrimSpace(req.PolicyDecision)
	req.PolicyID = strings.TrimSpace(req.PolicyID)
	req.Severity = normalizeSeverity(req.Severity)
	req.DispositionStatus = normalizeDisposition(req.DispositionStatus)
	req.TicketID = strings.TrimSpace(req.TicketID)
	if req.ActorID == "" {
		req.ActorID = claims.UserID
	}
	if req.PolicyDecision == "" {
		req.PolicyDecision = "allow"
	}
	if !strings.HasPrefix(req.ActionType, "security.") {
		writeError(w, http.StatusBadRequest, "invalid_action_type")
		return
	}
	if req.PolicyDecision != "allow" && req.PolicyDecision != "deny" {
		writeError(w, http.StatusBadRequest, "invalid_decision")
		return
	}
	if !validSeverity(req.Severity) {
		writeError(w, http.StatusBadRequest, "invalid_severity")
		return
	}
	if !validDisposition(req.DispositionStatus) {
		writeError(w, http.StatusBadRequest, "invalid_disposition_status")
		return
	}
	contextSnapshot, err := eventContextSnapshot(r, claims, req)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_context")
		return
	}
	id, err := h.insertEvent(req, contextSnapshot)
	if err != nil {
		if schemaErr := audit.EnsureSchema(h.db); schemaErr != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		id, err = h.insertEvent(req, contextSnapshot)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
	}
	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"id":                 id,
		"action_type":        req.ActionType,
		"status":             "recorded",
		"severity":           req.Severity,
		"disposition_status": req.DispositionStatus,
		"ticket_id":          req.TicketID,
	})
}

func (h *Handler) insertEvent(req auditEventRequest, contextSnapshot string) (int64, error) {
	result, err := h.db.Exec(`
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
	`,
		time.Now().UTC().Format(time.RFC3339Nano),
		req.ActorID,
		req.ActionType,
		req.ResourceType,
		req.ResourceID,
		req.PolicyDecision,
		req.PolicyID,
		contextSnapshot,
		1,
	)
	if err != nil {
		return 0, err
	}
	return result.LastInsertId()
}

func eventContextSnapshot(r *http.Request, claims auth.Claims, req auditEventRequest) (string, error) {
	snapshot := map[string]string{
		"trace_id":            strings.TrimSpace(r.Header.Get("X-Trace-ID")),
		"x_request_id":        strings.TrimSpace(r.Header.Get("X-Request-ID")),
		"x_client_id":         strings.TrimSpace(r.Header.Get("X-Client-ID")),
		"x_resource_owner_id": strings.TrimSpace(r.Header.Get("X-Resource-Owner-ID")),
		"x_resource_id":       strings.TrimSpace(r.Header.Get("X-Resource-ID")),
		"x_tenant_id":         strings.TrimSpace(r.Header.Get("X-Tenant-ID")),
		"x_action":            strings.TrimSpace(r.Header.Get("X-Action")),
	}
	if snapshot["trace_id"] == "" {
		snapshot["trace_id"] = snapshot["x_request_id"]
	}
	if snapshot["x_tenant_id"] == "" {
		snapshot["x_tenant_id"] = strings.TrimSpace(claims.OrgID)
	}
	for key, value := range req.Context {
		key = strings.TrimSpace(key)
		if key == "" {
			return "", fmt.Errorf("empty context key")
		}
		snapshot[key] = strings.TrimSpace(value)
	}
	snapshot["severity"] = req.Severity
	snapshot["disposition_status"] = req.DispositionStatus
	if req.TicketID != "" {
		snapshot["ticket_id"] = req.TicketID
	}
	encoded, err := json.Marshal(snapshot)
	if err != nil {
		return "", err
	}
	return string(encoded), nil
}

func parseQueryFilters(r *http.Request) (queryFilters, error) {
	values := r.URL.Query()
	filters := queryFilters{
		Limit:          100,
		TraceID:        strings.TrimSpace(values.Get("trace_id")),
		ActorID:        strings.TrimSpace(values.Get("actor_id")),
		ActionType:     strings.TrimSpace(values.Get("action_type")),
		ResourceType:   strings.TrimSpace(values.Get("resource_type")),
		ResourceID:     strings.TrimSpace(values.Get("resource_id")),
		PolicyDecision: strings.TrimSpace(values.Get("decision")),
		FromTS:         strings.TrimSpace(values.Get("from_ts")),
		ToTS:           strings.TrimSpace(values.Get("to_ts")),
		Severity:       strings.ToLower(strings.TrimSpace(values.Get("severity"))),
		Disposition:    strings.ToLower(strings.TrimSpace(values.Get("disposition_status"))),
		TicketID:       strings.TrimSpace(values.Get("ticket_id")),
	}

	if raw := strings.TrimSpace(values.Get("limit")); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed <= 0 || parsed > 1000 {
			return filters, fmt.Errorf("invalid_limit")
		}
		filters.Limit = parsed
	}
	if raw := strings.TrimSpace(values.Get("after_id")); raw != "" {
		parsed, err := strconv.ParseInt(raw, 10, 64)
		if err != nil || parsed < 0 {
			return filters, fmt.Errorf("invalid_after_id")
		}
		filters.AfterID = parsed
	}
	if filters.PolicyDecision != "" && filters.PolicyDecision != "allow" && filters.PolicyDecision != "deny" {
		return filters, fmt.Errorf("invalid_decision")
	}
	if filters.Severity != "" && !validSeverity(filters.Severity) {
		return filters, fmt.Errorf("invalid_severity")
	}
	if filters.Disposition != "" && !validDisposition(filters.Disposition) {
		return filters, fmt.Errorf("invalid_disposition_status")
	}
	return filters, nil
}

func (h *Handler) query(filters queryFilters, tenantID string) ([]auditLog, error) {
	tenantID = strings.TrimSpace(tenantID)
	query := `
		SELECT id, ts, actor_id, action_type, resource_type, resource_id, policy_decision, COALESCE(policy_id, ''), context_snapshot, version
		FROM audit_logs
		WHERE 1=1
	`
	args := make([]interface{}, 0, 10)
	if tenantID != "" {
		query += " AND instr(context_snapshot, ?) > 0"
		args = append(args, contextFragment("x_tenant_id", tenantID))
	}
	if filters.TraceID != "" {
		query += " AND instr(context_snapshot, ?) > 0"
		args = append(args, contextFragment("trace_id", filters.TraceID))
	}
	if filters.Severity != "" {
		query += " AND instr(context_snapshot, ?) > 0"
		args = append(args, contextFragment("severity", filters.Severity))
	}
	if filters.Disposition != "" {
		query += " AND instr(context_snapshot, ?) > 0"
		args = append(args, contextFragment("disposition_status", filters.Disposition))
	}
	if filters.TicketID != "" {
		query += " AND instr(context_snapshot, ?) > 0"
		args = append(args, contextFragment("ticket_id", filters.TicketID))
	}
	if filters.AfterID > 0 {
		query += " AND id > ?"
		args = append(args, filters.AfterID)
	}
	if filters.ActorID != "" {
		query += " AND actor_id = ?"
		args = append(args, filters.ActorID)
	}
	if filters.ActionType != "" {
		query += " AND action_type = ?"
		args = append(args, filters.ActionType)
	}
	if filters.ResourceType != "" {
		query += " AND resource_type = ?"
		args = append(args, filters.ResourceType)
	}
	if filters.ResourceID != "" {
		query += " AND resource_id = ?"
		args = append(args, filters.ResourceID)
	}
	if filters.PolicyDecision != "" {
		query += " AND policy_decision = ?"
		args = append(args, filters.PolicyDecision)
	}
	if filters.FromTS != "" {
		query += " AND ts >= ?"
		args = append(args, filters.FromTS)
	}
	if filters.ToTS != "" {
		query += " AND ts <= ?"
		args = append(args, filters.ToTS)
	}
	query += `
		ORDER BY id DESC
		LIMIT ?
	`
	args = append(args, filters.Limit)
	rows, err := h.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	logs := make([]auditLog, 0)
	for rows.Next() {
		var item auditLog
		if err := rows.Scan(&item.ID, &item.Timestamp, &item.ActorID, &item.ActionType, &item.ResourceType, &item.ResourceID, &item.PolicyDecision, &item.PolicyID, &item.ContextSnapshot, &item.Version); err != nil {
			return nil, err
		}
		logs = append(logs, item)
	}
	return logs, rows.Err()
}

func contextFragment(key, value string) string {
	encodedValue, err := json.Marshal(value)
	if err != nil {
		return `"` + key + `":"` + value + `"`
	}
	return `"` + key + `":` + string(encodedValue)
}

func nextAfterID(logs []auditLog) int64 {
	var maxID int64
	for _, log := range logs {
		if log.ID > maxID {
			maxID = log.ID
		}
	}
	return maxID
}

func normalizeSeverity(severity string) string {
	severity = strings.ToLower(strings.TrimSpace(severity))
	if severity == "" {
		return "info"
	}
	return severity
}

func validSeverity(severity string) bool {
	switch severity {
	case "info", "low", "medium", "high", "critical":
		return true
	default:
		return false
	}
}

func normalizeDisposition(disposition string) string {
	disposition = strings.ToLower(strings.TrimSpace(disposition))
	if disposition == "" {
		return "open"
	}
	return disposition
}

func validDisposition(disposition string) bool {
	switch disposition {
	case "open", "acknowledged", "resolved", "ignored":
		return true
	default:
		return false
	}
}

func isAdmin(claims auth.Claims) bool {
	for _, role := range claims.RoleList {
		if role == "hanhe_admin" {
			return true
		}
	}
	return false
}

func writeJSON(w http.ResponseWriter, status int, response interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(response)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
