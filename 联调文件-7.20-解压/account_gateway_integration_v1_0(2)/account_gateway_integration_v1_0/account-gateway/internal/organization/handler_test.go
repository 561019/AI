package organization

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/audit"
	"hanhe.com/account-gateway/internal/auth"

	_ "github.com/mattn/go-sqlite3"
)

func TestOrganizationRolesAndAssignmentLifecycle(t *testing.T) {
	handler, jwt, _ := newTestHandler(t)

	staff := token(t, jwt, "staff", []string{"staff"})
	im := token(t, jwt, "im-user", []string{"hanhe_im"})
	dsm := token(t, jwt, "dsm-user", []string{"hanhe_dsm"})
	admin := token(t, jwt, "admin", []string{"hanhe_admin"})

	forbidden := doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-a","title":"Analyst","department_id":"dep-a","tenant_id":"org-1","tags":["finance"]}`, staff)
	if forbidden.Code != http.StatusForbidden {
		t.Fatalf("staff create position status = %d, body = %s", forbidden.Code, forbidden.Body.String())
	}

	created := doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-a","title":"Analyst","department_id":"dep-a","tenant_id":"org-1","tags":["finance"]}`, im)
	if created.Code != http.StatusCreated {
		t.Fatalf("create position status = %d, body = %s", created.Code, created.Body.String())
	}

	assignment := doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-a","user_id":"user-a","position_id":"pos-a","tenant_id":"org-1"}`, im)
	if assignment.Code != http.StatusCreated {
		t.Fatalf("create assignment status = %d, body = %s", assignment.Code, assignment.Body.String())
	}
	var assignmentBody Assignment
	if err := json.Unmarshal(assignment.Body.Bytes(), &assignmentBody); err != nil {
		t.Fatalf("decode assignment: %v", err)
	}

	duplicate := doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-a","user_id":"user-a","position_id":"pos-a","tenant_id":"org-1"}`, im)
	if duplicate.Code != http.StatusConflict {
		t.Fatalf("duplicate assignment status = %d, body = %s", duplicate.Code, duplicate.Body.String())
	}

	domainByDSM := doRequest(handler, http.MethodPost, "/api/domains", `{"id":"domain-a","name":"Finance","tenant_id":"org-1","dsm_user_id":"dsm-user"}`, dsm)
	if domainByDSM.Code != http.StatusForbidden {
		t.Fatalf("dsm create domain status = %d", domainByDSM.Code)
	}

	domain := doRequest(handler, http.MethodPost, "/api/domains", `{"id":"domain-a","name":"Finance","tenant_id":"org-1","dsm_user_id":"dsm-user"}`, admin)
	if domain.Code != http.StatusCreated {
		t.Fatalf("admin create domain status = %d, body = %s", domain.Code, domain.Body.String())
	}

	selfManager := doRequest(handler, http.MethodPost, "/api/person-manager-edges", `{"person_id":"person-a","manager_person_id":"person-a","domain_id":"domain-a"}`, dsm)
	if selfManager.Code != http.StatusBadRequest {
		t.Fatalf("self manager status = %d, body = %s", selfManager.Code, selfManager.Body.String())
	}

	edge := doRequest(handler, http.MethodPost, "/api/person-manager-edges", `{"person_id":"person-a","manager_person_id":"person-mgr","domain_id":"domain-a"}`, dsm)
	if edge.Code != http.StatusCreated {
		t.Fatalf("create manager edge status = %d, body = %s", edge.Code, edge.Body.String())
	}

	ended := doRequest(handler, http.MethodPost, "/api/person-position-assignments/"+itoa(assignmentBody.ID)+"/end", "", im)
	if ended.Code != http.StatusOK {
		t.Fatalf("end assignment status = %d, body = %s", ended.Code, ended.Body.String())
	}
}

