// Resume versions (Profile tab), the resume-check result (modal) and saved searches (Jobs tab).
import { esc, timeAgo } from '../utils.js';

export function renderResumes(container, resumes) {
    if (!resumes.length) {
        container.innerHTML = '<p class="muted">Upload your main resume above first.</p>';
        return;
    }
    container.innerHTML = resumes.map((r) => `
        <div class="resume-row">
            <span><strong>${esc(r.label)}</strong> <span class="muted small">${esc(r.filename)}</span>
                ${r.skills?.length ? `<br><span class="muted small">${esc(r.skills.slice(0, 8).join(', '))}${r.skills.length > 8 ? '…' : ''}</span>` : ''}</span>
            ${r.id ? `<button class="btn-ghost btn-sm" data-action="delete-resume" data-resume-id="${esc(r.id)}" aria-label="Delete ${esc(r.label)}"><i class="fa-solid fa-trash"></i></button>` : '<span class="tag subtle">main</span>'}
        </div>`).join('');
}

export function resumeCheckHtml(result) {
    const checks = result.checks.map((c) => `
        <li class="${c.ok ? 'ok' : 'fail'}"><i class="fa-solid ${c.ok ? 'fa-circle-check' : 'fa-circle-xmark'}"></i>
            <strong>${esc(c.check)}</strong> <span class="muted small">${esc(c.detail)}</span></li>`).join('');
    const chips = (skills, kind) => skills.map((s) => `<span class="chip ${kind}">${esc(s)}</span>`).join('');
    const coverage = result.keyword_coverage == null ? 'n/a' : `${result.keyword_coverage}%`;
    return `
    <div class="resume-check">
        <p>Checked <strong>${esc(result.resume)}</strong> · overall <strong>${result.score}%</strong>
            · keyword coverage <strong>${coverage}</strong> · readability <strong>${result.readability}%</strong></p>
        ${result.matched_skills.length ? `<div class="chip-row"><span class="muted">In your resume:</span> ${chips(result.matched_skills, 'ok')}</div>` : ''}
        ${result.missing_skills.length ? `<div class="chip-row"><span class="muted">Missing (required):</span> ${chips(result.missing_skills, 'missing')}</div>` : ''}
        ${result.missing_preferred.length ? `<div class="chip-row"><span class="muted">Missing (nice to have):</span> ${chips(result.missing_preferred, 'nice')}</div>` : ''}
        <h4>Applicant-tracking checks</h4>
        <ul class="check-list">${checks}</ul>
        ${result.suggestions.length ? `<h4>Suggestions</h4><ul class="suggestions">${result.suggestions.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>` : ''}
        ${result.tips?.length ? `<h4><i class="fa-solid fa-robot"></i> AI tailoring tips</h4><ul class="suggestions">${result.tips.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>` : ''}
    </div>`;
}

const INTERVALS = [[0, 'Only when I run it'], [6, 'Every 6 hours'], [12, 'Every 12 hours'], [24, 'Daily'], [168, 'Weekly']];

export function intervalOptions(selected = 24) {
    return INTERVALS.map(([hours, label]) => `<option value="${hours}"${hours === selected ? ' selected' : ''}>${label}</option>`).join('');
}

export function renderSavedSearches(container, searches) {
    if (!searches.length) {
        container.innerHTML = '<p class="muted small">No saved searches yet. Run a search, then press "Save search".</p>';
        return;
    }
    container.innerHTML = searches.map((s) => {
        const last = s.last_run_at
            ? `last run ${esc(timeAgo(s.last_run_at))}: ${s.last_found} jobs, ${s.last_new} new`
            : 'not run yet';
        const where = [s.request.roles?.join(', ') || 'from your resume', s.request.locations?.join(', ')].filter(Boolean).join(' · ');
        return `<div class="saved-search${s.enabled ? '' : ' paused'}" data-search-id="${esc(s.id)}">
            <div><strong>${esc(s.name)}</strong> <span class="muted small">${esc(where)}</span><br>
                <span class="muted small">${last}${s.last_error ? ` · <span class="error-text">${esc(s.last_error)}</span>` : ''}</span></div>
            <div class="saved-search-actions">
                <select data-action-change="search-interval" data-search-id="${esc(s.id)}" aria-label="How often">${intervalOptions(s.interval_hours)}</select>
                <button class="btn-secondary btn-sm" data-action="run-saved-search" data-search-id="${esc(s.id)}"><i class="fa-solid fa-play"></i> Run</button>
                <button class="btn-ghost btn-sm" data-action="toggle-saved-search" data-search-id="${esc(s.id)}" data-enabled="${s.enabled}">${s.enabled ? 'Pause' : 'Resume'}</button>
                <button class="btn-ghost btn-sm" data-action="delete-saved-search" data-search-id="${esc(s.id)}" aria-label="Delete saved search"><i class="fa-solid fa-trash"></i></button>
            </div>
        </div>`;
    }).join('');
}
