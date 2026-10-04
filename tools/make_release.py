# Builds the release zips (one per platform) into dist/.
#   python tools/make_release.py 0.2.1
#   python tools/make_release.py 0.2.1 --skip-build   # reuse existing publish output
# Produces dist/shizuku3-v<ver>-win-x64.zip and dist/shizuku3-v<ver>-osx-arm64.zip.
# The macOS zip stores Unix permissions so that Shizuku3 and the .command
# helpers are executable right after unzipping (a plain Windows zip loses them).
import argparse
import subprocess
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "emulator" / "Shizuku3"
DIST = ROOT / "dist"

# Shared content: tracked files under these paths (gui.ai is the design source, not shipped)
SHARED_DIRS = ["client", "docs", "examples", "gui"]
SHARED_FILES = ["LICENSE", "README.md"]
EXCLUDE = {"gui/gui.ai"}

PLATFORMS = {
    "win-x64": {"exe": "Shizuku3.exe",
                "helpers": ["setup.bat", "start_gui.bat", "console.bat"]},
    "osx-arm64": {"exe": "Shizuku3",
                  "helpers": ["setup.command", "start_gui.command", "console.command"]},
}


def publish_dir(rid):
    return PROJECT / "bin" / "Release" / "net10.0" / "publish" / rid


def publish(rid):
    subprocess.run(["dotnet", "publish", str(PROJECT), "-c", "Release", "-r", rid,
                    "--self-contained", "true", "-p:PublishSingleFile=true",
                    "-p:PublishReadyToRun=false", "-p:PublishTrimmed=false",
                    "-o", str(publish_dir(rid))], check=True)


def shared_files():
    # -z: NUL-separated raw paths (otherwise git quotes the Japanese file names)
    out = subprocess.run(["git", "ls-files", "-z", "--", *SHARED_DIRS], cwd=ROOT, check=True,
                         capture_output=True, text=True, encoding="utf-8").stdout
    files = [p for p in out.split("\0") if p and p not in EXCLUDE]
    return sorted(files + SHARED_FILES)


def make_zip(rid, version):
    cfg = PLATFORMS[rid]
    top = f"shizuku3-v{version}"
    zpath = DIST / f"shizuku3-v{version}-{rid}.zip"
    unix = rid.startswith("osx")
    pub = publish_dir(rid)

    # (path in zip, source file, executable?)
    entries = [(p, ROOT / p, False) for p in shared_files()]
    entries += [(h, ROOT / h, unix) for h in cfg["helpers"]]
    entries += [(cfg["exe"], pub / cfg["exe"], unix),
                ("setting.ini", pub / "setting.ini", False)]

    DIST.mkdir(exist_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, src, exe in entries:
            data = src.read_bytes()
            if src.suffix == ".command":
                data = data.replace(b"\r\n", b"\n")  # bash cannot run CRLF scripts
            info = zipfile.ZipInfo(f"{top}/{arc}", date_time=time.localtime(src.stat().st_mtime)[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            if unix:
                info.create_system = 3  # Unix, so that the mode bits below are honored
                info.external_attr = (0o100755 if exe else 0o100644) << 16
            z.writestr(info, data)
    print(f"{zpath.name}: {len(entries)} files, {zpath.stat().st_size / 1e6:.1f} MB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version", help="e.g. 0.2.1")
    ap.add_argument("--skip-build", action="store_true", help="reuse existing publish output")
    args = ap.parse_args()
    for rid in PLATFORMS:
        if not args.skip_build:
            publish(rid)
        make_zip(rid, args.version)


if __name__ == "__main__":
    main()
