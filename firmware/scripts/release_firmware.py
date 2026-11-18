"""Build the Wiegand Gateway firmware release into firmware/build/release/ (git-ignored).

    firmware.bin            application image for Web OTA updates
    usb-flash-firmware.bin  merged bootloader + partitions + otadata + app for 0x0 USB flash
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import shutil
import subprocess
import sys
import time
from pathlib import Path

_SCRIPT_FILE = Path(inspect.getfile(lambda: None)).resolve()
REPO = _SCRIPT_FILE.parents[2]
BUILD = REPO / "firmware/.pio/build/release_c6"
OUT = REPO / "firmware/build/release"
IMAGES = [
    ("0x0", "bootloader.bin"),
    ("0x8000", "partitions.bin"),
    ("0x19000", "ota_data_initial.bin"),
    ("0x20000", "firmware.bin"),
]


def container(cmd: str, version: str | None) -> None:
    env = ["-e", f"FW_VERSION={version}"] if version else []
    give_back = 'chown -R "$(stat -c %u:%g /work)" /work/firmware/.pio 2>/dev/null'
    subprocess.run(
        ["docker", "compose", "--profile", "lint", "run", "--rm", "-T", *env, "cpp-lint", f"{cmd}; rc=$?; {give_back}; exit $rc"],
        cwd=REPO,
        check=True,
    )


def default_version() -> str:
    try:
        ts = int(
            subprocess.run(
                ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, ValueError, subprocess.CalledProcessError):
        return "dev"
    return time.strftime("%Y.%m.%d.%H%M", time.gmtime(ts)) + ("-dirty" if dirty else "")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", help="firmware version string")
    args = ap.parse_args()
    version = args.version or default_version()

    subprocess.run([sys.executable, str(REPO / "firmware/scripts/pack_webui.py")], check=True)
    container("cd firmware && pio run -e release_c6", version)
    parts = " ".join(f"{off} .pio/build/release_c6/{name}" for off, name in IMAGES)
    container(
        "cd firmware && pio pkg exec --package tool-esptoolpy -- esptool.py --chip esp32c6 merge_bin "
        "--flash_mode keep --flash_freq keep --flash_size 4MB "
        f"-o .pio/build/release_c6/usb-flash-firmware.bin {parts}",
        None,
    )

    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BUILD / "firmware.bin", OUT / "firmware.bin")
    shutil.copy2(BUILD / "usb-flash-firmware.bin", OUT / "usb-flash-firmware.bin")
    print(f"Wiegand Gateway firmware {version}")
    for name in ("firmware.bin", "usb-flash-firmware.bin"):
        f = OUT / name
        print(f"  {name:24s} {f.stat().st_size:>9} bytes  sha256 {sha256(f)}")


if __name__ == "__main__":
    main()
