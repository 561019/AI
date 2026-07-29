package credentials

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"

	_ "github.com/mattn/go-sqlite3"
)

const testEncryptionKey = "12345678901234567890123456789012"

func TestCredentialsStoreListAndUse(t *testing.T) {
	db := openCredentialsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt, audit.NewWriter(db))
	token := issueCredentialsToken(t, jwt, "user-1", []string{"employee"})

	storeReq := httptest.NewRequest(http.MethodPost, "/api/credentials", bytes.NewBufferString(`{"name":"openai-key","type":"api_key"}`))
	storeReq.Header.Set("Authorization", "Bearer "+token)
	storeReq.Header.Set("X-Credential-Value", "sk-secret123")
	storeReq.Header.Set("Content-Type", "application/json")
	storeRec := httptest.NewRecorder()

	handler.ServeHTTP(storeRec, storeReq)

	if storeRec.Code != http.StatusCreated {
		t.Fatalf("store status = %d, body = %s", storeRec.Code, storeRec.Body.String())
	}
	if strings.Contains(storeRec.Body.String(), "sk-secret123") || strings.Contains(storeRec.Body.String(), "encrypted_value") {
		t.Fatalf("store response leaked credential data: %s", storeRec.Body.String())
	}
	var storeResp struct {
		ID   int64  `json:"id"`
		Name string `json:"name"`
		Type string `json:"type"`
	}
	if err := json.Unmarshal(storeRec.Body.Bytes(), &storeResp); err != nil {
		t.Fatalf("decode store response: %v", err)
	}
	if storeResp.ID == 0 || storeResp.Name != "openai-key" || storeResp.Type != "api_key" {
		t.Fatalf("unexpected store response: %+v", storeResp)
	}

	var encryptedValue, ownerUserID string
	if err := db.QueryRow(`SELECT encrypted_value, owner_user_id FROM credentials WHERE id = ?`, storeResp.ID).Scan(&encryptedValue, &ownerUserID); err != nil {
		t.Fatalf("read stored credential: %v", err)
	}
	if encryptedValue == "sk-secret123" || encryptedValue == "" || ownerUserID != "user-1" {
		t.Fatalf("credential was not encrypted or owned correctly: encrypted=%q owner=%q", encryptedValue, ownerUserID)
	}

	listReq := httptest.NewRequest(http.MethodGet, "/api/credentials", nil)
	listReq.Header.Set("Authorization", "Bearer "+token)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)

	if listRec.Code != http.StatusOK {
		t.Fatalf("list status = %d, body = %s", listRec.Code, listRec.Body.String())
	}
	if strings.Contains(listRec.Body.String(), "sk-secret123") || strings.Contains(listRec.Body.String(), "encrypted_value") || strings.Contains(listRec.Body.String(), encryptedValue) {
		t.Fatalf("list response leaked credential data: %s", listRec.Body.String())
	}
	var listResp struct {
		Credentials []struct {
			ID          int64  `json:"id"`
			Name        string `json:"name"`
			Type        string `json:"type"`
			OwnerUserID string `json:"owner_user_id"`
			CreatedAt   string `json:"created_at"`
			Status      string `json:"status"`
		} `json:"credentials"`
	}
	if err := json.Unmarshal(listRec.Body.Bytes(), &listResp); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if len(listResp.Credentials) != 1 || listResp.Credentials[0].ID != storeResp.ID || listResp.Credentials[0].OwnerUserID != "user-1" || listResp.Credentials[0].CreatedAt == "" {
		t.Fatalf("unexpected list response: %+v", listResp)
	}
	if listResp.Credentials[0].Status != "active" {
		t.Fatalf("credential status = %q", listResp.Credentials[0].Status)
	}

	useReq := httptest.NewRequest(http.MethodPost, "/api/credentials/"+strconv.FormatInt(storeResp.ID, 10)+"/use", nil)
	useReq.Header.Set("Authorization", "Bearer "+token)
	useRec := httptest.NewRecorder()
	handler.ServeHTTP(useRec, useReq)

	if useRec.Code != http.StatusNotImplemented {
		t.Fatalf("use status = %d, body = %s", useRec.Code, useRec.Body.String())
	}
	if got := useRec.Header().Get("X-Distributed-Credential"); got != "" {
		t.Fatalf("credential must never be returned = %q", got)
	}
	var auditCount int
	if err := db.QueryRow(`SELECT COUNT(*) FROM audit_logs WHERE action_type = 'credentials.use' AND actor_id = 'user-1' AND resource_type = 'credential' AND resource_id = ? AND policy_decision = 'allow'`, strconv.FormatInt(storeResp.ID, 10)).Scan(&auditCount); err != nil {
		t.Fatalf("read audit logs: %v", err)
	}
	if auditCount != 1 {
		t.Fatalf("audit log count = %d", auditCount)
	}
}

