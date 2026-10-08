import { api, auth, setToken } from './api.js';
import { renderApplications } from './components/approvalQueue.js';
import { renderBoard, renderFollowUps, renderReport } from './components/board.js';
import { renderHealth } from './components/health.js';
import { renderInterview } from './components/interview.js';
import { PAGE_SIZE, renderJobFeed, visibleJobs } from './components/jobFeed.js';
import { setupLocationSuggest } from './components/locationSuggest.js';
import { outreachHtml, renderContacts } from './components/network.js';
import { renderInsights, renderPrepSelect } from './components/prepare.js';
import { fillProfileForm, readProfileForm, renderAnswers, renderNavbar } from './components/profile.js';
import { intervalOptions, renderResumes, renderSavedSearches, resumeCheckHtml } from './components/resumes.js';
import { renderBoards, renderInbox } from './components/sources.js';
import { checkAgentQuestions } from './components/agentChat.js';
import { AWAITING, IN_FLIGHT, NEEDS_REVIEW, SUBMITTED, store } from './state.js';
import { closeModal, esc, openModal, setBusy, splitList, toast } from './utils.js';

const $ = (id) => document.getElementById(id);
const POLL_MS = 3000;
const LAST_VISIT_KEY = 'jobpilot.lastVisit';
let pollTimer = null;

// ---------------------------------------------------------------- rendering
let renderedAnswers = null;
store.subscribe((state) => {
    renderJobFeed($('jobs-container'), state);
    renderApplications($('applications-list'), state.applications);
    renderBoard($('applications-board'), state.applications);
    renderFollowUps($('follow-up-banner'), state.applications);
    renderNavbar(state.profile);
    renderAnalytics(state.applications);
    renderPrepSelect($('prepare-app-select'), state.applications);
    renderSavedSearches($('saved-searches-list'), state.savedSearches);
    $('saved-search-count').textContent = state.savedSearches.length ? `(${state.savedSearches.length})` : '';
    // Only when the bank itself changed, so polling never wipes an answer being edited.
    if (state.answers !== renderedAnswers) {
        renderAnswers($('answer-list'), state.answers);
        renderedAnswers = state.answers;
    }

    const shown = visibleJobs(state);
    $('stat-total').textContent = shown.length;
    $('stat-high').textContent = shown.filter((j) => j.match?.overall_match >= 70).length;
    $('stat-visa').textContent = shown.filter((j) => j.job.visa_sponsorship.status === 'YES').length;
    $('stat-applied').textContent = state.applications.filter((a) => SUBMITTED.has(a.status)).length;

    const review = state.applications.filter((a) => NEEDS_REVIEW.has(a.status) || a.status === AWAITING || a.follow_up_due).length;
    $('review-count').textContent = review;
    $('review-count').hidden = review === 0;
    document.querySelectorAll('#job-view .view-btn').forEach((b) => b.classList.toggle('active', b.dataset.view === state.jobView));
    $('view-search').disabled = !state.searchJobs;
    const titleHeader = $('job-section-title');
    if (titleHeader) {
        const titleMap = {
            recommended: '<i class="fa-solid fa-wand-magic-sparkles"></i> Recommended Jobs (Matched to your profile)',
            search: '<i class="fa-solid fa-magnifying-glass"></i> Search Results',
            all: '<i class="fa-solid fa-layer-group"></i> All Saved Jobs',
        };
        titleHeader.innerHTML = titleMap[state.jobView] || titleMap.recommended;
    }
    $('applications-board').hidden = state.appView !== 'board';
    $('applications-list').hidden = state.appView !== 'list';
    document.querySelectorAll('#app-view .view-btn').forEach((b) => b.classList.toggle('active', b.dataset.view === state.appView));

    checkAgentQuestions(state.applications);

    schedulePolling(state.applications.some(
        (a) => IN_FLIGHT.has(a.status) || (a.status === AWAITING && a.cover_letter === null) || a.status === 'NEEDS_INPUT',
    ));
});

