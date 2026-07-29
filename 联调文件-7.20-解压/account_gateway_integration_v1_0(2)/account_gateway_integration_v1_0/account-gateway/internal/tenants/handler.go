package tenants

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
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

type tenant struct {
	ID        string   `json:"id"`
	Name      string   `json:"name"`
	Users     []string `json:"users,omitempty"`
	CreatedBy string   `json:"created_by,omitempty"`
	CreatedAt string   `json:"created_at,omitempty"`
}

type createTenantRequest struct {
	ID    string   `json:"id"`
	Name  string   `json:"name"`
	Users []string `json:"users"`
}

type updateTenantRequest struct {
	Name  *string   `json:"name"`
	Users *[]string `json:"users"`
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
	if strings.TrimRight(r.URL.Path, "/") != "/api/tenants" {
		h.detail(w, r, claims)
		return
	}

	switch r.Method {
	case http.MethodPost:
		h.create(w, r, claims)
	case http.MethodGet:
		h.list(w, r, claims)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) detail(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	tenantID := tenantIDFromPath(r.URL.Path)
	if tenantID == "" {
		writeError(w, http.StatusNotFound, "tenant_not_found")
		return
	}
	switch r.Method {
	case http.MethodGet:
		h.get(w, claims, tenantID)
	case http.MethodPatch:
		h.update(w, r, claims, tenantID)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) get(w http.ResponseWriter, claims auth.Claims, tenantID string) {
	if !h.canReadTenant(claims, tenantID) {
		writeError(w, http.StatusNotFound, "tenant_not_found")
		return
	}
	var item tenant
	err := h.db.QueryRow("SELECT id, name, created_by, created_at FROM tenants WHERE id = ?", tenantID).Scan(&item.ID, &item.Name, &item.CreatedBy, &item.CreatedAt)
	if err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "tenant_not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	users, err := h.users(item.ID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	item.Users = users
	writeJSON(w, http.StatusOK, item)
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "admin_only")
		return
	}
	var req createTenantRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	req.ID = strings.TrimSpace(req.ID)
	req.Name = strings.TrimSpace(req.Name)
	if req.ID == "" {
		req.ID = claims.OrgID
	}
	if req.Name == "" {
		req.Name = req.ID
	}
	now := time.Now().UTC().Format(time.RFC3339)
	users := normalizedUsers(req.Users)
	tx, err := h.db.Begin()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	defer tx.Rollback()
	if _, err := tx.Exec("INSERT INTO tenants (id, name, created_by, created_at) VALUES (?, ?, ?, ?)", req.ID, req.Name, claims.UserID, now); err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "unique") {
			writeError(w, http.StatusConflict, "tenant_exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	for _, userID := range users {
		if _, err := tx.Exec("INSERT INTO tenant_users (tenant_id, user_id, created_at) VALUES (?, ?, ?)", req.ID, userID, now); err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
	}
	if err := tx.Commit(); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.log(r, claims, "tenants.create", req.ID)
	writeJSON(w, http.StatusCreated, tenant{ID: req.ID, Name: req.Name, Users: users, CreatedBy: claims.UserID, CreatedAt: now})
}

func (h *Handler) update(w http.ResponseWriter, r *http.Request, claims auth.Claims, tenantID string) {
	if !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "admin_only")
		return
	}
	var req updateTenantRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	if req.Name == nil && req.Users == nil {
		writeError(w, http.StatusBadRequest, "empty_update")
		return
	}
	var item tenant
	if err := h.db.QueryRow("SELECT id, name, created_by, created_at FROM tenants WHERE id=?", tenantID).Scan(&item.ID, &item.Name, &item.CreatedBy, &item.CreatedAt); err == sql.ErrNoRows {
		writeError(w, http.StatusNotFound, "tenant_not_found")
		return
	} else if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	tx, err := h.db.Begin()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	defer tx.Rollback()
	if req.Name != nil {
		item.Name = strings.TrimSpace(*req.Name)
		if item.Name == "" {
			writeError(w, http.StatusBadRequest, "missing_name")
			return
		}
		if _, err := tx.Exec("UPDATE tenants SET name=? WHERE id=?", item.Name, tenantID); err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
	}
	if req.Users != nil {
		item.Users = normalizedUsers(*req.Users)
		if _, err := tx.Exec("DELETE FROM tenant_users WHERE tenant_id=?", tenantID); err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		now := time.Now().UTC().Format(time.RFC3339)
		for _, userID := range item.Users {
			if _, err := tx.Exec("INSERT INTO tenant_users (tenant_id, user_id, created_at) VALUES (?, ?, ?)", tenantID, userID, now); err != nil {
				writeError(w, http.StatusInternalServerError, "db_error")
				return
			}
		}
	} else {
		item.Users, err = h.usersTx(tx, tenantID)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
	}
	if err := tx.Commit(); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	h.log(r, claims, "tenants.update", tenantID)
	writeJSON(w, http.StatusOK, item)
}

