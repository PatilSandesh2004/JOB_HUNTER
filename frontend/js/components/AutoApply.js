/**
 * AutoApply.js – Production-grade live auto-apply progress UI.
 *
 * Flow:
 *  1. Caller invokes openAutoApply(jobId) → new tab opens at /auto-apply.html#<jobId>
 *  2. auto-apply.html loads, calls initAutoApply()
 *  3. initAutoApply() calls POST /api/v1/auto-apply/start  → gets {application_id, stream_url}
 *  4. listenAutoApply() opens a fetch()-based SSE stream (needed for auth headers)
 *  5. question / answer / captcha / complete / error events update the live UI
 */

import { api } from '../api.js';

// ─── helpers ─────────────────────────────────────────────────────────────────

function getToken() {
    try { return localStorage.getItem('jobpilot.apiToken') || ''; } catch { return ''; }
}

function authHeaders() {
    const token = getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
}

function toast(msg, type = 'info') {
    const t = document.createElement('div');
    t.className = `aa-toast aa-toast--${type}`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.classList.add('aa-toast--show'), 10);
    setTimeout(() => { t.classList.remove('aa-toast--show'); setTimeout(() => t.remove(), 400); }, 3500);
}

function iconFor(type) {
    return { info: '💡', success: '✅', error: '❌', warning: '⚠️' }[type] || 'ℹ️';
}

// ─── entry points ─────────────────────────────────────────────────────────────

/** Called from the main page when user clicks "Auto‑Apply". Opens a new tab. */
export function openAutoApply(jobId) {
    window.open(`/auto-apply.html#${encodeURIComponent(jobId)}`, '_blank');
}

/** Called once by auto-apply.html on DOMContentLoaded. */
export async function initAutoApply() {
    const jobId = decodeURIComponent(location.hash.slice(1));
    const statusEl   = document.getElementById('aa-status');
    const progressEl = document.getElementById('aa-progress-bar');
    const percentEl  = document.getElementById('aa-percent');
    const container  = document.getElementById('aa-feed');
    const headerJob  = document.getElementById('aa-job-id');

    if (headerJob) headerJob.textContent = jobId || '—';

    if (!jobId) {
        statusEl.textContent = '⚠️  No job ID provided. Close this tab and try again.';
        return;
    }

    statusEl.textContent = '🚀 Starting auto-apply…';

    let applicationId, streamUrl;
    try {
        const res = await api.startAutoApply(jobId);
        applicationId = res.application_id;
        streamUrl     = res.stream_url;
    } catch (e) {
        statusEl.textContent = `❌ Failed to start: ${e.message}`;
        toast('Failed to start Auto‑Apply: ' + e.message, 'error');
        return;
    }

    statusEl.textContent = '📡 Connected — agent is filling the form…';
    document.getElementById('aa-app-id').textContent = applicationId;

    await listenAutoApply({ streamUrl, applicationId, jobId, container, progressEl, percentEl, statusEl });
}

// ─── SSE listener (fetch-based for auth) ─────────────────────────────────────

async function listenAutoApply({ streamUrl, applicationId, jobId, container, progressEl, percentEl, statusEl }) {
    let response;
    try {
        response = await fetch(streamUrl, { headers: { ...authHeaders(), Accept: 'text/event-stream' } });
    } catch (e) {
        statusEl.textContent = '❌ Cannot connect to the event stream. Check the server is running.';
        toast('Stream connection failed.', 'error');
        return;
    }
    if (!response.ok) {
        statusEl.textContent = `❌ Stream error: ${response.status}`;
        return;
    }

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer    = '';
    let total     = 0;
    let answered  = 0;

    const updateProgress = () => {
        const pct = total ? Math.round((answered / total) * 100) : 0;
        progressEl.style.width = pct + '%';
        percentEl.textContent  = pct + '%';
    };

    const handle = (block) => {
        block = block.trim();
        if (!block) return;

        const lines  = block.split('\n');
        let evType   = 'message';
        let evData   = '';
        for (const line of lines) {
            if (line.startsWith('event: ')) evType = line.slice(7).trim();
            else if (line.startsWith('data: ')) evData = line.slice(6).trim();
        }

        let data;
        try { data = JSON.parse(evData); } catch { data = {}; }

        switch (evType) {
            case 'question': handleQuestion(data, container, applicationId); total++; updateProgress(); break;
            case 'answer':   handleAnswer(data, container); answered++; updateProgress(); break;
            case 'captcha':  handleCaptcha(data, container, applicationId); break;
            case 'status':   statusEl.textContent = '📋 ' + (data.message || ''); break;
            case 'complete': handleComplete(data, statusEl, progressEl, percentEl); reader.cancel(); break;
            case 'error':    handleError(data, statusEl); reader.cancel(); break;
        }
    };

    for (;;) {
        let value, done;
        try { ({ value, done } = await reader.read()); } catch { break; }
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep;
        while ((sep = buffer.indexOf('\n\n')) >= 0) {
            handle(buffer.slice(0, sep));
            buffer = buffer.slice(sep + 2);
        }
    }
    if (buffer.trim()) handle(buffer.trim());
}

// ─── event handlers ───────────────────────────────────────────────────────────

