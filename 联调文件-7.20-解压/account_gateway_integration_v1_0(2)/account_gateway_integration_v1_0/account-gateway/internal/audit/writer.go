package audit

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"hanhe.com/account-gateway/internal/policy"
)

const validateActionType = "auth.validate"

var ErrWriterClosed = errors.New("audit writer is closed")

type spanContextKey struct{}

type Writer struct {
	db       *sql.DB
	mode     string
	queue    chan auditRecord
	done     chan struct{}
	mu       sync.RWMutex
	closed   atomic.Bool
	enqueued atomic.Int64
	written  atomic.Int64
	dropped  atomic.Int64
	failed   atomic.Int64
}

type WriterStats struct {
	Mode     string `json:"mode"`
	Enqueued int64  `json:"enqueued"`
	Written  int64  `json:"written"`
	Dropped  int64  `json:"dropped"`
	Failed   int64  `json:"failed"`
	Pending  int64  `json:"pending"`
	Closed   bool   `json:"closed"`
}

type auditRecord struct {
	actionType   string
	actorID      string
	resourceType string
	resourceID   string
	decision     policy.Decision
	policyID     string
	headers      http.Header
	traceID      string
	at           time.Time
}

func NewWriter(db *sql.DB) *Writer {
	return newWriter(db, "sync")
}

func NewWriterFromEnv(db *sql.DB) *Writer {
	return newWriter(db, os.Getenv("AUDIT_MODE"))
}

func newWriter(db *sql.DB, mode string) *Writer {
	mode = strings.ToLower(strings.TrimSpace(mode))
	if mode == "" {
		mode = "sync"
	}
	if mode != "sync" && mode != "async" && mode != "off" {
		log.Printf("unsupported AUDIT_MODE=%q; using sync", mode)
		mode = "sync"
	}
	w := &Writer{db: db, mode: mode}
	if mode == "async" {
		w.queue = make(chan auditRecord, 1024)
		w.done = make(chan struct{})
		go w.runAsync()
	}
	return w
}

// ensureSchema recreates the audit_logs table when the backing database file
// has been removed after gateway startup (e.g. by the E2E conftest teardown).
// CREATE TABLE IF NOT EXISTS is idempotent so this is safe to call on every
// write.
func (w *Writer) ensureSchema() error {
	if w == nil || w.db == nil {
		return fmt.Errorf("audit writer is not configured")
	}
	return EnsureSchema(w.db)
}

func WithSpan(ctx context.Context, headers http.Header) context.Context {
	traceID := strings.TrimSpace(headers.Get("X-Trace-ID"))
	if traceID == "" {
		traceID = strings.TrimSpace(headers.Get("X-Request-ID"))
	}
	if traceID == "" {
		return ctx
	}

	return context.WithValue(ctx, spanContextKey{}, traceID)
}

func (w *Writer) LogValidateCall(ctx context.Context, decision policy.Decision, policyID string, headers http.Header) error {
	resourceType := strings.TrimSpace(headers.Get("X-Resource-Type"))
	resourceID := strings.TrimSpace(headers.Get("X-Resource-ID"))
	if resourceID == "" {
		resourceID = resourceIDForType(resourceType)
	}
	return w.LogAction(ctx,
		validateActionType,
		strings.TrimSpace(headers.Get("X-User-ID")),
		resourceType,
		resourceID,
		decision,
		policyID,
		headers,
	)
}

func (w *Writer) LogAction(ctx context.Context, actionType, actorID, resourceType, resourceID string, decision policy.Decision, policyID string, headers http.Header) error {
	if w == nil || w.db == nil {
		return fmt.Errorf("audit writer is not configured")
	}
	w.mu.RLock()
	defer w.mu.RUnlock()
	if w.closed.Load() {
		return ErrWriterClosed
	}
	if w.mode == "off" {
		return nil
	}

	record := auditRecord{
		actionType:   strings.TrimSpace(actionType),
		actorID:      strings.TrimSpace(actorID),
		resourceType: strings.TrimSpace(resourceType),
		resourceID:   strings.TrimSpace(resourceID),
		decision:     decision,
		policyID:     policyID,
		headers:      headers.Clone(),
		traceID:      traceIDFromContext(ctx),
		at:           time.Now().UTC(),
	}
	if w.mode == "async" {
		w.enqueued.Add(1)
		select {
		case w.queue <- record:
		default:
			w.enqueued.Add(-1)
			w.dropped.Add(1)
			log.Printf("audit queue full; dropping action_type=%s actor_id=%s", record.actionType, record.actorID)
		}
		return nil
	}

	if err := w.insertRecord(ctx, record); err != nil {
		w.failed.Add(1)
		return err
	}
	w.written.Add(1)
	return nil
}

