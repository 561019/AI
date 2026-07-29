package gateway

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/breakglass"
	"hanhe.com/account-gateway/internal/organization"
	"hanhe.com/account-gateway/internal/permissionclient"
	"hanhe.com/account-gateway/internal/policy"
)

type ValidateHandler struct {
	db                 *sql.DB
	enforcer           *policy.Enforcer
	auditWriter        *audit.Writer
	jwt                *auth.JWTManager
	organizationStore  *organization.Store
	permissionClient   *permissionclient.Client
	permissionMode     permissionclient.Mode
	isBreakglassActive func() (bool, error)
}

type validateResponse struct {
	Allow    bool   `json:"allow"`
	PolicyID string `json:"policy_id,omitempty"`
	Reason   string `json:"reason,omitempty"`
}

func (h *ValidateHandler) WithOrganizationStore(store *organization.Store) *ValidateHandler {
	h.organizationStore = store
	return h
}

func (h *ValidateHandler) WithPermissionClient(client *permissionclient.Client, mode permissionclient.Mode) *ValidateHandler {
	h.permissionClient = client
	h.permissionMode = mode
	return h
}

func NewValidateHandler(db *sql.DB, enforcer *policy.Enforcer, auditWriter *audit.Writer, jwt *auth.JWTManager) *ValidateHandler {
	return &ValidateHandler{
		db:             db,
		enforcer:       enforcer,
		auditWriter:    auditWriter,
		jwt:            jwt,
		permissionMode: permissionclient.ModeLocal,
		isBreakglassActive: func() (bool, error) {
			return breakglass.IsBreakglassActive(db)
		},
	}
}

