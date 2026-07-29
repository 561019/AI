package auth

import (
	"strings"
	"testing"
)

func TestValidateProductionConfigAllowsDevelopmentDefaults(t *testing.T) {
	t.Setenv("GATEWAY_ENV", "development")
	t.Setenv("JWT_SECRET", "")
	t.Setenv("CREDENTIALS_ENCRYPTION_KEY", "")
	t.Setenv("BREAKGLASS_TTL", "")
	t.Setenv("CASDOOR_MOCK_OIDC", "1")
	if err := ValidateProductionConfig(); err != nil {
		t.Fatalf("development config rejected: %v", err)
	}
}

func TestValidateProductionConfigRejectsInvalidSecurityValues(t *testing.T) {
	t.Setenv("GATEWAY_ENV", "production")
	t.Setenv("JWT_SECRET", "too-short")
	t.Setenv("CREDENTIALS_ENCRYPTION_KEY", "also-too-short")
	t.Setenv("BREAKGLASS_TTL", "invalid")
	t.Setenv("CASDOOR_MOCK_OIDC", "1")
	err := ValidateProductionConfig()
	if err == nil {
		t.Fatal("invalid production config was accepted")
	}
	for _, expected := range []string{"JWT_SECRET", "CREDENTIALS_ENCRYPTION_KEY", "BREAKGLASS_TTL", "CASDOOR_MOCK_OIDC"} {
		if !strings.Contains(err.Error(), expected) {
			t.Fatalf("error %q does not mention %s", err, expected)
		}
	}
}

func TestValidateProductionConfigAcceptsValidSecurityValues(t *testing.T) {
	t.Setenv("APP_ENV", "prod")
	t.Setenv("GATEWAY_ENV", "")
	t.Setenv("JWT_SECRET", "0123456789abcdef0123456789abcdef")
	t.Setenv("CREDENTIALS_ENCRYPTION_KEY", "abcdef0123456789abcdef0123456789")
	t.Setenv("BREAKGLASS_TTL", "30")
	t.Setenv("CASDOOR_MOCK_OIDC", "0")
	if err := ValidateProductionConfig(); err != nil {
		t.Fatalf("valid production config rejected: %v", err)
	}
}
