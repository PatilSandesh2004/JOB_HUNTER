// Ranked job cards, with sorting, a text filter, "new since your last visit" and paging.
import { esc, safeUrl, timeAgo, titleCase } from '../utils.js';

export const PAGE_SIZE = 30;

const FILTERS = {
    all: () => true,
    strong: ({ match }) => match && match.overall_match >= 70,
    location: ({ match }) => match && match.location_match >= 100,
    remote: ({ job }) => job.workplace_type === 'REMOTE',
    visa: ({ job }) => job.visa_sponsorship.status === 'YES',
    salary: ({ job }) => job.salary_min != null || job.salary_max != null,
    new: (item, ctx) => isNew(item.job, ctx.lastVisit),
};

const dateOf = (job) => new Date(job.posted_at || job.first_seen_at || 0).getTime();
const SORTS = {
    match: (a, b) => Number(Boolean(b.match?.passed_hard_filters)) - Number(Boolean(a.match?.passed_hard_filters))
        || (b.match?.overall_match ?? -1) - (a.match?.overall_match ?? -1),
    newest: (a, b) => dateOf(b.job) - dateOf(a.job),
    company: (a, b) => a.job.company.localeCompare(b.job.company) || a.job.title.localeCompare(b.job.title),
    salary: (a, b) => (b.job.salary_max ?? b.job.salary_min ?? -1) - (a.job.salary_max ?? a.job.salary_min ?? -1),
};

export function isNew(job, lastVisit) {
    return Boolean(lastVisit && job.first_seen_at && new Date(job.first_seen_at).getTime() > lastVisit);
}

function matchesQuery({ job }, query) {
    if (!query) return true;
    const haystack = [job.title, job.company, job.location, ...job.required_skills, ...(job.preferred_skills || [])]
        .join(' ').toLowerCase();
    return query.toLowerCase().split(/\s+/).filter(Boolean).every((word) => haystack.includes(word));
}

/** The jobs to show, filtered and sorted. */
export function visibleJobs({ jobs, jobFilter, jobSort, jobQuery, lastVisit }) {
    const filter = FILTERS[jobFilter] || FILTERS.all;
    return jobs
        .filter((item) => filter(item, { lastVisit }) && matchesQuery(item, jobQuery))
        .sort(SORTS[jobSort] || SORTS.match);
}

export function renderJobFeed(container, state) {
    const { jobs, applications, profile, visibleCount = PAGE_SIZE, lastVisit } = state;
    const visible = visibleJobs(state);
    if (!visible.length) {
        container.innerHTML = `<div class="empty-state">
            <i class="fa-solid fa-magnifying-glass"></i>
            <p>${jobs.length ? 'No jobs match these filters.' : 'No jobs found yet. Click "Search Jobs" to discover postings matching your profile.'}</p>
        </div>`;
        return;
    }
    const appByJob = new Map(applications.filter((a) => a.status !== 'DISMISSED').map((a) => [a.job_id, a]));
    const shown = visible.slice(0, visibleCount);
    const more = visible.length - shown.length;
    container.innerHTML = shown.map((item) => jobCard(item, appByJob.get(item.job.id), Boolean(profile), lastVisit)).join('')
        + (more > 0 ? `<div class="load-more"><button class="btn-secondary" data-action="show-more-jobs">Show ${Math.min(more, PAGE_SIZE)} more (${more} left)</button></div>` : '');
}

const CURRENCY = { INR: '₹', USD: '$', EUR: '€', GBP: '£', CAD: 'C$', AUD: 'A$', SGD: 'S$' };

export function salaryText(job) {
    if (job.salary_min == null && job.salary_max == null) return '';
    const symbol = CURRENCY[job.salary_currency] ?? (job.salary_currency ? `${job.salary_currency} ` : '');
    const amount = (n) => {
        if (job.salary_currency === 'INR' && n >= 100000) return `${+(n / 100000).toFixed(1)}L`;
        if (n >= 1000) return `${Math.round(n / 1000)}k`;
        return String(Math.round(n));
    };
    const range = [...new Set([job.salary_min, job.salary_max].filter((n) => n != null).map(amount))].join('–');
    const period = { year: '/yr', month: '/mo', hour: '/hr' }[job.salary_period] || '';
    return `${symbol}${range}${period}`;
}

const VERDICT_LABELS = { strong: 'Strong fit', possible: 'Possible fit', weak: 'Weak fit', no: 'Not a fit' };

