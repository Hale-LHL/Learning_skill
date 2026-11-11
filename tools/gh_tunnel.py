#!/usr/bin/env python3
"""本地 TCP 转发代理：把 github.com:443 导向当前可达的 GitHub 官方 IP。

背景：某些网络里 DNS 返回的 github.com IP 被阻断（TCP 能连但 TLS 握手被 RST），
而 GitHub 其他官方 IP 仍可达，且**可用性会随时间变化**（今天能用的明天可能被限）。
git 无法指定「用哪个 IP 解析域名」，所以这里起一个最小 HTTP CONNECT 代理，
只做字节转发。TLS 仍是 git 与 GitHub 端到端协商，SNI 与证书校验不受影响。

关键点：探测必须做**真实 TLS 握手 + HTTP 请求**，只测 TCP 端口是测不准的
（被阻断的 IP 照样能完成 TCP 三次握手，然后在 ClientHello 上被重置）。

用法：
    python tools/gh_tunnel.py            # 起代理，默认 127.0.0.1:8899
    python tools/gh_tunnel.py --scan     # 只扫描各 IP 可用性，不起代理
    git -c http.proxy=http://127.0.0.1:8899 push ...

仅标准库。仅监听 127.0.0.1。
"""
from __future__ import annotations

import socket
import ssl
import sys
import threading
import time

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8899
PROBE_TTL = 120.0  # 探测结果缓存秒数

# GitHub 官方 IP（140.82.112.0/20 与 20.27.177.0/24 段）
CANDIDATES = {
    "github.com": [
        "140.82.121.3",
        "140.82.113.3",
        "140.82.116.3",
        "20.27.177.113",
        "140.82.112.3",
        "140.82.114.3",
    ],
    "api.github.com": [
        "140.82.121.6",
        "140.82.112.6",
        "140.82.113.6",
        "20.27.177.116",
    ],
    "codeload.github.com": [
        "140.82.121.9",
        "140.82.112.9",
        "140.82.113.9",
    ],
    "ssh.github.com": ["140.82.121.35", "140.82.112.35"],
    "objects.githubusercontent.com": [
        "185.199.108.133",
        "185.199.109.133",
        "185.199.110.133",
        "185.199.111.133",
    ],
}

_cache: dict[str, tuple[float, str | None]] = {}
_cache_lock = threading.Lock()


def tls_probe(ip: str, host: str, port: int = 443, timeout: float = 5.0) -> bool:
    """真实握手 + 一个 HEAD 请求。只有拿到 HTTP 响应才算通。"""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((ip, port), timeout=timeout) as raw:
            raw.settimeout(timeout)
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                tls.sendall(
                    f"HEAD / HTTP/1.1\r\nHost: {host}\r\n"
                    f"Connection: close\r\nUser-Agent: gh-tunnel-probe\r\n\r\n".encode()
                )
                return tls.recv(16).startswith(b"HTTP/")
    except (OSError, ssl.SSLError):
        return False


def pick_ip(host: str, port: int = 443, force: bool = False) -> str | None:
    """返回一个可用 IP；结果缓存 PROBE_TTL 秒。失败会依次试下一个并更新缓存。"""
    key = f"{host}:{port}"
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not force and now - hit[0] < PROBE_TTL and hit[1]:
            return hit[1]

    for ip in CANDIDATES.get(host, []):
        if tls_probe(ip, host, port):
            with _cache_lock:
                _cache[key] = (now, ip)
            return ip
        print(f"[tunnel] {ip} 不可用，试下一个", file=sys.stderr, flush=True)

    with _cache_lock:
        _cache[key] = (now, None)
    return None


def pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        # 只关写端，让对端把剩余数据读完再断，避免 TLS 层看到「突然断开」
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(client: socket.socket) -> None:
    upstream = None
    try:
        client.settimeout(20)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = client.recv(4096)
            if not chunk:
                return
            head += chunk
            if len(head) > 65536:
                client.sendall(b"HTTP/1.1 431 Header too large\n\n")
                return

        first = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        parts = first.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            client.sendall(b"HTTP/1.1 405 Only CONNECT\n\n")
            return

        target = parts[1]
        host, _, port_s = target.rpartition(":")
        port = int(port_s) if port_s.isdigit() else 443

        ip = pick_ip(host, port) or pick_ip(host, port, force=True)
        if not ip:
            client.sendall(b"HTTP/1.1 502 No reachable IP\n\n")
            print(f"[tunnel] {host}:{port} 全部 IP 不可用", file=sys.stderr, flush=True)
            return

        upstream = socket.create_connection((ip, port), timeout=15)
        upstream.settimeout(None)
        client.settimeout(None)
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        print(f"[tunnel] {host}:{port} -> {ip}", file=sys.stderr, flush=True)

        back = threading.Thread(target=pipe, args=(client, upstream), daemon=True)
        back.start()
        pipe(upstream, client)
        back.join(timeout=2)
    except OSError as exc:
        try:
            client.sendall(b"HTTP/1.1 502 Tunnel failed\n\n")
        except OSError:
            pass
        print(f"[tunnel] 异常 {exc}", file=sys.stderr, flush=True)
    finally:
        for s in (client, upstream):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


def scan() -> int:
    print("探测 GitHub 官方 IP（真实 TLS + HTTP）：", flush=True)
    for host, ips in CANDIDATES.items():
        for ip in ips:
            t0 = time.time()
            ok = tls_probe(ip, host)
            ms = (time.time() - t0) * 1000
            print(f"  {host:<32} {ip:<16} {'可用' if ok else '不可用':<6} {ms:6.0f} ms", flush=True)
    return 0


def serve() -> int:
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(32)
    print(f"[tunnel] 监听 {LISTEN_HOST}:{LISTEN_PORT}", file=sys.stderr, flush=True)
    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        print("[tunnel] 退出", file=sys.stderr, flush=True)
    finally:
        srv.close()
    return 0


if __name__ == "__main__":
    if "--scan" in sys.argv:
        sys.exit(scan())
    sys.exit(serve())
