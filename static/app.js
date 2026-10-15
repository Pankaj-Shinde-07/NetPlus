// NetPulse Cyber NOC v4.0 — Full Frontend Logic (Phase 2)

/* ─── State ─────────────────────────────────── */
let ws = null;
let timelineChart = null, categoryChart = null;
let topDomainsChart = null, bandwidthChart = null, latencyChart = null;
let currentDeviceFilter = 'All';
let currentMode = 'clean';
let activeModalIp = null;
let activeTab = 'overview';

/* ─── Animated Particle Canvas ───────────────── */
(function initBg() {
    const canvas = document.getElementById('bgCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let W, H, particles = [];
    function resize() { W = canvas.width = window.innerWidth; H = canvas.height = window.innerHeight; }
    class Particle {
        constructor() { this.reset(); }
        reset() {
            this.x  = Math.random() * W; this.y  = Math.random() * H;
            this.vx = (Math.random() - .5) * .35; this.vy = (Math.random() - .5) * .35;
            this.r  = Math.random() * 1.4 + .4;
            const p = ['#6366f1','#06b6d4','#a855f7','#3b82f6','#10b981'];
            this.color = p[Math.floor(Math.random() * p.length)];
            this.alpha = Math.random() * .45 + .15;
        }
        move() { this.x += this.vx; this.y += this.vy; if (this.x<0||this.x>W||this.y<0||this.y>H) this.reset(); }
        draw() { ctx.beginPath(); ctx.arc(this.x,this.y,this.r,0,Math.PI*2); ctx.fillStyle=this.color; ctx.globalAlpha=this.alpha; ctx.fill(); }
    }
    function loop() {
        ctx.clearRect(0,0,W,H);
        particles.forEach(p => { p.move(); p.draw(); });
        ctx.globalAlpha = 1;
        for (let i=0;i<particles.length;i++) for (let j=i+1;j<particles.length;j++) {
            const dx=particles[i].x-particles[j].x, dy=particles[i].y-particles[j].y;
            const d=Math.sqrt(dx*dx+dy*dy);
            if (d < 110) { ctx.beginPath(); ctx.moveTo(particles[i].x,particles[i].y); ctx.lineTo(particles[j].x,particles[j].y); ctx.strokeStyle=particles[i].color; ctx.globalAlpha=(1-d/110)*.1; ctx.lineWidth=.5; ctx.stroke(); }
        }
        requestAnimationFrame(loop);
    }
    window.addEventListener('resize', resize);
    resize(); particles = Array.from({length:80},()=>new Particle()); loop();
})();

/* ─── Helpers ────────────────────────────────── */
function formatBytes(bytes, dec=1) {
    if (!bytes||bytes===0) return '0 B';
    const k=1024, s=['B','KB','MB','GB','TB'], i=Math.floor(Math.log(bytes)/Math.log(k));
    return parseFloat((bytes/Math.pow(k,i)).toFixed(dec))+' '+s[i];
}
function formatRelTime(sec) {
    if (sec<=10) return 'Just now'; if (sec<60) return `${Math.floor(sec)}s ago`;
    const m=Math.floor(sec/60); if (m<60) return `${m}m ago`;
    return `${Math.floor(m/60)}h ago`;
}
function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function catClass(cat) {
    const m = {'Academic & Learning':'cat-academic','Entertainment & Social':'cat-social','Gaming & Arcade':'cat-gaming',
               'Proxy & Bypass':'cat-proxy','Search & Knowledge':'cat-search','Messaging & Collab':'cat-messaging','Cloud & Infrastructure':'cat-cloud'};
    return m[cat]||'cat-general';
}
function deviceIcon(type) {
    return type==='mobile'?'fa-mobile-screen-button':type==='tablet'?'fa-tablet-screen-button':type==='laptop'?'fa-laptop':'fa-desktop';
}
function livenessBadge(liveness, sec) {
    const t=formatRelTime(sec);
    if (liveness==='Online')  return `<span class="live-badge online"><span class="live-dot green"></span>${t}</span>`;
    if (liveness==='Idle')    return `<span class="live-badge idle"><span class="live-dot amber"></span>Idle (${t})</span>`;
    return `<span class="live-badge offline"><span class="live-dot gray"></span>Offline (${t})</span>`;
}
function toast(msg, icon='fa-circle-check', color='#34d399') {
    const c=document.getElementById('toastContainer');
    const el=document.createElement('div'); el.className='toast';
    el.innerHTML=`<i class="fa-solid ${icon}" style="color:${color};font-size:15px"></i><span>${msg}</span>`;
    c.appendChild(el); setTimeout(()=>el.remove(),3500);
}

/* ─── Notification API ───────────────────────── */
function requestNotificationPerm() {
    if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission();
}
function sendNotification(title, body, icon='🚫') {
    if ('Notification' in window && Notification.permission === 'granted') {
        try { new Notification(`${icon} ${title}`, { body, icon: '/static/favicon.ico' }); } catch(e) {}
    }
}

/* ─── Theme Toggle ───────────────────────────── */
(function initTheme() {
    const saved = localStorage.getItem('np-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
    updateThemeIcon(saved);
})();
function updateThemeIcon(theme) {
    const el = document.getElementById('themeIcon');
    if (!el) return;
    el.className = theme === 'dark' ? 'fa-solid fa-moon' : 'fa-solid fa-sun';
}
document.getElementById('btnThemeToggle').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('np-theme', next);
    updateThemeIcon(next);
    toast(`${next === 'light' ? '☀️ Light' : '🌙 Dark'} mode activated`, 'fa-circle-half-stroke', '#818cf8');
});

/* ─── Charts Initialization ──────────────────── */
function initCharts() {
    const gc = 'rgba(255,255,255,0.04)', tc = '#475569';

    timelineChart = new Chart(document.getElementById('timelineChart').getContext('2d'), {
        type:'line', data:{labels:[],datasets:[{label:'Requests',data:[],borderColor:'#6366f1',
            backgroundColor:(ctx)=>{ const g=ctx.chart.ctx.createLinearGradient(0,0,0,200); g.addColorStop(0,'rgba(99,102,241,.28)'); g.addColorStop(1,'rgba(99,102,241,.01)'); return g; },
            tension:.42,fill:true,pointRadius:2,pointHoverRadius:5,borderWidth:2}]},
        options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{intersect:false,mode:'index'},
            scales:{x:{grid:{color:gc},ticks:{color:tc,font:{family:'JetBrains Mono',size:10},maxTicksLimit:8}},
                    y:{beginAtZero:true,grid:{color:gc},ticks:{color:tc,precision:0}}},
            plugins:{legend:{display:false},tooltip:{bodyFont:{family:'JetBrains Mono'}}}}
    });

    categoryChart = new Chart(document.getElementById('categoryChart').getContext('2d'), {
        type:'doughnut', data:{labels:[],datasets:[{data:[],backgroundColor:['#10b981','#a855f7','#f59e0b','#3b82f6','#06b6d4','#f43f5e','#64748b'],borderWidth:0,hoverOffset:6}]},
        options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{color:'#64748b',font:{size:10},boxWidth:10,padding:10}}},cutout:'70%'}
    });

    topDomainsChart = new Chart(document.getElementById('topDomainsChart').getContext('2d'), {
        type:'bar', data:{labels:[],datasets:[{label:'Visits',data:[],backgroundColor:'rgba(6,182,212,0.7)',borderRadius:5}]},
        options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,
            scales:{x:{grid:{color:gc},ticks:{color:tc,precision:0}},y:{grid:{display:false},ticks:{color:'#94a3b8',font:{family:'JetBrains Mono',size:10}}}},
            plugins:{legend:{display:false}}}
    });

    bandwidthChart = new Chart(document.getElementById('bandwidthChart').getContext('2d'), {
        type:'bar', data:{labels:[],datasets:[{label:'Bytes',data:[],backgroundColor:'rgba(16,185,129,0.6)',borderRadius:4,hoverBackgroundColor:'rgba(16,185,129,0.9)'}]},
        options:{responsive:true,maintainAspectRatio:false,animation:false,
            scales:{x:{grid:{color:gc},ticks:{color:tc,font:{family:'JetBrains Mono',size:9},maxTicksLimit:12}},
                    y:{beginAtZero:true,grid:{color:gc},ticks:{color:tc,callback:v=>formatBytes(v,0)}}},
            plugins:{legend:{display:false},tooltip:{callbacks:{label:i=>` ${formatBytes(i.raw)}`}}}}
    });

    latencyChart = new Chart(document.getElementById('latencyChart').getContext('2d'), {
        type:'line', data:{labels:[],datasets:[]},
        options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{intersect:false,mode:'index'},
            scales:{x:{grid:{color:gc},ticks:{color:tc,font:{size:9},maxTicksLimit:8}},
                    y:{beginAtZero:true,grid:{color:gc},ticks:{color:tc,callback:v=>`${v}ms`}}},
            plugins:{legend:{display:true,labels:{color:'#64748b',font:{size:10},boxWidth:10}}}}
    });
}

