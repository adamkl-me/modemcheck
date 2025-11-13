console.log("DEBUG: db-viewer.js file loaded - DATABASE MODE");

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
const API_BASE = '/cgi-bin/db-api.py';

// Check authentication before initializing
async function checkAuth() {
    console.log("DEBUG: checkAuth called");
    console.log("DEBUG: Current URL:", window.location.href);

    try {
        console.log("DEBUG: Fetching auth status from /cgi-bin/auth.py");
        const response = await fetch('/cgi-bin/auth.py', {
            credentials: 'same-origin'
        });
        console.log("DEBUG: Auth response status:", response.status);

        if (!response.ok) {
            const errorText = await response.text();
            console.error("DEBUG: Auth check failed with status", response.status, errorText);
            window.location.href = '/login.html?return=' + encodeURIComponent(window.location.pathname);
            return false;
        }

        const data = await response.json();
        console.log("DEBUG: Auth data:", data);

        if (!data.authenticated) {
            console.log("DEBUG: User not authenticated, redirecting to login");
            window.location.href = '/login.html?return=' + encodeURIComponent(window.location.pathname);
            return false;
        }

        console.log("DEBUG: User authenticated, role:", data.role);

        // Show the page content now that auth is verified
        document.querySelector('.container').classList.add('authenticated');

        // Check if password change is required
        if (data.must_change_password || sessionStorage.getItem('must_change_password') === 'true') {
            sessionStorage.removeItem('must_change_password');
            showPasswordChangeDialog();
        }

        return true;
    } catch (error) {
        console.error('DEBUG: Auth check exception:', error);
        console.error('DEBUG: Error details:', error.message, error.stack);
        window.location.href = '/login.html?return=' + encodeURIComponent(window.location.pathname);
        return false;
    }
}

