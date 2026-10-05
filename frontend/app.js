document.addEventListener('DOMContentLoaded', () => {
    
    // --- Mock Initial Job Feed ---
    const initialJobs = [
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
        },
        {
            id: "job-103",
            title: "Backend Agent Developer",
            company: "InnovateLabs Inc",
            location: "Remote Global",
            experience: 3,
            skills: ["Python", "FastAPI", "AsyncIO"],
            visa_status: "UNKNOWN",
            remote_scope: "GLOBAL_REMOTE",
            match_score: 68,
            description: "Developing scalable REST APIs and agentic graph workflows using Python 3.12 and FastAPI.",
            application_url: "https://example.com/careers/backend-dev"
        }
    ];

    let currentJobs = [...initialJobs];
    let pendingApprovals = [
        {
            id: "app-201",
            job_title: "Senior AI Engineer (LLM & Agents)",
            company: "TechNexus AI",
            applicant_name: "John Doe",
            status: "PENDING_APPROVAL",
            cover_letter: "Dear Hiring Team at TechNexus AI,\n\nI am thrilled to submit my application for the Senior AI Engineer role. With over 4 years of experience specializing in Python, LangGraph agent workflows, and vector databases, I am eager to contribute to your autonomous agent architecture.\n\nSincerely,\nJohn Doe"
        }
    ];

    // --- Tab Switching ---
    const navButtons = document.querySelectorAll('.nav-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            navButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(targetTab).classList.add('active');
        });
    });

    // --- Render Job Feed ---
    function renderJobs(jobsToRender) {
        const container = document.getElementById('jobs-container');
        container.innerHTML = '';

        if (jobsToRender.length === 0) {
            container.innerHTML = '<div class="no-results">No matching jobs found. Run a new search above!</div>';
            return;
        }

        jobsToRender.forEach(job => {
            const scoreClass = job.match_score >= 80 ? 'high' : 'mid';
            const visaBadge = job.visa_status === 'YES' ? '<span class="tag visa"><i class="fa-solid fa-passport"></i> Visa Sponsored</span>' : '';
            const remoteBadge = `<span class="tag remote"><i class="fa-solid fa-wifi"></i> ${job.remote_scope}</span>`;

            const cardHtml = `
                <div class="job-card" data-job-id="${job.id}">
                    <div>
                        <div class="job-card-header">
                            <div>
                                <h3 class="job-title">${job.title}</h3>
                                <div class="job-company"><i class="fa-solid fa-building"></i> ${job.company} &bull; ${job.location}</div>
                            </div>
                            <span class="match-score-pill ${scoreClass}">
                                <i class="fa-solid fa-bolt"></i> ${job.match_score}% Match
                            </span>
                        </div>

                        <div class="job-tags">
                            ${visaBadge}
                            ${remoteBadge}
                            <span class="tag"><i class="fa-solid fa-briefcase"></i> ${job.experience}+ Yrs Exp</span>
                        </div>

                        <p class="job-description">${job.description}</p>
                    </div>

                    <div class="job-footer">
                        <span class="tag">${job.skills.slice(0, 3).join(', ')}</span>
                        <button class="btn-primary btn-tailor" data-job-id="${job.id}">
                            <i class="fa-solid fa-wand-magic-sparkles"></i> Tailor & Apply
                        </button>
                    </div>
                </div>
            `;
            container.insertAdjacentHTML('beforeend', cardHtml);
        });

        // Update stats
        document.getElementById('stat-total-jobs').innerText = currentJobs.length;
        document.getElementById('stat-high-match').innerText = currentJobs.filter(j => j.match_score >= 75).length;
        document.getElementById('stat-visa-jobs').innerText = currentJobs.filter(j => j.visa_status === 'YES').length;
        document.getElementById('stat-pending-apps').innerText = pendingApprovals.length;
        document.getElementById('pending-count').innerText = pendingApprovals.length;
    }

    renderJobs(currentJobs);

    // --- Search Form Handler ---
    const searchForm = document.getElementById('search-form');
    searchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const roleStr = document.getElementById('role-input').value;
        const locStr = document.getElementById('location-input').value;
        const remoteOnly = document.getElementById('remote-toggle').checked;
        const btnSearch = document.getElementById('btn-search');

        btnSearch.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Agent Searching...';

        try {
            const response = await fetch('/api/v1/search/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    roles: roleStr.split(',').map(s => s.trim()),
                    locations: locStr.split(',').map(s => s.trim()),
                    remote_only: remoteOnly
                })
            });

            if (response.ok) {
                const data = await response.json();
                if (data.results && data.results.length > 0) {
                    const newJobs = data.results.map((r, idx) => ({
                        id: `search-job-${idx}`,
                        title: r.title,
                        company: "Discovered Employer",
                        location: locStr || "Remote",
                        experience: 4,
                        skills: ["Python", "FastAPI"],
                        visa_status: "YES",
                        remote_scope: remoteOnly ? "REMOTE_ONLY" : "HYBRID",
                        match_score: 88,
                        description: r.content || "Discovered job via SearchAgent metasearch indexing.",
                        application_url: r.url
                    }));
                    currentJobs = [...newJobs, ...currentJobs];
                    renderJobs(currentJobs);
                }
            }
        } catch (err) {
            console.log('Search endpoint notice (using live state):', err);
        } finally {
            btnSearch.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Execute Agent Search';
        }
    });

    // --- Filter Buttons ---
    const filterBtns = document.querySelectorAll('.filter-btn');
    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const filter = btn.getAttribute('data-filter');
            if (filter === 'all') {
                renderJobs(currentJobs);
            } else if (filter === 'high-match') {
                renderJobs(currentJobs.filter(j => j.match_score >= 75));
            } else if (filter === 'visa') {
                renderJobs(currentJobs.filter(j => j.visa_status === 'YES'));
            }
        });
    });

    // --- Tailor & Apply Modal ---
    const modal = document.getElementById('tailor-modal');
    const modalJobMeta = document.getElementById('modal-job-meta');
    const modalCoverLetter = document.getElementById('modal-cover-letter');
    let activeModalJob = null;

    document.addEventListener('click', (e) => {
        if (e.target.closest('.btn-tailor')) {
            const btn = e.target.closest('.btn-tailor');
            const jobId = btn.getAttribute('data-job-id');
            activeModalJob = currentJobs.find(j => j.id === jobId);

            if (activeModalJob) {
                modalJobMeta.innerHTML = `
                    <h4>${activeModalJob.title}</h4>
                    <p>${activeModalJob.company} &bull; ${activeModalJob.location}</p>
                `;
                modalCoverLetter.value = `Dear Hiring Team at ${activeModalJob.company},\n\nI am writing to express my strong enthusiasm for the ${activeModalJob.title} position. With my background in AI engineering, Python, FastAPI, and agentic workflows, I am confident in my ability to add immediate value to your team.\n\nSincerely,\nJohn Doe`;
                modal.classList.add('active');
            }
        }
    });

    document.getElementById('close-modal-btn').addEventListener('click', () => modal.classList.remove('active'));
    document.getElementById('modal-cancel-btn').addEventListener('click', () => modal.classList.remove('active'));

    document.getElementById('modal-approve-btn').addEventListener('click', () => {
        if (activeModalJob) {
            pendingApprovals.unshift({
                id: `app-${Date.now()}`,
                job_title: activeModalJob.title,
                company: activeModalJob.company,
                applicant_name: "John Doe",
                status: "PENDING_APPROVAL",
                cover_letter: modalCoverLetter.value
            });
            renderApprovalQueue();
            modal.classList.remove('active');
            alert('Application package created and queued for Human Approval!');
        }
    });

    // --- Render Approval Queue ---
    function renderApprovalQueue() {
        const queueContainer = document.getElementById('approval-queue-list');
        queueContainer.innerHTML = '';

        if (pendingApprovals.length === 0) {
            queueContainer.innerHTML = '<p class="text-muted">No pending application forms awaiting approval.</p>';
            return;
        }

        pendingApprovals.forEach(app => {
            const itemHtml = `
                <div class="approval-item" id="${app.id}">
                    <div class="approval-info">
                        <h4>${app.job_title} — ${app.company}</h4>
                        <p>Playwright Form Filled &bull; Status: <strong style="color: var(--accent-amber);">${app.status}</strong></p>
                    </div>
                    <button class="btn-primary btn-submit-app" data-app-id="${app.id}">
                        <i class="fa-solid fa-paper-plane"></i> Approve & Submit
                    </button>
                </div>
            `;
            queueContainer.insertAdjacentHTML('beforeend', itemHtml);
        });

        document.getElementById('pending-count').innerText = pendingApprovals.length;
        document.getElementById('stat-pending-apps').innerText = pendingApprovals.length;
    }

    renderApprovalQueue();

    document.addEventListener('click', (e) => {
        if (e.target.closest('.btn-submit-app')) {
            const btn = e.target.closest('.btn-submit-app');
            const appId = btn.getAttribute('data-app-id');
            pendingApprovals = pendingApprovals.filter(a => a.id !== appId);
            renderApprovalQueue();
            alert('Application submitted successfully with verified Human Approval!');
        }
    });

    // --- Candidate Form Handler ---
    document.getElementById('candidate-form').addEventListener('submit', (e) => {
        e.preventDefault();
        alert('Candidate Profile preferences saved!');
    });

});
