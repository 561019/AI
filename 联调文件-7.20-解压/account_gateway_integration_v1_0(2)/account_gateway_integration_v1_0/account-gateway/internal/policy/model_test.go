package policy

import (
	"testing"

	"github.com/casbin/casbin/v2"
	"github.com/casbin/casbin/v2/model"
	"github.com/casbin/casbin/v2/persist"
)

type staticPolicyAdapter struct{}

func (staticPolicyAdapter) LoadPolicy(model model.Model) error {
	policies := []string{
		"p, role_data_writer, data_record_placeholder, data, create, *, allow",
		"p, role_data_writer, data_record_placeholder, data, update, *, allow",
		"p, role_data_writer, data_record_placeholder, data, delete, *, allow",
		"p, role_data_reader, data_record_placeholder, data, read, *, allow",
		"g, user_with_permanent_write, role_data_writer",
		"g, user_with_read, role_data_reader",
	}

	for _, line := range policies {
		if err := persist.LoadPolicyLine(line, model); err != nil {
			return err
		}
	}

	return nil
}

func (staticPolicyAdapter) SavePolicy(model.Model) error                              { return nil }
func (staticPolicyAdapter) AddPolicy(string, string, []string) error                  { return nil }
func (staticPolicyAdapter) RemovePolicy(string, string, []string) error               { return nil }
func (staticPolicyAdapter) RemoveFilteredPolicy(string, string, int, ...string) error { return nil }

func TestModelEnforce(t *testing.T) {
	enforcer, err := casbin.NewEnforcer("model.conf", staticPolicyAdapter{})
	if err != nil {
		t.Fatalf("load model: %v", err)
	}

	tests := []struct {
		name  string
		sub   string
		obj   string
		typ   string
		act   string
		owner string
		want  bool
	}{
		{
			name:  "tool owner can create without approval",
			sub:   "tool_owner_placeholder",
			obj:   "tool_resource_placeholder",
			typ:   "tool",
			act:   "create",
			owner: "tool_owner_placeholder",
			want:  true,
		},
		{
			name:  "non owner cannot create tool without policy",
			sub:   "other_actor_placeholder",
			obj:   "tool_resource_placeholder",
			typ:   "tool",
			act:   "create",
			owner: "tool_owner_placeholder",
			want:  false,
		},
		{
			name:  "data write without permanent policy is denied",
			sub:   "user_without_write_placeholder",
			obj:   "data_record_placeholder",
			typ:   "data",
			act:   "create",
			owner: "data_owner_placeholder",
			want:  false,
		},
		{
			name:  "data write with permanent policy is allowed",
			sub:   "user_with_permanent_write",
			obj:   "data_record_placeholder",
			typ:   "data",
			act:   "update",
			owner: "data_owner_placeholder",
			want:  true,
		},
		{
			name:  "data read with policy is allowed",
			sub:   "user_with_read",
			obj:   "data_record_placeholder",
			typ:   "data",
			act:   "read",
			owner: "data_owner_placeholder",
			want:  true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := enforcer.Enforce(tt.sub, tt.obj, tt.typ, tt.act, tt.owner, "org-1")
			if err != nil {
				t.Fatalf("enforce: %v", err)
			}
			if got != tt.want {
				t.Fatalf("enforce = %v, want %v", got, tt.want)
			}
		})
	}
}
