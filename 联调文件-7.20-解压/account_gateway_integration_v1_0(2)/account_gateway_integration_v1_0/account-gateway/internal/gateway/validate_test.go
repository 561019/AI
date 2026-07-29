package gateway

import (
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
	"hanhe.com/account-gateway/internal/organization"
	"hanhe.com/account-gateway/internal/policy"

	_ "github.com/mattn/go-sqlite3"
)

func TestValidateRejectsDigitalEmployeeDataAccess(t *testing.T) {
	chdirModuleRoot(t)

	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewValidateHandler(nil, enforcer, nil, jwt)
	token, err := jwt.IssueDigital("agent-1", "org-1", []string{"role_data_reader"}, "owner-1")
	if err != nil {
		t.Fatalf("issue digital token: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/auth/validate", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-User-ID", "agent-1")
	req.Header.Set("X-Resource-Type", "data")
	req.Header.Set("X-Resource-Owner-ID", "owner-1")
	req.Header.Set("X-Action", "read")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("validate status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var resp validateResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode validate response: %v", err)
	}
	if resp.Allow || resp.Reason != "digital_employee_no_data_access" {
		t.Fatalf("unexpected validate response: %+v", resp)
	}
}

func TestValidateDigitalEmployeeExecutionModes(t *testing.T) {
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
	if _, err := db.Exec(`
		INSERT INTO digital_employees (name, parent_user_id, roles, created_at, status, token_version, execution_mode, tenant_id)
		VALUES
			('agent-confirm', 'owner-1', '["tool_runner"]', '2026-07-07T00:00:00Z', 'active', 1, 'require_confirmation', 'org-1'),
			('agent-scope', 'owner-1', '["tool_runner"]', '2026-07-07T00:00:00Z', 'active', 1, 'scope_reject', 'org-1')
	`); err != nil {
		t.Fatalf("seed digital employees: %v", err)
	}

	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewValidateHandler(db, enforcer, audit.NewWriter(db), jwt)

	needsConfirmation := doDigitalValidate(t, handler, jwt, "agent-confirm", "owner-1", map[string]string{
		"X-Resource-Type":     "tool",
		"X-Resource-Owner-ID": "owner-1",
		"X-Action":            "use",
	})
	if needsConfirmation.Allow || needsConfirmation.Reason != "digital_employee_confirmation_required" {
		t.Fatalf("unexpected confirmation-required response: %+v", needsConfirmation)
	}

	confirmed := doDigitalValidate(t, handler, jwt, "agent-confirm", "owner-1", map[string]string{
		"X-Resource-Type":        "tool",
		"X-Resource-Owner-ID":    "owner-1",
		"X-Action":               "use",
		"X-Digital-Confirmed-By": "owner-1",
	})
	if !confirmed.Allow || confirmed.PolicyID != "digital_employee_parent_tool" {
		t.Fatalf("unexpected confirmed response: %+v", confirmed)
	}

	scopeRejected := doDigitalValidate(t, handler, jwt, "agent-scope", "owner-1", map[string]string{
		"X-Resource-Type":     "tool",
		"X-Resource-Owner-ID": "other-owner",
		"X-Action":            "use",
	})
	if scopeRejected.Allow || scopeRejected.Reason != "digital_employee_scope_rejected" {
		t.Fatalf("unexpected scope rejected response: %+v", scopeRejected)
	}

	scopeAllowed := doDigitalValidate(t, handler, jwt, "agent-scope", "owner-1", map[string]string{
		"X-Resource-Type":     "tool",
		"X-Resource-Owner-ID": "owner-1",
		"X-Action":            "use",
	})
	if !scopeAllowed.Allow || scopeAllowed.PolicyID != "digital_employee_parent_tool" {
		t.Fatalf("unexpected scope allowed response: %+v", scopeAllowed)
	}
}

func TestValidateRejectsCrossTenantDigitalEmployeeToken(t *testing.T) {
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
	if _, err := db.Exec(`
		INSERT INTO digital_employees (name, parent_user_id, roles, created_at, status, token_version, execution_mode, tenant_id)
		VALUES ('agent-shared-name', 'owner-a', '["tool_runner"]', '2026-07-07T00:00:00Z', 'active', 1, 'auto', 'org-a')
	`); err != nil {
		t.Fatalf("seed digital employee: %v", err)
	}

	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewValidateHandler(db, enforcer, audit.NewWriter(db), jwt)
	token, err := jwt.IssueDigitalWithVersion("agent-shared-name", "org-b", []string{"tool_runner"}, "owner-a", 1)
	if err != nil {
		t.Fatalf("issue digital token: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/auth/validate", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-User-ID", "agent-shared-name")
	req.Header.Set("X-Resource-Type", "tool")
	req.Header.Set("X-Resource-Owner-ID", "owner-a")
	req.Header.Set("X-Action", "use")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("validate status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var resp validateResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode validate response: %v", err)
	}
	if resp.Allow || resp.Reason != "digital_employee_token_revoked" {
		t.Fatalf("unexpected cross-tenant response: %+v", resp)
	}
}

func TestValidateRejectsExpiredDigitalEmployee(t *testing.T) {
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
	expiredAt := time.Now().UTC().Add(-time.Minute).Format(time.RFC3339)
	if _, err := db.Exec(`
		INSERT INTO digital_employees (name, parent_user_id, roles, created_at, status, token_version, execution_mode, tenant_id, expires_at)
		VALUES (?, 'owner-expired', '["tool_runner"]', '2026-07-10T00:00:00Z', 'active', 1, 'auto', 'org-1', ?)
	`, "agent-expired", expiredAt); err != nil {
		t.Fatalf("seed expired digital employee: %v", err)
	}

	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewValidateHandler(db, enforcer, audit.NewWriter(db), jwt)
	resp := doDigitalValidate(t, handler, jwt, "agent-expired", "owner-expired", map[string]string{
		"X-Resource-Type":     "tool",
		"X-Resource-Owner-ID": "owner-expired",
		"X-Action":            "use",
	})
	if resp.Allow || resp.Reason != "digital_employee_expired" {
		t.Fatalf("unexpected expired response: %+v", resp)
	}
}

func TestValidateAllowsPositionStandardResourceAndDeniesAfterAssignmentEnded(t *testing.T) {
	handler, store, jwt := newOrganizationValidateHandler(t)
	_, err := store.CreatePosition(organization.Position{ID: "pos-a", Title: "Analyst", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"})
	if err != nil {
		t.Fatalf("create position: %v", err)
	}
	assignment, err := store.CreateAssignment(organization.Assignment{PersonID: "person-a", UserID: "user-a", PositionID: "pos-a", TenantID: "org-1", AssignedBy: "im"})
	if err != nil {
		t.Fatalf("create assignment: %v", err)
	}
	resource, err := store.CreateStandardResource(organization.StandardResource{PositionID: "pos-a", ResourceType: "data", ResourceID: "data-1", Action: "fetch", OwnerUserID: "owner-1", CreatedBy: "dsm"})
	if err != nil {
		t.Fatalf("create standard resource: %v", err)
	}

	allowed := doValidate(t, handler, jwt, "user-a", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-1",
		"X-Resource-Owner-ID": "owner-1",
		"X-Action":            "fetch",
		"X-Person-ID":         "person-a",
		"X-Position-ID":       "pos-a",
		"X-Tenant-ID":         "org-1",
	})
	if !allowed.Allow || allowed.PolicyID != "position_standard:"+strconv.FormatInt(resource.ID, 10) {
		t.Fatalf("unexpected allowed response: %+v", allowed)
	}

	if _, err := store.EndAssignment(assignment.ID, "im"); err != nil {
		t.Fatalf("end assignment: %v", err)
	}
	denied := doValidate(t, handler, jwt, "user-a", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-1",
		"X-Resource-Owner-ID": "owner-1",
		"X-Action":            "fetch",
		"X-Person-ID":         "person-a",
		"X-Position-ID":       "pos-a",
		"X-Tenant-ID":         "org-1",
	})
	if denied.Allow || denied.Reason != "person_context_invalid" {
		t.Fatalf("unexpected denied response: %+v", denied)
	}
}

func TestValidateAllowsDelegationAndRejectsWrongContext(t *testing.T) {
	handler, store, jwt := newOrganizationValidateHandler(t)
	if _, err := store.CreatePosition(organization.Position{ID: "pos-a", Title: "A", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"}); err != nil {
		t.Fatalf("create pos-a: %v", err)
	}
	if _, err := store.CreatePosition(organization.Position{ID: "pos-b", Title: "B", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"}); err != nil {
		t.Fatalf("create pos-b: %v", err)
	}
	if _, err := store.CreateAssignment(organization.Assignment{PersonID: "person-a", UserID: "user-a", PositionID: "pos-a", TenantID: "org-1", AssignedBy: "im"}); err != nil {
		t.Fatalf("assign a: %v", err)
	}
	if _, err := store.CreateAssignment(organization.Assignment{PersonID: "person-b", UserID: "user-b", PositionID: "pos-b", TenantID: "org-1", AssignedBy: "im"}); err != nil {
		t.Fatalf("assign b: %v", err)
	}
	delegation, err := store.CreateDelegation(organization.Delegation{FromPersonID: "person-a", ToPersonID: "person-b", ResourceType: "data", ResourceID: "data-2", Action: "fetch", OwnerUserID: "owner-1", Basis: "handoff", CreatedBy: "dsm"})
	if err != nil {
		t.Fatalf("create delegation: %v", err)
	}

	allowed := doValidate(t, handler, jwt, "user-b", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-2",
		"X-Resource-Owner-ID": "owner-1",
		"X-Action":            "fetch",
		"X-Person-ID":         "person-b",
		"X-Delegation-ID":     strconv.FormatInt(delegation.ID, 10),
	})
	if !allowed.Allow || allowed.PolicyID != "delegation:"+strconv.FormatInt(delegation.ID, 10) {
		t.Fatalf("unexpected delegation response: %+v", allowed)
	}

	wrongUser := doValidate(t, handler, jwt, "user-a", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-2",
		"X-Resource-Owner-ID": "owner-1",
		"X-Action":            "fetch",
		"X-Person-ID":         "person-b",
		"X-Delegation-ID":     strconv.FormatInt(delegation.ID, 10),
	})
	if wrongUser.Allow || wrongUser.Reason != "person_context_invalid" {
		t.Fatalf("unexpected wrong user response: %+v", wrongUser)
	}
}

func TestValidateResourceDirectoryScopes(t *testing.T) {
	handler, store, jwt := newOrganizationValidateHandler(t)
	for _, position := range []organization.Position{
		{ID: "pos-a", Title: "A", DepartmentID: "dep-a", TenantID: "org-1", CreatedBy: "im"},
		{ID: "pos-b", Title: "B", DepartmentID: "dep-a", TenantID: "org-1", CreatedBy: "im"},
		{ID: "pos-c", Title: "C", DepartmentID: "dep-b", TenantID: "org-1", CreatedBy: "im"},
	} {
		if _, err := store.CreatePosition(position); err != nil {
			t.Fatalf("create position %s: %v", position.ID, err)
		}
	}
	for _, assignment := range []organization.Assignment{
		{PersonID: "person-a", UserID: "user-a", PositionID: "pos-a", TenantID: "org-1", AssignedBy: "im"},
		{PersonID: "person-b", UserID: "user-b", PositionID: "pos-b", TenantID: "org-1", AssignedBy: "im"},
		{PersonID: "person-c", UserID: "user-c", PositionID: "pos-c", TenantID: "org-1", AssignedBy: "im"},
	} {
		if _, err := store.CreateAssignment(assignment); err != nil {
			t.Fatalf("create assignment %s: %v", assignment.PersonID, err)
		}
	}
	if _, err := store.CreateResource(organization.Resource{
		ID: "skill-a", Name: "Skill A", ResourceType: "skill", OwnerPersonID: "person-a", OwnerUserID: "user-a", OwnerPositionID: "pos-a", DepartmentID: "dep-a", TenantID: "org-1", CreatedBy: "user-a",
	}); err != nil {
		t.Fatalf("create personal resource: %v", err)
	}

	ownerAllowed := doValidate(t, handler, jwt, "user-a", map[string]string{
		"X-Resource-Type":     "skill",
		"X-Resource-ID":       "skill-a",
		"X-Resource-Owner-ID": "user-a",
		"X-Action":            "use",
		"X-Person-ID":         "person-a",
		"X-Position-ID":       "pos-a",
	})
	if !ownerAllowed.Allow || ownerAllowed.PolicyID != "resource_scope:skill-a:personal_position" {
		t.Fatalf("unexpected personal owner response: %+v", ownerAllowed)
	}
	sameDepartmentDenied := doValidate(t, handler, jwt, "user-b", map[string]string{
		"X-Resource-Type":     "skill",
		"X-Resource-ID":       "skill-a",
		"X-Resource-Owner-ID": "user-a",
		"X-Action":            "use",
		"X-Person-ID":         "person-b",
		"X-Position-ID":       "pos-b",
	})
	if sameDepartmentDenied.Allow {
		t.Fatalf("personal resource should not allow same department: %+v", sameDepartmentDenied)
	}

	publication, err := store.CreateResourcePublication(organization.ResourcePublication{ResourceID: "skill-a", TargetLevel: "department_public", Reason: "share"}, "user-a", false)
	if err != nil {
		t.Fatalf("create publication: %v", err)
	}
	if _, err := store.ApproveResourcePublication(publication.ID, "dsm"); err != nil {
		t.Fatalf("approve publication: %v", err)
	}
	sameDepartmentAllowed := doValidate(t, handler, jwt, "user-b", map[string]string{
		"X-Resource-Type":     "skill",
		"X-Resource-ID":       "skill-a",
		"X-Resource-Owner-ID": "user-a",
		"X-Action":            "use",
		"X-Person-ID":         "person-b",
		"X-Position-ID":       "pos-b",
	})
	if !sameDepartmentAllowed.Allow || sameDepartmentAllowed.PolicyID != "resource_scope:skill-a:department_public" {
		t.Fatalf("unexpected department response: %+v", sameDepartmentAllowed)
	}
	otherDepartmentDenied := doValidate(t, handler, jwt, "user-c", map[string]string{
		"X-Resource-Type":     "skill",
		"X-Resource-ID":       "skill-a",
		"X-Resource-Owner-ID": "user-a",
		"X-Action":            "use",
		"X-Person-ID":         "person-c",
		"X-Position-ID":       "pos-c",
	})
	if otherDepartmentDenied.Allow {
		t.Fatalf("department resource should not allow other department: %+v", otherDepartmentDenied)
	}

	if _, err := store.CreateResource(organization.Resource{
		ID: "knowledge-a", Name: "Knowledge A", ResourceType: "knowledge", OwnerPersonID: "person-a", OwnerUserID: "user-a", OwnerPositionID: "pos-a", DepartmentID: "dep-a", TenantID: "org-1", CreatedBy: "user-a",
	}); err != nil {
		t.Fatalf("create company resource: %v", err)
	}
	companyPublication, err := store.CreateResourcePublication(organization.ResourcePublication{ResourceID: "knowledge-a", TargetLevel: "company_public", Reason: "company share"}, "user-a", false)
	if err != nil {
		t.Fatalf("create company publication: %v", err)
	}
	if _, err := store.ApproveResourcePublication(companyPublication.ID, "dsm"); err != nil {
		t.Fatalf("approve company publication: %v", err)
	}
	companyAllowed := doValidate(t, handler, jwt, "user-c", map[string]string{
		"X-Resource-Type":     "knowledge",
		"X-Resource-ID":       "knowledge-a",
		"X-Resource-Owner-ID": "user-a",
		"X-Action":            "use",
		"X-Person-ID":         "person-c",
		"X-Position-ID":       "pos-c",
	})
	if !companyAllowed.Allow || companyAllowed.PolicyID != "resource_scope:knowledge-a:company_public" {
		t.Fatalf("unexpected company response: %+v", companyAllowed)
	}
}

func TestValidateAllowsManagerScopeDataFetch(t *testing.T) {
	handler, store, jwt := newOrganizationValidateHandler(t)
	for _, position := range []organization.Position{
		{ID: "pos-manager", Title: "Manager", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"},
		{ID: "pos-lead", Title: "Lead", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"},
		{ID: "pos-staff", Title: "Staff", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"},
		{ID: "pos-peer", Title: "Peer", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"},
	} {
		if _, err := store.CreatePosition(position); err != nil {
			t.Fatalf("create position %s: %v", position.ID, err)
		}
	}
	for _, assignment := range []organization.Assignment{
		{PersonID: "person-manager", UserID: "user-manager", PositionID: "pos-manager", TenantID: "org-1", AssignedBy: "im"},
		{PersonID: "person-lead", UserID: "user-lead", PositionID: "pos-lead", TenantID: "org-1", AssignedBy: "im"},
		{PersonID: "person-staff", UserID: "user-staff", PositionID: "pos-staff", TenantID: "org-1", AssignedBy: "im"},
		{PersonID: "person-peer", UserID: "user-peer", PositionID: "pos-peer", TenantID: "org-1", AssignedBy: "im"},
	} {
		if _, err := store.CreateAssignment(assignment); err != nil {
			t.Fatalf("create assignment %s: %v", assignment.PersonID, err)
		}
	}
	if _, err := store.CreateDomain(organization.Domain{ID: "domain-a", Name: "Domain A", TenantID: "org-1", DSMUserID: "dsm", CreatedBy: "admin"}); err != nil {
		t.Fatalf("create domain: %v", err)
	}
	for _, edge := range []organization.ManagerEdge{
		{PersonID: "person-lead", ManagerPersonID: "person-manager", DomainID: "domain-a", CreatedBy: "dsm"},
		{PersonID: "person-staff", ManagerPersonID: "person-lead", DomainID: "domain-a", CreatedBy: "dsm"},
	} {
		if _, err := store.UpsertManagerEdge(edge); err != nil {
			t.Fatalf("create manager edge %s: %v", edge.PersonID, err)
		}
	}
	subordinates, err := store.ListSubordinates("person-manager", "domain-a")
	if err != nil {
		t.Fatalf("list subordinates: %v", err)
	}
	if len(subordinates) != 2 || subordinates[0].PersonID != "person-lead" || subordinates[1].PersonID != "person-staff" {
		t.Fatalf("unexpected subordinates: %+v", subordinates)
	}

	allowed := doValidate(t, handler, jwt, "user-manager", map[string]string{
		"X-Resource-Type":            "data",
		"X-Resource-ID":              "data-staff",
		"X-Resource-Owner-ID":        "owner-1",
		"X-Resource-Owner-Person-ID": "person-staff",
		"X-Action":                   "fetch",
		"X-Person-ID":                "person-manager",
		"X-Position-ID":              "pos-manager",
		"X-Domain-ID":                "domain-a",
		"X-Tenant-ID":                "org-1",
	})
	if !allowed.Allow || allowed.PolicyID != "manager_scope:domain-a:person-manager:person-staff" {
		t.Fatalf("unexpected manager scope response: %+v", allowed)
	}

	peerDenied := doValidate(t, handler, jwt, "user-peer", map[string]string{
		"X-Resource-Type":            "data",
		"X-Resource-ID":              "data-staff",
		"X-Resource-Owner-ID":        "owner-1",
		"X-Resource-Owner-Person-ID": "person-staff",
		"X-Action":                   "fetch",
		"X-Person-ID":                "person-peer",
		"X-Position-ID":              "pos-peer",
		"X-Domain-ID":                "domain-a",
		"X-Tenant-ID":                "org-1",
	})
	if peerDenied.Allow {
		t.Fatalf("peer should not have manager scope access: %+v", peerDenied)
	}
}

func TestValidateDataRecordConstraintsPrecedePersonAccess(t *testing.T) {
	handler, store, jwt := newOrganizationValidateHandler(t)
	if _, err := store.CreatePosition(organization.Position{ID: "pos-a", Title: "A", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"}); err != nil {
		t.Fatalf("create position: %v", err)
	}
	if _, err := store.CreateAssignment(organization.Assignment{PersonID: "person-a", UserID: "user-a", PositionID: "pos-a", TenantID: "org-1", AssignedBy: "im"}); err != nil {
		t.Fatalf("create assignment: %v", err)
	}
	if _, err := store.CreateStandardResource(organization.StandardResource{PositionID: "pos-a", ResourceType: "data", ResourceID: "data-locked", Action: "fetch", OwnerUserID: "owner-1", CreatedBy: "dsm"}); err != nil {
		t.Fatalf("create standard fetch: %v", err)
	}
	if _, err := store.CreateStandardResource(organization.StandardResource{PositionID: "pos-a", ResourceType: "data", ResourceID: "data-locked", Action: "delete", OwnerUserID: "owner-1", CreatedBy: "dsm"}); err != nil {
		t.Fatalf("create standard delete: %v", err)
	}
	if _, err := store.CreateDataRecord(organization.DataRecord{
		ID: "data-locked", Title: "Locked Data", SourceType: "report", OwnerPersonID: "person-a", OwnerUserID: "user-a", TenantID: "org-1", AllowedActions: []string{"fetch"}, Basis: "v1.8.5", CreatedBy: "user-a",
	}); err != nil {
		t.Fatalf("create data record: %v", err)
	}

	fetchAllowed := doValidate(t, handler, jwt, "user-a", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-locked",
		"X-Resource-Owner-ID": "owner-1",
		"X-Action":            "fetch",
		"X-Person-ID":         "person-a",
		"X-Position-ID":       "pos-a",
		"X-Tenant-ID":         "org-1",
	})
	if !fetchAllowed.Allow || fetchAllowed.PolicyID != "data_owner:data-locked:fetch" {
		t.Fatalf("unexpected fetch response: %+v", fetchAllowed)
	}

	deleteDenied := doValidate(t, handler, jwt, "user-a", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-locked",
		"X-Resource-Owner-ID": "owner-1",
		"X-Action":            "delete",
		"X-Person-ID":         "person-a",
		"X-Position-ID":       "pos-a",
		"X-Tenant-ID":         "org-1",
	})
	if deleteDenied.Allow || deleteDenied.Reason != "data_action_forbidden" {
		t.Fatalf("unexpected delete response: %+v", deleteDenied)
	}

	if _, err := store.SetDataRecordStatus("data-locked", "frozen", "dsm"); err != nil {
		t.Fatalf("freeze data record: %v", err)
	}
	frozenDenied := doValidate(t, handler, jwt, "user-a", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-locked",
		"X-Resource-Owner-ID": "owner-1",
		"X-Action":            "fetch",
		"X-Person-ID":         "person-a",
		"X-Position-ID":       "pos-a",
		"X-Tenant-ID":         "org-1",
	})
	if frozenDenied.Allow || frozenDenied.Reason != "data_record_inactive" {
		t.Fatalf("unexpected frozen response: %+v", frozenDenied)
	}
}

func TestValidateUsesRegisteredDataActionCatalog(t *testing.T) {
	handler, store, jwt := newOrganizationValidateHandler(t)
	if _, err := store.RegisterDataAction(organization.DataAction{Action: "archive_review", Description: "归档复核", RiskLevel: "high", CreatedBy: "dsm"}); err != nil {
		t.Fatalf("register data action: %v", err)
	}
	if _, err := store.CreatePosition(organization.Position{ID: "pos-a", Title: "A", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"}); err != nil {
		t.Fatalf("create position: %v", err)
	}
	if _, err := store.CreateAssignment(organization.Assignment{PersonID: "person-a", UserID: "user-a", PositionID: "pos-a", TenantID: "org-1", AssignedBy: "im"}); err != nil {
		t.Fatalf("create assignment: %v", err)
	}
	if _, err := store.CreateStandardResource(organization.StandardResource{PositionID: "pos-a", ResourceType: "data", ResourceID: "data-custom-action", Action: "archive_review", OwnerUserID: "owner-1", CreatedBy: "dsm"}); err != nil {
		t.Fatalf("create standard custom action: %v", err)
	}
	if _, err := store.CreateDataRecord(organization.DataRecord{
		ID: "data-custom-action", Title: "Custom Action Data", SourceType: "report", OwnerPersonID: "person-a", OwnerUserID: "user-a", TenantID: "org-1", AllowedActions: []string{"archive_review"}, Basis: "v1.8.5", CreatedBy: "user-a",
	}); err != nil {
		t.Fatalf("create data record: %v", err)
	}

	allowed := doValidate(t, handler, jwt, "user-a", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-custom-action",
		"X-Resource-Owner-ID": "owner-1",
		"X-Action":            "archive_review",
		"X-Person-ID":         "person-a",
		"X-Position-ID":       "pos-a",
		"X-Tenant-ID":         "org-1",
	})
	if !allowed.Allow || !strings.HasPrefix(allowed.PolicyID, "position_standard:") {
		t.Fatalf("custom action should be allowed: %+v", allowed)
	}

	req := httptest.NewRequest(http.MethodPost, "/auth/validate", nil)
	token, err := jwt.Issue("user-a", "org-1", []string{"staff"})
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-User-ID", "user-a")
	req.Header.Set("X-Resource-Type", "data")
	req.Header.Set("X-Resource-ID", "data-custom-action")
	req.Header.Set("X-Resource-Owner-ID", "owner-1")
	req.Header.Set("X-Action", "not_registered")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("unregistered data action status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var denied validateResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &denied); err != nil {
		t.Fatalf("decode denied: %v", err)
	}
	if denied.Reason != "invalid_action" {
		t.Fatalf("unexpected denied response: %+v", denied)
	}
}

func TestValidateDataRecordInitialPermissionsFromRegistry(t *testing.T) {
	handler, store, jwt := newOrganizationValidateHandler(t)
	if _, err := store.CreatePosition(organization.Position{ID: "pos-owner", Title: "Owner", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"}); err != nil {
		t.Fatalf("create owner position: %v", err)
	}
	if _, err := store.CreatePosition(organization.Position{ID: "pos-manager", Title: "Manager", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"}); err != nil {
		t.Fatalf("create manager position: %v", err)
	}
	if _, err := store.CreatePosition(organization.Position{ID: "pos-peer", Title: "Peer", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"}); err != nil {
		t.Fatalf("create peer position: %v", err)
	}
	if _, err := store.CreateAssignment(organization.Assignment{PersonID: "person-owner", UserID: "user-owner", PositionID: "pos-owner", TenantID: "org-1", AssignedBy: "im"}); err != nil {
		t.Fatalf("assign owner: %v", err)
	}
	if _, err := store.CreateAssignment(organization.Assignment{PersonID: "person-manager", UserID: "user-manager", PositionID: "pos-manager", TenantID: "org-1", AssignedBy: "im"}); err != nil {
		t.Fatalf("assign manager: %v", err)
	}
	if _, err := store.CreateAssignment(organization.Assignment{PersonID: "person-peer", UserID: "user-peer", PositionID: "pos-peer", TenantID: "org-1", AssignedBy: "im"}); err != nil {
		t.Fatalf("assign peer: %v", err)
	}
	if _, err := store.CreateDomain(organization.Domain{ID: "domain-initial", Name: "Initial", TenantID: "org-1", DSMUserID: "dsm", CreatedBy: "admin"}); err != nil {
		t.Fatalf("create domain: %v", err)
	}
	if _, err := store.UpsertManagerEdge(organization.ManagerEdge{PersonID: "person-owner", ManagerPersonID: "person-manager", DomainID: "domain-initial", CreatedBy: "dsm"}); err != nil {
		t.Fatalf("manager edge: %v", err)
	}
	if _, err := store.CreateDataRecord(organization.DataRecord{
		ID: "data-initial", Title: "Initial Data", SourceType: "conversation", OwnerPersonID: "person-owner", OwnerUserID: "user-owner", TenantID: "org-1", AllowedActions: []string{"fetch", "update", "delete"}, Basis: "v1.8.5 initial permission", CreatedBy: "user-owner",
	}); err != nil {
		t.Fatalf("create data record: %v", err)
	}

	ownerUpdate := doValidate(t, handler, jwt, "user-owner", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-initial",
		"X-Resource-Owner-ID": "owner-placeholder",
		"X-Action":            "update",
		"X-Person-ID":         "person-owner",
		"X-Position-ID":       "pos-owner",
		"X-Tenant-ID":         "org-1",
	})
	if !ownerUpdate.Allow || ownerUpdate.PolicyID != "data_owner:data-initial:update" {
		t.Fatalf("owner update should use registry initial permission: %+v", ownerUpdate)
	}

	ownerDelete := doValidate(t, handler, jwt, "user-owner", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-initial",
		"X-Resource-Owner-ID": "owner-placeholder",
		"X-Action":            "delete",
		"X-Person-ID":         "person-owner",
		"X-Position-ID":       "pos-owner",
		"X-Tenant-ID":         "org-1",
	})
	if ownerDelete.Allow {
		t.Fatalf("owner delete should not be granted by default: %+v", ownerDelete)
	}

	managerFetch := doValidate(t, handler, jwt, "user-manager", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-initial",
		"X-Resource-Owner-ID": "owner-placeholder",
		"X-Action":            "fetch",
		"X-Person-ID":         "person-manager",
		"X-Position-ID":       "pos-manager",
		"X-Domain-ID":         "domain-initial",
		"X-Tenant-ID":         "org-1",
	})
	if !managerFetch.Allow || managerFetch.PolicyID != "manager_scope:domain-initial:person-manager:person-owner" {
		t.Fatalf("manager fetch should infer owner person from data record: %+v", managerFetch)
	}

	peerFetch := doValidate(t, handler, jwt, "user-peer", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-initial",
		"X-Resource-Owner-ID": "owner-placeholder",
		"X-Action":            "fetch",
		"X-Person-ID":         "person-peer",
		"X-Position-ID":       "pos-peer",
		"X-Domain-ID":         "domain-initial",
		"X-Tenant-ID":         "org-1",
	})
	if peerFetch.Allow {
		t.Fatalf("peer fetch should stay denied: %+v", peerFetch)
	}
}

func TestValidateDataRecordInitialParticipants(t *testing.T) {
	handler, store, jwt := newOrganizationValidateHandler(t)
	if _, err := store.CreatePosition(organization.Position{ID: "pos-owner", Title: "Owner", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"}); err != nil {
		t.Fatalf("create owner position: %v", err)
	}
	if _, err := store.CreatePosition(organization.Position{ID: "pos-participant", Title: "Participant", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"}); err != nil {
		t.Fatalf("create participant position: %v", err)
	}
	if _, err := store.CreatePosition(organization.Position{ID: "pos-outsider", Title: "Outsider", DepartmentID: "dep", TenantID: "org-1", CreatedBy: "im"}); err != nil {
		t.Fatalf("create outsider position: %v", err)
	}
	if _, err := store.CreateAssignment(organization.Assignment{PersonID: "person-owner", UserID: "user-owner", PositionID: "pos-owner", TenantID: "org-1", AssignedBy: "im"}); err != nil {
		t.Fatalf("assign owner: %v", err)
	}
	if _, err := store.CreateAssignment(organization.Assignment{PersonID: "person-participant", UserID: "user-participant", PositionID: "pos-participant", TenantID: "org-1", AssignedBy: "im"}); err != nil {
		t.Fatalf("assign participant: %v", err)
	}
	if _, err := store.CreateAssignment(organization.Assignment{PersonID: "person-outsider", UserID: "user-outsider", PositionID: "pos-outsider", TenantID: "org-1", AssignedBy: "im"}); err != nil {
		t.Fatalf("assign outsider: %v", err)
	}
	if _, err := store.CreateDataRecord(organization.DataRecord{
		ID: "data-participant", Title: "Participant Data", SourceType: "report", OwnerPersonID: "person-owner", OwnerUserID: "user-owner", TenantID: "org-1", AllowedActions: []string{"fetch", "update", "delete"}, InitialPersonIDs: []string{"person-participant"}, InitialUserIDs: []string{"user-participant"}, Basis: "v1.8.5 initial participants", CreatedBy: "user-owner",
	}); err != nil {
		t.Fatalf("create data record: %v", err)
	}

	participantFetch := doValidate(t, handler, jwt, "user-participant", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-participant",
		"X-Resource-Owner-ID": "owner-placeholder",
		"X-Action":            "fetch",
		"X-Person-ID":         "person-participant",
		"X-Position-ID":       "pos-participant",
		"X-Tenant-ID":         "org-1",
	})
	if !participantFetch.Allow || participantFetch.PolicyID != "data_initial:data-participant:person-participant:fetch" {
		t.Fatalf("participant fetch should be allowed: %+v", participantFetch)
	}

	participantUpdate := doValidate(t, handler, jwt, "user-participant", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-participant",
		"X-Resource-Owner-ID": "owner-placeholder",
		"X-Action":            "update",
		"X-Person-ID":         "person-participant",
		"X-Position-ID":       "pos-participant",
		"X-Tenant-ID":         "org-1",
	})
	if participantUpdate.Allow {
		t.Fatalf("participant update should not be allowed by initial participant list: %+v", participantUpdate)
	}

	outsiderFetch := doValidate(t, handler, jwt, "user-outsider", map[string]string{
		"X-Resource-Type":     "data",
		"X-Resource-ID":       "data-participant",
		"X-Resource-Owner-ID": "owner-placeholder",
		"X-Action":            "fetch",
		"X-Person-ID":         "person-outsider",
		"X-Position-ID":       "pos-outsider",
		"X-Tenant-ID":         "org-1",
	})
	if outsiderFetch.Allow {
		t.Fatalf("outsider fetch should stay denied: %+v", outsiderFetch)
	}
}

func TestValidateTenantMismatchRejectsNormalAdminButAllowsBreakglass(t *testing.T) {
	chdirModuleRoot(t)

	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewValidateHandler(nil, enforcer, nil, jwt)
	handler.isBreakglassActive = func() (bool, error) { return true, nil }

	adminToken, err := jwt.Issue("admin-user", "org-a", []string{"hanhe_admin"})
	if err != nil {
		t.Fatalf("issue admin token: %v", err)
	}
	adminReq := httptest.NewRequest(http.MethodPost, "/auth/validate", nil)
	adminReq.Header.Set("Authorization", "Bearer "+adminToken)
	adminReq.Header.Set("X-User-ID", "admin-user")
	adminReq.Header.Set("X-Resource-Type", "tool")
	adminReq.Header.Set("X-Resource-Owner-ID", "admin-user")
	adminReq.Header.Set("X-Action", "create")
	adminReq.Header.Set("X-Tenant-ID", "org-b")
	adminRec := httptest.NewRecorder()
	handler.ServeHTTP(adminRec, adminReq)
	if adminRec.Code != http.StatusOK {
		t.Fatalf("admin mismatch status = %d, body = %s", adminRec.Code, adminRec.Body.String())
	}
	var adminResp validateResponse
	if err := json.Unmarshal(adminRec.Body.Bytes(), &adminResp); err != nil {
		t.Fatalf("decode admin response: %v", err)
	}
	if adminResp.Allow || adminResp.Reason != "tenant_mismatch" {
		t.Fatalf("normal admin should not cross tenant: %+v", adminResp)
	}

	breakglassToken, err := jwt.IssueBreakglassWithTTL("breakglass-user", "org-a", []string{"hanhe_admin"}, time.Hour)
	if err != nil {
		t.Fatalf("issue breakglass token: %v", err)
	}
	breakglassReq := httptest.NewRequest(http.MethodPost, "/auth/validate", nil)
	breakglassReq.Header.Set("Authorization", "Bearer "+breakglassToken)
	breakglassReq.Header.Set("X-User-ID", "breakglass-user")
	breakglassReq.Header.Set("X-Resource-Type", "tool")
	breakglassReq.Header.Set("X-Resource-Owner-ID", "other-owner")
	breakglassReq.Header.Set("X-Action", "delete")
	breakglassReq.Header.Set("X-Tenant-ID", "org-b")
	breakglassRec := httptest.NewRecorder()
	handler.ServeHTTP(breakglassRec, breakglassReq)
	if breakglassRec.Code != http.StatusOK {
		t.Fatalf("breakglass mismatch status = %d, body = %s", breakglassRec.Code, breakglassRec.Body.String())
	}
	var breakglassResp validateResponse
	if err := json.Unmarshal(breakglassRec.Body.Bytes(), &breakglassResp); err != nil {
		t.Fatalf("decode breakglass response: %v", err)
	}
	if !breakglassResp.Allow || breakglassResp.PolicyID != "breakglass:*:*:*:allow" {
		t.Fatalf("breakglass should use emergency policy across tenant: %+v", breakglassResp)
	}
}

func TestValidateRejectsInactiveBreakglass(t *testing.T) {
	chdirModuleRoot(t)

	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	handler := NewValidateHandler(nil, enforcer, nil, jwt)
	handler.isBreakglassActive = func() (bool, error) { return false, nil }
	token, err := jwt.IssueBreakglassWithTTL("breakglass-user", "org-1", []string{"hanhe_admin"}, time.Hour)
	if err != nil {
		t.Fatalf("issue breakglass token: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/auth/validate", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-User-ID", "breakglass-user")
	req.Header.Set("X-Resource-Type", "data")
	req.Header.Set("X-Resource-Owner-ID", "owner-1")
	req.Header.Set("X-Action", "read")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("validate status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var resp validateResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode validate response: %v", err)
	}
	if resp.Allow || resp.Reason != "breakglass_inactive" {
		t.Fatalf("unexpected validate response: %+v", resp)
	}
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

func newOrganizationValidateHandler(t *testing.T) (*ValidateHandler, *organization.Store, *auth.JWTManager) {
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
	enforcer, err := policy.NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}
	jwt := auth.NewJWTManager("test-secret", time.Hour)
	store := organization.NewStore(db)
	handler := NewValidateHandler(db, enforcer, audit.NewWriter(db), jwt).WithOrganizationStore(store)
	return handler, store, jwt
}

func doValidate(t *testing.T, handler *ValidateHandler, jwt *auth.JWTManager, userID string, headers map[string]string) validateResponse {
	t.Helper()
	token, err := jwt.Issue(userID, "org-1", []string{"staff"})
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/auth/validate", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-User-ID", userID)
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("validate status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var resp validateResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return resp
}

func doDigitalValidate(t *testing.T, handler *ValidateHandler, jwt *auth.JWTManager, userID string, parentUserID string, headers map[string]string) validateResponse {
	t.Helper()
	token, err := jwt.IssueDigitalWithVersion(userID, "org-1", []string{"tool_runner"}, parentUserID, 1)
	if err != nil {
		t.Fatalf("issue digital token: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/auth/validate", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-User-ID", userID)
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("validate status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var resp validateResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return resp
}