function renderAnalytics(applications) {
    const count = (test) => applications.filter(test).length;
    const applied = count((a) => SUBMITTED.has(a.status));
    const interviews = count((a) => a.status === 'INTERVIEW' || a.status === 'OFFER');
    const review = count((a) => NEEDS_REVIEW.has(a.status));
    const closed = count((a) => a.status === 'DISMISSED' || a.status === 'REJECTED');
    const total = applications.length || 1;
    const set = (id, value) => { if ($(id)) $(id).textContent = value; };
    const width = (id, n) => { if ($(id)) $(id).style.width = `${(n / total) * 100}%`; };

    set('analytics-total', applied);
    set('analytics-shortlisted', interviews);
    set('analytics-rate', `${applied ? Math.round((interviews / applied) * 100) : 0}%`);
    set('analytics-letters', count((a) => a.cover_letter !== null));
    set('count-applied', Math.max(0, applied - interviews));
    set('count-interview', interviews);
    set('count-review', review);
    set('count-dismissed', closed);
    width('bar-applied', Math.max(0, applied - interviews));
    width('bar-interview', interviews);
    width('bar-review', review);
    width('bar-dismissed', closed);
    set('pipeline-status-text', `${applications.length} tracked application${applications.length === 1 ? '' : 's'}`);
}

