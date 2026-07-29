package account

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/auth"
)

func TestAccountMutationsRequireBearerAndManager(t *testing.T) {
	handler, jwt := newMockHandler(t)

	unauthenticated := doAccountRequest(t, handler, http.MethodPost, "/api/accounts", accountBody("user-no-token"), "")
	if unauthenticated.Code != http.StatusUnauthorized {
		t.Fatalf("unauthenticated create status = %d, want %d", unauthenticated.Code, http.StatusUnauthorized)
	}

	staff := doAccountRequest(t, handler, http.MethodPost, "/api/accounts", accountBody("user-staff"), bearer(t, jwt, "staff-user", []string{"staff"}))
	if staff.Code != http.StatusForbidden {
		t.Fatalf("staff create status = %d, want %d", staff.Code, http.StatusForbidden)
	}
	assertError(t, staff, "admin_or_operator_only")

	operator := doAccountRequest(t, handler, http.MethodPost, "/api/accounts", accountBody("user-operator"), bearer(t, jwt, "operator-user", []string{"operator"}))
	if operator.Code != http.StatusCreated {
		t.Fatalf("operator create status = %d, want %d; body=%s", operator.Code, http.StatusCreated, operator.Body.String())
	}
}

func TestRegularUserCanOnlyReadSelf(t *testing.T) {
	handler, jwt := newMockHandler(t)
	admin := bearer(t, jwt, "admin-user", []string{"hanhe_admin"})
	createAccountForTest(t, handler, admin, "alice")
	createAccountForTest(t, handler, admin, "bob")

	aliceToken := bearer(t, jwt, "alice", []string{"staff"})
	implicitSelf := doAccountRequest(t, handler, http.MethodGet, "/api/accounts", nil, aliceToken)
	assertAccountList(t, implicitSelf, []string{"alice"})

	explicitSelf := doAccountRequest(t, handler, http.MethodGet, "/api/accounts?name=alice", nil, aliceToken)
	assertAccountList(t, explicitSelf, []string{"alice"})

	other := doAccountRequest(t, handler, http.MethodGet, "/api/accounts?name=bob", nil, aliceToken)
	if other.Code != http.StatusForbidden {
		t.Fatalf("read other account status = %d, want %d", other.Code, http.StatusForbidden)
	}
	assertError(t, other, "unauthorized")
}

func TestDeleteChecksOwnershipBeforeRemoval(t *testing.T) {
	handler, jwt := newMockHandler(t)
	admin := bearer(t, jwt, "admin-user", []string{"hanhe_admin"})
	createAccountForTest(t, handler, admin, "user_li")

	blocked := doAccountRequest(t, handler, http.MethodDelete, "/api/accounts?name=user_li", nil, admin)
	if blocked.Code != http.StatusConflict {
		t.Fatalf("delete owned account status = %d, want %d; body=%s", blocked.Code, http.StatusConflict, blocked.Body.String())
	}
	assertError(t, blocked, ErrOwnershipBlocked.Error())

	stillPresent := doAccountRequest(t, handler, http.MethodGet, "/api/accounts?name=user_li", nil, admin)
	assertAccountList(t, stillPresent, []string{"user_li"})
}

