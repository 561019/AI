package organization

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"hanhe.com/account-gateway/internal/auth"
)

type commandRequest struct {
	Action  string          `json:"action"`
	Payload json.RawMessage `json:"payload"`
}

func (h *Handler) orgCommands(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var req commandRequest
	if !decodeBody(w, r, &req) {
		return
	}
	req.Action = strings.TrimSpace(req.Action)
	switch req.Action {
	case "create_position":
		if !isIM(claims) && !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "im_only")
			return
		}
		var payload Position
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		if !defaultTenant(w, claims, &payload.TenantID) {
			return
		}
		payload.CreatedBy = claims.UserID
		item, err := h.store.CreatePosition(payload)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "positions.create", claims.UserID, "position", item.ID, "position:"+item.ID)
		writeJSON(w, http.StatusCreated, map[string]interface{}{"action": req.Action, "position": item})
	case "assign_person_position":
		if !isIM(claims) && !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "im_only")
			return
		}
		var payload Assignment
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		if !defaultTenant(w, claims, &payload.TenantID) {
			return
		}
		payload.AssignedBy = claims.UserID
		item, err := h.store.CreateAssignment(payload)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "person_position.assign", claims.UserID, "person_position_assignment", strconv.FormatInt(item.ID, 10), "assignment:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusCreated, map[string]interface{}{"action": req.Action, "assignment": item})
	case "end_person_position":
		if !isIM(claims) && !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "im_only")
			return
		}
		var payload struct {
			ID int64 `json:"id"`
		}
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		item, err := h.endAssignmentForClaims(payload.ID, claims)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "person_position.end", claims.UserID, "person_position_assignment", strconv.FormatInt(item.ID, 10), "assignment:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusOK, map[string]interface{}{"action": req.Action, "assignment": item})
	case "create_domain":
		if !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "admin_only")
			return
		}
		var payload Domain
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		if !defaultTenant(w, claims, &payload.TenantID) {
			return
		}
		payload.CreatedBy = claims.UserID
		item, err := h.store.CreateDomain(payload)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "domains.create", claims.UserID, "domain", item.ID, "domain:"+item.ID)
		writeJSON(w, http.StatusCreated, map[string]interface{}{"action": req.Action, "domain": item})
	case "upsert_manager_edge":
		if !isDSM(claims) && !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "dsm_only")
			return
		}
		var payload ManagerEdge
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		if err := h.requireDomainTenant(payload.DomainID, claims); err != nil {
			writeStoreError(w, err)
			return
		}
		payload.CreatedBy = claims.UserID
		item, err := h.store.UpsertManagerEdge(payload)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "manager_edges.upsert", claims.UserID, "manager_edge", strconv.FormatInt(item.ID, 10), "manager_edge:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusCreated, map[string]interface{}{"action": req.Action, "manager_edge": item})
	default:
		writeError(w, http.StatusBadRequest, "unknown_action")
	}
}

