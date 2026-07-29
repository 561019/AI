package account

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/policy"
)

const (
	defaultCasdoorURL   = "http://127.0.0.1:8000"
	defaultOwnershipURL = "http://127.0.0.1:9101"
	defaultOwner        = "hanhe"
	defaultType         = "normal"
	defaultSignupApp    = "app-built-in"
)

var (
	ErrBadRequest       = errors.New("bad request")
	ErrOwnershipBlocked = errors.New("account owns resources")
	ErrHandoverRequired = errors.New("account handover not confirmed")
	ErrAccountNotFrozen = errors.New("account not frozen")
)

type AssetFreezer interface {
	FreezeAssetsForUser(userID, tenantID, actor string) (AssetFreezeSummary, error)
}

type AssetInventory interface {
	OffboardingAssetsForUser(userID, tenantID string) (OffboardingAssets, error)
}

type AssetFreezeSummary struct {
	Resources        int `json:"resources"`
	DataRecords      int `json:"data_records"`
	DigitalEmployees int `json:"digital_employees"`
}

type OffboardingAssets struct {
	UserID           string                       `json:"user_id"`
	TenantID         string                       `json:"tenant_id"`
	Resources        []OffboardingResource        `json:"resources"`
	DataRecords      []OffboardingDataRecord      `json:"data_records"`
	DigitalEmployees []OffboardingDigitalEmployee `json:"digital_employees"`
}

type OffboardingResource struct {
	ID           string `json:"id"`
	Name         string `json:"name"`
	ResourceType string `json:"resource_type"`
	Status       string `json:"status"`
	AssetPool    string `json:"asset_pool,omitempty"`
	LockedBy     string `json:"locked_by,omitempty"`
	LockedAt     string `json:"locked_at,omitempty"`
}

type OffboardingDataRecord struct {
	ID        string `json:"id"`
	Title     string `json:"title"`
	Status    string `json:"status"`
	AssetPool string `json:"asset_pool,omitempty"`
	LockedBy  string `json:"locked_by,omitempty"`
	LockedAt  string `json:"locked_at,omitempty"`
}

type OffboardingDigitalEmployee struct {
	Name       string `json:"name"`
	Status     string `json:"status"`
	DisabledAt string `json:"disabled_at,omitempty"`
}

type Handler struct {
	client         *http.Client
	casdoorURL     string
	ownershipURL   string
	owner          string
	mockMode       bool
	mockMu         sync.Mutex
	mockAccounts   map[string]Account
	jwt            *auth.JWTManager
	audit          *audit.Writer
	assetFreezer   AssetFreezer
	assetInventory AssetInventory
}

type Account struct {
	Owner             string            `json:"owner,omitempty"`
	Name              string            `json:"name"`
	ID                string            `json:"id,omitempty"`
	Type              string            `json:"type,omitempty"`
	Password          string            `json:"password,omitempty"`
	DisplayName       string            `json:"displayName,omitempty"`
	Email             string            `json:"email,omitempty"`
	SignupApplication string            `json:"signupApplication,omitempty"`
	Roles             []string          `json:"roles,omitempty"`
	Properties        map[string]string `json:"properties,omitempty"`
	IsForbidden       bool              `json:"isForbidden"`
	IsDeleted         bool              `json:"isDeleted"`
}

func (h *Handler) WithAssetFreezer(freezer AssetFreezer) *Handler {
	h.assetFreezer = freezer
	if inventory, ok := freezer.(AssetInventory); ok {
		h.assetInventory = inventory
	}
	return h
}

func (h *Handler) WithAssetInventory(inventory AssetInventory) *Handler {
	h.assetInventory = inventory
	return h
}

type accountPatch struct {
	DisplayName *string           `json:"displayName"`
	Email       *string           `json:"email"`
	Roles       *[]string         `json:"roles"`
	Status      *string           `json:"status"`
	Properties  map[string]string `json:"properties"`
}