function schedulePolling(active) {
    if (active && !pollTimer) {
        pollTimer = setInterval(refreshApplications, POLL_MS);
    } else if (!active && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

export async function refreshApplications() {
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

const TAB_KEY = 'jobpilot.activeTab';

function showTab(tabId, updateHash = true) {
    if (!document.getElementById(tabId)) return;
    document.querySelectorAll('.nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.tab === tabId));
    document.querySelectorAll('.tab-content').forEach((c) => c.classList.toggle('active', c.id === tabId));
    try { localStorage.setItem(TAB_KEY, tabId); } catch { /* storage unavailable */ }
    if (updateHash && window.location.hash !== `#${tabId}`) {
        history.pushState(null, '', `#${tabId}`);
    }
    if (tabId === 'profile-tab') {
        loadHealth();
        loadSources();
        loadResumes();
    }
    if (tabId === 'network-tab') loadConnectionCount();
    if (tabId === 'applications-tab') loadReport();
}

document.querySelectorAll('.nav-btn').forEach((btn) => btn.addEventListener('click', () => showTab(btn.dataset.tab)));

window.addEventListener('popstate', () => {
    const hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById(hash)) {
        showTab(hash, false);
    }
});

// ---------------------------------------------------------------- job list: views, filters, sorting, paging
function filterRecommendedJobs(allJobs, profile) {
    if (!allJobs || !Array.isArray(allJobs)) return [];
    return allJobs.filter(({ match, job }) => {
        if (match) {
            if (match.passed_hard_filters === false) return false;
            if (match.ai_verdict === 'no') return false;
            if (match.overall_match < 50) return false;
        }
        if (profile && profile.years_of_experience != null && profile.years_of_experience !== '') {
            const userExp = Number(profile.years_of_experience);
            if (!isNaN(userExp) && job.experience_required != null) {
                if (job.experience_required > userExp + 2) return false;
                if (job.experience_required >= 7 && userExp <= 2) return false;
            }
        }
        return true;
    });
}

function setJobs(patch) {
    const next = { ...store.state, ...patch };
    const view = next.jobView || 'recommended';
    let jobs = next.allJobs || [];
    if (view === 'search' && next.searchJobs) {
        jobs = next.searchJobs;
    } else if (view === 'recommended') {
        jobs = filterRecommendedJobs(next.allJobs, next.profile);
    }
    store.set({ ...patch, jobs });
}

function dropJob(jobId) {
    const without = (list) => (list ? list.filter((j) => j.job.id !== jobId) : list);
    setJobs({ allJobs: without(store.state.allJobs), searchJobs: without(store.state.searchJobs) });
}

async function reloadAllJobs() {
    setJobs({ allJobs: await api.listJobs() });
}

$('job-filters').addEventListener('click', (e) => {
    const btn = e.target.closest('.filter-btn');
    if (!btn) return;
    document.querySelectorAll('.filter-btn').forEach((b) => b.classList.toggle('active', b === btn));
    store.set({ jobFilter: btn.dataset.filter, visibleCount: PAGE_SIZE });
});
$('job-view').addEventListener('click', (e) => {
    const btn = e.target.closest('.view-btn');
    if (btn && !btn.disabled) setJobs({ jobView: btn.dataset.view, visibleCount: PAGE_SIZE });
});
$('job-sort').addEventListener('change', () => store.set({ jobSort: $('job-sort').value }));
let queryTimer = null;
$('job-query').addEventListener('input', () => {
    clearTimeout(queryTimer);
    queryTimer = setTimeout(() => store.set({ jobQuery: $('job-query').value.trim(), visibleCount: PAGE_SIZE }), 150);
});

// ---------------------------------------------------------------- search
function searchParams() {
    return {
        roles: splitList($('role-input').value),
        locations: splitList($('location-input').value), // typed places always count, even when searching from the resume
        experience: $('exp-input').value || 'ANY',
        posted_within: $('posted-input').value || 'any',
        remote_only: $('remote-toggle').checked,
        sponsorship_required: $('visa-toggle').checked,
        strict_location: $('exact-toggle').checked,
    };
}

async function runSearch(button) {
    const params = searchParams();
    const fromResume = !params.roles.length;
    if (fromResume && !store.state.profile) {
        showTab('profile-tab');
        return toast('Type a role, or upload your resume to search from it', 'warn');
    }

    setBusy(button, true, 'Searching…');
    $('search-meta').title = '';
    $('search-meta').textContent = fromResume
        ? 'Building searches from your resume (roles, related titles, skills, seniority)…'
        : 'Planning searches…';
    // Each finished stage is appended as it streams in: "✓ Searching job boards (54 postings found) · …"
    const done = [];
    const showProgress = (stage) => {
        done.push(`✓ ${stage.label}${stage.detail ? ` (${stage.detail})` : ''}`);
        $('search-meta').textContent = `${done.join(' · ')} …`;
    };
    try {
        const result = await api.searchStream(params, showProgress);
        setJobs({ searchJobs: result.results, jobView: 'search', jobFilter: 'all', visibleCount: PAGE_SIZE });
        document.querySelectorAll('.filter-btn').forEach((b) => b.classList.toggle('active', b.dataset.filter === 'all'));
        $('role-input').value = result.roles.join(', ');
        $('location-input').value = result.locations.join(', ');
        syncLocationClear();
        describeSearch(result);
        api.listJobs().then((allJobs) => setJobs({ allJobs })).catch(() => {});
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
        `matched titles: ${result.titles.slice(0, 8).join(', ')}`,
        `searched: ${result.queries.join(' | ')}`,
    ];
    $('search-meta').textContent = parts.filter(Boolean).join(' · ');
    $('search-meta').title = result.errors.join('\n');
}

$('search-form').addEventListener('submit', (e) => {
    e.preventDefault();
    runSearch($('btn-search'));
});

const syncLocationClear = setupLocationSuggest($('location-input'), $('location-suggestions'), $('location-clear'));

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
    syncLocationClear();
}

// ---------------------------------------------------------------- saved searches
async function loadSavedSearches() {
    try {
        store.set({ savedSearches: await api.listSavedSearches() });
    } catch (err) {
        console.warn('Could not load saved searches', err);
    }
}

$('btn-save-search').addEventListener('click', () => {
    const params = searchParams();
    if (!params.roles.length && !store.state.profile) return toast('Type a role first, or upload your resume', 'warn');
    const name = params.roles.join(', ') || 'From my resume';
    openModal('Save this search', `
        <form id="save-search-form" class="form-layout">
            <div class="form-group"><label for="save-search-name">Name</label>
                <input id="save-search-name" value="${esc(name)}" maxlength="120" required></div>
            <div class="form-group"><label for="save-search-interval">Run it</label>
                <select id="save-search-interval">${intervalOptions(24)}</select></div>
            <p class="muted small">Strong new matches are announced on your webhook or email when those are set up; all results appear in "All saved jobs".</p>
            <div class="modal-footer"><button type="submit" class="btn-primary">Save</button></div>
        </form>`);
    $('save-search-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            await api.saveSearch($('save-search-name').value.trim(), params, Number($('save-search-interval').value));
            closeModal();
            toast('Search saved', 'success');
            $('saved-searches-panel').open = true;
            await loadSavedSearches();
        } catch (err) {
            toast(err.message, 'error');
        }
    });
});

async function runSavedSearch(button) {
    setBusy(button, true, 'Running…');
    try {
        const result = await api.runSavedSearch(button.dataset.searchId);
        toast(result.last_error ? `Search failed: ${result.last_error}` : `${result.last_found} jobs, ${result.last_new} new`, result.last_error ? 'error' : 'success');
        await Promise.all([loadSavedSearches(), reloadAllJobs()]);
        setJobs({ jobView: 'all' });
    } catch (err) {
        toast(err.message, 'error');
    } finally {
        setBusy(button, false);
    }
}

