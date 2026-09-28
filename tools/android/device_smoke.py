"""Run the engine checks inside the app's WebView on a real Android device.

The desktop smoke test (`tools/web/smoke.py`) proves the page works in
Chromium; this proves it works where it ships. It attaches to a *debug* build
(`build_apk.py --debug --install`) over adb and the Chrome DevTools protocol,
evaluates the same engine check, and reports what the phone measured.

Stdlib only, so the WebSocket client below is the minimum the DevTools
protocol needs: one text frame out, text frames in, no extensions.

    python3.11 tools/android/device_smoke.py [--serial SERIAL]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "web"))

APP = "com.astraarcana.vibecoder.debug"
ACTIVITY = "com.astraarcana.vibecoder.MainActivity"
PORT = 9333


class Socket:
    """A WebSocket client just large enough for DevTools."""

    def __init__(self, url: str) -> None:
        host_port, path = url.removeprefix("ws://").split("/", 1)
        host, port = host_port.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=300)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise ConnectionError(response.decode(errors="replace"))
        self.buffer = response.split(b"\r\n\r\n", 1)[1]
        self.sequence = 0

    def _read(self, count: int) -> bytes:
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("devtools socket closed")
            self.buffer += chunk
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def send(self, text: str) -> None:
        payload = text.encode()
        mask = os.urandom(4)
        header = bytes([0x81])
        if len(payload) < 126:
            header += bytes([0x80 | len(payload)])
        elif len(payload) < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", len(payload))
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", len(payload))
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def receive(self) -> str:
        message = b""
        while True:
            first, second = self._read(2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            data = self._read(length)
            opcode = first & 0x0F
            if opcode in (0x1, 0x0):
                message += data
                if first & 0x80:
                    return message.decode()
            elif opcode == 0x8:
                raise ConnectionError("devtools closed the socket")

    def evaluate(self, expression: str):
        self.sequence += 1
        self.send(json.dumps({"id": self.sequence, "method": "Runtime.evaluate", "params": {
            "expression": expression, "awaitPromise": True, "returnByValue": True}}))
        while True:
            reply = json.loads(self.receive())
            if reply.get("id") == self.sequence:
                result = reply.get("result", {})
                if "exceptionDetails" in result:
                    raise RuntimeError(json.dumps(result["exceptionDetails"])[:1500])
                return result.get("result", {}).get("value")


def adb(serial: str | None, *args: str) -> str:
    command = ["adb"] + (["-s", serial] if serial else []) + list(args)
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()


def attach(serial: str | None, *, restart: bool) -> Socket:
    if restart:
        adb(serial, "shell", "am", "force-stop", APP)
        adb(serial, "shell", "am", "start", "-W", "-n", f"{APP}/{ACTIVITY}")
    pid = ""
    for _ in range(50):
        pid = adb(serial, "shell", "pidof", APP)
        if pid:
            break
        time.sleep(0.2)
    adb(serial, "forward", f"tcp:{PORT}", f"localabstract:webview_devtools_remote_{pid}")
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2) as response:
                pages = [t for t in json.loads(response.read()) if t["type"] == "page"]
            if pages:
                return Socket(pages[0]["webSocketDebuggerUrl"])
        except OSError:
            pass
        time.sleep(0.2)
    raise SystemExit("could not attach to the app's WebView; is the debug build installed?")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serial")
    parser.add_argument("--eval", help="evaluate one expression in the page and print it")
    args = parser.parse_args(argv)

    if args.eval:
        print(json.dumps(attach(args.serial, restart=False).evaluate(args.eval), indent=1))
        return 0

    from smoke import ENGINE_CHECK  # noqa: E402
    from vibecoder.levels import get_level  # noqa: E402

    page = attach(args.serial, restart=True)
    # The same check as the desktop run, wrapped as a promise for DevTools.
    wrapped = (
        "new Promise((resolve) => { const arguments_ = [%s, resolve];"
        " (function () { %s }).apply(null, arguments_); })"
        % (json.dumps(get_level("w2-l3-join").reference), ENGINE_CHECK)
    )
    report = json.loads(page.evaluate(wrapped))
    model = adb(args.serial, "shell", "getprop", "ro.product.model")
    release = adb(args.serial, "shell", "getprop", "ro.build.version.release")
    report["device"] = f"{model}, Android {release}"
    print(json.dumps(report, indent=1))
    ok = (not report.get("error") and report["passed"] == report["total"]
          and report["hung"] == "Timeout" and report["boss"]["outcome"] == "wrong")
    print("DEVICE SMOKE", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
