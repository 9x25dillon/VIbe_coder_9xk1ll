"""Play the browser build end to end in headless Chromium.

Build-time tool, stdlib only: a W3C WebDriver client over `urllib`, talking to
`chromedriver`. It serves `build/web` with the production headers from
`serve.py`, so a CSP that blocks WebAssembly fails here rather than on a
phone. Contract tests prove the engine is right; this proves the page boots
the engine, runs code in a sandbox worker, and scores it.

    python3.11 tools/web/smoke.py                   # engine checks
    python3.11 tools/web/smoke.py --shots DIR       # plus UI screenshots
"""

from __future__ import annotations

import argparse
import base64
import functools
import http.server
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from serve import Handler  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

PHONE = {"width": 412, "height": 915, "pixelRatio": 2.625}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class WebDriver:
    """Just enough of the W3C WebDriver protocol to play a level."""

    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.session = ""

    def _call(self, method: str, path: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                reply = json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            reply = json.loads(error.read() or b"{}")
            raise RuntimeError(json.dumps(reply.get("value"), indent=1)[:2000]) from None
        return reply.get("value")

    def start(self, *, mobile: bool, extra: tuple[str, ...] = ()) -> None:
        options = {
            "args": ["--headless=new", "--disable-gpu", "--no-first-run",
                     "--hide-scrollbars", "--force-device-scale-factor=1", *extra],
        }
        chromium = shutil.which("chromium") or shutil.which("chromium-browser")
        if chromium:
            options["binary"] = chromium
        if mobile:
            options["mobileEmulation"] = {
                "deviceMetrics": PHONE,
                "userAgent": ("Mozilla/5.0 (Linux; Android 17; Pixel 10a) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/153.0.0.0 Mobile Safari/537.36"),
            }
        else:
            options["args"].append("--window-size=1280,860")
        value = self._call("POST", "/session", {"capabilities": {"alwaysMatch": {
            "browserName": "chrome", "goog:chromeOptions": options,
            "goog:loggingPrefs": {"browser": "ALL"},
        }}})
        self.session = value["sessionId"]
        self._call("POST", f"/session/{self.session}/timeouts",
                   {"script": 300000, "pageLoad": 60000})

    def get(self, url: str) -> None:
        self._call("POST", f"/session/{self.session}/url", {"url": url})

    def run(self, script: str, *args):
        return self._call("POST", f"/session/{self.session}/execute/sync",
                          {"script": script, "args": list(args)})

    def run_async(self, script: str, *args):
        return self._call("POST", f"/session/{self.session}/execute/async",
                          {"script": script, "args": list(args)})

    def screenshot(self, path: Path) -> None:
        data = self._call("GET", f"/session/{self.session}/screenshot")
        path.write_bytes(base64.b64decode(data))

    def logs(self) -> list:
        try:
            return self._call("POST", f"/session/{self.session}/se/log",
                              {"type": "browser"}) or []
        except RuntimeError:
            return []

    def quit(self) -> None:
        if self.session:
            try:
                self._call("DELETE", f"/session/{self.session}")
            except Exception:  # noqa: BLE001 - best effort
                pass


#: Drives the engine directly: boot, a level solved with its reference, a
#: failing starter, and a boss step. Returns what it saw as JSON.
ENGINE_CHECK = r"""
const done = arguments[arguments.length - 1];
(async () => {
  const t0 = performance.now();
  const { Engine } = await import(new URL("js/engine.js", location.href).href);
  const engine = new Engine({});
  await engine.ready;
  const boot = performance.now() - t0;
  const hello = await engine.call("hello");
  const catalogue = await engine.call("catalogue");
  const t1 = performance.now();
  const opened = await engine.call("open_level", { level_id: "w2-l3-join" });
  const open = performance.now() - t1;
  const reference = arguments[0];
  const t2 = performance.now();
  const ran = await engine.call("run", { play_id: opened.play, code: reference });
  const run = performance.now() - t2;
  const finished = await engine.call("finish", { play_id: opened.play });
  const fight = await engine.call("open_boss", { boss_id: "w1-boss-pipeline" });
  const attempt = await engine.call("boss_attempt", { fight_id: fight.fight });
  const loop = await engine.call("open_level", { level_id: "w1-l1-greet" });
  const t3 = performance.now();
  const hung = await engine.call("run", { play_id: loop.play, code: "def greet(name):\n    while True:\n        pass\n" });
  const hang = performance.now() - t3;
  done(JSON.stringify({
    boot, open, run, hang, hello,
    worlds: catalogue.worlds.length,
    passed: ran.passed, total: ran.total,
    score: finished.score, ops: finished.ops, ref_ops: finished.ref_ops,
    boss: { outcome: attempt.outcome, events: attempt.events.length },
    hung: hung.error_type,
    player: finished.player.cleared,
  }));
})().catch((error) => done(JSON.stringify({ error: String(error.stack || error) })));
"""


def wait_for(driver: WebDriver, condition: str, timeout: float = 90.0) -> None:
    """Poll a JS expression until it is truthy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if driver.run(f"return Boolean({condition});"):
            return
        time.sleep(0.2)
    raise TimeoutError(f"never true: {condition}")


def click(driver: WebDriver, selector: str) -> None:
    driver.run("document.querySelector(arguments[0]).click();", selector)


def type_code(driver: WebDriver, selector: str, code: str) -> None:
    driver.run(
        "const t = document.querySelector(arguments[0]); t.value = arguments[1];"
        "t.dispatchEvent(new Event('input'));", selector, code)


def ui_tour(driver: WebDriver, site: str, shots: Path) -> None:
    """Play through every screen the way a person would, with screenshots."""
    from vibecoder.levels import get_boss, get_level

    shots.mkdir(parents=True, exist_ok=True)
    shot = lambda name: driver.screenshot(shots / f"{name}.png")  # noqa: E731
    driver.get(site)
    time.sleep(0.6)
    shot("00-boot")
    wait_for(driver, "document.querySelector('.level-row')")
    time.sleep(0.5)
    shot("01-home")
    driver.run("document.querySelector('.scroll').scrollTop = 700;")
    time.sleep(0.3)
    shot("02-home-worlds")

    click(driver, ".level-row[data-id='w1-l3-count']")
    wait_for(driver, "document.querySelector('.brief-title')")
    time.sleep(0.4)
    shot("03-brief")
    click(driver, "[data-act=start]")
    wait_for(driver, "document.querySelector('.ed-src')")
    time.sleep(0.4)
    shot("04-play")
    click(driver, "[data-act=run]")
    wait_for(driver, "document.querySelector('.sheet .fail-box, .sheet .verdict.bad')")
    time.sleep(0.5)
    shot("05-fail")
    click(driver, ".sheet [data-act=edit]")
    type_code(driver, ".ed-src", get_level("w1-l3-count").reference)
    time.sleep(0.2)
    shot("06-edited")
    click(driver, "[data-act=run]")
    wait_for(driver, "document.querySelector('.big-total')")
    time.sleep(2.4)
    shot("07-score")
    driver.run("document.querySelector('.scroll').scrollTop = 600;")
    time.sleep(0.3)
    shot("08-score-tips")
    click(driver, "[data-act=replay]")
    wait_for(driver, "document.querySelector('.locals dt')")
    time.sleep(1.2)
    shot("09-replay")

    driver.run("history.back();")
    time.sleep(0.4)
    click(driver, "[data-act=home]")
    wait_for(driver, "document.querySelector('.level-row.boss')")
    click(driver, ".level-row.boss")
    wait_for(driver, "document.querySelector('[data-act=engage]')")
    time.sleep(0.4)
    shot("10-boss-intro")
    click(driver, "[data-act=engage]")
    wait_for(driver, "document.querySelector('.boss-screen')")
    time.sleep(1.5)
    shot("11-boss-live")
    wait_for(driver, "document.querySelector('.sheet .repair-ed')", 120)
    time.sleep(0.6)
    shot("12-boss-repair")
    boss = get_boss("w1-boss-pipeline")
    type_code(driver, ".sheet .ed-src", boss.reference_source())
    click(driver, ".sheet [data-act=repair]")
    driver.run("window.__skip = setInterval(() => { const b = document.querySelector('[data-act=skip]'); if (b) b.click(); }, 150);")
    wait_for(driver, "document.querySelector('.banner')", 180)
    time.sleep(2.2)
    shot("13-boss-end")

    click(driver, "[data-act=home]")
    wait_for(driver, "document.querySelector('.nav')")
    click(driver, "[data-act=nav][data-to=stats]")
    wait_for(driver, "document.querySelector('.mastery-row')")
    time.sleep(0.4)
    shot("14-stats")
    click(driver, "[data-act=nav][data-to=settings]")
    wait_for(driver, "document.querySelector('.seg')")
    time.sleep(0.4)
    shot("15-settings")


def serve(directory: Path, port: int) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(Handler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=ROOT / "build" / "web")
    parser.add_argument("--desktop", action="store_true", help="desktop viewport")
    parser.add_argument("--prefix", default="",
                        help="serve under a subpath (e.g. vibecoder), as a real host would")
    parser.add_argument("--shots", type=Path, help="tour the UI, saving screenshots here")
    parser.add_argument("--chrome-arg", action="append", default=[],
                        help="extra Chromium flag, e.g. --host-resolver-rules=...")
    parser.add_argument("--url", help="check an already-running site (e.g. production) "
                        "instead of serving --dir")
    args = parser.parse_args(argv)

    site_port, driver_port = free_port(), free_port()
    served = args.dir
    if args.prefix:
        # A directory whose only entry is the build under the prefix: every
        # URL the page makes must then be relative, or it 404s here.
        import tempfile
        served = Path(tempfile.mkdtemp(prefix="vibecoder-host-"))
        (served / args.prefix).symlink_to(args.dir.resolve(), target_is_directory=True)
    server = serve(served, site_port) if not args.url else None
    chromedriver = subprocess.Popen(
        ["chromedriver", f"--port={driver_port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    driver = WebDriver(driver_port)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{driver.base}/status", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        driver.start(mobile=not args.desktop, extra=tuple(args.chrome_arg))
        site = f"http://127.0.0.1:{site_port}/" + (f"{args.prefix}/" if args.prefix else "")
        if args.url:
            site = args.url.rstrip("/") + "/"
        if args.shots:
            ui_tour(driver, site, args.shots)
            for entry in driver.logs():
                if entry.get("level") in ("SEVERE", "WARNING"):
                    print("console:", entry.get("message", "")[:300])
            print("TOUR OK", args.shots)
            return 0
        driver.get(site + "build-info.json")
        from vibecoder.levels import get_level  # noqa: E402

        reference = get_level("w2-l3-join").reference
        report = json.loads(driver.run_async(ENGINE_CHECK, reference))
        print(json.dumps(report, indent=1))
        for entry in driver.logs():
            if entry.get("level") in ("SEVERE", "WARNING"):
                print("console:", entry.get("message", "")[:300])
        ok = (not report.get("error") and report["passed"] == report["total"]
              and report["hung"] == "Timeout" and report["boss"]["outcome"] == "wrong")
        print("SMOKE", "OK" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        driver.quit()
        chromedriver.terminate()
        if server is not None:
            server.shutdown()


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