func TestDelegationRequiresExistingRedelegableAccess(t *testing.T) {
	handler, jwt, _ := newTestHandler(t)
	im := token(t, jwt, "im-user", []string{"hanhe_im"})
	dsm := token(t, jwt, "dsm-user", []string{"hanhe_dsm"})
	userA := token(t, jwt, "user-a", []string{"staff"})
	userB := token(t, jwt, "user-b", []string{"staff"})

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-a","title":"A","department_id":"dep","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-b","title":"B","department_id":"dep","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-a","user_id":"user-a","position_id":"pos-a","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-b","user_id":"user-b","position_id":"pos-b","tenant_id":"org-1"}`, im), http.StatusCreated)

	noAccess := doRequest(handler, http.MethodPost, "/api/delegations", `{"from_person_id":"person-b","to_person_id":"person-a","resource_type":"data","resource_id":"data-1","action":"fetch","owner_user_id":"owner-1","basis":"try"}`, userB)
	if noAccess.Code != http.StatusForbidden {
		t.Fatalf("no access delegation status = %d, body = %s", noAccess.Code, noAccess.Body.String())
	}

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/position-standard-resources", `{"position_id":"pos-a","resource_type":"data","resource_id":"data-1","action":"fetch","owner_user_id":"owner-1"}`, dsm), http.StatusCreated)

	delegation := doRequest(handler, http.MethodPost, "/api/delegations", `{"from_person_id":"person-a","to_person_id":"person-b","resource_type":"data","resource_id":"data-1","action":"fetch","owner_user_id":"owner-1","basis":"handoff"}`, userA)
	if delegation.Code != http.StatusCreated {
		t.Fatalf("delegation status = %d, body = %s", delegation.Code, delegation.Body.String())
	}
}

func TestPersonCanHoldMultipleActivePositions(t *testing.T) {
	handler, jwt, db := newTestHandler(t)
	store := NewStore(db)
	im := token(t, jwt, "im-user", []string{"hanhe_im"})
	dsm := token(t, jwt, "dsm-user", []string{"hanhe_dsm"})

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-primary","title":"Primary","department_id":"dep-a","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-secondary","title":"Secondary","department_id":"dep-b","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-multi","user_id":"user-multi","position_id":"pos-primary","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-multi","user_id":"user-multi","position_id":"pos-secondary","tenant_id":"org-1"}`, im), http.StatusCreated)

	occupied := doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-other","user_id":"user-other","position_id":"pos-secondary","tenant_id":"org-1"}`, im)
	if occupied.Code != http.StatusConflict {
		t.Fatalf("occupied position assignment status = %d, body = %s", occupied.Code, occupied.Body.String())
	}

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/position-standard-resources", `{"position_id":"pos-secondary","resource_type":"data","resource_id":"data-secondary","action":"fetch","owner_user_id":"owner-secondary"}`, dsm), http.StatusCreated)
	decision, err := store.PersonHasAccess(ValidateContext{
		UserID:       "user-multi",
		TenantID:     "org-1",
		PersonID:     "person-multi",
		ResourceType: "data",
		ResourceID:   "data-secondary",
		Action:       "fetch",
		OwnerUserID:  "owner-secondary",
	})
	if err != nil {
		t.Fatalf("validate multi-position access: %v", err)
	}
	if !decision.Allow || !strings.HasPrefix(decision.PolicyID, "position_standard:") {
		t.Fatalf("unexpected decision: %+v", decision)
	}
}