func TestCredentialsExpiryBlocksUseWithoutLeakingSecret(t *testing.T) {
	db := openCredentialsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt, audit.NewWriter(db))
	token := issueCredentialsToken(t, jwt, "owner", []string{"employee"})
	expiredAt := time.Now().UTC().Add(-time.Minute).Format(time.RFC3339)

	storeReq := httptest.NewRequest(http.MethodPost, "/api/credentials", bytes.NewBufferString(`{"name":"expired-key","type":"api_key","expires_at":"`+expiredAt+`"}`))
	storeReq.Header.Set("Authorization", "Bearer "+token)
	storeReq.Header.Set("X-Credential-Value", "expired-secret")
	storeRec := httptest.NewRecorder()
	handler.ServeHTTP(storeRec, storeReq)
	if storeRec.Code != http.StatusCreated {
		t.Fatalf("store status = %d, body = %s", storeRec.Code, storeRec.Body.String())
	}
	var created credentialResponse
	if err := json.Unmarshal(storeRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode store response: %v", err)
	}
	if created.ExpiresAt != expiredAt || created.Status != "expired" {
		t.Fatalf("unexpected expiry response: %+v", created)
	}

	listReq := httptest.NewRequest(http.MethodGet, "/api/credentials", nil)
	listReq.Header.Set("Authorization", "Bearer "+token)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)
	if listRec.Code != http.StatusOK {
		t.Fatalf("list status = %d, body = %s", listRec.Code, listRec.Body.String())
	}
	if !strings.Contains(listRec.Body.String(), `"status":"expired"`) || strings.Contains(listRec.Body.String(), "expired-secret") {
		t.Fatalf("list did not expose expired status safely: %s", listRec.Body.String())
	}

	useReq := httptest.NewRequest(http.MethodPost, "/api/credentials/"+strconv.Itoa(created.ID)+"/use", nil)
	useReq.Header.Set("Authorization", "Bearer "+token)
	useRec := httptest.NewRecorder()
	handler.ServeHTTP(useRec, useReq)
	if useRec.Code != http.StatusConflict {
		t.Fatalf("expired use status = %d, body = %s", useRec.Code, useRec.Body.String())
	}
	if got := useRec.Header().Get("X-Distributed-Credential"); got != "" {
		t.Fatalf("expired credential leaked secret: %q", got)
	}
	if !strings.Contains(useRec.Body.String(), "credential_expired") {
		t.Fatalf("expired use body = %s", useRec.Body.String())
	}

	var auditCount int
	if err := db.QueryRow(`SELECT COUNT(*) FROM audit_logs WHERE action_type = 'credentials.use' AND actor_id = 'owner' AND resource_type = 'credential' AND resource_id = ? AND policy_decision = 'deny' AND policy_id = ?`, strconv.Itoa(created.ID), "credential_expired:"+strconv.Itoa(created.ID)).Scan(&auditCount); err != nil {
		t.Fatalf("read expired audit logs: %v", err)
	}
	if auditCount != 1 {
		t.Fatalf("expired use audit log count = %d", auditCount)
	}
}