function handleQuestion(data, container, applicationId) {
    const id         = data.id || data.label || Math.random().toString(36).slice(2);
    const text       = data.text || data.label || '(question)';
    const type       = data.field_type || 'text';
    const suggestion = data.suggestion || '';
    const isLong     = type === 'textarea' || text.length > 80;

    const card = document.createElement('div');
    card.className = 'aa-card aa-card--pending';
    card.id = `q-${CSS.escape(id)}`;
    card.innerHTML = `
        <div class="aa-card__header">
            <span class="aa-card__icon">❓</span>
            <span class="aa-card__field-type">${esc(type)}</span>
            <span class="aa-card__state-badge">Needs your answer</span>
        </div>
        <div class="aa-card__question">${esc(text)}</div>
        <div class="aa-card__answer">
            ${isLong
                ? `<textarea class="aa-input" rows="3" placeholder="Your answer…">${esc(suggestion)}</textarea>`
                : `<input class="aa-input" type="text" placeholder="Your answer…" value="${esc(suggestion)}">`
            }
            <label class="aa-remember">
                <input type="checkbox" class="aa-remember__check" checked> Remember for future applications
            </label>
            <button class="aa-btn aa-btn--primary aa-submit-answer" data-qid="${esc(id)}">Submit Answer</button>
        </div>
    `;
    container.appendChild(card);
    card.scrollIntoView({ behavior: 'smooth', block: 'end' });

    card.querySelector('.aa-submit-answer').addEventListener('click', async () => {
        const inputEl  = card.querySelector('.aa-input');
        const remember = card.querySelector('.aa-remember__check').checked;
        const answer   = inputEl.value.trim();
        if (!answer) { toast('Please enter an answer before submitting.', 'warning'); return; }

        const btn = card.querySelector('.aa-submit-answer');
        btn.disabled = true;
        btn.textContent = 'Saving…';
        try {
            await api.submitAnswer(applicationId, id, answer, remember);
            // Mark card as answered immediately
            card.classList.remove('aa-card--pending');
            card.classList.add('aa-card--answered');
            card.querySelector('.aa-card__state-badge').textContent = 'Answered';
            card.querySelector('.aa-card__icon').textContent = '✅';
            card.querySelector('.aa-card__answer').innerHTML =
                `<span class="aa-answer-text">${esc(answer)}</span>`;
            toast('Answer saved — agent is resuming…', 'success');
        } catch (err) {
            btn.disabled = false;
            btn.textContent = 'Submit Answer';
            toast('Could not save answer: ' + err.message, 'error');
        }
    });
}

function handleAnswer(data, container) {
    const id     = data.id || data.label || '';
    const answer = data.text || data.answer || '(no answer)';
    const card   = document.getElementById(`q-${CSS.escape(id)}`);
    if (!card) return;
    card.classList.remove('aa-card--pending');
    card.classList.add('aa-card--answered');
    card.querySelector('.aa-card__state-badge').textContent = 'Answered';
    card.querySelector('.aa-card__icon').textContent = '✅';
    const answerEl = card.querySelector('.aa-card__answer');
    answerEl.classList.remove('aa-card__answer--loading');
    answerEl.innerHTML = `<span class="aa-answer-text">${esc(answer)}</span>`;
}

function handleCaptcha(data, container, applicationId) {
    const id      = data.id || 'captcha';
    const siteKey = data.site_key || '';

    // Try to find existing card; otherwise create one
    let card = document.getElementById(`q-${CSS.escape(id)}`);
    if (!card) {
        card = document.createElement('div');
        card.id = `q-${CSS.escape(id)}`;
        container.appendChild(card);
    }
    card.className = 'aa-card aa-card--captcha';
    card.innerHTML = `
        <div class="aa-card__header">
            <span class="aa-card__icon">🔐</span>
            <span class="aa-card__field-type">CAPTCHA</span>
            <span class="aa-card__state-badge aa-card__state-badge--warn">Action Required</span>
        </div>
        <div class="aa-card__question">Please solve the CAPTCHA below to continue.</div>
        <div class="aa-card__answer">
            <div class="h-captcha" data-sitekey="${esc(siteKey)}" id="captcha-widget-${esc(id)}"></div>
            <button class="aa-btn aa-btn--primary" id="captcha-submit-${esc(id)}">Submit CAPTCHA</button>
        </div>
    `;
    card.scrollIntoView({ behavior: 'smooth', block: 'end' });

    // Render hCaptcha if SDK loaded
    if (window.hcaptcha) {
        hcaptcha.render(`captcha-widget-${id}`, {
            sitekey: siteKey,
            callback: (token) => submitCaptchaToken(applicationId, id, token, card),
        });
    }
    document.getElementById(`captcha-submit-${id}`)?.addEventListener('click', () => {
        const token = window.hcaptcha?.getResponse() || '';
        if (!token) { toast('Please complete the CAPTCHA first.', 'warning'); return; }
        submitCaptchaToken(applicationId, id, token, card);
    });
}

async function submitCaptchaToken(applicationId, questionId, token, card) {
    try {
        await api.submitCaptcha(applicationId, questionId, token);
        card.classList.remove('aa-card--captcha');
        card.classList.add('aa-card--answered');
        card.querySelector('.aa-card__state-badge').textContent = 'Solved';
        card.querySelector('.aa-card__icon').textContent = '✅';
        toast('CAPTCHA solved — resuming…', 'success');
    } catch (err) {
        toast('CAPTCHA submission failed: ' + err.message, 'error');
    }
}

function handleComplete(data, statusEl, progressEl, percentEl) {
    statusEl.innerHTML = '🎉 <strong>Application submitted successfully!</strong>';
    statusEl.classList.add('aa-status--success');
    progressEl.style.width = '100%';
    percentEl.textContent  = '100%';
    progressEl.classList.add('aa-progress__bar--done');
    toast('Auto‑Apply complete! 🎉', 'success');
}

function handleError(data, statusEl) {
    const msg = data.message || data.detail || 'Unknown error';
    statusEl.innerHTML = `❌ <strong>Error:</strong> ${esc(msg)}`;
    statusEl.classList.add('aa-status--error');
    toast('Auto‑Apply error: ' + msg, 'error');
}

function esc(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
