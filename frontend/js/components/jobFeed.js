// Modular Job Feed Component
export function renderJobFeed(container, jobs) {
    container.innerHTML = '';

    if (!jobs || jobs.length === 0) {
        container.innerHTML = '<div class="no-results">No matching jobs found. Execute a search!</div>';
        return;
    }

    jobs.forEach(job => {
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
                    <span class="tag">${job.skills ? job.skills.slice(0, 3).join(', ') : 'Python, Go'}</span>
                    <button class="btn-primary btn-tailor" data-job-id="${job.id}">
                        <i class="fa-solid fa-wand-magic-sparkles"></i> Tailor & Apply
                    </button>
                </div>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', cardHtml);
    });
}
