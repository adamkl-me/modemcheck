
// Utility functions for timestamp formatting
function formatEpochTime(epoch) {
    if (!epoch || epoch === 0) return '-';
    const date = new Date(epoch * 1000);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}

function formatUptime(seconds) {
    if (!seconds || seconds === 0) return '-';
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    
    if (days > 0) {
        return `${days} days ${hours}h: ${minutes}m: ${secs}s`;
    } else if (hours > 0) {
        return `${hours}h: ${minutes}m: ${secs}s`;
    } else if (minutes > 0) {
        return `${minutes}m: ${secs}s`;
    } else {
        return `${secs}s`;
    }
}

// Global state
let allChecks = [];
let currentCheckIndex = 0;
let charts = {};
let csrfToken = null;
const API_BASE = window.API_CONFIG?.baseUrl || '';

// CSRF token helpers
function updateCsrfFromResponse(response) {
    const newToken = response.headers.get('X-New-CSRF-Token');
    if (newToken) {
        csrfToken = newToken;
    }
}

async function refreshCsrfToken() {
    const sessionResp = await fetch('/api/auth/session_check', { credentials: 'same-origin' });
    const sessionData = await sessionResp.json();
    csrfToken = sessionData.csrf_token;
    return csrfToken;
}

/**
 * Fetch wrapper that handles CSRF tokens automatically.
 * - Adds CSRF token to request headers
 * - Updates token from response headers
 * - Automatically retries once on CSRF failure
 */
async function fetchWithCsrf(url, options = {}) {
    if (!csrfToken) await refreshCsrfToken();

    options.headers = {
        ...options.headers,
        'X-CSRF-Token': csrfToken
    };
    options.credentials = 'same-origin';

    const response = await fetch(url, options);
    updateCsrfFromResponse(response);

    // If CSRF error and we got a new token, retry once
    if (response.status === 403 && csrfToken) {
        const clonedResponse = response.clone();
        try {
            const data = await clonedResponse.json();
            if (data.detail && data.detail.includes('CSRF')) {
                options.headers['X-CSRF-Token'] = csrfToken;
                const retryResponse = await fetch(url, options);
                updateCsrfFromResponse(retryResponse);
                return retryResponse;
            }
        } catch (e) {
            // JSON parse failed
        }
    }

    return response;
}

// Check authentication before initializing
async function checkAuth() {

    try {
        const response = await fetch('/api/auth/session_check', {
            credentials: 'same-origin'
        });

        if (!response.ok) {
            const errorText = await response.text();
            window.location.href = '/login?return=' + encodeURIComponent(window.location.pathname);
            return false;
        }

        const data = await response.json();

        if (!data.authenticated) {
            window.location.href = '/login?return=' + encodeURIComponent(window.location.pathname);
            return false;
        }

        // Store CSRF token for subsequent requests
        csrfToken = data.csrf_token;

        // Show the page content now that auth is verified
        document.querySelector('.container').classList.add('authenticated');

        // Initialize session timeout monitor
        if (typeof initSessionMonitor === 'function') {
            initSessionMonitor();
        }

        // Show admin button for elevated and admin users (both desktop and mobile)
        const userRole = (data.role || '').toUpperCase();
        if (userRole === 'ADMIN' || userRole === 'ELEVATED') {
            const adminBtn = document.getElementById('adminBtn');
            const adminBtnMobile = document.getElementById('adminBtnMobile');
            if (adminBtn) {
                adminBtn.style.display = 'block';
            }
            if (adminBtnMobile) {
                adminBtnMobile.style.display = 'block';
            }
        }

        // Check if password change is required
        if (data.must_change_password || sessionStorage.getItem('must_change_password') === 'true') {
            sessionStorage.removeItem('must_change_password');
            showPasswordChangeDialog();
        }

        return true;
    } catch (error) {
        window.location.href = '/login?return=' + encodeURIComponent(window.location.pathname);
        return false;
    }
}

// Show password change dialog
function showPasswordChangeDialog() {
    // Hide any existing status/error messages while password change dialog is visible
    const statusDiv = document.getElementById('statusMessage');
    if (statusDiv) {
        statusDiv.textContent = '';
    }

    const dialog = document.createElement('div');
    dialog.className = 'pwd-dialog-overlay';
    dialog.innerHTML = `
        <div class="pwd-dialog-content">
            <h2 class="pwd-dialog-title">Change Password Required</h2>
            <p class="pwd-dialog-text">You must change your password before continuing.</p>
            <div id="pwd-error" class="pwd-dialog-error"></div>
            <div style="margin-bottom: 15px;">
                <label class="pwd-dialog-label">New Password</label>
                <input type="password" id="new-password" class="pwd-dialog-input" />
                <div id="pwd-strength-container" style="display: none; margin-top: 8px;">
                    <div class="pwd-strength-bar-container">
                        <div id="pwd-strength-bar" class="pwd-strength-bar"></div>
                    </div>
                    <div id="pwd-strength-text" class="pwd-strength-text"></div>
                </div>
                <div id="pwd-requirements" class="pwd-requirements">
                    <strong>Password Requirements:</strong>
                    <ul>
                        <li id="pwd-req-length" class="pwd-req-unmet">❌ At least 12 characters</li>
                        <li id="pwd-req-uppercase" class="pwd-req-unmet">❌ One uppercase letter</li>
                        <li id="pwd-req-lowercase" class="pwd-req-unmet">❌ One lowercase letter</li>
                        <li id="pwd-req-digit" class="pwd-req-unmet">❌ One digit</li>
                        <li id="pwd-req-special" class="pwd-req-unmet">❌ One special character (!@#$%^&*(),.?":{}|<>)</li>
                    </ul>
                </div>
            </div>
            <div style="margin-bottom: 20px;">
                <label class="pwd-dialog-label">Confirm Password</label>
                <input type="password" id="confirm-password" class="pwd-dialog-input" />
            </div>
            <button id="change-pwd-btn" class="pwd-dialog-btn">Change Password</button>
        </div>
    `;
    document.body.appendChild(dialog);

    // Password strength checking functions
    function checkPasswordRequirements(password) {
        const requirements = {
            length: password.length >= 12,
            uppercase: /[A-Z]/.test(password),
            lowercase: /[a-z]/.test(password),
            digit: /\d/.test(password),
            special: /[!@#$%^&*(),.?":{}|<>]/.test(password)
        };

        // Update requirement indicators with emoji icons
        const lengthEl = document.getElementById('pwd-req-length');
        const uppercaseEl = document.getElementById('pwd-req-uppercase');
        const lowercaseEl = document.getElementById('pwd-req-lowercase');
        const digitEl = document.getElementById('pwd-req-digit');
        const specialEl = document.getElementById('pwd-req-special');

        if (lengthEl) {
            lengthEl.className = requirements.length ? 'pwd-req-met' : 'pwd-req-unmet';
            lengthEl.textContent = (requirements.length ? '✔️ ' : '❌ ') + 'At least 12 characters';
        }
        if (uppercaseEl) {
            uppercaseEl.className = requirements.uppercase ? 'pwd-req-met' : 'pwd-req-unmet';
            uppercaseEl.textContent = (requirements.uppercase ? '✔️ ' : '❌ ') + 'One uppercase letter';
        }
        if (lowercaseEl) {
            lowercaseEl.className = requirements.lowercase ? 'pwd-req-met' : 'pwd-req-unmet';
            lowercaseEl.textContent = (requirements.lowercase ? '✔️ ' : '❌ ') + 'One lowercase letter';
        }
        if (digitEl) {
            digitEl.className = requirements.digit ? 'pwd-req-met' : 'pwd-req-unmet';
            digitEl.textContent = (requirements.digit ? '✔️ ' : '❌ ') + 'One digit';
        }
        if (specialEl) {
            specialEl.className = requirements.special ? 'pwd-req-met' : 'pwd-req-unmet';
            specialEl.textContent = (requirements.special ? '✔️ ' : '❌ ') + 'One special character (!@#$%^&*(),.?":{}|<>)';
        }

        return Object.values(requirements).every(Boolean);
    }

    function calculateBasicStrength(password) {
        let score = 0;
        if (password.length >= 8) score++;
        if (password.length >= 12) score++;
        if (password.length >= 16) score++;

        const hasLower = /[a-z]/.test(password);
        const hasUpper = /[A-Z]/.test(password);
        const hasDigit = /\d/.test(password);
        const hasSpecial = /[!@#$%^&*(),.?":{}|<>]/.test(password);

        const varietyCount = [hasLower, hasUpper, hasDigit, hasSpecial].filter(Boolean).length;
        if (varietyCount >= 3) score++;

        return Math.min(score, 4);
    }

    function updatePasswordStrength(password) {
        const strengthContainer = document.getElementById('pwd-strength-container');
        const strengthBar = document.getElementById('pwd-strength-bar');
        const strengthText = document.getElementById('pwd-strength-text');

        if (!password || password.length === 0) {
            if (strengthContainer) strengthContainer.style.display = 'none';
            return;
        }

        if (strengthContainer) strengthContainer.style.display = 'block';

        const meetsRequirements = checkPasswordRequirements(password);
        const score = calculateBasicStrength(password);

        // Get theme-aware colors from CSS variables
        const style = getComputedStyle(document.documentElement);
        const themeColors = {
            neutral: style.getPropertyValue('--border-color').trim() || '#e0e0e0',
            error: style.getPropertyValue('--error').trim() || '#ef4444',
            warning: style.getPropertyValue('--warning').trim() || '#f59e0b',
            success: style.getPropertyValue('--success').trim() || '#10b981',
            successDark: '#059669', // Keep dark green for very strong
            muted: style.getPropertyValue('--text-muted').trim() || '#999'
        };

        // Update strength bar
        const widths = ['0%', '25%', '50%', '75%', '100%'];
        const colors = [themeColors.neutral, themeColors.error, themeColors.warning, themeColors.success, themeColors.successDark];
        if (strengthBar) {
            strengthBar.style.width = widths[score];
            strengthBar.style.backgroundColor = colors[score];
        }

        // Update strength text
        const strengthLabels = ['Very Weak', 'Weak', 'Fair', 'Strong', 'Very Strong'];
        const textColors = [themeColors.muted, themeColors.error, themeColors.warning, themeColors.success, themeColors.successDark];
        let strengthMessage = strengthLabels[score];

        if (!meetsRequirements && score > 0) {
            strengthMessage += ' (does not meet requirements)';
        }

        if (strengthText) {
            strengthText.textContent = strengthMessage;
            strengthText.style.color = textColors[score];
            strengthText.style.fontWeight = score > 0 ? '600' : 'normal';
        }
    }

    // Setup password strength meter
    const newPasswordInput = document.getElementById('new-password');
    if (newPasswordInput) {
        newPasswordInput.addEventListener('input', function() {
            updatePasswordStrength(this.value);
        });
    }

    document.getElementById('change-pwd-btn').addEventListener('click', async () => {
        const newPassword = document.getElementById('new-password').value;
        const confirmPassword = document.getElementById('confirm-password').value;
        const errorDiv = document.getElementById('pwd-error');

        errorDiv.style.display = 'none';

        if (!newPassword || newPassword.length < 12) {
            errorDiv.textContent = 'Password must be at least 12 characters';
            errorDiv.style.display = 'block';
            return;
        }

        // Check if password meets all requirements
        const meetsRequirements = checkPasswordRequirements(newPassword);
        if (!meetsRequirements) {
            errorDiv.textContent = 'Password does not meet all requirements';
            errorDiv.style.display = 'block';
            return;
        }

        if (newPassword !== confirmPassword) {
            errorDiv.textContent = 'Passwords do not match';
            errorDiv.style.display = 'block';
            return;
        }
        
        try {
            const response = await fetch('/api/auth/change_own_password', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    new_password: newPassword
                }),
                credentials: 'same-origin'
            });

            const data = await response.json();
            
            if (data.success) {
                document.body.removeChild(dialog);
                // Reload page to refresh auth state and clear any error messages
                window.location.reload();
            } else {
                errorDiv.textContent = data.error || 'Failed to change password';
                errorDiv.style.display = 'block';
            }
        } catch (error) {
            errorDiv.textContent = 'Network error. Please try again.';
            errorDiv.style.display = 'block';
        }
    });
}

