package approvals

import (
	"database/sql"
	"fmt"
	"time"

	"hanhe.com/account-gateway/internal/policy"
)

type runtimePolicy struct {
	PolicyID     string
	Subject      string
	Object       string
	ResourceType string
	Action       string
	Effect       string
	OwnerUserID  string
	TenantID     string
	ApprovalID   int64
	CreatedBy    string
	CreatedAt    string
}

func runtimePolicyFromApproval(req approvalRequest, approvalID int64, createdBy string, createdAt time.Time) runtimePolicy {
	return runtimePolicy{
		PolicyID:     policyID(req),
		Subject:      req.Subject,
		Object:       req.Object,
		ResourceType: req.ResourceType,
		Action:       req.Action,
		Effect:       "allow",
		OwnerUserID:  req.OwnerUserID,
		TenantID:     normalizeTenant(req.TenantID),
		ApprovalID:   approvalID,
		CreatedBy:    createdBy,
		CreatedAt:    createdAt.UTC().Format(time.RFC3339),
	}
}

func insertRuntimePolicy(exec interface {
	Exec(query string, args ...interface{}) (sql.Result, error)
}, item runtimePolicy) (bool, error) {
	result, err := exec.Exec(`
		INSERT OR IGNORE INTO runtime_policies (
			policy_id,
			subject,
			object,
			resource_type,
			action,
			effect,
			owner_user_id,
			tenant_id,
			approval_id,
			created_by,
			created_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`,
		item.PolicyID,
		item.Subject,
		item.Object,
		item.ResourceType,
		item.Action,
		item.Effect,
		item.OwnerUserID,
		item.TenantID,
		item.ApprovalID,
		item.CreatedBy,
		item.CreatedAt,
	)
	if err != nil {
		return false, fmt.Errorf("insert runtime policy: %w", err)
	}
	affected, err := result.RowsAffected()
	if err != nil {
		return false, fmt.Errorf("read inserted runtime policy rows: %w", err)
	}
	return affected > 0, nil
}

func addRuntimePolicy(enforcer *policy.Enforcer, item runtimePolicy) error {
	if enforcer == nil {
		return fmt.Errorf("policy enforcer is not configured")
	}
	effect := item.Effect
	if effect == "" {
		effect = "allow"
	}
	if _, err := enforcer.AddRuntimePolicyForTenant(item.Subject, item.Object, item.ResourceType, item.Action, item.TenantID, effect); err != nil {
		return fmt.Errorf("add runtime policy to enforcer: %w", err)
	}
	return nil
}

func removeRuntimePolicy(enforcer *policy.Enforcer, item runtimePolicy) error {
	if enforcer == nil {
		return fmt.Errorf("policy enforcer is not configured")
	}
	effect := item.Effect
	if effect == "" {
		effect = "allow"
	}
	if _, err := enforcer.RemoveRuntimePolicyForTenant(item.Subject, item.Object, item.ResourceType, item.Action, item.TenantID, effect); err != nil {
		return fmt.Errorf("remove runtime policy from enforcer: %w", err)
	}
	return nil
}

func RestoreRuntimePolicies(db *sql.DB, enforcer *policy.Enforcer) (int, error) {
	rows, err := db.Query(`
		SELECT policy_id, subject, object, resource_type, action, effect, owner_user_id, COALESCE(tenant_id, '*'), COALESCE(approval_id, 0), created_by, created_at
		FROM runtime_policies
		WHERE effect = 'allow'
		ORDER BY created_at, policy_id
	`)
	if err != nil {
		return 0, fmt.Errorf("query runtime policies: %w", err)
	}
	defer rows.Close()

	restored := 0
	for rows.Next() {
		var item runtimePolicy
		if err := rows.Scan(
			&item.PolicyID,
			&item.Subject,
			&item.Object,
			&item.ResourceType,
			&item.Action,
			&item.Effect,
			&item.OwnerUserID,
			&item.TenantID,
			&item.ApprovalID,
			&item.CreatedBy,
			&item.CreatedAt,
		); err != nil {
			return restored, fmt.Errorf("scan runtime policy: %w", err)
		}
		if err := addRuntimePolicy(enforcer, item); err != nil {
			return restored, err
		}
		restored++
	}
	if err := rows.Err(); err != nil {
		return restored, fmt.Errorf("iterate runtime policies: %w", err)
	}
	return restored, nil
}
