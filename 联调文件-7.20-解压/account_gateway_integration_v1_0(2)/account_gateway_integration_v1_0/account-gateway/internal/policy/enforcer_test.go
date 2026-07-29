package policy

import "testing"

func TestBreakglassAccessUsesCasbinPolicy(t *testing.T) {
	chdirModuleRoot(t)

	enforcer, err := NewEnforcer()
	if err != nil {
		t.Fatalf("new enforcer: %v", err)
	}

	decision, err := enforcer.Enforce("breakglass", "unknown_resource", "unknown", "unknown", "owner-1")
	if err != nil {
		t.Fatalf("enforce breakglass: %v", err)
	}
	if !decision.Allow {
		t.Fatalf("breakglass decision denied: %+v", decision)
	}
	if decision.PolicyID != "breakglass:*:*:*:allow" {
		t.Fatalf("breakglass policy id = %q", decision.PolicyID)
	}
}
