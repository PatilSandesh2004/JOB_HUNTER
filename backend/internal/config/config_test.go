package config

import "testing"

func TestLoadDefaultsToLoopback(t *testing.T) {
	t.Setenv("BIND_ADDR", "")
	t.Setenv("PORT", "")
	t.Setenv("API_TOKEN", "")
	t.Setenv("CORS_ORIGINS", "")
	cfg := Load()
	if cfg.Addr() != "127.0.0.1:8090" {
		t.Fatalf("Addr = %q", cfg.Addr())
	}
	if cfg.APIToken != "" || len(cfg.CORSOrigins) != 2 {
		t.Fatalf("unexpected defaults: %+v", cfg)
	}
}

func TestLoadFromEnvironment(t *testing.T) {
	t.Setenv("BIND_ADDR", "0.0.0.0")
	t.Setenv("PORT", "9000")
	t.Setenv("API_TOKEN", " tok ")
	t.Setenv("CORS_ORIGINS", "http://a, ,http://b")
	cfg := Load()
	if cfg.Addr() != "0.0.0.0:9000" || cfg.APIToken != "tok" || len(cfg.CORSOrigins) != 2 {
		t.Fatalf("unexpected config: %+v", cfg)
	}
}
