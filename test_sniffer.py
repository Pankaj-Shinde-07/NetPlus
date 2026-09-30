import time
from scapy.all import sniff, DNS, DNSQR, IP, TCP, UDP, conf

# Disable verbose warnings
conf.verb = 0

def extract_sni(packet):
    """Extract Server Name Indication (SNI) from TLS Client Hello packet."""
    try:
        if packet.haslayer(TCP) and packet.haslayer(Raw):
            load = bytes(packet[TCP].payload)
            # Check for TLS Handshake (0x16) and Client Hello (0x01)
            if len(load) > 5 and load[0] == 0x16 and load[5] == 0x01:
                # Search for Server Name extension
                # TLS Record Header (5 bytes) + Handshake Header (4 bytes)
                pos = 9
                if pos + 34 <= len(load):
                    # Skip Client Version (2) + Random (32)
                    pos += 34
                    # Skip Session ID
                    if pos < len(load):
                        session_id_len = load[pos]
                        pos += 1 + session_id_len
                    # Skip Cipher Suites
                    if pos + 2 <= len(load):
                        cipher_len = int.from_bytes(load[pos:pos+2], "big")
                        pos += 2 + cipher_len
                    # Skip Compression Methods
                    if pos < len(load):
                        comp_len = load[pos]
                        pos += 1 + comp_len
                    # Extension Length
                    if pos + 2 <= len(load):
                        ext_total_len = int.from_bytes(load[pos:pos+2], "big")
                        pos += 2
                        end_pos = pos + ext_total_len
                        while pos + 4 <= end_pos and pos + 4 <= len(load):
                            ext_type = int.from_bytes(load[pos:pos+2], "big")
                            ext_len = int.from_bytes(load[pos+2:pos+4], "big")
                            pos += 4
                            # SNI Extension type is 0x0000
                            if ext_type == 0x00:
                                if pos + 5 <= len(load):
                                    # Server Name List Length (2), Server Name Type (1), HostName Length (2)
                                    name_len = int.from_bytes(load[pos+3:pos+5], "big")
                                    name = load[pos+5:pos+5+name_len].decode('utf-8', errors='ignore')
                                    return name
                            pos += ext_len
    except Exception:
        pass
    return None

from scapy.packet import Raw

def packet_callback(packet):
    if not packet.haslayer(IP):
        return

    src_ip = packet[IP].src
    dst_ip = packet[IP].dst
    pkt_size = len(packet)

    # 1. Check for DNS Queries
    if packet.haslayer(DNS) and packet.haslayer(DNSQR):
        dns_layer = packet[DNS]
        # qr == 0 means DNS Query (from client to resolver)
        if dns_layer.qr == 0:
            query_name = dns_layer.qd.qname.decode('utf-8', errors='ignore').rstrip('.')
            print(f"📡 [DNS QUERY] Client: {src_ip} ──> Searched Domain: {query_name} ({pkt_size} bytes)")
            return

    # 2. Check for TLS SNI (Direct HTTPS domain handshake)
    sni = extract_sni(packet)
    if sni:
        print(f"🔒 [TLS SNI] Client: {src_ip} ──> Accessed HTTPS Domain: {sni} ({pkt_size} bytes)")

print("🚀 Starting test sniffer on all IP traffic...")
print("Waiting for packets (Try opening a website on your mobile phone or browser)...")

# Sniff packets across hotspot and wifi
try:
    sniff(prn=packet_callback, store=0, filter="udp port 53 or tcp port 443", count=20, timeout=30)
    print("✅ Sniffer finished test run successfully!")
except Exception as e:
    print(f"❌ Error during sniff: {e}")
