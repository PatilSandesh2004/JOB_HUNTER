package server

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"jobpilot/backend/internal/config"
)

func newTestServer(t *testing.T, upstreamURL string) http.Handler {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "index.html"), []byte("<h1>JobPilot</h1>"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "styles.css"), []byte("body{}"), 0o644); err != nil {
		t.Fatal(err)
	}
	srv, err := New(config.Config{AIServiceURL: upstreamURL, FrontendDir: dir, CORSOrigins: []string{"*"}},
		slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	return srv.Handler()
}

func TestProxiesAPIRequests(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"path": r.URL.Path, "query": r.URL.RawQuery, "body": string(body)})
	}))
	defer upstream.Close()

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/search?x=1", strings.NewReader(`{"roles":["a"]}`))
	newTestServer(t, upstream.URL).ServeHTTP(rec, req)

	var got map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatalf("decode: %v (%s)", err, rec.Body.String())
	}
	if got["path"] != "/api/v1/search" || got["query"] != "x=1" || got["body"] != `{"roles":["a"]}` {
		t.Fatalf("unexpected proxied request: %+v", got)
	}
	if rec.Header().Get("X-Request-ID") == "" {
		t.Fatal("missing X-Request-ID")
	}
}

func TestUpstreamDownReturnsJSON502(t *testing.T) {
	rec := httptest.NewRecorder()
	newTestServer(t, "http://127.0.0.1:1").ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/jobs", nil))
	if rec.Code != http.StatusBadGateway || !strings.Contains(rec.Body.String(), "unavailable") {
		t.Fatalf("got %d %s", rec.Code, rec.Body.String())
	}
}

func TestHealthAggregatesUpstream(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"status":"ok","components":{"database":{"ok":true}}}`))
	}))
	defer upstream.Close()

	rec := httptest.NewRecorder()
	newTestServer(t, upstream.URL).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/health", nil))
	var got map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &got)
	if got["status"] != "ok" || got["components"] == nil {
		t.Fatalf("unexpected health: %s", rec.Body.String())
	}

	rec = httptest.NewRecorder()
	newTestServer(t, "http://127.0.0.1:1").ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/health", nil))
	_ = json.Unmarshal(rec.Body.Bytes(), &got)
	if got["status"] != "degraded" {
		t.Fatalf("expected degraded, got %s", rec.Body.String())
	}
}

func TestServesFrontend(t *testing.T) {
	h := newTestServer(t, "http://127.0.0.1:1")
	for path, want := range map[string]string{"/": "JobPilot", "/static/styles.css": "body{}"} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), want) {
			t.Errorf("%s: got %d %q", path, rec.Code, rec.Body.String())
		}
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/nope", nil))
	if rec.Code != http.StatusNotFound {
		t.Errorf("/nope: got %d", rec.Code)
	}
}
