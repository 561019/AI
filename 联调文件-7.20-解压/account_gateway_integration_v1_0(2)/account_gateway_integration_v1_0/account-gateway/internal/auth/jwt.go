package auth

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

const defaultJWTSecret = "change-me"

type JWTManager struct {
	secret []byte
	ttl    time.Duration
}

type Claims struct {
	UserID       string   `json:"user_id"`
	OrgID        string   `json:"org_id"`
	RoleList     []string `json:"role_list"`
	IsDigital    bool     `json:"is_digital,omitempty"`
	ParentUserID string   `json:"parent_user_id,omitempty"`
	TokenVersion int      `json:"token_version,omitempty"`
	IsBreakglass bool     `json:"is_breakglass,omitempty"`
	IssuedAt     int64    `json:"iat,omitempty"`
	Expires      int64    `json:"exp"`
}

// IdentityContext is deliberately narrower than a login JWT.  It carries only
// the current identity facts needed by the L1 channel and expires after one use.
type IdentityContext struct {
	UserID           string   `json:"user_id"`
	TenantID         string   `json:"tenant_id"`
	PositionIDs      []string `json:"position_ids"`
	ManagedPersonIDs []string `json:"managed_person_ids"`
	IssuedAt         int64    `json:"iat"`
	Expires          int64    `json:"exp"`
	Nonce            string   `json:"nonce"`
}

type IssueOption func(*Claims)

func WithDigitalEmployee(parentUserID string) IssueOption {
	return func(claims *Claims) {
		claims.IsDigital = true
		claims.ParentUserID = strings.TrimSpace(parentUserID)
	}
}

func WithTokenVersion(version int) IssueOption {
	return func(claims *Claims) {
		if version > 0 {
			claims.TokenVersion = version
		}
	}
}

func WithBreakglass() IssueOption {
	return func(claims *Claims) {
		claims.IsBreakglass = true
	}
}

func NewJWTManagerFromEnv() *JWTManager {
	secret := os.Getenv("JWT_SECRET")
	if secret == "" {
		secret = defaultJWTSecret
	}
	return NewJWTManager(secret, time.Hour)
}

func NewJWTManager(secret string, ttl time.Duration) *JWTManager {
	if secret == "" {
		secret = defaultJWTSecret
	}
	if ttl <= 0 {
		ttl = time.Hour
	}
	return &JWTManager{secret: []byte(secret), ttl: ttl}
}

func ValidateProductionConfig() error {
	if !productionMode() {
		return nil
	}
	var invalid []string
	jwtSecret := strings.TrimSpace(os.Getenv("JWT_SECRET"))
	if jwtSecret == "" || jwtSecret == defaultJWTSecret || len([]byte(jwtSecret)) < 32 {
		invalid = append(invalid, "JWT_SECRET (at least 32 bytes and not the default)")
	}
	if len([]byte(os.Getenv("CREDENTIALS_ENCRYPTION_KEY"))) != 32 {
		invalid = append(invalid, "CREDENTIALS_ENCRYPTION_KEY (exactly 32 bytes)")
	}
	ttl, err := strconv.Atoi(strings.TrimSpace(os.Getenv("BREAKGLASS_TTL")))
	if err != nil || ttl <= 0 {
		invalid = append(invalid, "BREAKGLASS_TTL (positive minutes)")
	}
	if strings.TrimSpace(os.Getenv("CASDOOR_MOCK_OIDC")) == "1" {
		invalid = append(invalid, "CASDOOR_MOCK_OIDC (must be disabled)")
	}
	if len(invalid) > 0 {
		return fmt.Errorf("production mode requires valid secure configuration: %s", strings.Join(invalid, ", "))
	}
	return nil
}

func productionMode() bool {
	mode := strings.ToLower(strings.TrimSpace(os.Getenv("GATEWAY_ENV")))
	if mode == "" {
		mode = strings.ToLower(strings.TrimSpace(os.Getenv("APP_ENV")))
	}
	return mode == "production" || mode == "prod"
}

