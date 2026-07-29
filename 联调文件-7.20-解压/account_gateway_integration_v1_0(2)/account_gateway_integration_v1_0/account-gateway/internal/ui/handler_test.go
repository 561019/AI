package ui

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/auth"
)

func TestCurrentPlatformRolesReceiveExpectedPanels(t *testing.T) {
	mapping := roleToPanels
	cases := []struct {
		role string
		want []string
	}{
		{role: "hanhe_im", want: []string{"组织信息管理"}},
		{role: "hanhe_dsm", want: []string{"数据安全治理台", "授权"}},
	}
	for _, tc := range cases {
		t.Run(tc.role, func(t *testing.T) {
			if got := panelsForRoles([]string{tc.role}, mapping); !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("panels=%v want=%v", got, tc.want)
			}
		})
	}
	adminPanels := panelsForRoles([]string{"hanhe_admin"}, mapping)
	for _, required := range []string{"授权", "数据安全治理台", "组织信息管理"} {
		if !containsPanel(adminPanels, required) {
			t.Fatalf("hanhe_admin panels %v missing %s", adminPanels, required)
		}
	}
}

func TestUIPermissionsHandlerAuthMethodAndRoleUnion(t *testing.T) {
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(nil, jwt)
	token, err := jwt.Issue("ui-user", "org-1", []string{"staff", "hanhe_dsm"})
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}

	postReq := httptest.NewRequest(http.MethodPost, "/api/ui-permissions", nil)
	postReq.Header.Set("Authorization", "Bearer "+token)
	postRec := httptest.NewRecorder()
	handler.ServeHTTP(postRec, postReq)
	if postRec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("POST status=%d", postRec.Code)
	}

	unauthorized := httptest.NewRecorder()
	handler.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/api/ui-permissions", nil))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized status=%d", unauthorized.Code)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/ui-permissions", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("GET status=%d body=%s", rec.Code, rec.Body.String())
	}
	var response permissionsResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	for _, required := range []string{"工作汇报", "数据安全治理台", "授权"} {
		if !containsPanel(response.Panels, required) {
			t.Fatalf("panels %v missing %s", response.Panels, required)
		}
	}
}

func TestLoadRolePanelsUsesValidFileAndFallsBackForInvalidFile(t *testing.T) {
	dir := t.TempDir()
	validPath := filepath.Join(dir, "valid.json")
	if err := os.WriteFile(validPath, []byte(`{"hanhe_im":["自定义组织台"]}`), 0o600); err != nil {
		t.Fatalf("write valid config: %v", err)
	}
	t.Setenv("UI_PERMISSIONS_FILE", validPath)
	if got := loadRolePanels()["hanhe_im"]; !reflect.DeepEqual(got, []string{"自定义组织台"}) {
		t.Fatalf("custom mapping=%v", got)
	}

	invalidPath := filepath.Join(dir, "invalid.json")
	if err := os.WriteFile(invalidPath, []byte(`{"hanhe_im":`), 0o600); err != nil {
		t.Fatalf("write invalid config: %v", err)
	}
	t.Setenv("UI_PERMISSIONS_FILE", invalidPath)
	if got := loadRolePanels()["hanhe_im"]; !reflect.DeepEqual(got, roleToPanels["hanhe_im"]) {
		t.Fatalf("fallback mapping=%v", got)
	}
}

func TestNewHandlerFromEnvRejectsConfiguredFileErrors(t *testing.T) {
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	t.Setenv("UI_PERMISSIONS_FILE", filepath.Join(t.TempDir(), "missing.json"))
	if _, err := NewHandlerFromEnv(nil, jwt); err == nil {
		t.Fatal("expected missing configured permissions file to fail")
	}

	dir := t.TempDir()
	invalidPath := filepath.Join(dir, "invalid.json")
	if err := os.WriteFile(invalidPath, []byte(`null`), 0o600); err != nil {
		t.Fatalf("write invalid config: %v", err)
	}
	t.Setenv("UI_PERMISSIONS_FILE", invalidPath)
	if _, err := NewHandlerFromEnv(nil, jwt); err == nil {
		t.Fatal("expected non-object permissions config to fail")
	}
}

func containsPanel(panels []string, target string) bool {
	for _, panel := range panels {
		if panel == target {
			return true
		}
	}
	return false
}