func (h *Handler) list(w http.ResponseWriter, _ *http.Request, claims auth.Claims) {
	var rows *sql.Rows
	var err error
	if isAdmin(claims) {
		rows, err = h.db.Query("SELECT id, name, created_by, created_at FROM tenants ORDER BY id")
	} else {
		rows, err = h.db.Query(`
			SELECT t.id, t.name, t.created_by, t.created_at
			FROM tenants t
			JOIN tenant_users u ON u.tenant_id=t.id
			WHERE t.id=? AND u.user_id=?
			ORDER BY t.id
		`, claims.OrgID, claims.UserID)
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}

	result := make([]tenant, 0)
	for rows.Next() {
		var item tenant
		if err := rows.Scan(&item.ID, &item.Name, &item.CreatedBy, &item.CreatedAt); err != nil {
			_ = rows.Close()
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		result = append(result, item)
	}
	if err := rows.Err(); err != nil {
		_ = rows.Close()
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	if err := rows.Close(); err != nil {
		writeError(w, http.StatusInternalServerError, "db_error")
		return
	}
	for index := range result {
		users, err := h.users(result[index].ID)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db_error")
			return
		}
		result[index].Users = users
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"tenants": result})
}

func (h *Handler) users(tenantID string) ([]string, error) {
	return h.usersQuery(h.db, tenantID)
}

type tenantUserQuerier interface {
	Query(query string, args ...interface{}) (*sql.Rows, error)
}

func (h *Handler) usersTx(tx *sql.Tx, tenantID string) ([]string, error) {
	return h.usersQuery(tx, tenantID)
}

func (h *Handler) usersQuery(queryer tenantUserQuerier, tenantID string) ([]string, error) {
	rows, err := queryer.Query("SELECT user_id FROM tenant_users WHERE tenant_id = ? ORDER BY user_id", tenantID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	users := make([]string, 0)
	for rows.Next() {
		var userID string
		if err := rows.Scan(&userID); err != nil {
			return nil, err
		}
		users = append(users, userID)
	}
	return users, rows.Err()
}

func (h *Handler) canReadTenant(claims auth.Claims, tenantID string) bool {
	if isAdmin(claims) {
		return true
	}
	if strings.TrimSpace(claims.OrgID) != tenantID {
		return false
	}
	var found int
	err := h.db.QueryRow("SELECT 1 FROM tenant_users WHERE tenant_id=? AND user_id=?", tenantID, claims.UserID).Scan(&found)
	return err == nil
}

func (h *Handler) log(r *http.Request, claims auth.Claims, actionType, tenantID string) {
	if h.audit == nil {
		return
	}
	headers := r.Header.Clone()
	headers.Set("X-Tenant-ID", tenantID)
	decision := policy.Decision{Allow: true, PolicyID: actionType}
	if err := h.audit.LogAction(audit.WithSpan(r.Context(), headers), actionType, claims.UserID, "tenant", tenantID, decision, actionType, headers); err != nil {
		log.Printf("tenant audit failed action=%s tenant_id=%s: %v", actionType, tenantID, err)
	}
}

func normalizedUsers(users []string) []string {
	result := make([]string, 0, len(users))
	seen := make(map[string]struct{})
	for _, userID := range users {
		userID = strings.TrimSpace(userID)
		if userID == "" {
			continue
		}
		if _, ok := seen[userID]; ok {
			continue
		}
		seen[userID] = struct{}{}
		result = append(result, userID)
	}
	return result
}

func tenantIDFromPath(path string) string {
	path = strings.Trim(strings.TrimPrefix(path, "/api/tenants/"), "/")
	if path == "" || strings.Contains(path, "/") {
		return ""
	}
	return path
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
