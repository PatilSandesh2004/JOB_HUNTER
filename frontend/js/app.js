import { api, auth, setToken } from './api.js';
import { renderApplications } from './components/approvalQueue.js';
import { renderHealth } from './components/health.js';
import { renderJobFeed } from './components/jobFeed.js';
import { fillProfileForm, readProfileForm, renderAnswers, renderNavbar } from './components/profile.js';
import { AWAITING, IN_FLIGHT, NEEDS_REVIEW, SUBMITTED, store } from './state.js';
import { closeModal, esc, openModal, setBusy, splitList, toast } from './utils.js';

const $ = (id) => document.getElementById(id);
const POLL_MS = 3000;
let pollTimer = null;

// ---------------------------------------------------------------- rendering
let renderedAnswers = null;
store.subscribe((state) => {
    renderJobFeed($('jobs-container'), state);
    renderApplications($('applications-list'), state.applications);
    renderNavbar(state.profile);
    // Only when the bank itself changed, so polling never wipes an answer being edited.
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
    if (tabId === 'system-tab') loadHealth();
}

document.querySelectorAll('.nav-btn').forEach((btn) => btn.addEventListener('click', () => showTab(btn.dataset.tab)));

$('job-filters').addEventListener('click', (e) => {
    const btn = e.target.closest('.filter-btn');
    if (!btn) return;
    document.querySelectorAll('.filter-btn').forEach((b) => b.classList.toggle('active', b === btn));
    store.set({ jobFilter: btn.dataset.filter });
});

// ---------------------------------------------------------------- search
async function runSearch(button, { fromResume = false } = {}) {
    const params = {
        roles: fromResume ? [] : splitList($('role-input').value),
        locations: fromResume ? [] : splitList($('location-input').value),
        remote_only: $('remote-toggle').checked,
        sponsorship_required: $('visa-toggle').checked,
        strict_location: $('exact-toggle').checked,
    };
    if (fromResume && !store.state.profile) {
        showTab('profile-tab');
        return toast('Upload your resume first, then search from it', 'warn');
    }
    if (!fromResume && !params.roles.length) return toast('Enter at least one role, or use "From my resume"', 'warn');

    setBusy(button, true, 'Searching…');
    $('search-meta').title = '';
    $('search-meta').textContent = fromResume
        ? 'Building searches from your resume (roles, seniority, skills, location)…'
        : 'Planning searches…';
    // Each finished stage is appended as it streams in: "✓ Searching job boards (54 postings found) · …"
    const done = [];
    const showProgress = (stage) => {
        done.push(`✓ ${stage.label}${stage.detail ? ` (${stage.detail})` : ''}`);
        $('search-meta').textContent = `${done.join(' · ')} …`;
    };
    try {
        const result = await api.searchStream(params, showProgress);
        // Show exactly this search's results; older searches stay stored but out of the way.
        store.set({ jobs: result.results, jobFilter: 'all' });
        document.querySelectorAll('.filter-btn').forEach((b) => b.classList.toggle('active', b.dataset.filter === 'all'));
        $('role-input').value = result.roles.join(', ');
        $('location-input').value = result.locations.join(', ');
        describeSearch(result);
        if (!store.state.profile) toast('Add your profile to get match scores', 'info');
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
        `${result.total_results} jobs in ${result.locations.join(', ') || 'any location'}`,
        removed.length ? `filtered out: ${removed.join(', ')}` : '',
        result.errors.length ? `${result.errors.length} source issue(s), hover for details` : '',
        `searched: ${result.queries.join(' | ')}`,
    ];
    $('search-meta').textContent = parts.filter(Boolean).join(' · ');
    $('search-meta').title = result.errors.join('\n');
}

$('search-form').addEventListener('submit', (e) => {
    e.preventDefault();
    runSearch($('btn-search'));
});
$('btn-auto-search').addEventListener('click', () => runSearch($('btn-auto-search'), { fromResume: true }));

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
    if (action === 'dismiss-modal') return closeModal();
    if (action === 'copy-letter') return copyLetter(appId);
    if (action === 'manual') return startManualApply(target);
    if (action === 'auto-apply' && !confirm('Auto-apply submits the form without your review when it is complete and has no CAPTCHA. Continue?')) {
        return;
    }

    const handlers = {
        prepare: () => api.createApplication(jobId, 'review'),
        'auto-apply': () => api.createApplication(jobId, 'auto'),
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
        // Approving submits the saved letter, so persist any unsaved edits first.
        if (action === 'approve') {
            const textarea = document.querySelector(`textarea[data-app-id="${CSS.escape(appId)}"]`);
            if (textarea?.dataset.dirty === '1') {
                await api.updateApplication(appId, { cover_letter: textarea.value });
                textarea.dataset.dirty = '0';
            }
        }
        await handlers[action]();
        if (action === 'prepare' || action === 'auto-apply') toast('Agent started: writing cover letter and filling the form', 'info');
        if (action === 'save-letter') toast('Cover letter saved', 'success');
        if (action === 'save-answers') toast('Answers saved. The agent is filling the form again.', 'success');
        if (action === 'set-status') {
            const done = { APPLIED: 'Moved to Applied', DISMISSED: 'Dismissed', INTERVIEW: 'Marked as interview', REJECTED: 'Marked as rejected' };
            toast(done[target.dataset.status] || 'Updated', 'success');
        }
        await refreshApplications();
    } catch (err) {
        toast(err.message, 'error');
    } finally {
        setBusy(target, false);
    }
});

