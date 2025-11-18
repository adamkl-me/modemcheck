// API Configuration for v2 FastAPI
// This file maps v1 CGI endpoints to v2 FastAPI endpoints

const API_CONFIG = {
    // Base URL for API (empty string means same origin)
    baseUrl: '',

    // Endpoint mappings
    endpoints: {
        // Auth endpoints
        auth: '/api/auth',  // Session check
        login: '/api/auth/login',
        logout: '/api/auth/logout',
        changePassword: '/api/auth/change-password',

        // Database query endpoints
        dbApi: '/api/db',
        listModems: '/api/db/list_modems',
        searchChecks: '/api/db/search',
        getCheckByFilename: '/api/db/by_filename',

        // Admin endpoints
        admin: '/api/admin',
        listApiKeys: '/api/admin/api-keys',
        createApiKey: '/api/admin/api-keys',
        deleteApiKey: '/api/admin/api-keys',

        // User management
        users: '/api/users',

        // Data management
        dataManagement: '/api/data',
        deleteCheck: '/api/data/delete',
        bulkDelete: '/api/data/bulk_delete'
    }
};

// Helper function to adapt v1 API calls to v2
async function apiCall(endpoint, options = {}) {
    const url = API_CONFIG.baseUrl + endpoint;

    // Default options
    const defaultOptions = {
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        }
    };

    // Merge options
    const fetchOptions = { ...defaultOptions, ...options };

    try {
        const response = await fetch(url, fetchOptions);

        // Handle redirects to login
        if (response.status === 401) {
            window.location.href = '/login?return=' + encodeURIComponent(window.location.pathname);
            return null;
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: 'Request failed' }));
            throw new Error(errorData.error || errorData.message || `HTTP ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API call failed:', error);
        throw error;
    }
}

// Expose globally for backwards compatibility with existing scripts
window.API_CONFIG = API_CONFIG;
window.apiCall = apiCall;
