// Application queue: review, edit, approve, and track outcomes.
import { AWAITING, IN_FLIGHT, NEEDS_REVIEW, SUBMITTED } from '../state.js';
import { esc, safeUrl, timeAgo } from '../utils.js';
import { manualButton, statusLabel } from './jobFeed.js';

const GROUPS = [
    { title: 'Did you apply?', icon: 'fa-circle-question', test: (a) => a.status === AWAITING },
    { title: 'Needs your review', icon: 'fa-hand', test: (a) => NEEDS_REVIEW.has(a.status) },
    { title: 'Agent working', icon: 'fa-robot', test: (a) => IN_FLIGHT.has(a.status) },
    { title: 'Applied', icon: 'fa-circle-check', test: (a) => SUBMITTED.has(a.status) },
    { title: 'Dismissed', icon: 'fa-box-archive', test: (a) => a.status === 'DISMISSED' },
];

export function renderApplications(container, applications) {
    if (!applications.length) {
        container.innerHTML = `<div class="empty-state"><i class="fa-solid fa-inbox"></i>
            <p>No applications yet. Use "Prepare application" on a job.</p></div>`;
        return;
    }
    // Keep unsaved cover-letter edits and typed answers across re-renders (polling refreshes this list).
    const drafts = new Map([...container.querySelectorAll('textarea[data-app-id]')]
        .filter((t) => t.dataset.dirty === '1').map((t) => [t.dataset.appId, t.value]));
    const answerDrafts = new Map([...container.querySelectorAll('[data-question-input]')]
        .filter((el) => el.dataset.dirty === '1').map((el) => [el.dataset.key, el.value]));
    const openTimelines = new Set([...container.querySelectorAll('details.timeline[open]')].map((d) => d.dataset.appId));

    container.innerHTML = GROUPS.map((group) => {
        const items = applications.filter(group.test);
        if (!items.length) return '';
        return `<h3 class="group-title"><i class="fa-solid ${group.icon}"></i> ${group.title} <span class="muted">(${items.length})</span></h3>
                ${items.map((a) => applicationCard(a, drafts.get(a.id), answerDrafts, openTimelines.has(a.id))).join('')}`;
    }).join('');

    container.querySelectorAll('textarea[data-app-id], [data-question-input]').forEach((el) => {
        const restored = el.matches('[data-question-input]') ? answerDrafts.has(el.dataset.key) : drafts.has(el.dataset.appId);
        if (restored) el.dataset.dirty = '1';
        const markDirty = () => { el.dataset.dirty = '1'; };
        el.addEventListener('input', markDirty);
        el.addEventListener('change', markDirty);
    });
}

function applicationCard(app, draft, answerDrafts, timelineOpen) {
    const busy = IN_FLIGHT.has(app.status);
    const reviewable = NEEDS_REVIEW.has(app.status);
    const filled = Object.entries(app.filled_fields || {});
    const statusText = busy
        ? `<i class="fa-solid fa-circle-notch fa-spin"></i> ${app.status === 'SUBMITTING' ? 'Submitting…' : 'Preparing cover letter and filling the form…'}`
        : esc(statusLabel(app.status));

    return `
    <div class="approval-item app-card" data-app-id="${esc(app.id)}">
        <div class="app-head">
            <div class="approval-info">
                <h4><a href="${esc(safeUrl(app.application_url))}" target="_blank" rel="noopener noreferrer">${esc(app.job_title)}</a> — ${esc(app.company)}</h4>
                <p><span class="status-pill status-${esc(app.status.toLowerCase())}">${statusText}</span>
                   <span class="tag subtle">${esc({ auto: 'auto-apply', manual: 'manual', review: 'agent-filled' }[app.mode] || app.mode)}</span>
                   <span class="muted">updated ${esc(timeAgo(app.updated_at))}</span></p>
            </div>
            <div class="app-actions">${actions(app, reviewable)}</div>
        </div>
        ${app.error ? `<p class="notice ${app.status === 'FAILED' ? 'error' : 'warn'}"><i class="fa-solid fa-circle-info"></i> ${esc(app.error)}</p>` : ''}
        ${app.confirmation ? `<p class="notice ok"><i class="fa-solid fa-check"></i> ${esc(app.confirmation)}</p>` : ''}
        ${filled.length ? `<div class="chip-row"><span class="muted">Filled:</span> ${filled.map(([label]) => `<span class="chip ok">${esc(label)}</span>`).join('')}</div>` : ''}
        ${app.missing_fields?.length ? `<div class="chip-row"><span class="muted">Needs you:</span> ${app.missing_fields.map((m) => `<span class="chip missing">${esc(m)}</span>`).join('')}</div>` : ''}
        ${reviewable ? questions(app, answerDrafts) : ''}
        ${resumeReport(app)}
        ${app.cover_letter !== null
            ? coverLetter(app, draft, reviewable || app.status === AWAITING)
            : app.status === AWAITING ? '<p class="muted"><i class="fa-solid fa-circle-notch fa-spin"></i> Drafting a cover letter you can paste…</p>' : ''}
        ${timeline(app, timelineOpen)}
    </div>`;
}