// Logout function
async function logout() {
    try {
        // Get fresh token if we don't have one
        if (!csrfToken) await refreshCsrfToken();

        await fetch('/api/auth/logout', {
            method: 'POST',
            headers: {
                'X-CSRF-Token': csrfToken
            },
            credentials: 'same-origin'
        });

        window.location.href = '/login';
    } catch (error) {
        console.error('Logout failed:', error);
        window.location.href = '/login';
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', async function() {

    // Check authentication first
    const isAuthenticated = await checkAuth();
    if (!isAuthenticated) return;

    // Setup logout buttons (desktop and mobile)
    document.getElementById('logoutBtn').addEventListener('click', logout);
    document.getElementById('logoutBtnMobile').addEventListener('click', () => {
        closeMobileMenu();
        logout();
    });

    // Setup admin buttons (desktop and mobile - if visible)
    const adminBtn = document.getElementById('adminBtn');
    const adminBtnMobile = document.getElementById('adminBtnMobile');

    if (adminBtn && adminBtn.style.display !== 'none') {
        adminBtn.addEventListener('click', () => {
            window.location.href = '/admin';
        });
        adminBtnMobile.addEventListener('click', () => {
            closeMobileMenu();
            window.location.href = '/admin';
        });
    }

    // Don't set default dates - let user choose or load all data

    loadModemList();
});

// Mobile menu toggle functions
function toggleMobileMenu() {
    const menu = document.querySelector('.mobile-menu');
    const overlay = document.querySelector('.menu-overlay');
    const hamburger = document.querySelector('.hamburger');

    menu.classList.toggle('active');
    overlay.classList.toggle('active');
    hamburger.classList.toggle('active');
}

function closeMobileMenu() {
    const menu = document.querySelector('.mobile-menu');
    const overlay = document.querySelector('.menu-overlay');
    const hamburger = document.querySelector('.hamburger');

    menu.classList.remove('active');
    overlay.classList.remove('active');
    hamburger.classList.remove('active');
}

// Set default date range to last 14 days
function setDefaultDateRange() {
    const endDate = new Date();
    const startDate = new Date();
    startDate.setDate(startDate.getDate() - 14);

    // Format dates as YYYY-MM-DD
    const formatDate = (date) => {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    };

    document.getElementById('startDate').value = formatDate(startDate);
    document.getElementById('endDate').value = formatDate(endDate);
}

// Load list of available modems
async function loadModemList() {

    try {
        const response = await fetch(`/api/db/list_modems`, {
            credentials: 'same-origin'
        });

        if (!response.ok) {
            let data = null;
            try {
                data = await response.json();
            } catch (e) {
                // Response is not JSON
            }
            showStatus(getErrorMessage(response, data), 'error');
            return;
        }

        const data = await response.json();

        if (!data.modems || data.modems.length === 0) {
            console.warn("DEBUG: No modems found in response");
            showStatus('No modems found. Upload some data first.', 'error');
            return;
        }

        const dropdown = document.getElementById('modemDropdown');
        const searchInput = document.getElementById('modemSearchInput');
        const hiddenSelect = document.getElementById('modemSelect');
        
        dropdown.innerHTML = '';

        // Store modems for filtering
        window.allModems = data.modems;

        data.modems.forEach(modem => {
            const option = document.createElement('div');
            option.className = 'searchable-option';
            option.dataset.value = modem.modem_id;
            const displayText = modem.modem_type ? `${modem.modem_type} - ${modem.modem_id.split('-').pop()}` : modem.modem_id;
            option.textContent = displayText;
            option.addEventListener('click', () => selectModem(modem.modem_id, displayText));
            dropdown.appendChild(option);
        });

        
        // Setup searchable dropdown event listeners
        setupSearchableDropdown();
    } catch (error) {
        console.error('Error loading modem list:', error);
        showStatus('Unable to load modem list. Please try again.', 'error');
    }
}

// Setup searchable dropdown functionality
function setupSearchableDropdown() {
    const searchInput = document.getElementById('modemSearchInput');
    const dropdown = document.getElementById('modemDropdown');
    const wrapper = searchInput.closest('.searchable-select');

    // Show dropdown when clicking on input
    searchInput.addEventListener('click', () => {
        dropdown.classList.add('show');
        wrapper.classList.add('open');
        searchInput.removeAttribute('readonly');
        searchInput.focus();
        searchInput.select();
    });

    // Filter options as user types
    searchInput.addEventListener('input', () => {
        const searchTerm = searchInput.value.toLowerCase();
        const options = dropdown.querySelectorAll('.searchable-option');

        options.forEach(option => {
            const text = option.textContent.toLowerCase();
            if (text.includes(searchTerm)) {
                option.classList.remove('hidden');
            } else {
                option.classList.add('hidden');
            }
        });

        dropdown.classList.add('show');
        wrapper.classList.add('open');
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.remove('show');
            wrapper.classList.remove('open');
            // Reset to selected value if user clicked away
            const hiddenSelect = document.getElementById('modemSelect');
            if (hiddenSelect.value) {
                const selectedOption = dropdown.querySelector(`[data-value="${hiddenSelect.value}"]`);
                if (selectedOption) {
                    searchInput.value = selectedOption.textContent;
                }
            } else {
                searchInput.value = '';
                searchInput.placeholder = '-- Select a modem --';
            }
            searchInput.setAttribute('readonly', 'readonly');
        }
    });
}

// Select a modem from the dropdown
function selectModem(modemId, modemText) {
    const searchInput = document.getElementById('modemSearchInput');
    const dropdown = document.getElementById('modemDropdown');
    const hiddenSelect = document.getElementById('modemSelect');
    const wrapper = searchInput.closest('.searchable-select');

    searchInput.value = modemText;
    hiddenSelect.value = modemId;
    dropdown.classList.remove('show');
    wrapper.classList.remove('open');
    searchInput.setAttribute('readonly', 'readonly');

    // Update selected styling
    dropdown.querySelectorAll('.searchable-option').forEach(opt => {
        opt.classList.remove('selected');
    });
    const selectedOption = dropdown.querySelector(`[data-value="${modemId}"]`);
    if (selectedOption) {
        selectedOption.classList.add('selected');
    }

    onModemChanged();
}

function onModemChanged() {
    const modemId = document.getElementById('modemSelect').value;
    document.getElementById('loadBtn').disabled = !modemId;
}

function showStatus(message, type = 'info') {
    const statusDiv = document.getElementById('statusMessage');
    statusDiv.textContent = message;
    // Use CSS variables for theme-aware status colors
    const style = getComputedStyle(document.documentElement);
    const errorColor = style.getPropertyValue('--error').trim() || '#f56565';
    const successColor = style.getPropertyValue('--success').trim() || '#48bb78';
    const infoColor = style.getPropertyValue('--text-muted').trim() || '#555';
    statusDiv.style.color = type === 'error' ? errorColor : type === 'success' ? successColor : infoColor;
}