/* ─── Stats ──────────────────────────────────── */
async function fetchStats() {
    const df = document.getElementById('filterDateFrom').value;
    const dt = document.getElementById('filterDateTo').value;
    let url = `/api/stats?mode=${currentMode}`;
    if (df) url += `&date_from=${df}`;
    if (dt) url += `&date_to=${dt}`;
    try {
        const d = await fetch(url).then(r=>r.json());
        document.getElementById('valTotalRequests').textContent = d.total_requests.toLocaleString();
        document.getElementById('valTotalBandwidth').textContent = formatBytes(d.total_bytes);
        document.getElementById('valTotalBlocked').textContent = d.total_blocked.toLocaleString();
        document.getElementById('valActiveDevices').textContent = d.active_devices;
        document.getElementById('subActiveDevices').innerHTML = `<i class="fa-solid fa-circle-dot"></i> ${d.active_devices} Online / ${d.total_devices} Recorded`;
        if (d.categories && Object.keys(d.categories).length) {
            categoryChart.data.labels = Object.keys(d.categories);
            categoryChart.data.datasets[0].data = Object.values(d.categories);
            categoryChart.update();
        }
        if (d.top_domains && d.top_domains.length) {
            const top = d.top_domains.slice(0,7);
            topDomainsChart.data.labels = top.map(d=>d.domain);
            topDomainsChart.data.datasets[0].data = top.map(d=>d.count);
            topDomainsChart.update();
        }
    } catch(e) { console.warn('Stats error',e); }
}

/* ─── Bandwidth Trend ───────────────────────── */
async function fetchBandwidthTrend() {
    try {
        const data = await fetch(`/api/bandwidth/trend?mode=${currentMode}`).then(r=>r.json());
        bandwidthChart.data.labels = data.map(d=>d.hour);
        bandwidthChart.data.datasets[0].data = data.map(d=>d.bytes);
        bandwidthChart.update('none');
    } catch(e) { console.warn('Bandwidth trend error',e); }
}
document.getElementById('btnRefreshBandwidth').addEventListener('click', fetchBandwidthTrend);

/* ─── Local AI Traffic Analysis ───────────────── */
async function fetchAIAnalysis() {
    const content = document.getElementById('aiAnalysisContent');
    try {
        const data = await fetch(`/api/ai/analysis?mode=${currentMode}`).then(r => r.json());
        document.getElementById('aiTrainingStatus').textContent =
            `${Number(data.training_requests || 0).toLocaleString()} requests · ${data.devices_trained || 0} devices`;
        const insights = (data.insights || []).map(text => `<li>${text}</li>`).join('');
        const anomalies = data.anomalies || [];
        const rows = anomalies.length ? anomalies.map(item => `
            <div class="ai-anomaly ${item.severity}">
                <span class="ai-anomaly-severity">${item.severity.toUpperCase()}</span>
                <div><strong>${item.device}</strong><small>${item.ip} · ${item.hour}</small></div>
                <div class="ai-anomaly-count">${item.observed}<small> requests (expected ${item.expected})</small></div>
            </div>`).join('') : '<div class="ai-no-anomalies"><i class="fa-solid fa-circle-check"></i> No unusual activity detected this hour</div>';
        content.innerHTML = `<ul class="ai-insights">${insights}</ul><div class="ai-anomaly-list">${rows}</div>
            <p class="ai-privacy"><i class="fa-solid fa-lock"></i> ${data.privacy}</p>`;
    } catch (error) {
        content.innerHTML = '<div class="ai-no-anomalies">Analysis is temporarily unavailable.</div>';
    }
}
document.getElementById('btnRefreshAI').addEventListener('click', fetchAIAnalysis);

/* ─── Main Tabs Navigation ───────────────────── */
function initNavigationTabs() {
    document.querySelectorAll('.topbar-nav-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab');
            document.querySelectorAll('.topbar-nav-tab').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.app-tab-pane').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const pane = document.getElementById(targetId);
            if (pane) pane.classList.add('active');
            
            if (targetId === 'tabAttendance') {
                fetchAttendance();
                fetchAttendanceStats();
                fetchConnectedDevices();
            } else if (targetId === 'tabAIExport') {
                fetchExportSchema();
                fetchExportPreview();
            }
        });
    });
}

/* ─── Smart Attendance System ────────────────── */
async function fetchAttendance() {
    const dateInput = document.getElementById('attendanceDate');
    const batchSelect = document.getElementById('attendanceBatchFilter');
    const searchInput = document.getElementById('attendanceSearchInput');
    const body = document.getElementById('attendanceTableBody');
    if (!body) return;

    const date = dateInput ? dateInput.value : '';
    const batch = batchSelect ? batchSelect.value : 'All';
    const search = searchInput ? searchInput.value.trim() : '';

    try {
        let url = `/api/attendance?date=${encodeURIComponent(date)}`;
        if (batch && batch !== 'All') url += `&batch=${encodeURIComponent(batch)}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;

        const rows = await fetch(url).then(r => r.json());
        const countBadge = document.getElementById('attendanceCount');
        if (countBadge) countBadge.textContent = `${rows.length} Present`;

        if (!rows.length) {
            body.innerHTML = '<tr class="table-empty-row"><td colspan="10"><i class="fa-solid fa-user-xmark" style="margin-right:8px"></i> No attendance records found for this date.</td></tr>';
            return;
        }

        body.innerHTML = rows.map(r => {
            const statusClass = r.is_online ? 'online' : (r.status === 'Present' ? 'present' : 'late');
            const statusLabel = r.is_online ? '<span class="pulse-green"></span> Online Now' : (r.status || 'Present');
            const shortMac = r.mac_address || '—';
            const shortIp = r.ip_address ? ` (${r.ip_address})` : '';

            return `
                <tr>
                    <td class="cell-ip"><strong>${escapeHtml(r.prn)}</strong></td>
                    <td class="cell-domain"><strong style="color:var(--tx-1)">${escapeHtml(r.name)}</strong></td>
                    <td><span class="cat-chip cat-academic">${escapeHtml(r.batch)}</span></td>
                    <td style="font-family:var(--f-mono);font-size:11px;color:var(--tx-2)">
                        ${escapeHtml(shortMac)}<span style="color:var(--tx-3);font-size:10px">${escapeHtml(shortIp)}</span>
                    </td>
                    <td>${escapeHtml((r.first_seen||'').split(' ')[1] || r.first_seen)}</td>
                    <td>${escapeHtml((r.last_seen||'').split(' ')[1] || r.last_seen)}</td>
                    <td><span style="font-weight:600;color:var(--tx-2)">${escapeHtml(r.duration_formatted)}</span></td>
                    <td style="font-family:var(--f-mono)">${r.connections || 1}</td>
                    <td><span class="status-pill ${statusClass}">${statusLabel}</span></td>
                    <td style="text-align:right">
                        <button class="icon-btn" onclick="deleteAttendanceRecord(${r.id})" title="Delete record" style="width:28px;height:28px;display:inline-flex">
                            <i class="fa-solid fa-trash-can" style="font-size:11px;color:var(--rose)"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        body.innerHTML = '<tr class="table-empty-row"><td colspan="10">Unable to load attendance ledger.</td></tr>';
    }
}