func (h *ValidateHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	timings := make(map[string]time.Duration)
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	var (
		resp         validateResponse
		status       int
		decision     policy.Decision
		claims       auth.Claims
		remote       *permissionclient.CheckResponse
		remoteStatus int
		remoteErr    error
	)

	defer func() {
		auditHeaders := r.Header.Clone()
		if strings.TrimSpace(auditHeaders.Get("X-Tenant-ID")) == "" {
			auditHeaders.Set("X-Tenant-ID", claims.OrgID)
		}
		ctx := audit.WithSpan(r.Context(), auditHeaders)
		auditStart := time.Now()
		if err := h.auditWriter.LogValidateCall(ctx, decision, resp.PolicyID, auditHeaders); err != nil {
			log.Printf("auth.validate audit write failed: %v", err)
		}
		timings["audit"] = time.Since(auditStart)
		if h.permissionMode == permissionclient.ModeShadow {
			logShadowDifference(resp, status, remote, remoteStatus, remoteErr)
		}
		if validateTimingEnabled() {
			log.Printf("auth.validate timings total=%s jwt=%s parse=%s enforce=%s audit=%s status=%d allow=%v reason=%s",
				time.Since(start),
				timings["jwt"],
				timings["parse"],
				timings["enforce"],
				timings["audit"],
				status,
				resp.Allow,
				resp.Reason,
			)
		}
	}()

	jwtStart := time.Now()
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	timings["jwt"] = time.Since(jwtStart)
	if err != nil {
		status = http.StatusUnauthorized
		resp = validateResponse{Allow: false, Reason: "invalid_token"}
		writeJSON(w, status, resp)
		return
	}

	parseStart := time.Now()
	req, ok := validateRequestFromHeaders(r)
	timings["parse"] = time.Since(parseStart)
	if !ok {
		status = http.StatusBadRequest
		resp = validateResponse{Allow: false, Reason: "missing_header"}
		writeJSON(w, status, resp)
		return
	}
	if !validResourceType(req.typ) {
		status = http.StatusBadRequest
		resp = validateResponse{Allow: false, Reason: "invalid_resource_type"}
		writeJSON(w, status, resp)
		return
	}
	if h.permissionMode != permissionclient.ModeRemote && req.typ == "data" && h.organizationStore != nil {
		enabled, err := h.organizationStore.IsDataActionEnabled(req.act)
		if err != nil {
			status = http.StatusInternalServerError
			resp = validateResponse{Allow: false, Reason: "organization_state_error"}
			writeJSON(w, status, resp)
			return
		}
		if !enabled {
			status = http.StatusBadRequest
			resp = validateResponse{Allow: false, Reason: "invalid_action"}
			writeJSON(w, status, resp)
			return
		}
	} else if h.permissionMode != permissionclient.ModeRemote && !validAction(req.act) {
		status = http.StatusBadRequest
		resp = validateResponse{Allow: false, Reason: "invalid_action"}
		writeJSON(w, status, resp)
		return
	}
	if req.tenantID != "" && claims.OrgID != "" && req.tenantID != claims.OrgID && !claims.IsBreakglass {
		status = http.StatusOK
		resp = validateResponse{Allow: false, Reason: "tenant_mismatch"}
		writeJSON(w, status, resp)
		return
	}
	if claims.IsDigital && req.typ == "data" {
		status = http.StatusOK
		resp = validateResponse{Allow: false, Reason: "digital_employee_no_data_access"}
		writeJSON(w, status, resp)
		return
	}
	if claims.IsDigital {
		state, err := h.digitalState(claims)
		if err != nil {
			status = http.StatusInternalServerError
			resp = validateResponse{Allow: false, Reason: "digital_employee_state_error"}
			writeJSON(w, status, resp)
			return
		}
		if !state.Active {
			reason := state.Reason
			if reason == "" {
				reason = "digital_employee_token_revoked"
			}
			status = http.StatusOK
			resp = validateResponse{Allow: false, Reason: reason}
			writeJSON(w, status, resp)
			return
		}
		if state.ExecutionMode == "require_confirmation" && strings.TrimSpace(r.Header.Get("X-Digital-Confirmed-By")) != claims.ParentUserID {
			status = http.StatusOK
			resp = validateResponse{Allow: false, Reason: "digital_employee_confirmation_required"}
			writeJSON(w, status, resp)
			return
		}
		if state.ExecutionMode == "scope_reject" && !(req.typ == "tool" && req.owner == claims.ParentUserID) {
			status = http.StatusOK
			resp = validateResponse{Allow: false, Reason: "digital_employee_scope_rejected"}
			writeJSON(w, status, resp)
			return
		}
	}
	if claims.IsDigital && req.typ == "tool" && req.owner == claims.ParentUserID {
		status = http.StatusOK
		resp = validateResponse{Allow: true, PolicyID: "digital_employee_parent_tool"}
		writeJSON(w, status, resp)
		return
	}
	if claims.IsBreakglass {
		active, err := h.isBreakglassActive()
		if err != nil {
			status = http.StatusInternalServerError
			resp = validateResponse{Allow: false, Reason: "breakglass_state_error"}
			writeJSON(w, status, resp)
			return
		}
		if !active {
			status = http.StatusOK
			resp = validateResponse{Allow: false, Reason: "breakglass_inactive"}
			writeJSON(w, status, resp)
			return
		}
		req.sub = "breakglass"
	}

	if h.permissionMode != permissionclient.ModeLocal && h.permissionClient != nil {
		remoteRequest := permissionRequestFromLegacy(r, claims, req)
		if strings.TrimSpace(r.Header.Get("X-Trace-ID")) == "" {
			r.Header.Set("X-Trace-ID", remoteRequest.TraceID)
		}
		if strings.TrimSpace(r.Header.Get("X-Request-ID")) == "" {
			r.Header.Set("X-Request-ID", remoteRequest.RequestID)
		}
		remoteStart := time.Now()
		remoteResult, responseStatus, err := h.permissionClient.Check(r.Context(), remoteRequest)
		timings["enforce"] = time.Since(remoteStart)
		remoteStatus = responseStatus
		remoteErr = err
		if err == nil {
			remote = &remoteResult
		}
		if h.permissionMode == permissionclient.ModeRemote {
			status, resp, decision = legacyRemoteDecision(remote, remoteStatus, remoteErr)
			writeJSON(w, status, resp)
			return
		}
	}

	if req.personID != "" {
		decision, err = h.organizationDecision(claims, req)
		if err != nil {
			status = http.StatusInternalServerError
			resp = validateResponse{Allow: false, Reason: "organization_state_error"}
			writeJSON(w, status, resp)
			return
		}
		if decision.Allow {
			status = http.StatusOK
			resp = validateResponse{Allow: true, PolicyID: decision.PolicyID}
			writeJSON(w, status, resp)
			return
		}
		if strings.HasPrefix(decision.PolicyID, "data_record_inactive:") {
			status = http.StatusOK
			resp = validateResponse{Allow: false, Reason: "data_record_inactive"}
			writeJSON(w, status, resp)
			return
		}
		if strings.HasPrefix(decision.PolicyID, "data_action_forbidden:") {
			status = http.StatusOK
			resp = validateResponse{Allow: false, Reason: "data_action_forbidden"}
			writeJSON(w, status, resp)
			return
		}
		if decision.PolicyID == "person_context_invalid" {
			status = http.StatusOK
			resp = validateResponse{Allow: false, Reason: "person_context_invalid"}
			writeJSON(w, status, resp)
			return
		}
		status = http.StatusOK
		resp = validateResponse{Allow: false}
		writeJSON(w, status, resp)
		return
	}

	enforceStart := time.Now()
	enforceTenant := req.tenantID
	if enforceTenant == "" {
		enforceTenant = claims.OrgID
	}
	decision, err = h.enforcer.EnforceWithTenant(req.sub, req.obj, req.typ, req.act, req.owner, enforceTenant)
	timings["enforce"] = time.Since(enforceStart)
	if err != nil {
		status = http.StatusInternalServerError
		resp = validateResponse{Allow: false, Reason: "enforce_error"}
		writeJSON(w, status, resp)
		return
	}

	status = http.StatusOK
	resp = validateResponse{Allow: decision.Allow, PolicyID: decision.PolicyID}
	writeJSON(w, status, resp)
}

