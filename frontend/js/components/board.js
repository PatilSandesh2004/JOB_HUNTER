// Applications board (Saved -> Applied -> Interview -> Offer), follow-up reminders and the progress report.
import { esc, safeUrl, timeAgo } from '../utils.js';
import { statusLabel } from './jobFeed.js';

const COLUMNS = [
    { key: 'saved', title: 'Saved', icon: 'fa-bookmark', statuses: ['SAVED'] },
    { key: 'todo', title: 'To finish', icon: 'fa-hourglass-half',
      statuses: ['PROCESSING', 'SUBMITTING', 'PENDING_APPROVAL', 'NEEDS_MANUAL', 'FAILED', 'AWAITING_CONFIRMATION'] },
    { key: 'applied', title: 'Applied', icon: 'fa-paper-plane', statuses: ['APPLIED'] },
    { key: 'interview', title: 'Interviewing', icon: 'fa-comments', statuses: ['INTERVIEW'] },
    { key: 'offer', title: 'Offer', icon: 'fa-trophy', statuses: ['OFFER'] },
    { key: 'closed', title: 'Closed', icon: 'fa-box-archive', statuses: ['REJECTED', 'DISMISSED'] },
];  // fmt: skip

function move(app, status, label, kind = 'btn-ghost') {
    return `<button class="${kind} btn-sm" data-action="set-status" data-status="${status}" data-app-id="${esc(app.id)}">${label}</button>`;
}

function cardActions(app) {
    const id = esc(app.id);
    switch (app.status) {
        case 'SAVED':
            return `<button class="btn-primary btn-sm" data-action="prepare" data-job-id="${esc(app.job_id)}">Prepare</button>
                    <button class="btn-secondary btn-sm" data-action="manual" data-job-id="${esc(app.job_id)}" data-url="${esc(safeUrl(app.application_url))}"
                        data-title="${esc(app.job_title)}" data-company="${esc(app.company)}">Apply manually</button>
                    ${move(app, 'DISMISSED', 'Remove')}`;
        case 'APPLIED':
            return `${app.follow_up_due ? `<button class="btn-primary btn-sm" data-action="follow-up" data-app-id="${id}" title="Mark that you followed up">Followed up</button>` : ''}
                    ${move(app, 'INTERVIEW', 'Interview', 'btn-secondary')}${move(app, 'REJECTED', 'Rejected')}`;
        case 'INTERVIEW':
            return `<button class="btn-secondary btn-sm" data-action="get-insights" data-app-id="${id}">Prepare</button>
                    ${move(app, 'OFFER', 'Offer', 'btn-primary')}${move(app, 'REJECTED', 'Rejected')}`;
        case 'OFFER':
            return move(app, 'REJECTED', 'Declined');
        case 'AWAITING_CONFIRMATION':
            return `${move(app, 'APPLIED', 'I applied', 'btn-primary')}${move(app, 'DISMISSED', 'Not applying')}`;
        default:
            return '<button class="btn-ghost btn-sm" data-action="show-app-details">Details</button>';
    }
}

function boardCard(app) {
    const due = app.follow_up_due ? '<span class="tag danger" title="Applied a while ago with no news">Follow up</span>' : '';
    return `<div class="board-card" data-app-id="${esc(app.id)}">
        <a class="board-card-title" href="${esc(safeUrl(app.application_url))}" target="_blank" rel="noopener noreferrer">${esc(app.job_title)}</a>
        <div class="muted small">${esc(app.company)} · ${esc(statusLabel(app.status))} · ${esc(timeAgo(app.updated_at))}</div>
        ${due}
        <div class="board-card-actions">${cardActions(app)}</div>
    </div>`;
}

export function renderBoard(container, applications) {
    if (!applications.length) {
        container.innerHTML = `<div class="empty-state"><i class="fa-solid fa-table-columns"></i>
            <p>Your board is empty. Save jobs (bookmark icon) or apply to see them here.</p></div>`;
        return;
    }
    container.innerHTML = `<div class="board">${COLUMNS.map((column) => {
        const items = applications.filter((a) => column.statuses.includes(a.status));
        return `<section class="board-column board-${column.key}">
            <h4><i class="fa-solid ${column.icon}"></i> ${column.title} <span class="muted">${items.length}</span></h4>
            ${items.map(boardCard).join('') || '<p class="muted small">Nothing here.</p>'}
        </section>`;
    }).join('')}</div>`;
}

export function renderFollowUps(container, applications) {
    const due = applications.filter((a) => a.follow_up_due);
    container.hidden = !due.length;
    if (!due.length) return;
    container.innerHTML = `<i class="fa-solid fa-bell"></i> <strong>${due.length} application${due.length === 1 ? '' : 's'} with no reply for a while:</strong>
        ${due.slice(0, 5).map((a) => `${esc(a.job_title)} at ${esc(a.company)}`).join(', ')}${due.length > 5 ? '…' : ''}.
        A short, polite follow-up email often gets a response.`;
}

export function renderReport(container, report) {
    if (!report) {
        container.innerHTML = '';
        return;
    }
    const p = report.period;
    const t = report.totals;
    const kinds = report.by_kind.slice(0, 5).map((k) => `<li><strong>${esc(k.kind)}</strong>: ${k.applied} applied, ${k.interviews} interview${k.interviews === 1 ? '' : 's'} (${k.interview_rate}%)</li>`).join('');
    container.innerHTML = `
        <div class="report-grid">
            <div class="report-stat"><span class="stat-value">${p.applied}</span><span class="stat-label">Applied this week</span></div>
            <div class="report-stat"><span class="stat-value">${p.interviews}</span><span class="stat-label">Interviews this week</span></div>
            <div class="report-stat"><span class="stat-value">${p.offers}</span><span class="stat-label">Offers this week</span></div>
            <div class="report-stat"><span class="stat-value">${t.response_rate}%</span><span class="stat-label">Reply rate (all time)</span></div>
            <div class="report-stat"><span class="stat-value">${t.interview_rate}%</span><span class="stat-label">Interview rate</span></div>
            <div class="report-stat"><span class="stat-value">${t.saved}</span><span class="stat-label">Saved to apply</span></div>
        </div>
        ${kinds ? `<p class="muted small" style="margin-top:0.75rem">Which kinds of roles get replies:</p><ul class="report-kinds">${kinds}</ul>` : ''}`;
}