// Load data for selected modem and date range
// Uses progressive loading: fast trend data first, then full data for single-check view
async function loadData() {
    const modemId = document.getElementById('modemSelect').value;
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;

    if (!modemId) {
        showStatus('Please select a modem', 'error');
        return;
    }

    showStatus('Loading data...', 'info');
    document.getElementById('loadBtn').disabled = true;

    // Reset data arrays
    trendData = [];
    allChecks = [];

    try {
        // Prepare request body
        const requestBody = {
            modem_id: modemId,
            start_date: startDate || '2020-01-01',
            end_date: endDate || new Date().toISOString().split('T')[0],
            limit: 10000
        };

        // Start both requests in parallel for faster loading
        // Trend data is smaller (~500 bytes/check) and faster to load
        // Full data is larger (~15-50KB/check) but needed for single-check view
        const [trendResponse, fullResponse] = await Promise.all([
            fetch('/api/db/get_trend_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
                credentials: 'same-origin'
            }),
            fetch('/api/db/get_all_checks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
                credentials: 'same-origin'
            })
        ]);

        // Process trend data (arrives faster due to smaller size)
        const trendResult = await trendResponse.json();
        if (trendResult.success && trendResult.data && trendResult.data.length > 0) {
            trendData = trendResult.data;
            showStatus(`Loaded ${trendData.length} check(s) for trends`, 'success');
        }

        // Process full data for single-check view
        const fullResult = await fullResponse.json();
        if (!fullResult.success || !fullResult.checks || fullResult.checks.length === 0) {
            if (trendData.length === 0) {
                showStatus('No data found for the selected criteria', 'error');
                document.getElementById('loadBtn').disabled = false;
                return;
            }
            // We have trend data but no full data - can still show trends
            showStatus('Warning: Full check data unavailable, trends only', 'warning');
        } else {
            // Extract full_data from each check
            allChecks = fullResult.checks.map(check => check.full_data);

            // Sort by check time (ascending for timeline navigation)
            allChecks.sort((a, b) => {
                const timeA = a.sysinfo?.checktime || 0;
                const timeB = b.sysinfo?.checktime || 0;
                return timeA - timeB;
            });

            currentCheckIndex = allChecks.length - 1; // Start with most recent
            updateTimelineNav();
        }

        // Hide welcome message once data is loaded
        const welcomeMsg = document.getElementById('welcomeMessage');
        if (welcomeMsg) {
            welcomeMsg.style.display = 'none';
        }

        // Show Single View by default (if we have full data)
        if (allChecks.length > 0) {
            showSingleView();
            displayCurrentCheck();
            showStatus(`Loaded ${allChecks.length} check(s) successfully`, 'success');
        } else if (trendData.length > 0) {
            // Only trend data available - show trends view
            showTrendsView();
        }

    } catch (error) {
        console.error('Error loading data:', error);
        showStatus('Unable to load data. Please try again.', 'error');
    } finally {
        document.getElementById('loadBtn').disabled = false;
    }
}

// View switching
function showSingleView() {
    document.getElementById('singleView').classList.add('active');
    document.getElementById('trendsView').classList.remove('active');
    document.querySelectorAll('.view-btn')[0].classList.add('active');
    document.querySelectorAll('.view-btn')[1].classList.remove('active');
    
    const nav = document.getElementById('timelineNav');
    if (allChecks.length > 0) {
        nav.classList.add('active');
    }
}

function showTrendsView() {
    document.getElementById('singleView').classList.remove('active');
    document.getElementById('trendsView').classList.add('active');
    document.querySelectorAll('.view-btn')[0].classList.remove('active');
    document.querySelectorAll('.view-btn')[1].classList.add('active');

    document.getElementById('timelineNav').classList.remove('active');

    // Use pre-aggregated data if available (much faster rendering)
    // Falls back to client-side aggregation if trendData is empty
    if (trendData.length > 0) {
        renderTrendChartsFromPreAggregated();
    } else if (allChecks.length > 0) {
        renderTrendChartsFromChecks();
    }
}

// Timeline navigation
function updateTimelineNav() {
    const nav = document.getElementById('timelineNav');
    const slider = document.getElementById('timelineSlider');
    const info = document.getElementById('timelineInfo');
    
    if (allChecks.length === 0) {
        nav.classList.remove('active');
        return;
    }
    
    nav.classList.add('active');
    slider.max = allChecks.length - 1;
    slider.value = currentCheckIndex;
    
    const current = allChecks[currentCheckIndex];
    const checkTime = current.sysinfo?.checktime 
        ? formatEpochTime(current.sysinfo.checktime) 
        : 'Unknown';
    info.textContent = `Check ${currentCheckIndex + 1} of ${allChecks.length}: ${checkTime}`;
    
    document.getElementById('firstBtn').disabled = currentCheckIndex === 0;
    document.getElementById('prevBtn').disabled = currentCheckIndex === 0;
    document.getElementById('nextBtn').disabled = currentCheckIndex === allChecks.length - 1;
    document.getElementById('lastBtn').disabled = currentCheckIndex === allChecks.length - 1;
}

function navigateToIndex(index) {
    // Validate bounds to prevent invalid index access
    const parsed = parseInt(index);
    if (isNaN(parsed) || allChecks.length === 0) return;
    currentCheckIndex = Math.max(0, Math.min(allChecks.length - 1, parsed));
    updateTimelineNav();
    displayCurrentCheck();
}

function navigateToFirst() { navigateToIndex(0); }
function navigatePrevious() { if (currentCheckIndex > 0) navigateToIndex(currentCheckIndex - 1); }
function navigateNext() { if (currentCheckIndex < allChecks.length - 1) navigateToIndex(currentCheckIndex + 1); }
function navigateToLast() { navigateToIndex(allChecks.length - 1); }

