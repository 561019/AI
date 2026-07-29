package permissionclient

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

type Mode string

const (
	ModeLocal  Mode = "local"
	ModeShadow Mode = "shadow"
	ModeRemote Mode = "remote"
)

type Client struct {
	baseURL    string
	httpClient *http.Client
}

type CheckRequest struct {
	TraceID       string `json:"trace_id"`
	RequestID     string `json:"request_id"`
	ActorID       string `json:"actor_id"`
	Action        string `json:"action"`
	SourceService string `json:"source_service"`
	TargetService string `json:"target_service"`
	DataLabel     string `json:"data_label"`
	DataState     string `json:"data_state"`
	TenantID      string `json:"tenant_id,omitempty"`
	PersonID      string `json:"person_id,omitempty"`
	PositionID    string `json:"position_id,omitempty"`
	ResourceType  string `json:"resource_type,omitempty"`
	ResourceID    string `json:"resource_id,omitempty"`
	DomainID      string `json:"domain_id,omitempty"`
}

type CheckResponse struct {
	TraceID    string `json:"trace_id"`
	RequestID  string `json:"request_id"`
	DecisionID string `json:"decision_id"`
	Allowed    bool   `json:"allowed"`
	Result     string `json:"result"`
	ReasonCode string `json:"reason_code"`
	Reason     string `json:"reason"`
}

func ModeFromEnv() Mode {
	switch Mode(strings.ToLower(strings.TrimSpace(os.Getenv("PERMISSION_MODE")))) {
	case ModeShadow:
		return ModeShadow
	case ModeRemote:
		return ModeRemote
	default:
		// Runtime traffic must fail closed through the permission authority.
		// local and shadow remain explicit migration-tool modes only.
		return ModeRemote
	}
}

func NewFromEnv() *Client {
	timeout := 2 * time.Second
	if raw := strings.TrimSpace(os.Getenv("PERMISSION_TIMEOUT_MS")); raw != "" {
		if milliseconds, err := strconv.Atoi(raw); err == nil && milliseconds > 0 {
			timeout = time.Duration(milliseconds) * time.Millisecond
		}
	}
	baseURL := strings.TrimSpace(os.Getenv("PERMISSION_URL"))
	if baseURL == "" {
		baseURL = "http://127.0.0.1:8001"
	}
	return New(baseURL, timeout)
}

func New(baseURL string, timeout time.Duration) *Client {
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	return &Client{
		baseURL:    strings.TrimRight(strings.TrimSpace(baseURL), "/"),
		httpClient: &http.Client{Timeout: timeout},
	}
}

func (c *Client) Check(ctx context.Context, request CheckRequest) (CheckResponse, int, error) {
	if c == nil || c.httpClient == nil || c.baseURL == "" {
		return CheckResponse{}, 0, errors.New("permission client is not configured")
	}
	body, err := json.Marshal(request)
	if err != nil {
		return CheckResponse{}, 0, fmt.Errorf("marshal permission request: %w", err)
	}
	httpRequest, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+"/api/permission/check",
		bytes.NewReader(body),
	)
	if err != nil {
		return CheckResponse{}, 0, fmt.Errorf("create permission request: %w", err)
	}
	httpRequest.Header.Set("Content-Type", "application/json; charset=utf-8")
	response, err := c.httpClient.Do(httpRequest)
	if err != nil {
		return CheckResponse{}, 0, fmt.Errorf("call permission service: %w", err)
	}
	defer response.Body.Close()
	limited := io.LimitReader(response.Body, 1<<20)
	var result CheckResponse
	if err := json.NewDecoder(limited).Decode(&result); err != nil {
		return CheckResponse{}, response.StatusCode, fmt.Errorf("decode permission response: %w", err)
	}
	return result, response.StatusCode, nil
}

func (c *Client) Forward(ctx context.Context, method, path, rawQuery string, headers http.Header, body io.Reader) (*http.Response, error) {
	if c == nil || c.httpClient == nil || c.baseURL == "" {
		return nil, errors.New("permission client is not configured")
	}
	target, err := url.Parse(c.baseURL + path)
	if err != nil {
		return nil, fmt.Errorf("parse permission URL: %w", err)
	}
	target.RawQuery = rawQuery
	request, err := http.NewRequestWithContext(ctx, method, target.String(), body)
	if err != nil {
		return nil, fmt.Errorf("create permission proxy request: %w", err)
	}
	request.Header = headers.Clone()
	request.Header.Del("Authorization")
	return c.httpClient.Do(request)
}

func HeaderOrGenerated(headers http.Header, name, prefix string) string {
	if value := strings.TrimSpace(headers.Get(name)); value != "" {
		return value
	}
	buffer := make([]byte, 8)
	if _, err := rand.Read(buffer); err != nil {
		return fmt.Sprintf("%s_%d", prefix, time.Now().UnixNano())
	}
	return prefix + "_" + hex.EncodeToString(buffer)
}

func HeaderOrDefault(headers http.Header, name, fallback string) string {
	if value := strings.TrimSpace(headers.Get(name)); value != "" {
		return value
	}
	return fallback
}
