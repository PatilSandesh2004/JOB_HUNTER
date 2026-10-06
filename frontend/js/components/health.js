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
        cards.push(card('SearXNG', c.searxng.ok, c.searxng.ok ? c.searxng.url : `Unreachable at ${c.searxng.url}`));
    }
    if (c.llm) cards.push(card('Groq LLM', c.llm.ok, c.llm.ok ? c.llm.model : 'GROQ_API_KEY not set; template letters only'));
    if (c.browser) cards.push(card('Browser agent', c.browser.ok, c.browser.headless ? 'Chromium (headless)' : 'Chromium (visible)'));
    container.innerHTML = cards.join('');
}

function card(name, ok, detail) {
    return `<div class="health-card">
        <div class="health-status ${ok ? 'online' : 'offline'}"></div>
        <div class="health-info"><h4>${esc(name)}</h4><span>${esc(detail || '')}</span></div>
        <span class="status-pill ${ok ? 'status-online' : 'status-offline'}">${ok ? 'OK' : 'DOWN'}</span>
    </div>`;
}
