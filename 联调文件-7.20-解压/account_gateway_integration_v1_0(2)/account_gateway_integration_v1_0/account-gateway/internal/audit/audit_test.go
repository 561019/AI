package audit

import (
	"context"
	"database/sql"
	"errors"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"hanhe.com/account-gateway/internal/policy"

	_ "github.com/mattn/go-sqlite3"
)

func openTestDB(t *testing.T) *sql.DB {
	t.Helper()

	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	t.Cleanup(func() {
		if err := db.Close(); err != nil {
			t.Errorf("close sqlite: %v", err)
		}
	})

	if err := EnsureSchema(db); err != nil {
		if strings.Contains(err.Error(), "go-sqlite3 requires cgo") {
			t.Skipf("sqlite tests require cgo: %v", err)
		}
		t.Fatalf("ensure schema: %v", err)
	}

	return db
}

func insertAuditLog(t *testing.T, db *sql.DB) int64 {
	t.Helper()

	result, err := db.Exec(`
        INSERT INTO audit_logs (
            ts,
            actor_id,
            action_type,
            resource_type,
            resource_id,
            policy_decision,
            policy_id,
            context_snapshot,
            version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
		"2026-06-30T00:00:00Z",
		"actor-123",
		"account.login",
		"account",
		"account-456",
		"allow",
		"policy-789",
		`{"ip":"127.0.0.1"}`,
		1,
	)
	if err != nil {
		t.Fatalf("insert audit log: %v", err)
	}

	id, err := result.LastInsertId()
	if err != nil {
		t.Fatalf("last insert id: %v", err)
	}

	return id
}

func TestAuditLogInsertAndRead(t *testing.T) {
	db := openTestDB(t)
	id := insertAuditLog(t, db)

	var got struct {
		id              int64
		ts              string
		actorID         string
		actionType      string
		resourceType    string
		resourceID      string
		policyDecision  string
		policyID        string
		contextSnapshot string
		version         int
	}

	err := db.QueryRow(`
        SELECT
            id,
            ts,
            actor_id,
            action_type,
            resource_type,
            resource_id,
            policy_decision,
            policy_id,
            context_snapshot,
            version
        FROM audit_logs
        WHERE id = ?
    `, id).Scan(
		&got.id,
		&got.ts,
		&got.actorID,
		&got.actionType,
		&got.resourceType,
		&got.resourceID,
		&got.policyDecision,
		&got.policyID,
		&got.contextSnapshot,
		&got.version,
	)
	if err != nil {
		t.Fatalf("read audit log: %v", err)
	}

	if got.id != id ||
		got.ts != "2026-06-30T00:00:00Z" ||
		got.actorID != "actor-123" ||
		got.actionType != "account.login" ||
		got.resourceType != "account" ||
		got.resourceID != "account-456" ||
		got.policyDecision != "allow" ||
		got.policyID != "policy-789" ||
		got.contextSnapshot != `{"ip":"127.0.0.1"}` ||
		got.version != 1 {
		t.Fatalf("unexpected audit log: %+v", got)
	}
}

func TestAuditLogRejectsUpdate(t *testing.T) {
	db := openTestDB(t)
	id := insertAuditLog(t, db)

	_, err := db.Exec(`UPDATE audit_logs SET action_type = ? WHERE id = ?`, "account.logout", id)
	if err == nil {
		t.Fatal("expected update to be rejected")
	}
}

func TestAuditLogRejectsDelete(t *testing.T) {
	db := openTestDB(t)
	id := insertAuditLog(t, db)

	_, err := db.Exec(`DELETE FROM audit_logs WHERE id = ?`, id)
	if err == nil {
		t.Fatal("expected delete to be rejected")
	}
}

func TestEnsureSchemaIsIdempotent(t *testing.T) {
	db := openTestDB(t)

	if err := EnsureSchema(db); err != nil {
		t.Fatalf("ensure schema again: %v", err)
	}
}

func TestWriterStatsForSyncAndAsync(t *testing.T) {
	db := openTestDB(t)
	headers := http.Header{
		"X-Request-ID":        []string{"audit-stats"},
		"X-User-ID":           []string{"actor-1"},
		"X-Resource-Type":     []string{"tool"},
		"X-Resource-ID":       []string{"tool-1"},
		"X-Resource-Owner-ID": []string{"actor-1"},
		"X-Action":            []string{"use"},
	}

	syncWriter := NewWriter(db)
	if err := syncWriter.LogAction(context.Background(), "test.sync", "actor-1", "tool", "tool-1", policy.Decision{Allow: true, PolicyID: "policy-sync"}, "policy-sync", headers); err != nil {
		t.Fatalf("sync log action: %v", err)
	}
	syncStats := syncWriter.Stats()
	if syncStats.Mode != "sync" || syncStats.Written != 1 || syncStats.Failed != 0 || syncStats.Dropped != 0 || syncStats.Pending != 0 {
		t.Fatalf("unexpected sync stats: %+v", syncStats)
	}

	asyncWriter := newWriter(db, "async")
	defer asyncWriter.Close(time.Second)
	if err := asyncWriter.LogAction(context.Background(), "test.async", "actor-2", "tool", "tool-2", policy.Decision{Allow: true, PolicyID: "policy-async"}, "policy-async", headers); err != nil {
		t.Fatalf("async log action: %v", err)
	}
	if !asyncWriter.Flush(2 * time.Second) {
		t.Fatalf("async writer did not flush: %+v", asyncWriter.Stats())
	}
	asyncStats := asyncWriter.Stats()
	if asyncStats.Mode != "async" || asyncStats.Enqueued != 1 || asyncStats.Written != 1 || asyncStats.Failed != 0 || asyncStats.Dropped != 0 || asyncStats.Pending != 0 {
		t.Fatalf("unexpected async stats: %+v", asyncStats)
	}
}

func TestAsyncWriterCloseDrainsAndRejectsNewRecords(t *testing.T) {
	db := openTestDB(t)
	writer := newWriter(db, "async")
	headers := http.Header{"X-Tenant-ID": []string{"org-1"}}

	for i := 0; i < 50; i++ {
		if err := writer.LogAction(context.Background(), "test.close", "actor", "tool", "tool", policy.Decision{Allow: true}, "policy", headers); err != nil {
			t.Fatalf("enqueue record %d: %v", i, err)
		}
	}
	if !writer.Close(2 * time.Second) {
		t.Fatalf("async writer did not close: %+v", writer.Stats())
	}
	stats := writer.Stats()
	if !stats.Closed || stats.Enqueued != 50 || stats.Written != 50 || stats.Pending != 0 || stats.Failed != 0 {
		t.Fatalf("unexpected closed stats: %+v", stats)
	}
	if err := writer.LogAction(context.Background(), "test.after_close", "actor", "tool", "tool", policy.Decision{Allow: true}, "policy", headers); !errors.Is(err, ErrWriterClosed) {
		t.Fatalf("write after close error=%v", err)
	}
	if !writer.Close(time.Second) {
		t.Fatal("idempotent close failed")
	}
}

func TestUnsupportedAuditModeFallsBackToSync(t *testing.T) {
	db := openTestDB(t)
	writer := newWriter(db, "not-a-mode")
	if writer.Stats().Mode != "sync" {
		t.Fatalf("mode=%q want sync", writer.Stats().Mode)
	}
	if err := writer.LogAction(context.Background(), "test.mode", "actor", "tool", "tool", policy.Decision{Allow: true}, "policy", nil); err != nil {
		t.Fatalf("sync fallback write: %v", err)
	}
	if writer.Stats().Written != 1 {
		t.Fatalf("stats=%+v", writer.Stats())
	}
}

func TestAsyncWriterConcurrentCloseDoesNotPanic(t *testing.T) {
	db := openTestDB(t)
	writer := newWriter(db, "async")
	start := make(chan struct{})
	var callers sync.WaitGroup
	for i := 0; i < 100; i++ {
		callers.Add(1)
		go func() {
			defer callers.Done()
			<-start
			err := writer.LogAction(context.Background(), "test.concurrent", "actor", "tool", "tool", policy.Decision{Allow: true}, "policy", nil)
			if err != nil && !errors.Is(err, ErrWriterClosed) {
				t.Errorf("concurrent write: %v", err)
			}
		}()
	}
	close(start)
	if !writer.Close(2 * time.Second) {
		t.Fatalf("close timed out: %+v", writer.Stats())
	}
	callers.Wait()
	if writer.Stats().Pending != 0 {
		t.Fatalf("pending records after close: %+v", writer.Stats())
	}
}
