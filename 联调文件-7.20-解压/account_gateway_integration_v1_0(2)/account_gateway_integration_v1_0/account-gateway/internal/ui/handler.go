package ui

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"

	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/policy"
)

type permissionsResponse struct {
	Panels []string `json:"panels"`
}

var roleToPanels = map[string][]string{
	"staff":       {"工作汇报", "我的 Agent", "自创 Agent"},
	"admin":       {"工作汇报", "我的 Agent", "自创 Agent", "大区经营", "知识库维护", "授权", "经验推广"},
	"data_owner":  {"数据安全治理台"},
	"hr":          {"组织信息管理"},
	"hanhe_im":    {"组织信息管理"},
	"hanhe_dsm":   {"数据安全治理台", "授权"},
	"hanhe_admin": {"工作汇报", "我的 Agent", "自创 Agent", "大区经营", "知识库维护", "授权", "经验推广", "数据安全治理台", "组织信息管理"},
}

type Handler struct {
	jwt          *auth.JWTManager
	roleToPanels map[string][]string
}

func NewHandler(enforcer *policy.Enforcer, jwt *auth.JWTManager) *Handler {
	return &Handler{jwt: jwt, roleToPanels: loadRolePanels()}
}

// NewHandlerFromEnv is the startup constructor. When an operator explicitly
// configures a permissions file, a bad path or malformed file is a startup
// error rather than a silent permission-map fallback.
func NewHandlerFromEnv(enforcer *policy.Enforcer, jwt *auth.JWTManager) (*Handler, error) {
	mapping, err := loadRolePanelsStrict()
	if err != nil {
		return nil, err
	}
	return &Handler{jwt: jwt, roleToPanels: mapping}, nil
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}

	writeJSON(w, http.StatusOK, permissionsResponse{Panels: panelsForRoles(claims.RoleList, h.roleToPanels)})
}

func panelsForRoles(roles []string, mapping map[string][]string) []string {
	panels := make([]string, 0)
	seen := make(map[string]struct{})
	for _, role := range roles {
		for _, panel := range mapping[role] {
			if _, ok := seen[panel]; ok {
				continue
			}
			seen[panel] = struct{}{}
			panels = append(panels, panel)
		}
	}
	return panels
}

func loadRolePanels() map[string][]string {
	mapping, err := loadRolePanelsStrict()
	if err != nil {
		log.Printf("load UI_PERMISSIONS_FILE failed, using defaults: %v", err)
		return roleToPanels
	}
	return mapping
}

func loadRolePanelsStrict() (map[string][]string, error) {
	path := os.Getenv("UI_PERMISSIONS_FILE")
	if path == "" {
		return roleToPanels, nil
	}
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read UI_PERMISSIONS_FILE %q: %w", path, err)
	}
	var mapping map[string][]string
	if err := json.Unmarshal(content, &mapping); err != nil {
		return nil, fmt.Errorf("parse UI_PERMISSIONS_FILE %q: %w", path, err)
	}
	if mapping == nil {
		return nil, fmt.Errorf("parse UI_PERMISSIONS_FILE %q: top-level value must be an object", path)
	}
	for role, panels := range mapping {
		if role == "" {
			return nil, fmt.Errorf("parse UI_PERMISSIONS_FILE %q: role must not be empty", path)
		}
		for _, panel := range panels {
			if panel == "" {
				return nil, fmt.Errorf("parse UI_PERMISSIONS_FILE %q: panel for role %q must not be empty", path, role)
			}
		}
	}
	return mapping, nil
}

func writeJSON(w http.ResponseWriter, status int, response permissionsResponse) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(response)
}
