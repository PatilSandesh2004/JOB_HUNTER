package models

import "time"

type SearchRequest struct {
	Roles      []string `json:"roles"`
	Locations  []string `json:"locations"`
	RemoteOnly bool     `json:"remote_only"`
}

type SearchResultItem struct {
	Title   string `json:"title"`
	URL     string `json:"url"`
	Content string `json:"content,omitempty"`
	Engine  string `json:"engine,omitempty"`
}

type SearchResponse struct {
	Query        string             `json:"query"`
	TotalResults int                `json:"total_results"`
	Results      []SearchResultItem `json:"results"`
}

type Job struct {
	ID                 string    `json:"id"`
	Title              string    `json:"title"`
	Company            string    `json:"company"`
	Location           string    `json:"location"`
	Description        string    `json:"description"`
	WorkplaceType      string    `json:"workplace_type"`
	RemoteScope        string    `json:"remote_scope"`
	VisaStatus         string    `json:"visa_status"`
	ExperienceRequired float64   `json:"experience_required"`
	RequiredSkills     []string  `json:"required_skills"`
	ApplicationURL     string    `json:"application_url"`
	PostedAt           time.Time `json:"posted_at"`
}

type CandidateProfile struct {
	ID                  string   `json:"id"`
	Name                string   `json:"name"`
	Email               string   `json:"email"`
	YearsOfExperience   float64  `json:"years_of_experience"`
	Skills              []string `json:"skills"`
	VisaRequired        bool     `json:"visa_required"`
}

type Application struct {
	ID             string    `json:"id"`
	CandidateID    string    `json:"candidate_id"`
	JobID          string    `json:"job_id"`
	ApplicationURL string    `json:"application_url"`
	CoverLetter    string    `json:"cover_letter"`
	Status         string    `json:"status"` // DISCOVERED, PENDING_APPROVAL, APPLIED, REJECTED
	HumanApproved  bool      `json:"human_approved"`
	Confirmation   string    `json:"confirmation,omitempty"`
	CreatedAt      time.Time `json:"created_at"`
}

type MatchEvaluation struct {
	OverallMatch float64 `json:"overall_match"`
	SkillMatch   float64 `json:"skill_match"`
	Explanation  string  `json:"explanation"`
}
