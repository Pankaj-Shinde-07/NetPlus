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

/* ─── CSV Export ─────────────────────────────── */
document.getElementById('btnExportCSV').addEventListener('click', async ()=>{
    try {
        const logs = await fetch(`/api/logs?limit=10000&mode=${currentMode}`).then(r=>r.json());
        if (!logs||!logs.length) { toast('No logs to export','fa-circle-info','#f59e0b'); return; }
        const headers = ['Time','Device','IP','Website','Category','Bytes','Status'];
        const rows = logs.map(l=>[l.timestamp,l.device_name,l.client_ip,l.clean_site||l.domain,l.category,l.bytes,l.status].map(v=>`"${v}"`).join(','));
        const a = document.createElement('a');
        a.href = 'data:text/csv;charset=utf-8,'+encodeURIComponent([headers.join(','),...rows].join('\n'));
        a.download = `netpulse_logs_${new Date().toISOString().slice(0,10)}.csv`;
        a.click();
        toast('CSV exported!','fa-download','#34d399');
    } catch(e) { toast('Export failed','fa-circle-exclamation','#fb7185'); }
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

/* ─── Bootstrap ───────────────────────────────── */
document.addEventListener('DOMContentLoaded', ()=>{
    initCharts();
    requestNotificationPerm();
    fetchStats();
    fetchDevices();
    fetchLogs();
    fetchBandwidthTrend();
    fetchLatency();
    connectWS();
    // Auto-refresh every 4s
    setInterval(()=>{ fetchStats(); fetchDevices(); }, 4000);
    // Bandwidth trend every 60s
    setInterval(fetchBandwidthTrend, 60000);
    // Latency every 35s (slightly offset from backend 30s)
    setInterval(fetchLatency, 35000);
});
