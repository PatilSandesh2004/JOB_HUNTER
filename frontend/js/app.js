import { api, auth, setToken } from './api.js';
import { renderApplications } from './components/approvalQueue.js';
import { renderHealth } from './components/health.js';
import { renderJobFeed } from './components/jobFeed.js';
import { renderBoards, renderInbox } from './components/sources.js';
import { fillProfileForm, readProfileForm, renderAnswers, renderNavbar } from './components/profile.js';
import { AWAITING, IN_FLIGHT, NEEDS_REVIEW, SUBMITTED, store } from './state.js';
import { closeModal, esc, openModal, setBusy, splitList, toast } from './utils.js';
import { setupLocationSuggest } from './components/locationSuggest.js';

const $ = (id) => document.getElementById(id);
const POLL_MS = 3000;
let pollTimer = null;

// ---------------------------------------------------------------- rendering & state subscription
let renderedAnswers = null;
store.subscribe((state) => {
    renderJobFeed($('jobs-container'), state);
    renderApplications($('applications-list'), state.applications);
    renderNavbar(state.profile);
    updateAnalytics(state.applications);

    // Update Profile Settings form if profile loaded
    if (state.profile) {
        fillProfileForm(state.profile);
        updatePrepareAppDropdown(state.applications);
    }

    if (state.answers !== renderedAnswers) {
        renderAnswers($('answer-list'), state.answers);
        renderedAnswers = state.answers;
    }

    $('stat-total').textContent = state.jobs.length;
    $('stat-high').textContent = state.jobs.filter((j) => j.match?.overall_match >= 70).length;
    $('stat-visa').textContent = state.jobs.filter((j) => j.job.visa_sponsorship.status === 'YES').length;
    $('stat-applied').textContent = state.applications.filter((a) => SUBMITTED.has(a.status)).length;

    const review = state.applications.filter((a) => NEEDS_REVIEW.has(a.status) || a.status === AWAITING).length;
    $('review-count').textContent = review;
    $('review-count').hidden = review === 0;

    schedulePolling(state.applications.some(
        (a) => IN_FLIGHT.has(a.status) || (a.status === AWAITING && a.cover_letter === null),
    ));
});

function updateAnalytics(applications) {
    const totalApplied = applications.filter(a => SUBMITTED.has(a.status)).length;
    const shortlisted = applications.filter(a => a.status === 'INTERVIEW').length;
    const reviewCount = applications.filter(a => NEEDS_REVIEW.has(a.status)).length;
    const dismissedCount = applications.filter(a => a.status === 'DISMISSED' || a.status === 'REJECTED').length;
    const lettersCount = applications.filter(a => a.cover_letter !== null).length;

    const rate = totalApplied > 0 ? Math.round((shortlisted / totalApplied) * 100) : 0;

    if ($('analytics-total')) $('analytics-total').textContent = totalApplied;
    if ($('analytics-shortlisted')) $('analytics-shortlisted').textContent = shortlisted;
    if ($('analytics-rate')) $('analytics-rate').textContent = `${rate}%`;
    if ($('analytics-letters')) $('analytics-letters').textContent = lettersCount;

    if ($('count-applied')) $('count-applied').textContent = Math.max(0, totalApplied - shortlisted);
    if ($('count-interview')) $('count-interview').textContent = shortlisted;
    if ($('count-review')) $('count-review').textContent = reviewCount;
    if ($('count-dismissed')) $('count-dismissed').textContent = dismissedCount;

    const totalAll = applications.length || 1;
    if ($('bar-applied')) $('bar-applied').style.width = `${(Math.max(0, totalApplied - shortlisted) / totalAll) * 100}%`;
    if ($('bar-interview')) $('bar-interview').style.width = `${(shortlisted / totalAll) * 100}%`;
    if ($('bar-review')) $('bar-review').style.width = `${(reviewCount / totalAll) * 100}%`;
    if ($('bar-dismissed')) $('bar-dismissed').style.width = `${(dismissedCount / totalAll) * 100}%`;

    if ($('pipeline-status-text')) $('pipeline-status-text').textContent = `${applications.length} Total Tracked Applications`;
}