func TestCredentialsRejectInvalidExpiry(t *testing.T) {
	db := openCredentialsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt, audit.NewWriter(db))
	token := issueCredentialsToken(t, jwt, "owner", []string{"employee"})

	storeReq := httptest.NewRequest(http.MethodPost, "/api/credentials", bytes.NewBufferString(`{"name":"bad-expiry","type":"api_key","expires_at":"tomorrow"}`))
	storeReq.Header.Set("Authorization", "Bearer "+token)
	storeReq.Header.Set("X-Credential-Value", "secret")
	storeRec := httptest.NewRecorder()
	handler.ServeHTTP(storeRec, storeReq)
	if storeRec.Code != http.StatusBadRequest {
		t.Fatalf("invalid expires_at status = %d, body = %s", storeRec.Code, storeRec.Body.String())
	}

	negativeReq := httptest.NewRequest(http.MethodPost, "/api/credentials", bytes.NewBufferString(`{"name":"negative-expiry","type":"api_key","expires_in_minutes":-1}`))
	negativeReq.Header.Set("Authorization", "Bearer "+token)
	negativeReq.Header.Set("X-Credential-Value", "secret")
	negativeRec := httptest.NewRecorder()
	handler.ServeHTTP(negativeRec, negativeReq)
	if negativeRec.Code != http.StatusBadRequest {
		t.Fatalf("negative expires_in_minutes status = %d, body = %s", negativeRec.Code, negativeRec.Body.String())
	}
}

func TestCredentialsDeleteRemovesCredentialAndAudits(t *testing.T) {
	db := openCredentialsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt, audit.NewWriter(db))
	token := issueCredentialsToken(t, jwt, "owner", []string{"employee"})

	credID := storeCredential(t, handler, token, "delete-key", "delete-secret")

	deleteReq := httptest.NewRequest(http.MethodDelete, "/api/credentials/"+strconv.FormatInt(credID, 10), nil)
	deleteReq.Header.Set("Authorization", "Bearer "+token)
	deleteRec := httptest.NewRecorder()
	handler.ServeHTTP(deleteRec, deleteReq)

	if deleteRec.Code != http.StatusNoContent {
		t.Fatalf("delete status = %d, body = %s", deleteRec.Code, deleteRec.Body.String())
	}

	useReq := httptest.NewRequest(http.MethodPost, "/api/credentials/"+strconv.FormatInt(credID, 10)+"/use", nil)
	useReq.Header.Set("Authorization", "Bearer "+token)
	useRec := httptest.NewRecorder()
	handler.ServeHTTP(useRec, useReq)
	if useRec.Code != http.StatusNotFound {
		t.Fatalf("use after delete status = %d, body = %s", useRec.Code, useRec.Body.String())
	}

	var auditCount int
	if err := db.QueryRow(`SELECT COUNT(*) FROM audit_logs WHERE action_type = 'credentials.delete' AND actor_id = 'owner' AND resource_type = 'credential' AND resource_id = ? AND policy_decision = 'allow'`, strconv.FormatInt(credID, 10)).Scan(&auditCount); err != nil {
		t.Fatalf("read delete audit logs: %v", err)
	}
	if auditCount != 1 {
		t.Fatalf("delete audit log count = %d", auditCount)
	}
}

func TestCredentialsUseRejectsNonOwner(t *testing.T) {
	db := openCredentialsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt, audit.NewWriter(db))
	ownerToken := issueCredentialsToken(t, jwt, "owner", []string{"employee"})
	otherToken := issueCredentialsToken(t, jwt, "other", []string{"employee"})

	storeReq := httptest.NewRequest(http.MethodPost, "/api/credentials", bytes.NewBufferString(`{"name":"private-key","type":"api_key"}`))
	storeReq.Header.Set("Authorization", "Bearer "+ownerToken)
	storeReq.Header.Set("X-Credential-Value", "secret")
	storeRec := httptest.NewRecorder()
	handler.ServeHTTP(storeRec, storeReq)
	if storeRec.Code != http.StatusCreated {
		t.Fatalf("store status = %d, body = %s", storeRec.Code, storeRec.Body.String())
	}

	useReq := httptest.NewRequest(http.MethodPost, "/api/credentials/1/use", nil)
	useReq.Header.Set("Authorization", "Bearer "+otherToken)
	useRec := httptest.NewRecorder()
	handler.ServeHTTP(useRec, useReq)

	if useRec.Code != http.StatusForbidden {
		t.Fatalf("use status = %d, body = %s", useRec.Code, useRec.Body.String())
	}
	if got := useRec.Header().Get("X-Distributed-Credential"); got != "" {
		t.Fatalf("non-owner received credential: %q", got)
	}
}