func TestAccountFreezeHandoverRequiredBeforeDelete(t *testing.T) {
	handler, jwt := newMockHandler(t)
	freezer := &recordingAssetFreezer{summary: AssetFreezeSummary{Resources: 2, DataRecords: 1, DigitalEmployees: 3}}
	handler.WithAssetFreezer(freezer)
	handler.WithAssetInventory(&recordingAssetInventory{assets: OffboardingAssets{
		UserID:   "leaver",
		TenantID: "test-org",
		Resources: []OffboardingResource{{
			ID:           "skill-leaver",
			Name:         "Leaver Skill",
			ResourceType: "skill",
			Status:       "frozen",
			AssetPool:    "offboarding",
			LockedBy:     "admin-user",
			LockedAt:     "2026-07-10T00:00:00Z",
		}},
		DataRecords:      []OffboardingDataRecord{},
		DigitalEmployees: []OffboardingDigitalEmployee{},
	}})
	admin := bearer(t, jwt, "admin-user", []string{"hanhe_admin"})
	createAccountForTest(t, handler, admin, "leaver")

	viewBeforeFreeze := doAccountRequest(t, handler, http.MethodGet, "/api/accounts/leaver/offboarding-assets", nil, admin)
	if viewBeforeFreeze.Code != http.StatusConflict {
		t.Fatalf("view before freeze status = %d, want %d; body=%s", viewBeforeFreeze.Code, http.StatusConflict, viewBeforeFreeze.Body.String())
	}
	assertError(t, viewBeforeFreeze, ErrAccountNotFrozen.Error())

	confirmWithoutFreeze := doAccountRequest(t, handler, http.MethodPost, "/api/accounts/leaver/handover-confirm", nil, admin)
	if confirmWithoutFreeze.Code != http.StatusConflict {
		t.Fatalf("handover before freeze status = %d, want %d; body=%s", confirmWithoutFreeze.Code, http.StatusConflict, confirmWithoutFreeze.Body.String())
	}
	assertError(t, confirmWithoutFreeze, ErrAccountNotFrozen.Error())

	frozen := doAccountRequest(t, handler, http.MethodPost, "/api/accounts/leaver/freeze", nil, admin)
	if frozen.Code != http.StatusOK {
		t.Fatalf("freeze status = %d, want %d; body=%s", frozen.Code, http.StatusOK, frozen.Body.String())
	}
	var frozenAccount Account
	if err := json.Unmarshal(frozen.Body.Bytes(), &frozenAccount); err != nil {
		t.Fatalf("decode frozen account: %v", err)
	}
	if !frozenAccount.IsForbidden || frozenAccount.Properties["lifecycle_state"] != "frozen" || frozenAccount.Properties["handover_confirmed"] != "false" {
		t.Fatalf("unexpected frozen account: %+v", frozenAccount)
	}
	if frozenAccount.Properties["frozen_resources"] != "2" || frozenAccount.Properties["frozen_data_records"] != "1" || frozenAccount.Properties["frozen_digital_employees"] != "3" {
		t.Fatalf("unexpected frozen asset counts: %+v", frozenAccount.Properties)
	}
	if freezer.userID != "leaver" || freezer.tenantID != "test-org" || freezer.actor != "admin-user" {
		t.Fatalf("unexpected freezer call: %+v", freezer)
	}

	viewAssets := doAccountRequest(t, handler, http.MethodGet, "/api/accounts/leaver/offboarding-assets", nil, admin)
	if viewAssets.Code != http.StatusOK {
		t.Fatalf("view assets status = %d, want %d; body=%s", viewAssets.Code, http.StatusOK, viewAssets.Body.String())
	}
	var assets OffboardingAssets
	if err := json.Unmarshal(viewAssets.Body.Bytes(), &assets); err != nil {
		t.Fatalf("decode offboarding assets: %v", err)
	}
	if assets.UserID != "leaver" || assets.TenantID != "test-org" || len(assets.Resources) != 1 || assets.Resources[0].AssetPool != "offboarding" {
		t.Fatalf("unexpected offboarding assets: %+v", assets)
	}

	blocked := doAccountRequest(t, handler, http.MethodDelete, "/api/accounts?name=leaver", nil, admin)
	if blocked.Code != http.StatusConflict {
		t.Fatalf("delete before handover status = %d, want %d; body=%s", blocked.Code, http.StatusConflict, blocked.Body.String())
	}
	assertError(t, blocked, ErrHandoverRequired.Error())

	confirmed := doAccountRequest(t, handler, http.MethodPost, "/api/accounts/leaver/handover-confirm", []byte(`{"handover_to_user_id":"successor","note":"assets checked"}`), admin)
	if confirmed.Code != http.StatusOK {
		t.Fatalf("handover confirm status = %d, want %d; body=%s", confirmed.Code, http.StatusOK, confirmed.Body.String())
	}
	var confirmedAccount Account
	if err := json.Unmarshal(confirmed.Body.Bytes(), &confirmedAccount); err != nil {
		t.Fatalf("decode confirmed account: %v", err)
	}
	if confirmedAccount.Properties["handover_confirmed"] != "true" || confirmedAccount.Properties["lifecycle_state"] != "handover_confirmed" {
		t.Fatalf("unexpected confirmed account: %+v", confirmedAccount)
	}
	if confirmedAccount.Properties["handover_to_user_id"] != "successor" || confirmedAccount.Properties["handover_note"] != "assets checked" {
		t.Fatalf("unexpected handover details: %+v", confirmedAccount.Properties)
	}

	deleted := doAccountRequest(t, handler, http.MethodDelete, "/api/accounts?name=leaver", nil, admin)
	if deleted.Code != http.StatusNoContent {
		t.Fatalf("delete after handover status = %d, want %d; body=%s", deleted.Code, http.StatusNoContent, deleted.Body.String())
	}
	assertAccountList(t, doAccountRequest(t, handler, http.MethodGet, "/api/accounts?name=leaver", nil, admin), []string{})
}

func TestAccountsAreIsolatedByTenant(t *testing.T) {
	handler, jwt := newMockHandler(t)
	adminA := bearerForOrg(t, jwt, "admin-a", "tenant-a", []string{"hanhe_admin"})
	adminB := bearerForOrg(t, jwt, "admin-b", "tenant-b", []string{"hanhe_admin"})
	createAccountForTest(t, handler, adminA, "tenant-a-user")

	listB := doAccountRequest(t, handler, http.MethodGet, "/api/accounts", nil, adminB)
	assertAccountList(t, listB, []string{})

	getB := doAccountRequest(t, handler, http.MethodGet, "/api/accounts?name=tenant-a-user", nil, adminB)
	assertAccountList(t, getB, []string{})

	updateB := doAccountRequest(t, handler, http.MethodPatch, "/api/accounts?name=tenant-a-user", []byte(`{"status":"inactive"}`), adminB)
	if updateB.Code != http.StatusNotFound {
		t.Fatalf("cross-tenant update status = %d, want %d; body=%s", updateB.Code, http.StatusNotFound, updateB.Body.String())
	}
	assertError(t, updateB, "account_not_found")

	deleteB := doAccountRequest(t, handler, http.MethodDelete, "/api/accounts?name=tenant-a-user", nil, adminB)
	if deleteB.Code != http.StatusNotFound {
		t.Fatalf("cross-tenant delete status = %d, want %d; body=%s", deleteB.Code, http.StatusNotFound, deleteB.Body.String())
	}
	assertError(t, deleteB, "account_not_found")

	listA := doAccountRequest(t, handler, http.MethodGet, "/api/accounts", nil, adminA)
	assertAccountList(t, listA, []string{"tenant-a-user"})
}

