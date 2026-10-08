// Prepare tab: interview-prep insights for one application.
import { esc } from '../utils.js';

const SECTIONS = [
    { key: 'missing_skills', title: 'Skills to bridge', icon: 'fa-triangle-exclamation', tone: 'rose' },
    { key: 'technical_topics', title: 'Topics to revise', icon: 'fa-laptop-code', tone: 'cyan' },
    { key: 'behavioral_questions', title: 'Likely questions', icon: 'fa-comments', tone: 'amber' },
];

export function renderInsights(container, data) {
    const cards = SECTIONS.map(({ key, title, icon, tone }) => {
        const items = (data[key] || []).map((text) => `<li class="insight-item ${tone}">${esc(text)}</li>`).join('');
        return `<div class="insight-card">
            <h3 class="tone-${tone}"><i class="fa-solid ${icon}"></i> ${title}</h3>
            ${items ? `<ul>${items}</ul>` : '<p class="muted small">Nothing found.</p>'}
        </div>`;
    }).join('');
    const note = data.source === 'template'
        ? '<p class="muted small">Built from the posting\'s skills (AI unavailable): add GROQ_API_KEY for tailored prep.</p>'
        : '';
    container.innerHTML = `<div class="insight-grid">${cards}</div>${note}`;
}

export function renderPrepSelect(select, applications) {
    const current = select.value;
    const relevant = applications.filter((a) => a.status !== 'DISMISSED');
    select.innerHTML = relevant.length
        ? '<option value="">Choose an application…</option>'
            + relevant.map((a) => `<option value="${esc(a.id)}">${esc(a.job_title)} @ ${esc(a.company)}</option>`).join('')
        : '<option value="">No applications yet</option>';
    if (current && relevant.some((a) => a.id === current)) select.value = current;
}
