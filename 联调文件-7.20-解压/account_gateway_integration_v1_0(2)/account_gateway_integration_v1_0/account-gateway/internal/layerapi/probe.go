package layerapi

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"os"
)

// PermissionProbeHandler is a deliberately narrow L1 test target. It proves
// that the internal channel forwarded a request after a permission decision;
// it never evaluates or stores authorization data.
type PermissionProbeHandler struct{}

func NewPermissionProbeHandler() *PermissionProbeHandler { return &PermissionProbeHandler{} }

func (h *PermissionProbeHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || r.URL.Path != "/api/layer/permission-probe" || r.Header.Get("X-L1-Caller-Service") != "l1_layer_interface" {
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
		Action             string `json:"action"`
		ResourceType       string `json:"resource_type"`
		ResourceID         string `json:"resource_id"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&request); err != nil || request.ResponsibleActorID == "" || request.TenantID == "" || request.Action == "" || request.ResourceType == "" {
		w.WriteHeader(http.StatusBadRequest)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]string{
		"actor_id": request.ResponsibleActorID, "tenant_id": request.TenantID,
		"action": request.Action, "resource_type": request.ResourceType, "resource_id": request.ResourceID,
	})
}
