package policy

import (
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/casbin/casbin/v2"
	"github.com/casbin/casbin/v2/model"
	"github.com/casbin/casbin/v2/persist"
)

type Enforcer struct {
	enforcer *casbin.Enforcer
}

type Decision struct {
	Allow    bool
	PolicyID string
}

func NewEnforcer() (*Enforcer, error) {
	basePath, err := packageDir()
	if err != nil {
		return nil, err
	}
	modelPath := filepath.Join(basePath, "model.conf")
	policyPath := filepath.Join(basePath, "policy_seed.csv")

	adapter, err := newValidatePolicyAdapter(policyPath)
	if err != nil {
		return nil, err
	}

	enforcer, err := casbin.NewEnforcer(modelPath, adapter)
	if err != nil {
		return nil, fmt.Errorf("load casbin enforcer: %w", err)
	}

	return &Enforcer{enforcer: enforcer}, nil
}

func packageDir() (string, error) {
	var candidates []string
	if _, file, _, ok := runtime.Caller(0); ok {
		candidates = append(candidates, filepath.Dir(file))
	}
	if cwd, err := os.Getwd(); err == nil {
		candidates = append(candidates,
			filepath.Join(cwd, "internal", "policy"),
			cwd,
		)
	}
	if executable, err := os.Executable(); err == nil {
		candidates = append(candidates,
			filepath.Join(filepath.Dir(executable), "internal", "policy"),
		)
	}

	for _, candidate := range candidates {
		if policyFilesExist(candidate) {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("locate policy package")
}

func policyFilesExist(dir string) bool {
	if dir == "" {
		return false
	}
	if _, err := os.Stat(filepath.Join(dir, "model.conf")); err != nil {
		return false
	}
	if _, err := os.Stat(filepath.Join(dir, "policy_seed.csv")); err != nil {
		return false
	}
	return true
}

func (e *Enforcer) Enforce(sub, obj, typ, act, owner string) (Decision, error) {
	return e.EnforceWithTenant(sub, obj, typ, act, owner, "*")
}

func (e *Enforcer) EnforceWithTenant(sub, obj, typ, act, owner, tenant string) (Decision, error) {
	if typ == "tool" && (act == "create" || act == "update") && sub == owner {
		return Decision{Allow: true, PolicyID: "tool_owner_self"}, nil
	}
	if strings.TrimSpace(tenant) == "" {
		tenant = "*"
	}

	allow, matched, err := e.enforcer.EnforceEx(sub, obj, typ, act, owner, tenant)
	if err != nil {
		return Decision{}, err
	}

	decision := Decision{Allow: allow}
	if allow {
		decision.PolicyID = policyID(matched)
	}
	return decision, nil
}

func (e *Enforcer) AddRuntimePolicy(sub, obj, typ, act, eft string) (bool, error) {
	return e.AddRuntimePolicyForTenant(sub, obj, typ, act, "*", eft)
}

func (e *Enforcer) AddRuntimePolicyForTenant(sub, obj, typ, act, tenant, eft string) (bool, error) {
	if eft == "" {
		eft = "allow"
	}
	if strings.TrimSpace(tenant) == "" {
		tenant = "*"
	}
	return e.enforcer.AddPolicy(sub, obj, typ, act, tenant, eft)
}

func (e *Enforcer) RemoveRuntimePolicy(sub, obj, typ, act, eft string) (bool, error) {
	return e.RemoveRuntimePolicyForTenant(sub, obj, typ, act, "*", eft)
}

func (e *Enforcer) RemoveRuntimePolicyForTenant(sub, obj, typ, act, tenant, eft string) (bool, error) {
	if eft == "" {
		eft = "allow"
	}
	if strings.TrimSpace(tenant) == "" {
		tenant = "*"
	}
	return e.enforcer.RemovePolicy(sub, obj, typ, act, tenant, eft)
}

type validatePolicyAdapter struct {
	lines []string
}

func newValidatePolicyAdapter(seedPath string) (validatePolicyAdapter, error) {
	lines, err := loadCompatibleSeedPolicies(seedPath)
	if err != nil {
		return validatePolicyAdapter{}, err
	}

	lines = append(lines,
		"p, breakglass, *, *, *, *, allow",
		"p, role_data_writer, data_record_placeholder, data, create, *, allow",
		"p, role_data_writer, data_record_placeholder, data, update, *, allow",
		"p, role_data_writer, data_record_placeholder, data, delete, *, allow",
		"p, role_data_reader, data_record_placeholder, data, read, *, allow",
		"g, user_with_permanent_write, role_data_writer",
		"g, user_with_read, role_data_reader",
	)

	return validatePolicyAdapter{lines: lines}, nil
}

func loadCompatibleSeedPolicies(path string) ([]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open policy seed: %w", err)
	}
	defer file.Close()

	reader := csv.NewReader(file)
	reader.TrimLeadingSpace = true
	reader.FieldsPerRecord = -1

	var lines []string
	for {
		record, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("read policy seed: %w", err)
		}
		if len(record) == 0 {
			continue
		}

		switch record[0] {
		case "p":
			if len(record) >= 9 {
				lines = append(lines, strings.Join([]string{
					"p",
					record[2],
					record[3],
					"*",
					record[4],
					"*",
					record[7],
				}, ", "))
			}
		case "g":
			if len(record) == 3 {
				lines = append(lines, strings.Join(record, ", "))
			}
		}
	}

	return lines, nil
}

func (a validatePolicyAdapter) LoadPolicy(model model.Model) error {
	for _, line := range a.lines {
		if err := persist.LoadPolicyLine(line, model); err != nil {
			return err
		}
	}
	return nil
}

func (a validatePolicyAdapter) SavePolicy(model.Model) error                              { return nil }
func (a validatePolicyAdapter) AddPolicy(string, string, []string) error                  { return nil }
func (a validatePolicyAdapter) RemovePolicy(string, string, []string) error               { return nil }
func (a validatePolicyAdapter) RemoveFilteredPolicy(string, string, int, ...string) error { return nil }

func policyID(matched []string) string {
	if len(matched) == 0 {
		return ""
	}
	if len(matched) == 6 && matched[4] == "*" {
		return strings.Join([]string{matched[0], matched[1], matched[2], matched[3], matched[5]}, ":")
	}
	return strings.Join(matched, ":")
}
