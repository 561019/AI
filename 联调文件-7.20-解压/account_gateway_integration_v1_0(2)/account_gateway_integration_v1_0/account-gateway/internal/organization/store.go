package organization

import (
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	"hanhe.com/account-gateway/internal/account"
)

var (
	ErrNotFound              = errors.New("not found")
	ErrActiveAssignmentExist = errors.New("active assignment exists")
	ErrInvalidContext        = errors.New("invalid person context")
	ErrInvalidOwnerContext   = errors.New("invalid owner context")
	ErrForbiddenDelegation   = errors.New("forbidden delegation")
)

type Store struct {
	db *sql.DB
}

type Position struct {
	ID           string   `json:"id"`
	Title        string   `json:"title"`
	DepartmentID string   `json:"department_id"`
	TenantID     string   `json:"tenant_id"`
	Tags         []string `json:"tags"`
	CreatedBy    string   `json:"created_by,omitempty"`
	CreatedAt    string   `json:"created_at,omitempty"`
}

type Assignment struct {
	ID         int64  `json:"id"`
	PersonID   string `json:"person_id"`
	UserID     string `json:"user_id"`
	PositionID string `json:"position_id"`
	TenantID   string `json:"tenant_id"`
	Status     string `json:"status"`
	AssignedBy string `json:"assigned_by,omitempty"`
	AssignedAt string `json:"assigned_at,omitempty"`
	EndedBy    string `json:"ended_by,omitempty"`
	EndedAt    string `json:"ended_at,omitempty"`
}

type Domain struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	TenantID  string `json:"tenant_id"`
	DSMUserID string `json:"dsm_user_id"`
	CreatedBy string `json:"created_by,omitempty"`
	CreatedAt string `json:"created_at,omitempty"`
}

type ManagerEdge struct {
	ID              int64  `json:"id"`
	PersonID        string `json:"person_id"`
	ManagerPersonID string `json:"manager_person_id"`
	DomainID        string `json:"domain_id"`
	Status          string `json:"status"`
	CreatedBy       string `json:"created_by,omitempty"`
	CreatedAt       string `json:"created_at,omitempty"`
	UpdatedAt       string `json:"updated_at,omitempty"`
}

type Subordinate struct {
	PersonID        string `json:"person_id"`
	ManagerPersonID string `json:"manager_person_id"`
	DomainID        string `json:"domain_id"`
	Depth           int    `json:"depth"`
}

type StandardResource struct {
	ID           int64  `json:"id"`
	PositionID   string `json:"position_id"`
	ResourceType string `json:"resource_type"`
	ResourceID   string `json:"resource_id"`
	Action       string `json:"action"`
	OwnerUserID  string `json:"owner_user_id"`
	CreatedBy    string `json:"created_by,omitempty"`
	CreatedAt    string `json:"created_at,omitempty"`
}

type Delegation struct {
	ID            int64  `json:"id"`
	FromPersonID  string `json:"from_person_id"`
	ToPersonID    string `json:"to_person_id"`
	ResourceType  string `json:"resource_type"`
	ResourceID    string `json:"resource_id"`
	Action        string `json:"action"`
	OwnerUserID   string `json:"owner_user_id"`
	CanRedelegate bool   `json:"can_redelegate"`
	Basis         string `json:"basis"`
	CreatedBy     string `json:"created_by,omitempty"`
	CreatedAt     string `json:"created_at,omitempty"`
}

type Resource struct {
	ID              string `json:"id"`
	Name            string `json:"name"`
	ResourceType    string `json:"resource_type"`
	Level           string `json:"level"`
	Status          string `json:"status"`
	AssetPool       string `json:"asset_pool,omitempty"`
	LockedBy        string `json:"locked_by,omitempty"`
	LockedAt        string `json:"locked_at,omitempty"`
	OwnerPersonID   string `json:"owner_person_id"`
	OwnerUserID     string `json:"owner_user_id"`
	OwnerPositionID string `json:"owner_position_id"`
	DepartmentID    string `json:"department_id"`
	TenantID        string `json:"tenant_id"`
	CreatedBy       string `json:"created_by,omitempty"`
	CreatedAt       string `json:"created_at,omitempty"`
}

type ResourcePublication struct {
	ID          int64  `json:"id"`
	ResourceID  string `json:"resource_id"`
	TargetLevel string `json:"target_level"`
	Reason      string `json:"reason"`
	Status      string `json:"status"`
	RequestedBy string `json:"requested_by,omitempty"`
	RequestedAt string `json:"requested_at,omitempty"`
	ApprovedBy  string `json:"approved_by,omitempty"`
	ApprovedAt  string `json:"approved_at,omitempty"`
}

type DataRecord struct {
	ID               string   `json:"id"`
	Title            string   `json:"title"`
	SourceType       string   `json:"source_type"`
	OwnerPersonID    string   `json:"owner_person_id"`
	OwnerUserID      string   `json:"owner_user_id"`
	TenantID         string   `json:"tenant_id"`
	BusinessTags     []string `json:"business_tags"`
	StorageRefs      []string `json:"storage_refs"`
	Status           string   `json:"status"`
	AllowedActions   []string `json:"allowed_actions"`
	InitialPersonIDs []string `json:"initial_person_ids"`
	InitialUserIDs   []string `json:"initial_user_ids"`
	AssetPool        string   `json:"asset_pool,omitempty"`
	LockedBy         string   `json:"locked_by,omitempty"`
	LockedAt         string   `json:"locked_at,omitempty"`
	Basis            string   `json:"basis"`
	CreatedBy        string   `json:"created_by,omitempty"`
	CreatedAt        string   `json:"created_at,omitempty"`
	UpdatedBy        string   `json:"updated_by,omitempty"`
	UpdatedAt        string   `json:"updated_at,omitempty"`
}

type DataAction struct {
	Action      string `json:"action"`
	Description string `json:"description"`
	RiskLevel   string `json:"risk_level"`
	Enabled     bool   `json:"enabled"`
	CreatedBy   string `json:"created_by,omitempty"`
	CreatedAt   string `json:"created_at,omitempty"`
}

type DataAccessEntry struct {
	DataID     string `json:"data_id"`
	Source     string `json:"source"`
	PersonID   string `json:"person_id,omitempty"`
	UserID     string `json:"user_id,omitempty"`
	PositionID string `json:"position_id,omitempty"`
	Action     string `json:"action"`
	PolicyID   string `json:"policy_id"`
}

type ResourceFilters struct {
	ResourceType string
	Level        string
	DepartmentID string
	TenantID     string
	Status       string
}

type DataRecordFilters struct {
	OwnerPersonID string
	OwnerUserID   string
	TenantID      string
	Status        string
}

type DelegationFilters struct {
	PersonID     string
	ResourceType string
	ResourceID   string
	Action       string
	OwnerUserID  string
	TenantID     string
}

type ValidateContext struct {
	UserID        string
	TenantID      string
	PersonID      string
	PositionID    string
	DomainID      string
	DelegationID  string
	ResourceType  string
	ResourceID    string
	Action        string
	OwnerUserID   string
	OwnerPersonID string
}

type AccessDecision struct {
	Allow    bool
	PolicyID string
}

func NewStore(db *sql.DB) *Store {
	return &Store{db: db}
}

func (s *Store) CreatePosition(item Position) (Position, error) {
	item.ID = strings.TrimSpace(item.ID)
	item.Title = strings.TrimSpace(item.Title)
	item.DepartmentID = strings.TrimSpace(item.DepartmentID)
	item.TenantID = strings.TrimSpace(item.TenantID)
	item.CreatedBy = strings.TrimSpace(item.CreatedBy)
	if item.ID == "" || item.Title == "" || item.DepartmentID == "" || item.TenantID == "" || item.CreatedBy == "" {
		return Position{}, fmt.Errorf("missing field")
	}
	item.CreatedAt = now()
	tagsJSON, err := encodeTags(item.Tags)
	if err != nil {
		return Position{}, err
	}
	_, err = s.db.Exec(`
		INSERT INTO positions (id, title, department_id, tenant_id, tags, created_by, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)
	`, item.ID, item.Title, item.DepartmentID, item.TenantID, tagsJSON, item.CreatedBy, item.CreatedAt)
	return item, err
}

func (s *Store) ListPositions() ([]Position, error) {
	return s.ListPositionsByTenant("")
}

