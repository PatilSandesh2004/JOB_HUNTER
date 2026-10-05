package main

import (
	"fmt"
	"log"
	"net/http"

	"jobpilot/backend/clients"
	"jobpilot/backend/config"
	"jobpilot/backend/handlers"
)

// Simple CORS middleware for Go backend
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
	log.Printf("Starting JobPilot Go Backend service on port %s...", cfg.Port)
	log.Printf("Targeting AI Service at: %s", cfg.AIServiceURL)

	aiClient := clients.NewAIClient(cfg.AIServiceURL)
	searchHandler := handlers.NewSearchHandler(aiClient)
	appHandler := handlers.NewApplicationHandler()

	mux := http.NewServeMux()

	// API Routes
	mux.HandleFunc("/api/v1/search/", searchHandler.HandleSearch)
	mux.HandleFunc("/api/v1/applications", appHandler.HandleList)
	mux.HandleFunc("/api/v1/applications/approve", appHandler.HandleApprove)

	// Health check endpoint
	mux.HandleFunc("/api/v1/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"service":"jobpilot-go-backend","status":"online","ai_service_url":"%s"}`, cfg.AIServiceURL)
	})

	// Serve Frontend Static Files
	fs := http.FileServer(http.Dir("./frontend"))
	mux.Handle("/", fs)

	handler := enableCORS(mux)

	addr := fmt.Sprintf(":%s", cfg.Port)
	if err := http.ListenAndServe(addr, handler); err != nil {
		log.Fatalf("Go backend failed to start: %v", err)
	}
}