func TestResourcesAndPublications(t *testing.T) {
	handler, jwt, _ := newTestHandler(t)
	im := token(t, jwt, "im-user", []string{"hanhe_im"})
	dsm := token(t, jwt, "dsm-user", []string{"hanhe_dsm"})
	userA := token(t, jwt, "user-a", []string{"staff"})
	userB := token(t, jwt, "user-b", []string{"staff"})

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-a","title":"A","department_id":"dep-a","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-b","title":"B","department_id":"dep-a","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-a","user_id":"user-a","position_id":"pos-a","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-b","user_id":"user-b","position_id":"pos-b","tenant_id":"org-1"}`, im), http.StatusCreated)

	forbiddenCreate := doRequest(handler, http.MethodPost, "/api/resources", `{"id":"skill-a","name":"Skill A","resource_type":"skill","owner_person_id":"person-a","owner_user_id":"user-a","owner_position_id":"pos-a","department_id":"dep-a","tenant_id":"org-1"}`, userB)
	if forbiddenCreate.Code != http.StatusForbidden {
		t.Fatalf("forbidden create status = %d, body = %s", forbiddenCreate.Code, forbiddenCreate.Body.String())
	}
	created := doRequest(handler, http.MethodPost, "/api/resources", `{"id":"skill-a","name":"Skill A","resource_type":"skill","owner_person_id":"person-a","owner_user_id":"user-a","owner_position_id":"pos-a","department_id":"dep-a","tenant_id":"org-1"}`, userA)
	if created.Code != http.StatusCreated {
		t.Fatalf("create resource status = %d, body = %s", created.Code, created.Body.String())
	}

	forbiddenPublication := doRequest(handler, http.MethodPost, "/api/resource-publications", `{"resource_id":"skill-a","target_level":"department_public","reason":"share"}`, userB)
	if forbiddenPublication.Code != http.StatusForbidden {
		t.Fatalf("forbidden publication status = %d, body = %s", forbiddenPublication.Code, forbiddenPublication.Body.String())
	}
	publication := doRequest(handler, http.MethodPost, "/api/resource-publications", `{"resource_id":"skill-a","target_level":"department_public","reason":"share"}`, userA)
	if publication.Code != http.StatusCreated {
		t.Fatalf("publication status = %d, body = %s", publication.Code, publication.Body.String())
	}
	var publicationBody ResourcePublication
	if err := json.Unmarshal(publication.Body.Bytes(), &publicationBody); err != nil {
		t.Fatalf("decode publication: %v", err)
	}
	approveForbidden := doRequest(handler, http.MethodPost, "/api/resource-publications/"+itoa(publicationBody.ID)+"/approve", "", userA)
	if approveForbidden.Code != http.StatusForbidden {
		t.Fatalf("approve forbidden status = %d, body = %s", approveForbidden.Code, approveForbidden.Body.String())
	}
	approved := doRequest(handler, http.MethodPost, "/api/resource-publications/"+itoa(publicationBody.ID)+"/approve", "", dsm)
	if approved.Code != http.StatusOK {
		t.Fatalf("approve status = %d, body = %s", approved.Code, approved.Body.String())
	}
	var approvedBody map[string]interface{}
	if err := json.Unmarshal(approved.Body.Bytes(), &approvedBody); err != nil {
		t.Fatalf("decode approved: %v", err)
	}
	if approvedBody["policy_id"] != "resource_publication:"+itoa(publicationBody.ID) {
		t.Fatalf("unexpected approve body: %+v", approvedBody)
	}

	digitalCreated := doRequest(handler, http.MethodPost, "/api/resources", `{"id":"agent-a","name":"Agent A","resource_type":"digital_employee","owner_person_id":"person-a","owner_user_id":"user-a","owner_position_id":"pos-a","department_id":"dep-a","tenant_id":"org-1"}`, userA)
	if digitalCreated.Code != http.StatusCreated {
		t.Fatalf("create digital employee resource status = %d, body = %s", digitalCreated.Code, digitalCreated.Body.String())
	}
	digitalPublication := doRequest(handler, http.MethodPost, "/api/resource-publications", `{"resource_id":"agent-a","target_level":"department_public","reason":"share agent"}`, userA)
	if digitalPublication.Code != http.StatusCreated {
		t.Fatalf("digital publication status = %d, body = %s", digitalPublication.Code, digitalPublication.Body.String())
	}
}

func TestDataActionCatalogControlsDataRecordAllowedActions(t *testing.T) {
	handler, jwt, _ := newTestHandler(t)
	im := token(t, jwt, "im-user", []string{"hanhe_im"})
	dsm := token(t, jwt, "dsm-user", []string{"hanhe_dsm"})
	staff := token(t, jwt, "staff", []string{"staff"})
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-data-owner","title":"Data Owner","department_id":"dep-a","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-a","user_id":"user-a","position_id":"pos-data-owner","tenant_id":"org-1"}`, im), http.StatusCreated)

	forbidden := doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"register_data_action","payload":{"action":"archive_review","description":"归档复核","risk_level":"normal"}}`, staff)
	if forbidden.Code != http.StatusForbidden {
		t.Fatalf("staff register action status = %d, body = %s", forbidden.Code, forbidden.Body.String())
	}

	invalidRecord := doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"register_data","payload":{"id":"data-custom","title":"Custom Data","source_type":"report","owner_person_id":"person-a","owner_user_id":"user-a","tenant_id":"org-1","allowed_actions":["archive_review"],"basis":"v1.8.5"}}`, dsm)
	if invalidRecord.Code != http.StatusBadRequest {
		t.Fatalf("unregistered data action status = %d, body = %s", invalidRecord.Code, invalidRecord.Body.String())
	}

	registered := doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"register_data_action","payload":{"action":"archive_review","description":"归档复核","risk_level":"high"}}`, dsm)
	if registered.Code != http.StatusCreated {
		t.Fatalf("register data action status = %d, body = %s", registered.Code, registered.Body.String())
	}

	createdRecord := doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"register_data","payload":{"id":"data-custom","title":"Custom Data","source_type":"report","owner_person_id":"person-a","owner_user_id":"user-a","tenant_id":"org-1","allowed_actions":["archive_review"],"basis":"v1.8.5"}}`, dsm)
	if createdRecord.Code != http.StatusCreated {
		t.Fatalf("registered data action record status = %d, body = %s", createdRecord.Code, createdRecord.Body.String())
	}

	snapshot := doRequest(handler, http.MethodGet, "/api/permissions/snapshot", "", dsm)
	if snapshot.Code != http.StatusOK {
		t.Fatalf("snapshot status = %d, body = %s", snapshot.Code, snapshot.Body.String())
	}
	var body struct {
		DataActions []DataAction `json:"data_actions"`
	}
	if err := json.Unmarshal(snapshot.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode snapshot: %v", err)
	}
	foundCustom := false
	foundDefaultFreeze := false
	for _, action := range body.DataActions {
		if action.Action == "archive_review" && action.Enabled && action.RiskLevel == "high" {
			foundCustom = true
		}
		if action.Action == "freeze" && action.Enabled {
			foundDefaultFreeze = true
		}
	}
	if !foundCustom || !foundDefaultFreeze {
		t.Fatalf("unexpected data actions: %+v", body.DataActions)
	}
}