func (s *Store) ListPositionsByTenant(tenantID string) ([]Position, error) {
	tenantID = strings.TrimSpace(tenantID)
	query := "SELECT id, title, department_id, tenant_id, tags, created_by, created_at FROM positions WHERE 1=1"
	args := make([]interface{}, 0)
	if tenantID != "" {
		query += " AND tenant_id=?"
		args = append(args, tenantID)
	}
	query += " ORDER BY id"
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]Position, 0)
	for rows.Next() {
		var item Position
		var tagsJSON string
		if err := rows.Scan(&item.ID, &item.Title, &item.DepartmentID, &item.TenantID, &tagsJSON, &item.CreatedBy, &item.CreatedAt); err != nil {
			return nil, err
		}
		item.Tags = decodeTags(tagsJSON)
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *Store) CreateAssignment(item Assignment) (Assignment, error) {
	item.PersonID = strings.TrimSpace(item.PersonID)
	item.UserID = strings.TrimSpace(item.UserID)
	item.PositionID = strings.TrimSpace(item.PositionID)
	item.TenantID = strings.TrimSpace(item.TenantID)
	item.AssignedBy = strings.TrimSpace(item.AssignedBy)
	if item.PersonID == "" || item.UserID == "" || item.PositionID == "" || item.TenantID == "" || item.AssignedBy == "" {
		return Assignment{}, fmt.Errorf("missing field")
	}
	positionTenantID, err := s.positionTenant(item.PositionID)
	if err != nil {
		return Assignment{}, err
	}
	if positionTenantID != item.TenantID {
		return Assignment{}, ErrNotFound
	}
	item.Status = "active"
	item.AssignedAt = now()
	result, err := s.db.Exec(`
		INSERT INTO person_position_assignments (person_id, user_id, position_id, tenant_id, status, assigned_by, assigned_at)
		VALUES (?, ?, ?, ?, 'active', ?, ?)
	`, item.PersonID, item.UserID, item.PositionID, item.TenantID, item.AssignedBy, item.AssignedAt)
	if err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "unique") {
			return Assignment{}, ErrActiveAssignmentExist
		}
		return Assignment{}, err
	}
	item.ID, _ = result.LastInsertId()
	return item, nil
}

func (s *Store) EndAssignment(id int64, endedBy string) (Assignment, error) {
	item, err := s.GetAssignment(id)
	if err != nil {
		return Assignment{}, err
	}
	if item.Status != "active" {
		return item, nil
	}
	item.Status = "ended"
	item.EndedBy = strings.TrimSpace(endedBy)
	item.EndedAt = now()
	_, err = s.db.Exec("UPDATE person_position_assignments SET status='ended', ended_by=?, ended_at=? WHERE id=?", item.EndedBy, item.EndedAt, id)
	return item, err
}

func (s *Store) GetAssignment(id int64) (Assignment, error) {
	var item Assignment
	err := s.db.QueryRow(`
		SELECT id, person_id, user_id, position_id, tenant_id, status, assigned_by, assigned_at, COALESCE(ended_by, ''), COALESCE(ended_at, '')
		FROM person_position_assignments
		WHERE id = ?
	`, id).Scan(&item.ID, &item.PersonID, &item.UserID, &item.PositionID, &item.TenantID, &item.Status, &item.AssignedBy, &item.AssignedAt, &item.EndedBy, &item.EndedAt)
	if err == sql.ErrNoRows {
		return Assignment{}, ErrNotFound
	}
	if err != nil {
		return Assignment{}, err
	}
	return item, nil
}

func (s *Store) ListAssignments() ([]Assignment, error) {
	return s.ListAssignmentsByTenant("")
}

func (s *Store) ListAssignmentsByTenant(tenantID string) ([]Assignment, error) {
	tenantID = strings.TrimSpace(tenantID)
	query := `
		SELECT id, person_id, user_id, position_id, tenant_id, status, assigned_by, assigned_at, COALESCE(ended_by, ''), COALESCE(ended_at, '')
		FROM person_position_assignments
		WHERE 1=1
	`
	args := make([]interface{}, 0)
	if tenantID != "" {
		query += " AND tenant_id=?"
		args = append(args, tenantID)
	}
	query += " ORDER BY id"
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]Assignment, 0)
	for rows.Next() {
		var item Assignment
		if err := rows.Scan(&item.ID, &item.PersonID, &item.UserID, &item.PositionID, &item.TenantID, &item.Status, &item.AssignedBy, &item.AssignedAt, &item.EndedBy, &item.EndedAt); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *Store) CreateDomain(item Domain) (Domain, error) {
	item.ID = strings.TrimSpace(item.ID)
	item.Name = strings.TrimSpace(item.Name)
	item.TenantID = strings.TrimSpace(item.TenantID)
	item.DSMUserID = strings.TrimSpace(item.DSMUserID)
	item.CreatedBy = strings.TrimSpace(item.CreatedBy)
	if item.ID == "" || item.Name == "" || item.TenantID == "" || item.DSMUserID == "" || item.CreatedBy == "" {
		return Domain{}, fmt.Errorf("missing field")
	}
	item.CreatedAt = now()
	_, err := s.db.Exec(`
		INSERT INTO domains (id, name, tenant_id, dsm_user_id, created_by, created_at)
		VALUES (?, ?, ?, ?, ?, ?)
	`, item.ID, item.Name, item.TenantID, item.DSMUserID, item.CreatedBy, item.CreatedAt)
	return item, err
}

func (s *Store) ListDomains() ([]Domain, error) {
	return s.ListDomainsByTenant("")
}

func (s *Store) ListDomainsByTenant(tenantID string) ([]Domain, error) {
	tenantID = strings.TrimSpace(tenantID)
	query := "SELECT id, name, tenant_id, dsm_user_id, created_by, created_at FROM domains WHERE 1=1"
	args := make([]interface{}, 0)
	if tenantID != "" {
		query += " AND tenant_id=?"
		args = append(args, tenantID)
	}
	query += " ORDER BY id"
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]Domain, 0)
	for rows.Next() {
		var item Domain
		if err := rows.Scan(&item.ID, &item.Name, &item.TenantID, &item.DSMUserID, &item.CreatedBy, &item.CreatedAt); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *Store) UpsertManagerEdge(item ManagerEdge) (ManagerEdge, error) {
	item.PersonID = strings.TrimSpace(item.PersonID)
	item.ManagerPersonID = strings.TrimSpace(item.ManagerPersonID)
	item.DomainID = strings.TrimSpace(item.DomainID)
	item.CreatedBy = strings.TrimSpace(item.CreatedBy)
	if item.PersonID == "" || item.ManagerPersonID == "" || item.DomainID == "" || item.CreatedBy == "" {
		return ManagerEdge{}, fmt.Errorf("missing field")
	}
	if item.PersonID == item.ManagerPersonID {
		return ManagerEdge{}, fmt.Errorf("self manager")
	}
	if ok, err := s.domainExists(item.DomainID); err != nil {
		return ManagerEdge{}, err
	} else if !ok {
		return ManagerEdge{}, ErrNotFound
	}
	ts := now()
	tx, err := s.db.Begin()
	if err != nil {
		return ManagerEdge{}, err
	}
	defer tx.Rollback()
	if _, err := tx.Exec("UPDATE person_manager_edges SET status='ended', updated_at=? WHERE person_id=? AND status='active'", ts, item.PersonID); err != nil {
		return ManagerEdge{}, err
	}
	result, err := tx.Exec(`
		INSERT INTO person_manager_edges (person_id, manager_person_id, domain_id, status, created_by, created_at, updated_at)
		VALUES (?, ?, ?, 'active', ?, ?, ?)
	`, item.PersonID, item.ManagerPersonID, item.DomainID, item.CreatedBy, ts, ts)
	if err != nil {
		return ManagerEdge{}, err
	}
	if err := tx.Commit(); err != nil {
		return ManagerEdge{}, err
	}
	item.ID, _ = result.LastInsertId()
	item.Status = "active"
	item.CreatedAt = ts
	item.UpdatedAt = ts
	return item, nil
}

func (s *Store) ListManagerEdges() ([]ManagerEdge, error) {
	return s.ListManagerEdgesByTenant("")
}

func (s *Store) ListManagerEdgesByTenant(tenantID string) ([]ManagerEdge, error) {
	tenantID = strings.TrimSpace(tenantID)
	query := `
		SELECT e.id, e.person_id, e.manager_person_id, e.domain_id, e.status, e.created_by, e.created_at, e.updated_at
		FROM person_manager_edges e
		JOIN domains d ON d.id = e.domain_id
		WHERE e.status='active'
	`
	args := make([]interface{}, 0)
	if tenantID != "" {
		query += " AND d.tenant_id=?"
		args = append(args, tenantID)
	}
	query += " ORDER BY e.id"
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]ManagerEdge, 0)
	for rows.Next() {
		var item ManagerEdge
		if err := rows.Scan(&item.ID, &item.PersonID, &item.ManagerPersonID, &item.DomainID, &item.Status, &item.CreatedBy, &item.CreatedAt, &item.UpdatedAt); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *Store) CreateStandardResource(item StandardResource) (StandardResource, error) {
	item.PositionID = strings.TrimSpace(item.PositionID)
	item.ResourceType = strings.TrimSpace(item.ResourceType)
	item.ResourceID = strings.TrimSpace(item.ResourceID)
	item.Action = strings.TrimSpace(item.Action)
	item.OwnerUserID = strings.TrimSpace(item.OwnerUserID)
	item.CreatedBy = strings.TrimSpace(item.CreatedBy)
	if item.PositionID == "" || item.ResourceType == "" || item.ResourceID == "" || item.Action == "" || item.OwnerUserID == "" || item.CreatedBy == "" {
		return StandardResource{}, fmt.Errorf("missing field")
	}
	if ok, err := s.positionExists(item.PositionID); err != nil {
		return StandardResource{}, err
	} else if !ok {
		return StandardResource{}, ErrNotFound
	}
	item.CreatedAt = now()
	result, err := s.db.Exec(`
		INSERT OR IGNORE INTO position_standard_resources (position_id, resource_type, resource_id, action, owner_user_id, created_by, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)
	`, item.PositionID, item.ResourceType, item.ResourceID, item.Action, item.OwnerUserID, item.CreatedBy, item.CreatedAt)
	if err != nil {
		return StandardResource{}, err
	}
	item.ID, _ = result.LastInsertId()
	if item.ID == 0 {
		_ = s.db.QueryRow(`
			SELECT id, created_by, created_at
			FROM position_standard_resources
			WHERE position_id=? AND resource_type=? AND resource_id=? AND action=? AND owner_user_id=?
		`, item.PositionID, item.ResourceType, item.ResourceID, item.Action, item.OwnerUserID).Scan(&item.ID, &item.CreatedBy, &item.CreatedAt)
	}
	return item, nil
}

