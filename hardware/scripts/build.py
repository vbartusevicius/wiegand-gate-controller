"""Unified hardware & mechanical build, route, render, release and test pipeline."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def has_module(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def run_eda(boards, *, fresh=False, do_release=False, do_test=False):
    sys.path.insert(0, str(REPO / "hardware/scripts"))
    import gen_circuits
    import layout
    import pcbnew
    import release
    import render_board

    gen_circuits.main()
    os.chdir(REPO)
    variant = layout.VARIANT
    target_boards = boards or layout.SPEC["variants"][variant]["boards"]
    for b in target_boards:
        pcb_path = layout.stored_board_path(b)
        if fresh and pcb_path.exists():
            pcb_path.unlink()
        layout.sync(b)
        board = pcbnew.LoadBoard(str(pcb_path))
        if len(list(board.GetTracks())) == 0 or fresh:
            layout.route(b)
        layout.tidy_silk(b)
        render_board.render(b, "routed", placement=False)
    if do_release:
        rc = release.main(variant, target_boards)
        if rc:
            sys.exit(rc)
    if do_test:
        subprocess.run([sys.executable, "-m", "pytest", "hardware/tests", "-q", "-p", "no:cacheprovider"], cwd=REPO, check=True)


def run_cad(*, do_test=False):
    sys.path.insert(0, str(REPO / "mechanical/scripts"))
    import build_enclosure
    import render_assembly3d

    build_enclosure.export_parts(REPO / "mechanical/build" / build_enclosure.VARIANT)
    render_assembly3d.main()
    if do_test:
        subprocess.run([sys.executable, "-m", "pytest", "mechanical/tests", "-q", "-p", "no:cacheprovider"], cwd=REPO, check=True)


def docker_run(service, cmd):
    ci = ["-e", "JLC_LIVE=0"] if os.environ.get("CI") else []
    full = ["docker", "compose", "--profile", "hardware", "run", "--rm", "-T", *ci, service, cmd]
    subprocess.run(full, cwd=REPO, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boards", nargs="*", default=[])
    parser.add_argument("--eda", action="store_true")
    parser.add_argument("--cad", action="store_true")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--firmware", action="store_true")
    parser.add_argument("--package", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--in-eda", action="store_true")
    parser.add_argument("--in-cad", action="store_true")
    args = parser.parse_args()

    if args.in_eda or has_module("pcbnew"):
        run_eda(args.boards, fresh=args.fresh, do_release=args.release, do_test=args.test)
        return
    if args.in_cad or has_module("cadquery"):
        run_cad(do_test=args.test)
        return

    run_all = not (args.eda or args.cad or args.release or args.test or args.firmware or args.package)
    fresh_flag = " --fresh" if args.fresh else ""
    if args.eda or run_all:
        docker_run("eda", f"python3 hardware/scripts/build.py --in-eda{fresh_flag}")
    if args.cad or run_all:
        docker_run("cad", "python3 hardware/scripts/build.py --in-cad")
    if args.release or run_all:
        docker_run("eda", "python3 hardware/scripts/release.py v1")
    if args.test or run_all:
        docker_run("eda", "python3 -m pytest hardware/tests -q -p no:cacheprovider")
        docker_run("cad", "python3 -m pytest mechanical/tests -q -p no:cacheprovider")
    if args.firmware or run_all:
        subprocess.run([sys.executable, str(REPO / "firmware/scripts/release_firmware.py")], cwd=REPO, check=True)
    if args.package or run_all:
        subprocess.run([sys.executable, str(REPO / "scripts/package_release.py")], cwd=REPO, check=True)


if __name__ == "__main__":
    main()