func (m *JWTManager) Issue(userID, orgID string, roleList []string, opts ...IssueOption) (string, error) {
	now := time.Now().Unix()
	claims := Claims{
		UserID:   strings.TrimSpace(userID),
		OrgID:    strings.TrimSpace(orgID),
		RoleList: roleList,
		IssuedAt: now,
		Expires:  now + int64(m.ttl.Seconds()),
	}
	for _, opt := range opts {
		if opt != nil {
			opt(&claims)
		}
	}
	if err := claims.ValidAt(time.Now()); err != nil {
		return "", err
	}

	header, err := base64URLJSON(map[string]string{"alg": "HS256", "typ": "JWT"})
	if err != nil {
		return "", err
	}
	payload, err := base64URLJSON(claims)
	if err != nil {
		return "", err
	}
	signingInput := header + "." + payload
	return signingInput + "." + m.sign(signingInput), nil
}

func (m *JWTManager) IssueDigital(userID, orgID string, roleList []string, parentUserID string) (string, error) {
	return m.Issue(userID, orgID, roleList, WithDigitalEmployee(parentUserID))
}

func (m *JWTManager) IssueDigitalWithVersion(userID, orgID string, roleList []string, parentUserID string, tokenVersion int) (string, error) {
	return m.Issue(userID, orgID, roleList, WithDigitalEmployee(parentUserID), WithTokenVersion(tokenVersion))
}

func (m *JWTManager) IssueBreakglass(userID, orgID string, roleList []string) (string, error) {
	return m.Issue(userID, orgID, roleList, WithBreakglass())
}

func (m *JWTManager) IssueBreakglassWithTTL(userID, orgID string, roleList []string, ttl time.Duration) (string, error) {
	manager := &JWTManager{secret: m.secret, ttl: ttl}
	return manager.IssueBreakglass(userID, orgID, roleList)
}

func (m *JWTManager) IssueIdentityContext(userID, tenantID string, positionIDs, managedPersonIDs []string, nonce string, ttl time.Duration) (string, error) {
	if userID == "" || tenantID == "" || nonce == "" || ttl <= 0 {
		return "", errors.New("invalid identity context")
	}
	now := time.Now().Unix()
	context := IdentityContext{UserID: userID, TenantID: tenantID, PositionIDs: positionIDs, ManagedPersonIDs: managedPersonIDs, IssuedAt: now, Expires: now + int64(ttl.Seconds()), Nonce: nonce}
	header, err := base64URLJSON(map[string]string{"alg": "HS256", "typ": "IdentityContext"})
	if err != nil {
		return "", err
	}
	payload, err := base64URLJSON(context)
	if err != nil {
		return "", err
	}
	signingInput := header + "." + payload
	return signingInput + "." + m.sign(signingInput), nil
}

func (m *JWTManager) ValidateBearer(authorization string) (Claims, error) {
	token, ok := strings.CutPrefix(authorization, "Bearer ")
	if !ok || strings.TrimSpace(token) == "" {
		return Claims{}, errors.New("missing bearer token")
	}
	return m.Validate(token)
}

func (m *JWTManager) Validate(token string) (Claims, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return Claims{}, errors.New("malformed jwt")
	}

	signingInput := parts[0] + "." + parts[1]
	signature, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		return Claims{}, err
	}
	if !hmac.Equal(signature, m.signature(signingInput)) {
		return Claims{}, errors.New("invalid jwt signature")
	}

	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return Claims{}, err
	}
	var claims Claims
	if err := json.Unmarshal(payload, &claims); err != nil {
		return Claims{}, err
	}
	if err := claims.ValidAt(time.Now()); err != nil {
		return Claims{}, err
	}
	return claims, nil
}

func (c Claims) ValidAt(now time.Time) error {
	if c.UserID == "" {
		return errors.New("missing user_id")
	}
	if c.OrgID == "" {
		return errors.New("missing org_id")
	}
	if len(c.RoleList) == 0 {
		return errors.New("missing role_list")
	}
	if c.Expires == 0 || now.Unix() >= c.Expires {
		return errors.New("expired jwt")
	}
	return nil
}

func (m *JWTManager) sign(signingInput string) string {
	return base64.RawURLEncoding.EncodeToString(m.signature(signingInput))
}

func (m *JWTManager) signature(signingInput string) []byte {
	mac := hmac.New(sha256.New, m.secret)
	_, _ = mac.Write([]byte(signingInput))
	return mac.Sum(nil)
}

func base64URLJSON(value interface{}) (string, error) {
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(encoded), nil
}
