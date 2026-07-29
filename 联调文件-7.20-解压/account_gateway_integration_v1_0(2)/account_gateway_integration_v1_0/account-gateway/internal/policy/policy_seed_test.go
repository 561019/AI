package policy

import "testing"

func TestPolicySeedLoadsAndEnforcesRuntimeModel(t *testing.T) {
	chdirModuleRoot(t)

	enforcer, err := NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}

	tests := []struct {
		name         string
		sub          string
		obj          string
		typ          string
		act          string
		owner        string
		wantAllow    bool
		wantPolicyID string
	}{
		{
			name:         "converted seed policy supports wildcard type and action",
			sub:          "hanhe_admin",
			obj:          "/admin/:resource",
			typ:          "data",
			act:          "write",
			owner:        "owner-1",
			wantAllow:    true,
			wantPolicyID: "hanhe_admin:/admin/:resource:*:*:allow",
		},
		{
			name:         "breakglass wildcard policy allows any runtime action",
			sub:          "breakglass",
			obj:          "unknown_resource",
			typ:          "unknown",
			act:          "unknown",
			owner:        "owner-1",
			wantAllow:    true,
			wantPolicyID: "breakglass:*:*:*:allow",
		},
		{
			name:         "data writer compatibility policy allows update",
			sub:          "user_with_permanent_write",
			obj:          "data_record_placeholder",
			typ:          "data",
			act:          "update",
			owner:        "data_owner_placeholder",
			wantAllow:    true,
			wantPolicyID: "role_data_writer:data_record_placeholder:data:update:allow",
		},
		{
			name:         "data reader compatibility policy allows read",
			sub:          "user_with_read",
			obj:          "data_record_placeholder",
			typ:          "data",
			act:          "read",
			owner:        "data_owner_placeholder",
			wantAllow:    true,
			wantPolicyID: "role_data_reader:data_record_placeholder:data:read:allow",
		},
		{
			name:         "unmatched data action is denied",
			sub:          "user_without_write_placeholder",
			obj:          "data_record_placeholder",
			typ:          "data",
			act:          "delete",
			owner:        "data_owner_placeholder",
			wantAllow:    false,
			wantPolicyID: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			decision, err := enforcer.Enforce(tt.sub, tt.obj, tt.typ, tt.act, tt.owner)
			if err != nil {
				t.Fatalf("enforce: %v", err)
			}
			if decision.Allow != tt.wantAllow {
				t.Fatalf("allow = %v, want %v, decision = %+v", decision.Allow, tt.wantAllow, decision)
			}
			if decision.PolicyID != tt.wantPolicyID {
				t.Fatalf("policy id = %q, want %q", decision.PolicyID, tt.wantPolicyID)
			}
		})
	}
}
