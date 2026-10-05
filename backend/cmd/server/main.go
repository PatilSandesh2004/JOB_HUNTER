package main

import (
	"fmt"
	"log"
	"net/http"

	"jobpilot/backend/config"
	"jobpilot/backend/internal/clients"
	"jobpilot/backend/internal/handlers"
	"jobpilot/backend/internal/repository"
)

func enableCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func main() {
	cfg := config.LoadConfig()
	log.Printf("[Modular Go Server] Starting on port %s...", cfg.Port)
	log.Printf("[Modular Go Server] AI Microservice URL: %s", cfg.AIServiceURL)

	aiClient := clients.NewAIClient(cfg.AIServiceURL)
	appRepo := repository.NewInMemoryApplicationRepo()
	router := handlers.NewRouterHandler(aiClient, appRepo)

	mux := http.NewServeMux()

	// REST API Endpoints
	mux.HandleFunc("/api/v1/search/", router.HandleSearch)
	mux.HandleFunc("/api/v1/applications", router.HandleListApplications)
	mux.HandleFunc("/api/v1/applications/approve", router.HandleApproveApplication)
	mux.HandleFunc("/api/v1/applications/auto-apply", router.HandleAutoApply)
	mux.HandleFunc("/api/v1/health", router.HandleHealth)

	// Serve Frontend Static Web App
	fs := http.FileServer(http.Dir("./frontend"))
	mux.Handle("/", fs)

	handler := enableCORS(mux)

	addr := fmt.Sprintf(":%s", cfg.Port)
	if err := http.ListenAndServe(addr, handler); err != nil {
		log.Fatalf("Server launch failed: %v", err)
	}
}
