/**
 * Session Timeout Monitor
 *
 * Proactively monitors session expiration and warns users before timeout.
 * Works with ModemCheck's sliding window session management.
 *
 * Usage: Call initSessionMonitor() after successful authentication.
 */
(function() {
    'use strict';

    // Configuration - matches server settings
    // Can be overridden via window variables for testing
    const CONFIG = {
        TTL_SECONDS: window.SESSION_TEST_TTL || 3600,                    // 1 hour session TTL
        WARNING_THRESHOLD_SECONDS: window.SESSION_TEST_WARNING || 300,   // Show warning at 5 minutes remaining
        POLL_INTERVAL_MS: window.SESSION_TEST_POLL || 60000,             // Check every 60 seconds
        COUNTDOWN_INTERVAL_MS: 1000,                                      // Update countdown every second
        SESSION_CHECK_ENDPOINT: '/api/auth/session_check'
    };

    // State
    let lastRefreshTime = Date.now();
    let pollIntervalId = null;
    let countdownIntervalId = null;
    let isWarningVisible = false;
    let isExtending = false;
    let isInitialized = false;

    /**
     * Initialize the session monitor.
     * Call this after successful authentication.
     */
    function initSessionMonitor() {
        if (isInitialized) {
            console.log('[SessionMonitor] Already initialized');
            return;
        }

        // Record initial refresh time
        lastRefreshTime = Date.now();

        // Create modal element (hidden initially)
        createModalElement();

        // Start polling
        pollIntervalId = setInterval(checkSessionStatus, CONFIG.POLL_INTERVAL_MS);

        // Also check immediately
        checkSessionStatus();

        // Intercept fetch to track session refreshes
        interceptFetch();

        // Cleanup on page unload
        window.addEventListener('beforeunload', cleanup);

        isInitialized = true;
        console.log('[SessionMonitor] Initialized with TTL:', CONFIG.TTL_SECONDS, 'seconds');
    }

    /**
     * Calculate seconds remaining until session expires.
     */
    function getTimeRemaining() {
        const elapsed = (Date.now() - lastRefreshTime) / 1000;
        return Math.max(0, CONFIG.TTL_SECONDS - elapsed);
    }

    /**
     * Check session status and show warning if needed.
     */
    function checkSessionStatus() {
        const remaining = getTimeRemaining();

        if (remaining <= 0) {
            // Session has expired
            handleTimeout();
            return;
        }

        if (remaining <= CONFIG.WARNING_THRESHOLD_SECONDS && !isWarningVisible) {
            showWarning();
        }
    }

    /**
     * Create the modal DOM element.
     */
    function createModalElement() {
        // Check if already exists
        if (document.getElementById('session-timeout-overlay')) {
            return;
        }

        const overlay = document.createElement('div');
        overlay.id = 'session-timeout-overlay';
        overlay.className = 'session-timeout-overlay';
        overlay.setAttribute('data-testid', 'session-timeout-overlay');
        overlay.innerHTML = `
            <div class="session-timeout-modal" data-testid="session-timeout-modal">
                <div class="session-timeout-icon">&#9200;</div>
                <h2>Session Expiring Soon</h2>
                <p>Your session will expire in <span id="session-countdown" class="session-countdown" data-testid="session-countdown">5:00</span></p>
                <p class="session-timeout-subtext">Would you like to extend your session?</p>
                <div class="session-timeout-actions">
                    <button id="extend-session-btn" class="session-btn session-btn-primary" data-testid="extend-session-btn">
                        Extend Session
                    </button>
                    <button id="logout-now-btn" class="session-btn session-btn-secondary" data-testid="logout-now-btn">
                        Log Out Now
                    </button>
                </div>
                <div id="session-extend-status" class="session-extend-status" data-testid="session-extend-status"></div>
            </div>
        `;

        document.body.appendChild(overlay);

        // Attach event listeners
        document.getElementById('extend-session-btn').addEventListener('click', extendSession);
        document.getElementById('logout-now-btn').addEventListener('click', handleLogoutClick);
    }

    /**
     * Show the warning modal.
     */
    function showWarning() {
        isWarningVisible = true;

        const overlay = document.getElementById('session-timeout-overlay');
        if (overlay) {
            overlay.classList.add('active');
        }

        // Start countdown timer
        updateCountdown();
        countdownIntervalId = setInterval(updateCountdown, CONFIG.COUNTDOWN_INTERVAL_MS);
    }

    /**
     * Hide the warning modal.
     */
    function hideWarning() {
        isWarningVisible = false;

        const overlay = document.getElementById('session-timeout-overlay');
        if (overlay) {
            overlay.classList.remove('active');
        }

        // Stop countdown
        if (countdownIntervalId) {
            clearInterval(countdownIntervalId);
            countdownIntervalId = null;
        }

        // Clear status message
        const statusEl = document.getElementById('session-extend-status');
        if (statusEl) {
            statusEl.textContent = '';
            statusEl.className = 'session-extend-status';
        }
    }

    /**
     * Update the countdown display.
     */
    function updateCountdown() {
        const remaining = getTimeRemaining();

        if (remaining <= 0) {
            handleTimeout();
            return;
        }

        const minutes = Math.floor(remaining / 60);
        const seconds = Math.floor(remaining % 60);
        const display = `${minutes}:${seconds.toString().padStart(2, '0')}`;

        const countdownEl = document.getElementById('session-countdown');
        if (countdownEl) {
            countdownEl.textContent = display;

            // Change color when under 1 minute
            if (remaining < 60) {
                countdownEl.classList.add('urgent');
            } else {
                countdownEl.classList.remove('urgent');
            }
        }
    }

    /**
     * Extend the session by calling the session check endpoint.
     */
    async function extendSession() {
        if (isExtending) return;

        isExtending = true;
        const btn = document.getElementById('extend-session-btn');
        const statusEl = document.getElementById('session-extend-status');

        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Extending...';
        }

        try {
            const response = await fetch(CONFIG.SESSION_CHECK_ENDPOINT, {
                credentials: 'same-origin'
            });

            if (response.ok) {
                const data = await response.json();

                if (data.authenticated) {
                    // Success - session extended
                    lastRefreshTime = Date.now();

                    // Update CSRF token if available globally
                    if (data.csrf_token && typeof window.csrfToken !== 'undefined') {
                        window.csrfToken = data.csrf_token;
                    }

                    if (statusEl) {
                        statusEl.textContent = 'Session extended successfully!';
                        statusEl.className = 'session-extend-status success';
                    }

                    // Hide modal after brief delay
                    setTimeout(hideWarning, 1000);
                } else {
                    // Not authenticated - session already expired
                    handleTimeout();
                }
            } else if (response.status === 401) {
                // Session expired
                handleTimeout();
            } else {
                throw new Error(`Server returned ${response.status}`);
            }
        } catch (error) {
            console.error('[SessionMonitor] Failed to extend session:', error);

            if (statusEl) {
                statusEl.textContent = 'Failed to extend. Please try again.';
                statusEl.className = 'session-extend-status error';
            }
        } finally {
            isExtending = false;
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Extend Session';
            }
        }
    }

    /**
     * Handle logout button click.
     */
    function handleLogoutClick() {
        // Use the page's logout handler if available
        if (typeof window.logoutHandler === 'function') {
            window.logoutHandler();
        } else if (typeof logout === 'function') {
            logout();
        } else {
            // Fallback: redirect to login
            window.location.href = '/login';
        }
    }

    /**
     * Handle session timeout - redirect to login.
     */
    function handleTimeout() {
        cleanup();

        // Redirect to login with timeout indicator
        const returnUrl = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `/login?timeout=1&return=${returnUrl}`;
    }

    /**
     * Intercept fetch to track when session is refreshed.
     * Any successful API call to session_check refreshes the session.
     */
    function interceptFetch() {
        const originalFetch = window.fetch;

        window.fetch = async function(...args) {
            const response = await originalFetch.apply(this, args);

            // Check if this was a session-related call
            const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url);

            if (url && url.includes('/api/auth/session_check') && response.ok) {
                // Session was refreshed
                lastRefreshTime = Date.now();

                // If warning is showing but we have plenty of time, hide it
                if (isWarningVisible && getTimeRemaining() > CONFIG.WARNING_THRESHOLD_SECONDS) {
                    hideWarning();
                }
            }

            return response;
        };
    }

    /**
     * Cleanup intervals and event listeners.
     */
    function cleanup() {
        if (pollIntervalId) {
            clearInterval(pollIntervalId);
            pollIntervalId = null;
        }

        if (countdownIntervalId) {
            clearInterval(countdownIntervalId);
            countdownIntervalId = null;
        }
    }

    // Expose initialization function globally
    window.initSessionMonitor = initSessionMonitor;

})();
