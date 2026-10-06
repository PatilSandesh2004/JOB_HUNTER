// Job sources: company boards searched directly, and the job-alert inbox.
import { esc, timeAgo, titleCase } from '../utils.js';

const ATS_NAMES = {
    greenhouse: 'Greenhouse', lever: 'Lever', ashby: 'Ashby', workable: 'Workable',
    smartrecruiters: 'SmartRecruiters', recruitee: 'Recruitee', personio: 'Personio',
};

export function renderBoards(container, boards) {
    const watched = boards.filter((b) => b.source === 'watched');
    const discovered = boards.filter((b) => b.source === 'discovered');
    const seeds = boards.filter((b) => b.source === 'seed').length;
    const row = (b) => `
        <div class="board-row">
            <span><strong>${esc(b.company)}</strong> <span class="tag subtle">${esc(ATS_NAMES[b.ats] || b.ats)}</span></span>
            <button class="btn-ghost btn-sm" data-action="remove-board" data-ats="${esc(b.ats)}" data-slug="${esc(b.slug)}"
                    aria-label="Stop searching ${esc(b.company)}"><i class="fa-solid fa-xmark"></i></button>
        </div>`;
    container.innerHTML = `
        <h5>Watching (${watched.length})</h5>
        ${watched.map(row).join('') || '<p class="muted">No companies added yet.</p>'}
        ${discovered.length ? `<details class="board-group"><summary>Found through your searches (${discovered.length})</summary>${discovered.map(row).join('')}</details>` : ''}
        <p class="muted small">Plus ${seeds} built-in company boards.</p>`;
}

export function renderInbox(container, status) {
    if (!status.configured) {
        container.innerHTML = `
            <p class="notice warn"><i class="fa-solid fa-circle-info"></i> Not set up.</p>
            <ol class="setup-steps">
                <li>Create job alerts on LinkedIn, Indeed and/or Naukri, delivered to your email.</li>
                <li>Gmail: turn on 2-step verification, then create an <strong>app password</strong> (Google Account → Security → App passwords).</li>
                <li>Add to <code>.env</code>: <code>IMAP_USER=you@gmail.com</code> and <code>IMAP_PASSWORD=&lt;app password&gt;</code>, then restart.</li>
            </ol>
            <p class="muted small">The inbox is opened read-only. Only alert emails and replies from companies you applied to are read.</p>`;
        return;
    }
    const last = status.last_check;
    const summary = last
        ? `Last check ${esc(timeAgo(last.checked_at))}: ${last.job_alerts} alert email(s), ${last.jobs_new} new job(s), ${last.status_updates.length} status update(s).`
        : `Checks every ${status.interval_minutes} minutes${status.interval_minutes ? '' : ' (off: use Check now)'}.`;
    const errors = (last?.errors || []).map((e) => `<p class="notice error">${esc(e)}</p>`).join('');
    const recent = (status.recent || []).map((r) => `
        <li><span class="when">${esc(timeAgo(r.received_at || ''))}</span>
            ${r.kind === 'job_alert'
                ? `<strong>${esc(titleCase(r.source || ''))} alert</strong> <span class="muted">${esc(r.jobs)} job(s) · ${esc(r.subject || '')}</span>`
                : `<strong>${esc(r.company || '')}: ${esc(titleCase(r.to || ''))}</strong> <span class="muted">${esc(r.subject || '')}</span>`}
        </li>`).join('');
    container.innerHTML = `
        <p class="muted">Reading <strong>${esc(status.account)}</strong>. ${summary}</p>
        ${errors}
        ${recent ? `<ol class="inbox-recent">${recent}</ol>` : ''}`;
}