type errorResponse struct {
	Error string `json:"error"`
}

type ownershipResource struct {
	ResourceID string `json:"resource_id"`
	OwnerID    string `json:"owner_id"`
}

type ownershipByUserResponse struct {
	UserID    string              `json:"user_id"`
	Resources []ownershipResource `json:"resources"`
}

type ownershipBlockedResponse struct {
	Error     string              `json:"error"`
	Resources []ownershipResource `json:"resources"`
}

type handoverBlockedResponse struct {
	Error string `json:"error"`
	State string `json:"lifecycle_state"`
}

type handoverRequest struct {
	HandoverToUserID string `json:"handover_to_user_id"`
	Note             string `json:"note"`
}

type casdoorResponse struct {
	Status string          `json:"status"`
	Msg    string          `json:"msg"`
	Data   json.RawMessage `json:"data"`
}

func NewHandler(jwt *auth.JWTManager, auditWriter *audit.Writer) *Handler {
	return &Handler{
		client:       &http.Client{Timeout: 5 * time.Second},
		casdoorURL:   envURL("CASDOOR_URL", defaultCasdoorURL),
		ownershipURL: envURL("OWNERSHIP_URL", defaultOwnershipURL),
		owner:        envString("CASDOOR_OWNER", defaultOwner),
		mockMode:     os.Getenv("CASDOOR_MOCK_OIDC") == "1",
		mockAccounts: map[string]Account{},
		jwt:          jwt,
		audit:        auditWriter,
	}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}

	if strings.HasPrefix(strings.TrimRight(r.URL.Path, "/"), "/api/accounts/") {
		h.action(w, r, claims)
		return
	}

	switch r.Method {
	case http.MethodPost:
		if !canManageAccounts(claims) {
			writeError(w, http.StatusForbidden, "admin_or_operator_only")
			return
		}
		h.create(w, r, claims)
	case http.MethodGet:
		h.read(w, r, claims)
	case http.MethodPatch:
		if !canManageAccounts(claims) {
			writeError(w, http.StatusForbidden, "admin_or_operator_only")
			return
		}
		h.update(w, r, claims)
	case http.MethodDelete:
		if !canManageAccounts(claims) {
			writeError(w, http.StatusForbidden, "admin_or_operator_only")
			return
		}
		h.delete(w, r, claims)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) action(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if !canManageAccounts(claims) {
		writeError(w, http.StatusForbidden, "admin_or_operator_only")
		return
	}
	name, action, ok := accountActionPath(r.URL.Path)
	if !ok {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	switch action {
	case "freeze":
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		h.freeze(w, r, claims, name)
	case "handover-confirm":
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		h.confirmHandover(w, r, claims, name)
	case "offboarding-assets":
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		h.offboardingAssets(w, r, claims, name)
	default:
		w.WriteHeader(http.StatusNotFound)
	}
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	var account Account
	if err := decodeJSON(r.Body, &account); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	if err := h.normalizeAccount(&account); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	account.Properties["tenant_id"] = strings.TrimSpace(claims.OrgID)
	if h.mockMode {
		h.mockMu.Lock()
		h.mockAccounts[account.Name] = cloneAccount(account)
		h.mockMu.Unlock()

		h.logAccountAction(r, "accounts.create", claims, account.Name, policy.Decision{Allow: true, PolicyID: "account_create"})
		writeJSON(w, http.StatusCreated, account)
		return
	}

	if err := h.casdoorPost("/api/add-user", nil, account); err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}

	h.logAccountAction(r, "accounts.create", claims, account.Name, policy.Decision{Allow: true, PolicyID: "account_create"})
	writeJSON(w, http.StatusCreated, account)
}

