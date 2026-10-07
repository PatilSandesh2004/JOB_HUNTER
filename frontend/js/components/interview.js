// Mock interview chat for the Prepare tab.
import { esc } from '../utils.js';

export function renderInterview(container, { messages, turn, busy }) {
    const bubbles = messages.map((m) => `
        <div class="chat-bubble ${m.role === 'candidate' ? 'mine' : 'theirs'}">
            ${m.feedback ? `<div class="chat-feedback"><i class="fa-solid fa-lightbulb"></i> ${esc(m.feedback)}</div>` : ''}
            <div>${esc(m.content)}</div>
        </div>`).join('');
    const summary = turn?.summary
        ? `<div class="chat-summary"><i class="fa-solid fa-flag-checkered"></i> ${esc(turn.summary)}</div>`
        : '';
    const finished = turn?.done;
    const note = turn?.source === 'template'
        ? '<p class="muted small">Prepared questions (AI unavailable): add GROQ_API_KEY for an adaptive interviewer with feedback.</p>'
        : '';
    container.innerHTML = `
        <div class="chat-log">${bubbles || '<p class="muted">Press Start to begin a five-question mock interview for this job.</p>'}${summary}</div>
        ${finished || !messages.length ? '' : `
        <form class="chat-form" id="interview-form">
            <textarea id="interview-answer" rows="3" placeholder="Type your answer… (Ctrl+Enter to send)" ${busy ? 'disabled' : ''}></textarea>
            <button type="submit" class="btn-primary" ${busy ? 'disabled' : ''}><i class="fa-solid fa-paper-plane"></i> Answer</button>
        </form>`}
        ${note}`;
}