// ---------------------------------------------------------------- answers & resumes
/** Save the answers typed on an application card to the answer bank, then re-fill that form. */
async function saveQuestionAnswers(card, appId) {
    const inputs = [...card.querySelectorAll('[data-question-input]')];
    const answers = inputs
        .filter((el) => el.value.trim())
        .map((el) => ({
            question: el.dataset.label,
            answer: el.value.trim(),
            source: el.value.trim() === el.dataset.suggestion ? 'suggested' : 'user',
        }));
    if (!answers.length) throw new Error('Answer at least one question first');
    store.set({ answers: await api.saveAnswers(answers) });
    inputs.forEach((el) => { el.dataset.dirty = '0'; });
    return api.refillApplication(appId);
}

async function editAnswer(button, action) {
    const row = button.closest('.answer-row');
    setBusy(button, true, '');
    try {
        if (action === 'delete-answer') {
            await api.deleteAnswer(button.dataset.answerId);
            store.set({ answers: store.state.answers.filter((a) => a.id !== button.dataset.answerId) });
            toast('Answer removed', 'success');
        } else {
            const input = row.querySelector('.answer-input');
            store.set({ answers: await api.saveAnswers([{ question: input.dataset.question, answer: input.value }]) });
            toast(input.value.trim() ? 'Answer saved' : 'Answer removed', 'success');
        }
    } catch (err) {
        toast(err.message, 'error');
        setBusy(button, false);
    }
}

$('answer-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const question = $('answer-question').value.trim();
    const answer = $('answer-text').value.trim();
    if (!question || !answer) return;
    try {
        store.set({ answers: await api.saveAnswers([{ question, answer }]) });
        $('answer-form').reset();
        toast('Answer saved', 'success');
    } catch (err) {
        toast(err.message, 'error');
    }
});

function openPdf(urlPromise) {
    // Open the tab inside the click (popup blockers allow that), then point it at the PDF once loaded.
    const tab = window.open('', '_blank');
    urlPromise
        .then((url) => {
            if (tab) tab.location.href = url;
            else window.location.href = url;
        })
        .catch((err) => {
            tab?.close();
            toast(err.message, 'error');
        });
}

async function showImage(title, urlPromise) {
    try {
        const url = await urlPromise;
        openModal(title, `<img class="screenshot" alt="${esc(title)}" src="${esc(url)}">`, {
            onClose: () => URL.revokeObjectURL(url),
        });
    } catch (err) {
        toast(err.message, 'error');
    }
}

// ---------------------------------------------------------------- access token
auth.onUnauthorized = () => new Promise((resolve) => {
    openModal('Access token required', `
        <form id="token-form" class="form-layout">
            <p class="muted">This JobPilot server is protected. Enter the <code>API_TOKEN</code> value from its <code>.env</code> file.</p>
            <div class="form-group"><label for="token-input">API token</label>
                <input id="token-input" type="password" autocomplete="current-password" required></div>
            <div class="modal-footer"><button type="submit" class="btn-primary">Continue</button></div>
        </form>`, { onClose: () => resolve(false) });
    $('token-input').focus();
    $('token-form').addEventListener('submit', (e) => {
        e.preventDefault();
        setToken($('token-input').value.trim());
        resolve(true);
        closeModal();
    });
});

// ---------------------------------------------------------------- manual apply
// Open the company's site, track it as "Did you apply?", and ask when the user comes back to this tab.
const PENDING_KEY = 'jobpilot.pendingManualApply';
let pendingManual = null;
try { pendingManual = JSON.parse(sessionStorage.getItem(PENDING_KEY) || 'null'); } catch { pendingManual = null; }

function rememberPending(value) {
    pendingManual = value;
    try {
        if (value) sessionStorage.setItem(PENDING_KEY, JSON.stringify(value));
        else sessionStorage.removeItem(PENDING_KEY);
    } catch { /* storage unavailable: the in-memory value still works for this tab */ }
}

async function startManualApply(button) {
    const { jobId, url, title, company } = button.dataset;
    // Open synchronously inside the click so popup blockers allow it.
    window.open(url, '_blank', 'noopener');
    try {
        const app = await api.createApplication(jobId, 'manual');
        rememberPending({ id: app.id, title, company, openedAt: Date.now() });
        toast('Apply on the company site. When you come back here, JobPilot will ask if you applied.', 'info');
        await refreshApplications();
    } catch (err) {
        toast(err.message, 'error');
    }
}

