# Smoke test of an unzipped release folder (used by .github/workflows/release.yml).
#   python tools/smoke_test.py <unzipped release folder>
# Starts the bundled emulator, talks to it over BACnet with the Python client
# (read / step / reset), checks that the web GUI serves its pages, then shuts
# everything down. Exits non-zero on any failure. The client must be installed
# beforehand: pip install "<release>/client[gui]"
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from shizuku3client import FULL_SPEED, Shizuku3Client


def wait_for(what, check, timeout):
    limit = time.time() + timeout
    while True:
        try:
            return check()
        except Exception as ex:
            if time.time() > limit:
                raise TimeoutError(f"{what}: no success within {timeout} s ({ex!r})")
            time.sleep(2)


def test_emulator():
    emu = Shizuku3Client()
    try:
        t0 = wait_for("emulator start", emu.current_time, 180)
        print(f"connected, simulation time {t0}")
        room = emu.read("RoomTemperature")
        print(f"room temperature {room:.1f} C")
        assert -50 < room < 80, f"implausible room temperature {room}"
        t1 = emu.step(minutes=30, acceleration=FULL_SPEED)
        print(f"step 30 min -> {t1}")
        assert (t1 - t0).total_seconds() == 1800, f"step went from {t0} to {t1}"
        start = emu.reset()  # reloads setting.ini next to the executable
        print(f"reset -> {start}")
        assert start == t0, f"reset returned {start}, expected {t0}"
    finally:
        emu.close()


def test_gui(release):
    gui = subprocess.Popen([sys.executable, str(release / "gui" / "server.py"), "--no-browser"])
    try:
        for path in ["/", "/gui.svg", "/web/app.js"]:
            url = f"http://127.0.0.1:8000{path}"
            status = wait_for(f"GUI {path}",
                              lambda: urllib.request.urlopen(url, timeout=5).status, 60)
            print(f"GET {path} -> {status}")
            assert status == 200
    finally:
        gui.terminate()
        gui.wait(10)


def main():
    release = Path(sys.argv[1]).resolve()
    exe = release / ("Shizuku3.exe" if sys.platform == "win32" else "Shizuku3")
    log_path = release / "emulator.log"
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    # stdin stays open: the emulator shuts down when it reads a line from it
    emu_proc = subprocess.Popen([str(exe)], cwd=release, stdin=subprocess.PIPE,
                                stdout=log, stderr=subprocess.STDOUT)
    ok = False
    try:
        test_emulator()
        test_gui(release)
        ok = True
    finally:
        try:
            emu_proc.communicate(b"\n", timeout=15)
        except Exception:
            emu_proc.kill()
        log.close()
        if not ok:
            print("----- emulator output -----")
            print(log_path.read_text(encoding="utf-8", errors="replace"))
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
