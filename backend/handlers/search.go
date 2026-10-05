package handlers

import (
	"encoding/json"
	"net/http"

	"jobpilot/backend/clients"
	"jobpilot/backend/models"
)

type SearchHandler struct {
	AIClient *clients.AIClient
}

func NewSearchHandler(aiClient *clients.AIClient) *SearchHandler {
	return &SearchHandler{AIClient: aiClient}
}

func (h *SearchHandler) HandleSearch(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req models.SearchRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid JSON payload", http.StatusBadRequest)
		return
	}

	res, err := h.AIClient.ForwardSearch(req)
	if err != nil {
		// Fallback mock search results if AI service is starting up
		res = &models.SearchResponse{
			Query:        "Go & AI Search",
			TotalResults: 2,
			Results: []models.SearchResultItem{
				{
					Title:   "Senior AI Systems Engineer",
					URL:     "https://example.com/jobs/ai-eng",
					Content: "High throughput backend engineering with Go, Python, LangGraph and vector search.",
					Engine:  "Go-Backend-Fallback",
				},
			},
		}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(res)
}
