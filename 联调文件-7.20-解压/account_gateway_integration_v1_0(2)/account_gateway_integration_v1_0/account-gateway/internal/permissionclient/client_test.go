package permissionclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/auth"
)

func TestCheckPreservesContract(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/permission/check" || r.Method != http.MethodPost {
			t.Fatalf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		var request CheckRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Fatal(err)
		}
		if request.TraceID != "trace-1" || request.ActorID != "u-1" {
			t.Fatalf("unexpected request: %+v", request)
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(CheckResponse{
			TraceID: "trace-1", RequestID: "request-1", DecisionID: "decision-1",
			Allowed: true, Result: "allow", ReasonCode: "PERMISSION_GRANTED",
		})
	}))
	defer server.Close()

	client := New(server.URL, time.Second)
	response, status, err := client.Check(context.Background(), CheckRequest{
		TraceID: "trace-1", RequestID: "request-1", ActorID: "u-1",
		Action: "read", SourceService: "account_gateway", TargetService: "legacy_runtime",
		DataLabel: "normal", DataState: "active",
	})
	if err != nil || status != http.StatusOK || !response.Allowed || response.DecisionID != "decision-1" {
		t.Fatalf("status=%d response=%+v err=%v", status, response, err)
	}
}

func TestManagementProxyAuthenticatesAndForwardsClaims(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "" {
			t.Fatal("authorization header must not be forwarded")
		}
		if r.Header.Get("X-Actor-ID") != "admin" || r.Header.Get("X-Tenant-ID") != "tenant-a" {
			t.Fatalf("missing forwarded identity: %+v", r.Header)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer server.Close()

	jwt := auth.NewJWTManager("test-secret", time.Hour)
	token, err := jwt.Issue("admin", "tenant-a", []string{"hanhe_admin"})
	if err != nil {
		t.Fatal(err)
	}
	proxy := NewManagementProxy(New(server.URL, time.Second), jwt)
	request := httptest.NewRequest(http.MethodPost, "/api/org/commands", nil)
	request.Header.Set("Authorization", "Bearer "+token)
	recorder := httptest.NewRecorder()
	proxy.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusCreated || recorder.Body.String() != `{"ok":true}` {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}

	unauthorized := httptest.NewRequest(http.MethodGet, "/api/org/snapshot", nil)
	unauthorizedRecorder := httptest.NewRecorder()
	proxy.ServeHTTP(unauthorizedRecorder, unauthorized)
	if unauthorizedRecorder.Code != http.StatusUnauthorized {
		t.Fatalf("status=%d", unauthorizedRecorder.Code)
	}
}
