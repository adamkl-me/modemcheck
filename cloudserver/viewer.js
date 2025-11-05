console.log("DEBUG: viewer.js file loaded");
// Global state
let allChecks = [];
let currentCheckIndex = 0;
let charts = {};
const API_BASE = '/cgi-bin/api.py';

// Check authentication before initializing
async function checkAuth() {
    console.log("DEBUG: checkAuth called");
    console.log("DEBUG: Current URL:", window.location.href);

    try {
        console.log("DEBUG: Fetching auth status from /cgi-bin/auth.py");
        const response = await fetch('/cgi-bin/auth.py');
        console.log("DEBUG: Auth response status:", response.status);

        if (!response.ok) {
            const errorText = await response.text();
            console.error("DEBUG: Auth check failed with status", response.status, errorText);
            window.location.href = '/login.html';
            return false;
        }

        const data = await response.json();
        console.log("DEBUG: Auth data:", data);

        if (!data.authenticated) {
            console.log("DEBUG: User not authenticated, redirecting to login");
            window.location.href = '/login.html';
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
        window.location.href = '/login.html';
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
            body: formData
        });
        
        window.location.href = '/login.html';
    } catch (error) {
        console.error('Logout failed:', error);
        window.location.href = '/login.html';
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

    // Set default date range to last 14 days
    setDefaultDateRange();

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
        const response = await fetch(`${API_BASE}?action=list_modems`);
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

        const select = document.getElementById('modemSelect');
        console.log("DEBUG: Select element found:", select);
        select.innerHTML = '<option value="">-- Select a modem --</option>';
        console.log("DEBUG: Default option set");

        data.modems.forEach(modem => {
            const option = document.createElement('option');
            option.value = modem.id;
            option.textContent = `${modem.type} - ${modem.mac}`;
            select.appendChild(option);
        });

        console.log("DEBUG: Successfully loaded", data.modems.length, "modems");
    } catch (error) {
        console.error('DEBUG: Error loading modems:', error);
        console.error('DEBUG: Error details:', error.message, error.stack);
        showStatus(`Error loading modem list: ${error.message}`, 'error');
    }
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
        // Get list of files
        let url = `${API_BASE}?action=list_files&modem_id=${encodeURIComponent(modemId)}`;
        if (startDate) url += `&start_date=${startDate}`;
        if (endDate) url += `&end_date=${endDate}`;
        
        const response = await fetch(url);
        console.log("DEBUG: Fetch completed, status:", response.status);
        const data = await response.json();
        console.log("DEBUG: JSON parsed, modems:", data.modems);
        
        if (data.files.length === 0) {
            showStatus('No data found for the selected criteria', 'error');
            document.getElementById('loadBtn').disabled = false;
            return;
        }
        
        showStatus(`Loading ${data.files.length} check(s)...`, 'info');
        
        // Load all files
        allChecks = [];
        for (const file of data.files) {
            const fileResponse = await fetch(
                `${API_BASE}?action=get_file&modem_id=${encodeURIComponent(modemId)}&filename=${encodeURIComponent(file.filename)}`
            );
            const fileData = await fileResponse.json();
            if (fileData.success) {
                allChecks.push(fileData.data);
            }
        }
        
        if (allChecks.length === 0) {
            showStatus('Failed to load data', 'error');
            document.getElementById('loadBtn').disabled = false;
            return;
        }
        
        // Sort by check time
        allChecks.sort((a, b) => {
            const timeA = a.sysinfo?.checktime || '';
            const timeB = b.sysinfo?.checktime || '';
            return timeA.localeCompare(timeB);
        });
        
        currentCheckIndex = allChecks.length - 1; // Start with most recent
        updateTimelineNav();
        
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
    const checkTime = current.sysinfo?.checktime || 'Unknown';
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
    
    document.getElementById('checktime').textContent = data.sysinfo?.checktime || '-';
    document.getElementById('modemtype').textContent = data.sysinfo?.modemtype || '-';
    document.getElementById('modemmac').textContent = data.sysinfo?.modemmac || '-';
    document.getElementById('firmware').textContent = data.sysinfo?.firmware || '-';
    document.getElementById('uptime').textContent = data.sysinfo?.uptime || '-';
    document.getElementById('systime').textContent = data.sysinfo?.systime || '-';
    
    document.getElementById('iperf3_ul').textContent = data.iperf3test_ul || '-';
    document.getElementById('iperf3_dl').textContent = data.iperf3test_dl || '-';
    
    document.getElementById('iperf3_ul_limit').textContent = data.iperf3uploadlimit ? `(Test limited to ${data.iperf3uploadlimit} Mbps)` : '';
    document.getElementById('iperf3_dl_limit').textContent = data.iperf3downloadlimit ? `(Test limited to ${data.iperf3downloadlimit} Mbps)` : '';
    
    // Display ping test results
    const pingGoogleAvg = data.ping_google_avg || '-';
    const pingGoogleLoss = data.ping_google_loss || '';
    document.getElementById('ping_google').textContent = pingGoogleAvg !== '-' && pingGoogleAvg !== 'Failed' ? `${pingGoogleAvg} ms` : pingGoogleAvg;
    document.getElementById('ping_google_loss').textContent = pingGoogleLoss ? `Packet loss: ${pingGoogleLoss}` : '';
    
    const pingCloudflareAvg = data.ping_cloudflare_avg || '-';
    const pingCloudflareLoss = data.ping_cloudflare_loss || '';
    document.getElementById('ping_cloudflare').textContent = pingCloudflareAvg !== '-' && pingCloudflareAvg !== 'Failed' ? `${pingCloudflareAvg} ms` : pingCloudflareAvg;
    document.getElementById('ping_cloudflare_loss').textContent = pingCloudflareLoss ? `Packet loss: ${pingCloudflareLoss}` : '';
    
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
            cell.textContent = item[key] !== undefined && item[key] !== null ? item[key] : 'n/a';
            row.appendChild(cell);
        });
        tableBody.appendChild(row);
    });
}

