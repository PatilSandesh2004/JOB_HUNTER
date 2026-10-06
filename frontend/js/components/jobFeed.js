// Ranked job cards.
import { esc, safeUrl, titleCase } from '../utils.js';

const FILTERS = {
    all: () => true,
    strong: ({ match }) => match && match.overall_match >= 70,
    remote: ({ job }) => job.workplace_type === 'REMOTE',
    visa: ({ job }) => job.visa_sponsorship.status === 'YES',
};

export function renderJobFeed(container, { jobs, applications, jobFilter, profile }) {
    const visible = jobs.filter(FILTERS[jobFilter] || FILTERS.all);
    if (!visible.length) {
        container.innerHTML = `<div class="empty-state">
            <i class="fa-solid fa-magnifying-glass"></i>
            <p>${jobs.length ? 'No jobs match this filter.' : 'No jobs yet. Run a search above.'}</p>
        </div>`;
        return;
    }
    const appByJob = new Map(applications.filter((a) => a.status !== 'DISMISSED').map((a) => [a.job_id, a]));
    container.innerHTML = visible.map((item) => jobCard(item, appByJob.get(item.job.id), Boolean(profile))).join('');
}

function jobCard({ job, match }, application, hasProfile) {
    const score = match ? Math.round(match.overall_match) : null;
    const scoreClass = score === null ? 'none' : score >= 70 ? 'high' : score >= 50 ? 'mid' : 'low';
    const visa = job.visa_sponsorship;
    const visaTag = visa.status === 'YES'
        ? `<span class="tag visa" title="${esc(visa.evidence)}"><i class="fa-solid fa-passport"></i> Sponsors visas</span>`
        : visa.status === 'NO'
            ? `<span class="tag danger" title="${esc(visa.evidence)}"><i class="fa-solid fa-ban"></i> No sponsorship</span>`
            : '';
    const workplace = job.workplace_type !== 'UNKNOWN'
        ? `<span class="tag remote"><i class="fa-solid fa-wifi"></i> ${esc(titleCase(job.workplace_type))}${
            job.remote_scope && !['UNKNOWN', 'NOT_REMOTE'].includes(job.remote_scope) ? ` · ${esc(titleCase(job.remote_scope))}` : ''}</span>`
        : '';
    const experience = job.experience_required ? `<span class="tag">${esc(job.experience_required)}+ yrs</span>` : '';
    const skills = match
        ? [...match.matched_skills.map((s) => `<span class="chip ok">${esc(s)}</span>`),
           ...match.missing_skills.map((s) => `<span class="chip missing" title="Not in your profile">${esc(s)}</span>`)].join('')
        : job.required_skills.map((s) => `<span class="chip">${esc(s)}</span>`).join('');
    const reasons = match?.reasons?.length
        ? `<details class="reasons"><summary>Why this score</summary><ul>${match.reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul></details>`
        : '';

    return `
    <article class="job-card${match && !match.passed_hard_filters ? ' filtered' : ''}">
        <div>
            <div class="job-card-header">
                <div>
                    <h3 class="job-title"><a href="${esc(safeUrl(job.application_url))}" target="_blank" rel="noopener noreferrer">${esc(job.title)}</a></h3>
                    <div class="job-company"><i class="fa-solid fa-building"></i> ${esc(job.company)} &bull; ${esc(job.location)}</div>
                </div>
                <span class="match-score-pill ${scoreClass}" title="${hasProfile ? 'Overall match' : 'Add a profile to score jobs'}">
                    ${score === null ? 'Not scored' : `<i class="fa-solid fa-bolt"></i> ${score}%`}
                </span>
            </div>
            <div class="job-tags">
                ${workplace}${visaTag}${experience}
                <span class="tag subtle">${esc(sourceLabel(job))}</span>
                ${job.verified ? '<span class="tag verified" title="Title, location and description confirmed with the job board"><i class="fa-solid fa-circle-check"></i> Verified</span>' : ''}
            </div>
            ${skills ? `<div class="chip-row">${skills}</div>` : ''}
            <p class="job-description">${esc(job.description || 'No description snippet available.')}</p>
            ${reasons}
        </div>
        <div class="job-footer">${footer(job, application, hasProfile)}</div>
    </article>`;
}

const SITE_LABELS = { 'linkedin.com': 'linkedin', 'indeed.com': 'indeed', 'naukri.com': 'naukri' };

/** Where the posting lives: the ATS, the job site, or the alert email it came from. */
function sourceLabel(job) {
    if (job.source?.startsWith('email_')) return `${job.source.slice(6)} alert`;
    if (job.ats !== 'other' && job.ats !== 'aggregator') return job.ats;
    const host = (() => { try { return new URL(job.application_url).hostname; } catch { return ''; } })();
    const site = Object.keys(SITE_LABELS).find((domain) => host === domain || host.endsWith(`.${domain}`));
    return site ? SITE_LABELS[site] : job.source;
}

export function manualButton(jobId, url, title, company, label = 'Apply manually') {
    return `<button class="btn-secondary btn-sm" data-action="manual" data-job-id="${esc(jobId)}"
                data-url="${esc(safeUrl(url))}" data-title="${esc(title)}" data-company="${esc(company)}"
                title="Open the company's site, apply there, and JobPilot will ask you afterwards">
                <i class="fa-solid fa-arrow-up-right-from-square"></i> ${esc(label)}
            </button>`;
}

/** "Not interested" and "hide this company" controls, shown on jobs you have not applied to. */
function hideButtons(job) {
    return `<span class="hide-controls">
        <button class="btn-ghost btn-sm" data-action="hide-job" data-job-id="${esc(job.id)}" title="Not interested: hide this job" aria-label="Not interested"><i class="fa-solid fa-eye-slash"></i></button>
        <button class="btn-ghost btn-sm" data-action="block-company" data-company="${esc(job.company)}" title="Hide every job from ${esc(job.company)}" aria-label="Hide company"><i class="fa-solid fa-ban"></i></button>
    </span>`;
}

function footer(job, application, hasProfile) {
    if (!application) return `${hideButtons(job)}<span class="footer-actions">${footerActions(job, hasProfile)}</span>`;
    return footerActions(job, hasProfile, application);
}

function footerActions(job, hasProfile, application = null) {
    if (application) {
        return `<span class="status-pill status-${esc(application.status.toLowerCase())}">${esc(statusLabel(application.status))}</span>
                <button class="btn-secondary btn-sm" data-action="goto-applications">View application</button>`;
    }
    if (!hasProfile) {
        return `<span class="muted">Add your profile to apply</span>
                <button class="btn-secondary btn-sm" data-action="goto-profile">Set up profile</button>`;
    }
    const manual = manualButton(job.id, job.application_url, job.title, job.company);
    if (!job.auto_apply_supported) {
        return `<span class="muted small" title="This site has no fillable form for the agent (login, bot protection or listing page)">
                    <i class="fa-solid fa-hand"></i> Auto-fill not available here</span>${manual}`;
    }
    return `${manual}
            <button class="btn-secondary btn-sm" data-action="auto-apply" data-job-id="${esc(job.id)}" title="Submit automatically when the form is complete and has no CAPTCHA">
                <i class="fa-solid fa-bolt"></i> Auto-apply
            </button>
            <button class="btn-primary btn-sm" data-action="prepare" data-job-id="${esc(job.id)}" title="Agent fills the form; you review before it submits">
                <i class="fa-solid fa-wand-magic-sparkles"></i> Prepare
            </button>`;
}

export function statusLabel(status) {
    return status === 'AWAITING_CONFIRMATION' ? 'Did you apply?' : titleCase(status);
}