func (s *Store) ListStandardResources() ([]StandardResource, error) {
	return s.ListStandardResourcesByTenant("")
}

func (s *Store) ListStandardResourcesByTenant(tenantID string) ([]StandardResource, error) {
	tenantID = strings.TrimSpace(tenantID)
	query := `
		SELECT r.id, r.position_id, r.resource_type, r.resource_id, r.action, r.owner_user_id, r.created_by, r.created_at
		FROM position_standard_resources r
		JOIN positions p ON p.id = r.position_id
		WHERE 1=1
	`
	args := make([]interface{}, 0)
	if tenantID != "" {
		query += " AND p.tenant_id=?"
		args = append(args, tenantID)
	}
	query += " ORDER BY r.id"
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]StandardResource, 0)
	for rows.Next() {
		var item StandardResource
		if err := rows.Scan(&item.ID, &item.PositionID, &item.ResourceType, &item.ResourceID, &item.Action, &item.OwnerUserID, &item.CreatedBy, &item.CreatedAt); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *Store) CreateDelegation(item Delegation) (Delegation, error) {
	item.FromPersonID = strings.TrimSpace(item.FromPersonID)
	item.ToPersonID = strings.TrimSpace(item.ToPersonID)
	item.ResourceType = strings.TrimSpace(item.ResourceType)
	item.ResourceID = strings.TrimSpace(item.ResourceID)
	item.Action = strings.TrimSpace(item.Action)
	item.OwnerUserID = strings.TrimSpace(item.OwnerUserID)
	item.Basis = strings.TrimSpace(item.Basis)
	item.CreatedBy = strings.TrimSpace(item.CreatedBy)
	if item.FromPersonID == "" || item.ToPersonID == "" || item.ResourceType == "" || item.ResourceID == "" || item.Action == "" || item.OwnerUserID == "" || item.Basis == "" || item.CreatedBy == "" {
		return Delegation{}, fmt.Errorf("missing field")
	}
	item.CreatedAt = now()
	result, err := s.db.Exec(`
		INSERT INTO delegations (from_person_id, to_person_id, resource_type, resource_id, action, owner_user_id, can_redelegate, basis, created_by, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, item.FromPersonID, item.ToPersonID, item.ResourceType, item.ResourceID, item.Action, item.OwnerUserID, boolInt(item.CanRedelegate), item.Basis, item.CreatedBy, item.CreatedAt)
	if err != nil {
		return Delegation{}, err
	}
	item.ID, _ = result.LastInsertId()
	return item, nil
}

func (s *Store) ListDelegations() ([]Delegation, error) {
	return s.ListDelegationsForSnapshot("", true, DelegationFilters{})
}

func (s *Store) ListDelegationsForSnapshot(claimUserID string, elevated bool, filters DelegationFilters) ([]Delegation, error) {
	filters = normalizeDelegationFilters(filters)
	query := `
		SELECT id, from_person_id, to_person_id, resource_type, resource_id, action, owner_user_id, can_redelegate, basis, created_by, created_at
		FROM delegations
		WHERE 1=1
	`
	args := make([]interface{}, 0)
	if filters.PersonID != "" {
		query += " AND (from_person_id=? OR to_person_id=?)"
		args = append(args, filters.PersonID, filters.PersonID)
	}
	if filters.ResourceType != "" {
		query += " AND resource_type=?"
		args = append(args, filters.ResourceType)
	}
	if filters.ResourceID != "" {
		query += " AND resource_id=?"
		args = append(args, filters.ResourceID)
	}
	if filters.Action != "" {
		query += " AND action=?"
		args = append(args, filters.Action)
	}
	if filters.OwnerUserID != "" {
		query += " AND owner_user_id=?"
		args = append(args, filters.OwnerUserID)
	}
	if filters.TenantID != "" {
		query += ` AND EXISTS (
			SELECT 1 FROM person_position_assignments a
			WHERE a.status='active'
			  AND a.tenant_id=?
			  AND (a.person_id=delegations.from_person_id OR a.person_id=delegations.to_person_id)
		)`
		args = append(args, filters.TenantID)
	}
	if !elevated {
		assignment, err := s.activeAssignmentByUser(claimUserID)
		if err != nil {
			return []Delegation{}, nil
		}
		query += " AND (from_person_id=? OR to_person_id=?)"
		args = append(args, assignment.PersonID, assignment.PersonID)
	}
	query += " ORDER BY id"
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]Delegation, 0)
	for rows.Next() {
		var item Delegation
		var canRedelegate int
		if err := rows.Scan(&item.ID, &item.FromPersonID, &item.ToPersonID, &item.ResourceType, &item.ResourceID, &item.Action, &item.OwnerUserID, &canRedelegate, &item.Basis, &item.CreatedBy, &item.CreatedAt); err != nil {
			return nil, err
		}
		item.CanRedelegate = canRedelegate == 1
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *Store) CreateResource(item Resource) (Resource, error) {
	item = normalizeResource(item)
	if item.ID == "" || item.Name == "" || item.ResourceType == "" || item.OwnerPersonID == "" || item.OwnerUserID == "" || item.OwnerPositionID == "" || item.DepartmentID == "" || item.TenantID == "" || item.CreatedBy == "" {
		return Resource{}, fmt.Errorf("missing field")
	}
	if !validDirectoryResourceType(item.ResourceType) {
		return Resource{}, fmt.Errorf("invalid resource type")
	}
	if item.Level == "" {
		item.Level = "personal_position"
	}
	if item.Level != "personal_position" {
		return Resource{}, fmt.Errorf("invalid resource level")
	}
	if item.Status == "" {
		item.Status = "active"
	}
	ownerContextValid, err := s.resourceOwnerContextValid(item)
	if err != nil {
		return Resource{}, err
	}
	if !ownerContextValid {
		return Resource{}, ErrInvalidOwnerContext
	}
	item.CreatedAt = now()
	_, err = s.db.Exec(`
		INSERT INTO resources (id, name, resource_type, level, status, owner_person_id, owner_user_id, owner_position_id, department_id, tenant_id, created_by, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, item.ID, item.Name, item.ResourceType, item.Level, item.Status, item.OwnerPersonID, item.OwnerUserID, item.OwnerPositionID, item.DepartmentID, item.TenantID, item.CreatedBy, item.CreatedAt)
	return item, err
}

func (s *Store) ListResources(claimUserID string, elevated bool, filters ResourceFilters) ([]Resource, error) {
	filters = normalizeResourceFilters(filters)
	query := `
		SELECT id, name, resource_type, level, status, COALESCE(asset_pool, ''), COALESCE(locked_by, ''), COALESCE(locked_at, ''), owner_person_id, owner_user_id, owner_position_id, department_id, tenant_id, created_by, created_at
		FROM resources
		WHERE 1=1
	`
	args := make([]interface{}, 0)
	if filters.Status != "" {
		query += " AND status=?"
		args = append(args, filters.Status)
	} else {
		query += " AND status='active'"
	}
	if filters.ResourceType != "" {
		query += " AND resource_type=?"
		args = append(args, filters.ResourceType)
	}
	if filters.Level != "" {
		query += " AND level=?"
		args = append(args, filters.Level)
	}
	if filters.DepartmentID != "" {
		query += " AND department_id=?"
		args = append(args, filters.DepartmentID)
	}
	if filters.TenantID != "" {
		query += " AND tenant_id=?"
		args = append(args, filters.TenantID)
	}
	if !elevated {
		assignment, err := s.activeAssignmentByUser(claimUserID)
		if err != nil {
			return []Resource{}, nil
		}
		query += ` AND (
			(owner_person_id=? AND owner_position_id=? AND level='personal_position')
			OR (department_id=? AND level='department_public')
			OR (tenant_id=? AND level='company_public')
		)`
		departmentID, err := s.departmentForPosition(assignment.PositionID)
		if err != nil {
			return nil, err
		}
		args = append(args, assignment.PersonID, assignment.PositionID, departmentID, assignment.TenantID)
	}
	query += " ORDER BY id"
	return s.queryResources(query, args...)
}

func (s *Store) FreezeAssetsForUser(userID, tenantID, actor string) (account.AssetFreezeSummary, error) {
	userID = strings.TrimSpace(userID)
	tenantID = strings.TrimSpace(tenantID)
	actor = strings.TrimSpace(actor)
	if userID == "" || tenantID == "" || actor == "" {
		return account.AssetFreezeSummary{}, fmt.Errorf("missing field")
	}
	tx, err := s.db.Begin()
	if err != nil {
		return account.AssetFreezeSummary{}, err
	}
	defer tx.Rollback()

	resourceResult, err := tx.Exec(`
		UPDATE resources
		SET status='frozen', asset_pool='offboarding', locked_by=?, locked_at=?
		WHERE owner_user_id=? AND tenant_id=? AND status='active'
	`, actor, now(), userID, tenantID)
	if err != nil {
		return account.AssetFreezeSummary{}, err
	}
	ts := now()
	dataResult, err := tx.Exec(`
		UPDATE data_records
		SET status='frozen', asset_pool='offboarding', locked_by=?, locked_at=?, updated_by=?, updated_at=?
		WHERE owner_user_id=? AND tenant_id=? AND status='active'
	`, actor, ts, actor, ts, userID, tenantID)
	if err != nil {
		return account.AssetFreezeSummary{}, err
	}
	digitalResult, err := tx.Exec(`
		UPDATE digital_employees
		SET status='disabled', disabled_at=?
		WHERE parent_user_id=? AND tenant_id=? AND status='active'
	`, now(), userID, tenantID)
	if err != nil {
		return account.AssetFreezeSummary{}, err
	}
	if err := tx.Commit(); err != nil {
		return account.AssetFreezeSummary{}, err
	}
	resources, _ := resourceResult.RowsAffected()
	dataRecords, _ := dataResult.RowsAffected()
	digitalEmployees, _ := digitalResult.RowsAffected()
	return account.AssetFreezeSummary{Resources: int(resources), DataRecords: int(dataRecords), DigitalEmployees: int(digitalEmployees)}, nil
}

func (s *Store) OffboardingAssetsForUser(userID, tenantID string) (account.OffboardingAssets, error) {
	userID = strings.TrimSpace(userID)
	tenantID = strings.TrimSpace(tenantID)
	if userID == "" || tenantID == "" {
		return account.OffboardingAssets{}, fmt.Errorf("missing field")
	}

	result := account.OffboardingAssets{
		UserID:           userID,
		TenantID:         tenantID,
		Resources:        []account.OffboardingResource{},
		DataRecords:      []account.OffboardingDataRecord{},
		DigitalEmployees: []account.OffboardingDigitalEmployee{},
	}

	resourceRows, err := s.db.Query(`
		SELECT id, name, resource_type, status, COALESCE(asset_pool, ''), COALESCE(locked_by, ''), COALESCE(locked_at, '')
		FROM resources
		WHERE owner_user_id=? AND tenant_id=? AND status='frozen'
		ORDER BY id
	`, userID, tenantID)
	if err != nil {
		return account.OffboardingAssets{}, err
	}
	defer resourceRows.Close()
	for resourceRows.Next() {
		var item account.OffboardingResource
		if err := resourceRows.Scan(&item.ID, &item.Name, &item.ResourceType, &item.Status, &item.AssetPool, &item.LockedBy, &item.LockedAt); err != nil {
			return account.OffboardingAssets{}, err
		}
		result.Resources = append(result.Resources, item)
	}
	if err := resourceRows.Err(); err != nil {
		return account.OffboardingAssets{}, err
	}

	dataRows, err := s.db.Query(`
		SELECT id, title, status, COALESCE(asset_pool, ''), COALESCE(locked_by, ''), COALESCE(locked_at, '')
		FROM data_records
		WHERE owner_user_id=? AND tenant_id=? AND status='frozen'
		ORDER BY id
	`, userID, tenantID)
	if err != nil {
		return account.OffboardingAssets{}, err
	}
	defer dataRows.Close()
	for dataRows.Next() {
		var item account.OffboardingDataRecord
		if err := dataRows.Scan(&item.ID, &item.Title, &item.Status, &item.AssetPool, &item.LockedBy, &item.LockedAt); err != nil {
			return account.OffboardingAssets{}, err
		}
		result.DataRecords = append(result.DataRecords, item)
	}
	if err := dataRows.Err(); err != nil {
		return account.OffboardingAssets{}, err
	}

	digitalRows, err := s.db.Query(`
		SELECT name, status, COALESCE(disabled_at, '')
		FROM digital_employees
		WHERE parent_user_id=? AND tenant_id=? AND status!='active'
		ORDER BY name
	`, userID, tenantID)
	if err != nil {
		return account.OffboardingAssets{}, err
	}
	defer digitalRows.Close()
	for digitalRows.Next() {
		var item account.OffboardingDigitalEmployee
		if err := digitalRows.Scan(&item.Name, &item.Status, &item.DisabledAt); err != nil {
			return account.OffboardingAssets{}, err
		}
		result.DigitalEmployees = append(result.DigitalEmployees, item)
	}
	if err := digitalRows.Err(); err != nil {
		return account.OffboardingAssets{}, err
	}

	return result, nil
}

func (s *Store) CreateResourcePublication(item ResourcePublication, requestedBy string, elevated bool) (ResourcePublication, error) {
	item.ResourceID = strings.TrimSpace(item.ResourceID)
	item.TargetLevel = strings.TrimSpace(item.TargetLevel)
	item.Reason = strings.TrimSpace(item.Reason)
	requestedBy = strings.TrimSpace(requestedBy)
	if item.ResourceID == "" || item.TargetLevel == "" || item.Reason == "" || requestedBy == "" {
		return ResourcePublication{}, fmt.Errorf("missing field")
	}
	if !validPublicLevel(item.TargetLevel) {
		return ResourcePublication{}, fmt.Errorf("invalid target level")
	}
	resource, err := s.GetResource(item.ResourceID)
	if err != nil {
		return ResourcePublication{}, err
	}
	if resource.Level != "personal_position" || resource.Status != "active" {
		return ResourcePublication{}, fmt.Errorf("resource_not_personal")
	}
	if !elevated {
		assignment, err := s.activeAssignment(resource.OwnerPersonID)
		if err != nil {
			return ResourcePublication{}, err
		}
		if assignment.UserID != requestedBy || assignment.PositionID != resource.OwnerPositionID {
			return ResourcePublication{}, ErrForbiddenDelegation
		}
	}
	item.Status = "pending"
	item.RequestedBy = requestedBy
	item.RequestedAt = now()
	result, err := s.db.Exec(`
		INSERT INTO resource_publications (resource_id, target_level, reason, status, requested_by, requested_at)
		VALUES (?, ?, ?, 'pending', ?, ?)
	`, item.ResourceID, item.TargetLevel, item.Reason, item.RequestedBy, item.RequestedAt)
	if err != nil {
		return ResourcePublication{}, err
	}
	item.ID, _ = result.LastInsertId()
	return item, nil
}

func (s *Store) ListResourcePublications(claimUserID string, elevated bool) ([]ResourcePublication, error) {
	return s.ListResourcePublicationsByTenant(claimUserID, elevated, "")
}

func (s *Store) ListResourcePublicationsByTenant(claimUserID string, elevated bool, tenantID string) ([]ResourcePublication, error) {
	tenantID = strings.TrimSpace(tenantID)
	query := `
		SELECT p.id, p.resource_id, p.target_level, p.reason, p.status, p.requested_by, p.requested_at, COALESCE(p.approved_by, ''), COALESCE(p.approved_at, '')
		FROM resource_publications p
		JOIN resources r ON r.id = p.resource_id
		WHERE 1=1
	`
	args := make([]interface{}, 0)
	if tenantID != "" {
		query += " AND r.tenant_id=?"
		args = append(args, tenantID)
	}
	if !elevated {
		query += " AND (p.requested_by=? OR r.owner_user_id=?)"
		args = append(args, claimUserID, claimUserID)
	}
	query += " ORDER BY p.id"
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]ResourcePublication, 0)
	for rows.Next() {
		var item ResourcePublication
		if err := rows.Scan(&item.ID, &item.ResourceID, &item.TargetLevel, &item.Reason, &item.Status, &item.RequestedBy, &item.RequestedAt, &item.ApprovedBy, &item.ApprovedAt); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *Store) ApproveResourcePublication(id int64, approvedBy string) (ResourcePublication, error) {
	var item ResourcePublication
	err := s.db.QueryRow(`
		SELECT id, resource_id, target_level, reason, status, requested_by, requested_at, COALESCE(approved_by, ''), COALESCE(approved_at, '')
		FROM resource_publications
		WHERE id=?
	`, id).Scan(&item.ID, &item.ResourceID, &item.TargetLevel, &item.Reason, &item.Status, &item.RequestedBy, &item.RequestedAt, &item.ApprovedBy, &item.ApprovedAt)
	if err == sql.ErrNoRows {
		return ResourcePublication{}, ErrNotFound
	}
	if err != nil {
		return ResourcePublication{}, err
	}
	if item.Status == "approved" {
		return item, nil
	}
	ts := now()
	tx, err := s.db.Begin()
	if err != nil {
		return ResourcePublication{}, err
	}
	defer tx.Rollback()
	if _, err := tx.Exec("UPDATE resources SET level=? WHERE id=?", item.TargetLevel, item.ResourceID); err != nil {
		return ResourcePublication{}, err
	}
	if _, err := tx.Exec("UPDATE resource_publications SET status='approved', approved_by=?, approved_at=? WHERE id=?", approvedBy, ts, id); err != nil {
		return ResourcePublication{}, err
	}
	if err := tx.Commit(); err != nil {
		return ResourcePublication{}, err
	}
	item.Status = "approved"
	item.ApprovedBy = approvedBy
	item.ApprovedAt = ts
	return item, nil
}

