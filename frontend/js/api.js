// REST client for the JobPilot API (served by the Go gateway or directly by the AI service).
const BASE = '/api/v1';
const TOKEN_KEY = 'jobpilot.apiToken';

export class ApiError extends Error {
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}

// ---------------------------------------------------------------- access token
// When the server has API_TOKEN set, every /api call needs it. app.js installs `onUnauthorized`
// to ask the user for it; concurrent 401s share one prompt.
export const auth = { onUnauthorized: null };
let pendingPrompt = null;

function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
}

export function setToken(token) {
    try {
        if (token) localStorage.setItem(TOKEN_KEY, token);
        else localStorage.removeItem(TOKEN_KEY);
    } catch { /* storage unavailable: the user is asked again next time */ }
}

function authHeaders() {
    const token = getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
}

async function retryAfterLogin() {
    if (!auth.onUnauthorized) return false;
    pendingPrompt ??= auth.onUnauthorized().finally(() => { pendingPrompt = null; });
    return pendingPrompt;
}

/** fetch() with the token, re-asking for it once on 401. */
async function authedFetch(url, options = {}, retried = false) {
    let response;
    try {
        response = await fetch(url, { ...options, headers: { ...(options.headers || {}), ...authHeaders() } });
    } catch {
        throw new ApiError('Cannot reach the server. Is it running?', 0);
    }
    if (response.status === 401 && !retried && await retryAfterLogin()) {
        return authedFetch(url, options, true);
    }
    return response;
}

async function errorFrom(response) {
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text.slice(0, 200) }; }
    const detail = data?.detail;
    const message = Array.isArray(detail)
        ? detail.map((d) => `${d.loc?.slice(-1)[0] ?? 'field'}: ${d.msg}`).join('; ')
        : detail || `Request failed (${response.status})`;
    return new ApiError(message, response.status);
}

async function request(path, { method = 'GET', body, form } = {}) {
    const options = { method, headers: {} };
    if (form) {
        options.body = form;
    } else if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }
    const response = await authedFetch(`${BASE}${path}`, options);
    if (!response.ok) throw await errorFrom(response);
    const text = await response.text();
    return text ? JSON.parse(text) : null;
}

/** Load a protected file (screenshot, PDF) as an object URL, since <img src> cannot send the token. */
async function blobUrl(path) {
    const response = await authedFetch(`${BASE}${path}`);
    if (!response.ok) throw await errorFrom(response);
    return URL.createObjectURL(await response.blob());
}

/**
 * POST /search/stream: calls onStage({stage, label, detail}) as each step finishes, resolves with the
 * SearchResponse. Server-Sent Events are parsed by hand because EventSource cannot POST or send headers.
 */
async function searchStream(params, onStage) {
    const response = await authedFetch(`${BASE}/search/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
    });
    if (!response.ok) throw await errorFrom(response);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let result = null;
    const handle = (block) => {
        const fields = Object.fromEntries(block.split('\n').map((line) => {
            const at = line.indexOf(': ');
            return [line.slice(0, at), line.slice(at + 2)];
        }));
        const data = JSON.parse(fields.data || 'null');
        if (fields.event === 'stage') onStage(data);
        else if (fields.event === 'result') result = data;
        else if (fields.event === 'error') throw new ApiError(data?.detail || 'Search failed', 500);
    };
    for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let end;
        while ((end = buffer.indexOf('\n\n')) >= 0) {
            handle(buffer.slice(0, end));
            buffer = buffer.slice(end + 2);
        }
    }
    if (buffer.trim()) handle(buffer.trim());
    if (!result) throw new ApiError('The search ended without a result. Try again.', 0);
    return result;
}

export const api = {
    health: () => request('/health'),

    search: (params) => request('/search', { method: 'POST', body: params }),
    searchStream,
    listJobs: () => request('/jobs'),
    rescoreJobs: () => request('/jobs/rescore', { method: 'POST' }),
    recheckJobs: () => request('/jobs/recheck?force=true', { method: 'POST' }),
    hideJob: (id) => request(`/jobs/${encodeURIComponent(id)}/hide`, { method: 'POST' }),
    unhideJob: (id) => request(`/jobs/${encodeURIComponent(id)}/unhide`, { method: 'POST' }),

    // Company job boards searched directly (watchlist), and the job-alert inbox.
    listBoards: () => request('/boards'),
    addBoard: (url) => request('/boards', { method: 'POST', body: { url } }),
    removeBoard: (ats, slug) => request(`/boards/${encodeURIComponent(ats)}/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
    inboxStatus: () => request('/inbox'),
    checkInbox: () => request('/inbox/check', { method: 'POST' }),

    getProfile: () => request('/candidates/me'),
    saveProfile: (profile) => request('/candidates/me', { method: 'PUT', body: profile }),
    uploadResume: (file) => {
        const form = new FormData();
        form.append('file', file);
        return request('/candidates/me/resume', { method: 'POST', form });
    },

    listApplications: () => request('/applications'),
    // mode: 'review' (agent fills, you approve) | 'auto' (agent submits) | 'manual' (you apply on the site)
    createApplication: (jobId, mode = 'review') =>
        request('/applications', { method: 'POST', body: { job_id: jobId, mode } }),
    updateApplication: (id, patch) => request(`/applications/${id}`, { method: 'PATCH', body: patch }),
    approveApplication: (id) => request(`/applications/${id}/approve`, { method: 'POST' }),
    refillApplication: (id) => request(`/applications/${id}/refill`, { method: 'POST' }),
    screenshotUrl: (id) => blobUrl(`/applications/${id}/screenshot`),
    stepScreenshotUrl: (id, name) => blobUrl(`/applications/${id}/screenshots/${encodeURIComponent(name)}`),
    tailoredResumeUrl: (id) => blobUrl(`/applications/${id}/resume`),

    // Answer bank: [{question, answer, source}]; an empty answer deletes the saved one.
    listAnswers: () => request('/screening-answers'),
    saveAnswers: (answers) => request('/screening-answers', { method: 'PUT', body: answers }),
    deleteAnswer: (id) => request(`/screening-answers/${id}`, { method: 'DELETE' }),
};
