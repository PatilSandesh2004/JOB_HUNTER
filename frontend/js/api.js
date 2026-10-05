// Modular API Client for JobPilot Go Backend
export const API = {
    baseUrl: '/api/v1',

    async searchJobs(roles, locations, remoteOnly) {
        const response = await fetch(`${this.baseUrl}/search/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ roles, locations, remote_only: remoteOnly })
        });
        if (!response.ok) throw new Error('Search failed');
        return await response.json();
    },

    async fetchApplications() {
        const response = await fetch(`${this.baseUrl}/applications`);
        if (!response.ok) throw new Error('Failed loading applications');
        return await response.json();
    },

    async approveApplication(appId) {
        const response = await fetch(`${this.baseUrl}/applications/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ application_id: appId })
        });
        if (!response.ok) throw new Error('Failed approving application');
        return await response.json();
    }
};