// Show password change dialog
function showPasswordChangeDialog() {
    const dialog = document.createElement('div');
    dialog.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.8); display: flex; align-items: center; justify-content: center; z-index: 10000;';
    dialog.innerHTML = `
        <div style="background: white; padding: 30px; border-radius: 12px; max-width: 400px; width: 90%;">
            <h2 style="margin: 0 0 10px 0; color: #667eea;">Change Password Required</h2>
            <p style="margin: 0 0 20px 0; color: #666;">You must change your password before continuing.</p>
            <div id="pwd-error" style="display: none; background: #fee; color: #c33; padding: 10px; border-radius: 6px; margin-bottom: 15px; font-size: 14px;"></div>
            <div style="margin-bottom: 15px;">
                <label style="display: block; margin-bottom: 5px; font-weight: 600; color: #333;">New Password (min 6 characters)</label>
                <input type="password" id="new-password" style="width: 100%; padding: 10px; border: 2px solid #e0e0e0; border-radius: 6px; font-size: 14px;" />
            </div>
            <div style="margin-bottom: 20px;">
                <label style="display: block; margin-bottom: 5px; font-weight: 600; color: #333;">Confirm Password</label>
                <input type="password" id="confirm-password" style="width: 100%; padding: 10px; border: 2px solid #e0e0e0; border-radius: 6px; font-size: 14px;" />
            </div>
            <button id="change-pwd-btn" style="width: 100%; padding: 12px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer;">Change Password</button>
        </div>
    `;
    document.body.appendChild(dialog);
    
    document.getElementById('change-pwd-btn').addEventListener('click', async () => {
        const newPassword = document.getElementById('new-password').value;
        const confirmPassword = document.getElementById('confirm-password').value;
        const errorDiv = document.getElementById('pwd-error');
        
        errorDiv.style.display = 'none';
        
        if (!newPassword || newPassword.length < 6) {
            errorDiv.textContent = 'Password must be at least 6 characters';
            errorDiv.style.display = 'block';
            return;
        }
        
        if (newPassword !== confirmPassword) {
            errorDiv.textContent = 'Passwords do not match';
            errorDiv.style.display = 'block';
            return;
        }
        
        try {
            const formData = new FormData();
            formData.append('action', 'change_own_password');
            formData.append('new_password', newPassword);
            
            const response = await fetch('/cgi-bin/auth.py', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (data.success) {
                document.body.removeChild(dialog);
                alert('Password changed successfully!');
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
        const formData = new FormData();
        formData.append('action', 'logout');
        
        await fetch('/cgi-bin/auth.py', {
            method: 'POST',
            body: formData,
            credentials: 'same-origin'
        });
        
        window.location.href = '/login.html?return=' + encodeURIComponent(window.location.pathname);
    } catch (error) {
        console.error('Logout failed:', error);
        window.location.href = '/login.html?return=' + encodeURIComponent(window.location.pathname);
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', async function() {
    console.log("DEBUG: DOMContentLoaded fired");

    // Check authentication first
    const isAuthenticated = await checkAuth();
    if (!isAuthenticated) return;

    // Setup logout button
    document.getElementById('logoutBtn').addEventListener('click', logout);

    // Don't set default dates - let user choose or load all data
    
    loadModemList();
});

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
    console.log("DEBUG: loadModemList called");
    console.log("DEBUG: API_BASE is:", API_BASE);
    console.log("DEBUG: Current URL:", window.location.href);

    try {
        console.log("DEBUG: About to fetch modems from API");
        const response = await fetch(`${API_BASE}?action=list_modems`, {
            credentials: 'same-origin'
        });
        console.log("DEBUG: Fetch completed, status:", response.status);
        console.log("DEBUG: Response headers:", response.headers);

        if (!response.ok) {
            const errorText = await response.text();
            console.error("DEBUG: API error response:", errorText);
            throw new Error(`API returned status ${response.status}: ${errorText}`);
        }

        const data = await response.json();
        console.log("DEBUG: JSON parsed, modems:", data.modems);

        if (!data.modems || data.modems.length === 0) {
            console.warn("DEBUG: No modems found in response");
            showStatus('No modems found. Upload some data first.', 'error');
            return;
        }

        const dropdown = document.getElementById('modemDropdown');
        const searchInput = document.getElementById('modemSearchInput');
        const hiddenSelect = document.getElementById('modemSelect');
        
        console.log("DEBUG: Dropdown element found:", dropdown);
        dropdown.innerHTML = '';
        console.log("DEBUG: Dropdown cleared");

        // Store modems for filtering
        window.allModems = data.modems;

        data.modems.forEach(modem => {
            const option = document.createElement('div');
            option.className = 'searchable-option';
            option.dataset.value = modem.id;
            option.textContent = `${modem.type} - ${modem.mac}`;
            option.addEventListener('click', () => selectModem(modem.id, `${modem.type} - ${modem.mac}`));
            dropdown.appendChild(option);
        });

        console.log("DEBUG: Successfully loaded", data.modems.length, "modems");
        
        // Setup searchable dropdown event listeners
        setupSearchableDropdown();
    } catch (error) {
        console.error('DEBUG: Error loading modems:', error);
        console.error('DEBUG: Error details:', error.message, error.stack);
        showStatus(`Error loading modem list: ${error.message}`, 'error');
    }
}

// Setup searchable dropdown functionality
function setupSearchableDropdown() {
    const searchInput = document.getElementById('modemSearchInput');
    const dropdown = document.getElementById('modemDropdown');
    
    // Show dropdown when clicking on input
    searchInput.addEventListener('click', () => {
        dropdown.classList.add('show');
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
    });
    
    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.remove('show');
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
    
    searchInput.value = modemText;
    hiddenSelect.value = modemId;
    dropdown.classList.remove('show');
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
    statusDiv.style.color = type === 'error' ? '#f56565' : type === 'success' ? '#48bb78' : '#555';
}

// Load data for selected modem and date range
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
    
    try {
        // Use new get_all_checks endpoint for single request with all data
        let url = `${API_BASE}?action=get_all_checks&modem_id=${encodeURIComponent(modemId)}`;
        if (startDate) url += `&start_date=${startDate}`;
        if (endDate) url += `&end_date=${endDate}`;
        
        showStatus('Loading data...', 'info');
        
        const response = await fetch(url, {
            credentials: 'same-origin'
        });
        console.log("DEBUG: Fetch completed, status:", response.status);
        const data = await response.json();
        console.log("DEBUG: JSON parsed, success:", data.success, "checks:", data.checks?.length);
        
        if (!data.success || !data.checks || data.checks.length === 0) {
            showStatus('No data found for the selected criteria', 'error');
            document.getElementById('loadBtn').disabled = false;
            return;
        }
        
        showStatus(`Loaded ${data.checks.length} check(s)`, 'success');
        
        // All data retrieved in single request
        allChecks = data.checks;
        
        if (allChecks.length === 0) {
            showStatus('Failed to load data', 'error');
            document.getElementById('loadBtn').disabled = false;
            return;
        }
        
        // Sort by check time (numeric comparison for int64 timestamps)
        allChecks.sort((a, b) => {
            const timeA = a.sysinfo?.checktime || 0;
            const timeB = b.sysinfo?.checktime || 0;
            return timeA - timeB;
        });
        
        currentCheckIndex = allChecks.length - 1; // Start with most recent
        updateTimelineNav();
        
        // Hide welcome message once data is loaded
        const welcomeMsg = document.getElementById('welcomeMessage');
        if (welcomeMsg) {
            welcomeMsg.style.display = 'none';
        }
        
        if (allChecks.length > 1) {
            showTrendsView();
        } else {
            showSingleView();
        }
        
        displayCurrentCheck();
        showStatus(`Loaded ${allChecks.length} check(s) successfully`, 'success');
        
    } catch (error) {
        console.error('Error loading data:', error);
        showStatus('Error loading data: ' + error.message, 'error');
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
    
    renderTrendChartsFromChecks();
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
    currentCheckIndex = parseInt(index);
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
    const hasSpeedTestData = data.iperf3test_dl && data.iperf3test_dl > 0;

    let speedTestStatus = '';
    if (speedTestEnabled === true || speedTestEnabled === 1) {
        if (hasSpeedTestData) {
            speedTestStatus = 'Enabled';
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

    let googleDetailsText = googleParts.join(' | ');
    if (pingGoogleLoss && pingGoogleLoss !== 'N/A') {
        if (googleDetailsText) {
            googleDetailsText += '\nLoss: ' + pingGoogleLoss;
        } else {
            googleDetailsText = 'Loss: ' + pingGoogleLoss;
        }
    }
    document.getElementById('ping_google_details').textContent = googleDetailsText;

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

    let cloudflareDetailsText = cloudflareParts.join(' | ');
    if (pingCloudflareLoss && pingCloudflareLoss !== 'N/A') {
        if (cloudflareDetailsText) {
            cloudflareDetailsText += '\nLoss: ' + pingCloudflareLoss;
        } else {
            cloudflareDetailsText = 'Loss: ' + pingCloudflareLoss;
        }
    }
    document.getElementById('ping_cloudflare_details').textContent = cloudflareDetailsText;
    
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
    if (allChecks.length < 2) return;
    
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
    renderPingChart(timestamps, googlePingAvg, googlePingLoss, cloudflarePingAvg, cloudflarePingLoss,
                    speedtestLatency, speedtestMaxLatency, googleMaxLatency, cloudflareMaxLatency);
    renderUptimeChart(timestamps, uptimeData);
    renderRxPowerChart(timestamps, rxScqamPowerData, rxOfdmPowerData);
    renderRxSnrChart(timestamps, rxScqamSnrData, rxOfdmSnrData);
    renderBerChart(timestamps, rxScqamBerData, rxOfdmBerData, rxScqamCorrectedData, rxOfdmCorrectedData);
    renderTxPowerChart(timestamps, txScqamData, txOfdmaData);
            }

            // Old API function - can be removed if no longer needed
            function renderTrendCharts(speedData, signalData) {
                // Debug logging
                console.log('Speed data sample:', speedData[0]);
                console.log('Signal data sample:', signalData[0]);
                
                // Extract timestamps from speed data (all checks should have same timestamps)
                const timestamps = speedData.map(d => d.check_time);
                
                // Extract speed test data
                const uploadSpeeds = speedData.map(d => parseSpeed(d.iperf3_upload));
                const downloadSpeeds = speedData.map(d => parseSpeed(d.iperf3_download));
                const uploadLimits = speedData.map(d => d.iperf3_upload_limit ? parseSpeed(d.iperf3_upload_limit) : null);
                const downloadLimits = speedData.map(d => d.iperf3_download_limit ? parseSpeed(d.iperf3_download_limit) : null);
                
                // Extract RX SC-QAM data (handle null values)
                const rxScqamPowerData = signalData.map(d => ({
                    min: d.rx_scqam?.min_power ?? null,
                    avg: d.rx_scqam?.avg_power ?? null,
                    max: d.rx_scqam?.max_power ?? null
                }));
                
                const rxScqamSnrData = signalData.map(d => ({
                    min: d.rx_scqam?.min_snr ?? null,
                    avg: d.rx_scqam?.avg_snr ?? null,
                    max: d.rx_scqam?.max_snr ?? null
                }));
                
                const rxScqamBerData = signalData.map(d => ({
                    avg: d.rx_scqam?.avg_ber ?? null,
                    max: d.rx_scqam?.max_ber ?? null
                }));
                
                // Extract RX OFDM data (handle null values)
                const rxOfdmPowerData = signalData.map(d => ({
                    min: d.rx_ofdm?.min_power ?? null,
                    avg: d.rx_ofdm?.avg_power ?? null,
                    max: d.rx_ofdm?.max_power ?? null
                }));
                
                const rxOfdmSnrData = signalData.map(d => ({
                    min: d.rx_ofdm?.min_snr ?? null,
                    avg: d.rx_ofdm?.avg_snr ?? null,
                    max: d.rx_ofdm?.max_snr ?? null
                }));
                
                const rxOfdmBerData = signalData.map(d => ({
                    avg: d.rx_ofdm?.avg_ber ?? null,
                    max: d.rx_ofdm?.max_ber ?? null
                }));
                
                // Extract TX SC-QAM data (handle null values)
                const txScqamData = signalData.map(d => ({
                    min: d.tx_scqam?.min_power ?? null,
                    avg: d.tx_scqam?.avg_power ?? null,
                    max: d.tx_scqam?.max_power ?? null,
                    bonded: d.tx_scqam?.bonded_count ?? 0
                }));
                
                // Extract TX OFDMA data (handle null values)
                const txOfdmaData = signalData.map(d => ({
                    avgPower: d.tx_ofdma?.avg_power ?? null,
                    bonded: d.tx_ofdma?.bonded_count ?? 0,
                    impaired: d.tx_ofdma?.impaired_count ?? 0
                }));
                
                console.log('Extracted data samples:');
                console.log('  Labels:', labels.slice(0, 3));
                console.log('  RX SC-QAM Power:', rxScqamPowerData.slice(0, 3));
                console.log('  RX OFDM Power:', rxOfdmPowerData.slice(0, 3));
                console.log('  RX SC-QAM SNR:', rxScqamSnrData.slice(0, 3));
                console.log('  TX SC-QAM:', txScqamData.slice(0, 3));
                console.log('  TX OFDMA:', txOfdmaData.slice(0, 3));
                
                // Render all charts (Note: API function doesn't calculate corrected data, so passing empty arrays)
                renderSpeedChart(timestamps, uploadSpeeds, downloadSpeeds, uploadLimits, downloadLimits);
                renderRxPowerChart(timestamps, rxScqamPowerData, rxOfdmPowerData);
                renderRxSnrChart(timestamps, rxScqamSnrData, rxOfdmSnrData);
                renderBerChart(timestamps, rxScqamBerData, rxOfdmBerData, [], []);
                renderTxPowerChart(timestamps, txScqamData, txOfdmaData);
            }

            function renderSpeedChart(timestamps, uploadData, downloadData, uploadLimits, downloadLimits) {
                const ctx = document.getElementById('speedChart');

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
                        plugins: {
                            legend: {
                                position: 'top',
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
                                title: {
                                    display: true,
                                    text: 'Time'
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true
                                }
                            },
                            y: {
                                beginAtZero: true,
                                title: {
                                    display: true,
                                    text: 'Speed (Mbps)'
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

            function renderPingChart(timestamps, googleAvg, googleLoss, cloudflareAvg, cloudflareLoss,
                                      speedtestLatency, speedtestMaxLatency, googleMaxLatency, cloudflareMaxLatency) {
                const ctx = document.getElementById('pingChart');

                if (charts.ping) {
                    charts.ping.destroy();
                }

                charts.ping = new Chart(ctx, {
                    type: 'line',
                    data: {
                        datasets: [{
                            label: 'Google Ping (ms)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: googleAvg[i] })),
                            borderColor: '#4285f4',
                            backgroundColor: 'rgba(66, 133, 244, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true,
                            yAxisID: 'y'
                        }, {
                            label: 'Cloudflare Ping (ms)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: cloudflareAvg[i] })),
                            borderColor: '#f6821f',
                            backgroundColor: 'rgba(246, 130, 31, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true,
                            yAxisID: 'y'
                        }, {
                            label: 'Speed Test Avg Latency (ms)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: speedtestLatency[i] })),
                            borderColor: '#34a853',
                            backgroundColor: 'rgba(52, 168, 83, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true,
                            yAxisID: 'y'
                        }, {
                            label: 'Speed Test Max Latency (ms)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: speedtestMaxLatency[i] })),
                            borderColor: '#9c27b0',
                            backgroundColor: 'rgba(156, 39, 176, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true,
                            yAxisID: 'y',
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
                            yAxisID: 'y',
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
                            yAxisID: 'y',
                            hidden: true
                        }, {
                            label: 'Google Packet Loss (%)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: googleLoss[i] })),
                            borderColor: 'rgba(234, 67, 53, 0.7)',
                            backgroundColor: 'rgba(234, 67, 53, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            borderWidth: 2,
                            pointRadius: 3,
                            yAxisID: 'y1'
                        }, {
                            label: 'Cloudflare Packet Loss (%)',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: cloudflareLoss[i] })),
                            borderColor: 'rgba(251, 188, 5, 0.7)',
                            backgroundColor: 'rgba(251, 188, 5, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            borderWidth: 2,
                            pointRadius: 3,
                            yAxisID: 'y1'
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'top',
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
                                            if (label.includes('Loss')) {
                                                label += context.parsed.y.toFixed(1) + '%';
                                            } else {
                                                label += context.parsed.y.toFixed(2) + ' ms';
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
                                title: {
                                    display: true,
                                    text: 'Time'
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true
                                }
                            },
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                title: {
                                    display: true,
                                    text: 'Latency (ms)'
                                },
                                beginAtZero: true,
                                suggestedMax: 50  // Auto-adjust but ensure reasonable minimum scale
                            },
                            y1: {
                                type: 'linear',
                                display: true,
                                position: 'right',
                                title: {
                                    display: true,
                                    text: 'Packet Loss (%)'
                                },
                                beginAtZero: true,
                                max: 100,
                                grid: {
                                    drawOnChartArea: false,
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

            function renderUptimeChart(timestamps, uptimeData) {
                const ctx = document.getElementById('uptimeChart');
                
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
                        plugins: {
                            legend: {
                                position: 'top',
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
                                title: {
                                    display: true,
                                    text: 'Time'
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true
                                }
                            },
                            y: {
                                beginAtZero: true,
                                title: {
                                    display: true,
                                    text: 'Uptime (days)'
                                },
                                ticks: {
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
                        plugins: {
                            legend: {
                                position: 'top',
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
                                title: {
                                    display: true,
                                    text: 'Time'
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true
                                }
                            },
                            y: {
                                title: {
                                    display: true,
                                    text: 'Power (dBmV)'
                                },
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
                        plugins: {
                            legend: {
                                position: 'top',
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
                                title: {
                                    display: true,
                                    text: 'Time'
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true
                                }
                            },
                            y: {
                                title: {
                                    display: true,
                                    text: 'SNR (dB)'
                                },
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
                        plugins: {
                            legend: {
                                position: 'top',
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
                                title: {
                                    display: true,
                                    text: 'Time'
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true
                                }
                            },
                            y: {
                                type: 'logarithmic',
                                title: {
                                    display: true,
                                    text: 'Error Rate (%)'
                                },
                                ticks: {
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

            function renderTxPowerChart(timestamps, txScqamData, txOfdmaData) {
                const ctx = document.getElementById('txPowerChart');
                
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
                            pointRadius: 2,
                            yAxisID: 'y'
                        }, {
                            label: 'Avg TX SC-QAM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txScqamData[i].avg })),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true,
                            yAxisID: 'y'
                        }, {
                            label: 'Max TX SC-QAM Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txScqamData[i].max })),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2,
                            yAxisID: 'y'
                        }, {
                            label: 'Avg TX OFDMA Power',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txOfdmaData[i].avgPower })),
                            borderColor: '#48bb78',
                            backgroundColor: 'rgba(72, 187, 120, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true,
                            yAxisID: 'y'
                        }, {
                            label: 'TX SC-QAM Bonded Channels',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txScqamData[i].bonded })),
                            borderColor: '#9f7aea',
                            backgroundColor: 'rgba(159, 122, 234, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            yAxisID: 'y1'
                        }, {
                            label: 'TX OFDMA Bonded Channels',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txOfdmaData[i].bonded })),
                            borderColor: '#38b2ac',
                            backgroundColor: 'rgba(56, 178, 172, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            yAxisID: 'y1'
                        }, {
                            label: 'TX OFDMA Impaired Channels',
                            data: timestamps.map((t, i) => ({ x: t * 1000, y: txOfdmaData[i].impaired })),
                            borderColor: '#f56565',
                            backgroundColor: 'rgba(245, 101, 101, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            yAxisID: 'y1'
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'top',
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
                                title: {
                                    display: true,
                                    text: 'Time'
                                },
                                ticks: {
                                    maxRotation: 45,
                                    minRotation: 45,
                                    autoSkip: true
                                }
                            },
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                title: {
                                    display: true,
                                    text: 'Power (dBmV)'
                                },
                                // Auto-scale to data range for better visibility
                                grace: '5%'  // Add 5% padding above/below data range
                            },
                            y1: {
                                type: 'linear',
                                display: true,
                                position: 'right',
                                title: {
                                    display: true,
                                    text: 'Channel Count'
                                },
                                beginAtZero: true,
                                grid: {
                                    drawOnChartArea: false,
                                },
                                ticks: {
                                    stepSize: 1
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