func (s *Store) ResourcePublicationTenant(id int64) (string, error) {
	var tenantID string
	err := s.db.QueryRow(`
		SELECT r.tenant_id
		FROM resource_publications p
		JOIN resources r ON r.id = p.resource_id
		WHERE p.id=?
	`, id).Scan(&tenantID)
	if err == sql.ErrNoRows {
		return "", ErrNotFound
	}
	return tenantID, err
}

func (s *Store) GetResource(id string) (Resource, error) {
	items, err := s.queryResources(`
		SELECT id, name, resource_type, level, status, COALESCE(asset_pool, ''), COALESCE(locked_by, ''), COALESCE(locked_at, ''), owner_person_id, owner_user_id, owner_position_id, department_id, tenant_id, created_by, created_at
		FROM resources
		WHERE id=?
	`, strings.TrimSpace(id))
	if err != nil {
		return Resource{}, err
	}
	if len(items) == 0 {
		return Resource{}, ErrNotFound
	}
	return items[0], nil
}

func (s *Store) CreateDataRecord(item DataRecord) (DataRecord, error) {
	item = normalizeDataRecord(item)
	if item.ID == "" || item.Title == "" || item.SourceType == "" || item.OwnerPersonID == "" || item.OwnerUserID == "" || item.TenantID == "" || item.Basis == "" || item.CreatedBy == "" {
		return DataRecord{}, fmt.Errorf("missing field")
	}
	if item.Status == "" {
		item.Status = "active"
	}
	if !validDataStatus(item.Status) {
		return DataRecord{}, fmt.Errorf("invalid data status")
	}
	ownerContextValid, err := s.dataOwnerContextValid(item)
	if err != nil {
		return DataRecord{}, err
	}
	if !ownerContextValid {
		return DataRecord{}, ErrInvalidOwnerContext
	}
	if len(item.AllowedActions) == 0 {
		item.AllowedActions = []string{"read", "fetch", "store", "update"}
	}
	for _, action := range item.AllowedActions {
		enabled, err := s.IsDataActionEnabled(action)
		if err != nil {
			return DataRecord{}, err
		}
		if !enabled {
			return DataRecord{}, fmt.Errorf("invalid data action")
		}
	}
	actionsJSON, err := encodeStringList(item.AllowedActions)
	if err != nil {
		return DataRecord{}, err
	}
	tagsJSON, err := encodeStringList(item.BusinessTags)
	if err != nil {
		return DataRecord{}, err
	}
	refsJSON, err := encodeStringList(item.StorageRefs)
	if err != nil {
		return DataRecord{}, err
	}
	initialPersonIDsJSON, err := encodeStringList(item.InitialPersonIDs)
	if err != nil {
		return DataRecord{}, err
	}
	initialUserIDsJSON, err := encodeStringList(item.InitialUserIDs)
	if err != nil {
		return DataRecord{}, err
	}
	item.CreatedAt = now()
	_, err = s.db.Exec(`
		INSERT INTO data_records (id, title, source_type, owner_person_id, owner_user_id, tenant_id, business_tags, storage_refs, status, allowed_actions, initial_person_ids, initial_user_ids, basis, created_by, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, item.ID, item.Title, item.SourceType, item.OwnerPersonID, item.OwnerUserID, item.TenantID, tagsJSON, refsJSON, item.Status, actionsJSON, initialPersonIDsJSON, initialUserIDsJSON, item.Basis, item.CreatedBy, item.CreatedAt)
	return item, err
}

func (s *Store) RegisterDataAction(item DataAction) (DataAction, error) {
	item.Action = strings.TrimSpace(item.Action)
	item.Description = strings.TrimSpace(item.Description)
	item.RiskLevel = strings.TrimSpace(item.RiskLevel)
	item.CreatedBy = strings.TrimSpace(item.CreatedBy)
	if item.Action == "" || item.Description == "" || item.CreatedBy == "" {
		return DataAction{}, fmt.Errorf("missing field")
	}
	if item.RiskLevel == "" {
		item.RiskLevel = "normal"
	}
	if item.RiskLevel != "normal" && item.RiskLevel != "high" {
		return DataAction{}, fmt.Errorf("invalid data action risk")
	}
	item.Enabled = true
	item.CreatedAt = now()
	_, err := s.db.Exec(`
		INSERT INTO data_actions (action, description, risk_level, enabled, created_by, created_at)
		VALUES (?, ?, ?, 1, ?, ?)
		ON CONFLICT(action) DO UPDATE SET
			description=excluded.description,
			risk_level=excluded.risk_level,
			enabled=1,
			created_by=excluded.created_by,
			created_at=excluded.created_at
	`, item.Action, item.Description, item.RiskLevel, item.CreatedBy, item.CreatedAt)
	return item, err
}

func (s *Store) ListDataActions() ([]DataAction, error) {
	rows, err := s.db.Query(`
		SELECT action, description, risk_level, enabled, created_by, created_at
		FROM data_actions
		ORDER BY action
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]DataAction, 0)
	for rows.Next() {
		var item DataAction
		var enabled int
		if err := rows.Scan(&item.Action, &item.Description, &item.RiskLevel, &enabled, &item.CreatedBy, &item.CreatedAt); err != nil {
			return nil, err
		}
		item.Enabled = enabled == 1
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *Store) IsDataActionEnabled(action string) (bool, error) {
	action = strings.TrimSpace(action)
	if action == "" {
		return false, nil
	}
	var enabled int
	err := s.db.QueryRow("SELECT enabled FROM data_actions WHERE action=?", action).Scan(&enabled)
	if err == sql.ErrNoRows {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return enabled == 1, nil
}

func (s *Store) ListDataRecords(elevated bool, claimUserID string, filters DataRecordFilters) ([]DataRecord, error) {
	filters = normalizeDataRecordFilters(filters)
	query := `
		SELECT id, title, source_type, owner_person_id, owner_user_id, tenant_id, business_tags, storage_refs, status, allowed_actions, initial_person_ids, initial_user_ids, COALESCE(asset_pool, ''), COALESCE(locked_by, ''), COALESCE(locked_at, ''), basis, created_by, created_at, COALESCE(updated_by, ''), COALESCE(updated_at, '')
		FROM data_records
		WHERE 1=1
	`
	args := make([]interface{}, 0)
	if filters.OwnerPersonID != "" {
		query += " AND owner_person_id=?"
		args = append(args, filters.OwnerPersonID)
	}
	if filters.OwnerUserID != "" {
		query += " AND owner_user_id=?"
		args = append(args, filters.OwnerUserID)
	}
	if filters.TenantID != "" {
		query += " AND tenant_id=?"
		args = append(args, filters.TenantID)
	}
	if filters.Status != "" {
		query += " AND status=?"
		args = append(args, filters.Status)
	}
	if !elevated {
		assignment, err := s.activeAssignmentByUser(claimUserID)
		if err != nil {
			return []DataRecord{}, nil
		}
		query += " AND (owner_person_id=? OR owner_user_id=?)"
		args = append(args, assignment.PersonID, claimUserID)
	}
	query += " ORDER BY id"
	return s.queryDataRecords(query, args...)
}

func (s *Store) BuildDataAccessSummary(claimUserID string, elevated bool, records []DataRecord) ([]DataAccessEntry, error) {
	return s.BuildDataAccessSummaryByTenant(claimUserID, elevated, "", records)
}

func (s *Store) BuildDataAccessSummaryByTenant(claimUserID string, elevated bool, tenantID string, records []DataRecord) ([]DataAccessEntry, error) {
	tenantID = strings.TrimSpace(tenantID)
	assignments, err := s.ListAssignmentsByTenant(tenantID)
	if err != nil {
		return nil, err
	}
	standards, err := s.ListStandardResourcesByTenant(tenantID)
	if err != nil {
		return nil, err
	}
	delegations, err := s.ListDelegationsForSnapshot("", true, DelegationFilters{TenantID: tenantID})
	if err != nil {
		return nil, err
	}

	activeByPerson := make(map[string]Assignment)
	activeByUser := make(map[string]Assignment)
	activeByPosition := make(map[string][]Assignment)
	currentPersonID := ""
	if !elevated {
		if assignment, err := s.activeAssignmentByUser(claimUserID); err == nil {
			currentPersonID = assignment.PersonID
		}
	}
	for _, assignment := range assignments {
		if assignment.Status != "active" {
			continue
		}
		activeByPerson[assignment.PersonID] = assignment
		activeByUser[assignment.UserID] = assignment
		activeByPosition[assignment.PositionID] = append(activeByPosition[assignment.PositionID], assignment)
	}

	result := make([]DataAccessEntry, 0)
	include := func(entry DataAccessEntry) {
		if !elevated && entry.PersonID != currentPersonID && entry.UserID != claimUserID {
			return
		}
		result = append(result, entry)
	}

	for _, record := range records {
		if record.Status != "active" {
			continue
		}
		allowedActions := uniqueStrings(record.AllowedActions)
		ownerAssignment, hasOwnerAssignment := activeByPerson[record.OwnerPersonID]
		for _, action := range allowedActions {
			if isDataOwnerDefaultAction(action) {
				entry := DataAccessEntry{
					DataID:   record.ID,
					Source:   "owner",
					PersonID: record.OwnerPersonID,
					UserID:   record.OwnerUserID,
					Action:   action,
					PolicyID: "data_owner:" + record.ID + ":" + action,
				}
				if hasOwnerAssignment {
					entry.PositionID = ownerAssignment.PositionID
				}
				include(entry)
			}
			if isDataInitialParticipantAction(action) {
				for _, personID := range uniqueStrings(record.InitialPersonIDs) {
					assignment, ok := activeByPerson[personID]
					entry := DataAccessEntry{
						DataID:   record.ID,
						Source:   "initial_participant",
						PersonID: personID,
						Action:   action,
						PolicyID: "data_initial:" + record.ID + ":" + personID + ":" + action,
					}
					if ok {
						entry.UserID = assignment.UserID
						entry.PositionID = assignment.PositionID
					}
					include(entry)
				}
				for _, userID := range uniqueStrings(record.InitialUserIDs) {
					assignment, ok := activeByUser[userID]
					if !ok || assignment.TenantID != record.TenantID {
						continue
					}
					include(DataAccessEntry{
						DataID:     record.ID,
						Source:     "initial_participant",
						PersonID:   assignment.PersonID,
						UserID:     userID,
						PositionID: assignment.PositionID,
						Action:     action,
						PolicyID:   "data_initial:" + record.ID + ":" + assignment.PersonID + ":" + action,
					})
				}
			}
		}

		for _, standard := range standards {
			if standard.ResourceType != "data" || standard.ResourceID != record.ID || !containsString(record.AllowedActions, standard.Action) {
				continue
			}
			for _, assignment := range activeByPosition[standard.PositionID] {
				if assignment.TenantID != record.TenantID {
					continue
				}
				include(DataAccessEntry{
					DataID:     record.ID,
					Source:     "position_standard",
					PersonID:   assignment.PersonID,
					UserID:     assignment.UserID,
					PositionID: standard.PositionID,
					Action:     standard.Action,
					PolicyID:   fmt.Sprintf("position_standard:%d", standard.ID),
				})
			}
		}

		for _, delegation := range delegations {
			if delegation.ResourceType != "data" || delegation.ResourceID != record.ID || !containsString(record.AllowedActions, delegation.Action) {
				continue
			}
			assignment, ok := activeByPerson[delegation.ToPersonID]
			if !ok || assignment.TenantID != record.TenantID {
				continue
			}
			include(DataAccessEntry{
				DataID:     record.ID,
				Source:     "delegation",
				PersonID:   delegation.ToPersonID,
				UserID:     assignment.UserID,
				PositionID: assignment.PositionID,
				Action:     delegation.Action,
				PolicyID:   fmt.Sprintf("delegation:%d", delegation.ID),
			})
		}
	}
	return result, nil
}

func (s *Store) GetDataRecord(id string) (DataRecord, error) {
	items, err := s.queryDataRecords(`
		SELECT id, title, source_type, owner_person_id, owner_user_id, tenant_id, business_tags, storage_refs, status, allowed_actions, initial_person_ids, initial_user_ids, COALESCE(asset_pool, ''), COALESCE(locked_by, ''), COALESCE(locked_at, ''), basis, created_by, created_at, COALESCE(updated_by, ''), COALESCE(updated_at, '')
		FROM data_records
		WHERE id=?
	`, strings.TrimSpace(id))
	if err != nil {
		return DataRecord{}, err
	}
	if len(items) == 0 {
		return DataRecord{}, ErrNotFound
	}
	return items[0], nil
}

func (s *Store) SetDataRecordStatus(id, status, updatedBy string) (DataRecord, error) {
	id = strings.TrimSpace(id)
	status = strings.TrimSpace(status)
	updatedBy = strings.TrimSpace(updatedBy)
	if id == "" || status == "" || updatedBy == "" {
		return DataRecord{}, fmt.Errorf("missing field")
	}
	if !validDataStatus(status) {
		return DataRecord{}, fmt.Errorf("invalid data status")
	}
	if _, err := s.GetDataRecord(id); err != nil {
		return DataRecord{}, err
	}
	ts := now()
	if _, err := s.db.Exec("UPDATE data_records SET status=?, updated_by=?, updated_at=? WHERE id=?", status, updatedBy, ts, id); err != nil {
		return DataRecord{}, err
	}
	return s.GetDataRecord(id)
}

func (s *Store) PersonHasAccess(ctx ValidateContext) (AccessDecision, error) {
	assignments, err := s.activeAssignments(ctx.PersonID)
	if err != nil {
		return AccessDecision{}, err
	}
	assignments = filterAssignmentsForContext(assignments, ctx)
	if len(assignments) == 0 {
		return AccessDecision{}, ErrInvalidContext
	}
	if ctx.DomainID != "" {
		if ok, err := s.domainExists(ctx.DomainID); err != nil {
			return AccessDecision{}, err
		} else if !ok {
			return AccessDecision{}, ErrInvalidContext
		}
	}
	if decision, err := s.dataRecordConstraintDecision(ctx); err != nil {
		return AccessDecision{}, err
	} else if decision.PolicyID != "" && !decision.Allow {
		return decision, nil
	}
	for _, assignment := range assignments {
		if decision, err := s.dataRecordOwnerDecision(assignment, ctx); err != nil {
			return AccessDecision{}, err
		} else if decision.Allow {
			return decision, nil
		}
		if decision, err := s.dataRecordInitialParticipantDecision(assignment, ctx); err != nil {
			return AccessDecision{}, err
		} else if decision.Allow {
			return decision, nil
		}
		if decision, err := s.positionStandardDecision(assignment.PositionID, ctx); err != nil {
			return AccessDecision{}, err
		} else if decision.Allow {
			return decision, nil
		}
	}
	if decision, err := s.delegationDecision(ctx); err != nil {
		return AccessDecision{}, err
	} else if decision.Allow {
		return decision, nil
	}
	for _, assignment := range assignments {
		if decision, err := s.managerScopeDecision(assignment, ctx); err != nil {
			return AccessDecision{}, err
		} else if decision.Allow {
			return decision, nil
		}
		if decision, err := s.resourceScopeDecision(assignment, ctx); err != nil {
			return AccessDecision{}, err
		} else if decision.Allow {
			return decision, nil
		}
	}
	return AccessDecision{}, nil
}

func (s *Store) dataRecordConstraintDecision(ctx ValidateContext) (AccessDecision, error) {
	if ctx.ResourceType != "data" {
		return AccessDecision{}, nil
	}
	enabled, err := s.IsDataActionEnabled(ctx.Action)
	if err != nil {
		return AccessDecision{}, err
	}
	if !enabled {
		return AccessDecision{Allow: false, PolicyID: "data_action_unregistered:" + ctx.Action}, nil
	}
	record, err := s.GetDataRecord(ctx.ResourceID)
	if err == ErrNotFound {
		return AccessDecision{}, nil
	}
	if err != nil {
		return AccessDecision{}, err
	}
	if record.Status != "active" {
		return AccessDecision{Allow: false, PolicyID: "data_record_inactive:" + record.ID}, nil
	}
	if !containsString(record.AllowedActions, ctx.Action) {
		return AccessDecision{Allow: false, PolicyID: "data_action_forbidden:" + record.ID}, nil
	}
	return AccessDecision{}, nil
}

func (s *Store) dataRecordOwnerDecision(assignment Assignment, ctx ValidateContext) (AccessDecision, error) {
	if ctx.ResourceType != "data" || !isDataOwnerDefaultAction(ctx.Action) {
		return AccessDecision{}, nil
	}
	record, err := s.GetDataRecord(ctx.ResourceID)
	if err == ErrNotFound {
		return AccessDecision{}, nil
	}
	if err != nil {
		return AccessDecision{}, err
	}
	if record.OwnerPersonID == assignment.PersonID && record.OwnerUserID == assignment.UserID && record.TenantID == assignment.TenantID {
		return AccessDecision{Allow: true, PolicyID: "data_owner:" + record.ID + ":" + ctx.Action}, nil
	}
	return AccessDecision{}, nil
}

func (s *Store) dataRecordInitialParticipantDecision(assignment Assignment, ctx ValidateContext) (AccessDecision, error) {
	if ctx.ResourceType != "data" || !isDataInitialParticipantAction(ctx.Action) {
		return AccessDecision{}, nil
	}
	record, err := s.GetDataRecord(ctx.ResourceID)
	if err == ErrNotFound {
		return AccessDecision{}, nil
	}
	if err != nil {
		return AccessDecision{}, err
	}
	if record.TenantID != assignment.TenantID {
		return AccessDecision{}, nil
	}
	if containsString(record.InitialPersonIDs, assignment.PersonID) || containsString(record.InitialUserIDs, assignment.UserID) {
		return AccessDecision{Allow: true, PolicyID: "data_initial:" + record.ID + ":" + assignment.PersonID + ":" + ctx.Action}, nil
	}
	return AccessDecision{}, nil
}

func (s *Store) PersonCanRedelegate(personID, resourceType, resourceID, action, ownerUserID string) (bool, error) {
	assignments, err := s.activeAssignments(personID)
	if err != nil {
		return false, err
	}
	for _, assignment := range assignments {
		ctx := ValidateContext{
			PersonID:     personID,
			UserID:       assignment.UserID,
			PositionID:   assignment.PositionID,
			TenantID:     assignment.TenantID,
			ResourceType: resourceType,
			ResourceID:   resourceID,
			Action:       action,
			OwnerUserID:  ownerUserID,
		}
		if decision, err := s.positionStandardDecision(assignment.PositionID, ctx); err != nil {
			return false, err
		} else if decision.Allow {
			return true, nil
		}
	}
	var id int64
	err = s.db.QueryRow(`
		SELECT id
		FROM delegations
		WHERE to_person_id=? AND resource_type=? AND resource_id=? AND action=? AND owner_user_id=? AND can_redelegate=1
		ORDER BY id
		LIMIT 1
	`, personID, resourceType, resourceID, action, ownerUserID).Scan(&id)
	if err == sql.ErrNoRows {
		return false, nil
	}
	return err == nil, err
}

func (s *Store) activeAssignment(personID string) (Assignment, error) {
	assignments, err := s.activeAssignments(personID)
	if err != nil {
		return Assignment{}, err
	}
	return assignments[0], nil
}

func (s *Store) activeAssignments(personID string) ([]Assignment, error) {
	rows, err := s.db.Query(`
		SELECT id, person_id, user_id, position_id, tenant_id, status, assigned_by, assigned_at, COALESCE(ended_by, ''), COALESCE(ended_at, '')
		FROM person_position_assignments
		WHERE person_id=? AND status='active'
		ORDER BY id
	`, strings.TrimSpace(personID))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]Assignment, 0)
	for rows.Next() {
		var item Assignment
		if err := rows.Scan(&item.ID, &item.PersonID, &item.UserID, &item.PositionID, &item.TenantID, &item.Status, &item.AssignedBy, &item.AssignedAt, &item.EndedBy, &item.EndedAt); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(result) == 0 {
		return nil, ErrInvalidContext
	}
	return result, nil
}