func permissionRequestFromLegacy(r *http.Request, claims auth.Claims, req validateRequest) permissionclient.CheckRequest {
	tenantID := req.tenantID
	if tenantID == "" {
		tenantID = claims.OrgID
	}
	return permissionclient.CheckRequest{
		TraceID:       permissionclient.HeaderOrGenerated(r.Header, "X-Trace-ID", "trace_gateway"),
		RequestID:     permissionclient.HeaderOrGenerated(r.Header, "X-Request-ID", "request_gateway"),
		ActorID:       claims.UserID,
		Action:        req.act,
		SourceService: permissionclient.HeaderOrDefault(r.Header, "X-Source-Service", "account_gateway"),
		TargetService: permissionclient.HeaderOrDefault(r.Header, "X-Target-Service", "legacy_runtime"),
		DataLabel:     permissionclient.HeaderOrDefault(r.Header, "X-Data-Label", "normal"),
		DataState:     permissionclient.HeaderOrDefault(r.Header, "X-Data-State", "active"),
		TenantID:      tenantID,
		PersonID:      claims.UserID,
		PositionID:    req.positionID,
		ResourceType:  req.typ,
		ResourceID:    req.obj,
		DomainID:      req.domainID,
	}
}

func legacyRemoteDecision(remote *permissionclient.CheckResponse, remoteStatus int, remoteErr error) (int, validateResponse, policy.Decision) {
	if remoteErr != nil || remote == nil || remoteStatus != http.StatusOK || remote.Result == "error" {
		return http.StatusServiceUnavailable,
			validateResponse{Allow: false, Reason: "permission_service_unavailable"},
			policy.Decision{Allow: false, PolicyID: "permission_service_unavailable"}
	}
	if remote.Allowed && remote.Result == "allow" {
		return http.StatusOK,
			validateResponse{Allow: true, PolicyID: remote.DecisionID},
			policy.Decision{Allow: true, PolicyID: remote.DecisionID}
	}
	reason := strings.ToLower(strings.TrimSpace(remote.ReasonCode))
	if reason == "" {
		reason = "permission_denied"
	}
	return http.StatusOK,
		validateResponse{Allow: false, Reason: reason},
		policy.Decision{Allow: false, PolicyID: remote.DecisionID}
}

func logShadowDifference(local validateResponse, localStatus int, remote *permissionclient.CheckResponse, remoteStatus int, remoteErr error) {
	if remoteErr != nil {
		log.Printf("permission shadow unavailable local_status=%d local_allow=%v error=%v", localStatus, local.Allow, remoteErr)
		return
	}
	if remote == nil {
		log.Printf("permission shadow returned no decision local_status=%d local_allow=%v remote_status=%d", localStatus, local.Allow, remoteStatus)
		return
	}
	if remoteStatus != http.StatusOK || remote.Allowed != local.Allow {
		log.Printf("permission shadow difference local_status=%d local_allow=%v local_reason=%s remote_status=%d remote_allow=%v remote_result=%s remote_reason=%s decision_id=%s",
			localStatus, local.Allow, local.Reason, remoteStatus, remote.Allowed, remote.Result, remote.ReasonCode, remote.DecisionID)
	}
}

type validateRequest struct {
	sub           string
	obj           string
	typ           string
	act           string
	owner         string
	tenantID      string
	personID      string
	positionID    string
	domainID      string
	delegationID  string
	ownerPersonID string
}

func validateRequestFromHeaders(r *http.Request) (validateRequest, bool) {
	sub := strings.TrimSpace(r.Header.Get("X-User-ID"))
	typ := strings.TrimSpace(r.Header.Get("X-Resource-Type"))
	owner := strings.TrimSpace(r.Header.Get("X-Resource-Owner-ID"))
	act := strings.TrimSpace(r.Header.Get("X-Action"))
	resourceID := strings.TrimSpace(r.Header.Get("X-Resource-ID"))
	if sub == "" || typ == "" || owner == "" || act == "" {
		return validateRequest{}, false
	}
	if resourceID == "" {
		resourceID = objectForType(typ)
	}

	return validateRequest{
		sub:           sub,
		obj:           resourceID,
		typ:           typ,
		act:           act,
		owner:         owner,
		tenantID:      strings.TrimSpace(r.Header.Get("X-Tenant-ID")),
		personID:      strings.TrimSpace(r.Header.Get("X-Person-ID")),
		positionID:    strings.TrimSpace(r.Header.Get("X-Position-ID")),
		domainID:      strings.TrimSpace(r.Header.Get("X-Domain-ID")),
		delegationID:  strings.TrimSpace(r.Header.Get("X-Delegation-ID")),
		ownerPersonID: strings.TrimSpace(r.Header.Get("X-Resource-Owner-Person-ID")),
	}, true
}

