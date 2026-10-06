// REST client for the JobPilot API (served by the Go gateway or directly by the AI service).
const BASE = '/api/v1';

export class ApiError extends Error {
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}

async function request(path, { method = 'GET', body, form } = {}) {
    const options = { method, headers: {} };
    if (form) {
        options.body = form;
    } else if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }

    let response;
    try {
        response = await fetch(`${BASE}${path}`, options);
    } catch {
        throw new ApiError('Cannot reach the server. Is it running?', 0);
    }

    const text = await response.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = { detail: text.slice(0, 200) };
    }
    if (!response.ok) {
        const detail = data?.detail;
        const message = Array.isArray(detail)
            ? detail.map((d) => `${d.loc?.slice(-1)[0] ?? 'field'}: ${d.msg}`).join('; ')
            : detail || `Request failed (${response.status})`;
        throw new ApiError(message, response.status);
    }
    return data;
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
    screenshotUrl: (id, version) => `${BASE}/applications/${id}/screenshot?v=${encodeURIComponent(version)}`,
};
