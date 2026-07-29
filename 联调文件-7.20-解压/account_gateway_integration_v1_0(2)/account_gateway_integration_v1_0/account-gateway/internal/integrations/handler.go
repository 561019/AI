package integrations

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
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
	now   func() time.Time
}

type syncStatus struct {
	Provider    string         `json:"provider"`
	TenantID    string         `json:"tenant_id"`
	Mode        string         `json:"mode"`
	Status      string         `json:"status"`
	Synced      bool           `json:"synced"`
	AttemptedAt string         `json:"attempted_at"`
	SyncedAt    string         `json:"synced_at"`
	ActorID     string         `json:"actor_id"`
	Source      string         `json:"source"`
	Summary     map[string]int `json:"summary"`
	LastError   string         `json:"last_error,omitempty"`
	Attempts    int            `json:"attempts"`
}

func NewHandler(db *sql.DB, jwt *auth.JWTManager, auditWriter *audit.Writer) *Handler {
	return &Handler{
		db:    db,
		jwt:   jwt,
		audit: auditWriter,
		now:   func() time.Time { return time.Now().UTC() },
	}
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

	provider, action := parseProviderAction(r.URL.Path)
	if provider == "" {
		writeError(w, http.StatusBadRequest, "missing_provider")
		return
	}
	if !supportedProvider(provider) {
		writeError(w, http.StatusNotFound, "provider_not_supported")
		return
	}

	switch {
	case r.Method == http.MethodPost && action == "sync":
		h.sync(w, r, claims, provider)
	case r.Method == http.MethodGet && action == "status":
		h.status(w, claims, provider)
	default:
		w.WriteHeader(http.StatusNotFound)
	}
}

func (h *Handler) sync(w http.ResponseWriter, r *http.Request, claims auth.Claims, provider string) {
	now := h.now().Format(time.RFC3339)
	summary, source, err := connectorSummary(provider)
	status := syncStatus{
		Provider:    provider,
		TenantID:    strings.TrimSpace(claims.OrgID),
		Mode:        "mock",
		Status:      "success",
		Synced:      true,
		AttemptedAt: now,
		SyncedAt:    now,
		ActorID:     claims.UserID,
		Source:      source,
		Summary:     summary,
	}
	if err != nil {
		status.Status = "failed"
		status.Synced = false
		status.SyncedAt = ""
		status.LastError = "fixture_error"
		status.Source = "fixture"
		status.Summary = map[string]int{}
	}
	saved, saveErr := h.saveStatus(status)
	if saveErr != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	decision := policy.Decision{Allow: err == nil, PolicyID: "integration_sync:" + provider + ":" + saved.Status}
	h.logSync(r, claims, provider, decision)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "fixture_error")
		return
	}
	writeJSON(w, http.StatusOK, saved)
}

func (h *Handler) status(w http.ResponseWriter, claims auth.Claims, provider string) {
	status, err := h.readStatus(claims.OrgID, provider)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "sync_status_not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	writeJSON(w, http.StatusOK, status)
}

func (h *Handler) saveStatus(status syncStatus) (syncStatus, error) {
	summary, err := json.Marshal(status.Summary)
	if err != nil {
		return syncStatus{}, err
	}
	_, err = h.db.Exec(`
		INSERT INTO integration_sync_status (
			tenant_id, provider, mode, status, synced, attempted_at, synced_at,
			actor_id, source, summary_json, last_error, attempts
		) VALUES (?, ?, ?, ?, ?, ?, NULLIF(?, ''), ?, ?, ?, NULLIF(?, ''), 1)
		ON CONFLICT(tenant_id, provider) DO UPDATE SET
			mode=excluded.mode,
			status=excluded.status,
			synced=excluded.synced,
			attempted_at=excluded.attempted_at,
			synced_at=CASE WHEN excluded.synced=1 THEN excluded.synced_at ELSE integration_sync_status.synced_at END,
			actor_id=excluded.actor_id,
			source=excluded.source,
			summary_json=excluded.summary_json,
			last_error=excluded.last_error,
			attempts=integration_sync_status.attempts + 1
	`, status.TenantID, status.Provider, status.Mode, status.Status, boolInt(status.Synced), status.AttemptedAt, status.SyncedAt,
		status.ActorID, status.Source, string(summary), status.LastError)
	if err != nil {
		return syncStatus{}, err
	}
	return h.readStatus(status.TenantID, status.Provider)
}