async function fetchAttendanceStats() {
    const dateInput = document.getElementById('attendanceDate');
    const date = dateInput ? dateInput.value : '';
    try {
        const stats = await fetch(`/api/attendance/stats?date=${encodeURIComponent(date)}`).then(r => r.json());
        
        const elReg = document.getElementById('valAttRegistered');
        const elPres = document.getElementById('valAttPresent');
        const elActive = document.getElementById('valAttActiveNow');
        const elRate = document.getElementById('valAttRateBadge');
        const elNav = document.getElementById('navAttendanceCount');

        if (elReg) elReg.textContent = stats.total_registered || 0;
        if (elPres) elPres.textContent = stats.present_today || 0;
        if (elActive) elActive.textContent = stats.active_now || 0;
        if (elRate) elRate.textContent = `${stats.attendance_rate}% Rate`;
        if (elNav) elNav.textContent = `${stats.active_now || stats.present_today || 0} Live`;

        // Update batch dropdown options if new batches are available
        const batchSelect = document.getElementById('attendanceBatchFilter');
        if (batchSelect && stats.batches) {
            const currentVal = batchSelect.value;
            const currentOptions = Array.from(batchSelect.options).map(o => o.value);
            stats.batches.forEach(b => {
                if (!currentOptions.includes(b)) {
                    const opt = document.createElement('option');
                    opt.value = b;
                    opt.textContent = b;
                    batchSelect.appendChild(opt);
                }
            });
            batchSelect.value = currentVal;
        }
    } catch(e) {}
}

async function fetchConnectedDevices() {
    const radarList = document.getElementById('radarDeviceList');
    const regSelect = document.getElementById('regDeviceSelect');
    if (!radarList) return;

    try {
        const devs = await fetch('/api/connected-devices').then(r => r.json());
        if (!devs.length) {
            radarList.innerHTML = '<div class="loading-cell" style="padding:20px;text-align:center"><i class="fa-solid fa-signal" style="color:var(--tx-3)"></i><p style="margin-top:6px;font-size:12px;color:var(--tx-3)">No active hotspot/Wi-Fi devices detected.</p></div>';
            return;
        }

        // Populate modal select
        if (regSelect) {
            regSelect.innerHTML = '<option value="">— Pick Live Device —</option>';
            devs.forEach(d => {
                if (d.mac) {
                    const opt = document.createElement('option');
                    opt.value = d.mac;
                    opt.textContent = `${d.name} (${d.ip})`;
                    regSelect.appendChild(opt);
                }
            });
        }

        radarList.innerHTML = devs.map(d => {
            const isMatched = !!d.student;
            const statusHtml = isMatched
                ? `<span class="radar-status-tag matched"><i class="fa-solid fa-check"></i> ${escapeHtml(d.student.name)} (${escapeHtml(d.student.batch)})</span>`
                : `<span class="radar-status-tag unmapped"><i class="fa-solid fa-triangle-exclamation"></i> Unassigned Device</span>`;
            
            const actionHtml = isMatched
                ? `<div style="font-size:10px;color:var(--tx-3);font-family:var(--f-mono)">PRN: ${escapeHtml(d.student.prn)} &bull; Attendance Auto-Updating</div>`
                : `<button class="btn-quick-map" onclick="openAssignModal('${escapeHtml(d.mac)}', '${escapeHtml(d.ip)}')"><i class="fa-solid fa-user-plus"></i> Assign to Student</button>`;

            return `
                <div class="radar-device-item">
                    <div class="radar-device-top">
                        <div class="radar-dev-name">
                            <i class="fa-solid ${deviceIcon(d.device_type)}" style="color:var(--cyan)"></i>
                            <span>${escapeHtml(d.name)}</span>
                        </div>
                        <span class="live-badge ${d.liveness.toLowerCase()}"><span class="live-dot ${d.liveness==='Online'?'green':'gray'}"></span>${d.liveness}</span>
                    </div>
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span class="radar-dev-ip">${escapeHtml(d.ip)}</span>
                        <span class="radar-dev-mac">${escapeHtml(d.mac || 'No MAC')}</span>
                    </div>
                    ${statusHtml}
                    ${actionHtml}
                </div>
            `;
        }).join('');
    } catch(e) {
        radarList.innerHTML = '<div class="loading-cell">Failed to scan devices.</div>';
    }
}

function openAssignModal(mac, ip) {
    const modal = document.getElementById('studentModal');
    if (!modal) return;
    const inpMac = document.getElementById('regMac');
    if (inpMac && mac) inpMac.value = mac;
    modal.classList.add('active');
}

async function deleteAttendanceRecord(id) {
    if (!confirm('Remove this attendance record?')) return;
    try {
        await fetch(`/api/attendance/${id}`, { method: 'DELETE' });
        toast('Attendance record deleted', 'fa-trash-can', '#f59e0b');
        fetchAttendance();
        fetchAttendanceStats();
    } catch(e) {
        toast('Failed to delete record', 'fa-circle-exclamation', '#fb7185');
    }
}

/* ─── AI Dataset Export Studio ───────────────── */
let activeDatasetType = 'traffic_features';