func TestPermissionSnapshotIncludesDataAccessSummary(t *testing.T) {
	handler, jwt, _ := newTestHandler(t)
	im := token(t, jwt, "im-user", []string{"hanhe_im"})
	dsm := token(t, jwt, "dsm-user", []string{"hanhe_dsm"})

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-owner","title":"Owner","department_id":"dep","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-initial","title":"Initial","department_id":"dep","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-standard","title":"Standard","department_id":"dep","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-delegated","title":"Delegated","department_id":"dep","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-owner","user_id":"user-owner","position_id":"pos-owner","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-initial","user_id":"user-initial","position_id":"pos-initial","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-standard","user_id":"user-standard","position_id":"pos-standard","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-delegated","user_id":"user-delegated","position_id":"pos-delegated","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"register_data","payload":{"id":"data-summary","title":"Summary Data","source_type":"report","owner_person_id":"person-owner","owner_user_id":"user-owner","tenant_id":"org-1","allowed_actions":["fetch","update"],"initial_person_ids":["person-initial"],"basis":"summary"}}`, dsm), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/position-standard-resources", `{"position_id":"pos-standard","resource_type":"data","resource_id":"data-summary","action":"fetch","owner_user_id":"owner-summary"}`, dsm), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/delegations", `{"from_person_id":"person-owner","to_person_id":"person-delegated","resource_type":"data","resource_id":"data-summary","action":"fetch","owner_user_id":"owner-summary","basis":"summary delegation"}`, dsm), http.StatusCreated)

	snapshot := doRequest(handler, http.MethodGet, "/api/permissions/snapshot?resource_id=data-summary", "", dsm)
	if snapshot.Code != http.StatusOK {
		t.Fatalf("snapshot status = %d, body = %s", snapshot.Code, snapshot.Body.String())
	}
	var body struct {
		DataAccessSummary []DataAccessEntry `json:"data_access_summary"`
	}
	if err := json.Unmarshal(snapshot.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode snapshot: %v", err)
	}
	seen := map[string]bool{}
	for _, entry := range body.DataAccessSummary {
		seen[entry.Source+":"+entry.PersonID+":"+entry.Action] = true
	}
	for _, key := range []string{
		"owner:person-owner:fetch",
		"owner:person-owner:update",
		"initial_participant:person-initial:fetch",
		"position_standard:person-standard:fetch",
		"delegation:person-delegated:fetch",
	} {
		if !seen[key] {
			t.Fatalf("missing summary entry %s in %+v", key, body.DataAccessSummary)
		}
	}
}

func TestFreezeAssetsForUserMovesAssetsToOffboardingPool(t *testing.T) {
	handler, jwt, _ := newTestHandler(t)
	store := handler.store
	im := token(t, jwt, "im-user", []string{"hanhe_im"})
	user := token(t, jwt, "leaver", []string{"staff"})
	dsm := token(t, jwt, "dsm-user", []string{"hanhe_dsm"})

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-leaver","title":"Leaver","department_id":"dep","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-leaver","user_id":"leaver","position_id":"pos-leaver","tenant_id":"org-1"}`, im), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/resources", `{"id":"skill-leaver","name":"Skill","resource_type":"skill","owner_person_id":"person-leaver","owner_user_id":"leaver","owner_position_id":"pos-leaver","department_id":"dep","tenant_id":"org-1"}`, user), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"register_data","payload":{"id":"data-leaver","title":"Data","source_type":"report","owner_person_id":"person-leaver","owner_user_id":"leaver","tenant_id":"org-1","allowed_actions":["fetch"],"basis":"offboarding"}}`, dsm), http.StatusCreated)

	summary, err := store.FreezeAssetsForUser("leaver", "org-1", "admin-user")
	if err != nil {
		t.Fatalf("freeze assets: %v", err)
	}
	if summary.Resources != 1 || summary.DataRecords != 1 {
		t.Fatalf("unexpected freeze summary: %+v", summary)
	}

	resources, err := store.ListResources("dsm-user", true, ResourceFilters{Status: "frozen"})
	if err != nil {
		t.Fatalf("list resources: %v", err)
	}
	if len(resources) != 1 || resources[0].AssetPool != "offboarding" || resources[0].LockedBy != "admin-user" || resources[0].LockedAt == "" {
		t.Fatalf("unexpected frozen resources: %+v", resources)
	}
	records, err := store.ListDataRecords(true, "dsm-user", DataRecordFilters{Status: "frozen"})
	if err != nil {
		t.Fatalf("list data records: %v", err)
	}
	if len(records) != 1 || records[0].AssetPool != "offboarding" || records[0].LockedBy != "admin-user" || records[0].LockedAt == "" {
		t.Fatalf("unexpected frozen data records: %+v", records)
	}
	assets, err := store.OffboardingAssetsForUser("leaver", "org-1")
	if err != nil {
		t.Fatalf("offboarding assets: %v", err)
	}
	if len(assets.Resources) != 1 || assets.Resources[0].ID != "skill-leaver" || assets.Resources[0].AssetPool != "offboarding" {
		t.Fatalf("unexpected offboarding resources: %+v", assets)
	}
	if len(assets.DataRecords) != 1 || assets.DataRecords[0].ID != "data-leaver" || assets.DataRecords[0].LockedBy != "admin-user" {
		t.Fatalf("unexpected offboarding data records: %+v", assets)
	}
}

