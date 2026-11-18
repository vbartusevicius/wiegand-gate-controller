"""PlatformIO pre-build script: GATEWAY_FW_VERSION = $FW_VERSION, else UTC commit time."""

from __future__ import annotations

import os
import subprocess
import time

Import("env")  # type: ignore[name-defined]


def commit_version(cwd: str) -> str:
    git = ["git", "-c", "safe.directory=*"]
    try:
        ts = int(
            subprocess.run(
                [*git, "show", "-s", "--format=%ct", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        dirty = subprocess.run(
            [*git, "status", "--porcelain", "--untracked-files=no"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, ValueError, subprocess.CalledProcessError):
        return "dev"
    return time.strftime("%Y.%m.%d.%H%M", time.gmtime(ts)) + ("-dirty" if dirty else "")


fw_ver = os.environ.get("FW_VERSION", "").strip() or commit_version(env.subst("$PROJECT_DIR"))
env.Append(CPPDEFINES=[("GATEWAY_FW_VERSION", env.StringifyMacro(fw_ver))])
print(f"GATEWAY_FW_VERSION = {fw_ver}")