function initAIExportStudio() {
    // Dataset Card selection
    document.querySelectorAll('.dataset-card').forEach(card => {
        card.addEventListener('click', () => {
            document.querySelectorAll('.dataset-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            const radio = card.querySelector('input[type="radio"]');
            if (radio) radio.checked = true;
            activeDatasetType = card.getAttribute('data-dataset-type') || 'traffic_features';
            fetchExportSchema();
            fetchExportPreview();
        });
    });

    // Formats & Limit change
    const selFmt = document.getElementById('exportFormatSelect');
    const selMode = document.getElementById('exportModeSelect');
    const selLimit = document.getElementById('exportLimitSelect');
    if (selFmt) selFmt.addEventListener('change', fetchExportPreview);
    if (selMode) selMode.addEventListener('change', fetchExportPreview);
    if (selLimit) selLimit.addEventListener('change', fetchExportPreview);

    // Refresh preview button
    const btnRefPrev = document.getElementById('btnRefreshPreview');
    if (btnRefPrev) btnRefPrev.addEventListener('click', fetchExportPreview);

    // Download AI Dataset button
    const btnDownload = document.getElementById('btnDownloadAIDataset');
    if (btnDownload) {
        btnDownload.addEventListener('click', () => {
            const format = selFmt ? selFmt.value : 'csv';
            const mode = selMode ? selMode.value : 'clean';
            const limit = selLimit ? selLimit.value : '5000';
            const downloadUrl = `/api/export/ai-dataset?type=${activeDatasetType}&format=${format}&mode=${mode}&limit=${limit}`;
            
            toast(`Generating ${activeDatasetType} dataset…`, 'fa-cloud-arrow-down', '#6366f1');
            const link = document.createElement('a');
            link.href = downloadUrl;
            link.setAttribute('download', '');
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            setTimeout(() => toast('AI Dataset downloaded successfully!', 'fa-circle-check', '#10b981'), 1200);
        });
    }

    // Copy API URL button
    const btnCopy = document.getElementById('btnCopyDatasetAPI');
    if (btnCopy) {
        btnCopy.addEventListener('click', () => {
            const format = selFmt ? selFmt.value : 'csv';
            const mode = selMode ? selMode.value : 'clean';
            const limit = selLimit ? selLimit.value : '5000';
            const fullUrl = `${location.protocol}//${location.host}/api/export/ai-dataset?type=${activeDatasetType}&format=${format}&mode=${mode}&limit=${limit}`;
            navigator.clipboard.writeText(fullUrl).then(() => {
                toast('API URL copied to clipboard!', 'fa-copy', '#34d399');
            }).catch(() => {
                prompt('Copy dataset API URL:', fullUrl);
            });
        });
    }
}

async function fetchExportSchema() {
    const tbody = document.getElementById('schemaTableBody');
    const descEl = document.getElementById('schemaDatasetDesc');
    if (!tbody) return;
    try {
        const data = await fetch('/api/export/schema').then(r => r.json());
        const dsInfo = data.datasets && data.datasets[activeDatasetType];
        if (!dsInfo) return;
        if (descEl) descEl.textContent = dsInfo.description;

        tbody.innerHTML = dsInfo.attributes.map(attr => `
            <tr>
                <td style="font-family:var(--f-mono);font-weight:700;color:var(--tx-1)">${escapeHtml(attr.name)}</td>
                <td style="font-family:var(--f-mono);font-size:11px;color:var(--tx-code)">${escapeHtml(attr.type)}</td>
                <td><span class="role-badge ${escapeHtml(attr.role)}">${escapeHtml(attr.role)}</span></td>
                <td style="color:var(--tx-2);font-size:12px">${escapeHtml(attr.description)}</td>
            </tr>
        `).join('');
    } catch(e) {
        tbody.innerHTML = '<tr><td colspan="4" class="loading-cell">Failed to load feature schema.</td></tr>';
    }
}

async function fetchExportPreview() {
    const container = document.getElementById('previewTableContainer');
    if (!container) return;
    const mode = document.getElementById('exportModeSelect')?.value || 'clean';

    container.innerHTML = '<div class="loading-cell"><i class="fa-solid fa-spinner fa-spin"></i> Generating preview sample…</div>';

    try {
        const rows = await fetch(`/api/export/ai-dataset?type=${activeDatasetType}&format=json&limit=5&mode=${mode}`).then(r => r.json());
        if (!rows || !rows.length) {
            container.innerHTML = '<div class="loading-cell">No data rows recorded yet.</div>';
            return;
        }

        const headers = Object.keys(rows[0]);
        const theadHtml = headers.map(h => `<th>${escapeHtml(h)}</th>`).join('');
        const tbodyHtml = rows.map(row => {
            const cells = headers.map(h => `<td style="font-family:var(--f-mono);font-size:11px">${escapeHtml(row[h])}</td>`).join('');
            return `<tr>${cells}</tr>`;
        }).join('');

        container.innerHTML = `
            <table class="log-table mini" style="white-space:nowrap">
                <thead><tr>${theadHtml}</tr></thead>
                <tbody>${tbodyHtml}</tbody>
            </table>
        `;
    } catch(e) {
        container.innerHTML = '<div class="loading-cell">Failed to load preview sample.</div>';
    }
}

/* ─── Latency Monitor ───────────────────────── */
const LATENCY_COLORS = ['#6366f1','#06b6d4','#10b981','#f59e0b','#f43f5e','#a855f7'];
async function fetchLatency() {
    try {
        const data = await fetch('/api/latency').then(r=>r.json());
        const grid = document.getElementById('latencyTargetsGrid');
        if (!data || Object.keys(data).length === 0) {
            grid.innerHTML = '<div class="latency-loading"><i class="fa-solid fa-spinner fa-spin"></i> Collecting first measurements…</div>';
            return;
        }

        // Update target chips
        grid.innerHTML = Object.entries(data).map(([label, pts]) => {
            const last = pts[pts.length-1];
            if (!last) return '';
            const cls = last.ms === -1 ? 'down' : last.ms > 300 ? 'slow' : 'ok';
            const msStr = last.ms === -1 ? 'DOWN' : `${last.ms}ms`;
            return `<div class="lat-chip ${cls}"><span class="lat-dot ${cls}"></span><span>${label}</span><strong>${msStr}</strong></div>`;
        }).join('');

        // Update latency chart
        const labels = Object.keys(data);
        const allTimes = new Set();
        labels.forEach(l => data[l].forEach(p => allTimes.add(p.time)));
        const sortedTimes = [...allTimes].sort().slice(-20);

        latencyChart.data.labels = sortedTimes;
        latencyChart.data.datasets = labels.map((label, i) => {
            const pointMap = {};
            data[label].forEach(p => { pointMap[p.time] = p.ms === -1 ? null : p.ms; });
            return {
                label, data: sortedTimes.map(t => pointMap[t] ?? null),
                borderColor: LATENCY_COLORS[i % LATENCY_COLORS.length],
                backgroundColor: 'transparent',
                tension: .4, pointRadius: 2, borderWidth: 2, spanGaps: false
            };
        });
        latencyChart.update('none');
    } catch(e) { console.warn('Latency error',e); }
}

/* ─── Latency Targets Modal ─────────────────── */
async function fetchLatencyTargets() {
    try {
        const targets = await fetch('/api/latency/targets').then(r=>r.json());
        const list = document.getElementById('latencyTargetsList');
        if (!targets.length) { list.innerHTML = '<li class="empty-rules-note">No targets configured.</li>'; return; }
        list.innerHTML = targets.map(t => `
        <li>
            <div>
                <strong>${t.label}</strong>
                <div style="font-size:11px;color:var(--tx-3);margin-top:2px;font-family:var(--f-mono)">${t.host}:${t.port}</div>
            </div>
            <button class="block-btn" onclick="removeLatencyTarget(${t.id},'${t.label}')"><i class="fa-solid fa-trash"></i> Remove</button>
        </li>`).join('');
    } catch(e) {}
}

window.removeLatencyTarget = async function(id, label) {
    try {
        await fetch(`/api/latency/targets/${id}`, {method:'DELETE'});
        toast(`Target '${label}' removed`, 'fa-trash', '#f59e0b');
        fetchLatencyTargets();
    } catch(e) { toast('Remove failed','fa-circle-exclamation','#fb7185'); }
};

document.getElementById('addTargetForm').addEventListener('submit', async e => {
    e.preventDefault();
    const label = document.getElementById('targetLabelInput').value.trim();
    const host  = document.getElementById('targetHostInput').value.trim();
    const port  = parseInt(document.getElementById('targetPortInput').value)||80;
    if (!label||!host) return;
    try {
        await fetch('/api/latency/targets', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label,host,port})});
        document.getElementById('targetLabelInput').value='';
        document.getElementById('targetHostInput').value='';
        toast(`'${label}' added to latency monitor`,'fa-heartbeat','#f43f5e');
        fetchLatencyTargets();
    } catch(e) { toast('Failed to add target','fa-circle-exclamation','#fb7185'); }
});

document.getElementById('btnOpenLatencyTargets').addEventListener('click', () => {
    fetchLatencyTargets();
    document.getElementById('latencyTargetsModal').classList.add('active');
});
document.getElementById('btnCloseLatencyTargets').addEventListener('click', () =>
    document.getElementById('latencyTargetsModal').classList.remove('active'));

