package auth

import (
	"errors"
	"net/url"
	"os"
	"strings"

	"github.com/casdoor/casdoor-go-sdk/casdoorsdk"
)

type OIDCClient struct {
	endpoint     string
	clientID     string
	clientSecret string
	certificate  string
	organization string
	application  string
	redirectURI  string
	mock         bool
}

type UserIdentity struct {
	UserID   string
	OrgID    string
	RoleList []string
}

func NewOIDCClientFromEnv() *OIDCClient {
	client := &OIDCClient{
		endpoint:     envOrDefault("CASDOOR_ENDPOINT", "http://127.0.0.1:8000"),
		clientID:     envOrDefault("CASDOOR_CLIENT_ID", "account-gateway"),
		clientSecret: os.Getenv("CASDOOR_CLIENT_SECRET"),
		certificate:  os.Getenv("CASDOOR_CERTIFICATE"),
		organization: envOrDefault("CASDOOR_ORGANIZATION", "built-in"),
		application:  envOrDefault("CASDOOR_APPLICATION", "account-gateway"),
		redirectURI:  envOrDefault("CASDOOR_REDIRECT_URI", "http://127.0.0.1:8080/callback"),
		mock:         os.Getenv("CASDOOR_MOCK_OIDC") == "1",
	}
	if !client.mock {
		casdoorsdk.InitConfig(
			client.endpoint,
			client.clientID,
			client.clientSecret,
			client.certificate,
			client.organization,
			client.application,
		)
	}
	return client
}

func (c *OIDCClient) LoginURL(state string) string {
	values := url.Values{}
	values.Set("client_id", c.clientID)
	values.Set("response_type", "code")
	values.Set("redirect_uri", c.redirectURI)
	values.Set("scope", "read")
	values.Set("state", state)
	return strings.TrimRight(c.endpoint, "/") + "/login/oauth/authorize?" + values.Encode()
}

func (c *OIDCClient) ExchangeCode(code, state string) (UserIdentity, error) {
	if strings.TrimSpace(code) == "" {
		return UserIdentity{}, errors.New("missing authorization code")
	}
	if c.mock {
		return UserIdentity{
			UserID:   envOrDefault("CASDOOR_MOCK_USER_ID", "casdoor-e2e-user"),
			OrgID:    envOrDefault("CASDOOR_MOCK_ORG_ID", "casdoor-e2e-org"),
			RoleList: mockRoles(),
		}, nil
	}

	token, err := casdoorsdk.GetOAuthToken(code, state)
	if err != nil {
		return UserIdentity{}, err
	}
	claims, err := casdoorsdk.ParseJwtToken(token.AccessToken)
	if err != nil {
		return UserIdentity{}, err
	}

	roles := rolesFromType(claims.Type)
	return UserIdentity{
		UserID:   claims.Name,
		OrgID:    claims.Owner,
		RoleList: roles,
	}, nil
}

func rolesFromType(userType string) []string {
	role := strings.TrimSpace(userType)
	if role == "" {
		return []string{"user"}
	}
	return []string{role}
}

func envOrDefault(key, fallback string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value
}

func mockRoles() []string {
	configured := strings.TrimSpace(os.Getenv("CASDOOR_MOCK_ROLE_LIST"))
	if configured == "" {
		return []string{"admin", "operator"}
	}
	parts := strings.Split(configured, ",")
	roles := make([]string, 0, len(parts))
	for _, part := range parts {
		role := strings.TrimSpace(part)
		if role != "" {
			roles = append(roles, role)
		}
	}
	return roles
}
