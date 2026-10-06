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

export const api = {
    health: () => request('/health'),

    search: (params) => request('/search', { method: 'POST', body: params }),
    listJobs: () => request('/jobs'),
    rescoreJobs: () => request('/jobs/rescore', { method: 'POST' }),

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
    screenshotUrl: (id) => blobUrl(`/applications/${id}/screenshot`),
};