/* ─── Devices ─────────────────────────────────── */
async function fetchDevices() {
    try {
        const devices = await fetch(`/api/devices?mode=${currentMode}`).then(r=>r.json());
        const container = document.getElementById('devicesDeckContainer');
        const counter   = document.getElementById('devicesCounter');
        const pillsEl   = document.getElementById('deviceFilterPills');

        const online = devices.filter(d=>d.liveness==='Online').length;
        counter.textContent = `${online} Online / ${devices.length} Total`;

        // Rebuild pills
        let pillsHtml = `<button class="d-pill ${currentDeviceFilter==='All'?'active':''}" data-ip="All">🌐 All</button>`;
        devices.forEach(d => {
            const icon = d.device_type==='mobile'?'📱':d.device_type==='tablet'?'📟':'💻';
            const dot  = d.liveness==='Online'?'🟢':d.liveness==='Idle'?'🟡':'⚪';
            pillsHtml += `<button class="d-pill ${currentDeviceFilter===d.ip?'active':''}" data-ip="${d.ip}">${dot}${icon} ${d.name}</button>`;
        });
        pillsEl.innerHTML = pillsHtml;
        pillsEl.querySelectorAll('.d-pill').forEach(btn => btn.addEventListener('click', () => {
            pillsEl.querySelectorAll('.d-pill').forEach(b=>b.classList.remove('active'));
            btn.classList.add('active');
            currentDeviceFilter = btn.dataset.ip;
            fetchLogs();
        }));

        // Populate quota device select
        const sel = document.getElementById('quotaDeviceSelect');
        if (sel) {
            const prev = sel.value;
            sel.innerHTML = '<option value="">— Select Device —</option>' +
                devices.map(d => `<option value="${d.ip}">${d.name} (${d.ip})</option>`).join('');
            if (prev) sel.value = prev;
        }

        if (!devices.length) {
            container.innerHTML = `<div class="empty-state"><div class="empty-icon"><i class="fa-solid fa-plug-circle-xmark"></i></div><h3>No Devices Connected</h3><p>Connect your phone to the PC Hotspot and configure proxy <code>192.168.137.1:8080</code></p><button class="btn-setup-link" onclick="document.getElementById('guideModal').classList.add('active')"><i class="fa-solid fa-bolt"></i> Quick Setup Guide</button></div>`;
            return;
        }

        container.innerHTML = devices.map(d => {
            const ico  = deviceIcon(d.device_type);
            const badge = livenessBadge(d.liveness, d.seconds_ago);
            const chips = d.top_domains && d.top_domains.length
                ? d.top_domains.slice(0,4).map(s=>`<span class="s-chip">${s.domain} <small style="opacity:.6">(${s.count})</small></span>`).join('')
                : '<span class="s-chip" style="opacity:.45">No sites yet</span>';

            // Quota bar
            let quotaHtml = '';
            if (d.quota_mb > 0) {
                const pct = Math.min((d.used_mb / d.quota_mb) * 100, 100);
                const cls = pct >= 100 ? 'over' : '';
                quotaHtml = `<div class="tile-quota-wrap"><div class="tile-quota-label"><span><i class="fa-solid fa-gauge-high"></i> Daily Quota</span><span>${d.used_mb.toFixed(1)} / ${d.quota_mb} MB</span></div><div class="tile-quota-track"><div class="tile-quota-fill ${cls}" style="width:${pct}%"></div></div></div>`;
            }

            return `<div class="device-tile" onclick="openDeviceModal('${d.ip}')">
                <div class="tile-top">
                    <div class="tile-avatar-group">
                        <div class="tile-icon"><i class="fa-solid ${ico}"></i></div>
                        <div><div class="tile-name">${d.name}</div><div class="tile-ip">${d.ip}</div></div>
                    </div>
                    <div style="display:flex;align-items:center;gap:6px">
                        ${badge}
                        <button class="rename-mini-btn" onclick="event.stopPropagation();openRenameModal('${d.ip}','${d.name}')" title="Rename"><i class="fa-solid fa-pen"></i></button>
                    </div>
                </div>
                <div class="tile-stats">
                    <div><span class="tile-stat-label">WEBSITE VISITS</span><div class="tile-stat-val">${d.total_requests.toLocaleString()}</div></div>
                    <div><span class="tile-stat-label">DATA CONSUMED</span><div class="tile-stat-val">${formatBytes(d.total_bytes)}</div></div>
                </div>
                ${quotaHtml}
                <div><span class="tile-sites-label">VISITED WEBSITES</span><div class="tile-site-chips">${chips}</div></div>
                <div class="tile-footer">
                    <span class="tile-last-seen">Last: ${formatRelTime(d.seconds_ago)}</span>
                    <button class="inspect-btn" onclick="event.stopPropagation();openDeviceModal('${d.ip}')"><i class="fa-solid fa-magnifying-glass-chart"></i> Inspect</button>
                </div>
            </div>`;
        }).join('');
    } catch(e) { console.warn('Devices error',e); }
}