func (h *Handler) read(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	name := strings.TrimSpace(r.URL.Query().Get("name"))
	if !canManageAccounts(claims) {
		if name == "" {
			name = claims.UserID
		}
		if name != claims.UserID {
			writeError(w, http.StatusForbidden, "unauthorized")
			return
		}
	}
	if h.mockMode {
		writeJSON(w, http.StatusOK, h.mockAccountList(name, claims.OrgID))
		return
	}

	query := url.Values{"owner": []string{h.owner}}
	if name != "" {
		query.Set("id", h.owner+"/"+name)
	}

	var body json.RawMessage
	if err := h.casdoorGet("/api/get-users", query, &body); err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}

	filtered, err := filterAccountJSONByTenant(body, claims.OrgID)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, filtered)
}

func (h *Handler) update(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	name := strings.TrimSpace(r.URL.Query().Get("name"))
	if name == "" {
		writeError(w, http.StatusBadRequest, "missing_name")
		return
	}
	if h.mockMode {
		current, ok := h.mockAccount(name)
		if !ok {
			writeError(w, http.StatusNotFound, "account_not_found")
			return
		}
		if !sameTenant(current.Properties["tenant_id"], claims.OrgID) {
			writeError(w, http.StatusNotFound, "account_not_found")
			return
		}

		var patch accountPatch
		if err := decodeJSON(r.Body, &patch); err != nil {
			writeError(w, http.StatusBadRequest, "invalid_json")
			return
		}
		if err := applyPatch(&current, patch); err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
		ensureAccountTenant(&current, claims.OrgID)

		h.mockMu.Lock()
		h.mockAccounts[name] = cloneAccount(current)
		h.mockMu.Unlock()

		h.logAccountAction(r, "accounts.update", claims, name, policy.Decision{Allow: true, PolicyID: "account_update"})
		writeJSON(w, http.StatusOK, current)
		return
	}

	current, err := h.getAccount(name)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	if !sameTenant(current.Properties["tenant_id"], claims.OrgID) {
		writeError(w, http.StatusNotFound, "account_not_found")
		return
	}

	var patch accountPatch
	if err := decodeJSON(r.Body, &patch); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	if err := applyPatch(&current, patch); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	ensureAccountTenant(&current, claims.OrgID)

	query := url.Values{"id": []string{h.owner + "/" + name}}
	if err := h.casdoorPost("/api/update-user", query, current); err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}

	h.logAccountAction(r, "accounts.update", claims, name, policy.Decision{Allow: true, PolicyID: "account_update"})
	writeJSON(w, http.StatusOK, current)
}

