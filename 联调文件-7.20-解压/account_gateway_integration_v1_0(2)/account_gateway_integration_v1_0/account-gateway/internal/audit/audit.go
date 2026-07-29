package audit

import (
	"database/sql"
	"embed"
	"fmt"
	"os"
	"sort"
	"strings"
)

//go:embed migrations/*.sql
var migrationFiles embed.FS

// EnsureSchema creates the audit schema and applies embedded migrations.
func EnsureSchema(db *sql.DB) error {
	if sqliteWALEnabled() {
		if _, err := db.Exec("PRAGMA journal_mode=WAL"); err != nil {
			return fmt.Errorf("enable sqlite wal: %w", err)
		}
	} else {
		if _, err := db.Exec("PRAGMA journal_mode=DELETE"); err != nil {
			return fmt.Errorf("set sqlite delete journal mode: %w", err)
		}
	}
	if _, err := db.Exec("PRAGMA busy_timeout=5000"); err != nil {
		return fmt.Errorf("set sqlite busy timeout: %w", err)
	}

	entries, err := migrationFiles.ReadDir("migrations")
	if err != nil {
		return fmt.Errorf("read audit migrations: %w", err)
	}

	sort.Slice(entries, func(i, j int) bool {
		return entries[i].Name() < entries[j].Name()
	})

	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}

		path := "migrations/" + entry.Name()
		migration, err := migrationFiles.ReadFile(path)
		if err != nil {
			return fmt.Errorf("read audit migration %s: %w", path, err)
		}

		if _, err := db.Exec(string(migration)); err != nil {
			return fmt.Errorf("apply audit migration %s: %w", path, err)
		}
	}

	for _, column := range []struct {
		table      string
		name       string
		definition string
	}{
		{"breakglass_state", "reason", "TEXT"},
		{"breakglass_state", "ticket_id", "TEXT"},
		{"breakglass_state", "activated_by", "TEXT"},
		{"breakglass_state", "approval_required", "INTEGER NOT NULL DEFAULT 0"},
		{"breakglass_state", "requested_by", "TEXT"},
		{"breakglass_state", "requested_at", "TEXT"},
		{"breakglass_state", "approved_by", "TEXT"},
		{"breakglass_state", "approved_at", "TEXT"},
		{"digital_employees", "status", "TEXT NOT NULL DEFAULT 'active'"},
		{"digital_employees", "disabled_at", "TEXT"},
		{"digital_employees", "token_version", "INTEGER NOT NULL DEFAULT 1"},
		{"digital_employees", "execution_mode", "TEXT NOT NULL DEFAULT 'auto'"},
		{"digital_employees", "tenant_id", "TEXT"},
		{"digital_employees", "expires_at", "TEXT"},
		{"approvals", "approver_user_id", "TEXT"},
		{"approvals", "approval_type", "TEXT NOT NULL DEFAULT 'permission_grant'"},
		{"approvals", "tenant_id", "TEXT NOT NULL DEFAULT ''"},
		{"approvals", "template_id", "TEXT"},
		{"approvals", "current_stage", "INTEGER NOT NULL DEFAULT 0"},
		{"approval_templates", "stages_json", "TEXT NOT NULL DEFAULT '[]'"},
		{"runtime_policies", "tenant_id", "TEXT NOT NULL DEFAULT '*'"},
		{"credentials", "tenant_id", "TEXT"},
		{"credentials", "expires_at", "TEXT"},
		{"data_records", "initial_person_ids", "TEXT NOT NULL DEFAULT '[]'"},
		{"data_records", "initial_user_ids", "TEXT NOT NULL DEFAULT '[]'"},
		{"resources", "asset_pool", "TEXT"},
		{"resources", "locked_by", "TEXT"},
		{"resources", "locked_at", "TEXT"},
		{"data_records", "asset_pool", "TEXT"},
		{"data_records", "locked_by", "TEXT"},
		{"data_records", "locked_at", "TEXT"},
	} {
		if err := ensureColumn(db, column.table, column.name, column.definition); err != nil {
			return err
		}
	}

	if _, err := db.Exec("CREATE INDEX IF NOT EXISTS idx_runtime_policies_tenant_id ON runtime_policies (tenant_id)"); err != nil {
		return fmt.Errorf("create runtime_policies tenant index: %w", err)
	}
	if _, err := db.Exec("DROP INDEX IF EXISTS idx_person_position_active_person"); err != nil {
		return fmt.Errorf("drop legacy person active assignment index: %w", err)
	}
	if _, err := db.Exec("CREATE UNIQUE INDEX IF NOT EXISTS idx_person_position_active_position ON person_position_assignments (position_id) WHERE status = 'active'"); err != nil {
		return fmt.Errorf("create active position assignment index: %w", err)
	}

	return nil
}

func sqliteWALEnabled() bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv("SQLITE_JOURNAL_MODE")))
	return value == "wal"
}

func ensureColumn(db *sql.DB, table, name, definition string) error {
	rows, err := db.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		return fmt.Errorf("inspect %s columns: %w", table, err)
	}
	defer rows.Close()

	for rows.Next() {
		var (
			cid        int
			columnName string
			columnType string
			notNull    int
			defaultVal sql.NullString
			pk         int
		)
		if err := rows.Scan(&cid, &columnName, &columnType, &notNull, &defaultVal, &pk); err != nil {
			return fmt.Errorf("scan %s column info: %w", table, err)
		}
		if columnName == name {
			return nil
		}
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("iterate %s columns: %w", table, err)
	}

	if _, err := db.Exec("ALTER TABLE " + table + " ADD COLUMN " + name + " " + strings.TrimSpace(definition)); err != nil {
		return fmt.Errorf("add %s.%s: %w", table, name, err)
	}
	return nil
}
