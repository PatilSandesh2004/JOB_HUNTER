// Package config loads gateway settings from environment variables.
package config

import (
	"os"
	"path/filepath"
	"strings"
)

type Config struct {
	Port         string
	AIServiceURL string
	FrontendDir  string
	CORSOrigins  []string
	Environment  string
}

func Load() Config {
	return Config{
		Port:         getenv("PORT", "8090"),
		AIServiceURL: strings.TrimRight(getenv("AI_SERVICE_URL", "http://localhost:8000"), "/"),
		FrontendDir:  getenv("FRONTEND_DIR", findFrontendDir()),
		CORSOrigins:  strings.Split(getenv("CORS_ORIGINS", "*"), ","),
		Environment:  getenv("ENVIRONMENT", "development"),
	}
}

func getenv(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
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