document.addEventListener('change', async (e) => {
    const select = e.target.closest('[data-action-change="search-interval"]');
    if (!select) return;
    try {
        await api.updateSavedSearch(select.dataset.searchId, { interval_hours: Number(select.value) });
        await loadSavedSearches();
    } catch (err) {
        toast(err.message, 'error');
    }
});

// ---------------------------------------------------------------- resume mode for agent applications
const RESUME_CHOICE_KEY = 'jobpilot.resumeChoice';
function initResumeChoice(profile) {
    let saved = null;
    try { saved = localStorage.getItem(RESUME_CHOICE_KEY); } catch { /* storage unavailable */ }
    $('resume-choice').value = saved || (profile?.preferences?.tailor_resume ? 'tailored' : 'original');
}
$('resume-choice').addEventListener('change', () => {
    try { localStorage.setItem(RESUME_CHOICE_KEY, $('resume-choice').value); } catch { /* storage unavailable */ }
});
const wantsTailored = () => $('resume-choice').value === 'tailored';

// ---------------------------------------------------------------- job + application actions
document.addEventListener('click', async (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    const { action, jobId, appId } = target.dataset;

    if (action === 'goto-applications') return showTab('applications-tab');
    if (action === 'goto-profile') return showTab('profile-tab');
    if (action === 'show-more-jobs') return store.set({ visibleCount: (store.state.visibleCount || PAGE_SIZE) + PAGE_SIZE });
    if (action === 'show-app-details') return store.set({ appView: 'list' });
    if (action === 'screenshot') return showImage('Form screenshot', api.screenshotUrl(appId));
    if (action === 'step-screenshot') return showImage('Agent screenshot', api.stepScreenshotUrl(appId, target.dataset.name));
    if (action === 'open-resume') return openPdf(api.tailoredResumeUrl(appId));
    if (action === 'update-answer' || action === 'delete-answer') return editAnswer(target, action);
    if (action === 'hide-job') return hideJob(jobId);
    if (action === 'block-company') return blockCompany(target.dataset.company);
    if (action === 'save-job') return saveJob(target, jobId);
    if (action === 'resume-check') return showResumeCheck(jobId);
    if (action === 'remove-board') return removeBoard(target);
    if (action === 'dismiss-modal') return closeModal();
    if (action === 'copy-letter') return copyLetter(appId);
    if (action === 'copy-text') return copyText($(target.dataset.target));
    if (action === 'manual') return startManualApply(target);
    if (action === 'get-insiders') return openNetwork(jobId, target.dataset.company, target.dataset.jobTitle);
    if (action === 'get-insights') {
        showTab('prepare-tab');
        $('prepare-app-select').value = appId;
        return loadInsights(appId);
    }
    if (action === 'draft-outreach') return showOutreach(target.dataset);
    if (action === 'run-saved-search') return runSavedSearch(target);
    if (action === 'toggle-saved-search') {
        await api.updateSavedSearch(target.dataset.searchId, { enabled: target.dataset.enabled !== 'true' }).catch((err) => toast(err.message, 'error'));
        return loadSavedSearches();
    }
    if (action === 'delete-saved-search') {
        if (!confirm('Delete this saved search?')) return;
        await api.deleteSavedSearch(target.dataset.searchId).catch((err) => toast(err.message, 'error'));
        return loadSavedSearches();
    }
    if (action === 'delete-resume') return deleteResume(target);
    if (action === 'auto-apply' && !confirm('Auto-apply submits the form without your review when it is complete and has no CAPTCHA. Continue?')) {
        return;
    }

    const handlers = {
        prepare: () => api.createApplication(jobId, 'review', wantsTailored()),
        'auto-apply': () => api.createApplication(jobId, 'auto', wantsTailored()),
        approve: () => api.approveApplication(appId),
        'set-status': () => api.updateApplication(appId, { status: target.dataset.status }),
        'follow-up': () => api.followUp(appId),
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
        if (action === 'follow-up') toast('Noted. The reminder starts again.', 'success');
        if (action === 'set-status') {
            const done = {
                APPLIED: 'Moved to Applied', DISMISSED: 'Removed', INTERVIEW: 'Moved to Interviewing',
                OFFER: 'Congratulations! Moved to Offer', REJECTED: 'Moved to Closed',
            };
            toast(done[target.dataset.status] || 'Updated', 'success');
        }
        await refreshApplications();
        if (['set-status', 'follow-up'].includes(action) && $('applications-tab').classList.contains('active')) loadReport();
    } catch (err) {
        toast(err.message, 'error');
    } finally {
        setBusy(target, false);
    }
});

