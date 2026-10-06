// Profile form <-> CandidateProfile mapping.
import { esc, splitList } from '../utils.js';

const $ = (id) => document.getElementById(id);

export function fillProfileForm(profile) {
    const p = profile || {};
    const prefs = p.preferences || {};
    $('p-name').value = p.name || '';
    $('p-email').value = p.email || '';
    $('p-phone').value = p.phone || '';
    $('p-location').value = p.location || '';
    $('p-role').value = p.current_role || '';
    $('p-company').value = p.current_company || '';
    $('p-years').value = p.years_of_experience || '';
    $('p-linkedin').value = p.linkedin_url || '';
    $('p-github').value = p.github_url || '';
    $('p-portfolio').value = p.portfolio_url || '';
    $('p-skills').value = (p.skills || []).join(', ');
    $('p-roles').value = (prefs.preferred_roles || []).join(', ');
    $('p-locations').value = (prefs.preferred_locations || []).join(', ');
    $('p-remote').value = prefs.remote_preference || 'ANY';
    $('p-visa').value = String(Boolean(prefs.visa_sponsorship_required));
    $('p-relocate').checked = Boolean(prefs.willing_to_relocate);
    $('p-tailor').checked = Boolean(prefs.tailor_resume);
    $('p-blocked').value = (prefs.blocked_companies || []).join(', ');
    $('p-salary').value = prefs.expected_salary || '';
    $('p-notice').value = prefs.notice_period || '';

    $('skill-tags').innerHTML = (p.skills || []).map((s) => `<span class="skill-tag">${esc(s)}</span>`).join('')
        || '<span class="muted">None yet</span>';
    $('resume-status').textContent = p.resume_filename
        ? 'Resume on file. It will be attached to applications.'
        : 'No resume uploaded yet.';
}

/** Read the form back into a profile, preserving fields the form does not show (experience, education). */
export function readProfileForm(existing) {
    const base = existing || {};
    return {
        ...base,
        name: $('p-name').value.trim(),
        email: $('p-email').value.trim() || null,
        phone: $('p-phone').value.trim() || null,
        location: $('p-location').value.trim() || null,
        current_role: $('p-role').value.trim() || null,
        current_company: $('p-company').value.trim() || null,
        years_of_experience: Number($('p-years').value) || 0,
        linkedin_url: $('p-linkedin').value.trim() || null,
        github_url: $('p-github').value.trim() || null,
        portfolio_url: $('p-portfolio').value.trim() || null,
        skills: splitList($('p-skills').value),
        preferences: {
            ...(base.preferences || {}),
            preferred_roles: splitList($('p-roles').value),
            preferred_locations: splitList($('p-locations').value),
            remote_preference: $('p-remote').value,
            visa_sponsorship_required: $('p-visa').value === 'true',
            willing_to_relocate: $('p-relocate').checked,
            tailor_resume: $('p-tailor').checked,
            blocked_companies: splitList($('p-blocked').value),
            expected_salary: $('p-salary').value.trim() || null,
            notice_period: $('p-notice').value.trim() || null,
        },
    };
}

export function renderNavbar(profile) {
    const name = profile?.name || '';
    $('nav-name').textContent = name || 'No profile yet';
    $('nav-role').textContent = profile?.current_role || (name ? '' : 'Upload your resume');
    $('nav-avatar').textContent = name ? name.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase() : '?';
}

/** The answer bank list: each saved answer is editable in place. */
export function renderAnswers(container, answers) {
    if (!answers.length) {
        container.innerHTML = '<p class="muted">No saved answers yet. Add one above, or answer the questions shown on an application.</p>';
        return;
    }
    container.innerHTML = answers.map((a) => `
        <div class="answer-row" data-answer-id="${esc(a.id)}">
            <div class="answer-question">${esc(a.question)}
                ${a.source === 'suggested' ? '<span class="tag subtle" title="Accepted from an AI suggestion">ai-drafted</span>' : ''}</div>
            <input class="answer-input" value="${esc(a.answer)}" data-question="${esc(a.question)}" aria-label="Answer">
            <button class="btn-secondary btn-sm" data-action="update-answer" data-answer-id="${esc(a.id)}"><i class="fa-solid fa-floppy-disk"></i> Save</button>
            <button class="btn-ghost btn-sm" data-action="delete-answer" data-answer-id="${esc(a.id)}" aria-label="Delete answer"><i class="fa-solid fa-trash"></i></button>
        </div>`).join('');
}
