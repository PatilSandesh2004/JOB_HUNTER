// Live service status cards.
import { esc } from '../utils.js';

export function renderHealth(container, health, error) {
    if (error) {
        container.innerHTML = card('Gateway / API', false, error.message);
        return;
    }
    const c = health.components || {};
    const cards = [];
    if (health.gateway) cards.push(card('Go gateway', true, 'Serving UI and proxying /api'));
    if (health.ai_service) {
        cards.push(card('Python AI service', health.ai_service.ok, health.ai_service.url || health.ai_service.detail));
    } else {
        cards.push(card('Python AI service', true, 'Serving directly (no gateway)'));
    }
    if (c.database) cards.push(card('Database', c.database.ok, c.database.driver));
    if (c.searxng) {
        const serper = c.searxng.provider === 'serper';
        const detail = serper ? 'Google results via Serper' : (c.searxng.ok ? c.searxng.url : `Unreachable at ${c.searxng.url}`);
        cards.push(card(serper ? 'Web search (Serper)' : 'SearXNG', c.searxng.ok, detail));
    }
    if (c.llm) cards.push(card('Groq LLM', c.llm.ok, c.llm.ok ? c.llm.model : 'GROQ_API_KEY not set; template letters only'));
    if (c.semantic) {
        const status = {
            ready: c.semantic.model, loading: 'Loading the model (first start downloads ~65 MB)…',
            off: 'Turned off (SEMANTIC_MATCHING=false)', unavailable: 'Could not load the model; scoring without it',
        }[c.semantic.status] || c.semantic.status;
        cards.push(card('Resume similarity (local AI)', c.semantic.ok, status));
    }
    if (c.browser) {
        const mode = c.browser.headless ? 'Chromium (headless)' : 'Chromium (visible)';
        cards.push(card('Browser agent', c.browser.ok, c.browser.ok ? mode : c.browser.detail));
    }
    container.innerHTML = cards.join('');
}

function card(name, ok, detail) {
    return `<div class="health-card">
        <div class="health-status ${ok ? 'online' : 'offline'}"></div>
        <div class="health-info"><h4>${esc(name)}</h4><span>${esc(detail || '')}</span></div>
        <span class="status-pill ${ok ? 'status-online' : 'status-offline'}">${ok ? 'OK' : 'DOWN'}</span>
    </div>`;
}
