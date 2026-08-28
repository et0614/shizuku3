# 生UDPでBACnet ReadProperty(AV201 presentValue)を送り、応答の有無だけ確認する診断スクリプト
import socket

# BVLC(Original-Unicast) + NPDU + ReadProperty-Request(analogValue:201, presentValue)
req = bytes.fromhex("810a0011" "0104" "0005010c" "0c008000c9" "1955")

print("probe start", flush=True)
for port in (47809, 47808):
    print(f"send to {port}", flush=True)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))  # 任意ポート
    s.settimeout(3)
    s.sendto(req, ("127.0.0.1", port))
    try:
        data, addr = s.recvfrom(1500)
        print(f"port {port}: RESPONSE {len(data)}bytes from {addr}: {data.hex()}", flush=True)
    except socket.timeout:
        print(f"port {port}: TIMEOUT", flush=True)
    except ConnectionResetError:
        print(f"port {port}: ICMP unreachable", flush=True)
    s.close()
print("probe end", flush=True)
