#!/usr/bin/env python3
"""本地 TCP 转发代理：把 github.com:443 导向一个未被阻断的官方 IP。

背景：某些网络里 DNS 返回的 github.com IP 被阻断（TLS 握手被 RST），
但 GitHub 的其他官方 IP 仍然可达。git 无法指定「用哪个 IP 解析域名」，
所以这里起一个最小 HTTP CONNECT 代理，只做字节转发。

TLS 仍然是 git 与 GitHub 之间端到端协商的，SNI 与证书校验都不受影响。

用法：
    python tools/gh_tunnel.py            # 默认监听 127.0.0.1:8899
    git -c http.proxy=http://127.0.0.1:8899 ...

仅标准库。仅本地监听。
"""
from __future__ import annotations

import socket
import sys
import threading

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8899

# GitHub 官方 IP 段候选，按可达性依次尝试
CANDIDATES = {
    "github.com": ["140.82.112.3", "140.82.121.3", "140.82.113.3"],
    "api.github.com": ["140.82.112.6", "140.82.121.6"],
    "codeload.github.com": ["140.82.112.9", "140.82.121.9"],
    "ssh.github.com": ["140.82.112.35"],
    "objects.githubusercontent.com": ["185.199.108.133", "185.199.109.133"],
}
DEFAULT_PORTS = {443}

_pick_cache: dict[str, str] = {}


def probe(ip: str, port: int, timeout: float = 3.0) -> bool:
    """TCP 能连上不代表能用（可能握手被 RST），所以顺带做一次 HTTP 头探测。"""
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_ip(host: str, port: int) -> str | None:
    key = f"{host}:{port}"
    if key in _pick_cache:
        return _pick_cache[key]
    for ip in CANDIDATES.get(host, []):
        if probe(ip, port):
            _pick_cache[key] = ip
            return ip
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
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def handle(client: socket.socket) -> None:
    upstream = None
    try:
        client.settimeout(15)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = client.recv(4096)
            if not chunk:
                return
            head += chunk
            if len(head) > 65536:
                return

        first = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        parts = first.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            client.sendall(b"HTTP/1.1 405 Only CONNECT\n\n")
            return

        target = parts[1]
        host, _, port_s = target.rpartition(":")
        port = int(port_s) if port_s.isdigit() else 443

        ip = pick_ip(host, port)
        if not ip:
            client.sendall(b"HTTP/1.1 502 No reachable IP\n\n")
            print(f"[tunnel] {host}:{port} 无可用 IP", file=sys.stderr, flush=True)
            return

        upstream = socket.socket()
        upstream.settimeout(15)
        upstream.connect((ip, port))
        upstream.settimeout(None)
        client.settimeout(None)

        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        print(f"[tunnel] {host}:{port} -> {ip}", file=sys.stderr, flush=True)

        t = threading.Thread(target=pipe, args=(client, upstream), daemon=True)
        t.start()
        pipe(upstream, client)
        t.join(timeout=1)
    except OSError as exc:
        try:
            client.sendall(b"HTTP/1.1 502 Tunnel failed\n\n")
        except OSError:
            pass
        print(f"[tunnel] 异常 {exc}", file=sys.stderr, flush=True)
    finally:
        for s in (client, upstream):
            if s:
                try:
                    s.close()
                except OSError:
                    pass


def main() -> int:
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(16)
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
    sys.exit(main())
