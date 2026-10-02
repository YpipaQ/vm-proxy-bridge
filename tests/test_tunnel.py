"""转发器：透传、并发、优雅退出、安全红线（拒绝非回环绑定）。"""
import socket
import threading
import time

import pytest

from proxybridge import tunnel


class EchoServer:
    """本机 echo server，代替真实上游。"""
    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        self.threads = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self._stop:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._echo, args=(c,), daemon=True).start()

    @staticmethod
    def _echo(c):
        with c:
            while True:
                d = c.recv(4096)
                if not d:
                    return
                c.sendall(d)

    def close(self):
        self._stop = True
        self.sock.close()


def test_loopback_guard_rejects_non_loopback():
    assert tunnel.is_loopback("127.0.0.1") and tunnel.is_loopback("localhost")
    assert not tunnel.is_loopback("0.0.0.0") and not tunnel.is_loopback("192.168.18.129")
    with pytest.raises(tunnel.TunnelRefused, match="无鉴权"):
        tunnel.run(bind="0.0.0.0:17897", upstream="127.0.0.1:1")


def _start_tunnel(upstream_port, port):
    """在后台线程里起转发器，等端口真的可连再返回（不靠 sleep 猜）。"""
    t = threading.Thread(target=tunnel.run,
                         args=(f"127.0.0.1:{port}", f"127.0.0.1:{upstream_port}"), daemon=True)
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return t
        time.sleep(0.05)
    raise AssertionError(f"转发器端口 {port} 未在 5s 内起来")


def test_relay_roundtrip_and_counters():
    echo = EchoServer()
    port = free_port()
    _start_tunnel(echo.port, port)
    with socket.create_connection(("127.0.0.1", port), timeout=3) as c:
        c.sendall(b"ping-through-tunnel")
        assert c.recv(4096) == b"ping-through-tunnel"
    time.sleep(0.3)
    assert tunnel._counters["accepted"] >= 1
    assert tunnel._counters["bytes"] >= len(b"ping-through-tunnel")
    echo.close()


def test_concurrent_connections():
    echo = EchoServer()
    port = free_port()
    _start_tunnel(echo.port, port)
    results = []
    def one(i):
        with socket.create_connection(("127.0.0.1", port), timeout=3) as c:
            payload = f"msg-{i}".encode()
            c.sendall(payload)
            results.append(c.recv(4096) == payload)
    threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
    [th.start() for th in threads]
    [th.join() for th in threads]
    assert all(results) and len(results) == 8
    echo.close()


def test_upstream_unreachable_is_logged_not_crash():
    port = free_port()
    _start_tunnel(9, port)          # 9 = discard 端口，必然连不上
    with socket.create_connection(("127.0.0.1", port), timeout=3) as c:
        c.sendall(b"x")
        try:
            got = c.recv(4096)
        except ConnectionResetError:
            got = b""                        # 上游不可达时 RST 亦可接受（进程必须活着）
        assert got == b""
    assert tunnel._counters["errors"] >= 1, "上游不可达必须计入 errors 并落日志"


_PORTS = iter(range(17901, 17990))
def free_port():
    return next(_PORTS)
