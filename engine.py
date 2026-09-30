import socket
import select
import threading
import time
import json
import sqlite3
import os
import sys
import re
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

DB_PATH = os.path.join(os.path.dirname(__file__), "network_logs.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            client_ip TEXT,
            device_name TEXT,
            device_type TEXT,
            domain TEXT,
            clean_site TEXT,
            is_background INTEGER DEFAULT 0,
            category TEXT,
            method TEXT,
            bytes_transferred INTEGER,
            status TEXT,
            risk_flag TEXT,
            user_agent TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            ip TEXT PRIMARY KEY,
            custom_name TEXT,
            auto_name TEXT,
            device_type TEXT,
            first_seen TEXT,
            last_seen TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blocklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT UNIQUE,
            reason TEXT,
            created_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS device_quotas (
            ip TEXT PRIMARY KEY,
            daily_mb_limit INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS latency_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT,
            host TEXT,
            port INTEGER DEFAULT 80,
            enabled INTEGER DEFAULT 1
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM latency_targets")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO latency_targets (label, host, port, enabled) VALUES (?, ?, ?, 1)",
            [
                ('Google (Baseline)', 'www.google.com', 80),
                ('Cloudflare', 'one.one.one.one', 80),
            ]
        )
    conn.commit()
    conn.close()

# Known Root Brand Normalization Mapping
ROOT_DOMAIN_RULES = [
    (r'.*takeuforward\.(org|com).*', 'takeuforward.org', 'Academic & Learning'),
    (r'.*codechef\.(com|org).*', 'codechef.com', 'Academic & Learning'),
    (r'.*leetcode\.(com|org).*', 'leetcode.com', 'Academic & Learning'),
    (r'.*geeksforgeeks\.(org|com).*', 'geeksforgeeks.org', 'Academic & Learning'),
    (r'.*moodle.*', 'moodle.college.edu', 'Academic & Learning'),
    (r'.*erp.*', 'erp.college.edu', 'Academic & Learning'),
    (r'.*github\.(com|io).*', 'github.com', 'Academic & Learning'),
    (r'.*stackoverflow\.(com).*', 'stackoverflow.com', 'Academic & Learning'),
    (r'.*wikipedia\.(org|com).*', 'wikipedia.org', 'Search & Knowledge'),
    (r'.*chatgpt\.com.*', 'chatgpt.com', 'Academic & Learning'),
    (r'.*openai\.com.*', 'openai.com', 'Academic & Learning'),
    
    (r'.*instagram\.(com|net).*', 'instagram.com', 'Entertainment & Social'),
    (r'.*facebook\.(com|net).*', 'facebook.com', 'Entertainment & Social'),
    (r'.*fbcdn\.net.*', 'facebook.com', 'Entertainment & Social'),
    (r'.*netflix\.(com|net).*', 'netflix.com', 'Entertainment & Social'),
    (r'.*nflx.*\.net.*', 'netflix.com', 'Entertainment & Social'),
    (r'.*nflxext\.com.*', 'netflix.com', 'Entertainment & Social'),
    (r'.*youtube\.(com|be).*', 'youtube.com', 'Entertainment & Social'),
    (r'.*googlevideo\.com.*', 'youtube.com', 'Entertainment & Social'),
    (r'.*ytimg\.com.*', 'youtube.com', 'Entertainment & Social'),
    (r'.*spotify\.(com|net).*', 'spotify.com', 'Entertainment & Social'),
    (r'.*twitch\.tv.*', 'twitch.tv', 'Entertainment & Social'),
    (r'.*snapchat\.com.*', 'snapchat.com', 'Entertainment & Social'),
    (r'.*linkedin\.com.*', 'linkedin.com', 'Entertainment & Social'),
    (r'.*reddit\.(com|it).*', 'reddit.com', 'Entertainment & Social'),
    (r'.*twitter\.(com).*|.*x\.com.*', 'x.com (Twitter)', 'Entertainment & Social'),
    
    (r'.*roblox\.com.*', 'roblox.com', 'Gaming & Arcade'),
    (r'.*steam(powered)?\.com.*', 'steam.com', 'Gaming & Arcade'),
    (r'.*chess\.com.*', 'chess.com', 'Gaming & Arcade'),
    (r'.*epicgames\.com.*', 'epicgames.com', 'Gaming & Arcade'),
    
    (r'.*google\.(com|co\..*|edu|org).*', 'google.com', 'Search & Knowledge'),
    (r'.*yahoo\.(com|co\..*).*', 'yahoo.com', 'Search & Knowledge'),
    (r'.*bing\.com.*', 'bing.com', 'Search & Knowledge'),
    (r'.*whatsapp\.(com|net).*', 'whatsapp.com', 'Messaging & Collab'),
    (r'.*telegram\.(org|me).*', 'telegram.org', 'Messaging & Collab'),
    (r'.*discord\.(com|gg).*', 'discord.com', 'Messaging & Collab'),
    
    (r'.*amazon\.(com|in|co\..*).*', 'amazon.com', 'Shopping & Services'),
    (r'.*awsstatic\.com.*', 'aws.amazon.com', 'Cloud & Infrastructure'),
    (r'.*aws\.dev.*', 'aws.amazon.com', 'Cloud & Infrastructure'),
]

# Patterns representing background telemetry / ads / OS captive portal / noise
BACKGROUND_PATTERNS = [
    r'.*connectivitycheck\..*',
    r'.*generate_204.*',
    r'.*gvt\d+\.com.*',
    r'.*gcp\.gvt\d+\.com.*',
    r'.*googleapis\.com.*',
    r'.*gstatic\.com.*',
    r'.*googleusercontent\.com.*',
    r'.*googleadservices\.com.*',
    r'.*googletagmanager\.com.*',
    r'.*google-analytics\.com.*',
    r'.*doubleclick\.net.*',
    r'.*miui\.com.*',
    r'.*mioffice\.cn.*',
    r'.*xiaomi\.com.*',
    r'.*mi-img\.com.*',
    r'.*pangle\.io.*',
    r'.*demdex\.net.*',
    r'.*omtrdc\.net.*',
    r'.*everesttech\.net.*',
    r'.*onetrust\.(com|io).*',
    r'.*adsrvr\.org.*',
    r'.*adobedc\.net.*',
    r'.*sc-static\.net.*',
    r'.*clrt\.ai.*',
    r'.*brave\.com.*',
    r'.*cloudflareinsights\.com.*',
    r'.*app-measurement\.com.*',
    r'^\d+\.\d+\.\d+\.\d+$' # Raw IP
]

def clean_and_normalize_domain(domain):
    d = domain.lower()

    # 1. Check if it matches a known human-visited website
    for pattern, root_brand, cat in ROOT_DOMAIN_RULES:
        if re.match(pattern, d, re.I):
            return root_brand, cat, False

    # 2. Check if it's background noise / telemetry
    is_bg = any(re.match(p, d, re.I) for p in BACKGROUND_PATTERNS)
    if is_bg:
        return domain, 'Background & OS Telemetry', True

    # 3. Strip subdomains for general sites (e.g. blog.example.com -> example.com)
    parts = d.split('.')
    if len(parts) >= 2:
        root_site = ".".join(parts[-2:])
        # Check academic keywords
        if any(k in root_site for k in ['edu', 'college', 'univ', 'ac.', 'learn', 'code', 'study']):
            return root_site, 'Academic & Learning', False
        elif any(k in root_site for k in ['game', 'play', 'arcade']):
            return root_site, 'Gaming & Arcade', False
        elif any(k in root_site for k in ['proxy', 'vpn', 'hide', 'tunnel']):
            return root_site, 'Proxy & Bypass', False
        return root_site, 'General Web', False

    return domain, 'General Web', False

def parse_user_agent(ua_string):
    if not ua_string:
        return {"name": "Mobile Device", "type": "mobile", "os": "Unknown"}
    ua = ua_string.lower()

    # Extract Android version
    android_ver = ""
    m = re.search(r'android ([\d.]+)', ua)
    if m: android_ver = f" (Android {m.group(1)})"

    # Extract iOS version
    ios_ver = ""
    m2 = re.search(r'os ([\d_]+) like', ua)
    if m2: ios_ver = f" (iOS {m2.group(1).replace('_','.')})"

    if 'iphone' in ua:
        return {"name": f"Apple iPhone{ios_ver}", "type": "mobile", "os": f"iOS{ios_ver}"}
    if 'ipad' in ua:
        return {"name": f"Apple iPad{ios_ver}", "type": "tablet", "os": f"iPadOS{ios_ver}"}
    if 'macintosh' in ua or 'mac os x' in ua:
        return {"name": "MacBook / macOS", "type": "laptop", "os": "macOS"}
    if 'android' in ua:
        if 'samsung' in ua or 'sm-' in ua:
            return {"name": f"Samsung Galaxy{android_ver}", "type": "mobile", "os": f"Android{android_ver}"}
        if 'pixel' in ua:
            return {"name": f"Google Pixel{android_ver}", "type": "mobile", "os": f"Android{android_ver}"}
        if 'oneplus' in ua:
            return {"name": f"OnePlus{android_ver}", "type": "mobile", "os": f"Android{android_ver}"}
        if 'redmi' in ua or 'xiaomi' in ua or 'poco' in ua or 'miui' in ua:
            return {"name": f"Xiaomi / Redmi{android_ver}", "type": "mobile", "os": f"Android{android_ver}"}
        if 'vivo' in ua:
            return {"name": f"Vivo{android_ver}", "type": "mobile", "os": f"Android{android_ver}"}
        if 'oppo' in ua:
            return {"name": f"Oppo{android_ver}", "type": "mobile", "os": f"Android{android_ver}"}
        if 'realme' in ua:
            return {"name": f"Realme{android_ver}", "type": "mobile", "os": f"Android{android_ver}"}
        return {"name": f"Android Phone{android_ver}", "type": "mobile", "os": f"Android{android_ver}"}
    if 'windows nt 10' in ua:
        return {"name": "Windows 10/11 PC", "type": "desktop", "os": "Windows 10/11"}
    if 'windows' in ua:
        return {"name": "Windows PC", "type": "desktop", "os": "Windows"}
    if 'linux' in ua:
        return {"name": "Linux PC", "type": "desktop", "os": "Linux"}
    return {"name": "Unknown Device", "type": "mobile", "os": "Unknown"}

class NetworkMonitoringEngine:
    def __init__(self, host='0.0.0.0', port=8080):
        self.host = host
        self.port = port
        self.running = False
        self.server_socket = None
        self.blocked_domains = set()
        self.ws_subscribers = []
        self.lock = threading.Lock()
        self._quota_cache = {}   # {ip: daily_mb_limit}
        self._quota_cache_ts = 0
        init_db()
        self.load_blocklist()
        self._refresh_quota_cache()

    def _refresh_quota_cache(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT ip, daily_mb_limit FROM device_quotas WHERE enabled = 1 AND daily_mb_limit > 0")
            self._quota_cache = {r[0]: r[1] for r in c.fetchall()}
            self._quota_cache_ts = time.time()
            conn.close()
        except Exception:
            pass

    def get_daily_usage_mb(self, ip):
        """Returns today's MB consumed by this IP from access_logs."""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(
                "SELECT COALESCE(SUM(bytes_transferred),0) FROM access_logs "
                "WHERE client_ip = ? AND timestamp LIKE ?",
                (ip, f"{today}%")
            )
            total_bytes = c.fetchone()[0] or 0
            conn.close()
            return total_bytes / (1024 * 1024)
        except Exception:
            return 0.0

    def is_quota_exceeded(self, ip):
        if time.time() - self._quota_cache_ts > 60:
            self._refresh_quota_cache()
        limit_mb = self._quota_cache.get(ip, 0)
        if limit_mb <= 0:
            return False
        used_mb = self.get_daily_usage_mb(ip)
        return used_mb >= limit_mb

    def set_quota(self, ip, daily_mb_limit):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO device_quotas (ip, daily_mb_limit, enabled, created_at) VALUES (?, ?, 1, ?)",
                (ip, daily_mb_limit, now)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Quota set error: {e}")
        self._refresh_quota_cache()

    def remove_quota(self, ip):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM device_quotas WHERE ip = ?", (ip,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Quota remove error: {e}")
        self._refresh_quota_cache()

    def load_blocklist(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT domain FROM blocklist")
            self.blocked_domains = {r[0].lower() for r in c.fetchall()}
            conn.close()
        except Exception:
            pass

    def add_block_rule(self, domain, reason="Restricted by policy"):
        domain = domain.strip().lower()
        with self.lock:
            self.blocked_domains.add(domain)
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO blocklist (domain, reason, created_at) VALUES (?, ?, ?)",
                      (domain, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error saving block rule: {e}")

    def remove_block_rule(self, domain):
        domain = domain.strip().lower()
        with self.lock:
            self.blocked_domains.discard(domain)
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM blocklist WHERE domain = ?", (domain,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error removing block rule: {e}")

    def rename_device(self, ip, new_name):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE devices SET custom_name = ? WHERE ip = ?", (new_name, ip))
            c.execute("UPDATE access_logs SET device_name = ? WHERE client_ip = ?", (new_name, ip))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error updating device name: {e}")

    def is_blocked(self, domain, clean_site):
        d1 = domain.lower()
        d2 = clean_site.lower()
        for b in self.blocked_domains:
            if b in d1 or b in d2:
                return True
        return False

    def get_or_create_device(self, ip, ua_string):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ua_info = parse_user_agent(ua_string)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT ip, custom_name, auto_name, device_type FROM devices WHERE ip = ?", (ip,))
        row = c.fetchone()

        if row:
            custom_name = row[1]
            auto_name = row[2]
            dev_type = row[3]
            
            if ua_string and ('Mobile Device' in auto_name or 'Client Device' in auto_name):
                auto_name = f"{ua_info['name']} (#{ip.split('.')[-1]})"
                dev_type = ua_info['type']
                c.execute("UPDATE devices SET auto_name = ?, device_type = ?, last_seen = ? WHERE ip = ?", (auto_name, dev_type, timestamp, ip))
            else:
                c.execute("UPDATE devices SET last_seen = ? WHERE ip = ?", (timestamp, ip))
            
            conn.commit()
            conn.close()
            return {
                "ip": ip,
                "name": custom_name or auto_name,
                "device_type": dev_type
            }
        else:
            if ip == '127.0.0.1':
                auto_name = 'Host PC (Localhost)'
                dev_type = 'desktop'
            elif ip.startswith('192.168.137.'):
                auto_name = f"{ua_info['name']} (#{ip.split('.')[-1]})"
                dev_type = ua_info['type']
            else:
                auto_name = f"{ua_info['name']} ({ip})"
                dev_type = ua_info['type']

            c.execute("INSERT INTO devices (ip, custom_name, auto_name, device_type, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
                      (ip, '', auto_name, dev_type, timestamp, timestamp))
            conn.commit()
            conn.close()
            return {
                "ip": ip,
                "name": auto_name,
                "device_type": dev_type
            }

    def log_event(self, entry):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                INSERT INTO access_logs (timestamp, client_ip, device_name, device_type, domain, clean_site, is_background, category, method, bytes_transferred, status, risk_flag, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry['timestamp'],
                entry['client_ip'],
                entry['device_name'],
                entry['device_type'],
                entry['domain'],
                entry['clean_site'],
                1 if entry.get('is_background') else 0,
                entry['category'],
                entry['method'],
                entry['bytes'],
                entry['status'],
                entry['risk_flag'],
                entry.get('user_agent', '')
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"DB Error: {e}")

        # Broadcast via WebSocket
        self.broadcast_event(entry)

    def register_ws(self, ws):
        with self.lock:
            self.ws_subscribers.append(ws)

    def unregister_ws(self, ws):
        with self.lock:
            if ws in self.ws_subscribers:
                self.ws_subscribers.remove(ws)

    def broadcast_event(self, event):
        dead = []
        with self.lock:
            subscribers = list(self.ws_subscribers)
        
        msg = json.dumps({"type": "NEW_LOG", "data": event})
        for ws in subscribers:
            try:
                ws.send_text(msg)
            except Exception:
                dead.append(ws)
        
        if dead:
            with self.lock:
                for d in dead:
                    if d in self.ws_subscribers:
                        self.ws_subscribers.remove(d)

    def handle_client(self, client_socket, client_address):
        client_ip, _ = client_address
        remote_socket = None

        try:
            request_data = client_socket.recv(8192)
            if not request_data:
                client_socket.close()
                return

            request_text = request_data.decode('utf-8', errors='ignore')
            lines = request_text.split('\r\n')
            if not lines or not lines[0]:
                client_socket.close()
                return

            request_line = lines[0]
            parts = request_line.split()
            if len(parts) < 2:
                client_socket.close()
                return

            method, target = parts[0].upper(), parts[1]

            # Extract User-Agent header
            user_agent = ""
            for line in lines[1:]:
                if line.lower().startswith('user-agent:'):
                    user_agent = line.split(':', 1)[1].strip()
                    break

            device_info = self.get_or_create_device(client_ip, user_agent)
            device_name = device_info['name']
            device_type = device_info['device_type']

            # Extract domain and port
            if method == 'CONNECT':
                if ':' in target:
                    host, port = target.split(':', 1)
                    port = int(port)
                else:
                    host, port = target, 443
            else:
                if target.startswith('http://') or target.startswith('https://'):
                    url_part = target.split('://', 1)[1]
                    host = url_part.split('/')[0]
                else:
                    host = target.split('/')[0]
                if ':' in host:
                    host, port = host.split(':', 1)
                    port = int(port)
                else:
                    port = 80

            # Normalize to clean website & category
            clean_site, category, is_background = clean_and_normalize_domain(host)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Risk check
            blocked = self.is_blocked(host, clean_site)
            risk_flag = "Normal"
            status = "Blocked" if blocked else "Allowed"

            if blocked:
                risk_flag = "Policy Violation"
            elif category == 'Gaming & Arcade':
                risk_flag = "Restricted Gaming"
            elif category == 'Proxy & Bypass':
                risk_flag = "Bypass Attempt"

            # If blocked
            if blocked:
                response = b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html><html><body style='font-family:sans-serif;text-align:center;padding:50px;background:#111;color:#fff;'><h1>403 Forbidden</h1><p>Access to <strong>" + host.encode() + b"</strong> has been restricted by College Policy.</p></body></html>"
                client_socket.sendall(response)
                client_socket.close()

                self.log_event({
                    'timestamp': timestamp,
                    'client_ip': client_ip,
                    'device_name': device_name,
                    'device_type': device_type,
                    'domain': host,
                    'clean_site': clean_site,
                    'is_background': is_background,
                    'category': category,
                    'method': method,
                    'bytes': len(request_data),
                    'status': 'Blocked',
                    'risk_flag': risk_flag,
                    'user_agent': user_agent
                })
                print(f"[{timestamp}] 🚫 BLOCKED: [{client_ip}] {device_name} ──> {clean_site} ({host})")
                return

            # Quota enforcement
            if not is_background and self.is_quota_exceeded(client_ip):
                used_mb = self.get_daily_usage_mb(client_ip)
                quota_mb = self._quota_cache.get(client_ip, 0)
                quota_html = (
                    b"HTTP/1.1 429 Too Many Requests\r\nContent-Type: text/html\r\n\r\n"
                    b"<!DOCTYPE html><html><body style='font-family:sans-serif;text-align:center;"
                    b"padding:60px;background:#111;color:#fff;'>"
                    b"<h1>\xf0\x9f\x9a\xab Daily Quota Exceeded</h1>"
                    b"<p>Your device has reached its daily data limit.<br>Limit: "
                    + f"{quota_mb:.0f} MB".encode()
                    + b" &nbsp;|&nbsp; Used: "
                    + f"{used_mb:.1f} MB".encode()
                    + b"</p><p style='color:#888;'>Quota resets at midnight. Contact admin to adjust.</p>"
                    b"</body></html>"
                )
                client_socket.sendall(quota_html)
                client_socket.close()
                self.log_event({
                    'timestamp': timestamp,
                    'client_ip': client_ip,
                    'device_name': device_name,
                    'device_type': device_type,
                    'domain': host,
                    'clean_site': clean_site,
                    'is_background': False,
                    'category': category,
                    'method': method,
                    'bytes': 0,
                    'status': 'Blocked',
                    'risk_flag': 'Quota Exceeded',
                    'user_agent': user_agent
                })
                print(f"[{timestamp}] 🚫 QUOTA: [{client_ip}] {device_name} — daily limit {quota_mb:.0f} MB reached")
                return

            # Print terminal notification
            if not is_background:
                dev_icon = "📱" if device_type == "mobile" else "💻"
                print(f"[{timestamp}] {dev_icon} [{client_ip}] {device_name} ──> 🌟 {clean_site} [{category}]")

            # Connect to destination
            remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote_socket.settimeout(12.0)
            remote_socket.connect((host, port))

            bytes_transferred = len(request_data)

            if method == 'CONNECT':
                client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            else:
                remote_socket.sendall(request_data)

            # Tunnel traffic
            sockets = [client_socket, remote_socket]
            active = True
            while active and self.running:
                r_socks, _, _ = select.select(sockets, [], [], 25.0)
                if not r_socks:
                    break
                for s in r_socks:
                    data = s.recv(16384)
                    if not data:
                        active = False
                        break
                    bytes_transferred += len(data)
                    if s is client_socket:
                        remote_socket.sendall(data)
                    else:
                        client_socket.sendall(data)

            self.log_event({
                'timestamp': timestamp,
                'client_ip': client_ip,
                'device_name': device_name,
                'device_type': device_type,
                'domain': host,
                'clean_site': clean_site,
                'is_background': is_background,
                'category': category,
                'method': method,
                'bytes': bytes_transferred,
                'status': 'Allowed',
                'risk_flag': risk_flag,
                'user_agent': user_agent
            })

        except Exception:
            pass
        finally:
            try:
                client_socket.close()
            except:
                pass
            try:
                if remote_socket:
                    remote_socket.close()
            except:
                pass

    def start(self):
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(200)
        print(f"🚀 Gateway Proxy listening on {self.host}:{self.port}")

        while self.running:
            try:
                client_sock, client_addr = self.server_socket.accept()
                t = threading.Thread(target=self.handle_client, args=(client_sock, client_addr), daemon=True)
                t.start()
            except Exception:
                if not self.running:
                    break

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

engine = NetworkMonitoringEngine()
