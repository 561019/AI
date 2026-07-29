package gateway

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/permissionclient"
	"hanhe.com/account-gateway/internal/policy"
)

func TestRemotePermissionModeMapsLegacyHeaders(t *testing.T) {
	permissionServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request permissionclient.CheckRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Fatal(err)
		}
		if request.ActorID != "remote-user" || request.Action != "content.generate" || request.DataLabel != "normal" || request.DataState != "active" {
			t.Fatalf("unexpected mapped request: %+v", request)
		}
		if request.SourceService != "account_gateway" || request.TargetService != "legacy_runtime" || request.TenantID != "tenant-a" {
			t.Fatalf("unexpected compatibility defaults: %+v", request)
		}
		_ = json.NewEncoder(w).Encode(permissionclient.CheckResponse{
			TraceID: request.TraceID, RequestID: request.RequestID,
			DecisionID: "decision-remote", Allowed: true, Result: "allow", ReasonCode: "PERMISSION_GRANTED",
		})
	}))
	defer permissionServer.Close()

	handler, token := remoteValidateHandler(t, permissionServer.URL)
	request := remoteValidateRequest(t, token)
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK || recorder.Body.String() != `{"allow":true,"policy_id":"decision-remote"}`+"\n" {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestRemotePermissionModeFailsClosedWithoutLocalFallback(t *testing.T) {
	permissionServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	url := permissionServer.URL
	permissionServer.Close()
	handler, token := remoteValidateHandler(t, url)
	request := remoteValidateRequest(t, token)
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
	var response validateResponse
	if err := json.NewDecoder(recorder.Body).Decode(&response); err != nil {
		t.Fatal(err)
	}
	if response.Allow || response.Reason != "permission_service_unavailable" {
		t.Fatalf("unexpected response: %+v", response)
	}
}

func remoteValidateHandler(t *testing.T, permissionURL string) (*ValidateHandler, string) {
	t.Helper()
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatal(err)
	}
	jwt := auth.NewJWTManager("remote-test-secret", time.Hour)
	token, err := jwt.Issue("remote-user", "tenant-a", []string{"staff"})
	if err != nil {
		t.Fatal(err)
	}
	handler := NewValidateHandler(nil, enforcer, nil, jwt).
		WithPermissionClient(permissionclient.New(permissionURL, 200*time.Millisecond), permissionclient.ModeRemote)
	return handler, token
}

func remoteValidateRequest(t *testing.T, token string) *http.Request {
	t.Helper()
	request := httptest.NewRequest(http.MethodPost, "/auth/validate", nil)
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("X-User-ID", "remote-user")
	request.Header.Set("X-Resource-Type", "data")
	request.Header.Set("X-Resource-ID", "data-1")
	request.Header.Set("X-Resource-Owner-ID", "owner-1")
	request.Header.Set("X-Action", "content.generate")
	return request
}