func (w *Writer) runAsync() {
	defer close(w.done)
	for record := range w.queue {
		if err := w.insertRecord(context.Background(), record); err != nil {
			w.failed.Add(1)
			log.Printf("audit async write failed: %v", err)
			continue
		}
		w.written.Add(1)
	}
}

func (w *Writer) Stats() WriterStats {
	if w == nil {
		return WriterStats{}
	}
	enqueued := w.enqueued.Load()
	written := w.written.Load()
	failed := w.failed.Load()
	pending := enqueued - written - failed
	if pending < 0 {
		pending = 0
	}
	return WriterStats{
		Mode:     w.mode,
		Enqueued: enqueued,
		Written:  written,
		Dropped:  w.dropped.Load(),
		Failed:   failed,
		Pending:  pending,
		Closed:   w.closed.Load(),
	}
}

func (w *Writer) Flush(timeout time.Duration) bool {
	if w == nil || w.mode != "async" {
		return true
	}
	deadline := time.Now().Add(timeout)
	for {
		if w.Stats().Pending == 0 {
			return true
		}
		if timeout <= 0 || time.Now().After(deadline) {
			return false
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// Close stops accepting new records and drains every record already accepted
// by the async writer before returning. A false result means the caller's
// shutdown deadline elapsed; the worker continues draining in the background.
func (w *Writer) Close(timeout time.Duration) bool {
	if w == nil {
		return true
	}
	w.mu.Lock()
	if !w.closed.Swap(true) && w.mode == "async" {
		close(w.queue)
	}
	done := w.done
	mode := w.mode
	w.mu.Unlock()

	if mode != "async" || done == nil {
		return true
	}
	if timeout <= 0 {
		select {
		case <-done:
			return true
		default:
			return false
		}
	}
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case <-done:
		return true
	case <-timer.C:
		return false
	}
}

func (w *Writer) insertRecord(ctx context.Context, record auditRecord) error {
	contextSnapshot, err := json.Marshal(map[string]string{
		"trace_id":            record.traceID,
		"x_request_id":        strings.TrimSpace(record.headers.Get("X-Request-ID")),
		"x_client_id":         strings.TrimSpace(record.headers.Get("X-Client-ID")),
		"x_resource_owner_id": strings.TrimSpace(record.headers.Get("X-Resource-Owner-ID")),
		"x_resource_id":       strings.TrimSpace(record.headers.Get("X-Resource-ID")),
		"x_tenant_id":         strings.TrimSpace(record.headers.Get("X-Tenant-ID")),
		"x_action":            strings.TrimSpace(record.headers.Get("X-Action")),
	})
	if err != nil {
		return fmt.Errorf("marshal audit context snapshot: %w", err)
	}

	policyDecision := "deny"
	if record.decision.Allow {
		policyDecision = "allow"
	}
	if record.policyID == "" {
		record.policyID = record.decision.PolicyID
	}

	_, err = w.db.ExecContext(ctx, `
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
		record.at.Format(time.RFC3339Nano),
		record.actorID,
		record.actionType,
		record.resourceType,
		record.resourceID,
		policyDecision,
		record.policyID,
		string(contextSnapshot),
		1,
	)
	if err != nil {
		// Self-heal: the audit database file may have been removed after
		// gateway startup (the E2E conftest deletes it between sessions).
		// Recreate the schema and retry the insert once.
		if schemaErr := w.ensureSchema(); schemaErr != nil {
			return fmt.Errorf("insert validate audit log: %w (schema recovery failed: %v)", err, schemaErr)
		}
		_, retryErr := w.db.ExecContext(ctx, `
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
			record.at.Format(time.RFC3339Nano),
			record.actorID,
			record.actionType,
			record.resourceType,
			record.resourceID,
			policyDecision,
			record.policyID,
			string(contextSnapshot),
			1,
		)
		if retryErr != nil {
			return fmt.Errorf("insert validate audit log after schema recovery: %w", errors.Join(err, retryErr))
		}
	}

	return nil
}

func traceIDFromContext(ctx context.Context) string {
	traceID, _ := ctx.Value(spanContextKey{}).(string)
	return traceID
}

func resourceIDForType(resourceType string) string {
	if resourceType == "" {
		return "unknown_resource"
	}
	return resourceType + "_resource_placeholder"
}