function parseSpeed(speedString) {
    if (!speedString || speedString === '-' || speedString === 'Failed' || speedString === 'Disabled') return null;
    const match = speedString.match(/(\d+\.?\d*)\s*(\w+)/);
    if (!match) return null;
    const value = parseFloat(match[1]);
    const unit = match[2].toLowerCase();
    if (unit.includes('gbits') || unit.includes('gb')) return value * 1000;
    if (unit.includes('mbits') || unit.includes('mb')) return value;
    if (unit.includes('kbits') || unit.includes('kb')) return value / 1000;
    return value;
}
function renderTrendChartsFromChecks() {
    if (allChecks.length < 2) return;
    
    // Extract data for charts
    const labels = allChecks.map(c => c.sysinfo?.checktime || '');
    
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
    
    // BER data (Bit Error Rate = uncorrectables / octets * 100)
    const rxScqamBerData = allChecks.map(c => {
        if (!c.rx || c.rx.length === 0) return { avg: null, max: null };
        const bers = c.rx.map(ch => {
            const octets = parseInt(ch.octets) || 0;
            const uncorrectds = parseInt(ch.uncorrectds) || 0;
            if (octets === 0) return 0;
            return (uncorrectds / octets) * 100;
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
            const octets = parseInt(ch.octets) || 0;
            const uncorrectds = parseInt(ch.uncorrectds) || 0;
            if (octets === 0) return 0;
            return (uncorrectds / octets) * 100;
        }).filter(b => !isNaN(b) && isFinite(b));
        if (bers.length === 0) return { avg: null, max: null };
        return {
            avg: bers.reduce((a, b) => a + b) / bers.length,
            max: Math.max(...bers)
        };
    });
    
    // Correctable codeword error rate data (correcteds / octets * 100)
    const rxScqamCorrectedData = allChecks.map(c => {
        if (!c.rx || c.rx.length === 0) return { avg: null, max: null };
        const rates = c.rx.map(ch => {
            const octets = parseInt(ch.octets) || 0;
            const correcteds = parseInt(ch.correcteds) || 0;
            if (octets === 0) return 0;
            return (correcteds / octets) * 100;
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
            const octets = parseInt(ch.octets) || 0;
            const correcteds = parseInt(ch.correcteds) || 0;
            if (octets === 0) return 0;
            return (correcteds / octets) * 100;
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
    
    // Render all charts
    renderSpeedChart(labels, uploadSpeeds, downloadSpeeds, uploadLimits, downloadLimits);
    renderPingChart(labels, googlePingAvg, googlePingLoss, cloudflarePingAvg, cloudflarePingLoss);
    renderRxPowerChart(labels, rxScqamPowerData, rxOfdmPowerData);
    renderRxSnrChart(labels, rxScqamSnrData, rxOfdmSnrData);
    renderBerChart(labels, rxScqamBerData, rxOfdmBerData, rxScqamCorrectedData, rxOfdmCorrectedData);
    renderTxPowerChart(labels, txScqamData, txOfdmaData);
            }

            // Old API function - can be removed if no longer needed
            function renderTrendCharts(speedData, signalData) {
                // Debug logging
                console.log('Speed data sample:', speedData[0]);
                console.log('Signal data sample:', signalData[0]);
                
                // Extract labels from speed data (all checks should have same timestamps)
                const labels = speedData.map(d => d.check_time);
                
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
                renderSpeedChart(labels, uploadSpeeds, downloadSpeeds, uploadLimits, downloadLimits);
                renderRxPowerChart(labels, rxScqamPowerData, rxOfdmPowerData);
                renderRxSnrChart(labels, rxScqamSnrData, rxOfdmSnrData);
                renderBerChart(labels, rxScqamBerData, rxOfdmBerData, [], []);
                renderTxPowerChart(labels, txScqamData, txOfdmaData);
            }

            function parseSpeed(speedString) {
                if (!speedString || speedString === '-' || speedString === 'Failed' || speedString === 'Disabled') {
                    return null;
                }
                
                const match = speedString.match(/(\d+\.?\d*)\s*(\w+)/);
                if (!match) return null;
                
                const value = parseFloat(match[1]);
                const unit = match[2].toLowerCase();
                
                // Convert to Mbps
                if (unit.includes('gbits') || unit.includes('gb')) {
                    return value * 1000;
                } else if (unit.includes('mbits') || unit.includes('mb')) {
                    return value;
                } else if (unit.includes('kbits') || unit.includes('kb')) {
                    return value / 1000;
                }
                
                return value;
            }

            function renderSpeedChart(labels, uploadData, downloadData, uploadLimits, downloadLimits) {
                const ctx = document.getElementById('speedChart');
                
                if (charts.speed) {
                    charts.speed.destroy();
                }
                
                const datasets = [{
                    label: 'Download Speed',
                    data: downloadData,
                    borderColor: '#667eea',
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    tension: 0.4,
                    fill: true
                }, {
                    label: 'Upload Speed',
                    data: uploadData,
                    borderColor: '#764ba2',
                    backgroundColor: 'rgba(118, 75, 162, 0.1)',
                    tension: 0.4,
                    fill: true
                }];
                
                // Add download limit line if available
                if (downloadLimits && downloadLimits.some(l => l !== null)) {
                    datasets.push({
                        label: 'Download Limit',
                        data: downloadLimits,
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
                        data: uploadLimits,
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
                        labels: labels,
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

            function renderPingChart(labels, googleAvg, googleLoss, cloudflareAvg, cloudflareLoss) {
                const ctx = document.getElementById('pingChart');
                
                if (charts.ping) {
                    charts.ping.destroy();
                }
                
                charts.ping = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Google Ping (ms)',
                            data: googleAvg,
                            borderColor: '#4285f4',
                            backgroundColor: 'rgba(66, 133, 244, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true,
                            yAxisID: 'y'
                        }, {
                            label: 'Cloudflare Ping (ms)',
                            data: cloudflareAvg,
                            borderColor: '#f6821f',
                            backgroundColor: 'rgba(246, 130, 31, 0.1)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true,
                            yAxisID: 'y'
                        }, {
                            label: 'Google Packet Loss (%)',
                            data: googleLoss,
                            borderColor: 'rgba(234, 67, 53, 0.7)',
                            backgroundColor: 'rgba(234, 67, 53, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            borderWidth: 2,
                            pointRadius: 3,
                            yAxisID: 'y1'
                        }, {
                            label: 'Cloudflare Packet Loss (%)',
                            data: cloudflareLoss,
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
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                title: {
                                    display: true,
                                    text: 'Latency (ms)'
                                },
                                beginAtZero: true
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

            function renderRxPowerChart(labels, rxScqamData, rxOfdmData) {
                const ctx = document.getElementById('rxPowerChart');
                
                if (charts.rxPower) {
                    charts.rxPower.destroy();
                }
                
                charts.rxPower = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Min RX SC-QAM Power',
                            data: rxScqamData.map(d => d.min),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2,
                            spanGaps: true
                        }, {
                            label: 'Avg RX SC-QAM Power',
                            data: rxScqamData.map(d => d.avg),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true
                        }, {
                            label: 'Max RX SC-QAM Power',
                            data: rxScqamData.map(d => d.max),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Min RX OFDM Power',
                            data: rxOfdmData.map(d => d.min),
                            borderColor: '#48bb78',
                            backgroundColor: 'rgba(72, 187, 120, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX OFDM Power',
                            data: rxOfdmData.map(d => d.avg),
                            borderColor: '#48bb78',
                            backgroundColor: 'rgba(72, 187, 120, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true
                        }, {
                            label: 'Max RX OFDM Power',
                            data: rxOfdmData.map(d => d.max),
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
                            y: {
                                title: {
                                    display: true,
                                    text: 'Power (dBmV)'
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

            function renderRxSnrChart(labels, rxScqamData, rxOfdmData) {
                const ctx = document.getElementById('rxSnrChart');
                
                if (charts.rxSnr) {
                    charts.rxSnr.destroy();
                }
                
                charts.rxSnr = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Min RX SC-QAM SNR',
                            data: rxScqamData.map(d => d.min),
                            borderColor: '#ed8936',
                            backgroundColor: 'rgba(237, 137, 54, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX SC-QAM SNR',
                            data: rxScqamData.map(d => d.avg),
                            borderColor: '#ed8936',
                            backgroundColor: 'rgba(237, 137, 54, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true
                        }, {
                            label: 'Max RX SC-QAM SNR',
                            data: rxScqamData.map(d => d.max),
                            borderColor: '#ed8936',
                            backgroundColor: 'rgba(237, 137, 54, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Min RX OFDM SNR',
                            data: rxOfdmData.map(d => d.min),
                            borderColor: '#9f7aea',
                            backgroundColor: 'rgba(159, 122, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX OFDM SNR',
                            data: rxOfdmData.map(d => d.avg),
                            borderColor: '#9f7aea',
                            backgroundColor: 'rgba(159, 122, 234, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true
                        }, {
                            label: 'Max RX OFDM SNR',
                            data: rxOfdmData.map(d => d.max),
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
                            y: {
                                title: {
                                    display: true,
                                    text: 'SNR (dB)'
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

            function renderBerChart(labels, rxScqamBerData, rxOfdmBerData, rxScqamCorrectedData, rxOfdmCorrectedData) {
                const ctx = document.getElementById('berChart');
                
                if (charts.ber) {
                    charts.ber.destroy();
                }
                
                charts.ber = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Avg RX SC-QAM BER (Uncorrectable)',
                            data: rxScqamBerData.map(d => d.avg),
                            borderColor: '#f56565',
                            backgroundColor: 'rgba(245, 101, 101, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'Max RX SC-QAM BER (Uncorrectable)',
                            data: rxScqamBerData.map(d => d.max),
                            borderColor: '#c53030',
                            backgroundColor: 'rgba(197, 48, 48, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX OFDM BER (Uncorrectable)',
                            data: rxOfdmBerData.map(d => d.avg),
                            borderColor: '#ed8936',
                            backgroundColor: 'rgba(237, 137, 54, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'Max RX OFDM BER (Uncorrectable)',
                            data: rxOfdmBerData.map(d => d.max),
                            borderColor: '#c05621',
                            backgroundColor: 'rgba(192, 86, 33, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX SC-QAM Corrected',
                            data: rxScqamCorrectedData.map(d => d.avg),
                            borderColor: '#48bb78',
                            backgroundColor: 'rgba(72, 187, 120, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'Max RX SC-QAM Corrected',
                            data: rxScqamCorrectedData.map(d => d.max),
                            borderColor: '#38a169',
                            backgroundColor: 'rgba(56, 161, 105, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2
                        }, {
                            label: 'Avg RX OFDM Corrected',
                            data: rxOfdmCorrectedData.map(d => d.avg),
                            borderColor: '#4299e1',
                            backgroundColor: 'rgba(66, 153, 225, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true
                        }, {
                            label: 'Max RX OFDM Corrected',
                            data: rxOfdmCorrectedData.map(d => d.max),
                            borderColor: '#3182ce',
                            backgroundColor: 'rgba(49, 130, 206, 0.1)',
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
                                intersect: false,
                                callbacks: {
                                    label: function(context) {
                                        let label = context.dataset.label || '';
                                        if (label) {
                                            label += ': ';
                                        }
                                        if (context.parsed.y !== null) {
                                            label += context.parsed.y.toExponential(2) + '%';
                                        }
                                        return label;
                                    }
                                }
                            }
                        },
                        scales: {
                            y: {
                                type: 'logarithmic',
                                title: {
                                    display: true,
                                    text: 'Error Rate (%)'
                                },
                                ticks: {
                                    callback: function(value) {
                                        return value.toExponential(0);
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

            function renderTxPowerChart(labels, txScqamData, txOfdmaData) {
                const ctx = document.getElementById('txPowerChart');
                
                if (charts.txPower) {
                    charts.txPower.destroy();
                }
                
                charts.txPower = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Min TX SC-QAM Power',
                            data: txScqamData.map(d => d.min),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2,
                            yAxisID: 'y'
                        }, {
                            label: 'Avg TX SC-QAM Power',
                            data: txScqamData.map(d => d.avg),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.2)',
                            tension: 0.4,
                            borderWidth: 3,
                            fill: true,
                            yAxisID: 'y'
                        }, {
                            label: 'Max TX SC-QAM Power',
                            data: txScqamData.map(d => d.max),
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            borderDash: [5, 5],
                            tension: 0.4,
                            pointRadius: 2,
                            yAxisID: 'y'
                        }, {
                            label: 'Avg TX OFDMA Power',
                            data: txOfdmaData.map(d => d.avgPower),
                            borderColor: '#48bb78',
                            backgroundColor: 'rgba(72, 187, 120, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            fill: true,
                            yAxisID: 'y'
                        }, {
                            label: 'TX SC-QAM Bonded Channels',
                            data: txScqamData.map(d => d.bonded),
                            borderColor: '#9f7aea',
                            backgroundColor: 'rgba(159, 122, 234, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            yAxisID: 'y1'
                        }, {
                            label: 'TX OFDMA Bonded Channels',
                            data: txOfdmaData.map(d => d.bonded),
                            borderColor: '#38b2ac',
                            backgroundColor: 'rgba(56, 178, 172, 0.2)',
                            tension: 0.4,
                            borderWidth: 2,
                            yAxisID: 'y1'
                        }, {
                            label: 'TX OFDMA Impaired Channels',
                            data: txOfdmaData.map(d => d.impaired),
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
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                title: {
                                    display: true,
                                    text: 'Power (dBmV)'
                                }
                            },
                            y1: {
                                type: 'linear',
                                display: true,
                                position: 'right',
                                title: {
                                    display: true,
                                    text: 'Channel Count'
                                },
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