func (s *Store) activeAssignmentByUser(userID string) (Assignment, error) {
	var item Assignment
	err := s.db.QueryRow(`
		SELECT id, person_id, user_id, position_id, tenant_id, status, assigned_by, assigned_at, COALESCE(ended_by, ''), COALESCE(ended_at, '')
		FROM person_position_assignments
		WHERE user_id=? AND status='active'
		ORDER BY id
		LIMIT 1
	`, strings.TrimSpace(userID)).Scan(&item.ID, &item.PersonID, &item.UserID, &item.PositionID, &item.TenantID, &item.Status, &item.AssignedBy, &item.AssignedAt, &item.EndedBy, &item.EndedAt)
	if err == sql.ErrNoRows {
		return Assignment{}, ErrInvalidContext
	}
	return item, err
}

func filterAssignmentsForContext(assignments []Assignment, ctx ValidateContext) []Assignment {
	result := make([]Assignment, 0, len(assignments))
	for _, assignment := range assignments {
		if assignment.UserID != ctx.UserID || assignment.Status != "active" {
			continue
		}
		if ctx.TenantID != "" && assignment.TenantID != ctx.TenantID {
			continue
		}
		if ctx.PositionID != "" && assignment.PositionID != ctx.PositionID {
			continue
		}
		result = append(result, assignment)
	}
	return result
}