func (h *Handler) delete(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	name := strings.TrimSpace(r.URL.Query().Get("name"))
	if name == "" {
		writeError(w, http.StatusBadRequest, "missing_name")
		return
	}
	var current Account
	if h.mockMode {
		var ok bool
		current, ok = h.mockAccount(name)
		if !ok {
			writeError(w, http.StatusNotFound, "account_not_found")
			return
		}
	} else {
		var err error
		current, err = h.getAccount(name)
		if err != nil {
			writeError(w, http.StatusBadGateway, err.Error())
			return
		}
	}
	if !sameTenant(current.Properties["tenant_id"], claims.OrgID) {
		writeError(w, http.StatusNotFound, "account_not_found")
		return
	}
	owned, err := h.ownedResources(name)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	if len(owned) > 0 {
		h.logAccountAction(r, "accounts.delete", claims, name, policy.Decision{Allow: false, PolicyID: "ownership_blocked"})
		writeJSON(w, http.StatusConflict, ownershipBlockedResponse{Error: ErrOwnershipBlocked.Error(), Resources: owned})
		return
	}
	if !handoverConfirmed(current) {
		h.logAccountAction(r, "accounts.delete", claims, name, policy.Decision{Allow: false, PolicyID: "handover_required"})
		writeJSON(w, http.StatusConflict, handoverBlockedResponse{Error: ErrHandoverRequired.Error(), State: accountLifecycleState(current)})
		return
	}
	if h.mockMode {
		h.mockMu.Lock()
		delete(h.mockAccounts, name)
		h.mockMu.Unlock()

		h.logAccountAction(r, "accounts.delete", claims, name, policy.Decision{Allow: true, PolicyID: "account_delete"})
		w.WriteHeader(http.StatusNoContent)
		return
	}

	if err := h.casdoorPost("/api/delete-user", nil, current); err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}

	h.logAccountAction(r, "accounts.delete", claims, name, policy.Decision{Allow: true, PolicyID: "account_delete"})
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) freeze(w http.ResponseWriter, r *http.Request, claims auth.Claims, name string) {
	current, ok := h.accountInTenant(w, name, claims)
	if !ok {
		return
	}
	ensureAccountTenant(&current, claims.OrgID)
	current.IsForbidden = true
	setLifecycleProperty(&current, "lifecycle_state", "frozen")
	setLifecycleProperty(&current, "frozen_by", claims.UserID)
	setLifecycleProperty(&current, "frozen_at", time.Now().UTC().Format(time.RFC3339))
	setLifecycleProperty(&current, "handover_confirmed", "false")
	if h.assetFreezer != nil {
		summary, err := h.assetFreezer.FreezeAssetsForUser(name, claims.OrgID, claims.UserID)
		if err != nil {
			writeError(w, http.StatusBadGateway, "asset_freeze_failed")
			return
		}
		setLifecycleProperty(&current, "frozen_resources", fmt.Sprintf("%d", summary.Resources))
		setLifecycleProperty(&current, "frozen_data_records", fmt.Sprintf("%d", summary.DataRecords))
		setLifecycleProperty(&current, "frozen_digital_employees", fmt.Sprintf("%d", summary.DigitalEmployees))
	}

	if err := h.saveAccount(name, current); err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	h.logAccountAction(r, "accounts.freeze", claims, name, policy.Decision{Allow: true, PolicyID: "account_freeze"})
	writeJSON(w, http.StatusOK, current)
}