func (h *Handler) orgSnapshot(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	if !isIM(claims) && !isDSM(claims) && !isAdmin(claims) {
		writeError(w, http.StatusForbidden, "org_snapshot_forbidden")
		return
	}
	tenantID, ok := tenantScope(w, r, claims)
	if !ok {
		return
	}
	positions, err := h.store.ListPositionsByTenant(tenantID)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	assignments, err := h.store.ListAssignmentsByTenant(tenantID)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	domains := []Domain{}
	managerEdges := []ManagerEdge{}
	subordinates := []Subordinate{}
	if isDSM(claims) || isAdmin(claims) {
		domains, err = h.store.ListDomainsByTenant(tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		managerEdges, err = h.store.ListManagerEdgesByTenant(tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		if r.URL.Query().Get("manager_person_id") != "" && r.URL.Query().Get("domain_id") != "" {
			subordinates, err = h.store.ListSubordinatesByTenant(r.URL.Query().Get("manager_person_id"), r.URL.Query().Get("domain_id"), tenantID)
			if err != nil {
				writeStoreError(w, err)
				return
			}
		}
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"positions":     positions,
		"assignments":   assignments,
		"domains":       domains,
		"manager_edges": managerEdges,
		"subordinates":  subordinates,
	})
}

func (h *Handler) permissionCommands(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var req commandRequest
	if !decodeBody(w, r, &req) {
		return
	}
	req.Action = strings.TrimSpace(req.Action)
	switch req.Action {
	case "create_position_standard_resource":
		if !isDSM(claims) && !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "dsm_only")
			return
		}
		var payload StandardResource
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		if err := h.requirePositionTenant(payload.PositionID, claims); err != nil {
			writeStoreError(w, err)
			return
		}
		payload.CreatedBy = claims.UserID
		item, err := h.store.CreateStandardResource(payload)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "position_standard_resources.create", claims.UserID, "position_standard_resource", strconv.FormatInt(item.ID, 10), "position_standard:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusCreated, map[string]interface{}{"action": req.Action, "position_standard_resource": item})
	case "create_delegation":
		var payload Delegation
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		payload.CreatedBy = claims.UserID
		if !isDSM(claims) && !isAdmin(claims) {
			if err := h.authorizeDelegationByUser(claims, payload); err != nil {
				if errors.Is(err, ErrForbiddenDelegation) {
					writeError(w, http.StatusForbidden, "delegation_forbidden")
					return
				}
				writeStoreError(w, err)
				return
			}
		}
		if err := h.requireDelegationTenant(payload, claims); err != nil {
			writeStoreError(w, err)
			return
		}
		item, err := h.store.CreateDelegation(payload)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "delegations.create", claims.UserID, "delegation", strconv.FormatInt(item.ID, 10), "delegation:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusCreated, map[string]interface{}{"action": req.Action, "delegation": item})
	case "create_resource":
		var payload Resource
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		if !defaultTenant(w, claims, &payload.TenantID) {
			return
		}
		payload.CreatedBy = claims.UserID
		if !isDSM(claims) && !isAdmin(claims) {
			if err := h.authorizeResourceCreate(claims, payload); err != nil {
				if errors.Is(err, ErrForbiddenDelegation) {
					writeError(w, http.StatusForbidden, "resource_forbidden")
					return
				}
				writeStoreError(w, err)
				return
			}
		}
		item, err := h.store.CreateResource(payload)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "resources.create", claims.UserID, item.ResourceType, item.ID, "resource:"+item.ID)
		writeJSON(w, http.StatusCreated, map[string]interface{}{"action": req.Action, "resource": item})
	case "register_data":
		var payload DataRecord
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		if !defaultTenant(w, claims, &payload.TenantID) {
			return
		}
		payload.CreatedBy = claims.UserID
		if !isDSM(claims) && !isAdmin(claims) {
			if err := h.authorizeDataRegister(claims, payload); err != nil {
				if errors.Is(err, ErrForbiddenDelegation) {
					writeError(w, http.StatusForbidden, "data_register_forbidden")
					return
				}
				writeStoreError(w, err)
				return
			}
		}
		item, err := h.store.CreateDataRecord(payload)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "data_records.register", claims.UserID, "data", item.ID, "data_record:"+item.ID)
		writeJSON(w, http.StatusCreated, map[string]interface{}{"action": req.Action, "data_record": item})
	case "register_data_action":
		if !isDSM(claims) && !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "dsm_only")
			return
		}
		var payload DataAction
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		payload.CreatedBy = claims.UserID
		item, err := h.store.RegisterDataAction(payload)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "data_actions.register", claims.UserID, "data_action", item.Action, "data_action:"+item.Action)
		writeJSON(w, http.StatusCreated, map[string]interface{}{"action": req.Action, "data_action": item})
	case "set_data_status":
		if !isDSM(claims) && !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "dsm_only")
			return
		}
		var payload struct {
			ID     string `json:"id"`
			Status string `json:"status"`
		}
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		item, err := h.setDataRecordStatusForClaims(payload.ID, payload.Status, claims)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		h.log(r, "data_records.status", claims.UserID, "data", item.ID, "data_record:"+item.ID+":"+item.Status)
		writeJSON(w, http.StatusOK, map[string]interface{}{"action": req.Action, "data_record": item})
	case "request_resource_publication":
		var payload ResourcePublication
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		if err := h.requireResourceTenant(payload.ResourceID, claims); err != nil {
			writeStoreError(w, err)
			return
		}
		item, err := h.store.CreateResourcePublication(payload, claims.UserID, isDSM(claims) || isAdmin(claims))
		if err != nil {
			if errors.Is(err, ErrForbiddenDelegation) {
				writeError(w, http.StatusForbidden, "publication_forbidden")
				return
			}
			writeStoreError(w, err)
			return
		}
		h.log(r, "resource_publications.create", claims.UserID, "resource_publication", strconv.FormatInt(item.ID, 10), "resource_publication:"+strconv.FormatInt(item.ID, 10))
		writeJSON(w, http.StatusCreated, map[string]interface{}{"action": req.Action, "resource_publication": item})
	case "approve_resource_publication":
		if !isDSM(claims) && !isAdmin(claims) {
			writeError(w, http.StatusForbidden, "dsm_only")
			return
		}
		var payload struct {
			ID int64 `json:"id"`
		}
		if !decodePayload(w, req.Payload, &payload) {
			return
		}
		item, err := h.approveResourcePublicationForClaims(payload.ID, claims)
		if err != nil {
			writeStoreError(w, err)
			return
		}
		policyID := "resource_publication:" + strconv.FormatInt(item.ID, 10)
		h.log(r, "resource_publications.approve", claims.UserID, "resource_publication", strconv.FormatInt(item.ID, 10), policyID)
		writeJSON(w, http.StatusOK, map[string]interface{}{"action": req.Action, "resource_publication": item, "policy_id": policyID})
	default:
		writeError(w, http.StatusBadRequest, "unknown_action")
	}
}