// ---------------------------------------------------------------- not interested / hidden companies / saving
async function hideJob(jobId) {
    try {
        await api.hideJob(jobId);
        dropJob(jobId);
        toast('Hidden. It will not come back in later searches.', 'info', {
            label: 'Undo',
            onClick: async () => {
                await api.unhideJob(jobId);
                await reloadAllJobs();
                setJobs({ jobView: 'all' });
            },
        });
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function setBlockedCompanies(blocked) {
    const profile = store.state.profile;
    const saved = await api.saveProfile({ ...profile, preferences: { ...profile.preferences, blocked_companies: blocked } });
    const lower = new Set(blocked.map((c) => c.toLowerCase()));
    const searchJobs = store.state.searchJobs?.filter((j) => !lower.has(j.job.company.toLowerCase())) ?? null;
    store.set({ profile: saved });
    setJobs({ allJobs: await api.listJobs(), searchJobs });
    fillProfileForm(saved);
}

async function blockCompany(company) {
    if (!store.state.profile) return toast('Set up your profile first', 'warn');
    if (!confirm(`Hide every job from ${company}? You can undo this in Profile Settings → Hidden companies.`)) return;
    const before = store.state.profile.preferences.blocked_companies || [];
    try {
        await setBlockedCompanies([...before, company]);
        toast(`Jobs from ${company} are hidden`, 'info', { label: 'Undo', onClick: () => setBlockedCompanies(before) });
    } catch (err) {
        toast(err.message, 'error');
    }
}

async function saveJob(button, jobId) {
    setBusy(button, true, '');
    try {
        await api.createApplication(jobId, 'save');
        toast('Saved to your Applications board', 'success');
        await refreshApplications();
    } catch (err) {
        toast(err.message, 'error');
        setBusy(button, false);
    }
}

async function showResumeCheck(jobId) {
    openModal('Resume check', '<p class="muted loading-note"><i class="fa-solid fa-spinner fa-spin"></i> Checking your resume against this job…</p>');
    try {
        openModal('Resume check', resumeCheckHtml(await api.resumeCheck(jobId)));
    } catch (err) {
        closeModal();
        toast(err.message, 'error');
    }
}

// ---------------------------------------------------------------- job sources & health (Profile tab)
async function loadSources() {
    try {
        const [boards, inbox] = await Promise.all([api.listBoards(), api.inboxStatus()]);
        renderBoards($('board-list'), boards);
        renderInbox($('inbox-status'), inbox);
        $('btn-check-inbox').hidden = !inbox.configured;
    } catch (err) {
        toast(`Could not load job sources: ${err.message}`, 'error');
    }
}

async function loadHealth() {
    try {
        renderHealth($('health-grid'), await api.health());
    } catch (err) {
        renderHealth($('health-grid'), null, err);
    }
}

$('board-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const button = e.submitter || $('board-form').querySelector('button');
    setBusy(button, true, 'Checking…');
    try {
        const board = await api.addBoard($('board-url').value.trim());
        $('board-form').reset();
        toast(`Watching ${board.company} (${board.open_jobs} open job${board.open_jobs === 1 ? '' : 's'} right now)`, 'success');
        await loadSources();
    } catch (err) {
        toast(err.message, 'error');
    } finally {
        setBusy(button, false);
    }
});

async function removeBoard(button) {
    try {
        await api.removeBoard(button.dataset.ats, button.dataset.slug);
        await loadSources();
    } catch (err) {
        toast(err.message, 'error');
    }
}

$('btn-check-inbox').addEventListener('click', async () => {
    const button = $('btn-check-inbox');
    setBusy(button, true, 'Reading inbox…');
    try {
        const report = await api.checkInbox();
        if (report.errors.length) {
            toast(report.errors[0], 'error');
        } else {
            toast(`${report.job_alerts} alert email(s): ${report.jobs_new} new job(s); ${report.status_updates.length} application update(s)`, 'success');
        }
        const [allJobs, applications] = await Promise.all([api.listJobs(), api.listApplications()]);
        store.set({ applications });
        setJobs({ allJobs });
        await loadSources();
    } catch (err) {
        toast(err.message, 'error');
    } finally {
        setBusy(button, false);
    }
});

$('btn-recheck').addEventListener('click', async () => {
    const button = $('btn-recheck');
    setBusy(button, true, 'Checking…');
    try {
        const { checked, closed, unknown } = await api.recheckJobs();
        toast(checked
            ? `Checked ${checked} posting(s): ${closed} closed${unknown ? `, ${unknown} could not be verified` : ''}`
            : 'No postings to check (only Greenhouse, Lever, Ashby, Workable and SmartRecruiters can be verified)', 'success');
        if (closed) await reloadAllJobs();
    } catch (err) {
        toast(`Re-check failed: ${err.message}`, 'error');
    } finally {
        setBusy(button, false);
    }
});

// ---------------------------------------------------------------- resume versions
async function loadResumes() {
    try {
        renderResumes($('resume-list'), await api.listResumes());
    } catch (err) {
        $('resume-list').innerHTML = `<p class="notice error">${esc(err.message)}</p>`;
    }
}

$('resume-version-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = $('resume-version-file').files[0];
    if (!file) return;
    const button = e.submitter || $('resume-version-form').querySelector('button');
    setBusy(button, true, 'Reading…');
    try {
        const version = await api.addResumeVersion(file, $('resume-version-label').value.trim());
        $('resume-version-form').reset();
        toast(`Added "${version.label}" (${version.skills.length} skills found)`, 'success');
        await loadResumes();
    } catch (err) {
        toast(err.message, 'error');
    } finally {
        setBusy(button, false);
    }
});