func (h *Handler) confirmHandover(w http.ResponseWriter, r *http.Request, claims auth.Claims, name string) {
	current, ok := h.accountInTenant(w, name, claims)
	if !ok {
		return
	}
	ensureAccountTenant(&current, claims.OrgID)
	if accountLifecycleState(current) != "frozen" {
		writeError(w, http.StatusConflict, ErrAccountNotFrozen.Error())
		return
	}
	var req handoverRequest
	if err := decodeOptionalJSON(r.Body, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	setLifecycleProperty(&current, "lifecycle_state", "handover_confirmed")
	setLifecycleProperty(&current, "handover_confirmed", "true")
	setLifecycleProperty(&current, "handover_confirmed_by", claims.UserID)
	setLifecycleProperty(&current, "handover_confirmed_at", time.Now().UTC().Format(time.RFC3339))
	if strings.TrimSpace(req.HandoverToUserID) != "" {
		setLifecycleProperty(&current, "handover_to_user_id", strings.TrimSpace(req.HandoverToUserID))
	}
	if strings.TrimSpace(req.Note) != "" {
		setLifecycleProperty(&current, "handover_note", strings.TrimSpace(req.Note))
	}

	if err := h.saveAccount(name, current); err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	h.logAccountAction(r, "accounts.handover_confirm", claims, name, policy.Decision{Allow: true, PolicyID: "account_handover_confirm"})
	writeJSON(w, http.StatusOK, current)
}

func (h *Handler) offboardingAssets(w http.ResponseWriter, r *http.Request, claims auth.Claims, name string) {
	current, ok := h.accountInTenant(w, name, claims)
	if !ok {
		return
	}
	state := accountLifecycleState(current)
	if state != "frozen" && state != "handover_confirmed" {
		writeError(w, http.StatusConflict, ErrAccountNotFrozen.Error())
		return
	}
	if h.assetInventory == nil {
		writeError(w, http.StatusBadGateway, "asset_inventory_unavailable")
		return
	}
	assets, err := h.assetInventory.OffboardingAssetsForUser(name, claims.OrgID)
	if err != nil {
		writeError(w, http.StatusBadGateway, "asset_inventory_failed")
		return
	}
	h.logAccountAction(r, "accounts.offboarding_assets_view", claims, name, policy.Decision{Allow: true, PolicyID: "account_offboarding_assets_view"})
	writeJSON(w, http.StatusOK, assets)
}

func (h *Handler) accountInTenant(w http.ResponseWriter, name string, claims auth.Claims) (Account, bool) {
	name = strings.TrimSpace(name)
	if name == "" {
		writeError(w, http.StatusBadRequest, "missing_name")
		return Account{}, false
	}
	var current Account
	if h.mockMode {
		var ok bool
		current, ok = h.mockAccount(name)
		if !ok {
			writeError(w, http.StatusNotFound, "account_not_found")
			return Account{}, false
		}
	} else {
		var err error
		current, err = h.getAccount(name)
		if err != nil {
			writeError(w, http.StatusBadGateway, err.Error())
			return Account{}, false
		}
	}
	if !sameTenant(current.Properties["tenant_id"], claims.OrgID) {
		writeError(w, http.StatusNotFound, "account_not_found")
		return Account{}, false
	}
	return current, true
}

func (h *Handler) saveAccount(name string, account Account) error {
	if h.mockMode {
		h.mockMu.Lock()
		h.mockAccounts[name] = cloneAccount(account)
		h.mockMu.Unlock()
		return nil
	}
	query := url.Values{"id": []string{h.owner + "/" + name}}
	return h.casdoorPost("/api/update-user", query, account)
}

func (h *Handler) normalizeAccount(account *Account) error {
	account.Name = strings.TrimSpace(account.Name)
	if account.Name == "" {
		return fmt.Errorf("%w: missing_name", ErrBadRequest)
	}
	if strings.Contains(account.Name, "/") {
		return fmt.Errorf("%w: invalid_name", ErrBadRequest)
	}
	if account.Owner == "" {
		account.Owner = h.owner
	}
	if account.Owner != h.owner {
		return fmt.Errorf("%w: invalid_owner", ErrBadRequest)
	}
	if account.Type == "" {
		account.Type = defaultType
	}
	if account.SignupApplication == "" {
		account.SignupApplication = defaultSignupApp
	}
	if account.Properties == nil {
		account.Properties = map[string]string{}
	}
	return nil
}

func (h *Handler) mockAccount(name string) (Account, bool) {
	h.mockMu.Lock()
	defer h.mockMu.Unlock()

	account, ok := h.mockAccounts[name]
	if !ok {
		return Account{}, false
	}
	return cloneAccount(account), true
}

func (h *Handler) mockAccountList(name string, tenantID string) []Account {
	h.mockMu.Lock()
	defer h.mockMu.Unlock()

	if name != "" {
		account, ok := h.mockAccounts[name]
		if !ok || !sameTenant(account.Properties["tenant_id"], tenantID) {
			return []Account{}
		}
		return []Account{cloneAccount(account)}
	}

	accounts := make([]Account, 0, len(h.mockAccounts))
	for _, account := range h.mockAccounts {
		if sameTenant(account.Properties["tenant_id"], tenantID) {
			accounts = append(accounts, cloneAccount(account))
		}
	}
	return accounts
}

func cloneAccount(account Account) Account {
	if account.Roles != nil {
		account.Roles = append([]string(nil), account.Roles...)
	}
	if account.Properties != nil {
		properties := make(map[string]string, len(account.Properties))
		for key, value := range account.Properties {
			properties[key] = value
		}
		account.Properties = properties
	}
	return account
}

func applyPatch(account *Account, patch accountPatch) error {
	if patch.DisplayName != nil {
		account.DisplayName = strings.TrimSpace(*patch.DisplayName)
	}
	if patch.Email != nil {
		account.Email = strings.TrimSpace(*patch.Email)
	}
	if patch.Roles != nil {
		account.Roles = *patch.Roles
	}
	if patch.Properties != nil {
		account.Properties = patch.Properties
	}
	if patch.Status != nil {
		switch strings.ToLower(strings.TrimSpace(*patch.Status)) {
		case "active":
			account.IsForbidden = false
		case "inactive", "disabled":
			account.IsForbidden = true
		default:
			return fmt.Errorf("%w: invalid_status", ErrBadRequest)
		}
	}
	return nil
}

func ensureAccountTenant(account *Account, tenantID string) {
	if account.Properties == nil {
		account.Properties = map[string]string{}
	}
	account.Properties["tenant_id"] = strings.TrimSpace(tenantID)
}

func (h *Handler) getAccount(name string) (Account, error) {
	query := url.Values{"owner": []string{h.owner}}
	var users []Account
	if err := h.casdoorGet("/api/get-users", query, &users); err != nil {
		return Account{}, err
	}
	for _, user := range users {
		if user.Name == name {
			return user, nil
		}
	}
	return Account{}, fmt.Errorf("casdoor user %q not found", name)
}

func (h *Handler) ownedResources(userID string) ([]ownershipResource, error) {
	if h.mockMode {
		for _, entry := range mockOwnershipData {
			if entry.OwnerID == userID {
				return []ownershipResource{{ResourceID: entry.ResourceID, OwnerID: entry.OwnerID}}, nil
			}
		}
		return nil, nil
	}
	endpoint := h.ownershipURL + "/ownership/by_user/" + url.PathEscape(userID)
	request, err := http.NewRequest(http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, err
	}
	response, err := h.client.Do(request)
	if err != nil {
		return nil, fmt.Errorf("ownership pre-check failed: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("ownership pre-check returned %d", response.StatusCode)
	}
	var result ownershipByUserResponse
	if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("ownership pre-check decode failed: %w", err)
	}
	return result.Resources, nil
}

var mockOwnershipData = []ownershipResource{
	{ResourceID: "dataset_001", OwnerID: "user_li"},
	{ResourceID: "dataset_002", OwnerID: "user_fu"},
	{ResourceID: "dataset_003", OwnerID: "user_huang"},
}

func (h *Handler) casdoorGet(path string, query url.Values, out interface{}) error {
	endpoint := h.casdoorURL + path
	if len(query) > 0 {
		endpoint += "?" + query.Encode()
	}
	request, err := http.NewRequest(http.MethodGet, endpoint, nil)
	if err != nil {
		return err
	}
	return h.doCasdoor(request, out)
}

func (h *Handler) casdoorPost(path string, query url.Values, payload interface{}) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	endpoint := h.casdoorURL + path
	if len(query) > 0 {
		endpoint += "?" + query.Encode()
	}
	request, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	return h.doCasdoor(request, nil)
}