function jobCard({ job, match }, application, hasProfile, lastVisit) {
    const score = match ? Math.round(match.overall_match) : null;
    const scoreClass = score === null ? 'none' : score >= 70 ? 'high' : score >= 50 ? 'mid' : 'low';
    const visa = job.visa_sponsorship;
    const visaTag = visa.status === 'YES'
        ? `<span class="tag visa" title="${esc(visa.evidence)}"><i class="fa-solid fa-passport"></i> Sponsors Visa</span>`
        : visa.status === 'NO'
            ? `<span class="tag danger" title="${esc(visa.evidence)}"><i class="fa-solid fa-ban"></i> No Visa</span>`
            : '';
    const workplace = job.workplace_type !== 'UNKNOWN'
        ? `<span class="tag remote"><i class="fa-solid fa-wifi"></i> ${esc(titleCase(job.workplace_type))}${
            job.remote_scope && !['UNKNOWN', 'NOT_REMOTE'].includes(job.remote_scope) ? ` · ${esc(titleCase(job.remote_scope))}` : ''}</span>`
        : '';
    const years = job.experience_required != null
        ? (job.experience_max != null && job.experience_max > job.experience_required
            ? `${job.experience_required}–${job.experience_max} yrs`
            : `${job.experience_required}+ yrs`)
        : '';
    const tags = [
        isNew(job, lastVisit) ? '<span class="tag new-badge">New</span>' : '',
        match?.ai_verdict
            ? `<span class="tag verdict verdict-${esc(match.ai_verdict)}" title="${esc(match.ai_reason || '')}"><i class="fa-solid fa-robot"></i> ${esc(VERDICT_LABELS[match.ai_verdict] || match.ai_verdict)}</span>`
            : '',
        workplace,
        visaTag,
        years ? `<span class="tag"><i class="fa-solid fa-user-clock"></i> ${esc(years)}</span>` : '',
        salaryText(job) ? `<span class="tag salary"><i class="fa-solid fa-money-bill-wave"></i> ${esc(salaryText(job))}</span>` : '',
        job.posted_at ? `<span class="tag subtle" title="Posted ${esc(new Date(job.posted_at).toLocaleString())}"><i class="fa-regular fa-clock"></i> ${esc(timeAgo(job.posted_at))}</span>` : '',
        match?.confidence === 'LOW'
            ? '<span class="tag subtle" title="The posting gave little detail (no description, skills or experience), so this score is rough"><i class="fa-solid fa-circle-half-stroke"></i> limited info</span>'
            : '',
        `<span class="tag subtle">${esc(sourceLabel(job))}</span>`,
        job.verified ? '<span class="tag verified" title="Confirmed open on the company\'s job board"><i class="fa-solid fa-circle-check"></i> Verified</span>' : '',
    ].join('');
    const skills = match
        ? [...match.matched_skills.map((s) => `<span class="chip ok"><i class="fa-solid fa-check"></i> ${esc(s)}</span>`),
           ...match.missing_skills.map((s) => `<span class="chip missing" title="Required; not in your profile">${esc(s)}</span>`),
           ...(match.missing_preferred || []).map((s) => `<span class="chip nice" title="Nice to have; not in your profile">${esc(s)}</span>`)].join('')
        : job.required_skills.map((s) => `<span class="chip">${esc(s)}</span>`).join('');
    const reasons = match?.reasons?.length
        ? `<details class="reasons"><summary>Why this score</summary><ul>${match.reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul></details>`
        : '';

    return `
    <article class="job-card${match && !match.passed_hard_filters ? ' filtered' : ''}" data-job-id="${esc(job.id)}">
        <div>
            <div class="job-card-header">
                <div>
                    <h3 class="job-title"><a href="${esc(safeUrl(job.application_url))}" target="_blank" rel="noopener noreferrer">${esc(job.title)}</a></h3>
                    <div class="job-company"><i class="fa-solid fa-building"></i> ${esc(job.company)} &bull; <i class="fa-solid fa-location-dot"></i> ${esc(job.location)}</div>
                </div>
                <span class="match-score-pill ${scoreClass}" title="${hasProfile ? 'Overall match score' : 'Add a profile to calculate score'}">
                    ${score === null ? 'Not scored' : `<i class="fa-solid fa-bolt"></i> ${score}%`}
                </span>
            </div>
            <div class="job-tags">${tags}</div>
            ${match?.ai_reason ? `<p class="ai-reason"><i class="fa-solid fa-robot"></i> ${esc(match.ai_reason)}</p>` : ''}
            ${skills ? `<div class="chip-row">${skills}</div>` : ''}
            ${reasons}
            <p class="job-description">${esc(job.description || 'No description snippet available.')}</p>
        </div>
        <div class="job-footer">${footer(job, application, hasProfile)}</div>
    </article>`;
}

