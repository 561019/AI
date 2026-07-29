package organization

import (
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strconv"
	"strings"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/policy"
)

type Handler struct {
	store *Store
	jwt   *auth.JWTManager
	audit *audit.Writer
}

func NewHandler(store *Store, jwt *auth.JWTManager, auditWriter *audit.Writer) *Handler {
	return &Handler{store: store, jwt: jwt, audit: auditWriter}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}
	if strings.TrimSpace(r.Header.Get("X-Tenant-ID")) == "" {
		r.Header.Set("X-Tenant-ID", claims.OrgID)
	}

	path := strings.TrimRight(r.URL.Path, "/")
	switch {
	case path == "/api/org/commands":
		h.orgCommands(w, r, claims)
	case path == "/api/org/snapshot":
		h.orgSnapshot(w, r, claims)
	case path == "/api/permissions/commands":
		h.permissionCommands(w, r, claims)
	case path == "/api/permissions/snapshot":
		h.permissionSnapshot(w, r, claims)
	case path == "/api/positions":
		h.positions(w, r, claims)
	case path == "/api/person-position-assignments":
		h.assignments(w, r, claims)
	case strings.HasPrefix(path, "/api/person-position-assignments/") && strings.HasSuffix(path, "/end"):
		h.endAssignment(w, r, claims)
	case path == "/api/domains":
		h.domains(w, r, claims)
	case path == "/api/person-manager-edges":
		h.managerEdges(w, r, claims)
	case path == "/api/position-standard-resources":
		h.standardResources(w, r, claims)
	case path == "/api/delegations":
		h.delegations(w, r, claims)
	case path == "/api/resources":
		h.resources(w, r, claims)
	case path == "/api/resource-publications":
		h.resourcePublications(w, r, claims)
	case strings.HasPrefix(path, "/api/resource-publications/") && strings.HasSuffix(path, "/approve"):
		h.approveResourcePublication(w, r, claims)
	default:
		w.WriteHeader(http.StatusNotFound)
	}
}

func tenantScope(w http.ResponseWriter, r *http.Request, claims auth.Claims) (string, bool) {
	return tenantScopeValue(w, claims, r.URL.Query().Get("tenant_id"))
}

func tenantScopeValue(w http.ResponseWriter, claims auth.Claims, requested string) (string, bool) {
	requested = strings.TrimSpace(requested)
	orgID := strings.TrimSpace(claims.OrgID)
	if requested == "" {
		return orgID, true
	}
	if claims.IsBreakglass || orgID == "" || requested == orgID {
		return requested, true
	}
	writeError(w, http.StatusForbidden, "tenant_mismatch")
	return "", false
}

func defaultTenant(w http.ResponseWriter, claims auth.Claims, tenantID *string) bool {
	scoped, ok := tenantScopeValue(w, claims, *tenantID)
	if !ok {
		return false
	}
	if strings.TrimSpace(*tenantID) == "" {
		*tenantID = scoped
	}
	return true
}

func (h *Handler) positions(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if !isIM(claims) && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "im_only")
		return
	}
	switch r.Method {
	case http.MethodPost:
		var req Position
		if !decodeBody(w, r, &req) {
			return
		}
		if !defaultTenant(w, claims, &req.TenantID) {
			return
		}
		req.CreatedBy = claims.UserID
		item, err := h.store.CreatePosition(req)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "positions.create", claims.UserID, "position", item.ID, "position:"+item.ID)
		writeJSON(w, http.StatusCreated, item)
	case http.MethodGet:
		tenantID, ok := tenantScope(w, r, claims)
		if !ok {
			return
		}
		items, err := h.store.ListPositionsByTenant(tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"positions": items})
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) assignments(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if !isIM(claims) && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "im_only")
		return
	}
	switch r.Method {
	case http.MethodPost:
		var req Assignment
		if !decodeBody(w, r, &req) {
			return
		}
		if !defaultTenant(w, claims, &req.TenantID) {
			return
		}
		req.AssignedBy = claims.UserID
		item, err := h.store.CreateAssignment(req)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "person_position.assign", claims.UserID, "person_position_assignment", strconv.FormatInt(item.ID, 10), "assignment:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusCreated, item)
	case http.MethodGet:
		tenantID, ok := tenantScope(w, r, claims)
		if !ok {
			return
		}
		items, err := h.store.ListAssignmentsByTenant(tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"assignments": items})
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) endAssignment(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if !isIM(claims) && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "im_only")
		return
	}
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	id, err := pathID(r.URL.Path, "/api/person-position-assignments/", "/end")
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_id")
		return
	}
	item, err := h.endAssignmentForClaims(id, claims)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	h.log(r, "person_position.end", claims.UserID, "person_position_assignment", strconv.FormatInt(item.ID, 10), "assignment:"+strconv.FormatInt(item.ID, 10))
	writeJSON(w, http.StatusOK, item)
}