func (h *Handler) doCasdoor(request *http.Request, out interface{}) error {
	response, err := h.client.Do(request)
	if err != nil {
		return fmt.Errorf("casdoor request failed: %w", err)
	}
	defer response.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		return fmt.Errorf("casdoor response read failed: %w", err)
	}
	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		return fmt.Errorf("casdoor returned %d: %s", response.StatusCode, strings.TrimSpace(string(body)))
	}

	if unwrapped, err := unwrapCasdoorResponse(body); err != nil {
		return err
	} else if unwrapped != nil {
		body = unwrapped
	}

	if raw, ok := out.(*json.RawMessage); ok {
		*raw = append((*raw)[:0], body...)
		return nil
	}
	if out == nil {
		return nil
	}
	if len(bytes.TrimSpace(body)) == 0 {
		return nil
	}
	if err := json.Unmarshal(body, out); err != nil {
		return fmt.Errorf("casdoor response decode failed: %w", err)
	}
	return nil
}

func unwrapCasdoorResponse(body []byte) ([]byte, error) {
	var response casdoorResponse
	if err := json.Unmarshal(body, &response); err != nil || response.Status == "" {
		return nil, nil
	}
	if response.Status != "ok" {
		message := strings.TrimSpace(response.Msg)
		if message == "" {
			message = response.Status
		}
		return nil, fmt.Errorf("casdoor returned %s: %s", response.Status, message)
	}
	if len(bytes.TrimSpace(response.Data)) == 0 {
		return []byte("null"), nil
	}
	return response.Data, nil
}