func TestSnapshotsDefaultToJWTTenantAndRejectCrossTenantQuery(t *testing.T) {
	handler, jwt, _ := newTestHandler(t)
	im1 := tokenForOrg(t, jwt, "im-org-1", "org-1", []string{"hanhe_im"})
	dsm1 := tokenForOrg(t, jwt, "dsm-org-1", "org-1", []string{"hanhe_dsm"})
	admin1 := tokenForOrg(t, jwt, "admin-org-1", "org-1", []string{"hanhe_admin"})
	im2 := tokenForOrg(t, jwt, "im-org-2", "org-2", []string{"hanhe_im"})
	dsm2 := tokenForOrg(t, jwt, "dsm-org-2", "org-2", []string{"hanhe_dsm"})
	admin2 := tokenForOrg(t, jwt, "admin-org-2", "org-2", []string{"hanhe_admin"})

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/org/commands", `{"action":"create_position","payload":{"id":"pos-org-1","title":"Org 1","department_id":"dep-1"}}`, im1), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/org/commands", `{"action":"assign_person_position","payload":{"person_id":"person-org-1","user_id":"user-org-1","position_id":"pos-org-1"}}`, im1), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/org/commands", `{"action":"create_domain","payload":{"id":"domain-org-1","name":"Domain 1","dsm_user_id":"dsm-org-1"}}`, admin1), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/org/commands", `{"action":"upsert_manager_edge","payload":{"person_id":"person-org-1","manager_person_id":"manager-org-1","domain_id":"domain-org-1"}}`, dsm1), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"create_resource","payload":{"id":"resource-org-1","name":"Resource 1","resource_type":"skill","owner_person_id":"person-org-1","owner_user_id":"user-org-1","owner_position_id":"pos-org-1","department_id":"dep-1"}}`, admin1), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"register_data","payload":{"id":"data-org-1","title":"Data 1","source_type":"report","owner_person_id":"person-org-1","owner_user_id":"user-org-1","basis":"tenant scope"}}`, admin1), http.StatusCreated)

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/org/commands", `{"action":"create_position","payload":{"id":"pos-org-2","title":"Org 2","department_id":"dep-2"}}`, im2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/org/commands", `{"action":"assign_person_position","payload":{"person_id":"person-org-2","user_id":"user-org-2","position_id":"pos-org-2"}}`, im2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/org/commands", `{"action":"create_domain","payload":{"id":"domain-org-2","name":"Domain 2","dsm_user_id":"dsm-org-2"}}`, admin2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/org/commands", `{"action":"upsert_manager_edge","payload":{"person_id":"person-org-2","manager_person_id":"manager-org-2","domain_id":"domain-org-2"}}`, dsm2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"create_resource","payload":{"id":"resource-org-2","name":"Resource 2","resource_type":"skill","owner_person_id":"person-org-2","owner_user_id":"user-org-2","owner_position_id":"pos-org-2","department_id":"dep-2"}}`, admin2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"register_data","payload":{"id":"data-org-2","title":"Data 2","source_type":"report","owner_person_id":"person-org-2","owner_user_id":"user-org-2","basis":"tenant scope"}}`, admin2), http.StatusCreated)

	orgSnapshot := doRequest(handler, http.MethodGet, "/api/org/snapshot", "", dsm1)
	mustStatus(t, orgSnapshot, http.StatusOK)
	var orgBody struct {
		Positions    []Position    `json:"positions"`
		Assignments  []Assignment  `json:"assignments"`
		Domains      []Domain      `json:"domains"`
		ManagerEdges []ManagerEdge `json:"manager_edges"`
	}
	if err := json.Unmarshal(orgSnapshot.Body.Bytes(), &orgBody); err != nil {
		t.Fatalf("decode org snapshot: %v", err)
	}
	if !hasPosition(orgBody.Positions, "pos-org-1") || hasPosition(orgBody.Positions, "pos-org-2") {
		t.Fatalf("unexpected scoped positions: %+v", orgBody.Positions)
	}
	if !hasAssignment(orgBody.Assignments, "person-org-1") || hasAssignment(orgBody.Assignments, "person-org-2") {
		t.Fatalf("unexpected scoped assignments: %+v", orgBody.Assignments)
	}
	if !hasDomain(orgBody.Domains, "domain-org-1") || hasDomain(orgBody.Domains, "domain-org-2") {
		t.Fatalf("unexpected scoped domains: %+v", orgBody.Domains)
	}
	if len(orgBody.ManagerEdges) != 1 || orgBody.ManagerEdges[0].DomainID != "domain-org-1" {
		t.Fatalf("unexpected scoped manager edges: %+v", orgBody.ManagerEdges)
	}

	permissionSnapshot := doRequest(handler, http.MethodGet, "/api/permissions/snapshot", "", admin1)
	mustStatus(t, permissionSnapshot, http.StatusOK)
	var permissionBody struct {
		Resources   []Resource   `json:"resources"`
		DataRecords []DataRecord `json:"data_records"`
	}
	if err := json.Unmarshal(permissionSnapshot.Body.Bytes(), &permissionBody); err != nil {
		t.Fatalf("decode permission snapshot: %v", err)
	}
	if !hasResource(permissionBody.Resources, "resource-org-1") || hasResource(permissionBody.Resources, "resource-org-2") {
		t.Fatalf("unexpected scoped resources: %+v", permissionBody.Resources)
	}
	if !hasDataRecord(permissionBody.DataRecords, "data-org-1") || hasDataRecord(permissionBody.DataRecords, "data-org-2") {
		t.Fatalf("unexpected scoped data records: %+v", permissionBody.DataRecords)
	}

	sameTenant := doRequest(handler, http.MethodGet, "/api/org/snapshot?tenant_id=org-1", "", dsm1)
	mustStatus(t, sameTenant, http.StatusOK)
	crossTenant := doRequest(handler, http.MethodGet, "/api/org/snapshot?tenant_id=org-2", "", dsm1)
	mustStatus(t, crossTenant, http.StatusForbidden)
	if !strings.Contains(crossTenant.Body.String(), "tenant_mismatch") {
		t.Fatalf("unexpected cross-tenant body: %s", crossTenant.Body.String())
	}
}