func TestAccountUpdatePreservesTenantID(t *testing.T) {
	handler, jwt := newMockHandler(t)
	admin := bearerForOrg(t, jwt, "admin-a", "tenant-a", []string{"hanhe_admin"})
	createAccountForTest(t, handler, admin, "tenant-user")

	update := doAccountRequest(t, handler, http.MethodPatch, "/api/accounts?name=tenant-user", []byte(`{"properties":{"tenant_id":"tenant-b","team":"sales"}}`), admin)
	if update.Code != http.StatusOK {
		t.Fatalf("update status = %d, want %d; body=%s", update.Code, http.StatusOK, update.Body.String())
	}

	var account Account
	if err := json.Unmarshal(update.Body.Bytes(), &account); err != nil {
		t.Fatalf("decode account: %v", err)
	}
	if account.Properties["tenant_id"] != "tenant-a" {
		t.Fatalf("tenant_id = %q, want tenant-a", account.Properties["tenant_id"])
	}
	if account.Properties["team"] != "sales" {
		t.Fatalf("team property = %q, want sales", account.Properties["team"])
	}
}

func newMockHandler(t *testing.T) (*Handler, *auth.JWTManager) {
	t.Helper()
	t.Setenv("CASDOOR_MOCK_OIDC", "1")
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	return NewHandler(jwt, nil), jwt
}

func createAccountForTest(t *testing.T, handler http.Handler, token string, name string) {
	t.Helper()
	response := doAccountRequest(t, handler, http.MethodPost, "/api/accounts", accountBody(name), token)
	if response.Code != http.StatusCreated {
		t.Fatalf("create %s status = %d, want %d; body=%s", name, response.Code, http.StatusCreated, response.Body.String())
	}
}

func doAccountRequest(t *testing.T, handler http.Handler, method string, target string, body []byte, authorization string) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(method, target, bytes.NewReader(body))
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	if authorization != "" {
		request.Header.Set("Authorization", authorization)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func accountBody(name string) []byte {
	payload := Account{
		Name:        name,
		Password:    "123",
		DisplayName: name,
		Email:       name + "@hanhe.local",
		Roles:       []string{"staff"},
	}
	body, _ := json.Marshal(payload)
	return body
}

func bearer(t *testing.T, jwt *auth.JWTManager, userID string, roles []string) string {
	t.Helper()
	return bearerForOrg(t, jwt, userID, "test-org", roles)
}

func bearerForOrg(t *testing.T, jwt *auth.JWTManager, userID string, orgID string, roles []string) string {
	t.Helper()
	token, err := jwt.Issue(userID, orgID, roles)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	return "Bearer " + token
}

func assertAccountList(t *testing.T, response *httptest.ResponseRecorder, names []string) {
	t.Helper()
	if response.Code != http.StatusOK {
		t.Fatalf("account list status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body.String())
	}
	var accounts []Account
	if err := json.Unmarshal(response.Body.Bytes(), &accounts); err != nil {
		t.Fatalf("decode account list: %v", err)
	}
	if len(accounts) != len(names) {
		t.Fatalf("account list length = %d, want %d; body=%s", len(accounts), len(names), response.Body.String())
	}
	for index, name := range names {
		if accounts[index].Name != name {
			t.Fatalf("account[%d].Name = %q, want %q", index, accounts[index].Name, name)
		}
	}
}

func assertError(t *testing.T, response *httptest.ResponseRecorder, want string) {
	t.Helper()
	var payload errorResponse
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode error response: %v; body=%s", err, response.Body.String())
	}
	if payload.Error != want {
		t.Fatalf("error = %q, want %q", payload.Error, want)
	}
}

type recordingAssetFreezer struct {
	summary  AssetFreezeSummary
	userID   string
	tenantID string
	actor    string
}

func (f *recordingAssetFreezer) FreezeAssetsForUser(userID, tenantID, actor string) (AssetFreezeSummary, error) {
	f.userID = userID
	f.tenantID = tenantID
	f.actor = actor
	return f.summary, nil
}

type recordingAssetInventory struct {
	userID   string
	tenantID string
	assets   OffboardingAssets
}

func (i *recordingAssetInventory) OffboardingAssetsForUser(userID, tenantID string) (OffboardingAssets, error) {
	i.userID = userID
	i.tenantID = tenantID
	return i.assets, nil
}
