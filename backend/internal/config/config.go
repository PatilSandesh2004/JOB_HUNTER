// Package config loads gateway settings from environment variables.
package config

import (
	"os"
	"path/filepath"
	"strings"
)

type Config struct {
	// BindAddr defaults to loopback so the UI is not exposed to the network by accident.
	// The Docker image sets it to 0.0.0.0; compose then publishes it on 127.0.0.1 only.
	BindAddr     string
	Port         string
	AIServiceURL string
	FrontendDir  string
	CORSOrigins  []string
	Environment  string
	// APIToken, when set, is required on every /api request except /api/v1/health.
	APIToken string
}

func Load() Config {
	return Config{
		BindAddr:     getenv("BIND_ADDR", "127.0.0.1"),
		Port:         getenv("PORT", "8090"),
		AIServiceURL: strings.TrimRight(getenv("AI_SERVICE_URL", "http://localhost:8000"), "/"),
		FrontendDir:  getenv("FRONTEND_DIR", findFrontendDir()),
		CORSOrigins:  splitList(getenv("CORS_ORIGINS", "http://localhost:8090,http://127.0.0.1:8090")),
		Environment:  getenv("ENVIRONMENT", "development"),
		APIToken:     strings.TrimSpace(os.Getenv("API_TOKEN")),
	}
}

// Addr is the listen address for http.Server.
func (c Config) Addr() string {
	return c.BindAddr + ":" + c.Port
}

func getenv(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func splitList(value string) []string {
	var out []string
	for _, item := range strings.Split(value, ",") {
		if item = strings.TrimSpace(item); item != "" {
			out = append(out, item)
		}
	}
	return out
}

// findFrontendDir supports running from the repo root, from backend/, or from the Docker image.
func findFrontendDir() string {
	for _, candidate := range []string{"frontend", filepath.Join("..", "frontend")} {
		if info, err := os.Stat(filepath.Join(candidate, "index.html")); err == nil && !info.IsDir() {
			return candidate
		}
	}
	return "frontend"
}