// Display current check
function displayCurrentCheck() {
    if (allChecks.length === 0) return;
    
    const data = allChecks[currentCheckIndex];
    
    document.getElementById('checktime').textContent = formatEpochTime(data.sysinfo?.checktime);
    document.getElementById('modemtype').textContent = data.sysinfo?.modemtype || '-';
    document.getElementById('modemmac').textContent = data.sysinfo?.modemmac || '-';
    document.getElementById('firmware').textContent = data.sysinfo?.firmware || '-';
    document.getElementById('uptime').textContent = formatUptime(data.sysinfo?.uptime);
    document.getElementById('systime').textContent = formatEpochTime(data.sysinfo?.systime);

    // Format client version info
    const clientVersion = data.client_version || '-';
    const clientOS = data.client_os || '';
    const clientArch = data.client_arch || '';
    let clientInfo = clientVersion;
    if (clientOS && clientArch) {
        clientInfo += ` (${clientOS}/${clientArch})`;
    } else if (clientOS) {
        clientInfo += ` (${clientOS})`;
    }
    document.getElementById('clientinfo').textContent = clientInfo;

    // Display detection status
    const detectionStatus = data.sysinfo?.detection_status || '';
    if (detectionStatus === 'success') {
        document.getElementById('detection_status').textContent = 'Success';
    } else if (detectionStatus === 'detection_failed') {
        document.getElementById('detection_status').textContent = 'Failed';
    } else {
        document.getElementById('detection_status').textContent = '-';
    }

    // Display public IP
    document.getElementById('public_ip').textContent = data.public_ip || '-';

    // Display ISP and ASN combined
    const ispName = data.isp_name || '';
    const asn = data.asn || '';
    let ispInfo = '';
    if (ispName && asn) {
        ispInfo = `${ispName} (${asn})`;
    } else if (ispName) {
        ispInfo = ispName;
    } else if (asn) {
        ispInfo = asn;
    } else {
        ispInfo = '-';
    }
    document.getElementById('isp_info').textContent = ispInfo;

    // Display speed test status (in speed-cards section now)
    const speedTestEnabled = data.speedtest_enabled;
    const downloadSpeed = data.iperf3test_dl;
    const uploadSpeed = data.iperf3test_ul;

    let speedTestStatus = '';
    if (speedTestEnabled === true || speedTestEnabled === 1) {
        // Check if speed test was skipped (value is -2)
        if (downloadSpeed === -2 || uploadSpeed === -2) {
            speedTestStatus = 'Skipped';
        } else if (downloadSpeed > 0 && uploadSpeed > 0) {
            speedTestStatus = 'Enabled';
        } else if (downloadSpeed === -1 || uploadSpeed === -1) {
            speedTestStatus = 'Failed';
        } else {
            speedTestStatus = 'Failed';
        }
    } else if (speedTestEnabled === false || speedTestEnabled === 0) {
        speedTestStatus = 'Disabled';
    } else {
        speedTestStatus = '-';
    }
    document.getElementById('speedtest_status').textContent = speedTestStatus;

    // Display speed test server in small text below status
    const serverName = data.speedtest_server_name || '';
    const serverID = data.speedtest_server_id || '';
    let serverInfo = '';
    if (serverName && serverID) {
        serverInfo = `Server ID: ${serverID} (${serverName})`;
    } else if (serverName) {
        serverInfo = serverName;
    } else if (serverID) {
        serverInfo = `Server ID: ${serverID}`;
    }
    document.getElementById('speedtest_server').textContent = serverInfo;

    // Display Speed Test Ping (average latency prominently)
    if (data.speedtest_latency) {
        document.getElementById('speedtest_ping').textContent = `${data.speedtest_latency.toFixed(1)} ms`;
    } else {
        document.getElementById('speedtest_ping').textContent = '-';
    }

    // Display speed test ping details (Max | Jitter)
    const speedTestPingParts = [];
    if (data.speedtest_max_latency) {
        speedTestPingParts.push(`Max: ${data.speedtest_max_latency.toFixed(1)} ms`);
    }
    if (data.speedtest_jitter) {
        speedTestPingParts.push(`Jitter: ${data.speedtest_jitter.toFixed(1)} ms`);
    }
    document.getElementById('speedtest_ping_details').textContent = speedTestPingParts.join(' | ');

    // Display download speed and loaded latency
    document.getElementById('iperf3_dl').textContent = formatSpeed(data.iperf3test_dl);
    const dlLoadedParts = [];
    if (data.speedtest_dl_latency) {
        dlLoadedParts.push(`Loaded latency: ${data.speedtest_dl_latency.toFixed(1)} ms`);
    }
    document.getElementById('iperf3_dl_loaded').textContent = dlLoadedParts.join(' | ');

    // Display upload speed and loaded jitter
    document.getElementById('iperf3_ul').textContent = formatSpeed(data.iperf3test_ul);
    const ulLoadedParts = [];
    if (data.speedtest_ul_jitter) {
        ulLoadedParts.push(`Loaded jitter: ${data.speedtest_ul_jitter.toFixed(1)} ms`);
    }
    document.getElementById('iperf3_ul_loaded').textContent = ulLoadedParts.join(' | ');

    // Display ping Google results with jitter and max latency
    const pingGoogleAvg = data.ping_google_avg || '-';
    const pingGoogleLoss = data.ping_google_loss || '';
    const pingGoogleJitter = data.ping_google_jitter || '';
    const pingGoogleMax = data.ping_google_max_latency || '';

    if (pingGoogleAvg !== '-' && pingGoogleAvg !== 'Failed') {
        document.getElementById('ping_google').textContent = `${parseFloat(pingGoogleAvg).toFixed(1)} ms`;
    } else {
        document.getElementById('ping_google').textContent = pingGoogleAvg;
    }

    const googleParts = [];
    if (pingGoogleMax && pingGoogleMax !== 'N/A') {
        googleParts.push(`Max: ${parseFloat(pingGoogleMax).toFixed(1)} ms`);
    }
    if (pingGoogleJitter && pingGoogleJitter !== 'N/A') {
        googleParts.push(`Jitter: ${parseFloat(pingGoogleJitter).toFixed(1)} ms`);
    }

    // Build details using DOM manipulation to support traceroute link
    const googleTopLineParts = googleParts.join(' | ');
    const pingGoogleDetailsEl = document.getElementById('ping_google_details');
    pingGoogleDetailsEl.textContent = ''; // Clear existing content

    if (googleTopLineParts) {
        pingGoogleDetailsEl.appendChild(document.createTextNode(googleTopLineParts));
    }
    if (pingGoogleLoss && pingGoogleLoss !== 'N/A') {
        if (googleTopLineParts) {
            pingGoogleDetailsEl.appendChild(document.createElement('br'));
        }
        pingGoogleDetailsEl.appendChild(document.createTextNode('Loss: ' + pingGoogleLoss));

        // Add traceroute link inline with loss (if data available)
        if (data.traceroute_google && data.traceroute_google.status) {
            pingGoogleDetailsEl.appendChild(document.createTextNode(' | '));
            pingGoogleDetailsEl.appendChild(createTracerouteLink(data.traceroute_google));
        }
    } else if (data.traceroute_google && data.traceroute_google.status) {
        // Show traceroute link even without loss data
        if (googleTopLineParts) {
            pingGoogleDetailsEl.appendChild(document.createElement('br'));
        }
        pingGoogleDetailsEl.appendChild(createTracerouteLink(data.traceroute_google));
    }

    // Display ping Cloudflare results with jitter and max latency
    const pingCloudflareAvg = data.ping_cloudflare_avg || '-';
    const pingCloudflareLoss = data.ping_cloudflare_loss || '';
    const pingCloudflareJitter = data.ping_cloudflare_jitter || '';
    const pingCloudflareMax = data.ping_cloudflare_max_latency || '';

    if (pingCloudflareAvg !== '-' && pingCloudflareAvg !== 'Failed') {
        document.getElementById('ping_cloudflare').textContent = `${parseFloat(pingCloudflareAvg).toFixed(1)} ms`;
    } else {
        document.getElementById('ping_cloudflare').textContent = pingCloudflareAvg;
    }

    const cloudflareParts = [];
    if (pingCloudflareMax && pingCloudflareMax !== 'N/A') {
        cloudflareParts.push(`Max: ${parseFloat(pingCloudflareMax).toFixed(1)} ms`);
    }
    if (pingCloudflareJitter && pingCloudflareJitter !== 'N/A') {
        cloudflareParts.push(`Jitter: ${parseFloat(pingCloudflareJitter).toFixed(1)} ms`);
    }

    // Build details text with Loss always on its own line
    const cloudflareTopLineParts = cloudflareParts.join(' | ');
    const cloudflareDetailsLines = [];
    if (cloudflareTopLineParts) {
        cloudflareDetailsLines.push(cloudflareTopLineParts);
    }
    if (pingCloudflareLoss && pingCloudflareLoss !== 'N/A') {
        cloudflareDetailsLines.push('Loss: ' + pingCloudflareLoss);
    }
    document.getElementById('ping_cloudflare_details').textContent = cloudflareDetailsLines.join('\n');
    
    populateTable('rxTable', data.rx, ['portid', 'frequency', 'power', 'snr', 'octets', 'correcteds', 'uncorrectds']);
    populateTable('rxofdmTable', data.rxofdm, ['portid', 'subcarr0freq', 'plclock', 'ncplock', 'mdc1lock', 'plcpower', 'plcsnr', 'octets', 'correcteds', 'uncorrectds']);
    populateTable('txTable', data.tx, ['portid', 'frequency', 'power']);
    populateTable('txofdmTable', data.txofdm, ['portid', 'state', 'subcarr0freq', 'power', 'activescs', 'excludedscs', 'notusedscs', 'minislots', 'interfacespeed']);
    populateTable('eventlogTable', data.eventlog, ['time', 'id', 'event']);
}

function populateTable(tableId, data, keys) {
    const tableBody = document.getElementById(tableId).querySelector('tbody');
    tableBody.innerHTML = '';
    
    if (!data || data.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = keys.length;
        cell.className = 'empty-state';
        cell.textContent = 'No data available';
        row.appendChild(cell);
        tableBody.appendChild(row);
        return;
    }
    
    data.forEach(item => {
        const row = document.createElement('tr');
        keys.forEach(key => {
            const cell = document.createElement('td');
            let value = item[key];
            
            // Format timestamps in event logs
            if (key === 'time' && tableId === 'eventlogTable' && typeof value === 'number') {
                value = formatEpochTime(value);
            }
            
            cell.textContent = value !== undefined && value !== null ? value : 'n/a';
            row.appendChild(cell);
        });
        tableBody.appendChild(row);
    });
}

function parseSpeed(speed) {
    // Handle numeric values (new format) - already in Mbps
    if (typeof speed === 'number') {
        return speed <= 0 ? null : speed;
    }
    
    // Handle string values (old format) - parse and convert to Mbps
    if (!speed || speed === '-' || speed === 'Failed' || speed === 'Disabled') return null;
    const match = speed.match(/(\d+\.?\d*)\s*(\w+)/);
    if (!match) return null;
    const value = parseFloat(match[1]);
    const unit = match[2].toLowerCase();
    if (unit.includes('gbits') || unit.includes('gb')) return value * 1000;
    if (unit.includes('mbits') || unit.includes('mb')) return value;
    if (unit.includes('kbits') || unit.includes('kb')) return value / 1000;
    return value;
}

