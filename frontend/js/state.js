// Minimal pub/sub store. Components re-render from this state; nothing here is mock data.
const listeners = new Set();

export const store = {
    state: {
        jobs: [],          // [{ job, match }]: what the list shows (this search, or all saved jobs)
        allJobs: [],       // every stored job
        searchJobs: null,  // the latest search's results (null before the first search)
        jobView: 'all',    // 'search' | 'all'
        jobFilter: 'all',
        jobSort: 'match',
        jobQuery: '',
        visibleCount: 30,
        lastVisit: null,   // ms timestamp of the previous visit, for "new" badges
        applications: [],  // ApplicationRead[]
        appView: 'list',   // 'list' (details, the default) | 'board'
        profile: null,     // CandidateProfile | null
        answers: [],       // ScreeningAnswerRead[] (the answer bank)
        savedSearches: [],
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
export const SUBMITTED = new Set(['APPLIED', 'INTERVIEW', 'OFFER', 'REJECTED']);
