// Package layerapi exposes registered account facts to the L1 layer interface.
// It contains no user authentication or permission decision logic.
package layerapi

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"os"
	"strings"

	"hanhe.com/account-gateway/internal/organization"
)

type IdentityHandler struct{ store *organization.Store }

func NewIdentityHandler(store *organization.Store) *IdentityHandler {
	return &IdentityHandler{store: store}
}

func (h *IdentityHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || r.URL.Path != "/api/layer/identity-context" || r.Header.Get("X-L1-Caller-Service") != "l1_layer_interface" {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	expected, provided := os.Getenv("L1_INTERFACE_TARGET_SERVICE_SECRET"), r.Header.Get("X-L1-Target-Secret")
	if expected == "" || subtle.ConstantTimeCompare([]byte(expected), []byte(provided)) != 1 {
		w.WriteHeader(http.StatusForbidden)
		return
	}
	var request struct {
		ResponsibleActorID string `json:"responsible_actor_id"`
		TenantID           string `json:"tenant_id"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&request); err != nil || request.ResponsibleActorID == "" || request.TenantID == "" {
		w.WriteHeader(http.StatusBadRequest)
		return
	}
	assignments, err := h.store.ListAssignmentsByTenant(request.TenantID)
	if err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		return
	}
	positions := make([]string, 0)
	for _, item := range assignments {
		if item.PersonID == request.ResponsibleActorID && item.UserID == request.ResponsibleActorID && item.Status == "active" {
			positions = append(positions, item.PositionID)
		}
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"actor_id": strings.TrimSpace(request.ResponsibleActorID), "person_id": strings.TrimSpace(request.ResponsibleActorID), "tenant_id": strings.TrimSpace(request.TenantID), "position_ids": positions})
}