func (h *Handler) permissionSnapshot(w http.ResponseWriter, r *http.Request, claims auth.Claims) {
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	tenantID, ok := tenantScope(w, r, claims)
	if !ok {
		return
	}
	elevated := isDSM(claims) || isAdmin(claims)
	standardResources := []StandardResource{}
	delegations := []Delegation{}
	if elevated {
		var err error
		standardResources, err = h.store.ListStandardResourcesByTenant(tenantID)
		if err != nil {
			writeStoreError(w, err)
			return
		}
	}
	delegations, err := h.store.ListDelegationsForSnapshot(claims.UserID, elevated, DelegationFilters{
		PersonID:     r.URL.Query().Get("person_id"),
		ResourceType: r.URL.Query().Get("resource_type"),
		ResourceID:   r.URL.Query().Get("resource_id"),
		Action:       r.URL.Query().Get("action"),
		OwnerUserID:  r.URL.Query().Get("owner_user_id"),
		TenantID:     tenantID,
	})
	if err != nil {
		writeStoreError(w, err)
		return
	}
	resources, err := h.store.ListResources(claims.UserID, elevated, ResourceFilters{
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
	dataRecords, err := h.store.ListDataRecords(elevated, claims.UserID, DataRecordFilters{
		OwnerPersonID: r.URL.Query().Get("owner_person_id"),
		OwnerUserID:   r.URL.Query().Get("owner_user_id"),
		TenantID:      tenantID,
		Status:        r.URL.Query().Get("status"),
	})
	if err != nil {
		writeStoreError(w, err)
		return
	}
	dataAccessSummary, err := h.store.BuildDataAccessSummaryByTenant(claims.UserID, elevated, tenantID, dataRecords)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	dataActions, err := h.store.ListDataActions()
	if err != nil {
		writeStoreError(w, err)
		return
	}
	publications, err := h.store.ListResourcePublicationsByTenant(claims.UserID, elevated, tenantID)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"position_standard_resources": standardResources,
		"delegations":                 delegations,
		"resources":                   resources,
		"data_records":                dataRecords,
		"data_access_summary":         dataAccessSummary,
		"data_actions":                dataActions,
		"resource_publications":       publications,
	})
}

func decodePayload(w http.ResponseWriter, raw json.RawMessage, target interface{}) bool {
	if len(raw) == 0 {
		writeError(w, http.StatusBadRequest, "missing_payload")
		return false
	}
	if err := json.Unmarshal(raw, target); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_payload")
		return false
	}
	return true
}