const SITE_LABELS = { 'linkedin.com': 'linkedin', 'indeed.com': 'indeed', 'naukri.com': 'naukri' };

function sourceLabel(job) {
    if (job.source?.startsWith('email_')) return `${job.source.slice(6)} alert`;
    if (job.ats !== 'other' && job.ats !== 'aggregator') return job.ats;
    const host = (() => { try { return new URL(job.application_url).hostname; } catch { return ''; } })();
    const site = Object.keys(SITE_LABELS).find((domain) => host === domain || host.endsWith(`.${domain}`));
    return site ? SITE_LABELS[site] : job.source;
}

export function manualButton(jobId, url, title, company, label = 'Apply Manually') {
    return `<button class="btn-secondary btn-sm" data-action="manual" data-job-id="${esc(jobId)}"
                data-url="${esc(safeUrl(url))}" data-title="${esc(title)}" data-company="${esc(company)}"
                title="Open the job page; JobPilot asks afterwards whether you applied">
                <i class="fa-solid fa-arrow-up-right-from-square"></i> ${esc(label)}
            </button>`;
}

function hideButtons(job) {
    return `<span class="hide-controls">
        <button class="btn-ghost btn-sm" data-action="hide-job" data-job-id="${esc(job.id)}" title="Not interested: hide this job" aria-label="Not interested"><i class="fa-solid fa-eye-slash"></i></button>
        <button class="btn-ghost btn-sm" data-action="block-company" data-company="${esc(job.company)}" title="Hide all jobs from ${esc(job.company)}" aria-label="Hide company"><i class="fa-solid fa-ban"></i></button>
        <button class="btn-ghost btn-sm" data-action="save-job" data-job-id="${esc(job.id)}" title="Save to apply later (Applications board)" aria-label="Save job"><i class="fa-regular fa-bookmark"></i></button>
    </span>`;
}

function footer(job, application, hasProfile) {
    if (!application) return `${hideButtons(job)}<span class="footer-actions">${footerActions(job, hasProfile)}</span>`;
    return footerActions(job, hasProfile, application);
}

function footerActions(job, hasProfile, application = null) {
    if (application && application.status !== 'SAVED') {
        return `<span class="status-pill status-${esc(application.status.toLowerCase())}">${esc(statusLabel(application.status))}</span>
                <button class="btn-secondary btn-sm" data-action="goto-applications">View Application</button>`;
    }
    if (!hasProfile) {
        return `<span class="muted">Add your profile to apply</span>
                <button class="btn-secondary btn-sm" data-action="goto-profile">Set up Profile</button>`;
    }
    const saved = application ? '<span class="tag subtle"><i class="fa-solid fa-bookmark"></i> saved</span>' : '';
    const check = `<button class="btn-ghost btn-sm" data-action="resume-check" data-job-id="${esc(job.id)}" title="How well your resume fits this job">
                <i class="fa-solid fa-file-circle-check"></i> Resume check</button>`;
    const contacts = `<button class="btn-ghost btn-sm" data-action="get-insiders" data-job-id="${esc(job.id)}" data-company="${esc(job.company)}" data-job-title="${esc(job.title)}" title="Find recruiters and people you know at ${esc(job.company)}">
                <i class="fa-solid fa-users"></i> Contacts</button>`;
    const manual = manualButton(job.id, job.application_url, job.title, job.company);
    if (!job.auto_apply_supported) return `${saved}${check}${contacts}${manual}`;
    return `${saved}${check}${contacts}${manual}
            <button class="btn-secondary btn-sm" data-action="auto-apply" data-job-id="${esc(job.id)}" title="Submit automatically when the form is complete and has no CAPTCHA">
                <i class="fa-solid fa-bolt"></i> Auto-apply</button>
            <button class="btn-primary btn-sm" data-action="prepare" data-job-id="${esc(job.id)}" title="The agent fills the form and writes a cover letter for you to review">
                <i class="fa-solid fa-wand-magic-sparkles"></i> Prepare</button>`;
}

export function statusLabel(status) {
    return { AWAITING_CONFIRMATION: 'Did you apply?', SAVED: 'Saved' }[status] || titleCase(status);
}
