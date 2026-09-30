# 🛰️ NetPlus — Campus Network Intelligence & Monitoring System

![NetPlus](https://img.shields.io/badge/NetPlus-Cyber%20NOC%20v4.0-6366f1?style=for-the-badge&logo=satellite&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10+-3b82f6?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-10b981?style=for-the-badge&logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-f59e0b?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)

> **Real-time campus lab network monitoring** — track every website visited by every connected device through your PC gateway. No packet capture drivers. No admin privileges. Just Python.

---

## 📖 Overview

NetPlus turns your Windows PC into a full network monitoring gateway. Any phone, tablet, or laptop that connects to your PC Mobile Hotspot and sets the HTTP proxy gets **every website request tracked in real-time** — visible instantly on a premium dark-mode dashboard.

### Use Cases
- **College Lab Monitoring** — Track what students browse during lab hours
- **Home Parental Controls** — Monitor and block sites for kids devices
- **Network Research** — Analyze real traffic patterns and bandwidth
- **Cybersecurity Education** — Understand HTTP/HTTPS proxying and traffic analysis

---

## ✨ Features

### Core Monitoring
| Feature | Description |
|---------|-------------|
| Real-time Website Tracking | Every HTTP/HTTPS request captured and displayed instantly |
| Per-device Attribution | Identifies which device made each request |
| Smart Domain Normalization | Maps CDN subdomains to root brands (ytimg.com → youtube.com) |
| Background Noise Filtering | Filters OS telemetry, analytics, ads — show only human-visited sites |
| Device Auto-detection | Reads User-Agent to identify Samsung, Xiaomi, iPhone, Windows PC with OS version |
| WebSocket Live Streaming | New requests appear on dashboard with flash animation in real-time |

### Access Control
| Feature | Description |
|---------|-------------|
| Domain Blocker | Block any domain — device gets a custom 403 page at proxy level |
| Per-device Daily Quotas | Set MB/day data caps — device blocked when limit hit |
| Policy Management UI | Full modal interface to add/remove block rules |

### Analytics
| Feature | Description |
|---------|-------------|
| Live KPI Dashboard | Total visits, bandwidth, devices, blocks — auto-refreshed every 4s |
| Activity Timeline Chart | Live line chart streamed via WebSocket |
| Category Donut Chart | Academic, Social, Gaming, Messaging breakdown |
| Top Sites Bar Chart | Most-visited domains ranked by frequency |
| Hourly Bandwidth Trend | 24-hour bar chart of data consumption |
| Network Latency Monitor | Pings configurable targets every 30s |
| Session Grouping | Groups browsing into sessions (30-min gap = new session) |
| Date Range Filtering | Filter all data by custom from/to date |

### Dashboard UI
| Feature | Description |
|---------|-------------|
| Dark / Light Mode | Toggle with persistent preference |
| Mobile Responsive | Works on tablet and mobile browser |
| Device Matrix Grid | Cards per device with liveness badge, top sites, quota bar |
| Device Drilldown Modal | Full history, sessions, top sites, quota per device |
| HTML Audit Report | Download printable report with all device stats |
| CSV Log Export | Full log export |
| Browser Notifications | Desktop alert when blocked site attempted |
| Animated Particle Background | 80-node network canvas animation |

---

## 🏗️ Architecture

```
+------------------------------------------------------------------+
|                        HOST PC (Windows)                         |
|                                                                  |
|  +-----------------+    +----------------+    +---------------+  |
|  |   engine.py     |<-->|   server.py    |<-->|   static/     |  |
|  | (Proxy Gateway) |    | (FastAPI + WS) |    |  Dashboard    |  |
|  |  Port: 8080     |    |  Port: 5000    |    |  index.html   |  |
|  +-----------------+    +----------------+    +---------------+  |
|         |                       |                                 |
|         v                       v                                 |
|  +----------------------------------------------+                |
|  |         network_logs.db (SQLite)              |                |
|  | access_logs | devices | blocklist | quotas    |                |
|  +----------------------------------------------+                |
+--------------------------------+---------------------------------+
                                 | Windows Mobile Hotspot
                    +------------+------------+
                    v                         v
            Mobile Phone              Laptop / Tablet
        Proxy: 192.168.137.1:8080  Proxy: 192.168.137.1:8080
```

---

## 📁 Project Structure

```
network_monitor/
├── engine.py               # HTTP/HTTPS Proxy Gateway (TCP, multi-threaded)
├── server.py               # FastAPI Web Server + REST API + WebSocket
├── network_logs.db         # SQLite database (auto-created on first run)
├── start_netpulse.bat      # Windows one-click startup script
├── README.md               # This file
└── static/
    ├── index.html          # Dashboard HTML (all modals, panels)
    ├── style.css           # Full design system (dark/light, responsive)
    └── app.js              # Frontend logic (charts, WS, modals, theme)
```

---

## ⚡ Quick Setup

### Prerequisites

```bash
pip install fastapi uvicorn websockets
```

Python 3.10+ required. No other dependencies.

### Step 1 — Enable PC Hotspot

Windows Settings → Network & Internet → Mobile Hotspot → Turn ON

### Step 2 — Start NetPlus

Option A — Double click (easiest):
```
start_netpulse.bat
```

Option B — Terminal:
```bash
cd D:\MDM_Project\network_monitor
python server.py
```

### Step 3 — Open Dashboard

```
http://localhost:5000
```

### Step 4 — Configure Device Proxy

On your phone/tablet (connected to the PC hotspot):

| Setting | Value |
|---------|-------|
| Proxy Mode | Manual |
| Proxy Host | 192.168.137.1 |
| Proxy Port | 8080 |

**Android:** Wi-Fi Settings → Long press network → Modify → Advanced → Proxy: Manual  
**iPhone:** Wi-Fi Settings → info icon → HTTP Proxy → Manual

Start browsing — activity appears instantly on the dashboard!

---

## 🔌 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/stats | KPI metrics. Params: mode, date_from, date_to |
| GET | /api/devices | All devices with liveness, stats, quotas |
| GET | /api/devices/{ip}/activity | Full activity for one device |
| GET | /api/sessions/{ip} | Session-grouped browsing history |
| GET | /api/logs | Filterable log (mode, category, client_ip, status, search, dates) |
| POST | /api/logs/clear | Delete all logs and device records |
| PUT | /api/devices/{ip}/rename | Set custom device nickname |
| GET | /api/policy/rules | List all blocked domains |
| POST | /api/policy/block | Block a domain (proxy enforced) |
| POST | /api/policy/unblock | Remove a block rule |
| GET | /api/quota | List all quotas with usage |
| POST | /api/quota/set | Set daily MB cap for a device |
| DELETE | /api/quota/{ip} | Remove quota for a device |
| GET | /api/bandwidth/trend | Hourly bytes for last 24h |
| GET | /api/latency | Latency history for all targets |
| GET | /api/latency/targets | List configured ping targets |
| POST | /api/latency/targets | Add target {label, host, port} |
| DELETE | /api/latency/targets/{id} | Remove a latency target |
| GET | /api/report | Download HTML audit report |
| WS | /ws | WebSocket for live log streaming |

---

## 🗃️ Database Schema

### access_logs
```sql
id, timestamp, client_ip, device_name, device_type,
domain (raw), clean_site (normalized), is_background,
category, method, bytes_transferred, status, risk_flag, user_agent
```

### devices
```sql
ip, custom_name, auto_name, device_type, first_seen, last_seen
```

### blocklist
```sql
id, domain, reason, created_at
```

### device_quotas
```sql
ip, daily_mb_limit, enabled, created_at
```

### latency_targets
```sql
id, label, host, port, enabled
```

---

## 🧠 How It Works

1. PC shares internet via Windows Mobile Hotspot (192.168.137.1)
2. Devices connect to hotspot and set proxy to 192.168.137.1:8080
3. All HTTP/HTTPS traffic flows through engine.py's TCP proxy
4. For HTTPS: reads the CONNECT hostname:443 header (domain visible before TLS)
5. Domain is normalized, categorized, checked against blocklist + quotas
6. Logged to SQLite and broadcast via WebSocket to the dashboard
7. Dashboard auto-refreshes every 4 seconds; new rows flash in real-time

---

## 🔒 Privacy & Ethics

This tool is intended for network administrators monitoring their own infrastructure.
**Do NOT use to monitor devices without explicit consent of the device owner.**
Unauthorized interception of network traffic may be illegal in your jurisdiction.

---

## 🛣️ Roadmap

- [ ] HTTPS Deep Inspection — Full URL paths via mitmproxy
- [ ] Predictive Bandwidth Forecasting — Moving average model
- [ ] Per-device Time Restrictions — Block social media during lab hours
- [ ] Email Alerts — Notify admin on quota exceeded or blocked site
- [ ] MAC address capture — More reliable device identity than IP

---

## 📄 License

MIT License

---

## 👨‍💻 Author

**Pankaj Shinde**  
GitHub: [@Pankaj-Shinde-07](https://github.com/Pankaj-Shinde-07)

---

*NetPlus Cyber NOC v4.0 · Python · FastAPI · SQLite · Vanilla JS · Chart.js*