func objectForType(typ string) string {
	switch typ {
	case "tool":
		return "tool_resource_placeholder"
	case "data":
		return "data_record_placeholder"
	default:
		return typ + "_resource_placeholder"
	}
}

func validResourceType(typ string) bool {
	switch typ {
	case "tool", "data", "skill", "knowledge", "digital_employee":
		return true
	default:
		return false
	}
}

func validAction(action string) bool {
	switch action {
	case "create", "read", "update", "delete", "approve", "use", "store", "fetch", "delegate", "export", "disable", "freeze", "unfreeze":
		return true
	default:
		return false
	}
}

func (h *ValidateHandler) organizationDecision(claims auth.Claims, req validateRequest) (policy.Decision, error) {
	if h.organizationStore == nil {
		return policy.Decision{Allow: false, PolicyID: "person_context_invalid"}, nil
	}
	decision, err := h.organizationStore.PersonHasAccess(organization.ValidateContext{
		UserID:        claims.UserID,
		TenantID:      req.tenantID,
		PersonID:      req.personID,
		PositionID:    req.positionID,
		DomainID:      req.domainID,
		DelegationID:  req.delegationID,
		ResourceType:  req.typ,
		ResourceID:    req.obj,
		Action:        req.act,
		OwnerUserID:   req.owner,
		OwnerPersonID: req.ownerPersonID,
	})
	if err == organization.ErrInvalidContext {
		return policy.Decision{Allow: false, PolicyID: "person_context_invalid"}, nil
	}
	if err != nil {
		return policy.Decision{}, err
	}
	return policy.Decision{Allow: decision.Allow, PolicyID: decision.PolicyID}, nil
}

func validateTimingEnabled() bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv("AUTH_VALIDATE_TIMING")))
	return value == "1" || value == "true" || value == "yes"
}

func hasRole(claims auth.Claims, role string) bool {
	for _, current := range claims.RoleList {
		if current == role {
			return true
		}
	}
	return false
}

type digitalState struct {
	Active        bool
	ExecutionMode string
	Reason        string
}

func (h *ValidateHandler) digitalState(claims auth.Claims) (digitalState, error) {
	if h == nil || h.db == nil {
		return digitalState{Active: true, ExecutionMode: "auto"}, nil
	}
	var status string
	var tokenVersion int
	var executionMode string
	var expiresAt string
	err := h.db.QueryRow(`
		SELECT status, token_version, execution_mode, COALESCE(expires_at, '')
		FROM digital_employees
		WHERE name = ? AND tenant_id = ?
	`, claims.UserID, claims.OrgID).Scan(&status, &tokenVersion, &executionMode, &expiresAt)
	if err == sql.ErrNoRows {
		var exists int
		countErr := h.db.QueryRow("SELECT COUNT(1) FROM digital_employees WHERE name = ?", claims.UserID).Scan(&exists)
		if countErr != nil {
			return digitalState{}, countErr
		}
		if exists > 0 {
			return digitalState{Active: false, ExecutionMode: "auto"}, nil
		}
		return digitalState{Active: true, ExecutionMode: "auto"}, nil
	}
	if err != nil {
		return digitalState{}, err
	}
	if status != "active" {
		return digitalState{Active: false, ExecutionMode: normalizeDigitalExecutionMode(executionMode)}, nil
	}
	if digitalEmployeeExpired(expiresAt, time.Now().UTC()) {
		return digitalState{Active: false, ExecutionMode: normalizeDigitalExecutionMode(executionMode), Reason: "digital_employee_expired"}, nil
	}
	if claims.TokenVersion != 0 && claims.TokenVersion != tokenVersion {
		return digitalState{Active: false, ExecutionMode: normalizeDigitalExecutionMode(executionMode)}, nil
	}
	return digitalState{Active: true, ExecutionMode: normalizeDigitalExecutionMode(executionMode)}, nil
}

func digitalEmployeeExpired(expiresAt string, now time.Time) bool {
	expiresAt = strings.TrimSpace(expiresAt)
	if expiresAt == "" {
		return false
	}
	parsed, err := time.Parse(time.RFC3339, expiresAt)
	if err != nil {
		return true
	}
	return !now.Before(parsed)
}

func normalizeDigitalExecutionMode(mode string) string {
	mode = strings.TrimSpace(mode)
	if mode == "" {
		return "auto"
	}
	return mode
}

func writeJSON(w http.ResponseWriter, status int, response validateResponse) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(response)
}