function formatSpeed(mbps) {
    if (mbps === null || mbps === undefined || mbps <= 0) return '-';
    // Show decimals only for values < 1 Mbps
    if (mbps < 1) {
        return mbps.toFixed(2) + ' Mbps';
    }
    return Math.round(mbps) + ' Mbps';
}
function renderTrendChartsFromChecks() {
    if (allChecks.length < 1) {
        showStatus('No data available to display trends', 'error');
        return;
    }
    
    // Destroy all existing charts to prevent canvas reuse errors
    Object.keys(charts).forEach(key => {
        if (charts[key]) {
            charts[key].destroy();
            charts[key] = null;
        }
    });
    
    // Extract timestamps for time-based x-axis
    const timestamps = allChecks.map(c => c.sysinfo?.checktime || 0);
    
    // Speed data with limits
    const uploadSpeeds = allChecks.map(c => parseSpeed(c.iperf3test_ul));
    const downloadSpeeds = allChecks.map(c => parseSpeed(c.iperf3test_dl));
    const uploadLimits = allChecks.map(c => c.iperf3uploadlimit || null);
    const downloadLimits = allChecks.map(c => c.iperf3downloadlimit || null);
    
    // Ping data
    const googlePingAvg = allChecks.map(c => {
        const val = parseFloat(c.ping_google_avg);
        return isNaN(val) ? null : val;
    });
    const googlePingLoss = allChecks.map(c => {
        const val = parseFloat(c.ping_google_loss);
        return isNaN(val) ? null : val;
    });
    const cloudflarePingAvg = allChecks.map(c => {
        const val = parseFloat(c.ping_cloudflare_avg);
        return isNaN(val) ? null : val;
    });
    const cloudflarePingLoss = allChecks.map(c => {
        const val = parseFloat(c.ping_cloudflare_loss);
        return isNaN(val) ? null : val;
    });

    // New latency metrics for speed test and ping tests
    const speedtestLatency = allChecks.map(c => c.speedtest_latency || null);
    const speedtestMaxLatency = allChecks.map(c => c.speedtest_max_latency || null);
    const googleMaxLatency = allChecks.map(c => {
        const val = c.ping_google_max_latency;
        return (val && val !== 'N/A' && val !== 'Failed') ? parseFloat(val) : null;
    });
    const cloudflareMaxLatency = allChecks.map(c => {
        const val = c.ping_cloudflare_max_latency;
        return (val && val !== 'N/A' && val !== 'Failed') ? parseFloat(val) : null;
    });

    // RX SC-QAM Power data
    const rxScqamPowerData = allChecks.map(c => {
        if (!c.rx || c.rx.length === 0) return { min: null, avg: null, max: null };
        const powers = c.rx.map(ch => parseFloat(ch.power)).filter(p => !isNaN(p) && isFinite(p));
        if (powers.length === 0) return { min: null, avg: null, max: null };
        return {
            min: Math.min(...powers),
            avg: powers.reduce((a, b) => a + b) / powers.length,
            max: Math.max(...powers)
        };
    });
    
    // RX OFDM Power data
    const rxOfdmPowerData = allChecks.map(c => {
        if (!c.rxofdm || c.rxofdm.length === 0) return { min: null, avg: null, max: null };
        const powers = c.rxofdm.map(ch => parseFloat(ch.plcpower)).filter(p => !isNaN(p) && isFinite(p));
        if (powers.length === 0) return { min: null, avg: null, max: null };
        return {
            min: Math.min(...powers),
            avg: powers.reduce((a, b) => a + b) / powers.length,
            max: Math.max(...powers)
        };
    });
    
    // RX SC-QAM SNR data
    const rxScqamSnrData = allChecks.map(c => {
        if (!c.rx || c.rx.length === 0) return { min: null, avg: null, max: null };
        const snrs = c.rx.map(ch => parseFloat(ch.snr)).filter(s => !isNaN(s) && isFinite(s));
        if (snrs.length === 0) return { min: null, avg: null, max: null };
        return {
            min: Math.min(...snrs),
            avg: snrs.reduce((a, b) => a + b) / snrs.length,
            max: Math.max(...snrs)
        };
    });
    
    // RX OFDM SNR data
    const rxOfdmSnrData = allChecks.map(c => {
        if (!c.rxofdm || c.rxofdm.length === 0) return { min: null, avg: null, max: null };
        const snrs = c.rxofdm.map(ch => parseFloat(ch.plcsnr)).filter(s => !isNaN(s) && isFinite(s));
        if (snrs.length === 0) return { min: null, avg: null, max: null };
        return {
            min: Math.min(...snrs),
            avg: snrs.reduce((a, b) => a + b) / snrs.length,
            max: Math.max(...snrs)
        };
    });
    
    // BER data (Bit Error Rate = uncorrectables / total codewords * 100)
    // Note: octets = unerrored codewords, so total = octets + correcteds + uncorrectds
    const rxScqamBerData = allChecks.map(c => {
        if (!c.rx || c.rx.length === 0) return { avg: null, max: null };
        const bers = c.rx.map(ch => {
            const unerrored = parseInt(ch.octets) || 0;
            const correcteds = parseInt(ch.correcteds) || 0;
            const uncorrectds = parseInt(ch.uncorrectds) || 0;
            const total = unerrored + correcteds + uncorrectds;
            if (total === 0) return 0;
            return (uncorrectds / total) * 100;
        }).filter(b => !isNaN(b) && isFinite(b));
        if (bers.length === 0) return { avg: null, max: null };
        return {
            avg: bers.reduce((a, b) => a + b) / bers.length,
            max: Math.max(...bers)
        };
    });
    
    const rxOfdmBerData = allChecks.map(c => {
        if (!c.rxofdm || c.rxofdm.length === 0) return { avg: null, max: null };
        const bers = c.rxofdm.map(ch => {
            const unerrored = parseInt(ch.octets) || 0;
            const correcteds = parseInt(ch.correcteds) || 0;
            const uncorrectds = parseInt(ch.uncorrectds) || 0;
            const total = unerrored + correcteds + uncorrectds;
            if (total === 0) return 0;
            return (uncorrectds / total) * 100;
        }).filter(b => !isNaN(b) && isFinite(b));
        if (bers.length === 0) return { avg: null, max: null };
        return {
            avg: bers.reduce((a, b) => a + b) / bers.length,
            max: Math.max(...bers)
        };
    });
    
    // Correctable codeword error rate data (correcteds / total codewords * 100)
    const rxScqamCorrectedData = allChecks.map(c => {
        if (!c.rx || c.rx.length === 0) return { avg: null, max: null };
        const rates = c.rx.map(ch => {
            const unerrored = parseInt(ch.octets) || 0;
            const correcteds = parseInt(ch.correcteds) || 0;
            const uncorrectds = parseInt(ch.uncorrectds) || 0;
            const total = unerrored + correcteds + uncorrectds;
            if (total === 0) return 0;
            return (correcteds / total) * 100;
        }).filter(r => !isNaN(r) && isFinite(r));
        if (rates.length === 0) return { avg: null, max: null };
        return {
            avg: rates.reduce((a, b) => a + b) / rates.length,
            max: Math.max(...rates)
        };
    });
    
    const rxOfdmCorrectedData = allChecks.map(c => {
        if (!c.rxofdm || c.rxofdm.length === 0) return { avg: null, max: null };
        const rates = c.rxofdm.map(ch => {
            const unerrored = parseInt(ch.octets) || 0;
            const correcteds = parseInt(ch.correcteds) || 0;
            const uncorrectds = parseInt(ch.uncorrectds) || 0;
            const total = unerrored + correcteds + uncorrectds;
            if (total === 0) return 0;
            return (correcteds / total) * 100;
        }).filter(r => !isNaN(r) && isFinite(r));
        if (rates.length === 0) return { avg: null, max: null };
        return {
            avg: rates.reduce((a, b) => a + b) / rates.length,
            max: Math.max(...rates)
        };
    });
    
    // TX SC-QAM Power data and bonded channels
    const txScqamData = allChecks.map(c => {
        if (!c.tx || c.tx.length === 0) return { min: null, avg: null, max: null, bonded: 0 };
        const powers = c.tx.map(ch => parseFloat(ch.power)).filter(p => !isNaN(p) && isFinite(p) && p !== 0);
        return {
            min: powers.length > 0 ? Math.min(...powers) : null,
            avg: powers.length > 0 ? powers.reduce((a, b) => a + b) / powers.length : null,
            max: powers.length > 0 ? Math.max(...powers) : null,
            bonded: powers.length
        };
    });
    
    // TX OFDMA data
    const txOfdmaData = allChecks.map(c => {
        if (!c.txofdm || c.txofdm.length === 0) return { bonded: 0, impaired: 0, avgPower: null };
        
        const operateStates = ['OPERATE', 'Locked'];
        const impairedStates = ['Not Locked', 'RNG1', 'RNG2', 'RNG3', 'Partial Service'];
        
        let bonded = 0;
        let impaired = 0;
        const powers = [];
        
        c.txofdm.forEach(ch => {
            const state = ch.state || '';
            if (operateStates.some(s => state.includes(s))) {
                bonded++;
            } else if (impairedStates.some(s => state.includes(s))) {
                impaired++;
            }
            
            const power = parseFloat(ch.power);
            if (!isNaN(power) && isFinite(power)) {
                powers.push(power);
            }
        });
        
        return {
            bonded: bonded,
            impaired: impaired,
            avgPower: powers.length > 0 ? powers.reduce((a, b) => a + b) / powers.length : null
        };
    });
    
    // Uptime data (convert seconds to days)
    const uptimeData = allChecks.map(c => {
        const uptime = c.sysinfo?.uptime;
        if (!uptime || isNaN(uptime)) return null;
        return uptime / 86400; // Convert seconds to days
    });
    
    // Render all charts with time-based x-axis
    renderSpeedChart(timestamps, uploadSpeeds, downloadSpeeds, uploadLimits, downloadLimits);
    renderLatencyChart(timestamps, googlePingAvg, cloudflarePingAvg,
                       speedtestLatency, speedtestMaxLatency, googleMaxLatency, cloudflareMaxLatency);
    renderPacketLossChart(timestamps, googlePingLoss, cloudflarePingLoss);
    renderUptimeChart(timestamps, uptimeData);
    renderRxPowerChart(timestamps, rxScqamPowerData, rxOfdmPowerData);
    renderRxSnrChart(timestamps, rxScqamSnrData, rxOfdmSnrData);
    renderBerChart(timestamps, rxScqamBerData, rxOfdmBerData, rxScqamCorrectedData, rxOfdmCorrectedData);
    renderTxChannelsChart(timestamps, txScqamData, txOfdmaData);
    renderTxPowerChart(timestamps, txScqamData, txOfdmaData);
            }

// Global variable to store pre-aggregated trend data
let trendData = [];

/**
 * Render trend charts using pre-aggregated data from /api/db/get_trend_data.
 * This is significantly faster than renderTrendChartsFromChecks() because:
 * 1. Data transfer is ~500 bytes per check instead of ~15-50KB
 * 2. No client-side aggregation needed (server pre-computes min/avg/max)
 */
