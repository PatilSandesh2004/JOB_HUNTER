// Package server implements the JobPilot gateway: it serves the web UI and proxies /api to the AI service.
package server

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"path/filepath"
	"time"

	"jobpilot/backend/internal/config"
)

const (
	maxRequestBytes = 12 << 20 // resume uploads are capped at 10 MB upstream
	upstreamTimeout = 3 * time.Minute
)

type Server struct {
	cfg      config.Config
	logger   *slog.Logger
	upstream *url.URL
	client   *http.Client
}

func New(cfg config.Config, logger *slog.Logger) (*Server, error) {
	upstream, err := url.Parse(cfg.AIServiceURL)
	if err != nil {
		return nil, err
	}
	return &Server{
		cfg:      cfg,
		logger:   logger,
		upstream: upstream,
		client:   &http.Client{Timeout: 5 * time.Second},
	}, nil
}

// Handler returns the fully wrapped HTTP handler.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/v1/health", s.handleHealth)
	mux.Handle("/api/", s.apiProxy())
	mux.Handle("GET /static/", http.StripPrefix("/static/", http.FileServer(http.Dir(s.cfg.FrontendDir))))
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, filepath.Join(s.cfg.FrontendDir, "index.html"))
	})

	var handler http.Handler = mux
	handler = withCORS(s.cfg.CORSOrigins, handler)
	handler = withSecurityHeaders(handler)
	handler = withRecovery(s.logger, handler)
	handler = withRequestLogging(s.logger, handler)
	return handler
}

func (s *Server) apiProxy() http.Handler {
	proxy := httputil.NewSingleHostReverseProxy(s.upstream)
	proxy.Transport = &http.Transport{
		Proxy:                 http.ProxyFromEnvironment,
		ResponseHeaderTimeout: upstreamTimeout,
		IdleConnTimeout:       90 * time.Second,
		MaxIdleConnsPerHost:   16,
	}
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		s.logger.Error("upstream error", "path", r.URL.Path, "error", err)
		writeJSON(w, http.StatusBadGateway, map[string]string{
			"detail": "AI service is unavailable at " + s.cfg.AIServiceURL,
		})
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, maxRequestBytes)
		proxy.ServeHTTP(w, r)
	})
}

type componentStatus struct {
	OK     bool   `json:"ok"`
	URL    string `json:"url,omitempty"`
	Detail string `json:"detail,omitempty"`
}

// handleHealth reports gateway status plus the AI service's own component health.
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
	defer cancel()

	response := map[string]any{
		"service": "jobpilot-gateway",
		"status":  "ok",
		"gateway": componentStatus{OK: true},
	}

	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, s.cfg.AIServiceURL+"/api/v1/health", nil)
	resp, err := s.client.Do(req)
	if err != nil {
		response["status"] = "degraded"
		response["ai_service"] = componentStatus{OK: false, URL: s.cfg.AIServiceURL, Detail: err.Error()}
		writeJSON(w, http.StatusOK, response)
		return
	}
	defer resp.Body.Close()

	var upstream map[string]any
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode != http.StatusOK || json.Unmarshal(body, &upstream) != nil {
		response["status"] = "degraded"
		response["ai_service"] = componentStatus{OK: false, URL: s.cfg.AIServiceURL, Detail: resp.Status}
	} else {
		response["ai_service"] = componentStatus{OK: true, URL: s.cfg.AIServiceURL}
		response["components"] = upstream["components"]
		if upstream["status"] != "ok" {
			response["status"] = "degraded"
		}
	}
	writeJSON(w, http.StatusOK, response)
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
