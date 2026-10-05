package handlers

import (
	"encoding/json"
	"net/http"
	"time"

	"jobpilot/backend/models"
)

type ApplicationHandler struct {
	Applications []models.Application
}

func NewApplicationHandler() *ApplicationHandler {
	return &ApplicationHandler{
		Applications: []models.Application{
			{
				ID:             "app-101",
				CandidateID:    "cand-1",
				JobID:          "job-101",
				ApplicationURL: "https://example.com/apply/ai-eng",
				CoverLetter:    "Generated cover letter for Senior AI Engineer.",
				Status:         "PENDING_APPROVAL",
				HumanApproved:  false,
				CreatedAt:      time.Now(),
			},
		},
	}
}

func (h *ApplicationHandler) HandleList(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(h.Applications)
}

func (h *ApplicationHandler) HandleApprove(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		ApplicationID string `json:"application_id"`
	}

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid payload", http.StatusBadRequest)
		return
	}

	for i, app := range h.Applications {
		if app.ID == req.ApplicationID {
			h.Applications[i].Status = "APPLIED"
			h.Applications[i].HumanApproved = true
			h.Applications[i].Confirmation = "Application approved and submitted cleanly via Go Backend."

			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(h.Applications[i])
			return
		}
	}

	http.Error(w, "Application ID not found", http.StatusNotFound)
}