func (h *Handler) domains(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	switch r.Method {
	case http.MethodPost:
		if !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "admin_only")
			return
		}
		var req Domain
		if !decodeBody(w, r, &req) {
			return
		}
		if !defaultTenant(w, claims, &req.TenantID) {
			return
		}
		req.CreatedBy = claims.UserID
		item, err := h.store.CreateDomain(req)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "domains.create", claims.UserID, "domain", item.ID, "domain:"+item.ID)
		writeJSON(w, http.StatusCreated, item)
	case http.MethodGet:
		if !isDSM(claims) && !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "dsm_only")
			return
		}
		tenantID, ok := tenantScope(w, r, claims)
		if !ok {
			return
		}
		items, err := h.store.ListDomainsByTenant(tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"domains": items})
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) managerEdges(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if !isDSM(claims) && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "dsm_only")
		return
	}
	switch r.Method {
	case http.MethodPost:
		var req ManagerEdge
		if !decodeBody(w, r, &req) {
			return
		}
		if err := h.requireDomainTenant(req.DomainID, claims); err != nil {
			writeStoreError(w, err)
			return
		}
		req.CreatedBy = claims.UserID
		item, err := h.store.UpsertManagerEdge(req)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "manager_edges.upsert", claims.UserID, "manager_edge", strconv.FormatInt(item.ID, 10), "manager_edge:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusCreated, item)
	case http.MethodGet:
		tenantID, ok := tenantScope(w, r, claims)
		if !ok {
			return
		}
		items, err := h.store.ListManagerEdgesByTenant(tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"manager_edges": items})
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) standardResources(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if !isDSM(claims) && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "dsm_only")
		return
	}
	switch r.Method {
	case http.MethodPost:
		var req StandardResource
		if !decodeBody(w, r, &req) {
			return
		}
		if err := h.requirePositionTenant(req.PositionID, claims); err != nil {
			writeStoreError(w, err)
			return
		}
		req.CreatedBy = claims.UserID
		item, err := h.store.CreateStandardResource(req)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "position_standard_resources.create", claims.UserID, "position_standard_resource", strconv.FormatInt(item.ID, 10), "position_standard:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusCreated, item)
	case http.MethodGet:
		tenantID, ok := tenantScope(w, r, claims)
		if !ok {
			return
		}
		items, err := h.store.ListStandardResourcesByTenant(tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"position_standard_resources": items})
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) delegations(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	switch r.Method {
	case http.MethodPost:
		var req Delegation
		if !decodeBody(w, r, &req) {
			return
		}
		req.CreatedBy = claims.UserID
		if !isDSM(claims) && !isAdmin(claims) {
			if err := h.authorizeDelegationByUser(claims, req); err != nil {
				if errors.Is(err, ErrForbiddenDelegation) {
					writeError(w, http.StatusForbidden, "delegation_forbidden")
					return
				}
				writeStoreError(w, err)
				return
			}
		}
		if err := h.requireDelegationTenant(req, claims); err != nil {
			writeStoreError(w, err)
			return
		}
		item, err := h.store.CreateDelegation(req)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "delegations.create", claims.UserID, "delegation", strconv.FormatInt(item.ID, 10), "delegation:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusCreated, item)
	case http.MethodGet:
		if !isDSM(claims) && !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "dsm_only")
			return
		}
		tenantID, ok := tenantScope(w, r, claims)
		if !ok {
			return
		}
		items, err := h.store.ListDelegationsForSnapshot(claims.UserID, true, DelegationFilters{TenantID: tenantID})
		if err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"delegations": items})
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) resources(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	switch r.Method {
	case http.MethodPost:
		var req Resource
		if !decodeBody(w, r, &req) {
			return
		}
		if !defaultTenant(w, claims, &req.TenantID) {
			return
		}
		req.CreatedBy = claims.UserID
		if !isDSM(claims) && !isAdmin(claims) {
			if err := h.authorizeResourceCreate(claims, req); err != nil {
				if errors.Is(err, ErrForbiddenDelegation) {
					writeError(w, http.StatusForbidden, "resource_forbidden")
					return
				}
				writeStoreError(w, err)
				return
			}
		}
		item, err := h.store.CreateResource(req)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "resources.create", claims.UserID, item.ResourceType, item.ID, "resource:"+item.ID)
		writeJSON(w, http.StatusCreated, item)
	case http.MethodGet:
		tenantID, ok := tenantScope(w, r, claims)
		if !ok {
			return
		}
		items, err := h.store.ListResources(claims.UserID, isDSM(claims) || isAdmin(claims), ResourceFilters{
			ResourceType: r.URL.Query().Get("resource_type"),
			Level:        r.URL.Query().Get("level"),
			DepartmentID: r.URL.Query().Get("department_id"),
			TenantID:     tenantID,
			Status:       r.URL.Query().Get("status"),
		})
		if err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"resources": items})
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) resourcePublications(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	switch r.Method {
	case http.MethodPost:
		var req ResourcePublication
		if !decodeBody(w, r, &req) {
			return
		}
		if err := h.requireResourceTenant(req.ResourceID, claims); err != nil {
			writeStoreError(w, err)
			return
		}
		item, err := h.store.CreateResourcePublication(req, claims.UserID, isDSM(claims) || isAdmin(claims))
		if err != nil {
			if errors.Is(err, ErrForbiddenDelegation) {
				writeError(w, http.StatusForbidden, "publication_forbidden")
				return
			}
			writeStoreError(w, err)
			return
		}
		h.log(r, "resource_publications.create", claims.UserID, "resource_publication", strconv.FormatInt(item.ID, 10), "resource_publication:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusCreated, item)
	case http.MethodGet:
		tenantID, ok := tenantScope(w, r, claims)
		if !ok {
			return
		}
		items, err := h.store.ListResourcePublicationsByTenant(claims.UserID, isDSM(claims) || isAdmin(claims), tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"resource_publications": items})
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

func (h *Handler) approveResourcePublication(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if !isDSM(claims) && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "dsm_only")
		return
	}
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	id, err := pathID(r.URL.Path, "/api/resource-publications/", "/approve")
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_id")
		return
	}
	item, err := h.approveResourcePublicationForClaims(id, claims)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	policyID := "resource_publication:" + strconv.FormatInt(item.ID, 10)
	h.log(r, "resource_publications.approve", claims.UserID, "resource_publication", strconv.FormatInt(item.ID, 10), policyID)
	writeJSON(w, http.StatusOK, map[string]interface{}{"id": item.ID, "status": item.Status, "policy_id": policyID})
}