/* ─── Logs ───────────────────────────────────── */
async function fetchLogs() {
    try {
        const cat    = document.getElementById('categoryFilter').value;
        const status = document.getElementById('statusFilter').value;
        const search = document.getElementById('logSearch').value;
        const df     = document.getElementById('filterDateFrom').value;
        const dt     = document.getElementById('filterDateTo').value;
        let url = `/api/logs?limit=100&mode=${currentMode}`;
        if (cat && cat!=='All') url += `&category=${encodeURIComponent(cat)}`;
        if (status && status!=='All') url += `&status=${encodeURIComponent(status)}`;
        if (currentDeviceFilter && currentDeviceFilter!=='All') url += `&client_ip=${encodeURIComponent(currentDeviceFilter)}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        if (df) url += `&date_from=${df}`;
        if (dt) url += `&date_to=${dt}`;
        const logs = await fetch(url).then(r=>r.json());
        const tbody = document.getElementById('logsTableBody');
        if (!logs || !logs.length) {
            tbody.innerHTML = '<tr class="table-empty-row"><td colspan="8"><i class="fa-solid fa-magnifying-glass"></i> No matching records.</td></tr>';
            return;
        }
        tbody.innerHTML = logs.map(l=>buildLogRow(l)).join('');
    } catch(e) { console.warn('Logs error',e); }
}

function buildLogRow(log, isNew=false) {
    const site = log.clean_site || log.domain;
    const sub  = log.domain !== site ? `<div class="cell-sub">${log.domain}</div>` : '';
    const time = (log.timestamp||'').split(' ')[1] || log.timestamp;
    return `<tr class="${isNew?'row-new':''}">
        <td class="cell-time">${time}</td>
        <td><div class="cell-device"><i class="fa-solid ${deviceIcon(log.device_type)}"></i><span>${log.device_name}</span></div></td>
        <td class="cell-ip">${log.client_ip}</td>
        <td><div class="cell-domain">${site}</div>${sub}</td>
        <td><span class="cat-pill ${catClass(log.category)}">${log.category}</span></td>
        <td>${formatBytes(log.bytes)}</td>
        <td><span class="status-pill ${log.status==='Blocked'?'blocked':'allowed'}">${log.status}</span></td>
        <td><button class="block-btn" onclick="quickBlock('${site}')"><i class="fa-solid fa-ban"></i></button></td>
    </tr>`;
}

/* ─── Device Modal ───────────────────────────── */
window.openDeviceModal = async function(ip) {
    activeModalIp = ip;
    document.getElementById('deviceModal').classList.add('active');
    switchModalTab('overview');
    try {
        const [act, allDevs] = await Promise.all([
            fetch(`/api/devices/${ip}/activity?mode=${currentMode}`).then(r=>r.json()),
            fetch(`/api/devices?mode=${currentMode}`).then(r=>r.json())
        ]);
        const dev = allDevs.find(d=>d.ip===ip)||{name:`Device (${ip})`,device_type:'mobile',seconds_ago:0,quota_mb:0,used_mb:0};
        document.getElementById('modalDevName').textContent     = dev.name;
        document.getElementById('modalDevIp').textContent       = ip;
        document.getElementById('modalDevAvatar').innerHTML     = `<i class="fa-solid ${deviceIcon(dev.device_type)}"></i>`;
        document.getElementById('modalDevRequests').textContent = act.total_requests.toLocaleString();
        document.getElementById('modalDevBandwidth').textContent= formatBytes(act.total_bytes);
        document.getElementById('modalDevTopSite').textContent  = act.top_sites && act.top_sites.length ? act.top_sites[0].domain : '—';
        document.getElementById('modalDevLastSeen').textContent = formatRelTime(dev.seconds_ago);

        // Quota bar
        const qWrap = document.getElementById('modalQuotaBar');
        if (dev.quota_mb > 0) {
            const pct = Math.min((dev.used_mb / dev.quota_mb) * 100, 100);
            const cls = pct >= 100 ? 'over' : '';
            document.getElementById('quotaBarText').textContent = `${dev.used_mb.toFixed(1)} MB / ${dev.quota_mb} MB`;
            document.getElementById('quotaBarFill').className   = `quota-bar-fill ${cls}`;
            document.getElementById('quotaBarFill').style.width = `${pct}%`;
            qWrap.style.display = 'block';
        } else { qWrap.style.display = 'none'; }

        // Top sites chips
        const chipsEl = document.getElementById('modalDevTopSitesList');
        chipsEl.innerHTML = act.top_sites && act.top_sites.length
            ? act.top_sites.map(s=>`<div class="top-chip"><strong>${s.domain}</strong><span>${s.count} visits · ${formatBytes(s.bytes)}</span></div>`).join('')
            : '<span style="color:var(--tx-3);font-size:13px">No clean sites yet</span>';

        // History tab
        const tbody = document.getElementById('modalDevLogsBody');
        tbody.innerHTML = act.logs && act.logs.length
            ? act.logs.map(l => {
                const site = l.clean_site || l.domain;
                const time = (l.timestamp||'').split(' ')[1] || l.timestamp;
                return `<tr><td class="cell-time">${time}</td><td class="cell-domain">${site}</td><td><span class="cat-pill ${catClass(l.category)}">${l.category}</span></td><td>${formatBytes(l.bytes)}</td><td><span class="status-pill ${l.status==='Blocked'?'blocked':'allowed'}">${l.status}</span></td><td><button class="block-btn" onclick="quickBlock('${site}')"><i class="fa-solid fa-ban"></i></button></td></tr>`;
              }).join('')
            : '<tr><td colspan="6" class="loading-cell">No activity records.</td></tr>';
    } catch(e) { console.warn('Modal error',e); }
};

/* ─── Sessions Tab ───────────────────────────── */
async function loadSessions(ip) {
    const container = document.getElementById('sessionsContainer');
    container.innerHTML = '<div class="loading-cell"><i class="fa-solid fa-spinner fa-spin"></i> Grouping sessions…</div>';
    try {
        const data = await fetch(`/api/sessions/${ip}?mode=${currentMode}`).then(r=>r.json());
        if (!data.sessions || !data.sessions.length) {
            container.innerHTML = '<div class="loading-cell">No sessions recorded yet.</div>';
            return;
        }
        container.innerHTML = `<div style="margin-bottom:10px;font-size:12px;color:var(--tx-3)">${data.session_count} browsing session${data.session_count!==1?'s':''} found (30-min idle = new session)</div>` +
        `<div class="sessions-list">${data.sessions.map((s,i)=>`
            <div class="session-card">
                <div>
                    <div class="session-num">SESSION ${data.session_count - i}</div>
                    <div class="session-time">${s.start.split(' ')[1]} → ${s.end.split(' ')[1]} · ${s.start.split(' ')[0]}</div>
                </div>
                <div class="session-badges">
                    <span class="session-badge"><i class="fa-solid fa-globe"></i> ${s.count} visits</span>
                    <span class="session-badge"><i class="fa-solid fa-database"></i> ${formatBytes(s.total_bytes)}</span>
                </div>
                <div class="session-sites">${s.top_sites.map(t=>`<span class="s-chip">${t.domain} (${t.count})</span>`).join('')}</div>
            </div>`).join('')}</div>`;
    } catch(e) { container.innerHTML = '<div class="loading-cell">Failed to load sessions.</div>'; }
}

/* ─── Modal Tab Switcher ─────────────────────── */
function switchModalTab(tab) {
    activeTab = tab;
    document.querySelectorAll('.modal-tab').forEach(b=>b.classList.toggle('active', b.dataset.tab===tab));
    document.querySelectorAll('.modal-tab-content').forEach(c=>c.classList.toggle('active', c.id===`tab-${tab}`));
    if (tab==='sessions' && activeModalIp) loadSessions(activeModalIp);
}
document.querySelectorAll('.modal-tab').forEach(btn => btn.addEventListener('click', ()=>switchModalTab(btn.dataset.tab)));

/* ─── Rename Modal ───────────────────────────── */
window.openRenameModal = function(ip, name) { activeModalIp=ip; document.getElementById('renameInput').value=name||''; document.getElementById('renameModal').classList.add('active'); };
document.getElementById('btnSaveRename').addEventListener('click', async () => {
    const name = document.getElementById('renameInput').value.trim();
    if (!name||!activeModalIp) return;
    try {
        await fetch(`/api/devices/${activeModalIp}/rename`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
        document.getElementById('renameModal').classList.remove('active');
        toast(`Renamed to "${name}"`, 'fa-pen', '#818cf8');
        fetchDevices(); fetchLogs();
    } catch(e) { toast('Rename failed','fa-circle-exclamation','#fb7185'); }
});
document.getElementById('btnCancelRename').addEventListener('click', ()=>document.getElementById('renameModal').classList.remove('active'));
document.getElementById('btnCloseRenameModal').addEventListener('click', ()=>document.getElementById('renameModal').classList.remove('active'));
document.getElementById('btnModalRename').addEventListener('click', ()=>{
    if (activeModalIp) openRenameModal(activeModalIp, document.getElementById('modalDevName').textContent);
});

/* ─── Quick Block ─────────────────────────────── */
window.quickBlock = async function(domain) {
    if (!confirm(`Block '${domain}' across the entire network?`)) return;
    try {
        const r = await fetch('/api/policy/block',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain,reason:'Quick blocked from live feed'})});
        const d = await r.json();
        toast(d.message||`${domain} blocked`,'fa-ban','#fb7185');
        sendNotification('Domain Blocked', `${domain} has been restricted.`, '🚫');
        fetchRules(); fetchLogs();
    } catch(e) { toast('Block failed','fa-circle-exclamation','#fb7185'); }
};

/* ─── Policy ──────────────────────────────────── */
async function fetchRules() {
    try {
        const rules = await fetch('/api/policy/rules').then(r=>r.json());
        const list = document.getElementById('rulesList');
        if (!rules||!rules.length) { list.innerHTML='<li class="empty-rules-note">No block rules configured yet.</li>'; return; }
        list.innerHTML = rules.map(r=>`
        <li><div><strong>${r.domain}</strong><div style="font-size:11px;color:var(--tx-3);margin-top:3px">${r.reason||'Restricted'} · ${r.created_at}</div></div>
        <button class="block-btn" onclick="unblockRule('${r.domain}')"><i class="fa-solid fa-trash"></i></button></li>`).join('');
    } catch(e) {}
}
window.unblockRule = async function(domain) {
    try {
        await fetch('/api/policy/unblock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain})});
        toast(`${domain} unblocked`,'fa-shield-check','#34d399');
        fetchRules(); fetchLogs();
    } catch(e) {}
};
document.getElementById('addBlockForm').addEventListener('submit', async e=>{
    e.preventDefault();
    const domain = document.getElementById('blockDomainInput').value.trim();
    const reason = document.getElementById('blockReasonInput').value.trim();
    if (!domain) return;
    try {
        await fetch('/api/policy/block',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain,reason:reason||'Policy Restriction'})});
        document.getElementById('blockDomainInput').value='';
        document.getElementById('blockReasonInput').value='';
        toast(`${domain} blocked`,'fa-ban','#fb7185');
        fetchRules();
    } catch(e) { toast('Block failed','fa-circle-exclamation','#fb7185'); }
});

/* ─── Quota Management ───────────────────────── */
async function fetchQuotas() {
    try {
        const quotas = await fetch('/api/quota').then(r=>r.json());
        const list = document.getElementById('quotaList');
        if (!quotas||!quotas.length) { list.innerHTML='<div class="loading-cell" style="padding:14px 0">No quotas configured.</div>'; return; }
        list.innerHTML = quotas.map(q=>`
        <div class="quota-item">
            <div class="quota-item-header">
                <div><div class="quota-item-name">${q.ip}</div><div class="quota-item-ip">${q.daily_mb_limit} MB / day</div></div>
                <button class="block-btn" onclick="removeQuota('${q.ip}')"><i class="fa-solid fa-trash"></i> Remove</button>
            </div>
            <div class="quota-item-bar"><div class="quota-item-fill ${q.pct>=100?'over':''}" style="width:${Math.min(q.pct,100)}%"></div></div>
            <div class="quota-item-meta"><span>${q.used_mb.toFixed(1)} MB used</span><span>${q.pct}% of limit</span></div>
        </div>`).join('');
    } catch(e) {}
}
window.removeQuota = async function(ip) {
    try {
        await fetch(`/api/quota/${ip}`,{method:'DELETE'});
        toast(`Quota removed for ${ip}`,'fa-trash','#f59e0b');
        fetchQuotas();
    } catch(e) {}
};
document.getElementById('addQuotaForm').addEventListener('submit', async e=>{
    e.preventDefault();
    const ip = document.getElementById('quotaDeviceSelect').value;
    const mb = parseInt(document.getElementById('quotaMBInput').value);
    if (!ip||!mb||mb<=0) { toast('Select a device and enter MB limit','fa-circle-exclamation','#f59e0b'); return; }
    try {
        await fetch('/api/quota/set',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip,daily_mb_limit:mb})});
        document.getElementById('quotaMBInput').value='';
        toast(`${mb} MB/day quota set for ${ip}`,'fa-gauge-high','#f59e0b');
        fetchQuotas(); fetchDevices();
    } catch(e) { toast('Failed to set quota','fa-circle-exclamation','#fb7185'); }
});

/* ─── Report Download ────────────────────────── */
document.getElementById('btnDownloadReport').addEventListener('click', async ()=>{
    const df = document.getElementById('filterDateFrom').value;
    const dt = document.getElementById('filterDateTo').value;
    let url = `/api/report?mode=${currentMode}`;
    if (df) url += `&date_from=${df}`;
    if (dt) url += `&date_to=${dt}`;
    try {
        const r = await fetch(url);
        const html = await r.text();
        const blob = new Blob([html], {type:'text/html'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `netpulse_report_${new Date().toISOString().slice(0,10)}.html`;
        a.click();
        toast('Audit report downloaded!','fa-file-lines','#10b981');
    } catch(e) { toast('Report generation failed','fa-circle-exclamation','#fb7185'); }
});

/* ─── CSV / AI Dataset Export ─────────────────────────── */
document.getElementById('btnExportCSV').addEventListener('click', ()=>{
    const aiTabBtn = document.querySelector('.tab-nav-btn[data-tab="tabAIExport"]');
    if (aiTabBtn) {
        aiTabBtn.click();
        const exportCard = document.querySelector('.ai-export-card');
        if (exportCard) exportCard.scrollIntoView({ behavior: 'smooth' });
        toast('Opened AI Analytics & Dataset Export Studio', 'fa-brain', '#6366f1');
    }
});

/* ─── Clear Logs ─────────────────────────────── */
document.getElementById('btnClearLogs').addEventListener('click', async ()=>{
    if (!confirm('Wipe all activity logs and device records?')) return;
    try {
        await fetch('/api/logs/clear',{method:'POST'});
        toast('All logs cleared','fa-trash-can','#f59e0b');
        fetchStats(); fetchDevices(); fetchLogs();
    } catch(e) {}
});

/* ─── Mode Switcher ──────────────────────────── */
document.getElementById('btnModeClean').addEventListener('click', ()=>{
    currentMode='clean';
    document.getElementById('btnModeClean').classList.add('active');
    document.getElementById('btnModeRaw').classList.remove('active');
    fetchStats(); fetchDevices(); fetchLogs();
});
document.getElementById('btnModeRaw').addEventListener('click', ()=>{
    currentMode='raw';
    document.getElementById('btnModeRaw').classList.add('active');
    document.getElementById('btnModeClean').classList.remove('active');
    fetchStats(); fetchDevices(); fetchLogs();
});

/* ─── Date Range ─────────────────────────────── */
document.getElementById('filterDateFrom').addEventListener('change', ()=>{ fetchStats(); fetchLogs(); });
document.getElementById('filterDateTo').addEventListener('change',   ()=>{ fetchStats(); fetchLogs(); });
document.getElementById('btnClearDates').addEventListener('click', ()=>{
    document.getElementById('filterDateFrom').value='';
    document.getElementById('filterDateTo').value='';
    fetchStats(); fetchLogs();
    toast('Date filter cleared','fa-xmark','#94a3b8');
});

/* ─── Gateway Copy ───────────────────────────── */
document.getElementById('gatewayBox').addEventListener('click', ()=>{
    navigator.clipboard.writeText('192.168.137.1:8080').catch(()=>{});
    toast('Proxy address copied!','fa-copy','#06b6d4');
});

/* ─── Modals ──────────────────────────────────── */
document.getElementById('btnOpenGuide').addEventListener('click',  ()=>document.getElementById('guideModal').classList.add('active'));
document.getElementById('btnCloseGuide').addEventListener('click', ()=>document.getElementById('guideModal').classList.remove('active'));
document.getElementById('btnGotIt').addEventListener('click',      ()=>document.getElementById('guideModal').classList.remove('active'));
document.getElementById('btnOpenPolicy').addEventListener('click',  ()=>{ fetchRules(); document.getElementById('policyModal').classList.add('active'); });
document.getElementById('btnClosePolicy').addEventListener('click', ()=>document.getElementById('policyModal').classList.remove('active'));
document.getElementById('btnCloseDeviceModal').addEventListener('click', ()=>document.getElementById('deviceModal').classList.remove('active'));
document.getElementById('btnOpenQuota').addEventListener('click',   ()=>{ fetchQuotas(); document.getElementById('quotaModal').classList.add('active'); });
document.getElementById('btnCloseQuota').addEventListener('click',  ()=>document.getElementById('quotaModal').classList.remove('active'));
document.querySelectorAll('.modal-bg').forEach(m=>m.addEventListener('click', e=>{ if (e.target===m) m.classList.remove('active'); }));

/* ─── Filters ─────────────────────────────────── */
document.getElementById('categoryFilter').addEventListener('change', fetchLogs);
document.getElementById('statusFilter').addEventListener('change', fetchLogs);
document.getElementById('logSearch').addEventListener('input', ()=>{ clearTimeout(window._st); window._st=setTimeout(fetchLogs,280); });
document.getElementById('btnRefreshDevices').addEventListener('click', fetchDevices);

/* ─── WebSocket ───────────────────────────────── */
function connectWS() {
    const proto = location.protocol==='https:'?'wss:':'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onopen = ()=>{
        const el=document.getElementById('wsStatus');
        el.innerHTML='<span class="ws-dot"></span><span class="ws-text">Live</span>';
        el.style.cssText='background:rgba(16,185,129,0.12);color:#34d399;border-color:rgba(16,185,129,0.3)';
    };
    ws.onmessage = e=>{
        try {
            const msg=JSON.parse(e.data);
            if (msg.type === 'ATTENDANCE_RECORDED') {
                fetchAttendance();
                fetchAttendanceStats();
                fetchConnectedDevices();
                toast(`🎓 Auto-Attendance: ${msg.student_name || 'Student'} checked in (${msg.time?.split(' ')[1] || 'now'})!`, 'fa-user-check', '#10b981');
                return;
            }
            if (msg.type === 'DEVICE_CONNECTED') {
                fetchConnectedDevices();
                fetchAttendanceStats();
                return;
            }
            if (msg.type!=='NEW_LOG') return;
            const log=msg.data;
            if (currentMode==='clean' && log.is_background) return;

            // Browser notification for blocked sites
            if (log.status==='Blocked') sendNotification('Site Blocked', `${log.device_name} tried to access ${log.clean_site||log.domain}`, '🚫');

            if (currentDeviceFilter==='All' || currentDeviceFilter===log.client_ip) {
                const tbody=document.getElementById('logsTableBody');
                if (tbody.querySelector('.table-empty-row')) tbody.innerHTML='';
                const tmp=document.createElement('tbody');
                tmp.innerHTML=buildLogRow(log,true);
                if (tmp.firstElementChild) { tbody.insertBefore(tmp.firstElementChild, tbody.firstChild); if (tbody.children.length>100) tbody.removeChild(tbody.lastChild); }
            }
            const time=(log.timestamp||'').split(' ')[1]||'';
            if (timelineChart.data.labels.length>=25) { timelineChart.data.labels.shift(); timelineChart.data.datasets[0].data.shift(); }
            const prev=timelineChart.data.datasets[0].data.slice(-1)[0]||0;
            timelineChart.data.labels.push(time);
            timelineChart.data.datasets[0].data.push(prev+1);
            timelineChart.update('none');
        } catch(e) {}
    };
    ws.onclose = ()=>{
        const el=document.getElementById('wsStatus');
        el.innerHTML='<span class="ws-text">Reconnecting…</span>';
        el.style.cssText='background:rgba(100,116,139,0.12);color:#94a3b8;border-color:rgba(100,116,139,0.2)';
        setTimeout(connectWS,3000);
    };
}

/* ─── Student Registration Modal & Attendance Hooks ────────── */
function initStudentModal() {
    const btnOpen = document.getElementById('btnOpenStudentModal');
    const modal = document.getElementById('studentModal');
    const btnClose = document.getElementById('btnCloseStudentModal');
    const btnCancel = document.getElementById('btnCancelStudentModal');
    const form = document.getElementById('studentRegistrationForm');
    const selDevice = document.getElementById('regDeviceSelect');
    const inpMac = document.getElementById('regMac');

    if (btnOpen && modal) btnOpen.addEventListener('click', () => { fetchConnectedDevices(); modal.classList.add('active'); });
    if (btnClose && modal) btnClose.addEventListener('click', () => modal.classList.remove('active'));
    if (btnCancel && modal) btnCancel.addEventListener('click', () => modal.classList.remove('active'));

    if (selDevice && inpMac) {
        selDevice.addEventListener('change', () => {
            if (selDevice.value) inpMac.value = selDevice.value;
        });
    }

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btnSubmit = form.querySelector('button[type="submit"]');
            btnSubmit.disabled = true;
            try {
                const res = await fetch('/api/students', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        prn: document.getElementById('regPrn').value.trim(),
                        name: document.getElementById('regName').value.trim(),
                        batch: document.getElementById('regBatch').value.trim(),
                        mac_address: inpMac.value.trim()
                    })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to register student');
                
                toast(data.message || 'Student registered & attendance updated!', 'fa-user-check', '#10b981');
                form.reset();
                modal.classList.remove('active');
                fetchAttendance();
                fetchAttendanceStats();
                fetchConnectedDevices();
            } catch(err) {
                toast(err.message, 'fa-circle-exclamation', '#fb7185');
            } finally {
                btnSubmit.disabled = false;
            }
        });
    }

    // Attendance Filter Controls
    const dateInp = document.getElementById('attendanceDate');
    const batchSel = document.getElementById('attendanceBatchFilter');
    const searchInp = document.getElementById('attendanceSearchInput');
    const btnToday = document.getElementById('btnTodayAttendance');
    const btnRefAtt = document.getElementById('btnRefreshAttendance');
    const btnRefRadar = document.getElementById('btnRefreshRadar');
    const btnExpAtt = document.getElementById('btnExportAttendanceCSV');

    if (dateInp) dateInp.addEventListener('change', () => { fetchAttendance(); fetchAttendanceStats(); });
    if (batchSel) batchSel.addEventListener('change', fetchAttendance);
    if (searchInp) searchInp.addEventListener('input', () => {
        clearTimeout(window._attSearchTimer);
        window._attSearchTimer = setTimeout(fetchAttendance, 250);
    });
    if (btnToday && dateInp) {
        btnToday.addEventListener('click', () => {
            const today = new Date();
            dateInp.value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
            fetchAttendance();
            fetchAttendanceStats();
        });
    }
    if (btnRefAtt) btnRefAtt.addEventListener('click', () => { fetchAttendance(); fetchAttendanceStats(); });
    if (btnRefRadar) btnRefRadar.addEventListener('click', fetchConnectedDevices);
    if (btnExpAtt) {
        btnExpAtt.addEventListener('click', () => {
            const dateVal = dateInp ? dateInp.value : '';
            toast('Downloading Attendance CSV…', 'fa-file-csv', '#10b981');
            const link = document.createElement('a');
            link.href = `/api/export/ai-dataset?type=attendance_ml&format=csv`;
            link.setAttribute('download', '');
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        });
    }
}

/* ─── Bootstrap ───────────────────────────────── */
document.addEventListener('DOMContentLoaded', ()=>{
    initCharts();
    initNavigationTabs();
    initStudentModal();
    initAIExportStudio();
    requestNotificationPerm();
    fetchStats();
    fetchDevices();
    fetchLogs();
    fetchBandwidthTrend();
    fetchAIAnalysis();

    const attendanceDate = document.getElementById('attendanceDate');
    const today = new Date();
    if (attendanceDate) {
        attendanceDate.value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
    }
    fetchAttendance();
    fetchAttendanceStats();
    fetchConnectedDevices();
    fetchLatency();
    connectWS();

    // Auto-refresh loops
    setInterval(()=>{ fetchStats(); fetchDevices(); }, 4000);
    setInterval(fetchConnectedDevices, 7000);
    setInterval(fetchAttendanceStats, 10000);
    setInterval(fetchAttendance, 30000);
    setInterval(fetchAIAnalysis, 30000);
    setInterval(fetchBandwidthTrend, 60000);
    setInterval(fetchLatency, 35000);
});
