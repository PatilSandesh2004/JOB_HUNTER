// Minimal pub/sub store. Components re-render from this state; nothing here is mock data.
const listeners = new Set();

export const store = {
    state: {
        jobs: [],          // [{ job, match }]
        applications: [],  // ApplicationRead[]
        profile: null,     // CandidateProfile | null
        jobFilter: 'all',
    },

    set(patch) {
        Object.assign(this.state, patch);
        listeners.forEach((fn) => fn(this.state));
    },

    subscribe(fn) {
        listeners.add(fn);
        return () => listeners.delete(fn);
    },
};

export const IN_FLIGHT = new Set(['PROCESSING', 'SUBMITTING']);
export const NEEDS_REVIEW = new Set(['PENDING_APPROVAL', 'NEEDS_MANUAL', 'FAILED']);
export const AWAITING = 'AWAITING_CONFIRMATION';
export const SUBMITTED = new Set(['APPLIED', 'INTERVIEW', 'REJECTED']);