function updatePrepareAppDropdown(applications) {
    const select = $('prepare-app-select');
    if (!select) return;
    const currentVal = select.value;
    
    const relevant = applications.filter((a) => a.status !== 'DISMISSED');
    if (!relevant.length) {
        select.innerHTML = `<option value="">No applications found yet</option>`;
        return;
    }

    select.innerHTML = `<option value="">Choose an application to generate interview prep...</option>` +
        relevant.map(a => `<option value="${esc(a.id)}">${esc(a.job_title)} @ ${esc(a.company)} (${esc(a.status)})</option>`).join('');

    if (currentVal) select.value = currentVal;
}

function schedulePolling(active) {
    if (active && !pollTimer) {
        pollTimer = setInterval(refreshApplications, POLL_MS);
    } else if (!active && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

async function refreshApplications() {
    try {
        const before = new Map(store.state.applications.map((a) => [a.id, a.status]));
        const applications = await api.listApplications();
        applications.forEach((a) => {
            const previous = before.get(a.id);
            if (previous && IN_FLIGHT.has(previous) && !IN_FLIGHT.has(a.status)) announce(a);
        });
        store.set({ applications });
    } catch (err) {
        console.warn('Polling failed', err);
    }
}

function announce(app) {
    const messages = {
        PENDING_APPROVAL: [`Form filled for ${app.job_title}. Review and approve.`, 'info'],
        APPLIED: [`Submitted: ${app.job_title} at ${app.company}`, 'success'],
        NEEDS_MANUAL: [`${app.job_title} needs your attention: ${app.error || ''}`, 'warn'],
        FAILED: [`${app.job_title} failed: ${app.error || 'unknown error'}`, 'error'],
    };
    const [text, kind] = messages[app.status] || [`${app.job_title}: ${app.status}`, 'info'];
    toast(text, kind);
}

// ---------------------------------------------------------------- navigation
function showTab(tabId) {
    document.querySelectorAll('.nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.tab === tabId));
    document.querySelectorAll('.tab-content').forEach((c) => c.classList.toggle('active', c.id === tabId));
    if (tabId === 'profile-tab') {
        loadHealth();
        loadSources();
    }
}

document.querySelectorAll('.nav-btn').forEach((btn) => btn.addEventListener('click', () => showTab(btn.dataset.tab)));

$('job-filters').addEventListener('click', (e) => {
    const btn = e.target.closest('.filter-btn');
    if (!btn) return;
    document.querySelectorAll('.filter-btn').forEach((b) => b.classList.toggle('active', b === btn));
    store.set({ jobFilter: btn.dataset.filter });
});

// ---------------------------------------------------------------- search
async function runSearch(button) {
    const roleInputVal = $('role-input').value.trim();
    const locInputVal = $('location-input').value.trim();
    const fromResume = !roleInputVal && store.state.profile;

    const params = {
        roles: fromResume ? [] : splitList(roleInputVal),
        locations: fromResume ? [] : splitList(locInputVal),
        experience: $('exp-input')?.value || 'ANY',
        posted_within: $('posted-input')?.value || 'any',
        remote_only: $('remote-toggle').checked,
        sponsorship_required: $('visa-toggle').checked,
        strict_location: $('exact-toggle').checked,
    };

    setBusy(button, true, 'Searching…');
    $('search-meta').title = '';
    $('search-meta').textContent = fromResume
        ? 'Searching matching jobs from your profile & resume…'
        : 'Planning search…';
    
    const done = [];
    const showProgress = (stage) => {
        done.push(`✓ ${stage.label}${stage.detail ? ` (${stage.detail})` : ''}`);
        $('search-meta').textContent = `${done.join(' · ')} …`;
    };
    try {
        const result = await api.searchStream(params, showProgress);
        store.set({ jobs: result.results, jobFilter: 'all' });
        document.querySelectorAll('.filter-btn').forEach((b) => b.classList.toggle('active', b.dataset.filter === 'all'));
        if (result.roles?.length) $('role-input').value = result.roles.join(', ');
        if (result.locations?.length) $('location-input').value = result.locations.join(', ');
        syncLocationClear();
        describeSearch(result);
        if (!store.state.profile) toast('Upload your resume or profile to get match scores', 'info');
    } catch (err) {
        $('search-meta').textContent = '';
        toast(`Search failed: ${err.message}`, 'error');
    } finally {
        setBusy(button, false);
    }
}

function describeSearch(result) {
    const removed = Object.entries(result.filtered_out || {}).map(([why, n]) => `${n} ${why}`);
    const parts = [
        `${result.total_results} jobs found`,
        removed.length ? `filtered out: ${removed.join(', ')}` : '',
        result.errors.length ? `${result.errors.length} source issue(s)` : '',
    ];
    $('search-meta').textContent = parts.filter(Boolean).join(' · ');
}

$('search-form').addEventListener('submit', (e) => {
    e.preventDefault();
    runSearch($('btn-search'));
});

// ---------------------------------------------------------------- location suggestions + resume choice
const syncLocationClear = setupLocationSuggest($('location-input'), $('location-suggestions'), $('location-clear'));
const resumeChoice = $('resume-choice');
if (resumeChoice) {
    resumeChoice.value = localStorage.getItem('resumeChoice') || (store.state.profile?.preferences?.tailor_resume ? 'tailored' : 'original');
    resumeChoice.addEventListener('change', () => localStorage.setItem('resumeChoice', resumeChoice.value));
}
const wantsTailored = () => resumeChoice ? resumeChoice.value === 'tailored' : false;

// ---------------------------------------------------------------- job + application actions
document.addEventListener('click', async (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    const { action, jobId, appId } = target.dataset;

    if (action === 'goto-applications') return showTab('applications-tab');
    if (action === 'goto-profile') return showTab('profile-tab');
    if (action === 'screenshot') return showImage('Form screenshot', api.screenshotUrl(appId));
    if (action === 'step-screenshot') return showImage('Agent screenshot', api.stepScreenshotUrl(appId, target.dataset.name));
    if (action === 'open-resume') return openPdf(api.tailoredResumeUrl(appId));
    if (action === 'update-answer' || action === 'delete-answer') return editAnswer(target, action);
    if (action === 'hide-job') return hideJob(target.dataset.jobId);
    if (action === 'block-company') return blockCompany(target.dataset.company);
    if (action === 'get-insiders') {
        showTab('network-tab');
        $('network-company-input').value = target.dataset.company || '';
        return runNetworkSearch(target.dataset.jobId, target.dataset.company);
    }
    if (action === 'get-insights') {
        showTab('prepare-tab');
        if (appId) {
            $('prepare-app-select').value = appId;
            return renderPrepInsightsForApp(appId);
        }
    }
    if (action === 'draft-outreach') {
        return showOutreachModal(target.dataset.contactName, target.dataset.contactRole, target.dataset.company);
    }
    if (action === 'remove-board') return removeBoard(target);
    if (action === 'dismiss-modal') return closeModal();
    if (action === 'copy-letter') return copyLetter(appId);
    if (action === 'manual') return startManualApply(target);

    const handlers = {
        prepare: () => api.createApplication(jobId, 'review', wantsTailored()),
        'auto-apply': () => api.createApplication(jobId, 'auto', wantsTailored()),
        approve: () => api.approveApplication(appId),
        'set-status': () => api.updateApplication(appId, { status: target.dataset.status }),
        'save-letter': () => {
            const textarea = document.querySelector(`textarea[data-app-id="${CSS.escape(appId)}"]`);
            textarea.dataset.dirty = '0';
            return api.updateApplication(appId, { cover_letter: textarea.value });
        },
        'save-answers': () => saveQuestionAnswers(target.closest('.app-card'), appId),
    };

    if (!handlers[action]) return;

    setBusy(target, true, '');
    try {
        if (target.closest('#modal')) closeModal();
        if (action === 'approve') {
            const textarea = document.querySelector(`textarea[data-app-id="${CSS.escape(appId)}"]`);
            if (textarea?.dataset.dirty === '1') {
                await api.updateApplication(appId, { cover_letter: textarea.value });
                textarea.dataset.dirty = '0';
            }
        }
        await handlers[action]();
        if (action === 'prepare') toast('Agent started: drafting cover letter and pre-filling form', 'info');
        if (action === 'save-letter') toast('Cover letter saved', 'success');
        if (action === 'save-answers') toast('Answers saved. The agent is filling the form again.', 'success');
        if (action === 'set-status') toast('Application status updated', 'success');
        await refreshApplications();
    } catch (err) {
        toast(err.message, 'error');
    } finally {
        setBusy(target, false);
    }
});

// ---------------------------------------------------------------- Network Tab Search & Outreach
$('network-search-form')?.addEventListener('submit', (e) => {
    e.preventDefault();
    const company = $('network-company-input').value.trim();
    if (company) runNetworkSearch(null, company);
});

async function runNetworkSearch(jobId, company) {
    const container = $('network-results');
    container.innerHTML = `<p class="muted" style="padding: 1.5rem; text-align: center;"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><br><br>Searching recruiters, hiring managers &amp; referral contacts for <strong>${esc(company)}</strong>...</p>`;
    try {
        const data = jobId ? await api.getInsiders(jobId) : await api.getCompanyContacts(company);
        const searchHrUrl = data.linkedin_search_hr || `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(company + " Recruiter HR Talent Acquisition")}`;
        const searchEmpUrl = data.linkedin_search_emp || `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(company + " Software Engineer AI Manager")}`;

        let html = `<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem;">`;
        
        // Recruiters column
        html += `<div style="background: var(--bg-card); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-color);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                <h3 style="color: var(--accent-cyan); font-size: 1.1rem;"><i class="fa-solid fa-user-tie"></i> Recruiters &amp; HR</h3>
                <a href="${esc(searchHrUrl)}" target="_blank" rel="noopener" class="btn-secondary btn-sm" style="text-decoration:none;"><i class="fa-brands fa-linkedin"></i> Search LinkedIn</a>
            </div>`;
        if (data.recruiters && data.recruiters.length > 0) {
            html += `<ul style="list-style:none;padding:0;">` + data.recruiters.map(r => `
                <li style="margin-bottom:1rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--border-color)">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                        <a href="${esc(r.url)}" target="_blank" rel="noopener" style="color: var(--primary); font-weight: 600; text-decoration: none; display: flex; align-items: center; gap: 0.5rem;">
                            <i class="fa-brands fa-linkedin" style="color: #0a66c2;"></i> ${esc(r.title)}
                        </a>
                        <button class="btn-primary btn-sm" data-action="draft-outreach" data-contact-name="${esc(r.title.split('-')[0].trim())}" data-contact-role="Recruiter" data-company="${esc(company)}"><i class="fa-solid fa-wand-magic-sparkles"></i> Draft Note</button>
                    </div>
                    <p class="muted small" style="margin-top: 0.25rem;">${esc(r.snippet)}</p>
                </li>
            `).join('') + `</ul>`;
        } else {
            html += `<p class="muted small">Click "Search LinkedIn" above to browse recruiters and TA contacts at ${esc(company)} directly on LinkedIn.</p>`;
        }
        html += `</div>`;

        // Employees & Referral contacts column
        html += `<div style="background: var(--bg-card); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-color);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                <h3 style="color: var(--accent-amber); font-size: 1.1rem;"><i class="fa-solid fa-briefcase"></i> Employees &amp; Referrals</h3>
                <a href="${esc(searchEmpUrl)}" target="_blank" rel="noopener" class="btn-secondary btn-sm" style="text-decoration:none;"><i class="fa-brands fa-linkedin"></i> Search LinkedIn</a>
            </div>`;
        if (data.employees && data.employees.length > 0) {
            html += `<ul style="list-style:none;padding:0;">` + data.employees.map(e => `
                <li style="margin-bottom:1rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--border-color)">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                        <a href="${esc(e.url)}" target="_blank" rel="noopener" style="color: var(--accent-amber); font-weight: 600; text-decoration: none; display: flex; align-items: center; gap: 0.5rem;">
                            <i class="fa-brands fa-linkedin" style="color: #0a66c2;"></i> ${esc(e.title)}
                        </a>
                        <button class="btn-primary btn-sm" data-action="draft-outreach" data-contact-name="${esc(e.title.split('-')[0].trim())}" data-contact-role="Employee" data-company="${esc(company)}"><i class="fa-solid fa-wand-magic-sparkles"></i> Draft Note</button>
                    </div>
                    <p class="muted small" style="margin-top: 0.25rem;">${esc(e.snippet)}</p>
                </li>
            `).join('') + `</ul>`;
        } else {
            html += `<p class="muted small">Click "Search LinkedIn" above to find team members and potential referral contacts at ${esc(company)}.</p>`;
        }
        html += `</div>`;

        // Direct Connections column
        html += `<div style="background: var(--bg-card); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-color);">
            <h3 style="margin-bottom: 1rem; color: var(--accent-emerald); font-size: 1.1rem;"><i class="fa-solid fa-users"></i> Direct Connections</h3>`;
        if (data.connections && data.connections.length > 0) {
            html += `<ul style="list-style:none;padding:0;">` + data.connections.map(c => `
                <li style="margin-bottom:0.75rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong>${esc(c.first_name)} ${esc(c.last_name)}</strong><br>
                        <span class="muted small">${esc(c.position)}</span>
                    </div>
                    <button class="btn-primary btn-sm" data-action="draft-outreach" data-contact-name="${esc(c.first_name)}" data-contact-role="${esc(c.position)}" data-company="${esc(company)}"><i class="fa-solid fa-wand-magic-sparkles"></i> Draft Note</button>
                </li>
            `).join('') + `</ul>`;
        } else {
            html += `<p class="muted small">No direct connections matched in your candidate database.</p>`;
        }
        html += `</div></div>`;

        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<p class="notice error">Failed to search contacts: ${esc(err.message)}</p>`;
    }
}

async function showOutreachModal(contactName, contactRole, company) {
    try {
        openModal(`Outreach Generator — ${esc(company)}`, `<p class="muted" style="padding: 1.5rem; text-align: center;"><i class="fa-solid fa-wand-magic-sparkles fa-pulse fa-2x"></i><br><br>Drafting personalized LinkedIn &amp; email outreach notes for ${esc(contactName || company)}...</p>`);
        const data = await api.generateOutreach({ contact_name: contactName, contact_role: contactRole, company: company });
        
        let html = `<div style="display: flex; flex-direction: column; gap: 1.5rem;">
            <div style="background: var(--bg-card); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-color);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <h4 style="color: var(--accent-cyan);"><i class="fa-brands fa-linkedin"></i> LinkedIn Invite Note (under 280 chars)</h4>
                    <button class="btn-secondary btn-sm" id="btn-copy-li"><i class="fa-solid fa-copy"></i> Copy Note</button>
                </div>
                <textarea id="li-note-text" rows="4" style="width: 100%; background: var(--bg-main); color: var(--text-main); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 0.75rem; font-family: var(--font-sans); outline: none;">${esc(data.linkedin_note)}</textarea>
            </div>

            <div style="background: var(--bg-card); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-color);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <h4 style="color: var(--accent-emerald);"><i class="fa-solid fa-envelope"></i> Direct Email / InMail Message</h4>
                    <button class="btn-secondary btn-sm" id="btn-copy-email"><i class="fa-solid fa-copy"></i> Copy Email</button>
                </div>
                <textarea id="email-msg-text" rows="7" style="width: 100%; background: var(--bg-main); color: var(--text-main); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 0.75rem; font-family: var(--font-sans); outline: none;">${esc(data.email_message)}</textarea>
            </div>
        </div>`;
        
        openModal(`Outreach Message for ${esc(contactName || company)}`, html);

        $('btn-copy-li')?.addEventListener('click', () => {
            navigator.clipboard.writeText($('li-note-text').value);
            toast('LinkedIn note copied!', 'success');
        });
        $('btn-copy-email')?.addEventListener('click', () => {
            navigator.clipboard.writeText($('email-msg-text').value);
            toast('Email message copied!', 'success');
        });
    } catch (err) {
        toast(`Outreach generation failed: ${err.message}`, 'error');
        closeModal();
    }
}

// ---------------------------------------------------------------- Prepare Tab Insights
$('btn-generate-prep')?.addEventListener('click', () => {
    const appId = $('prepare-app-select').value;
    if (!appId) return toast('Select an application first', 'warn');
    renderPrepInsightsForApp(appId);
});

async function renderPrepInsightsForApp(appId) {
    const container = $('prep-insights-view');
    const app = store.state.applications.find(a => a.id === appId);
    const company = app ? app.company : 'Company';

    container.innerHTML = `<p class="muted" style="padding: 2rem; text-align: center;"><i class="fa-solid fa-brain fa-pulse fa-2x"></i><br><br>Analyzing job requirements against your profile to generate interview preparation guidelines...</p>`;

    try {
        const data = await api.getApplicationInsights(appId);
        let html = `<div class="insights-container" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem;">`;

        html += `<div style="background: var(--bg-card); padding: 1.5rem; border-radius: var(--radius-md); border: 1px solid var(--border-color);">
            <h3 style="color: var(--accent-rose); margin-bottom: 1rem;"><i class="fa-solid fa-triangle-exclamation"></i> Skills to Bridge</h3>
            <ul style="list-style:none;padding:0;">` + data.missing_skills.map(s => `
                <li style="margin-bottom:0.75rem; background: rgba(244, 63, 94, 0.1); padding: 0.75rem; border-radius: var(--radius-sm); border-left: 4px solid var(--accent-rose); font-size: 0.95rem;">${esc(s)}</li>
            `).join('') + `</ul>
        </div>`;

        html += `<div style="background: var(--bg-card); padding: 1.5rem; border-radius: var(--radius-md); border: 1px solid var(--border-color);">
            <h3 style="color: var(--accent-cyan); margin-bottom: 1rem;"><i class="fa-solid fa-laptop-code"></i> Technical Topics to Study</h3>
            <ul style="list-style:none;padding:0;">` + data.technical_topics.map(t => `
                <li style="margin-bottom:0.75rem; background: rgba(6, 182, 212, 0.1); padding: 0.75rem; border-radius: var(--radius-sm); border-left: 4px solid var(--accent-cyan); font-size: 0.95rem;">${esc(t)}</li>
            `).join('') + `</ul>
        </div>`;

        html += `<div style="background: var(--bg-card); padding: 1.5rem; border-radius: var(--radius-md); border: 1px solid var(--border-color);">
            <h3 style="color: var(--accent-amber); margin-bottom: 1rem;"><i class="fa-solid fa-comments"></i> Behavioral Prep</h3>
            <ul style="list-style:none;padding:0;">` + data.behavioral_questions.map(q => `
                <li style="margin-bottom:0.75rem; background: rgba(245, 158, 11, 0.1); padding: 0.75rem; border-radius: var(--radius-sm); border-left: 4px solid var(--accent-amber); font-size: 0.95rem;">${esc(q)}</li>
            `).join('') + `</ul>
        </div>`;

        html += `</div>`;
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<div class="notice error"><i class="fa-solid fa-circle-exclamation"></i> Could not generate insights: ${esc(err.message)}</div>`;
    }
}

// ---------------------------------------------------------------- Profile, Resumes & Initial Load
async function init() {
    try {
        const [profile, jobs, applications, answers] = await Promise.all([
            api.getProfile(),
            api.listJobs(),
            api.listApplications(),
            api.listAnswers(),
        ]);
        store.set({ profile, jobs, applications, answers });
        if (profile) {
            fillProfileForm(profile);
            if (profile.target_roles?.length && !$('role-input').value) {
                $('role-input').value = profile.target_roles.join(', ');
            }
            if (profile.preferred_locations?.length && !$('location-input').value) {
                $('location-input').value = profile.preferred_locations.join(', ');
            }
        }
    } catch (err) {
        console.warn('Initial load failed:', err);
    }
}

// Upload handlers: Resume Upload Auto-fills Profile Settings
$('resume-input')?.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
        toast('Parsing resume and auto-filling profile...', 'info');
        const res = await api.uploadResume(file);
        store.set({ profile: res.candidate });
        fillProfileForm(res.candidate);

        // Pre-fill main job search inputs from extracted profile
        if (res.candidate.preferences?.preferred_roles?.length) {
            $('role-input').value = res.candidate.preferences.preferred_roles.join(', ');
        } else if (res.candidate.current_role) {
            $('role-input').value = res.candidate.current_role;
        }
        if (res.candidate.preferences?.preferred_locations?.length) {
            $('location-input').value = res.candidate.preferences.preferred_locations.join(', ');
        } else if (res.candidate.location) {
            $('location-input').value = res.candidate.location;
        }

        toast('Resume uploaded! Profile Settings auto-filled successfully.', 'success');
    } catch (err) {
        toast(`Resume upload failed: ${err.message}`, 'error');
    }
});

$('profile-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        const data = readProfileForm();
        const saved = await api.saveProfile(data);
        store.set({ profile: saved });
        toast('Profile Settings saved successfully', 'success');
    } catch (err) {
        toast(`Save failed: ${err.message}`, 'error');
    }
});

init();