func (h *Handler) authorizeDelegationByUser(claims auth.Claims, req Delegation) error {
	assignment, err := h.store.activeAssignment(req.FromPersonID)
	if err != nil {
		return err
	}
	if assignment.UserID != claims.UserID {
		return ErrForbiddenDelegation
	}
	ok, err := h.store.PersonCanRedelegate(req.FromPersonID, req.ResourceType, req.ResourceID, req.Action, req.OwnerUserID)
	if err != nil {
		return err
	}
	if !ok {
		return ErrForbiddenDelegation
	}
	return nil
}

func (h *Handler) authorizeResourceCreate(claims auth.Claims, req Resource) error {
	assignment, err := h.store.activeAssignment(req.OwnerPersonID)
	if err != nil {
		return err
	}
	if assignment.UserID != claims.UserID || assignment.PositionID != strings.TrimSpace(req.OwnerPositionID) || assignment.TenantID != strings.TrimSpace(req.TenantID) {
		return ErrForbiddenDelegation
	}
	departmentID, err := h.store.departmentForPosition(assignment.PositionID)
	if err != nil {
		return err
	}
	if departmentID != strings.TrimSpace(req.DepartmentID) || strings.TrimSpace(req.OwnerUserID) != claims.UserID {
		return ErrForbiddenDelegation
	}
	return nil
}

func (h *Handler) authorizeDataRegister(claims auth.Claims, req DataRecord) error {
	assignment, err := h.store.activeAssignment(req.OwnerPersonID)
	if err != nil {
		return err
	}
	if assignment.UserID != claims.UserID || strings.TrimSpace(req.OwnerUserID) != claims.UserID {
		return ErrForbiddenDelegation
	}
	if assignment.TenantID != strings.TrimSpace(req.TenantID) {
		return ErrForbiddenDelegation
	}
	return nil
}

func (h *Handler) endAssignmentForClaims(id int64, claims auth.Claims) (Assignment, error) {
	item, err := h.store.GetAssignment(id)
	if err != nil {
		return Assignment{}, err
	}
	if !mutationTenantAllowed(claims, item.TenantID) {
		return Assignment{}, ErrNotFound
	}
	return h.store.EndAssignment(id, claims.UserID)
}

func (h *Handler) approveResourcePublicationForClaims(id int64, claims auth.Claims) (ResourcePublication, error) {
	tenantID, err := h.store.ResourcePublicationTenant(id)
	if err != nil {
		return ResourcePublication{}, err
	}
	if !mutationTenantAllowed(claims, tenantID) {
		return ResourcePublication{}, ErrNotFound
	}
	return h.store.ApproveResourcePublication(id, claims.UserID)
}

func (h *Handler) setDataRecordStatusForClaims(id, status string, claims auth.Claims) (DataRecord, error) {
	item, err := h.store.GetDataRecord(id)
	if err != nil {
		return DataRecord{}, err
	}
	if !mutationTenantAllowed(claims, item.TenantID) {
		return DataRecord{}, ErrNotFound
	}
	return h.store.SetDataRecordStatus(id, status, claims.UserID)
}