func (h *Handler) readStatus(tenantID, provider string) (syncStatus, error) {
	var status syncStatus
	var synced int
	var syncedAt, lastError sql.NullString
	var summaryJSON string
	err := h.db.QueryRow(`
		SELECT provider, tenant_id, mode, status, synced, attempted_at, synced_at,
		       actor_id, source, summary_json, last_error, attempts
		FROM integration_sync_status
		WHERE tenant_id=? AND provider=?
	`, strings.TrimSpace(tenantID), strings.TrimSpace(provider)).Scan(
		&status.Provider, &status.TenantID, &status.Mode, &status.Status, &synced,
		&status.AttemptedAt, &syncedAt, &status.ActorID, &status.Source, &summaryJSON,
		&lastError, &status.Attempts,
	)
	if err != nil {
		return syncStatus{}, err
	}
	status.Synced = synced == 1
	status.SyncedAt = syncedAt.String
	status.LastError = lastError.String
	if err := json.Unmarshal([]byte(summaryJSON), &status.Summary); err != nil {
		return syncStatus{}, err
	}
	return status, nil
}

func (h *Handler) logSync(r *http.Request, claims auth.Claims, provider string, decision policy.Decision) {
	if h.audit == nil {
		return
	}
	headers := r.Header.Clone()
	headers.Set("X-Tenant-ID", claims.OrgID)
	if err := h.audit.LogAction(audit.WithSpan(r.Context(), headers), "integrations.sync", claims.UserID, "integration", provider, decision, decision.PolicyID, headers); err != nil {
		log.Printf("integration sync audit failed: %v", err)
	}
}

func boolInt(value bool) int {
	if value {
		return 1
	}
	return 0
}

func parseProviderAction(path string) (string, string) {
	trimmed := strings.Trim(strings.TrimPrefix(path, "/api/integrations/"), "/")
	parts := strings.Split(trimmed, "/")
	if len(parts) != 2 {
		return "", ""
	}
	return strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1])
}

func supportedProvider(provider string) bool {
	switch provider {
	case "dingtalk", "wecom", "hr":
		return true
	default:
		return false
	}
}

func connectorSummary(provider string) (map[string]int, string, error) {
	switch provider {
	case "hr":
		if summary, ok, err := loadHRSummary(); err != nil || ok {
			return summary, "fixture", err
		}
		return map[string]int{"users": 3}, "built_in", nil
	case "dingtalk", "wecom":
		if summary, ok, err := loadOrgSummary(); err != nil || ok {
			return summary, "fixture", err
		}
		return map[string]int{"departments": 3, "positions": 4, "reporting_lines": 3}, "built_in", nil
	default:
		return nil, "", fmt.Errorf("unsupported provider")
	}
}

func loadHRSummary() (map[string]int, bool, error) {
	var fixture struct {
		Users []json.RawMessage `json:"users"`
	}
	ok, err := loadFixture("hr_source.json", &fixture)
	if !ok || err != nil {
		return nil, ok, err
	}
	return map[string]int{"users": len(fixture.Users)}, true, nil
}

func loadOrgSummary() (map[string]int, bool, error) {
	var fixture struct {
		Organization struct {
			Departments    []json.RawMessage `json:"departments"`
			Positions      []json.RawMessage `json:"positions"`
			ReportingLines []json.RawMessage `json:"reporting_lines"`
		} `json:"organization"`
	}
	ok, err := loadFixture("org_structure.json", &fixture)
	if !ok || err != nil {
		return nil, ok, err
	}
	return map[string]int{
		"departments":     len(fixture.Organization.Departments),
		"positions":       len(fixture.Organization.Positions),
		"reporting_lines": len(fixture.Organization.ReportingLines),
	}, true, nil
}

func loadFixture(name string, out interface{}) (bool, error) {
	if configured := strings.TrimSpace(os.Getenv("INTEGRATION_FIXTURE_DIR")); configured != "" {
		path := filepath.Join(configured, name)
		data, err := os.ReadFile(path)
		if err != nil {
			return true, fmt.Errorf("read configured integration fixture %s: %w", path, err)
		}
		return true, json.Unmarshal(data, out)
	}
	for _, dir := range fixtureDirs() {
		path := filepath.Join(dir, name)
		data, err := os.ReadFile(path)
		if err == nil {
			return true, json.Unmarshal(data, out)
		}
		if !os.IsNotExist(err) {
			return true, err
		}
	}
	return false, nil
}

func fixtureDirs() []string {
	dirs := []string{}
	if cwd, err := os.Getwd(); err == nil {
		dirs = append(dirs,
			filepath.Join(cwd, "tests", "mocks", "fixtures"),
			filepath.Join(cwd, "..", "..", "tests", "mocks", "fixtures"),
		)
	}
	return dirs
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
