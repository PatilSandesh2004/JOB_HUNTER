package repository

import (
	"errors"
	"sync"
	"time"

	"jobpilot/backend/internal/models"
)

type ApplicationRepository interface {
	List() ([]models.Application, error)
	Approve(id string) (*models.Application, error)
	Create(app models.Application) (*models.Application, error)
}

type InMemoryApplicationRepo struct {
	mu           sync.RWMutex
	applications map[string]models.Application
}

func NewInMemoryApplicationRepo() *InMemoryApplicationRepo {
	repo := &InMemoryApplicationRepo{
		applications: make(map[string]models.Application),
	}
	
	// Seed initial approval item
	repo.applications["app-101"] = models.Application{
		ID:             "app-101",
		CandidateID:    "cand-1",
		JobID:          "job-101",
		JobTitle:       "Senior AI Engineer (LLM & Agents)",
		Company:        "TechNexus AI",
		ApplicationURL: "https://example.com/careers/ai-engineer-101",
		CoverLetter:    "Dear Hiring Manager,\n\nI am applying for the Senior AI Engineer position with extensive experience in LangGraph and FastAPI.\n\nBest regards,\nJohn Doe",
		Status:         "PENDING_APPROVAL",
		HumanApproved:  false,
		CreatedAt:      time.Now(),
	}

	return repo
}

func (r *InMemoryApplicationRepo) List() ([]models.Application, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	result := make([]models.Application, 0, len(r.applications))
	for _, app := range r.applications {
		result = append(result, app)
	}
	return result, nil
}

func (r *InMemoryApplicationRepo) Approve(id string) (*models.Application, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	app, exists := r.applications[id]
	if !exists {
		return nil, errors.New("application not found")
	}

	app.Status = "APPLIED"
	app.HumanApproved = true
	app.Confirmation = "Submitted via Playwright agent with verified human approval."
	r.applications[id] = app

	return &app, nil
}

func (r *InMemoryApplicationRepo) Create(app models.Application) (*models.Application, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if app.ID == "" {
		app.ID = time.Now().Format("app-20060102150405")
	}
	app.CreatedAt = time.Now()
	r.applications[app.ID] = app
	return &app, nil
}
