import os
import sys
import time
import threading
import sqlite3
import socket
import json
import re
import math
import csv
import io
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
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

class StudentRegistrationRequest(BaseModel):
    token: str
    prn: str
    name: str
    batch: str

class StudentAdminRegistrationRequest(BaseModel):
    mac_address: str
    prn: str
    name: str
    batch: str

class ManualCheckInRequest(BaseModel):
    prn: str
    status: Optional[str] = "Present"
    date: Optional[str] = None

class DirectStudentRegistrationRequest(BaseModel):
    mac_address: str
    prn: str
    name: str
    batch: str
    ip_address: Optional[str] = ""

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

# ─── Local AI-style traffic analysis ─────────────────────────
@app.get("/api/ai/analysis")
def get_ai_analysis(mode: str = "clean"):
    """Learn per-device hourly request baselines from local history and report anomalies."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    bg_filter = "AND is_background=0" if mode == "clean" else ""
    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(f"""
        SELECT client_ip, device_name, strftime('%Y-%m-%d', timestamp) AS day,
               CAST(strftime('%H', timestamp) AS INTEGER) AS hour,
               COUNT(*) AS requests, COALESCE(SUM(bytes_transferred),0) AS bytes
        FROM access_logs WHERE timestamp >= ? {bg_filter}
        GROUP BY client_ip, day, hour ORDER BY day DESC
    """, (since,))
    rows = c.fetchall()
    c.execute(f"SELECT COUNT(DISTINCT client_ip), COUNT(*), COALESCE(SUM(bytes_transferred),0) FROM access_logs WHERE timestamp >= ? {bg_filter}", (since,))
    device_count, log_count, total_bytes = c.fetchone()
    conn.close()

    # Build an hourly-per-device baseline from prior days; evaluate only the current hour.
    today = datetime.now().strftime("%Y-%m-%d")
    current_hour = datetime.now().hour
    buckets = {}
    current = {}
    names = {}
    for ip, name, day, hour, requests, byte_count in rows:
        names[ip] = name or ip
        if hour != current_hour:
            continue
        if day == today:
            current[ip] = (requests, byte_count)
        else:
            buckets.setdefault(ip, []).append(requests)

    anomalies = []
    for ip, (observed, byte_count) in current.items():
        history = buckets.get(ip, [])
        if len(history) < 3:
            continue
        mean = sum(history) / len(history)
        variance = sum((value - mean) ** 2 for value in history) / len(history)
        stddev = variance ** 0.5
        threshold = max(mean * 2, mean + 2 * stddev, mean + 5)
        if observed > threshold:
            anomalies.append({"device": names[ip], "ip": ip, "observed": observed,
                              "expected": round(mean, 1), "hour": f"{current_hour:02d}:00",
                              "bytes": byte_count, "severity": "high" if observed > threshold * 2 else "medium"})
    anomalies.sort(key=lambda item: item["observed"] / max(item["expected"], 1), reverse=True)

    insights = []
    if log_count:
        insight_conn = sqlite3.connect(DB_PATH)
        c = insight_conn.cursor()
        c.execute(f"""SELECT category, COUNT(*) FROM access_logs
                    WHERE timestamp >= ? {bg_filter}
                    GROUP BY category ORDER BY COUNT(*) DESC LIMIT 1""", (since,))
        top_category = c.fetchone()
        c.execute(f"""SELECT CAST(strftime('%H', timestamp) AS INTEGER), COUNT(*) FROM access_logs
                    WHERE timestamp >= ? {bg_filter}
                    GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1""", (since,))
        peak_hour = c.fetchone()
        insight_conn.close()
        if top_category:
            insights.append(f"Most common traffic category: {top_category[0]} ({top_category[1]:,} requests in 30 days).")
        if peak_hour:
            insights.append(f"Peak activity hour: {peak_hour[0]:02d}:00 ({peak_hour[1]:,} requests in 30 days).")
        if anomalies:
            insights.append(f"{len(anomalies)} device(s) have unusually high activity this hour compared with their own history.")
        else:
            insights.append("No unusual per-device activity detected for this hour.")
    else:
        insights.append("Waiting for device traffic. Analysis learns as this gateway collects logs.")

    return {"model": "Per-device hourly baseline", "training_days": 30,
            "training_requests": log_count, "devices_trained": device_count,
            "trained_days_required": 3, "anomalies": anomalies, "insights": insights,
            "privacy": "Analysis runs locally on this gateway; raw browsing history is not sent to an external AI service."}

# ─── Student Attendance & Device Monitoring ───────────────────
@app.get("/attendance/register")
def attendance_registration_page():
    page = os.path.join(STATIC_DIR, "attendance.html")
    return FileResponse(page) if os.path.exists(page) else HTMLResponse("Registration page unavailable", status_code=503)

@app.post("/api/attendance/register")
def register_attendance_student(req: StudentRegistrationRequest):
    ip = engine.get_registration_ip(req.token)
    if not ip:
        raise HTTPException(400, "This registration link has expired. Open a plain HTTP website again to get a new one.")
    mac = engine.get_mac_for_ip(ip)
    if not mac:
        raise HTTPException(409, "Could not read this device's hotspot MAC address yet. Reconnect to the hotspot and try again.")

    prn = req.prn.strip()
    name = req.name.strip()
    batch = req.batch.strip()
    if not 2 <= len(prn) <= 40:
        raise HTTPException(422, "Enter a valid PRN (2–40 characters).")
    if not 2 <= len(name) <= 100:
        raise HTTPException(422, "Enter your name (2–100 characters).")
    if not 1 <= len(batch) <= 50:
        raise HTTPException(422, "Enter a batch (up to 50 characters).")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO students (mac_address, prn, name, batch, registered_at) VALUES (?, ?, ?, ?, ?)",
                (mac, prn, name, batch, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "This device or PRN is already registered. Contact the administrator if your details need correction.")

    engine.consume_registration_token(req.token)
    student = {"mac_address": mac, "prn": prn, "name": name, "batch": batch}
    engine.record_attendance(student, ip=ip)
    return {"status": "ok", "name": name, "prn": prn, "batch": batch,
            "attendance_date": datetime.now().strftime("%Y-%m-%d")}

@app.get("/api/attendance")
def get_attendance(date: Optional[str] = None, batch: Optional[str] = None, search: Optional[str] = None):
    attendance_date = date or datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(attendance_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Date must use YYYY-MM-DD format.")
    
    with sqlite3.connect(DB_PATH) as conn:
        query = """
            SELECT a.id, a.prn, a.student_name, a.batch, a.mac_address, 
                   COALESCE(a.ip_address, ''), a.attendance_date, a.first_seen, a.last_seen, 
                   a.connection_count, COALESCE(a.status, 'Present')
            FROM attendance a
            WHERE a.attendance_date = ?
        """
        params = [attendance_date]
        if batch and batch != "All":
            query += " AND a.batch = ?"
            params.append(batch)
        if search:
            query += " AND (a.prn LIKE ? OR a.student_name LIKE ? OR a.mac_address LIKE ?)"
            s = f"%{search.strip()}%"
            params.extend([s, s, s])
        
        query += " ORDER BY a.first_seen DESC"
        rows = conn.execute(query, params).fetchall()

    results = []
    now = datetime.now()
    for r in rows:
        aid, prn, name, bat, mac, ip, adate, first_s, last_s, count, status = r
        dur_mins = 0
        is_online = False
        try:
            dt1 = datetime.strptime(first_s, "%Y-%m-%d %H:%M:%S")
            dt2 = datetime.strptime(last_s, "%Y-%m-%d %H:%M:%S")
            dur_mins = max(int((dt2 - dt1).total_seconds() / 60), 0)
            diff_now = (now - dt2).total_seconds()
            is_online = diff_now <= 90
        except Exception:
            pass
        
        dur_str = f"{dur_mins // 60}h {dur_mins % 60}m" if dur_mins >= 60 else f"{dur_mins}m"
        results.append({
            "id": aid,
            "prn": prn,
            "name": name,
            "batch": bat,
            "mac_address": mac,
            "ip_address": ip,
            "date": adate,
            "first_seen": first_s,
            "last_seen": last_s,
            "duration_minutes": dur_mins,
            "duration_formatted": dur_str,
            "connections": count,
            "status": status,
            "is_online": is_online
        })
    return results

@app.get("/api/attendance/stats")
def get_attendance_stats(date: Optional[str] = None):
    attendance_date = date or datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(DB_PATH) as conn:
        total_students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] or 0
        present_count = conn.execute("SELECT COUNT(*) FROM attendance WHERE attendance_date=?", (attendance_date,)).fetchone()[0] or 0
        batches = conn.execute("SELECT DISTINCT batch FROM students ORDER BY batch").fetchall()
        batch_list = [b[0] for b in batches if b[0]]
        
        active_now = 0
        today_att = conn.execute("SELECT last_seen FROM attendance WHERE attendance_date=?", (attendance_date,)).fetchall()
        now = datetime.now()
        for r in today_att:
            try:
                dt = datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")
                if (now - dt).total_seconds() <= 90:
                    active_now += 1
            except Exception:
                pass

    rate = round((present_count / total_students * 100), 1) if total_students > 0 else 0
    return {
        "date": attendance_date,
        "total_registered": total_students,
        "present_today": present_count,
        "active_now": active_now,
        "attendance_rate": rate,
        "batches": batch_list
    }

@app.post("/api/attendance/checkin")
def manual_attendance_checkin(req: ManualCheckInRequest):
    prn = req.prn.strip()
    status = req.status or "Present"
    date_str = req.date or datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB_PATH) as conn:
        stu = conn.execute("SELECT mac_address, prn, name, batch FROM students WHERE prn=?", (prn,)).fetchone()
        if not stu:
            raise HTTPException(404, f"Student with PRN '{prn}' not found.")
        mac, prn, name, batch = stu
        conn.execute("""
            INSERT INTO attendance
                (mac_address, prn, student_name, batch, attendance_date, first_seen, last_seen, connection_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(mac_address, attendance_date) DO UPDATE SET
                status = excluded.status,
                last_seen = excluded.last_seen,
                connection_count = attendance.connection_count + 1
        """, (mac, prn, name, batch, date_str, now_str, now_str, status))

    return {"status": "ok", "message": f"Attendance marked for {name} ({prn}) on {date_str} as {status}."}

@app.delete("/api/attendance/{record_id}")
def delete_attendance_record(record_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM attendance WHERE id=?", (record_id,))
    return {"status": "ok", "message": "Attendance record deleted."}

@app.get("/api/connected-devices")
def get_connected_devices():
    """Returns real-time discovered connected devices from ARP and devices table, with student link status."""
    engine.scan_connected_devices()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT ip, custom_name, auto_name, device_type, first_seen, last_seen, COALESCE(mac_address, '') FROM devices ORDER BY last_seen DESC")
    rows = c.fetchall()

    c.execute("SELECT mac_address, prn, name, batch FROM students")
    student_map = {r[0].lower(): {"prn": r[1], "name": r[2], "batch": r[3]} for r in c.fetchall()}
    conn.close()

    result = []
    for ip, cname, aname, dtype, first_s, last_s, mac in rows:
        liveness, sec = calculate_device_liveness(last_s)
        stu = student_map.get(mac.lower()) if mac else None
        result.append({
            "ip": ip,
            "mac": mac,
            "name": cname or aname,
            "device_type": dtype or "mobile",
            "first_seen": first_s,
            "last_seen": last_s,
            "liveness": liveness,
            "seconds_ago": sec,
            "is_online": liveness == "Online",
            "student": stu
        })
    return result

@app.get("/api/students")
def get_students():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT prn, name, batch, mac_address, registered_at FROM students ORDER BY name COLLATE NOCASE").fetchall()
    return [{"prn": r[0], "name": r[1], "batch": r[2], "mac_address": r[3], "registered_at": r[4]} for r in rows]

@app.post("/api/students")
def admin_register_student(req: StudentAdminRegistrationRequest):
    mac = req.mac_address.strip().replace("-", ":").lower()
    if not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac):
        raise HTTPException(422, "Enter a MAC address in the format AA:BB:CC:DD:EE:FF.")
    prn, name, batch = req.prn.strip(), req.name.strip(), req.batch.strip()
    if not 2 <= len(prn) <= 40:
        raise HTTPException(422, "Enter a valid PRN (2–40 characters).")
    if not 2 <= len(name) <= 100:
        raise HTTPException(422, "Enter a name (2–100 characters).")
    if not 1 <= len(batch) <= 50:
        raise HTTPException(422, "Enter a batch (up to 50 characters).")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO students (mac_address, prn, name, batch, registered_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(mac_address) DO UPDATE SET
                    prn=excluded.prn, name=excluded.name, batch=excluded.batch,
                    registered_at=excluded.registered_at
            """, (mac, prn, name, batch, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That PRN is already registered to a different MAC address.")
    
    # Check if this device is currently online and record attendance immediately
    student_obj = {"mac_address": mac, "prn": prn, "name": name, "batch": batch}
    engine.record_attendance(student_obj)
    return {"status": "ok", "message": f"{name} ({prn}) registered for {mac}. Attendance has been updated."}

@app.delete("/api/students/{prn}")
def delete_student(prn: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM students WHERE prn=?", (prn.strip(),))
    return {"status": "ok", "message": f"Student with PRN {prn} deleted."}

# ─── AI Analytics & Machine Learning Dataset Export ──────────
CATEGORY_ENCODING = {
    'Academic & Learning': 1,
    'Entertainment & Social': 2,
    'Gaming & Arcade': 3,
    'Search & Knowledge': 4,
    'Messaging & Collab': 5,
    'Cloud & Infrastructure': 6,
    'Proxy & Bypass': 7,
    'Shopping & Services': 8,
    'General Web': 9
}

DEVICE_TYPE_ENCODING = {
    'desktop': 1,
    'mobile': 2,
    'tablet': 3,
    'laptop': 4
}

METHOD_ENCODING = {
    'GET': 1,
    'POST': 2,
    'CONNECT': 3,
    'PUT': 4,
    'DELETE': 5,
    'HEAD': 6
}

RISK_ENCODING = {
    'Normal': 0,
    'Low': 1,
    'Policy Violation': 2,
    'Restricted Gaming': 2,
    'Bypass Attempt': 3
}

@app.get("/api/export/schema")
def get_export_schema():
    """Returns documentation and attribute definitions for the AI dataset exporter."""
    return {
        "datasets": {
            "traffic_features": {
                "name": "Network Traffic ML Feature Matrix",
                "description": "Pre-engineered numerical and categorical features extracted from network access logs for anomaly detection, intrusion classification, and traffic category prediction.",
                "attributes": [
                    {"name": "log_id", "type": "int", "role": "identifier", "description": "Sequential unique entry identifier"},
                    {"name": "timestamp", "type": "string", "role": "temporal", "description": "ISO-8601 formatted event timestamp"},
                    {"name": "epoch_time", "type": "float", "role": "temporal", "description": "Unix timestamp in seconds for continuous time-series modeling"},
                    {"name": "hour_of_day", "type": "int", "role": "cyclical", "description": "Hour of event (0–23)"},
                    {"name": "day_of_week", "type": "int", "role": "cyclical", "description": "Day of week (0=Monday, 6=Sunday)"},
                    {"name": "is_weekend", "type": "binary", "role": "feature", "description": "1 if Saturday/Sunday, else 0"},
                    {"name": "is_academic_hours", "type": "binary", "role": "feature", "description": "1 if weekday between 09:00 and 17:00, else 0"},
                    {"name": "client_ip", "type": "string", "role": "categorical", "description": "Client IP address"},
                    {"name": "client_mac", "type": "string", "role": "categorical", "description": "Resolved physical MAC address of device"},
                    {"name": "device_name", "type": "string", "role": "metadata", "description": "Human-readable or auto-detected device name"},
                    {"name": "device_type", "type": "string", "role": "categorical", "description": "Device category (mobile, desktop, tablet, etc.)"},
                    {"name": "device_type_code", "type": "int", "role": "feature", "description": "Ordinal encoded device type integer (1=desktop, 2=mobile, 3=tablet, 4=laptop)"},
                    {"name": "student_prn", "type": "string", "role": "label", "description": "Associated student PRN or UNREGISTERED"},
                    {"name": "student_batch", "type": "string", "role": "categorical", "description": "Student academic batch or NONE"},
                    {"name": "domain", "type": "string", "role": "text", "description": "Target hostname accessed by device"},
                    {"name": "clean_site", "type": "string", "role": "categorical", "description": "Normalized root service or brand domain"},
                    {"name": "domain_length", "type": "int", "role": "feature", "description": "Character length of target domain string"},
                    {"name": "subdomain_count", "type": "int", "role": "feature", "description": "Count of sub-levels / dots in domain name"},
                    {"name": "method", "type": "string", "role": "categorical", "description": "HTTP method (GET, POST, CONNECT)"},
                    {"name": "method_code", "type": "int", "role": "feature", "description": "Encoded method integer (1=GET, 2=POST, 3=CONNECT)"},
                    {"name": "category", "type": "string", "role": "label", "description": "Domain behavioral classification"},
                    {"name": "category_code", "type": "int", "role": "target", "description": "Ordinal integer label (1=Academic, 2=Social, 3=Gaming, etc.)"},
                    {"name": "is_background", "type": "binary", "role": "feature", "description": "1 if background OS telemetry/ad, 0 if user-initiated browsing"},
                    {"name": "bytes_transferred", "type": "int", "role": "continuous", "description": "Total bytes transferred in this transaction"},
                    {"name": "log_bytes", "type": "float", "role": "continuous", "description": "log(bytes + 1) normalized scale for neural networks & regression"},
                    {"name": "status", "type": "string", "role": "categorical", "description": "Policy decision: Allowed or Blocked"},
                    {"name": "status_code", "type": "binary", "role": "feature", "description": "1 if Allowed, 0 if Blocked"},
                    {"name": "risk_flag", "type": "string", "role": "categorical", "description": "Threat assessment flag (Normal, Policy Violation, Bypass Attempt)"},
                    {"name": "risk_score", "type": "int", "role": "feature", "description": "Numeric risk scale (0=Normal, 1=Low, 2=Medium, 3=High)"},
                    {"name": "is_anomaly", "type": "binary", "role": "target", "description": "1 if event is anomalous or blocked, 0 if normal"}
                ]
            },
            "device_profiles": {
                "name": "Device Behavioral Feature Vectors",
                "description": "Aggregated per-device statistics for unsupervised clustering (K-Means, DBSCAN) and device profiling.",
                "attributes": [
                    {"name": "client_ip", "type": "string", "role": "identifier", "description": "Device IP address"},
                    {"name": "client_mac", "type": "string", "role": "identifier", "description": "Physical MAC address"},
                    {"name": "device_name", "type": "string", "role": "metadata", "description": "Device name"},
                    {"name": "device_type", "type": "string", "role": "categorical", "description": "Device type"},
                    {"name": "student_prn", "type": "string", "role": "metadata", "description": "Linked student PRN"},
                    {"name": "total_visits", "type": "int", "role": "continuous", "description": "Total website requests recorded"},
                    {"name": "total_mb_used", "type": "float", "role": "continuous", "description": "Total bandwidth consumed in MB"},
                    {"name": "avg_bytes_per_visit", "type": "float", "role": "continuous", "description": "Average payload size per visit"},
                    {"name": "unique_domains_visited", "type": "int", "role": "continuous", "description": "Domain diversity count"},
                    {"name": "academic_ratio", "type": "float", "role": "feature", "description": "Proportion of requests in Academic category (0.0–1.0)"},
                    {"name": "entertainment_ratio", "type": "float", "role": "feature", "description": "Proportion of requests in Entertainment category (0.0–1.0)"},
                    {"name": "gaming_ratio", "type": "float", "role": "feature", "description": "Proportion of requests in Gaming category (0.0–1.0)"},
                    {"name": "blocked_ratio", "type": "float", "role": "feature", "description": "Ratio of blocked requests to total requests"},
                    {"name": "blocked_count", "type": "int", "role": "feature", "description": "Total policy violations blocked"},
                    {"name": "threat_level", "type": "string", "role": "target", "description": "Synthesized risk classification (Low, Medium, High)"}
                ]
            },
            "attendance_ml": {
                "name": "Student Attendance & Network Engagement Dataset",
                "description": "Structured attendance timestamps and network liveness metrics for student punctuality and engagement AI models.",
                "attributes": [
                    {"name": "attendance_id", "type": "int", "role": "identifier", "description": "Record ID"},
                    {"name": "prn", "type": "string", "role": "identifier", "description": "Student PRN"},
                    {"name": "student_name", "type": "string", "role": "metadata", "description": "Full student name"},
                    {"name": "batch", "type": "string", "role": "categorical", "description": "Academic division / batch"},
                    {"name": "mac_address", "type": "string", "role": "metadata", "description": "Recognized device MAC"},
                    {"name": "ip_address", "type": "string", "role": "metadata", "description": "Assigned device IP"},
                    {"name": "attendance_date", "type": "string", "role": "temporal", "description": "Date of attendance (YYYY-MM-DD)"},
                    {"name": "check_in_time", "type": "string", "role": "temporal", "description": "First connection time of day"},
                    {"name": "last_active_time", "type": "string", "role": "temporal", "description": "Most recent connection time"},
                    {"name": "check_in_hour", "type": "float", "role": "continuous", "description": "Decimal hour of check-in (e.g. 9.5 for 09:30)"},
                    {"name": "duration_minutes", "type": "int", "role": "continuous", "description": "Total duration on network in minutes"},
                    {"name": "connection_count", "type": "int", "role": "continuous", "description": "Number of proxy network handshakes"},
                    {"name": "is_punctual", "type": "binary", "role": "target", "description": "1 if checked in before 09:30 AM, else 0"},
                    {"name": "status", "type": "string", "role": "label", "description": "Attendance status (Present, Late, Active)"}
                ]
            }
        }
    }

@app.get("/api/export/ai-dataset")
def export_ai_dataset(
    type: str = "traffic_features",
    format: str = "csv",
    limit: int = 5000,
    mode: str = "clean",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Exports collected and stored network telemetry into curated datasets with engineered
    attributes and numerical encodings tailored for Machine Learning and AI analysis.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Pre-load student mapping by MAC & IP
    c.execute("SELECT mac_address, prn, name, batch FROM students")
    mac_to_student = {r[0].lower(): {"prn": r[1], "name": r[2], "batch": r[3]} for r in c.fetchall()}
    c.execute("SELECT ip, COALESCE(mac_address,'') FROM devices")
    ip_to_mac = {r[0]: r[1].lower() for r in c.fetchall()}

    records = []
    filename_prefix = f"netplus_{type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if type == "traffic_features" or type == "raw_logs":
        conditions = []
        params = []
        if mode == "clean" and type == "traffic_features":
            conditions.append("is_background = 0")
        if start_date:
            conditions.append("timestamp >= ?")
            params.append(f"{start_date} 00:00:00")
        if end_date:
            conditions.append("timestamp <= ?")
            params.append(f"{end_date} 23:59:59")
        
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        lim_clause = f"LIMIT {limit}" if limit and limit > 0 else ""

        c.execute(f"""
            SELECT id, timestamp, client_ip, device_name, device_type, domain, clean_site,
                   is_background, category, method, bytes_transferred, status, risk_flag, user_agent
            FROM access_logs {where} ORDER BY id DESC {lim_clause}
        """, params)
        rows = c.fetchall()

        for r in rows:
            lid, ts, ip, dev_name, dev_type, dom, csite, is_bg, cat, meth, b_trans, stat, r_flag, ua = r
            
            # Feature engineering
            mac = ip_to_mac.get(ip, '')
            stu = mac_to_student.get(mac, {}) if mac else {}
            
            epoch = 0.0
            hour = 0
            dow = 0
            is_wknd = 0
            is_acad_hours = 0
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                epoch = dt.timestamp()
                hour = dt.hour
                dow = dt.weekday()
                is_wknd = 1 if dow >= 5 else 0
                is_acad_hours = 1 if (dow < 5 and 9 <= hour <= 17) else 0
            except Exception:
                pass

            bytes_val = b_trans or 0
            log_b = round(math.log1p(bytes_val), 4)
            d_len = len(dom or '')
            sub_count = (dom or '').count('.')
            meth_upper = (meth or 'GET').upper()
            meth_code = METHOD_ENCODING.get(meth_upper, 0)
            dev_type_str = (dev_type or 'mobile').lower()
            dev_type_code = DEVICE_TYPE_ENCODING.get(dev_type_str, 2)
            cat_code = CATEGORY_ENCODING.get(cat, 9)
            stat_code = 1 if stat == 'Allowed' else 0
            r_score = RISK_ENCODING.get(r_flag, 0)
            if stat == 'Blocked':
                r_score = max(r_score, 2)
            is_anomaly = 1 if (r_score > 0 or stat == 'Blocked') else 0

            if type == "traffic_features":
                records.append({
                    "log_id": lid,
                    "timestamp": ts,
                    "epoch_time": epoch,
                    "hour_of_day": hour,
                    "day_of_week": dow,
                    "is_weekend": is_wknd,
                    "is_academic_hours": is_acad_hours,
                    "client_ip": ip,
                    "client_mac": mac or "UNKNOWN",
                    "device_name": dev_name,
                    "device_type": dev_type_str,
                    "device_type_code": dev_type_code,
                    "student_prn": stu.get("prn", "UNREGISTERED"),
                    "student_batch": stu.get("batch", "NONE"),
                    "domain": dom,
                    "clean_site": csite or dom,
                    "domain_length": d_len,
                    "subdomain_count": sub_count,
                    "method": meth_upper,
                    "method_code": meth_code,
                    "category": cat,
                    "category_code": cat_code,
                    "is_background": is_bg,
                    "bytes_transferred": bytes_val,
                    "log_bytes": log_b,
                    "status": stat,
                    "status_code": stat_code,
                    "risk_flag": r_flag,
                    "risk_score": r_score,
                    "is_anomaly": is_anomaly
                })
            else: # raw_logs
                records.append({
                    "id": lid,
                    "timestamp": ts,
                    "client_ip": ip,
                    "device_name": dev_name,
                    "device_type": dev_type,
                    "domain": dom,
                    "clean_site": csite,
                    "is_background": is_bg,
                    "category": cat,
                    "method": meth,
                    "bytes_transferred": bytes_val,
                    "status": stat,
                    "risk_flag": r_flag,
                    "user_agent": ua
                })

    elif type == "device_profiles":
        c.execute("""
            SELECT d.ip, COALESCE(NULLIF(d.custom_name,''), d.auto_name, 'Device'), d.device_type,
                   COUNT(a.id) as total_reqs,
                   COALESCE(SUM(a.bytes_transferred), 0) as total_bytes,
                   COUNT(DISTINCT a.clean_site) as unique_sites,
                   COALESCE(SUM(CASE WHEN a.category = 'Academic & Learning' THEN 1 ELSE 0 END), 0) as acad_count,
                   COALESCE(SUM(CASE WHEN a.category = 'Entertainment & Social' THEN 1 ELSE 0 END), 0) as ent_count,
                   COALESCE(SUM(CASE WHEN a.category = 'Gaming & Arcade' THEN 1 ELSE 0 END), 0) as game_count,
                   COALESCE(SUM(CASE WHEN a.status = 'Blocked' THEN 1 ELSE 0 END), 0) as blocked_cnt
            FROM devices d
            LEFT JOIN access_logs a ON a.client_ip = d.ip
            GROUP BY d.ip
            ORDER BY total_reqs DESC, d.last_seen DESC
        """)
        dev_rows = c.fetchall()

        for r in dev_rows:
            ip, dname, dtype, total_r, total_b, uniq_sites, acad_c, ent_c, game_c, blk_c = r
            mac = ip_to_mac.get(ip, '')
            stu = mac_to_student.get(mac, {}) if mac else {}
            
            total_r = max(total_r, 1)
            mb = round(total_b / (1024 * 1024), 2)
            avg_b = round(total_b / total_r, 1)
            acad_ratio = round(acad_c / total_r, 3)
            ent_ratio = round(ent_c / total_r, 3)
            game_ratio = round(game_c / total_r, 3)
            blk_ratio = round(blk_c / total_r, 3)
            
            threat = "Low"
            if blk_c > 5 or game_ratio > 0.4:
                threat = "High"
            elif blk_c > 0 or game_ratio > 0.2:
                threat = "Medium"

            records.append({
                "client_ip": ip,
                "client_mac": mac or "UNKNOWN",
                "device_name": dname,
                "device_type": dtype or "mobile",
                "student_prn": stu.get("prn", "UNREGISTERED"),
                "student_name": stu.get("name", "N/A"),
                "total_visits": total_r,
                "total_mb_used": mb,
                "avg_bytes_per_visit": avg_b,
                "unique_domains_visited": uniq_sites,
                "academic_ratio": acad_ratio,
                "entertainment_ratio": ent_ratio,
                "gaming_ratio": game_ratio,
                "blocked_ratio": blk_ratio,
                "blocked_count": blk_c,
                "threat_level": threat
            })

    elif type == "attendance_ml":
        c.execute("""
            SELECT id, prn, student_name, batch, mac_address, COALESCE(ip_address,''),
                   attendance_date, first_seen, last_seen, connection_count, COALESCE(status, 'Present')
            FROM attendance ORDER BY attendance_date DESC, first_seen ASC
        """)
        att_rows = c.fetchall()
        for r in att_rows:
            aid, prn, name, bat, mac, ip, adate, first_s, last_s, count, status = r
            dur_mins = 0
            check_in_hour = 0.0
            is_punctual = 1
            try:
                dt1 = datetime.strptime(first_s, "%Y-%m-%d %H:%M:%S")
                dt2 = datetime.strptime(last_s, "%Y-%m-%d %H:%M:%S")
                dur_mins = max(int((dt2 - dt1).total_seconds() / 60), 0)
                check_in_hour = round(dt1.hour + dt1.minute / 60.0, 2)
                # Punctual if before 09:30 AM
                is_punctual = 1 if (dt1.hour < 9 or (dt1.hour == 9 and dt1.minute <= 30)) else 0
            except Exception:
                pass

            records.append({
                "attendance_id": aid,
                "prn": prn,
                "student_name": name,
                "batch": bat,
                "mac_address": mac,
                "ip_address": ip or "UNKNOWN",
                "attendance_date": adate,
                "check_in_time": first_s,
                "last_active_time": last_s,
                "check_in_hour": check_in_hour,
                "duration_minutes": dur_mins,
                "connection_count": count,
                "is_punctual": is_punctual,
                "status": status
            })

    conn.close()

    # Format output
    if format == "json":
        json_data = json.dumps(records, indent=2)
        return Response(
            content=json_data,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename_prefix}.json"}
        )
    else: # CSV format
        output = io.StringIO()
        if records:
            writer = csv.DictWriter(output, fieldnames=list(records[0].keys()), quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows(records)
        else:
            output.write("No records found for the specified criteria.")
        
        csv_data = output.getvalue()
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename_prefix}.csv"}
        )

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
