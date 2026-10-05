// Modular Global State Store
export const store = {
    jobs: [
        {
            id: "job-101",
            title: "Senior AI Engineer (LLM & Agents)",
            company: "TechNexus AI",
            location: "Bengaluru, India (Remote)",
            experience: 4,
            skills: ["Python", "LangGraph", "FastAPI", "Vector DBs"],
            visa_status: "YES",
            remote_scope: "REMOTE_INDIA_ONLY",
            match_score: 92,
            description: "Looking for an experienced AI Engineer to design and deploy multi-agent systems, RAG workflows, and vector store search integrations.",
            application_url: "https://example.com/careers/ai-engineer-101"
        },
        {
            id: "job-102",
            title: "Staff Autonomous Systems Engineer",
            company: "Global Quantum Tech",
            location: "Bengaluru, India",
            experience: 5,
            skills: ["Python", "Docker", "Qdrant", "PostgreSQL"],
            visa_status: "YES",
            remote_scope: "HYBRID",
            match_score: 84,
            description: "Join our core platform engineering team building next-generation automated workflow agents and high-throughput microservices.",
            application_url: "https://example.com/careers/quantum-eng"
        }
    ],

    applications: [
        {
            id: "app-101",
            job_title: "Senior AI Engineer (LLM & Agents)",
            company: "TechNexus AI",
            status: "PENDING_APPROVAL",
            cover_letter: "Dear Hiring Manager,\n\nI am thrilled to apply for the Senior AI Engineer role..."
        }
    ],

    listeners: [],

    subscribe(fn) {
        this.listeners.push(fn);
    },

    notify() {
        this.listeners.forEach(fn => fn(this));
    }
};