func (s *Store) positionStandardDecision(positionID string, ctx ValidateContext) (AccessDecision, error) {
	var id int64
	err := s.db.QueryRow(`
		SELECT id
		FROM position_standard_resources
		WHERE position_id=? AND resource_type=? AND resource_id=? AND action=? AND owner_user_id=?
		ORDER BY id
		LIMIT 1
	`, positionID, ctx.ResourceType, ctx.ResourceID, ctx.Action, ctx.OwnerUserID).Scan(&id)
	if err == sql.ErrNoRows {
		return AccessDecision{}, nil
	}
	if err != nil {
		return AccessDecision{}, err
	}
	return AccessDecision{Allow: true, PolicyID: fmt.Sprintf("position_standard:%d", id)}, nil
}

func (s *Store) delegationDecision(ctx ValidateContext) (AccessDecision, error) {
	query := `
		SELECT id
		FROM delegations
		WHERE to_person_id=? AND resource_type=? AND resource_id=? AND action=? AND owner_user_id=?
	`
	args := []interface{}{ctx.PersonID, ctx.ResourceType, ctx.ResourceID, ctx.Action, ctx.OwnerUserID}
	if ctx.DelegationID != "" {
		query += " AND id=?"
		args = append(args, ctx.DelegationID)
	}
	query += " ORDER BY id LIMIT 1"
	var id int64
	err := s.db.QueryRow(query, args...).Scan(&id)
	if err == sql.ErrNoRows {
		return AccessDecision{}, nil
	}
	if err != nil {
		return AccessDecision{}, err
	}
	return AccessDecision{Allow: true, PolicyID: fmt.Sprintf("delegation:%d", id)}, nil
}