func TestCredentialsDeleteRejectsNonOwner(t *testing.T) {
	db := openCredentialsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt, audit.NewWriter(db))
	ownerToken := issueCredentialsToken(t, jwt, "owner", []string{"employee"})
	otherToken := issueCredentialsToken(t, jwt, "other", []string{"employee"})

	credID := storeCredential(t, handler, ownerToken, "private-delete-key", "secret")

	deleteReq := httptest.NewRequest(http.MethodDelete, "/api/credentials/"+strconv.FormatInt(credID, 10), nil)
	deleteReq.Header.Set("Authorization", "Bearer "+otherToken)
	deleteRec := httptest.NewRecorder()
	handler.ServeHTTP(deleteRec, deleteReq)

	if deleteRec.Code != http.StatusForbidden {
		t.Fatalf("delete status = %d, body = %s", deleteRec.Code, deleteRec.Body.String())
	}
}

func TestCredentialsAdminCanUseAnyCredential(t *testing.T) {
	db := openCredentialsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt, audit.NewWriter(db))
	ownerToken := issueCredentialsToken(t, jwt, "owner", []string{"employee"})
	adminToken := issueCredentialsToken(t, jwt, "admin", []string{"hanhe_admin"})

	storeReq := httptest.NewRequest(http.MethodPost, "/api/credentials", bytes.NewBufferString(`{"name":"admin-key","type":"api_key"}`))
	storeReq.Header.Set("Authorization", "Bearer "+ownerToken)
	storeReq.Header.Set("X-Credential-Value", "admin-secret")
	storeRec := httptest.NewRecorder()
	handler.ServeHTTP(storeRec, storeReq)
	if storeRec.Code != http.StatusCreated {
		t.Fatalf("store status = %d, body = %s", storeRec.Code, storeRec.Body.String())
	}

	useReq := httptest.NewRequest(http.MethodPost, "/api/credentials/1/use", nil)
	useReq.Header.Set("Authorization", "Bearer "+adminToken)
	useRec := httptest.NewRecorder()
	handler.ServeHTTP(useRec, useReq)

	if useRec.Code != http.StatusNotImplemented {
		t.Fatalf("admin use status = %d, body = %s", useRec.Code, useRec.Body.String())
	}
	if got := useRec.Header().Get("X-Distributed-Credential"); got != "" {
		t.Fatalf("credential must never be returned = %q", got)
	}
}

func TestCredentialsAdminCanDeleteAnyCredential(t *testing.T) {
	db := openCredentialsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt, audit.NewWriter(db))
	ownerToken := issueCredentialsToken(t, jwt, "owner", []string{"employee"})
	adminToken := issueCredentialsToken(t, jwt, "admin", []string{"hanhe_admin"})

	credID := storeCredential(t, handler, ownerToken, "admin-delete-key", "admin-secret")

	deleteReq := httptest.NewRequest(http.MethodDelete, "/api/credentials/"+strconv.FormatInt(credID, 10), nil)
	deleteReq.Header.Set("Authorization", "Bearer "+adminToken)
	deleteRec := httptest.NewRecorder()
	handler.ServeHTTP(deleteRec, deleteReq)

	if deleteRec.Code != http.StatusNoContent {
		t.Fatalf("admin delete status = %d, body = %s", deleteRec.Code, deleteRec.Body.String())
	}
}

