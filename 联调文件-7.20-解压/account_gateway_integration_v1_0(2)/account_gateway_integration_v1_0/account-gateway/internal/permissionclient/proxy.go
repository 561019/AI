package permissionclient

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"

	"hanhe.com/account-gateway/internal/auth"
)

type ManagementProxy struct {
	client *Client
	jwt    *auth.JWTManager
}

func NewManagementProxy(client *Client, jwt *auth.JWTManager) *ManagementProxy {
	return &ManagementProxy{client: client, jwt: jwt}
}

func (p *ManagementProxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	claims, err := p.jwt.ValidateBearer(r.Header.Get("Authorization"))
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}
	headers := r.Header.Clone()
	headers.Set("X-Actor-ID", claims.UserID)
	headers.Set("X-Actor-Roles", strings.Join(claims.RoleList, ","))
	headers.Set("X-Tenant-ID", claims.OrgID)
	if claims.IsBreakglass {
		headers.Set("X-Actor-Roles", strings.Join(append(claims.RoleList, "breakglass"), ","))
	}
	response, err := p.client.Forward(r.Context(), r.Method, r.URL.Path, r.URL.RawQuery, headers, r.Body)
	if err != nil {
		writeProxyError(w, http.StatusServiceUnavailable, "permission_service_unavailable")
		return
	}
	defer response.Body.Close()
	for key, values := range response.Header {
		for _, value := range values {
			w.Header().Add(key, value)
		}
	}
	w.WriteHeader(response.StatusCode)
	_, _ = io.Copy(w, io.LimitReader(response.Body, 8<<20))
}

func writeProxyError(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": code})
}
