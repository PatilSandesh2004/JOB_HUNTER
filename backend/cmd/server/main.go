// Command server runs the JobPilot HTTP gateway.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"jobpilot/backend/internal/config"
	"jobpilot/backend/internal/server"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))
	cfg := config.Load()

	srv, err := server.New(cfg, logger)
	if err != nil {
		logger.Error("invalid configuration", "error", err)
		os.Exit(1)
	}

	httpServer := &http.Server{
		Addr:              cfg.Addr(),
		Handler:           srv.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		WriteTimeout:      4 * time.Minute, // searches and form filling can take a while
		IdleTimeout:       2 * time.Minute,
	}

	go func() {
		logger.Info("gateway listening", "addr", httpServer.Addr, "ai_service", cfg.AIServiceURL, "frontend", cfg.FrontendDir)
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("server failed", "error", err)
			os.Exit(1)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	<-stop

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	logger.Info("shutting down")
	if err := httpServer.Shutdown(ctx); err != nil {
		logger.Error("graceful shutdown failed", "error", err)
	}
}