func (s *Store) managerScopeDecision(assignment Assignment, ctx ValidateContext) (AccessDecision, error) {
	if ctx.ResourceType != "data" || (ctx.Action != "fetch" && ctx.Action != "read") {
		return AccessDecision{}, nil
	}
	if strings.TrimSpace(ctx.DomainID) == "" {
		return AccessDecision{}, nil
	}
	ownerPersonID := strings.TrimSpace(ctx.OwnerPersonID)
	if ownerPersonID == "" {
		record, err := s.GetDataRecord(ctx.ResourceID)
		if err == ErrNotFound {
			return AccessDecision{}, nil
		}
		if err != nil {
			return AccessDecision{}, err
		}
		if record.TenantID != assignment.TenantID {
			return AccessDecision{}, nil
		}
		ownerPersonID = record.OwnerPersonID
	}
	if ctx.PersonID == ownerPersonID {
		return AccessDecision{}, nil
	}
	ok, err := s.IsPersonInManagerScope(ctx.PersonID, ownerPersonID, ctx.DomainID)
	if err != nil || !ok {
		return AccessDecision{}, err
	}
	return AccessDecision{Allow: true, PolicyID: "manager_scope:" + ctx.DomainID + ":" + ctx.PersonID + ":" + ownerPersonID}, nil
}

func (s *Store) resourceScopeDecision(assignment Assignment, ctx ValidateContext) (AccessDecision, error) {
	if !validDirectoryResourceType(ctx.ResourceType) {
		return AccessDecision{}, nil
	}
	resource, err := s.GetResource(ctx.ResourceID)
	if err == ErrNotFound {
		return AccessDecision{}, nil
	}
	if err != nil {
		return AccessDecision{}, err
	}
	if resource.ResourceType != ctx.ResourceType || resource.Status != "active" {
		return AccessDecision{}, nil
	}
	switch resource.Level {
	case "personal_position":
		if resource.OwnerPersonID == assignment.PersonID && resource.OwnerPositionID == assignment.PositionID && resource.OwnerUserID == assignment.UserID {
			return AccessDecision{Allow: true, PolicyID: resourceScopePolicyID(resource)}, nil
		}
	case "department_public":
		departmentID, err := s.departmentForPosition(assignment.PositionID)
		if err != nil {
			return AccessDecision{}, err
		}
		if resource.DepartmentID == departmentID && resource.TenantID == assignment.TenantID {
			return AccessDecision{Allow: true, PolicyID: resourceScopePolicyID(resource)}, nil
		}
	case "company_public":
		if resource.TenantID == assignment.TenantID {
			return AccessDecision{Allow: true, PolicyID: resourceScopePolicyID(resource)}, nil
		}
	}
	return AccessDecision{}, nil
}

func (s *Store) ListSubordinates(managerPersonID, domainID string) ([]Subordinate, error) {
	return s.ListSubordinatesByTenant(managerPersonID, domainID, "")
}

func (s *Store) ListSubordinatesByTenant(managerPersonID, domainID, tenantID string) ([]Subordinate, error) {
	managerPersonID = strings.TrimSpace(managerPersonID)
	domainID = strings.TrimSpace(domainID)
	tenantID = strings.TrimSpace(tenantID)
	if managerPersonID == "" || domainID == "" {
		return []Subordinate{}, nil
	}
	edges, err := s.ListManagerEdgesByTenant(tenantID)
	if err != nil {
		return nil, err
	}
	children := make(map[string][]ManagerEdge)
	for _, edge := range edges {
		if edge.DomainID == domainID {
			children[edge.ManagerPersonID] = append(children[edge.ManagerPersonID], edge)
		}
	}
	result := make([]Subordinate, 0)
	visited := map[string]bool{managerPersonID: true}
	queue := []Subordinate{{PersonID: managerPersonID, DomainID: domainID, Depth: 0}}
	for len(queue) > 0 {
		current := queue[0]
		queue = queue[1:]
		for _, edge := range children[current.PersonID] {
			if visited[edge.PersonID] {
				continue
			}
			visited[edge.PersonID] = true
			next := Subordinate{
				PersonID:        edge.PersonID,
				ManagerPersonID: edge.ManagerPersonID,
				DomainID:        edge.DomainID,
				Depth:           current.Depth + 1,
			}
			result = append(result, next)
			queue = append(queue, next)
		}
	}
	return result, nil
}

func (s *Store) IsPersonInManagerScope(managerPersonID, personID, domainID string) (bool, error) {
	subordinates, err := s.ListSubordinates(managerPersonID, domainID)
	if err != nil {
		return false, err
	}
	for _, subordinate := range subordinates {
		if subordinate.PersonID == strings.TrimSpace(personID) {
			return true, nil
		}
	}
	return false, nil
}