/** Required questions the agent could not answer, prefilled with AI drafts to check. */
function questions(app, answerDrafts) {
    if (!app.questions?.length) return '';
    const fields = app.questions.map((q) => {
        const key = `${app.id}::${q.label}`;
        const value = answerDrafts.get(key) ?? q.suggestion ?? '';
        const attrs = `data-question-input data-key="${esc(key)}" data-label="${esc(q.label)}" data-suggestion="${esc(q.suggestion ?? '')}" aria-label="${esc(q.label)}"`;
        const input = q.options?.length
            ? `<select ${attrs}><option value="">Choose…</option>${q.options.map((o) => `<option${o === value ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>`
            : q.kind === 'textarea'
                ? `<textarea rows="3" ${attrs}>${esc(value)}</textarea>`
                : `<input ${attrs} value="${esc(value)}">`;
        const hint = q.suggestion
            ? '<span class="question-hint"><i class="fa-solid fa-robot"></i> Drafted by AI from your profile. Check it before saving.</span>'
            : '';
        return `<div class="question"><label>${esc(q.label)}</label>${input}${hint}</div>`;
    }).join('');
    return `
    <div class="questions">
        <h5><i class="fa-solid fa-circle-question"></i> Questions the agent could not answer</h5>
        ${fields}
        <div class="letter-actions">
            <button class="btn-primary btn-sm" data-action="save-answers" data-app-id="${esc(app.id)}"><i class="fa-solid fa-floppy-disk"></i> Save answers &amp; re-fill</button>
        </div>
        <p class="muted small">Saved answers go to your answer bank (Profile tab) and are reused on future applications.</p>
    </div>`;
}

/** How the profile matches the posting's skills, plus the tailored resume when one was attached. */
function resumeReport(app) {
    const report = app.resume_report;
    if (!report && !app.has_tailored_resume) return '';
    const matched = (report?.matched_skills || []).map((s) => `<span class="chip ok">${esc(s)}</span>`).join('');
    const missing = (report?.missing_skills || []).map((s) => `<span class="chip missing" title="The posting asks for it; it is not in your profile">${esc(s)}</span>`).join('');
    const pdf = app.has_tailored_resume
        ? `<button class="btn-secondary btn-sm" data-action="open-resume" data-app-id="${esc(app.id)}"><i class="fa-solid fa-file-pdf"></i> Tailored resume</button>`
        : '';
    if (!matched && !missing && !pdf) return '';
    return `<div class="chip-row resume-report">${pdf}
        ${matched ? `<span class="muted">Posting skills you have:</span> ${matched}` : ''}
        ${missing ? `<span class="muted">Not in your profile:</span> ${missing}` : ''}</div>`;
}

/** Everything the agent did, oldest first, with screenshots per step. */
function timeline(app, open) {
    if (!app.events?.length) return '';
    const rows = app.events.map((e) => `
        <li><span class="when" title="${esc(new Date(e.at).toLocaleString())}">${esc(timeAgo(e.at))}</span>
            <strong>${esc(e.step)}</strong>${e.detail ? ` <span class="muted">${esc(e.detail)}</span>` : ''}
            ${e.screenshot ? `<button class="link-btn" data-action="step-screenshot" data-app-id="${esc(app.id)}" data-name="${esc(e.screenshot)}"><i class="fa-solid fa-image"></i> screenshot</button>` : ''}
        </li>`).join('');
    return `<details class="timeline" data-app-id="${esc(app.id)}"${open ? ' open' : ''}>
        <summary>Agent activity <span class="muted">(${app.events.length})</span></summary><ol>${rows}</ol></details>`;
}

function coverLetter(app, draft, editable) {
    const source = { llm: 'AI-written', template: 'Template (LLM unavailable)', user: 'Edited by you' }[app.cover_letter_source] || '';
    return `
    <details class="cover-letter" ${editable ? 'open' : ''}>
        <summary>Cover letter <span class="muted">${esc(source)}</span></summary>
        <textarea data-app-id="${esc(app.id)}" rows="10" ${editable ? '' : 'readonly'}>${esc(draft ?? app.cover_letter)}</textarea>
        <div class="letter-actions">
            ${editable ? `<button class="btn-secondary btn-sm" data-action="save-letter" data-app-id="${esc(app.id)}"><i class="fa-solid fa-floppy-disk"></i> Save letter</button>` : ''}
            <button class="btn-secondary btn-sm" data-action="copy-letter" data-app-id="${esc(app.id)}"><i class="fa-solid fa-copy"></i> Copy</button>
        </div>
    </details>`;
}

function actions(app, reviewable) {
    const buttons = [];
    if (app.status === AWAITING) {
        const id = esc(app.id);
        return `<button class="btn-primary btn-sm" data-action="set-status" data-status="APPLIED" data-app-id="${id}"><i class="fa-solid fa-check"></i> Yes, I applied</button>
                ${manualButton(app.job_id, app.application_url, app.job_title, app.company, 'Open site again')}
                <button class="btn-ghost btn-sm" data-action="set-status" data-status="DISMISSED" data-app-id="${id}">Not applying</button>`;
    }
    if (app.has_screenshot) {
        buttons.push(`<button class="btn-secondary btn-sm" data-action="screenshot" data-app-id="${esc(app.id)}" data-version="${esc(app.updated_at)}"><i class="fa-solid fa-image"></i> Screenshot</button>`);
    }
    if (reviewable) {
        const label = app.status === 'PENDING_APPROVAL' ? 'Approve & submit' : 'Retry submit';
        // When the agent got stuck (no form, CAPTCHA, login), applying yourself is the main path.
        if (app.status === 'PENDING_APPROVAL') {
            buttons.push(`<button class="btn-primary btn-sm" data-action="approve" data-app-id="${esc(app.id)}"><i class="fa-solid fa-paper-plane"></i> ${label}</button>`);
        }
        buttons.push(manualButton(app.job_id, app.application_url, app.job_title, app.company));
        if (app.status !== 'PENDING_APPROVAL') {
            buttons.push(`<button class="btn-secondary btn-sm" data-action="approve" data-app-id="${esc(app.id)}"><i class="fa-solid fa-rotate"></i> ${label}</button>`);
        }
        buttons.push(`<button class="btn-ghost btn-sm" data-action="set-status" data-status="DISMISSED" data-app-id="${esc(app.id)}">Dismiss</button>`);
    }
    if (app.status === 'APPLIED') {
        buttons.push(`<button class="btn-secondary btn-sm" data-action="set-status" data-status="INTERVIEW" data-app-id="${esc(app.id)}">Got interview</button>`);
        buttons.push(`<button class="btn-ghost btn-sm" data-action="set-status" data-status="REJECTED" data-app-id="${esc(app.id)}">Rejected</button>`);
    }
    return buttons.join('');
}