function renderTrendChartsFromPreAggregated() {
    if (trendData.length < 1) {
        showStatus('No data available to display trends', 'error');
        return;
    }

    // Destroy all existing charts to prevent canvas reuse errors
    Object.keys(charts).forEach(key => {
        if (charts[key]) {
            charts[key].destroy();
            charts[key] = null;
        }
    });

    // Data is already pre-aggregated - just extract arrays directly
    const timestamps = trendData.map(c => c.check_time);

    // Speed data (already parsed to Mbps by server)
    const uploadSpeeds = trendData.map(c => c.upload_speed);
    const downloadSpeeds = trendData.map(c => c.download_speed);
    const uploadLimits = trendData.map(c => c.upload_limit);
    const downloadLimits = trendData.map(c => c.download_limit);

    // Ping data
    const googlePingAvg = trendData.map(c => c.ping_google_avg);
    const googlePingLoss = trendData.map(c => c.ping_google_loss);
    const cloudflarePingAvg = trendData.map(c => c.ping_cloudflare_avg);
    const cloudflarePingLoss = trendData.map(c => c.ping_cloudflare_loss);
    const speedtestLatency = trendData.map(c => c.speedtest_latency);
    const speedtestMaxLatency = trendData.map(c => c.speedtest_max_latency);
    const googleMaxLatency = trendData.map(c => c.ping_google_max);
    const cloudflareMaxLatency = trendData.map(c => c.ping_cloudflare_max);

    // Uptime data (already in days from server)
    const uptimeData = trendData.map(c => c.uptime_days);

    // RX data - already aggregated by server!
    // Map from server format (min_power/avg_power/max_power) to chart format (min/avg/max)
    const rxScqamPowerData = trendData.map(c => ({
        min: c.rx_scqam?.min_power ?? null,
        avg: c.rx_scqam?.avg_power ?? null,
        max: c.rx_scqam?.max_power ?? null
    }));
    const rxOfdmPowerData = trendData.map(c => ({
        min: c.rx_ofdm?.min_power ?? null,
        avg: c.rx_ofdm?.avg_power ?? null,
        max: c.rx_ofdm?.max_power ?? null
    }));
    const rxScqamSnrData = trendData.map(c => ({
        min: c.rx_scqam?.min_snr ?? null,
        avg: c.rx_scqam?.avg_snr ?? null,
        max: c.rx_scqam?.max_snr ?? null
    }));
    const rxOfdmSnrData = trendData.map(c => ({
        min: c.rx_ofdm?.min_snr ?? null,
        avg: c.rx_ofdm?.avg_snr ?? null,
        max: c.rx_ofdm?.max_snr ?? null
    }));

    // BER data - already calculated by server
    const rxScqamBerData = trendData.map(c => ({
        avg: c.rx_scqam?.avg_ber ?? null,
        max: c.rx_scqam?.max_ber ?? null
    }));
    const rxOfdmBerData = trendData.map(c => ({
        avg: c.rx_ofdm?.avg_ber ?? null,
        max: c.rx_ofdm?.max_ber ?? null
    }));
    const rxScqamCorrectedData = trendData.map(c => ({
        avg: c.rx_scqam?.avg_corrected_rate ?? null,
        max: c.rx_scqam?.max_corrected_rate ?? null
    }));
    const rxOfdmCorrectedData = trendData.map(c => ({
        avg: c.rx_ofdm?.avg_corrected_rate ?? null,
        max: c.rx_ofdm?.max_corrected_rate ?? null
    }));

    // TX data - already aggregated by server
    const txScqamData = trendData.map(c => ({
        min: c.tx_scqam?.min_power ?? null,
        avg: c.tx_scqam?.avg_power ?? null,
        max: c.tx_scqam?.max_power ?? null,
        bonded: c.tx_scqam?.bonded_count ?? 0
    }));
    const txOfdmaData = trendData.map(c => ({
        avgPower: c.tx_ofdma?.avg_power ?? null,
        bonded: c.tx_ofdma?.bonded_count ?? 0,
        impaired: c.tx_ofdma?.impaired_count ?? 0
    }));

    // Render all charts using existing render functions
    renderSpeedChart(timestamps, uploadSpeeds, downloadSpeeds, uploadLimits, downloadLimits);
    renderLatencyChart(timestamps, googlePingAvg, cloudflarePingAvg,
                       speedtestLatency, speedtestMaxLatency, googleMaxLatency, cloudflareMaxLatency);
    renderPacketLossChart(timestamps, googlePingLoss, cloudflarePingLoss);
    renderUptimeChart(timestamps, uptimeData);
    renderRxPowerChart(timestamps, rxScqamPowerData, rxOfdmPowerData);
    renderRxSnrChart(timestamps, rxScqamSnrData, rxOfdmSnrData);
    renderBerChart(timestamps, rxScqamBerData, rxOfdmBerData, rxScqamCorrectedData, rxOfdmCorrectedData);
    renderTxChannelsChart(timestamps, txScqamData, txOfdmaData);
    renderTxPowerChart(timestamps, txScqamData, txOfdmaData);
}

            function renderSpeedChart(timestamps, uploadData, downloadData, uploadLimits, downloadLimits) {
                const ctx = document.getElementById('speedChart');
                const colors = getChartColors();

                if (charts.speed) {
                    charts.speed.destroy();
                }

                // Convert to {x, y} format for time scale, filtering out null values
                // This allows lines to connect between valid points even when there are gaps
                const datasets = [{
                    label: 'Download Speed',
                    data: timestamps.map((t, i) => ({ x: t * 1000, y: downloadData[i] }))
                        .filter(point => point.y !== null && point.y !== undefined),
                    borderColor: '#667eea',
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    tension: 0.4,
                    fill: true,
                    spanGaps: true  // Connect line across gaps in data
                }, {
                    label: 'Upload Speed',
                    data: timestamps.map((t, i) => ({ x: t * 1000, y: uploadData[i] }))
                        .filter(point => point.y !== null && point.y !== undefined),
                    borderColor: '#764ba2',
                    backgroundColor: 'rgba(118, 75, 162, 0.1)',
                    tension: 0.4,
                    fill: true,
                    spanGaps: true  // Connect line across gaps in data
                }];
                
                // Add download limit line if available
                if (downloadLimits && downloadLimits.some(l => l !== null)) {
                    datasets.push({
                        label: 'Download Limit',
                        data: timestamps.map((t, i) => ({ x: t * 1000, y: downloadLimits[i] })),
                        borderColor: 'rgba(102, 126, 234, 0.5)',
                        borderDash: [5, 5],
                        borderWidth: 2,
                        pointRadius: 0,
                        fill: false,
                        tension: 0
                    });
                }
                
                // Add upload limit line if available
                if (uploadLimits && uploadLimits.some(l => l !== null)) {
                    datasets.push({
                        label: 'Upload Limit',
                        data: timestamps.map((t, i) => ({ x: t * 1000, y: uploadLimits[i] })),
                        borderColor: 'rgba(118, 75, 162, 0.5)',
                        borderDash: [5, 5],
                        borderWidth: 2,
                        pointRadius: 0,
                        fill: false,
                        tension: 0
                    });
                }
                
                charts.speed = new Chart(ctx, {
                    type: 'line',
                    data: {
                        datasets: datasets
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        parsing: false,
                        normalized: true,
                        plugins: {
                            decimation: {
                                enabled: true,
                                algorithm: 'lttb',
                                samples: 500,
                                threshold: 1000
                            },
                            legend: {
                                position: 'top',
                                labels: { color: colors.text }
                            },
                            tooltip: {
                                mode: 'index',
                                intersect: false
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                time: {
                                    unit: 'hour',
                                    displayFormats: {
                                        hour: 'MMM d, HH:mm'
                                    },
                                    tooltipFormat: 'MMM d, yyyy HH:mm:ss'
                                },
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Time',
                                    color: colors.text
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true,
                                    color: colors.text
                                }
                            },
                            y: {
                                beginAtZero: true,
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Speed (Mbps)',
                                    color: colors.text
                                },
                                ticks: { color: colors.text }
                            }
                        },
                        interaction: {
                            mode: 'nearest',
                            axis: 'x',
                            intersect: false
                        }
                    }
                });
            }

            function renderLatencyChart(timestamps, googleAvg, cloudflareAvg,
                                       speedtestLatency, speedtestMaxLatency, googleMaxLatency, cloudflareMaxLatency) {
                const ctx = document.getElementById('latencyChart');
                const colors = getChartColors();

                if (charts.latency) {
                    charts.latency.destroy();
                }

                charts.latency = new Chart(ctx, {
                    type: 'line',
                    data: {
                        datasets: [{
                            label: 'Google Ping (ms)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: googleAvg[i] })),
                            borderColor: '#4285f4',
                            backgroundColor: 'rgba(66, 133, 244, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'Cloudflare Ping (ms)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: cloudflareAvg[i] })),
                            borderColor: '#f6821f',
                            backgroundColor: 'rgba(246, 130, 31, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'Speed Test Avg Latency (ms)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: speedtestLatency[i] })),
                            borderColor: '#34a853',
                            backgroundColor: 'rgba(52, 168, 83, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'Speed Test Max Latency (ms)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: speedtestMaxLatency[i] })),
                            borderColor: '#9c27b0',
                            backgroundColor: 'rgba(156, 39, 176, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true,
                            hidden: true
                        }, {
                            label: 'Google Max Latency (ms)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: googleMaxLatency[i] })),
                            borderColor: '#7baaf7',
                            backgroundColor: 'rgba(123, 170, 247, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            borderDash: [2, 2],
                            fill: false,
                            hidden: true
                        }, {
                            label: 'Cloudflare Max Latency (ms)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: cloudflareMaxLatency[i] })),
                            borderColor: '#fab57f',
                            backgroundColor: 'rgba(250, 181, 127, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            borderDash: [2, 2],
                            fill: false,
                            hidden: true
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        parsing: false,
                        normalized: true,
                        plugins: {
                            decimation: {
                                enabled: true,
                                algorithm: 'lttb',
                                samples: 500,
                                threshold: 1000
                            },
                            legend: {
                                position: 'top',
                                labels: { color: colors.text }
                            },
                            tooltip: {
                                mode: 'index',
                                intersect: false,
                                callbacks: {
                                    label: function(context) {
                                        let label = context.dataset.label || '';
                                        if (label) {
                                            label += ': ';
                                        }
                                        if (context.parsed.y !== null) {
                                            label += context.parsed.y.toFixed(2) + ' ms';
                                        }
                                        return label;
                                    }
                                }
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                time: {
                                    unit: 'hour',
                                    displayFormats: {
                                        hour: 'MMM d, HH:mm'
                                    },
                                    tooltipFormat: 'MMM d, yyyy HH:mm:ss'
                                },
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Time',
                                    color: colors.text
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true,
                                    color: colors.text
                                }
                            },
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Latency (ms)',
                                    color: colors.text
                                },
                                ticks: { color: colors.text },
                                beginAtZero: true,
                                suggestedMax: 50
                            }
                        },
                        interaction: {
                            mode: 'nearest',
                            axis: 'x',
                            intersect: false
                        }
                    }
                });
            }

            function renderPacketLossChart(timestamps, googleLoss, cloudflareLoss) {
                const ctx = document.getElementById('packetLossChart');
                const colors = getChartColors();

                if (charts.packetLoss) {
                    charts.packetLoss.destroy();
                }

                charts.packetLoss = new Chart(ctx, {
                    type: 'line',
                    data: {
                        datasets: [{
                            label: 'Google Packet Loss (%)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: googleLoss[i] })),
                            borderColor: '#ea4335',
                            backgroundColor: 'rgba(234, 67, 53, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            pointRadius: 3,
                            fill: true
                        }, {
                            label: 'Cloudflare Packet Loss (%)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: cloudflareLoss[i] })),
                            borderColor: '#fbbc05',
                            backgroundColor: 'rgba(251, 188, 5, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            pointRadius: 3,
                            fill: true
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        parsing: false,
                        normalized: true,
                        plugins: {
                            decimation: {
                                enabled: true,
                                algorithm: 'lttb',
                                samples: 500,
                                threshold: 1000
                            },
                            legend: {
                                position: 'top',
                                labels: { color: colors.text }
                            },
                            tooltip: {
                                mode: 'index',
                                intersect: false,
                                callbacks: {
                                    label: function(context) {
                                        let label = context.dataset.label || '';
                                        if (label) {
                                            label += ': ';
                                        }
                                        if (context.parsed.y !== null) {
                                            label += context.parsed.y.toFixed(1) + '%';
                                        }
                                        return label;
                                    }
                                }
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                time: {
                                    unit: 'hour',
                                    displayFormats: {
                                        hour: 'MMM d, HH:mm'
                                    },
                                    tooltipFormat: 'MMM d, yyyy HH:mm:ss'
                                },
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Time',
                                    color: colors.text
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true,
                                    color: colors.text
                                }
                            },
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Packet Loss (%)',
                                    color: colors.text
                                },
                                ticks: { color: colors.text },
                                beginAtZero: true,
                                grace: '10%'  // Auto-scale with padding above data
                            }
                        },
                        interaction: {
                            mode: 'nearest',
                            axis: 'x',
                            intersect: false
                        }
                    }
                });
            }

            function renderUptimeChart(timestamps, uptimeData) {
                const ctx = document.getElementById('uptimeChart');
                const colors = getChartColors();

                if (charts.uptime) {
                    charts.uptime.destroy();
                }
                
                charts.uptime = new Chart(ctx, {
                    type: 'line',
                    data: {
                        datasets: [{
                            label: 'Uptime (days)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: uptimeData[i] })),
                            borderColor: '#38b2ac',
                            backgroundColor: 'rgba(56, 178, 172, 0.1)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true,
                            pointRadius: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        parsing: false,
                        normalized: true,
                        plugins: {
                            decimation: {
                                enabled: true,
                                algorithm: 'lttb',
                                samples: 500,
                                threshold: 1000
                            },
                            legend: {
                                position: 'top',
                                labels: { color: colors.text }
                            },
                            tooltip: {
                                mode: 'index',
                                intersect: false,
                                callbacks: {
                                    label: function(context) {
                                        let label = context.dataset.label || '';
                                        if (label) {
                                            label += ': ';
                                        }
                                        if (context.parsed.y !== null) {
                                            const days = Math.floor(context.parsed.y);
                                            const hours = Math.floor((context.parsed.y - days) * 24);
                                            label += days + 'd ' + hours + 'h';
                                        }
                                        return label;
                                    }
                                }
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                time: {
                                    unit: 'hour',
                                    displayFormats: {
                                        hour: 'MMM d, HH:mm'
                                    },
                                    tooltipFormat: 'MMM d, yyyy HH:mm:ss'
                                },
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Time',
                                    color: colors.text
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true,
                                    color: colors.text
                                }
                            },
                            y: {
                                beginAtZero: true,
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Uptime (days)',
                                    color: colors.text
                                },
                                ticks: {
                                    color: colors.text,
                                    callback: function(value) {
                                        return value.toFixed(1) + 'd';
                                    }
                                }
                            }
                        },
                        interaction: {
                            mode: 'nearest',
                            axis: 'x',
                            intersect: false
                        }
                    }
                });
            }

            function renderRxPowerChart(timestamps, rxScqamData, rxOfdmData) {
                const ctx = document.getElementById('rxPowerChart');
                const colors = getChartColors();

                if (charts.rxPower) {
                    charts.rxPower.destroy();
                }
                
                charts.rxPower = new Chart(ctx, {
                    type: 'line',
                    data: {
                        datasets: [{
                            label: 'Min RX SC-QAM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxScqamData[i].min })),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2,
                            spanGaps: true
                        }, {
                            label: 'Avg RX SC-QAM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxScqamData[i].avg })),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true
                        }, {
                            label: 'Max RX SC-QAM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxScqamData[i].max })),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Min RX OFDM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxOfdmData[i].min })),
                            borderColor: '#48bb78',
                            backgroundColor: 'rgba(72, 187, 120, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX OFDM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxOfdmData[i].avg })),
                            borderColor: '#48bb78',
                            backgroundColor: 'rgba(72, 187, 120, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true
                        }, {
                            label: 'Max RX OFDM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxOfdmData[i].max })),
                            borderColor: '#48bb78',
                            backgroundColor: 'rgba(72, 187, 120, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        parsing: false,
                        normalized: true,
                        plugins: {
                            decimation: {
                                enabled: true,
                                algorithm: 'lttb',
                                samples: 500,
                                threshold: 1000
                            },
                            legend: {
                                position: 'top',
                                labels: { color: colors.text }
                            },
                            tooltip: {
                                mode: 'index',
                                intersect: false
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                time: {
                                    unit: 'hour',
                                    displayFormats: {
                                        hour: 'MMM d, HH:mm'
                                    },
                                    tooltipFormat: 'MMM d, yyyy HH:mm:ss'
                                },
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Time',
                                    color: colors.text
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true,
                                    color: colors.text
                                }
                            },
                            y: {
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Power (dBmV)',
                                    color: colors.text
                                },
                                ticks: { color: colors.text },
                                // Auto-scale to data range for better visibility
                                grace: '5%'  // Add 5% padding above/below data range
                            }
                        },
                        interaction: {
                            mode: 'nearest',
                            axis: 'x',
                            intersect: false
                        }
                    }
                });
            }

            function renderRxSnrChart(timestamps, rxScqamData, rxOfdmData) {
                const ctx = document.getElementById('rxSnrChart');
                const colors = getChartColors();

                if (charts.rxSnr) {
                    charts.rxSnr.destroy();
                }
                
                charts.rxSnr = new Chart(ctx, {
                    type: 'line',
                    data: {
                        datasets: [{
                            label: 'Min RX SC-QAM SNR',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxScqamData[i].min })),
                            borderColor: '#ed8936',
                            backgroundColor: 'rgba(237, 137, 54, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX SC-QAM SNR',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxScqamData[i].avg })),
                            borderColor: '#ed8936',
                            backgroundColor: 'rgba(237, 137, 54, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true
                        }, {
                            label: 'Max RX SC-QAM SNR',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxScqamData[i].max })),
                            borderColor: '#ed8936',
                            backgroundColor: 'rgba(237, 137, 54, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Min RX OFDM SNR',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxOfdmData[i].min })),
                            borderColor: '#9f7aea',
                            backgroundColor: 'rgba(159, 122, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX OFDM SNR',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxOfdmData[i].avg })),
                            borderColor: '#9f7aea',
                            backgroundColor: 'rgba(159, 122, 234, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true
                        }, {
                            label: 'Max RX OFDM SNR',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxOfdmData[i].max })),
                            borderColor: '#9f7aea',
                            backgroundColor: 'rgba(159, 122, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        parsing: false,
                        normalized: true,
                        plugins: {
                            decimation: {
                                enabled: true,
                                algorithm: 'lttb',
                                samples: 500,
                                threshold: 1000
                            },
                            legend: {
                                position: 'top',
                                labels: { color: colors.text }
                            },
                            tooltip: {
                                mode: 'index',
                                intersect: false
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                time: {
                                    unit: 'hour',
                                    displayFormats: {
                                        hour: 'MMM d, HH:mm'
                                    },
                                    tooltipFormat: 'MMM d, yyyy HH:mm:ss'
                                },
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Time',
                                    color: colors.text
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true,
                                    color: colors.text
                                }
                            },
                            y: {
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'SNR (dB)',
                                    color: colors.text
                                },
                                ticks: { color: colors.text },
                                // Auto-scale to data range for better visibility
                                grace: '5%'  // Add 5% padding above/below data range
                            }
                        },
                        interaction: {
                            mode: 'nearest',
                            axis: 'x',
                            intersect: false
                        }
                    }
                });
            }

            function renderBerChart(timestamps, rxScqamBerData, rxOfdmBerData, rxScqamCorrectedData, rxOfdmCorrectedData) {
                const ctx = document.getElementById('berChart');
                const colors = getChartColors();

                if (charts.ber) {
                    charts.ber.destroy();
                }
                
                charts.ber = new Chart(ctx, {
                    type: 'line',
                    data: {
                        datasets: [{
                            label: 'Avg RX SC-QAM BER (Uncorrectable)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxScqamBerData[i].avg })),
                            borderColor: '#f56565',
                            backgroundColor: 'rgba(245, 101, 101, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'Max RX SC-QAM BER (Uncorrectable)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxScqamBerData[i].max })),
                            borderColor: '#c53030',
                            backgroundColor: 'rgba(197, 48, 48, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX OFDM BER (Uncorrectable)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxOfdmBerData[i].avg })),
                            borderColor: '#ed8936',
                            backgroundColor: 'rgba(237, 137, 54, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'Max RX OFDM BER (Uncorrectable)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxOfdmBerData[i].max })),
                            borderColor: '#c05621',
                            backgroundColor: 'rgba(192, 86, 33, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX SC-QAM Corrected',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxScqamCorrectedData[i].avg })),
                            borderColor: '#48bb78',
                            backgroundColor: 'rgba(72, 187, 120, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'Max RX SC-QAM Corrected',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxScqamCorrectedData[i].max })),
                            borderColor: '#38a169',
                            backgroundColor: 'rgba(56, 161, 105, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX OFDM Corrected',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxOfdmCorrectedData[i].avg })),
                            borderColor: '#4299e1',
                            backgroundColor: 'rgba(66, 153, 225, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true,
                            hidden: true
                        }, {
                            label: 'Max RX OFDM Corrected',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: rxOfdmCorrectedData[i].max })),
                            borderColor: '#3182ce',
                            backgroundColor: 'rgba(49, 130, 206, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2,
                            hidden: true
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        parsing: false,
                        normalized: true,
                        plugins: {
                            decimation: {
                                enabled: true,
                                algorithm: 'lttb',
                                samples: 500,
                                threshold: 1000
                            },
                            legend: {
                                position: 'top',
                                labels: { color: colors.text }
                            },
                            tooltip: {
                                mode: 'index',
                                intersect: false,
                                callbacks: {
                                    label: function(context) {
                                        let label = context.dataset.label || '';
                                        if (label) {
                                            label += ': ';
                                        }
                                        if (context.parsed.y !== null) {
                                            // Use fixed decimal notation for values
                                            const value = context.parsed.y;
                                            if (value >= 0.01) {
                                                label += value.toFixed(4) + '%';
                                            } else if (value >= 0.0001) {
                                                label += value.toFixed(6) + '%';
                                            } else {
                                                label += value.toFixed(8) + '%';
                                            }
                                        }
                                        return label;
                                    }
                                }
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                time: {
                                    unit: 'hour',
                                    displayFormats: {
                                        hour: 'MMM d, HH:mm'
                                    },
                                    tooltipFormat: 'MMM d, yyyy HH:mm:ss'
                                },
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Time',
                                    color: colors.text
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true,
                                    color: colors.text
                                }
                            },
                            y: {
                                type: 'logarithmic',
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Error Rate (%)',
                                    color: colors.text
                                },
                                ticks: {
                                    color: colors.text,
                                    callback: function(value) {
                                        // Use fixed decimal notation instead of scientific
                                        if (value >= 0.01) {
                                            return value.toFixed(4) + '%';
                                        } else if (value >= 0.0001) {
                                            return value.toFixed(6) + '%';
                                        } else {
                                            return value.toFixed(8) + '%';
                                        }
                                    }
                                }
                            }
                        },
                        interaction: {
                            mode: 'nearest',
                            axis: 'x',
                            intersect: false
                        }
                    }
                });
            }

            function renderTxChannelsChart(timestamps, txScqamData, txOfdmaData) {
                const ctx = document.getElementById('txChannelsChart');
                const colors = getChartColors();

                if (charts.txChannels) {
                    charts.txChannels.destroy();
                }

                charts.txChannels = new Chart(ctx, {
                    type: 'line',
                    data: {
                        datasets: [{
                            label: 'TX SC-QAM Bonded Channels',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txScqamData[i].bonded })),
                            borderColor: '#9f7aea',
                            backgroundColor: 'rgba(159, 122, 234, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'TX OFDMA Bonded Channels',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txOfdmaData[i].bonded })),
                            borderColor: '#38b2ac',
                            backgroundColor: 'rgba(56, 178, 172, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'TX OFDMA Impaired Channels',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txOfdmaData[i].impaired })),
                            borderColor: '#f56565',
                            backgroundColor: 'rgba(245, 101, 101, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        parsing: false,
                        normalized: true,
                        plugins: {
                            decimation: {
                                enabled: true,
                                algorithm: 'lttb',
                                samples: 500,
                                threshold: 1000
                            },
                            legend: {
                                position: 'top',
                                labels: { color: colors.text }
                            },
                            tooltip: {
                                mode: 'index',
                                intersect: false
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                time: {
                                    unit: 'hour',
                                    displayFormats: {
                                        hour: 'MMM d, HH:mm'
                                    },
                                    tooltipFormat: 'MMM d, yyyy HH:mm:ss'
                                },
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Time',
                                    color: colors.text
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true,
                                    color: colors.text
                                }
                            },
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Channel Count',
                                    color: colors.text
                                },
                                beginAtZero: true,
                                ticks: {
                                    stepSize: 1,
                                    color: colors.text
                                }
                            }
                        },
                        interaction: {
                            mode: 'nearest',
                            axis: 'x',
                            intersect: false
                        }
                    }
                });
            }

            function renderTxPowerChart(timestamps, txScqamData, txOfdmaData) {
                const ctx = document.getElementById('txPowerChart');
                const colors = getChartColors();

                if (charts.txPower) {
                    charts.txPower.destroy();
                }

                charts.txPower = new Chart(ctx, {
                    type: 'line',
                    data: {
                        datasets: [{
                            label: 'Min TX SC-QAM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txScqamData[i].min })),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg TX SC-QAM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txScqamData[i].avg })),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true
                        }, {
                            label: 'Max TX SC-QAM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txScqamData[i].max })),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg TX OFDMA Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txOfdmaData[i].avgPower })),
                            borderColor: '#48bb78',
                            backgroundColor: 'rgba(72, 187, 120, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        parsing: false,
                        normalized: true,
                        plugins: {
                            decimation: {
                                enabled: true,
                                algorithm: 'lttb',
                                samples: 500,
                                threshold: 1000
                            },
                            legend: {
                                position: 'top',
                                labels: { color: colors.text }
                            },
                            tooltip: {
                                mode: 'index',
                                intersect: false
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                time: {
                                    unit: 'hour',
                                    displayFormats: {
                                        hour: 'MMM d, HH:mm'
                                    },
                                    tooltipFormat: 'MMM d, yyyy HH:mm:ss'
                                },
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Time',
                                    color: colors.text
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true,
                                    color: colors.text
                                }
                            },
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                grid: { color: colors.grid },
                                title: {
                                    display: true,
                                    text: 'Power (dBmV)',
                                    color: colors.text
                                },
                                ticks: { color: colors.text },
                                grace: '5%'
                            }
                        },
                        interaction: {
                            mode: 'nearest',
                            axis: 'x',
                            intersect: false
                        }
                    }
                });
            }

            // Update chart colors when theme changes
            function updateChartColors() {
                const colors = getChartColors();

                Object.values(charts).forEach(chart => {
                    if (chart && chart.options) {
                        // Update scale colors (grid, ticks, titles)
                        if (chart.options.scales) {
                            Object.values(chart.options.scales).forEach(scale => {
                                if (scale.grid) {
                                    scale.grid.color = colors.grid;
                                }
                                if (scale.ticks) {
                                    scale.ticks.color = colors.text;
                                }
                                if (scale.title) {
                                    scale.title.color = colors.text;
                                }
                            });
                        }

                        // Update legend text color
                        if (chart.options.plugins?.legend?.labels) {
                            chart.options.plugins.legend.labels.color = colors.text;
                        } else if (chart.options.plugins?.legend) {
                            chart.options.plugins.legend.labels = { color: colors.text };
                        }

                        chart.update();
                    }
                });
            }

