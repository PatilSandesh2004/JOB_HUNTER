import { api } from '../api.js';
import { refreshApplications } from '../app.js';
import { store } from '../state.js';
import { openModal, closeModal, esc, setBusy, toast } from '../utils.js';

let activeQuestionAppId = null;
let activeQuestionLabel = null;

export function checkAgentQuestions(applications) {
    // Find the first application that needs input
    const app = applications.find(a => a.status === 'NEEDS_INPUT' && a.questions?.length > 0);
    
    if (app) {
        const question = app.questions[0];
        // If we are already showing this exact question, don't interrupt
        if (activeQuestionAppId === app.id && activeQuestionLabel === question.label && document.getElementById('agent-chat-modal')) return;
        
        activeQuestionAppId = app.id;
        activeQuestionLabel = question.label;
        showQuestionModal(app, question);
    } else {
        if (activeQuestionAppId && document.getElementById('agent-chat-modal')) {
            closeModal();
        }
        activeQuestionAppId = null;
        activeQuestionLabel = null;
    }
}

function showQuestionModal(app, question) {
    const title = 'JobPilot Agent needs your help';
    
    const inputHtml = question.options?.length
        ? `<select id="agent-question-input" class="chat-input-field">
            <option value="">Choose an option...</option>
            ${question.options.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('')}
           </select>`
        : (question.kind === 'textarea' 
            ? `<textarea id="agent-question-input" class="chat-input-field" rows="3" placeholder="Type your answer..."></textarea>`
            : `<input type="text" id="agent-question-input" class="chat-input-field" placeholder="Type your answer...">`);

    const suggestionHtml = question.suggestion 
        ? `<div class="chat-suggestion">
             <strong>Suggestion:</strong> ${esc(question.suggestion)}
             <button class="btn-ghost btn-sm" id="agent-use-suggestion">Use</button>
           </div>`
        : '';

    const bodyHtml = `
        <div id="agent-chat-modal" class="agent-chat-container">
            <div class="chat-header">
                <h4>Applying to <strong>${esc(app.company)}</strong> for <strong>${esc(app.job_title)}</strong></h4>
                <p class="muted">The agent paused because a required field is missing from your profile.</p>
            </div>
            
            <div class="chat-message bot-message">
                <div class="avatar"><i class="fa-solid fa-robot"></i></div>
                <div class="message-content">
                    <p>I need the following information to proceed with the application:</p>
                    <p class="question-label"><strong>${esc(question.label)}</strong></p>
                    ${suggestionHtml}
                </div>
            </div>
            
            <div class="chat-input-area">
                ${inputHtml}
                <div class="chat-actions">
                    <label class="checkbox-row"><input type="checkbox" id="agent-remember" checked> Remember this answer</label>
                    <button class="btn-primary" id="agent-submit-answer"><i class="fa-solid fa-paper-plane"></i> Submit Answer</button>
                </div>
            </div>
        </div>
    `;

    openModal(title, bodyHtml);

    // If it's a modal, we need to add event listeners after rendering
    setTimeout(() => {
        const input = document.getElementById('agent-question-input');
        const btnUse = document.getElementById('agent-use-suggestion');
        const btnSubmit = document.getElementById('agent-submit-answer');
        
        if (btnUse && input) {
            btnUse.addEventListener('click', () => {
                input.value = question.suggestion;
                input.focus();
            });
        }
        
        if (btnSubmit) {
            btnSubmit.addEventListener('click', async () => {
                const answer = input.value.trim();
                if (!answer) {
                    toast('Please provide an answer', 'warn');
                    return;
                }
                const remember = document.getElementById('agent-remember').checked;
                
                setBusy(btnSubmit, true, 'Submitting...');
                try {
                    await api.answerApplicationQuestion(app.id, question.label, answer, remember);
                    toast('Answer submitted to agent', 'success');
                    // We don't close the modal immediately; we'll let polling refresh the state 
                    // and either show the next question or close it.
                    input.value = '';
                    input.disabled = true;
                    refreshApplications();
                } catch (err) {
                    toast(err.message, 'error');
                } finally {
                    setBusy(btnSubmit, false);
                }
            });
        }
    }, 0);
}
