import socket
import select
import threading
import time
import json
from datetime import datetime

# In-memory activity log
activity_logs = []
connected_clients = {}

def categorize_domain(domain):
    """Categorize domain based on keywords."""
    d = domain.lower()
    if any(k in d for k in ['moodle', 'erp', 'college', 'edu', 'github', 'stackoverflow', 'w3schools', 'sciencedirect', 'ieee', 'springer', 'arxiv', 'nptel', 'coursera', 'swayam']):
        return 'Academic & Learning'
    elif any(k in d for k in ['youtube', 'netflix', 'spotify', 'twitch', 'primevideo', 'hotstar', 'instagram', 'facebook', 'twitter', 'tiktok', 'reddit', 'snapchat', 'pinterest']):
        return 'Entertainment & Social'
    elif any(k in d for k in ['steam', 'roblox', 'epicgames', 'riotgames', 'chess.com', 'poki', 'crazygames', 'y8.com', 'krunker', 'freefire', 'pubg', 'valorant']):
        return 'Gaming & Arcade'
    elif any(k in d for k in ['proxy', 'vpn', 'hide', 'tunnel', 'tor', 'nordvpn', 'expressvpn', 'psiphon']):
        return 'Proxy & Bypass'
    elif any(k in d for k in ['google', 'bing', 'yahoo', 'duckduckgo', 'wikipedia']):
        return 'Search & Knowledge'
    elif any(k in d for k in ['whatsapp', 'telegram', 'discord', 'slack', 'zoom', 'teams']):
        return 'Messaging & Collab'
    else:
        return 'General Web'

def handle_client(client_socket, client_address):
    client_ip, client_port = client_address
    try:
        # Read the initial HTTP / HTTPS CONNECT request
        request_data = client_socket.recv(8192)
        if not request_data:
            client_socket.close()
            return

        request_line = request_data.split(b'\r\n')[0].decode('utf-8', errors='ignore')
        parts = request_line.split()
        if len(parts) < 2:
            client_socket.close()
            return

        method, target = parts[0], parts[1]

        # Extract domain & port
        if method.upper() == 'CONNECT':
            # HTTPS Tunneling (CONNECT host:port)
            if ':' in target:
                host, port = target.split(':', 1)
                port = int(port)
            else:
                host, port = target, 443
        else:
            # Plain HTTP (GET http://host/...)
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

        # Categorize
        category = categorize_domain(host)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Track client stats
        if client_ip not in connected_clients:
            connected_clients[client_ip] = {
                'ip': client_ip,
                'total_requests': 0,
                'total_bytes': 0,
                'last_seen': timestamp,
                'top_domains': {}
            }
        
        connected_clients[client_ip]['total_requests'] += 1
        connected_clients[client_ip]['last_seen'] = timestamp
        connected_clients[client_ip]['top_domains'][host] = connected_clients[client_ip]['top_domains'].get(host, 0) + 1

        print(f"[{timestamp}] 📱 [{client_ip}] ──> 🌐 {host} [{category}] ({method})")

        # Connect to target destination server
        remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote_socket.settimeout(10.0)
        remote_socket.connect((host, port))

        bytes_transferred = len(request_data)

        if method.upper() == 'CONNECT':
            # Respond to client that connection is established
            client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            # Forward the original HTTP request
            remote_socket.sendall(request_data)

        # Bi-directional tunnel between client and target
        sockets = [client_socket, remote_socket]
        active = True
        while active:
            r_socks, _, _ = select.select(sockets, [], [], 30.0)
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

        connected_clients[client_ip]['total_bytes'] += bytes_transferred

        log_entry = {
            'timestamp': timestamp,
            'client_ip': client_ip,
            'domain': host,
            'category': category,
            'method': method,
            'bytes': bytes_transferred
        }
        activity_logs.append(log_entry)
        if len(activity_logs) > 5000:
            activity_logs.pop(0)

    except Exception as e:
        # Connection closed or timeout
        pass
    finally:
        try:
            client_socket.close()
        except:
            pass
        try:
            remote_socket.close()
        except:
            pass

def start_proxy_server(host='0.0.0.0', port=8080):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(100)
    print("=" * 65)
    print("🚀 CAMPUS LAB NETWORK MONITORING GATEWAY RUNNING")
    print(f"📡 Listening for connected devices on {host}:{port}")
    print("=" * 65)

    while True:
        client_sock, client_addr = server.accept()
        t = threading.Thread(target=handle_client, args=(client_sock, client_addr), daemon=True)
        t.start()

if __name__ == '__main__':
    start_proxy_server()