func TestMutatingEndpointsRejectCrossTenantRecords(t *testing.T) {
	handler, jwt, _ := newTestHandler(t)
	im1 := tokenForOrg(t, jwt, "im-org-1", "org-1", []string{"hanhe_im"})
	dsm1 := tokenForOrg(t, jwt, "dsm-org-1", "org-1", []string{"hanhe_dsm"})
	admin1 := tokenForOrg(t, jwt, "admin-org-1", "org-1", []string{"hanhe_admin"})
	im2 := tokenForOrg(t, jwt, "im-org-2", "org-2", []string{"hanhe_im"})
	dsm2 := tokenForOrg(t, jwt, "dsm-org-2", "org-2", []string{"hanhe_dsm"})
	admin2 := tokenForOrg(t, jwt, "admin-org-2", "org-2", []string{"hanhe_admin"})

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-scope-1","title":"Org 1","department_id":"dep-1"}`, im1), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-scope-2a","title":"Org 2 A","department_id":"dep-2"}`, im2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/positions", `{"id":"pos-scope-2b","title":"Org 2 B","department_id":"dep-2"}`, im2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-scope-1","user_id":"user-scope-1","position_id":"pos-scope-1"}`, im1), http.StatusCreated)
	assignment2 := doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-scope-2a","user_id":"user-scope-2a","position_id":"pos-scope-2a"}`, im2)
	mustStatus(t, assignment2, http.StatusCreated)
	var assignmentBody Assignment
	if err := json.Unmarshal(assignment2.Body.Bytes(), &assignmentBody); err != nil {
		t.Fatalf("decode assignment: %v", err)
	}
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-scope-2b","user_id":"user-scope-2b","position_id":"pos-scope-2b"}`, im2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/domains", `{"id":"domain-scope-2","name":"Org 2","dsm_user_id":"dsm-org-2"}`, admin2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/resources", `{"id":"skill-scope-2","name":"Org 2 Skill","resource_type":"skill","owner_person_id":"person-scope-2a","owner_user_id":"user-scope-2a","owner_position_id":"pos-scope-2a","department_id":"dep-2"}`, admin2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"register_data","payload":{"id":"data-scope-2","title":"Org 2 Data","source_type":"report","owner_person_id":"person-scope-2a","owner_user_id":"user-scope-2a","basis":"tenant isolation"}}`, admin2), http.StatusCreated)
	publication := doRequest(handler, http.MethodPost, "/api/resource-publications", `{"resource_id":"skill-scope-2","target_level":"department_public","reason":"tenant isolation"}`, admin2)
	mustStatus(t, publication, http.StatusCreated)
	var publicationBody ResourcePublication
	if err := json.Unmarshal(publication.Body.Bytes(), &publicationBody); err != nil {
		t.Fatalf("decode publication: %v", err)
	}

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments", `{"person_id":"person-invalid","user_id":"user-invalid","position_id":"pos-scope-2a","tenant_id":"org-1"}`, im1), http.StatusNotFound)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments/"+itoa(assignmentBody.ID)+"/end", "", im1), http.StatusNotFound)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/org/commands", `{"action":"end_person_position","payload":{"id":`+itoa(assignmentBody.ID)+`}}`, im1), http.StatusNotFound)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-manager-edges", `{"person_id":"person-scope-2a","manager_person_id":"person-scope-2b","domain_id":"domain-scope-2"}`, dsm1), http.StatusNotFound)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/position-standard-resources", `{"position_id":"pos-scope-2a","resource_type":"data","resource_id":"data-scope-2","action":"fetch","owner_user_id":"user-scope-2a"}`, dsm1), http.StatusNotFound)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/delegations", `{"from_person_id":"person-scope-2a","to_person_id":"person-scope-2b","resource_type":"data","resource_id":"data-scope-2","action":"fetch","owner_user_id":"user-scope-2a","basis":"cross tenant"}`, dsm1), http.StatusNotFound)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/resource-publications/"+itoa(publicationBody.ID)+"/approve", "", dsm1), http.StatusNotFound)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"approve_resource_publication","payload":{"id":`+itoa(publicationBody.ID)+`}}`, admin1), http.StatusNotFound)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"set_data_status","payload":{"id":"data-scope-2","status":"frozen"}}`, dsm1), http.StatusNotFound)
	invalidResourceOwner := doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"create_resource","payload":{"id":"invalid-owner-resource","name":"Invalid","resource_type":"skill","owner_person_id":"person-scope-1","owner_user_id":"user-scope-1","owner_position_id":"pos-scope-2a","department_id":"dep-2"}}`, admin1)
	mustStatus(t, invalidResourceOwner, http.StatusBadRequest)
	if !strings.Contains(invalidResourceOwner.Body.String(), "owner_context_invalid") {
		t.Fatalf("unexpected invalid resource owner body: %s", invalidResourceOwner.Body.String())
	}
	invalidDataOwner := doRequest(handler, http.MethodPost, "/api/permissions/commands", `{"action":"register_data","payload":{"id":"invalid-owner-data","title":"Invalid","source_type":"report","owner_person_id":"person-scope-2a","owner_user_id":"user-scope-2a","basis":"invalid owner"}}`, admin1)
	mustStatus(t, invalidDataOwner, http.StatusBadRequest)
	if !strings.Contains(invalidDataOwner.Body.String(), "owner_context_invalid") {
		t.Fatalf("unexpected invalid data owner body: %s", invalidDataOwner.Body.String())
	}

	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-manager-edges", `{"person_id":"person-scope-2a","manager_person_id":"person-scope-2b","domain_id":"domain-scope-2"}`, dsm2), http.StatusCreated)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/resource-publications/"+itoa(publicationBody.ID)+"/approve", "", dsm2), http.StatusOK)
	mustStatus(t, doRequest(handler, http.MethodPost, "/api/person-position-assignments/"+itoa(assignmentBody.ID)+"/end", "", im2), http.StatusOK)
}

func newTestHandler(t *testing.T) (*Handler, *auth.JWTManager, *sql.DB) {
	t.Helper()
	chdirModuleRoot(t)
	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err := audit.EnsureSchema(db); err != nil {
		if strings.Contains(err.Error(), "go-sqlite3 requires cgo") {
			t.Skipf("sqlite tests require cgo: %v", err)
		}
		t.Fatalf("ensure schema: %v", err)
	}
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	writer := audit.NewWriter(db)
	return NewHandler(NewStore(db), jwt, writer), jwt, db
}

func doRequest(handler http.Handler, method, path, body, bearer string) *httptest.ResponseRecorder {
	var reader *bytes.Reader
	if body == "" {
		reader = bytes.NewReader(nil)
	} else {
		reader = bytes.NewReader([]byte(body))
	}
	req := httptest.NewRequest(method, path, reader)
	req.Header.Set("Authorization", "Bearer "+bearer)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

func token(t *testing.T, jwt *auth.JWTManager, userID string, roles []string) string {
	t.Helper()
	return tokenForOrg(t, jwt, userID, "org-1", roles)
}

func tokenForOrg(t *testing.T, jwt *auth.JWTManager, userID, orgID string, roles []string) string {
	t.Helper()
	token, err := jwt.Issue(userID, orgID, roles)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	return token
}

func hasPosition(items []Position, id string) bool {
	for _, item := range items {
		if item.ID == id {
			return true
		}
	}
	return false
}

func hasAssignment(items []Assignment, personID string) bool {
	for _, item := range items {
		if item.PersonID == personID {
			return true
		}
	}
	return false
}

func hasDomain(items []Domain, id string) bool {
	for _, item := range items {
		if item.ID == id {
			return true
		}
	}
	return false
}

func hasResource(items []Resource, id string) bool {
	for _, item := range items {
		if item.ID == id {
			return true
		}
	}
	return false
}

func hasDataRecord(items []DataRecord, id string) bool {
	for _, item := range items {
		if item.ID == id {
			return true
		}
	}
	return false
}

func mustStatus(t *testing.T, rec *httptest.ResponseRecorder, status int) {
	t.Helper()
	if rec.Code != status {
		t.Fatalf("status = %d, want %d, body = %s", rec.Code, status, rec.Body.String())
	}
}

func itoa(id int64) string {
	return strconv.FormatInt(id, 10)
}

func chdirModuleRoot(t *testing.T) {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatalf("get working directory: %v", err)
	}
	for dir := wd; ; dir = filepath.Dir(dir) {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			if err := os.Chdir(dir); err != nil {
				t.Fatalf("change to module root: %v", err)
			}
			t.Cleanup(func() { _ = os.Chdir(wd) })
			return
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatalf("module root not found from %s", wd)
		}
	}
}