func (h *Handler) requirePositionTenant(positionID string, claims auth.Claims) error {
	tenantID, err := h.store.positionTenant(positionID)
	if err != nil {
		return err
	}
	if !mutationTenantAllowed(claims, tenantID) {
		return ErrNotFound
	}
	return nil
}

func (h *Handler) requireDomainTenant(domainID string, claims auth.Claims) error {
	tenantID, err := h.store.domainTenant(domainID)
	if err != nil {
		return err
	}
	if !mutationTenantAllowed(claims, tenantID) {
		return ErrNotFound
	}
	return nil
}

func (h *Handler) requireDelegationTenant(req Delegation, claims auth.Claims) error {
	if claims.IsBreakglass || strings.TrimSpace(claims.OrgID) == "" {
		return nil
	}
	for _, personID := range []string{req.FromPersonID, req.ToPersonID} {
		ok, err := h.store.personActiveInTenant(personID, claims.OrgID)
		if err != nil {
			return err
		}
		if !ok {
			return ErrNotFound
		}
	}
	return nil
}

func (h *Handler) requireResourceTenant(resourceID string, claims auth.Claims) error {
	item, err := h.store.GetResource(resourceID)
	if err != nil {
		return err
	}
	if !mutationTenantAllowed(claims, item.TenantID) {
		return ErrNotFound
	}
	return nil
}

func mutationTenantAllowed(claims auth.Claims, tenantID string) bool {
	orgID := strings.TrimSpace(claims.OrgID)
	tenantID = strings.TrimSpace(tenantID)
	return claims.IsBreakglass || orgID == "" || (tenantID != "" && tenantID == orgID)
}

func (h *Handler) log(r *http.Request, actionType, actorID, resourceType, resourceID, policyID string) {
	if h.audit == nil {
		return
	}
	decision := policy.Decision{Allow: true, PolicyID: policyID}
	if err := h.audit.LogAction(audit.WithSpan(r.Context(), r.Header), actionType, actorID, resourceType, resourceID, decision, policyID, r.Header); err != nil {
		log.Printf("organization audit write failed action=%s: %v", actionType, err)
	}
}

func decodeBody(w http.ResponseWriter, r *http.Request, target interface{}) bool {
	if err := json.NewDecoder(r.Body).Decode(target); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return false
	}
	return true
}

func writeStoreError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrNotFound):
		writeError(w, http.StatusNotFound, "not_found")
	case errors.Is(err, ErrActiveAssignmentExist):
		writeError(w, http.StatusConflict, "active_assignment_exists")
	case errors.Is(err, ErrInvalidOwnerContext):
		writeError(w, http.StatusBadRequest, "owner_context_invalid")
	case strings.Contains(err.Error(), "missing field"):
		writeError(w, http.StatusBadRequest, "missing_field")
	case strings.Contains(err.Error(), "self manager"):
		writeError(w, http.StatusBadRequest, "self_manager")
	case strings.Contains(err.Error(), "invalid resource type"):
		writeError(w, http.StatusBadRequest, "invalid_resource_type")
	case strings.Contains(err.Error(), "invalid resource level"):
		writeError(w, http.StatusBadRequest, "invalid_resource_level")
	case strings.Contains(err.Error(), "invalid target level"):
		writeError(w, http.StatusBadRequest, "invalid_target_level")
	case strings.Contains(err.Error(), "invalid data status"):
		writeError(w, http.StatusBadRequest, "invalid_data_status")
	case strings.Contains(err.Error(), "invalid data action risk"):
		writeError(w, http.StatusBadRequest, "invalid_data_action_risk")
	case strings.Contains(err.Error(), "invalid data action"):
		writeError(w, http.StatusBadRequest, "invalid_data_action")
	case strings.Contains(err.Error(), "resource_not_personal"):
		writeError(w, http.StatusConflict, "resource_not_personal")
	default:
		writeError(w, http.StatusInternalServerError, "db_error")
	}
}

func pathID(path, prefix, suffix string) (int64, error) {
	value := strings.TrimSuffix(strings.TrimPrefix(path, prefix), suffix)
	value = strings.Trim(value, "/")
	return strconv.ParseInt(value, 10, 64)
}

func hasRole(claims auth.Claims, role string) bool {
	for _, current := range claims.RoleList {
		if current == role {
			return true
		}
	}
	return false
}

func isAdmin(claims auth.Claims) bool {
	return hasRole(claims, "hanhe_admin")
}

func isIM(claims auth.Claims) bool {
	return hasRole(claims, "hanhe_im")
}

func isDSM(claims auth.Claims) bool {
	return hasRole(claims, "hanhe_dsm")
}

func writeJSON(w http.ResponseWriter, status int, response interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(response)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