func filterAccountJSONByTenant(body []byte, tenantID string) ([]Account, error) {
	var accounts []Account
	if err := json.Unmarshal(body, &accounts); err != nil {
		return nil, fmt.Errorf("casdoor response decode failed: %w", err)
	}
	filtered := make([]Account, 0, len(accounts))
	for _, account := range accounts {
		if sameTenant(account.Properties["tenant_id"], tenantID) {
			filtered = append(filtered, account)
		}
	}
	return filtered, nil
}

func sameTenant(recordTenantID, claimsOrgID string) bool {
	recordTenantID = strings.TrimSpace(recordTenantID)
	claimsOrgID = strings.TrimSpace(claimsOrgID)
	return recordTenantID != "" && recordTenantID == claimsOrgID
}

func accountActionPath(path string) (name string, action string, ok bool) {
	path = strings.Trim(strings.TrimPrefix(path, "/api/accounts/"), "/")
	parts := strings.Split(path, "/")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return "", "", false
	}
	return parts[0], parts[1], true
}

func setLifecycleProperty(account *Account, key, value string) {
	if account.Properties == nil {
		account.Properties = map[string]string{}
	}
	account.Properties[key] = value
}

func handoverConfirmed(account Account) bool {
	return strings.EqualFold(strings.TrimSpace(account.Properties["handover_confirmed"]), "true")
}

func accountLifecycleState(account Account) string {
	state := strings.TrimSpace(account.Properties["lifecycle_state"])
	if state == "" {
		return "active"
	}
	return state
}

func decodeJSON(body io.Reader, out interface{}) error {
	decoder := json.NewDecoder(body)
	decoder.DisallowUnknownFields()
	return decoder.Decode(out)
}

func decodeOptionalJSON(body io.Reader, out interface{}) error {
	if body == nil {
		return nil
	}
	payload, err := io.ReadAll(body)
	if err != nil {
		return err
	}
	if len(bytes.TrimSpace(payload)) == 0 {
		return nil
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	return decoder.Decode(out)
}

func writeJSON(w http.ResponseWriter, status int, response interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(response)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, errorResponse{Error: message})
}

func (h *Handler) logAccountAction(r *http.Request, actionType string, claims auth.Claims, accountName string, decision policy.Decision) {
	if h == nil || h.audit == nil {
		return
	}
	headers := r.Header.Clone()
	if strings.TrimSpace(headers.Get("X-Tenant-ID")) == "" {
		headers.Set("X-Tenant-ID", claims.OrgID)
	}
	if err := h.audit.LogAction(
		audit.WithSpan(r.Context(), headers),
		actionType,
		claims.UserID,
		"account",
		accountName,
		decision,
		decision.PolicyID,
		headers,
	); err != nil {
		log.Printf("%s audit failed: %v", actionType, err)
	}
}

func canManageAccounts(claims auth.Claims) bool {
	for _, role := range claims.RoleList {
		switch role {
		case "hanhe_admin", "admin", "operator":
			return true
		}
	}
	return false
}

func envURL(name string, fallback string) string {
	value := strings.TrimRight(strings.TrimSpace(os.Getenv(name)), "/")
	if value == "" {
		return fallback
	}
	return value
}

func envString(name string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	return value
}