func TestCredentialsTenantIsolationForAdminAndOwner(t *testing.T) {
	db := openCredentialsTestDB(t)
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewHandler(db, jwt, audit.NewWriter(db))
	tenantAToken := issueCredentialsTokenForOrg(t, jwt, "owner-a", "tenant-a", []string{"employee"})
	tenantAAdmin := issueCredentialsTokenForOrg(t, jwt, "admin-a", "tenant-a", []string{"hanhe_admin"})
	tenantBAdmin := issueCredentialsTokenForOrg(t, jwt, "admin-b", "tenant-b", []string{"hanhe_admin"})

	credID := storeCredential(t, handler, tenantAToken, "tenant-key", "tenant-secret")

	listBReq := httptest.NewRequest(http.MethodGet, "/api/credentials", nil)
	listBReq.Header.Set("Authorization", "Bearer "+tenantBAdmin)
	listBRec := httptest.NewRecorder()
	handler.ServeHTTP(listBRec, listBReq)
	if listBRec.Code != http.StatusOK {
		t.Fatalf("tenant b list status = %d body = %s", listBRec.Code, listBRec.Body.String())
	}
	var listB struct {
		Credentials []credentialResponse `json:"credentials"`
	}
	if err := json.Unmarshal(listBRec.Body.Bytes(), &listB); err != nil {
		t.Fatalf("decode tenant b list: %v", err)
	}
	if len(listB.Credentials) != 0 {
		t.Fatalf("tenant b saw credentials: %+v", listB.Credentials)
	}

	useBReq := httptest.NewRequest(http.MethodPost, "/api/credentials/"+strconv.FormatInt(credID, 10)+"/use", nil)
	useBReq.Header.Set("Authorization", "Bearer "+tenantBAdmin)
	useBRec := httptest.NewRecorder()
	handler.ServeHTTP(useBRec, useBReq)
	if useBRec.Code != http.StatusNotFound {
		t.Fatalf("tenant b use status = %d body = %s", useBRec.Code, useBRec.Body.String())
	}

	deleteBReq := httptest.NewRequest(http.MethodDelete, "/api/credentials/"+strconv.FormatInt(credID, 10), nil)
	deleteBReq.Header.Set("Authorization", "Bearer "+tenantBAdmin)
	deleteBRec := httptest.NewRecorder()
	handler.ServeHTTP(deleteBRec, deleteBReq)
	if deleteBRec.Code != http.StatusNotFound {
		t.Fatalf("tenant b delete status = %d body = %s", deleteBRec.Code, deleteBRec.Body.String())
	}

	useAReq := httptest.NewRequest(http.MethodPost, "/api/credentials/"+strconv.FormatInt(credID, 10)+"/use", nil)
	useAReq.Header.Set("Authorization", "Bearer "+tenantAAdmin)
	useARec := httptest.NewRecorder()
	handler.ServeHTTP(useARec, useAReq)
	if useARec.Code != http.StatusNotImplemented {
		t.Fatalf("tenant a admin use status = %d body = %s", useARec.Code, useARec.Body.String())
	}
	if got := useARec.Header().Get("X-Distributed-Credential"); got != "" {
		t.Fatalf("tenant a admin credential must never be returned = %q", got)
	}
}

func storeCredential(t *testing.T, handler *Handler, token, name, secret string) int64 {
	t.Helper()
	storeReq := httptest.NewRequest(http.MethodPost, "/api/credentials", bytes.NewBufferString(`{"name":"`+name+`","type":"api_key"}`))
	storeReq.Header.Set("Authorization", "Bearer "+token)
	storeReq.Header.Set("X-Credential-Value", secret)
	storeRec := httptest.NewRecorder()
	handler.ServeHTTP(storeRec, storeReq)
	if storeRec.Code != http.StatusCreated {
		t.Fatalf("store status = %d, body = %s", storeRec.Code, storeRec.Body.String())
	}

	var storeResp struct {
		ID int64 `json:"id"`
	}
	if err := json.Unmarshal(storeRec.Body.Bytes(), &storeResp); err != nil {
		t.Fatalf("decode store response: %v", err)
	}
	return storeResp.ID
}

func openCredentialsTestDB(t *testing.T) *sql.DB {
	t.Helper()
	t.Setenv("CREDENTIALS_ENCRYPTION_KEY", testEncryptionKey)

	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	db.SetMaxOpenConns(1)
	t.Cleanup(func() {
		_ = db.Close()
	})
	if err := audit.EnsureSchema(db); err != nil {
		t.Fatalf("ensure audit schema: %v", err)
	}

	return db
}

func issueCredentialsToken(t *testing.T, jwt *auth.JWTManager, userID string, roles []string) string {
	t.Helper()
	return issueCredentialsTokenForOrg(t, jwt, userID, "org-1", roles)
}

func issueCredentialsTokenForOrg(t *testing.T, jwt *auth.JWTManager, userID string, orgID string, roles []string) string {
	t.Helper()
	token, err := jwt.Issue(userID, orgID, roles)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	return token
}

func TestMain(m *testing.M) {
	os.Exit(m.Run())
}