func (s *Store) queryResources(query string, args ...interface{}) ([]Resource, error) {
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]Resource, 0)
	for rows.Next() {
		var item Resource
		if err := rows.Scan(&item.ID, &item.Name, &item.ResourceType, &item.Level, &item.Status, &item.AssetPool, &item.LockedBy, &item.LockedAt, &item.OwnerPersonID, &item.OwnerUserID, &item.OwnerPositionID, &item.DepartmentID, &item.TenantID, &item.CreatedBy, &item.CreatedAt); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *Store) queryDataRecords(query string, args ...interface{}) ([]DataRecord, error) {
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]DataRecord, 0)
	for rows.Next() {
		var item DataRecord
		var tagsJSON string
		var refsJSON string
		var actionsJSON string
		var initialPersonIDsJSON string
		var initialUserIDsJSON string
		if err := rows.Scan(&item.ID, &item.Title, &item.SourceType, &item.OwnerPersonID, &item.OwnerUserID, &item.TenantID, &tagsJSON, &refsJSON, &item.Status, &actionsJSON, &initialPersonIDsJSON, &initialUserIDsJSON, &item.AssetPool, &item.LockedBy, &item.LockedAt, &item.Basis, &item.CreatedBy, &item.CreatedAt, &item.UpdatedBy, &item.UpdatedAt); err != nil {
			return nil, err
		}
		item.BusinessTags = decodeStringList(tagsJSON)
		item.StorageRefs = decodeStringList(refsJSON)
		item.AllowedActions = decodeStringList(actionsJSON)
		item.InitialPersonIDs = decodeStringList(initialPersonIDsJSON)
		item.InitialUserIDs = decodeStringList(initialUserIDsJSON)
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *Store) positionExists(id string) (bool, error) {
	var found string
	err := s.db.QueryRow("SELECT id FROM positions WHERE id=?", strings.TrimSpace(id)).Scan(&found)
	if err == sql.ErrNoRows {
		return false, nil
	}
	return err == nil, err
}

func (s *Store) domainExists(id string) (bool, error) {
	var found string
	err := s.db.QueryRow("SELECT id FROM domains WHERE id=?", strings.TrimSpace(id)).Scan(&found)
	if err == sql.ErrNoRows {
		return false, nil
	}
	return err == nil, err
}

func (s *Store) positionTenant(id string) (string, error) {
	var tenantID string
	err := s.db.QueryRow("SELECT tenant_id FROM positions WHERE id=?", strings.TrimSpace(id)).Scan(&tenantID)
	if err == sql.ErrNoRows {
		return "", ErrNotFound
	}
	return tenantID, err
}

func (s *Store) domainTenant(id string) (string, error) {
	var tenantID string
	err := s.db.QueryRow("SELECT tenant_id FROM domains WHERE id=?", strings.TrimSpace(id)).Scan(&tenantID)
	if err == sql.ErrNoRows {
		return "", ErrNotFound
	}
	return tenantID, err
}

func (s *Store) personActiveInTenant(personID, tenantID string) (bool, error) {
	var found int
	err := s.db.QueryRow(`
		SELECT 1 FROM person_position_assignments
		WHERE person_id=? AND tenant_id=? AND status='active'
		LIMIT 1
	`, strings.TrimSpace(personID), strings.TrimSpace(tenantID)).Scan(&found)
	if err == sql.ErrNoRows {
		return false, nil
	}
	return err == nil, err
}

func (s *Store) resourceOwnerContextValid(item Resource) (bool, error) {
	var found int
	err := s.db.QueryRow(`
		SELECT 1
		FROM person_position_assignments a
		JOIN positions p ON p.id = a.position_id
		WHERE a.person_id=?
		  AND a.user_id=?
		  AND a.position_id=?
		  AND a.tenant_id=?
		  AND a.status='active'
		  AND p.tenant_id=a.tenant_id
		  AND p.department_id=?
		LIMIT 1
	`, item.OwnerPersonID, item.OwnerUserID, item.OwnerPositionID, item.TenantID, item.DepartmentID).Scan(&found)
	if err == sql.ErrNoRows {
		return false, nil
	}
	return err == nil, err
}

func (s *Store) dataOwnerContextValid(item DataRecord) (bool, error) {
	var found int
	err := s.db.QueryRow(`
		SELECT 1
		FROM person_position_assignments
		WHERE person_id=? AND user_id=? AND tenant_id=? AND status='active'
		LIMIT 1
	`, item.OwnerPersonID, item.OwnerUserID, item.TenantID).Scan(&found)
	if err == sql.ErrNoRows {
		return false, nil
	}
	return err == nil, err
}

func now() string {
	return time.Now().UTC().Format(time.RFC3339)
}

func boolInt(value bool) int {
	if value {
		return 1
	}
	return 0
}

func normalizeResource(item Resource) Resource {
	item.ID = strings.TrimSpace(item.ID)
	item.Name = strings.TrimSpace(item.Name)
	item.ResourceType = strings.TrimSpace(item.ResourceType)
	item.Level = strings.TrimSpace(item.Level)
	item.Status = strings.TrimSpace(item.Status)
	item.OwnerPersonID = strings.TrimSpace(item.OwnerPersonID)
	item.OwnerUserID = strings.TrimSpace(item.OwnerUserID)
	item.OwnerPositionID = strings.TrimSpace(item.OwnerPositionID)
	item.DepartmentID = strings.TrimSpace(item.DepartmentID)
	item.TenantID = strings.TrimSpace(item.TenantID)
	item.CreatedBy = strings.TrimSpace(item.CreatedBy)
	return item
}

func normalizeDataRecord(item DataRecord) DataRecord {
	item.ID = strings.TrimSpace(item.ID)
	item.Title = strings.TrimSpace(item.Title)
	item.SourceType = strings.TrimSpace(item.SourceType)
	item.OwnerPersonID = strings.TrimSpace(item.OwnerPersonID)
	item.OwnerUserID = strings.TrimSpace(item.OwnerUserID)
	item.TenantID = strings.TrimSpace(item.TenantID)
	item.Status = strings.TrimSpace(item.Status)
	item.Basis = strings.TrimSpace(item.Basis)
	item.CreatedBy = strings.TrimSpace(item.CreatedBy)
	return item
}

func normalizeDataRecordFilters(filters DataRecordFilters) DataRecordFilters {
	filters.OwnerPersonID = strings.TrimSpace(filters.OwnerPersonID)
	filters.OwnerUserID = strings.TrimSpace(filters.OwnerUserID)
	filters.TenantID = strings.TrimSpace(filters.TenantID)
	filters.Status = strings.TrimSpace(filters.Status)
	return filters
}

func normalizeResourceFilters(filters ResourceFilters) ResourceFilters {
	filters.ResourceType = strings.TrimSpace(filters.ResourceType)
	filters.Level = strings.TrimSpace(filters.Level)
	filters.DepartmentID = strings.TrimSpace(filters.DepartmentID)
	filters.TenantID = strings.TrimSpace(filters.TenantID)
	filters.Status = strings.TrimSpace(filters.Status)
	return filters
}

func normalizeDelegationFilters(filters DelegationFilters) DelegationFilters {
	filters.PersonID = strings.TrimSpace(filters.PersonID)
	filters.ResourceType = strings.TrimSpace(filters.ResourceType)
	filters.ResourceID = strings.TrimSpace(filters.ResourceID)
	filters.Action = strings.TrimSpace(filters.Action)
	filters.OwnerUserID = strings.TrimSpace(filters.OwnerUserID)
	filters.TenantID = strings.TrimSpace(filters.TenantID)
	return filters
}

func validDirectoryResourceType(resourceType string) bool {
	switch resourceType {
	case "tool", "skill", "knowledge", "digital_employee":
		return true
	default:
		return false
	}
}

func validPublicLevel(level string) bool {
	return level == "department_public" || level == "company_public"
}

func validDataStatus(status string) bool {
	switch status {
	case "active", "disabled", "frozen", "archived":
		return true
	default:
		return false
	}
}

func isDataOwnerDefaultAction(action string) bool {
	switch strings.TrimSpace(action) {
	case "create", "read", "fetch", "use", "store", "update":
		return true
	default:
		return false
	}
}

func isDataInitialParticipantAction(action string) bool {
	switch strings.TrimSpace(action) {
	case "read", "fetch", "use":
		return true
	default:
		return false
	}
}

func containsString(values []string, target string) bool {
	target = strings.TrimSpace(target)
	for _, value := range values {
		if strings.TrimSpace(value) == target {
			return true
		}
	}
	return false
}

func uniqueStrings(values []string) []string {
	result := make([]string, 0, len(values))
	seen := map[string]bool{}
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" || seen[value] {
			continue
		}
		seen[value] = true
		result = append(result, value)
	}
	return result
}

func resourceScopePolicyID(resource Resource) string {
	return "resource_scope:" + resource.ID + ":" + resource.Level
}

func (s *Store) departmentForPosition(positionID string) (string, error) {
	var departmentID string
	err := s.db.QueryRow("SELECT department_id FROM positions WHERE id=?", strings.TrimSpace(positionID)).Scan(&departmentID)
	if err == sql.ErrNoRows {
		return "", ErrInvalidContext
	}
	return departmentID, err
}
