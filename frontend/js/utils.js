// Shared DOM helpers.

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

/** Escape untrusted text (job titles, snippets, etc. come from the open web). */
export function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

/** Only allow http(s) links in hrefs. */
export function safeUrl(url) {
    try {
        const parsed = new URL(url, window.location.href);
        return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : '#';
    } catch {
        return '#';
    }
}

export function splitList(text) {
    return String(text || '').split(',').map((s) => s.trim()).filter(Boolean);
}

export function titleCase(value) {
    return String(value || '').toLowerCase().replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function timeAgo(iso) {
    if (!iso) return '';
    const seconds = Math.max(0, (Date.now() - new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)) / 1000);
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

/** Show a toast. `action` ({label, onClick}) adds a button such as "Undo" and keeps the toast up longer. */
export function toast(message, kind = 'info', action = null) {
    const container = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = `toast toast-${kind}`;
    el.textContent = message;
    if (action) {
        const button = document.createElement('button');
        button.className = 'toast-action';
        button.textContent = action.label;
        button.addEventListener('click', () => { el.remove(); action.onClick(); }, { once: true });
        el.appendChild(button);
    }
    container.appendChild(el);
    const visibleMs = action ? 8000 : 4200;
    setTimeout(() => el.classList.add('leaving'), visibleMs);
    setTimeout(() => el.remove(), visibleMs + 400);
}

export function setBusy(button, busy, busyLabel) {
    if (busy) {
        button.dataset.label = button.innerHTML;
        button.disabled = true;
        button.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> ${esc(busyLabel)}`;
    } else {
        button.disabled = false;
        if (button.dataset.label) button.innerHTML = button.dataset.label;
    }
}

let onModalClose = null;

export function openModal(title, bodyHtml, { onClose } = {}) {
    closeModal();
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal').classList.add('active');
    onModalClose = onClose || null;
}

export function closeModal() {
    document.getElementById('modal').classList.remove('active');
    document.getElementById('modal-body').innerHTML = '';
    const callback = onModalClose;
    onModalClose = null;
    callback?.();
}