async function deleteResume(button) {
    if (!confirm('Delete this resume version?')) return;
    try {
        await api.deleteResumeVersion(button.dataset.resumeId);
        await loadResumes();
    } catch (err) {
        toast(err.message, 'error');
    }
}

// ---------------------------------------------------------------- answer bank
/** Save the answers typed on an application card to the answer bank, then re-fill that form. */
async function saveQuestionAnswers(card, appId) {
    const inputs = [...card.querySelectorAll('[data-question-input]')];
    const answers = inputs
        .filter((el) => el.value.trim())
        .map((el) => ({
            question: el.dataset.label,
            answer: el.value.trim(),
        }));
    if (!answers.length) throw new Error('Answer at least one question first');
    
    // Send each answer to the backend which automatically queues a refill when all are answered
    await Promise.all(answers.map(a => api.answerApplicationQuestion(appId, a.question, a.answer, true)));
    
    inputs.forEach((el) => { el.dataset.dirty = '0'; });
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

// ---------------------------------------------------------------- files, images, clipboard
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

async function copyText(textarea) {
    if (!textarea) return;
    try {
        await navigator.clipboard.writeText(textarea.value);
        toast('Copied', 'success');
    } catch {
        textarea.select();
        toast('Press Ctrl+C to copy the selected text', 'info');
    }
}

function copyLetter(appId) {
    return copyText(document.querySelector(`textarea[data-app-id="${CSS.escape(appId)}"]`));
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
    if (app && app.status !== AWAITING) return;
    openModal('Did you apply?', `
        <p class="modal-question">Did you submit your application for <strong>${esc(title)}</strong> at <strong>${esc(company)}</strong>?</p>
        <div class="modal-footer">
            <button class="btn-ghost" data-action="set-status" data-status="DISMISSED" data-app-id="${esc(id)}">Not applying</button>
            <button class="btn-secondary" data-action="dismiss-modal">Not yet</button>
            <button class="btn-primary" data-action="set-status" data-status="APPLIED" data-app-id="${esc(id)}"><i class="fa-solid fa-check"></i> Yes, I applied</button>
        </div>
        <p class="muted small">"Not yet" keeps it under <em>To finish</em> in Applications.</p>`);
}

document.addEventListener('visibilitychange', askIfApplied);
window.addEventListener('focus', askIfApplied);

// ---------------------------------------------------------------- applications: views and report
const APP_VIEW_KEY = 'jobpilot.appView';
$('app-view').addEventListener('click', (e) => {
    const btn = e.target.closest('.view-btn');
    if (!btn) return;
    store.set({ appView: btn.dataset.view });
    try { localStorage.setItem(APP_VIEW_KEY, btn.dataset.view); } catch { /* storage unavailable */ }
});

async function loadReport() {
    try {
        renderReport($('report-view'), await api.applicationReport(7));
    } catch (err) {
        $('report-view').innerHTML = `<p class="notice error">${esc(err.message)}</p>`;
    }
}

$('btn-email-report').addEventListener('click', async () => {
    const button = $('btn-email-report');
    setBusy(button, true, 'Sending…');
    try {
        const { sent } = await api.emailReport(7);
        toast(sent ? 'Report sent to your email' : 'Could not send the email; check the SMTP settings', sent ? 'success' : 'error');
    } catch (err) {
        toast(err.message, 'error');
    } finally {
        setBusy(button, false);
    }
});

// ---------------------------------------------------------------- network tab
let networkContext = { company: '', jobTitle: '' };

async function openNetwork(jobId, company, jobTitle) {
    showTab('network-tab');
    $('network-company-input').value = company || '';
    await runNetworkSearch({ jobId, company, jobTitle });
}

async function runNetworkSearch({ jobId = null, company, jobTitle = '' }) {
    networkContext = { company, jobTitle };
    const container = $('network-results');
    container.innerHTML = `<p class="muted loading-note"><i class="fa-solid fa-spinner fa-spin"></i> Looking for people at <strong>${esc(company)}</strong>…</p>`;
    try {
        const data = jobId ? await api.getInsiders(jobId) : await api.getCompanyContacts(company);
        renderContacts(container, data, networkContext);
    } catch (err) {
        container.innerHTML = `<p class="notice error">Could not search contacts: ${esc(err.message)}</p>`;
    }
}

$('network-search-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const company = $('network-company-input').value.trim();
    if (company) runNetworkSearch({ company });
});

