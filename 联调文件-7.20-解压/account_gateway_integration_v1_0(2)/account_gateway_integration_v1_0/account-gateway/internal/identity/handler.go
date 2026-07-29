package identity

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"hanhe.com/account-gateway/internal/auth"
	"hanhe.com/account-gateway/internal/organization"
)

type Handler struct {
	store *organization.Store
	jwt   *auth.JWTManager
}

func NewHandler(store *organization.Store, jwt *auth.JWTManager) *Handler {
	return &Handler{store: store, jwt: jwt}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet || strings.TrimRight(r.URL.Path, "/") != "/api/identity/context" {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	claims, err := h.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil || claims.IsDigital {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}
	assignments, err := h.store.ListAssignmentsByTenant(claims.OrgID)
	if err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		return
	}
	positions := make([]string, 0)
	for _, assignment := range assignments {
		if assignment.UserID == claims.UserID && assignment.PersonID == claims.UserID && assignment.Status == "active" {
			positions = append(positions, assignment.PositionID)
		}
	}
	managed, err := managedPeople(h.store, claims.UserID, claims.OrgID)
	if err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		return
	}
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		return
	}
	nonce := hex.EncodeToString(buffer)
	token, err := h.jwt.IssueIdentityContext(claims.UserID, claims.OrgID, positions, managed, nonce, time.Minute)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"user_id": claims.UserID, "person_id": claims.UserID, "tenant_id": claims.OrgID,
		"position_ids": positions, "managed_person_ids": managed, "issued_at": time.Now().UTC().Format(time.RFC3339),
		"expires_in_seconds": 60, "nonce": nonce, "identity_context_token": token,
	})
}

func managedPeople(store *organization.Store, managerID, tenantID string) ([]string, error) {
	edges, err := store.ListManagerEdgesByTenant(tenantID)
	if err != nil {
		return nil, err
	}
	children := make(map[string][]string)
	for _, edge := range edges {
		children[edge.ManagerPersonID] = append(children[edge.ManagerPersonID], edge.PersonID)
	}
	result, seen := make([]string, 0), map[string]bool{managerID: true}
	queue := append([]string(nil), children[managerID]...)
	for len(queue) > 0 {
		personID := queue[0]
		queue = queue[1:]
		if seen[personID] {
			continue
		}
		seen[personID] = true
		result = append(result, personID)
		queue = append(queue, children[personID]...)
	}
	return result, nil
}
