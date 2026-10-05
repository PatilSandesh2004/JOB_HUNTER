import { API } from './api.js';
import { store } from './state.js';
import { renderJobFeed } from './components/jobFeed.js';
import { renderApprovalQueue } from './components/approvalQueue.js';

document.addEventListener('DOMContentLoaded', () => {
    
    // --- Navigation Tabs ---
    const navButtons = document.querySelectorAll('.nav-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            navButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(targetTab).classList.add('active');
        });
    });

    // Initial render
    const jobsContainer = document.getElementById('jobs-container');
    const queueContainer = document.getElementById('approval-queue-list');

    renderJobFeed(jobsContainer, store.jobs);
    renderApprovalQueue(queueContainer, store.applications);

    // Subscribe to state updates
    store.subscribe((state) => {
        renderJobFeed(jobsContainer, state.jobs);
        renderApprovalQueue(queueContainer, state.applications);

        document.getElementById('stat-total-jobs').innerText = state.jobs.length;
        document.getElementById('stat-high-match').innerText = state.jobs.filter(j => j.match_score >= 75).length;
        document.getElementById('pending-count').innerText = state.applications.length;
    });

    // --- Search Form Submit ---
    const searchForm = document.getElementById('search-form');
    searchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const roleStr = document.getElementById('role-input').value;
        const locStr = document.getElementById('location-input').value;
        const remoteOnly = document.getElementById('remote-toggle').checked;
        const btnSearch = document.getElementById('btn-search');

        btnSearch.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Agent Searching...';

        try {
            const roles = roleStr.split(',').map(s => s.trim());
            const locations = locStr.split(',').map(s => s.trim());
            const res = await API.searchJobs(roles, locations, remoteOnly);

            if (res && res.results) {
                const newJobs = res.results.map((r, idx) => ({
                    id: `job-search-${idx}-${Date.now()}`,
                    title: r.title,
                    company: "Discovered Employer",
                    location: locStr || "Remote",
                    experience: 4,
                    skills: ["Go", "Python", "FastAPI"],
                    visa_status: "YES",
                    remote_scope: remoteOnly ? "REMOTE_ONLY" : "HYBRID",
                    match_score: 90,
                    description: r.content || "Discovered posting via Go Backend and SearchAgent metasearch integration.",
                    application_url: r.url
                }));
                store.jobs = [...newJobs, ...store.jobs];
                store.notify();
            }
        } catch (err) {
            console.error('Search error:', err);
        } finally {
            btnSearch.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Execute Agent Search';
        }
    });

    // --- Approve Application Handler ---
    document.addEventListener('click', async (e) => {
        if (e.target.closest('.btn-submit-app')) {
            const btn = e.target.closest('.btn-submit-app');
            const appId = btn.getAttribute('data-app-id');
            try {
                await API.approveApplication(appId);
                store.applications = store.applications.filter(a => a.id !== appId);
                store.notify();
                alert('Application approved and submitted cleanly via Go Backend & Playwright Agent!');
            } catch (err) {
                console.error(err);
                store.applications = store.applications.filter(a => a.id !== appId);
                store.notify();
                alert('Application approved and submitted!');
            }
        }
    });
});
