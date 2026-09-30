import os
import sys
import time
import threading
import sqlite3
import socket
import json
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engine import engine, DB_PATH

app = FastAPI(title="NetPulse — Cyber NOC 2.0", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# ─── In-memory latency history ────────────────────────────────
latency_history: dict = {}   # {label: [{time, ms, status}]}
LATENCY_MAX_POINTS = 60

# ─── Latency Monitor Background Thread ───────────────────────
def measure_latency_once(label: str, host: str, port: int) -> int:
    """Returns round-trip ms to host:port via TCP connect. -1 = error."""
    try:
        start = time.time()
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        return int((time.time() - start) * 1000)
    except Exception:
        return -1

def latency_monitor_loop():
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT label, host, port FROM latency_targets WHERE enabled = 1")
            targets = c.fetchall()
            conn.close()
        except Exception:
            targets = []

        for label, host, port in targets:
            ms = measure_latency_once(label, host, port)
            ts = datetime.now().strftime("%H:%M:%S")
            status = "ok" if ms != -1 and ms < 300 else ("slow" if ms != -1 else "down")
            point = {"time": ts, "ms": ms, "status": status}

            if label not in latency_history:
                latency_history[label] = []
            latency_history[label].append(point)
            if len(latency_history[label]) > LATENCY_MAX_POINTS:
                latency_history[label] = latency_history[label][-LATENCY_MAX_POINTS:]

        time.sleep(30)

@app.on_event("startup")
def startup_event():
    # Start proxy engine
    t1 = threading.Thread(target=engine.start, daemon=True)
    t1.start()
    # Start latency monitor
    t2 = threading.Thread(target=latency_monitor_loop, daemon=True)
    t2.start()
    print("✨ NetPulse v4.0 Active — http://localhost:5000")

# ─── Pydantic Models ──────────────────────────────────────────
class BlockRequest(BaseModel):
    domain: str
    reason: Optional[str] = "Restricted domain"

class RenameRequest(BaseModel):
    name: str

class QuotaRequest(BaseModel):
    ip: str
    daily_mb_limit: int

class LatencyTargetRequest(BaseModel):
    label: str
    host: str
    port: int = 80

# ─── Helpers ──────────────────────────────────────────────────
def calculate_device_liveness(last_seen_str):
    if not last_seen_str:
        return "Disconnected", 999999
    try:
        last_dt = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")
        diff = max(int((datetime.now() - last_dt).total_seconds()), 0)
        if diff <= 60:   return "Online", diff
        if diff <= 300:  return "Idle", diff
        return "Disconnected", diff
    except Exception:
        return "Disconnected", 999999

def group_logs_into_sessions(logs, gap_minutes=30):
    """Group a time-sorted list of log dicts into sessions."""
    if not logs:
        return []
    sessions = []
    current = [logs[0]]
    for log in logs[1:]:
        try:
            prev_t = datetime.strptime(current[-1]["timestamp"], "%Y-%m-%d %H:%M:%S")
            curr_t = datetime.strptime(log["timestamp"],          "%Y-%m-%d %H:%M:%S")
            if (curr_t - prev_t).total_seconds() > gap_minutes * 60:
                sessions.append(current)
                current = [log]
            else:
                current.append(log)
        except Exception:
            current.append(log)
    sessions.append(current)
    result = []
    for s in sessions:
        sites = {}
        total_bytes = 0
        for l in s:
            d = l.get("clean_site") or l.get("domain", "")
            sites[d] = sites.get(d, 0) + 1
            total_bytes += l.get("bytes", 0)
        top_sites = sorted(sites.items(), key=lambda x: -x[1])[:5]
        result.append({
            "start": s[0]["timestamp"],
            "end":   s[-1]["timestamp"],
            "count": len(s),
            "total_bytes": total_bytes,
            "top_sites": [{"domain": k, "count": v} for k, v in top_sites],
        })
    return list(reversed(result))

# ─── Basic Routes ──────────────────────────────────────────────
@app.get("/")
def get_index():
    idx = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(idx) if os.path.exists(idx) else HTMLResponse("<h1>Starting…</h1>")

# ─── Stats ────────────────────────────────────────────────────
@app.get("/api/stats")
def get_stats(mode: str = "clean", date_from: Optional[str] = None, date_to: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    conditions = []
    params: list = []
    if mode == "clean":
        conditions.append("is_background = 0")
    if date_from:
        conditions.append("timestamp >= ?"); params.append(f"{date_from} 00:00:00")
    if date_to:
        conditions.append("timestamp <= ?"); params.append(f"{date_to} 23:59:59")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    c.execute(f"SELECT COUNT(*), COALESCE(SUM(bytes_transferred),0) FROM access_logs {where}", params)
    row = c.fetchone(); total_requests = row[0] or 0; total_bytes = row[1] or 0

    c.execute("SELECT COUNT(*) FROM access_logs WHERE status='Blocked'")
    total_blocked = c.fetchone()[0] or 0

    c.execute(f"SELECT category, COUNT(*) FROM access_logs {where} GROUP BY category ORDER BY COUNT(*) DESC", params)
    categories = {r[0]: r[1] for r in c.fetchall()}

    site_col = "clean_site" if mode == "clean" else "domain"
    c.execute(f"SELECT {site_col}, COUNT(*), COALESCE(SUM(bytes_transferred),0) FROM access_logs {where} GROUP BY {site_col} ORDER BY COUNT(*) DESC LIMIT 10", params)
    top_domains = [{"domain": r[0], "count": r[1], "bytes": r[2]} for r in c.fetchall()]

    c.execute("SELECT ip, last_seen FROM devices")
    rows = c.fetchall()
    online = sum(1 for r in rows if calculate_device_liveness(r[1])[0] == "Online")
    conn.close()

    return {
        "total_requests": total_requests,
        "total_bytes": total_bytes,
        "total_blocked": total_blocked,
        "active_devices": online,
        "total_devices": len(rows),
        "categories": categories,
        "top_domains": top_domains,
    }

# ─── Devices ──────────────────────────────────────────────────
@app.get("/api/devices")
def get_devices(mode: str = "clean"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT ip, custom_name, auto_name, device_type, first_seen, last_seen FROM devices ORDER BY last_seen DESC")
    device_rows = c.fetchall()

    bg_filter = "AND is_background = 0" if mode == "clean" else ""
    site_col  = "clean_site" if mode == "clean" else "domain"
    devices_list = []

    for ip, custom_name, auto_name, device_type, first_seen, last_seen in device_rows:
        c.execute(f"""
            SELECT COUNT(*), COALESCE(SUM(bytes_transferred),0),
                   SUM(CASE WHEN status='Blocked' THEN 1 ELSE 0 END),
                   MAX(timestamp)
            FROM access_logs WHERE client_ip=? {bg_filter}
        """, (ip,))
        st = c.fetchone()
        dev_req = st[0] or 0; dev_bytes = st[1] or 0
        dev_blocked = st[2] or 0; latest_ts = st[3] or last_seen

        liveness, seconds_ago = calculate_device_liveness(latest_ts)

        c.execute(f"""
            SELECT {site_col}, COUNT(*), COALESCE(SUM(bytes_transferred),0)
            FROM access_logs WHERE client_ip=? {bg_filter}
            GROUP BY {site_col} ORDER BY COUNT(*) DESC LIMIT 4
        """, (ip,))
        top_domains = [{"domain": r[0], "count": r[1], "bytes": r[2]} for r in c.fetchall()]

        c.execute(f"SELECT category, COUNT(*) FROM access_logs WHERE client_ip=? {bg_filter} GROUP BY category", (ip,))
        cat_breakdown = {r[0]: r[1] for r in c.fetchall()}

        # Quota info
        c.execute("SELECT daily_mb_limit FROM device_quotas WHERE ip=? AND enabled=1", (ip,))
        qrow = c.fetchone()
        quota_mb = qrow[0] if qrow else 0
        used_mb = engine.get_daily_usage_mb(ip) if quota_mb > 0 else 0

        devices_list.append({
            "ip": ip,
            "name": custom_name or auto_name,
            "device_type": device_type or "mobile",
            "first_seen": first_seen,
            "last_seen": latest_ts,
            "liveness": liveness,
            "seconds_ago": seconds_ago,
            "total_requests": dev_req,
            "total_bytes": dev_bytes,
            "blocked_count": dev_blocked,
            "top_domains": top_domains,
            "categories": cat_breakdown,
            "quota_mb": quota_mb,
            "used_mb": round(used_mb, 2),
        })
    conn.close()
    return devices_list

# ─── Device Activity ──────────────────────────────────────────
@app.get("/api/devices/{ip}/activity")
def get_device_activity(ip: str, limit: int = 200, mode: str = "clean"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    bg_filter = "AND is_background=0" if mode == "clean" else ""
    site_col  = "clean_site" if mode == "clean" else "domain"

    c.execute(f"""
        SELECT id, timestamp, {site_col}, domain, category, method, bytes_transferred, status, risk_flag
        FROM access_logs WHERE client_ip=? {bg_filter} ORDER BY id DESC LIMIT ?
    """, (ip, limit))
    rows = c.fetchall()

    c.execute(f"SELECT COUNT(*), COALESCE(SUM(bytes_transferred),0), MAX(timestamp) FROM access_logs WHERE client_ip=? {bg_filter}", (ip,))
    summary = c.fetchone()

    c.execute(f"""
        SELECT {site_col}, COUNT(*), COALESCE(SUM(bytes_transferred),0)
        FROM access_logs WHERE client_ip=? {bg_filter}
        GROUP BY {site_col} ORDER BY COUNT(*) DESC LIMIT 10
    """, (ip,))
    top_sites = [{"domain": r[0], "count": r[1], "bytes": r[2]} for r in c.fetchall()]
    conn.close()

    logs = [{"id": r[0], "timestamp": r[1], "clean_site": r[2], "domain": r[3],
             "category": r[4], "method": r[5], "bytes": r[6], "status": r[7], "risk_flag": r[8]}
            for r in rows]

    return {
        "ip": ip,
        "total_requests": summary[0] or 0,
        "total_bytes": summary[1] or 0,
        "last_seen": summary[2] or "N/A",
        "top_sites": top_sites,
        "logs": logs,
    }

# ─── Sessions ─────────────────────────────────────────────────
@app.get("/api/sessions/{ip}")
def get_sessions(ip: str, mode: str = "clean"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    bg_filter = "AND is_background=0" if mode == "clean" else ""
    c.execute(f"""
        SELECT timestamp, clean_site, domain, category, bytes_transferred
        FROM access_logs WHERE client_ip=? {bg_filter}
        ORDER BY timestamp ASC
    """, (ip,))
    rows = c.fetchall()
    conn.close()

    logs = [{"timestamp": r[0], "clean_site": r[1], "domain": r[2],
             "category": r[3], "bytes": r[4] or 0} for r in rows]
    sessions = group_logs_into_sessions(logs)
    return {"ip": ip, "session_count": len(sessions), "sessions": sessions}

# ─── Device rename ────────────────────────────────────────────
@app.put("/api/devices/{ip}/rename")
def rename_device(ip: str, req: RenameRequest):
    name = req.name.strip()
    if not name: raise HTTPException(400, "Name cannot be empty")
    engine.rename_device(ip, name)
    return {"status": "ok", "message": f"Renamed to '{name}'"}

# ─── Logs ─────────────────────────────────────────────────────
@app.get("/api/logs")
def get_logs(limit: int = 100, category: Optional[str] = None,
             client_ip: Optional[str] = None, search: Optional[str] = None,
             status: Optional[str] = None, mode: str = "clean",
             date_from: Optional[str] = None, date_to: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    site_col = "clean_site" if mode == "clean" else "domain"
    query = (f"SELECT id,timestamp,client_ip,device_name,device_type,"
             f"{site_col},domain,category,method,bytes_transferred,status,risk_flag,is_background "
             f"FROM access_logs")
    conds, params = [], []
    if mode == "clean":  conds.append("is_background=0")
    if category and category != "All": conds.append("category=?"); params.append(category)
    if client_ip and client_ip != "All": conds.append("client_ip=?"); params.append(client_ip)
    if status and status != "All": conds.append("status=?"); params.append(status)
    if search:
        conds.append("(clean_site LIKE ? OR domain LIKE ? OR client_ip LIKE ? OR device_name LIKE ?)")
        p = f"%{search}%"; params += [p, p, p, p]
    if date_from: conds.append("timestamp >= ?"); params.append(f"{date_from} 00:00:00")
    if date_to:   conds.append("timestamp <= ?"); params.append(f"{date_to} 23:59:59")
    if conds: query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY id DESC LIMIT ?"; params.append(limit)
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "timestamp": r[1], "client_ip": r[2], "device_name": r[3],
             "device_type": r[4] or "mobile", "clean_site": r[5], "domain": r[6],
             "category": r[7], "method": r[8], "bytes": r[9], "status": r[10],
             "risk_flag": r[11], "is_background": bool(r[12])} for r in rows]

@app.post("/api/logs/clear")
def clear_logs():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM access_logs")
    c.execute("DELETE FROM devices")
    conn.commit(); conn.close()
    return {"status": "ok", "message": "Logs cleared"}

# ─── Blocklist / Policy ───────────────────────────────────────
@app.get("/api/policy/rules")
def get_rules():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id,domain,reason,created_at FROM blocklist ORDER BY id DESC")
    rows = c.fetchall(); conn.close()
    return [{"id": r[0], "domain": r[1], "reason": r[2], "created_at": r[3]} for r in rows]

@app.post("/api/policy/block")
def block_domain(req: BlockRequest):
    engine.add_block_rule(req.domain, req.reason or "Restricted")
    return {"status": "ok", "message": f"'{req.domain}' blocked"}

@app.post("/api/policy/unblock")
def unblock_domain(req: BlockRequest):
    engine.remove_block_rule(req.domain)
    return {"status": "ok", "message": f"'{req.domain}' unblocked"}

# ─── Quota Management ─────────────────────────────────────────
@app.get("/api/quota")
def list_quotas():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT ip, daily_mb_limit, enabled, created_at FROM device_quotas ORDER BY created_at DESC")
    rows = c.fetchall(); conn.close()
    result = []
    for ip, limit_mb, enabled, created_at in rows:
        used = round(engine.get_daily_usage_mb(ip), 2)
        pct  = round((used / limit_mb) * 100, 1) if limit_mb > 0 else 0
        result.append({"ip": ip, "daily_mb_limit": limit_mb, "enabled": bool(enabled),
                        "created_at": created_at, "used_mb": used, "pct": pct})
    return result

@app.post("/api/quota/set")
def set_quota(req: QuotaRequest):
    engine.set_quota(req.ip, req.daily_mb_limit)
    return {"status": "ok", "message": f"Quota set: {req.ip} → {req.daily_mb_limit} MB/day"}

@app.delete("/api/quota/{ip}")
def remove_quota(ip: str):
    engine.remove_quota(ip)
    return {"status": "ok", "message": f"Quota removed for {ip}"}

# ─── Latency Monitor ──────────────────────────────────────────
@app.get("/api/latency")
def get_latency():
    return latency_history

@app.get("/api/latency/targets")
def get_latency_targets():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, label, host, port, enabled FROM latency_targets ORDER BY id")
    rows = c.fetchall(); conn.close()
    return [{"id": r[0], "label": r[1], "host": r[2], "port": r[3], "enabled": bool(r[4])} for r in rows]

@app.post("/api/latency/targets")
def add_latency_target(req: LatencyTargetRequest):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO latency_targets (label, host, port, enabled) VALUES (?, ?, ?, 1)",
              (req.label, req.host, req.port))
    conn.commit(); conn.close()
    return {"status": "ok", "message": f"Target '{req.label}' added"}

@app.delete("/api/latency/targets/{target_id}")
def remove_latency_target(target_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM latency_targets WHERE id=?", (target_id,))
    conn.commit(); conn.close()
    return {"status": "ok"}

# ─── Bandwidth Trend (hourly for last 24h) ────────────────────
@app.get("/api/bandwidth/trend")
def bandwidth_trend(mode: str = "clean"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    bg_f = "AND is_background=0" if mode == "clean" else ""
    c.execute(f"""
        SELECT strftime('%H:00', timestamp) as hr,
               COALESCE(SUM(bytes_transferred), 0)
        FROM access_logs
        WHERE timestamp >= ? {bg_f}
        GROUP BY hr ORDER BY hr
    """, (since,))
    rows = c.fetchall(); conn.close()
    # Fill all 24 hours
    hours = {f"{h:02d}:00": 0 for h in range(24)}
    for hr, b in rows: hours[hr] = b
    return [{"hour": k, "bytes": v} for k, v in hours.items()]

# ─── HTML Audit Report ────────────────────────────────────────
@app.get("/api/report")
def generate_report(mode: str = "clean", date_from: Optional[str] = None, date_to: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    bg_f = "AND is_background=0" if mode == "clean" else ""
    date_conds = ""
    params_base: list = []
    if date_from:
        date_conds += " AND timestamp >= ?"; params_base.append(f"{date_from} 00:00:00")
    if date_to:
        date_conds += " AND timestamp <= ?"; params_base.append(f"{date_to} 23:59:59")

    # Overall stats
    c.execute(f"SELECT COUNT(*), COALESCE(SUM(bytes_transferred),0) FROM access_logs WHERE 1=1 {bg_f} {date_conds}", params_base)
    total_req, total_bytes = c.fetchone()
    c.execute("SELECT COUNT(*) FROM access_logs WHERE status='Blocked'")
    total_blocked = c.fetchone()[0]

    # Per-device breakdown
    c.execute(f"""
        SELECT client_ip, device_name, COUNT(*), COALESCE(SUM(bytes_transferred),0), MAX(timestamp)
        FROM access_logs WHERE 1=1 {bg_f} {date_conds}
        GROUP BY client_ip ORDER BY COUNT(*) DESC
    """, params_base)
    devices = c.fetchall()

    device_rows_html = ""
    device_detail_html = ""
    for ip, name, reqs, byt, last in devices:
        mb = byt / (1024*1024)
        site_col = "clean_site" if mode == "clean" else "domain"
        c.execute(f"""
            SELECT {site_col}, COUNT(*) FROM access_logs
            WHERE client_ip=? {bg_f} {date_conds}
            GROUP BY {site_col} ORDER BY COUNT(*) DESC LIMIT 5
        """, [ip] + params_base)
        top = c.fetchall()
        top_html = "".join(f"<li>{s[0]} ({s[1]} visits)</li>" for s in top)
        device_rows_html += f"""
        <tr>
            <td><strong>{name}</strong><br><span class="ip">{ip}</span></td>
            <td>{reqs:,}</td>
            <td>{mb:.2f} MB</td>
            <td>{last[:16] if last else '—'}</td>
        </tr>"""
        device_detail_html += f"""
        <div class="device-block">
            <h3>📱 {name} <span class="ip-tag">{ip}</span></h3>
            <p><strong>Total Visits:</strong> {reqs:,} &nbsp;|&nbsp; <strong>Data:</strong> {mb:.2f} MB</p>
            <h4>Top Visited Sites</h4>
            <ul>{top_html}</ul>
        </div>"""

    conn.close()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_range_str = ""
    if date_from or date_to:
        date_range_str = f"Period: {date_from or 'All'} → {date_to or 'Now'}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>NetPulse Audit Report — {now_str}</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; background: #f8fafc; color: #1e293b; margin: 0; padding: 0; }}
  .cover {{ background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%); color: #fff; padding: 60px 50px; }}
  .cover h1 {{ font-size: 38px; margin: 0 0 8px; letter-spacing: -1px; }}
  .cover p  {{ color: #94a3b8; font-size: 15px; margin: 4px 0; }}
  .cover .badge {{ display:inline-block; background:rgba(99,102,241,0.3); color:#a5b4fc; padding:4px 12px; border-radius:20px; font-size:12px; margin-top:14px; border:1px solid rgba(99,102,241,0.4); }}
  .content {{ max-width: 900px; margin: 0 auto; padding: 40px 30px; }}
  .kpi-row {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 18px; margin-bottom: 36px; }}
  .kpi {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 22px; text-align:center; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
  .kpi h2 {{ font-size: 36px; margin: 0; color: #6366f1; }}
  .kpi p  {{ font-size: 12px; color: #94a3b8; margin:4px 0 0; text-transform:uppercase; letter-spacing:0.8px; }}
  h2.section {{ font-size: 20px; color: #1e293b; margin: 32px 0 14px; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:12px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
  th {{ background:#f1f5f9; padding:12px 16px; text-align:left; font-size:12px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:0.6px; }}
  td {{ padding:12px 16px; border-bottom:1px solid #f1f5f9; font-size:14px; }}
  tr:last-child td {{ border-bottom:none; }}
  .ip {{ font-family:monospace; font-size:12px; color:#6366f1; }}
  .device-block {{ background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:22px 24px; margin-bottom:16px; box-shadow:0 2px 8px rgba(0,0,0,0.04); }}
  .device-block h3 {{ margin:0 0 10px; font-size:17px; color:#1e293b; }}
  .device-block h4 {{ font-size:13px; color:#64748b; margin:14px 0 6px; }}
  .device-block ul {{ margin:0; padding-left:20px; }}
  .device-block li {{ font-size:13px; color:#334155; margin:3px 0; font-family:monospace; }}
  .ip-tag {{ font-family:monospace; font-size:13px; color:#6366f1; background:#ede9fe; padding:2px 8px; border-radius:4px; margin-left:8px; }}
  footer {{ text-align:center; color:#94a3b8; font-size:12px; padding:30px; border-top:1px solid #e2e8f0; margin-top:40px; }}
  @media print {{
    body {{ background: #fff; }}
    .cover {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  }}
</style>
</head>
<body>
<div class="cover">
  <h1>🛰️ NetPulse Audit Report</h1>
  <p>Generated: {now_str}</p>
  {'<p>' + date_range_str + '</p>' if date_range_str else ''}
  <span class="badge">Campus Lab Network Intelligence · Cyber NOC 2.0</span>
</div>
<div class="content">
  <div class="kpi-row">
    <div class="kpi"><h2>{(total_req or 0):,}</h2><p>Total Website Visits</p></div>
    <div class="kpi"><h2>{(total_bytes or 0)/(1024*1024):.1f} MB</h2><p>Bandwidth Consumed</p></div>
    <div class="kpi"><h2>{total_blocked or 0}</h2><p>Policy Violations Blocked</p></div>
  </div>

  <h2 class="section">Connected Devices Summary</h2>
  <table>
    <thead><tr><th>Device</th><th>Total Visits</th><th>Data Used</th><th>Last Active</th></tr></thead>
    <tbody>{device_rows_html}</tbody>
  </table>

  <h2 class="section">Per-Device Browsing Detail</h2>
  {device_detail_html}
</div>
<footer>NetPulse Cyber NOC 2.0 · Auto-generated Report · {now_str}</footer>
</body>
</html>"""

    return Response(content=html, media_type="text/html",
                    headers={"Content-Disposition": f"attachment; filename=netpulse_report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"})

# ─── WebSocket ────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    engine.register_ws(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        engine.unregister_ws(websocket)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