async function loadConnectionCount() {
    try {
        const { count } = await api.connectionsSummary();
        $('connections-status').textContent = count ? `${count} LinkedIn connections imported.` : 'No connections imported yet.';
    } catch {
        $('connections-status').textContent = '';
    }
}

$('connections-input').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
        const result = await api.uploadConnections(file);
        toast(result.message, 'success');
        await loadConnectionCount();
        if (networkContext.company) await runNetworkSearch(networkContext);
    } catch (err) {
        toast(err.message, 'error');
    } finally {
        e.target.value = '';
    }
});

async function showOutreach({ contactName, contactRole, company, jobTitle }) {
    openModal(`Message to ${contactName || company}`, '<p class="muted loading-note"><i class="fa-solid fa-wand-magic-sparkles fa-pulse"></i> Writing your message…</p>');
    try {
        const data = await api.generateOutreach({
            company, contact_name: contactName || '', contact_role: contactRole || '', job_title: jobTitle || networkContext.jobTitle || '',
        });
        openModal(`Message to ${contactName || company}`, outreachHtml(data));
        $('li-note-text').addEventListener('input', () => {
            $('li-note-count').textContent = `${$('li-note-text').value.length}/300`;
        });
    } catch (err) {
        closeModal();
        toast(`Could not write the message: ${err.message}`, 'error');
    }
}

// ---------------------------------------------------------------- prepare tab: insights and mock interview
$('btn-generate-prep').addEventListener('click', () => {
    const appId = $('prepare-app-select').value;
    if (!appId) return toast('Choose an application first', 'warn');
    loadInsights(appId);
});

async function loadInsights(appId) {
    const container = $('prep-insights-view');
    container.innerHTML = '<p class="muted loading-note"><i class="fa-solid fa-brain fa-pulse"></i> Comparing the job with your profile…</p>';
    try {
        renderInsights(container, await api.getApplicationInsights(appId));
    } catch (err) {
        container.innerHTML = `<p class="notice error"><i class="fa-solid fa-circle-exclamation"></i> Could not prepare insights: ${esc(err.message)}</p>`;
    }
}

const interview = { appId: null, messages: [], turn: null, busy: false };

function drawInterview() {
    renderInterview($('interview-view'), interview);
    const form = $('interview-form');
    if (!form) return;
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        answerInterview();
    });
    $('interview-answer').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) answerInterview();
    });
    $('interview-answer').focus();
}