// Helper function to create traceroute link element
function createTracerouteLink(tracerouteData) {
    const link = document.createElement('a');
    link.textContent = 'Traceroute';
    link.href = '#';
    link.style.cssText = 'color: white; text-decoration: underline; cursor: pointer;';
    link.addEventListener('click', (e) => {
        e.preventDefault();
        showTracerouteModal(tracerouteData);
    });
    return link;
}

// Traceroute modal functions
function showTracerouteModal(tracerouteData) {
    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'traceroute-modal-overlay';

    // Create content container
    const content = document.createElement('div');
    content.className = 'traceroute-modal-content';

    // Header
    const header = document.createElement('h3');
    header.textContent = 'Traceroute to ' + tracerouteData.target;
    content.appendChild(header);

    // Traceroute output
    const pre = document.createElement('pre');
    pre.className = 'traceroute-output';
    pre.textContent = formatTracerouteOutput(tracerouteData);
    content.appendChild(pre);

    // Buttons container
    const buttons = document.createElement('div');
    buttons.className = 'traceroute-modal-buttons';

    // Copy button with error handling for clipboard API
    const copyBtn = document.createElement('button');
    copyBtn.textContent = 'Copy to Clipboard';
    copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(pre.textContent).then(() => {
            copyBtn.textContent = 'Copied!';
            setTimeout(() => { copyBtn.textContent = 'Copy to Clipboard'; }, 2000);
        }).catch((err) => {
            console.warn('Clipboard access denied:', err);
            copyBtn.textContent = 'Copy Failed';
            setTimeout(() => { copyBtn.textContent = 'Copy to Clipboard'; }, 2000);
        });
    });
    buttons.appendChild(copyBtn);

    // Escape key handler - defined first so closeModal can reference it
    let handleEscape;

    // Close modal and cleanup function
    const closeModal = () => {
        document.removeEventListener('keydown', handleEscape);
        if (overlay.parentNode) {
            document.body.removeChild(overlay);
        }
    };

    // Now assign the actual function
    handleEscape = (e) => {
        if (e.key === 'Escape') {
            closeModal();
        }
    };

    // Close button
    const closeBtn = document.createElement('button');
    closeBtn.textContent = 'Close';
    closeBtn.addEventListener('click', closeModal);
    buttons.appendChild(closeBtn);

    content.appendChild(buttons);
    overlay.appendChild(content);

    // Close on overlay click (outside the modal)
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            closeModal();
        }
    });

    // Register escape key handler
    document.addEventListener('keydown', handleEscape);

    document.body.appendChild(overlay);
}

function formatTracerouteOutput(tracerouteData) {
    // Use raw output if available (preserves original formatting)
    if (tracerouteData.raw_output) {
        return tracerouteData.raw_output;
    }

    // Format hops array into readable output
    if (!tracerouteData.hops || tracerouteData.hops.length === 0) {
        return 'No hop data available';
    }

    return tracerouteData.hops.map(hop => {
        if (hop.timeout) {
            return hop.hop.toString().padStart(2) + '  * * *';
        }
        // Show hostname (IP) format when both are available and different
        let hostDisplay;
        if (hop.host && hop.ip && hop.host !== hop.ip) {
            hostDisplay = hop.host + ' (' + hop.ip + ')';
        } else {
            hostDisplay = hop.host || hop.ip || '*';
        }
        const rtts = [hop.rtt1, hop.rtt2, hop.rtt3].filter(r => r).join('  ');
        return hop.hop.toString().padStart(2) + '  ' + hostDisplay + '  ' + rtts;
    }).join('\n');
}
