// Modular Human-in-the-Loop Approval Queue Component
export function renderApprovalQueue(container, applications) {
    container.innerHTML = '';

    if (!applications || applications.length === 0) {
        container.innerHTML = '<p class="text-muted">No pending application forms awaiting approval.</p>';
        return;
    }

    applications.forEach(app => {
        const itemHtml = `
            <div class="approval-item" id="${app.id}">
                <div class="approval-info">
                    <h4>${app.job_title} — ${app.company}</h4>
                    <p>Playwright Form Filled &bull; Status: <strong style="color: var(--accent-amber);">${app.status}</strong></p>
                </div>
                <button class="btn-primary btn-submit-app" data-app-id="${app.id}">
                    <i class="fa-solid fa-paper-plane"></i> Approve & Submit
                </button>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', itemHtml);
    });
}