async function interviewTurn() {
    interview.busy = true;
    drawInterview();
    try {
        const transcript = interview.messages.map(({ role, content }) => ({ role, content }));
        const turn = await api.mockInterview(interview.appId, transcript);
        interview.turn = turn;
        const last = interview.messages.at(-1);
        if (last && last.role === 'candidate' && turn.feedback) last.feedback = turn.feedback;
        if (turn.question) interview.messages.push({ role: 'interviewer', content: turn.question });
    } catch (err) {
        toast(err.message, 'error');
    } finally {
        interview.busy = false;
        drawInterview();
    }
}

function answerInterview() {
    const answer = $('interview-answer')?.value.trim();
    if (!answer || interview.busy) return;
    interview.messages.push({ role: 'candidate', content: answer });
    interviewTurn();
}

$('btn-start-interview').addEventListener('click', () => {
    const appId = $('prepare-app-select').value;
    if (!appId) return toast('Choose an application above first', 'warn');
    Object.assign(interview, { appId, messages: [], turn: null, busy: false });
    interviewTurn();
});

// ---------------------------------------------------------------- profile & resume
$('profile-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const button = $('btn-save-profile');
    setBusy(button, true, 'Saving…');
    try {
        // Fields the form does not show (work history, education, summary) are kept from the stored profile.
        const profile = await api.saveProfile(readProfileForm(store.state.profile));
        const allJobs = await api.rescoreJobs();
        store.set({ profile });
        setJobs({ allJobs, jobView: 'all' });
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
        const allJobs = await api.rescoreJobs();
        store.set({ profile });
        setJobs({ allJobs });
        fillProfileForm(profile);
        prefillSearch(profile);
        loadResumes();
        const roles = profile.preferences?.preferred_roles || [];
        toast(roles.length
            ? `Resume parsed. Target roles: ${roles.join(', ')}. Review your profile and save any corrections.`
            : 'Resume parsed. Review the profile fields and save any corrections.', 'success');
    } catch (err) {
        $('resume-status').textContent = `Upload failed: ${err.message}`;
        toast(err.message, 'error');
    }
}

$('resume-input').addEventListener('change', (e) => {
    uploadResume(e.target.files[0]);
    e.target.value = '';
});
const dropzone = $('resume-dropzone');
['dragover', 'dragenter'].forEach((t) => dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.add('dragging'); }));
['dragleave', 'drop'].forEach((t) => dropzone.addEventListener(t, () => dropzone.classList.remove('dragging')));
dropzone.addEventListener('drop', (e) => { e.preventDefault(); uploadResume(e.dataTransfer.files[0]); });

// ---------------------------------------------------------------- modal
$('modal-close').addEventListener('click', closeModal);
$('modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

// ---------------------------------------------------------------- boot
function readLastVisit() {
    // "New" badges mark jobs first seen after your previous visit.
    let previous = null;
    try {
        previous = Number(localStorage.getItem(LAST_VISIT_KEY)) || null;
        localStorage.setItem(LAST_VISIT_KEY, String(Date.now()));
    } catch { /* storage unavailable: no "new" badges */ }
    return previous;
}

(async function boot() {
    let appView = 'list';
    try { appView = localStorage.getItem(APP_VIEW_KEY) === 'board' ? 'board' : 'list'; } catch { /* storage unavailable */ }
    store.set({ lastVisit: readLastVisit(), appView });
    try {
        const [profile, allJobs, applications, answers] = await Promise.all([
            api.getProfile(), api.listJobs(), api.listApplications(), api.listAnswers(),
        ]);
        store.set({ profile, applications, answers });
        setJobs({ allJobs, jobView: profile ? 'recommended' : 'all' });
        fillProfileForm(profile);
        prefillSearch(profile);
        initResumeChoice(profile);
        loadSavedSearches();
        const hash = window.location.hash.replace('#', '');
        let initialTab = 'jobs-tab';
        if (hash && document.getElementById(hash)) {
            initialTab = hash;
        } else {
            try { initialTab = localStorage.getItem(TAB_KEY) || 'jobs-tab'; } catch { /* storage unavailable */ }
        }
        if (!profile) initialTab = 'profile-tab';
        showTab(initialTab, false);
    } catch (err) {
        store.set({});
        toast(`Could not load data: ${err.message}`, 'error');
    }
})();
