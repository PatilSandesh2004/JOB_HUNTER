// Network tab: people to contact at a company, and the outreach-message modal.
import { esc, safeUrl } from '../utils.js';

function draftButton(name, role, company, jobTitle) {
    return `<button class="btn-primary btn-sm" data-action="draft-outreach" data-contact-name="${esc(name)}"
                data-contact-role="${esc(role)}" data-company="${esc(company)}" data-job-title="${esc(jobTitle || '')}">
                <i class="fa-solid fa-wand-magic-sparkles"></i> Draft note</button>`;
}

function personName(title) {
    // Search titles look like "Jane Doe - Recruiter - Acme"; the first part is the name.
    return title.split(/\s[-–—|]\s/)[0].trim();
}

function peopleColumn({ title, icon, kind, people, searchUrl, company, jobTitle, emptyText }) {
    const items = people.map((p) => `
        <li class="contact-item">
            <div class="contact-head">
                <a href="${esc(safeUrl(p.url))}" target="_blank" rel="noopener noreferrer"><i class="fa-brands fa-linkedin"></i> ${esc(p.title)}</a>
                ${draftButton(personName(p.title), kind, company, jobTitle)}
            </div>
            ${p.snippet ? `<p class="muted small">${esc(p.snippet)}</p>` : ''}
        </li>`).join('');
    return `
    <div class="contact-column">
        <div class="contact-column-head">
            <h3><i class="fa-solid ${icon}"></i> ${title}</h3>
            <a href="${esc(safeUrl(searchUrl))}" target="_blank" rel="noopener noreferrer" class="btn-secondary btn-sm"><i class="fa-brands fa-linkedin"></i> Search LinkedIn</a>
        </div>
        ${items ? `<ul class="contact-list">${items}</ul>` : `<p class="muted small">${emptyText}</p>`}
    </div>`;
}

export function renderContacts(container, data, { company, jobTitle }) {
    const connections = (data.connections || []).map((c) => `
        <li class="contact-item">
            <div class="contact-head">
                <span><strong>${esc(c.first_name)} ${esc(c.last_name)}</strong><br><span class="muted small">${esc(c.position)}</span></span>
                ${draftButton(c.first_name, c.position || 'Connection', company, jobTitle)}
            </div>
        </li>`).join('');
    container.innerHTML = `
    ${jobTitle ? `<p class="muted">People at <strong>${esc(company)}</strong> for the <strong>${esc(jobTitle)}</strong> role.</p>` : ''}
    <div class="contact-grid">
        <div class="contact-column">
            <div class="contact-column-head"><h3><i class="fa-solid fa-user-group"></i> Your connections</h3></div>
            ${connections ? `<ul class="contact-list">${connections}</ul>`
                : '<p class="muted small">None found. Import your LinkedIn connections above to see who you already know here.</p>'}
        </div>
        ${peopleColumn({
            title: 'Recruiters &amp; HR', icon: 'fa-user-tie', kind: 'Recruiter', people: data.recruiters || [],
            searchUrl: data.linkedin_search_hr, company, jobTitle,
            emptyText: `No public profiles found. Use "Search LinkedIn" to browse recruiters at ${esc(company)}.`,
        })}
        ${peopleColumn({
            title: 'Team members', icon: 'fa-briefcase', kind: 'Employee', people: data.employees || [],
            searchUrl: data.linkedin_search_emp, company, jobTitle,
            emptyText: `No public profiles found. Use "Search LinkedIn" to find people on the team at ${esc(company)}.`,
        })}
    </div>`;
}

export function outreachHtml(data) {
    const note = data.linkedin_note || '';
    return `
    <div class="outreach">
        <div class="outreach-block">
            <div class="outreach-head">
                <h4><i class="fa-brands fa-linkedin"></i> Connection note <span class="muted small" id="li-note-count">${note.length}/300</span></h4>
                <button class="btn-secondary btn-sm" data-action="copy-text" data-target="li-note-text"><i class="fa-solid fa-copy"></i> Copy</button>
            </div>
            <textarea id="li-note-text" rows="4" maxlength="300">${esc(note)}</textarea>
        </div>
        <div class="outreach-block">
            <div class="outreach-head">
                <h4><i class="fa-solid fa-envelope"></i> Message / email</h4>
                <button class="btn-secondary btn-sm" data-action="copy-text" data-target="email-msg-text"><i class="fa-solid fa-copy"></i> Copy</button>
            </div>
            <textarea id="email-msg-text" rows="8">${esc(data.email_message || '')}</textarea>
        </div>
        ${data.source === 'template' ? '<p class="muted small">Written from a template (AI unavailable). Personalise it before sending.</p>' : ''}
    </div>`;
}