function askIfApplied() {
    if (!pendingManual || document.visibilityState !== 'visible') return;
    // Ignore the instant focus flicker right after opening the new tab.
    if (Date.now() - pendingManual.openedAt < 3000) return;
    const app = store.state.applications.find((a) => a.id === pendingManual.id);
    const { id, title, company } = pendingManual;
    rememberPending(null);
    if (app && app.status !== 'AWAITING_CONFIRMATION') return;
    openModal('Did you apply?', `
        <p class="modal-question">Did you submit your application for <strong>${esc(title)}</strong> at <strong>${esc(company)}</strong>?</p>
        <div class="modal-footer">
            <button class="btn-ghost" data-action="set-status" data-status="DISMISSED" data-app-id="${esc(id)}">Not applying</button>
            <button class="btn-secondary" data-action="dismiss-modal">Not yet</button>
            <button class="btn-primary" data-action="set-status" data-status="APPLIED" data-app-id="${esc(id)}"><i class="fa-solid fa-check"></i> Yes, I applied</button>
        </div>
        <p class="muted small">"Not yet" keeps it under <em>Did you apply?</em> in Applications.</p>`);
}

document.addEventListener('visibilitychange', askIfApplied);
window.addEventListener('focus', askIfApplied);

async function copyLetter(appId) {
    const textarea = document.querySelector(`textarea[data-app-id="${CSS.escape(appId)}"]`);
    try {
        await navigator.clipboard.writeText(textarea.value);
        toast('Cover letter copied', 'success');
    } catch {
        textarea.select();
        toast('Press Ctrl+C to copy the selected letter', 'info');
    }
}

// ---------------------------------------------------------------- profile
$('profile-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const button = $('btn-save-profile');
    setBusy(button, true, 'Saving…');
    try {
        const profile = await api.saveProfile(readProfileForm(store.state.profile));
        const jobs = await api.rescoreJobs();
        store.set({ profile, jobs });
        fillProfileForm(profile);
        toast('Profile saved and jobs re-scored', 'success');
    } catch (err) {
        toast(`Could not save profile: ${err.message}`, 'error');
    } finally {
        setBusy(button, false);
    }
});

async function uploadResume(file) {
    if (!file) return;
    $('resume-status').textContent = `Parsing ${file.name}…`;
    try {
        const profile = await api.uploadResume(file);
        const jobs = await api.rescoreJobs();
        store.set({ profile, jobs });
        fillProfileForm(profile);
        prefillSearch(profile);
        toast('Resume parsed. Review the profile fields and save any corrections.', 'success');
    } catch (err) {
        $('resume-status').textContent = `Upload failed: ${err.message}`;
        toast(err.message, 'error');
    }
}

$('resume-input').addEventListener('change', (e) => uploadResume(e.target.files[0]));
const dropzone = $('resume-dropzone');
['dragover', 'dragenter'].forEach((t) => dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.add('dragging'); }));
['dragleave', 'drop'].forEach((t) => dropzone.addEventListener(t, () => dropzone.classList.remove('dragging')));
dropzone.addEventListener('drop', (e) => { e.preventDefault(); uploadResume(e.dataTransfer.files[0]); });

function prefillSearch(profile) {
    const prefs = profile?.preferences || {};
    if (!$('role-input').value) {
        $('role-input').value = (prefs.preferred_roles?.length ? prefs.preferred_roles : [profile?.current_role].filter(Boolean)).join(', ');
    }
    if (!$('location-input').value) {
        const city = profile?.location ? [profile.location.split(',')[0].trim()] : [];
        $('location-input').value = (prefs.preferred_locations?.length ? prefs.preferred_locations : city).join(', ');
    }
    $('remote-toggle').checked = prefs.remote_preference === 'REMOTE_ONLY';
    $('visa-toggle').checked = Boolean(prefs.visa_sponsorship_required);
}

// ---------------------------------------------------------------- health & modal
$('btn-recheck').addEventListener('click', async () => {
    const button = $('btn-recheck');
    setBusy(button, true, 'Checking�');
    try {
        const { checked, closed, unknown } = await api.recheckJobs();
        toast(checked
            ? `Checked ${checked} posting(s): ${closed} closed${unknown ? `, ${unknown} could not be verified` : ''}`
            : 'No postings to check (only Greenhouse, Lever, Ashby and Workable can be verified)', 'success');
        if (closed) store.set({ jobs: await api.listJobs() });
    } catch (err) {
        toast(`Re-check failed: ${err.message}`, 'error');
    } finally {
        setBusy(button, false);
    }
});

async function loadHealth() {
    try {
        renderHealth($('health-grid'), await api.health());
    } catch (err) {
        renderHealth($('health-grid'), null, err);
    }
}

$('modal-close').addEventListener('click', closeModal);
$('modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

// ---------------------------------------------------------------- boot
(async function boot() {
    try {
        const [profile, jobs, applications, answers] = await Promise.all([
            api.getProfile(), api.listJobs(), api.listApplications(), api.listAnswers(),
        ]);
        store.set({ profile, jobs, applications, answers });
        fillProfileForm(profile);
        prefillSearch(profile);
        if (!profile) showTab('profile-tab');
    } catch (err) {
        store.set({});
        toast(`Could not load data: ${err.message}`, 'error');
    }
})();
