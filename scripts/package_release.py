"""Shared GitHub Release asset packager for CI and manual releases (stdlib only).

Builds minimal, self-contained release assets grouped by hardware variant:
  - <project>[-<variant>]-hardware.zip  (boards/<board>/, enclosure/, BOM & order CSVs)
  - usb-flash-firmware.bin              (merged 0x0 USB-C factory image)
  - firmware.bin                        (Web UI OTA application image)
  - SHA256SUMS.txt                      (SHA-256 checksums for all release assets)
Plus a Markdown release body (outside the assets directory) with a | File | Use | table.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROJECT_SLUG = "wiegand-gate-controller"
DEFAULT_SPEC = REPO / "hardware/product/spec.yaml"

HARDWARE_ROOT_FILES = ("assembly_parts.csv", "order_elsewhere.csv", "order_lcsc.csv")
REQUIRED_BOARD_SUFFIXES = (
    "_gerbers.zip",
    "_odb.zip",
    "_bom_jlc.csv",
    "_cpl_jlc.csv",
    "_bom.csv",
    "_cpl.csv",
    ".kicad_pcb",
)
REQUIRED_ENCLOSURE_FILES = (
    "print/enclosure_plate.stl",
    "base.stl",
    "lid.stl",
    "assembly.step",
)
FIRMWARE_FILES = (
    ("usb-flash-firmware.bin", "Merged ESP32-C6 factory image (bootloader + partitions + OTA data + app) for initial USB-C flash at `0x0`"),
    ("firmware.bin", "Application image for Web UI OTA updates (`System -> Firmware Update`)"),
)
FORBIDDEN_TOP_SUFFIXES = {".py", ".sh", ".mjs", ".lpf", ".json", ".elf", ".map", ".svg"}
FORBIDDEN_ARCHIVE_SUFFIXES = {".py", ".sh", ".mjs", ".pyc"}
EXCLUDED_NAMES = {".DS_Store", "__pycache__", "Thumbs.db"}
ZIP_DATE_TIME = (2025, 1, 1, 0, 0, 0)


def parse_spec(spec_path: Path) -> tuple[str, dict[str, list[str]]]:
    """Read active_variant and variants.<name>.boards from spec.yaml without third-party deps."""
    text = spec_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        yaml = None

    if yaml is not None:
        data = yaml.safe_load(text) or {}
        active = str(data.get("active_variant", "v1"))
        variants = {
            str(name): [str(b) for b in (cfg or {}).get("boards", [])]
            for name, cfg in (data.get("variants") or {}).items()
        }
        return active, variants

    active = "v1"
    variants: dict[str, list[str]] = {}
    in_variants = False
    cur_variant: str | None = None
    in_boards_list = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            in_variants = False
            cur_variant = None
            in_boards_list = False
            m = re.match(r"^active_variant:\s*(\S+)$", stripped)
            if m:
                active = m.group(1).strip("\"'")
            elif stripped == "variants:":
                in_variants = True
            continue
        if not in_variants:
            continue
        if indent == 2 and stripped.endswith(":"):
            cur_variant = stripped[:-1].strip("\"'")
            variants[cur_variant] = []
            in_boards_list = False
        elif cur_variant is not None and indent == 4:
            in_boards_list = False
            m_inline = re.match(r"^boards:\s*\[([^\]]*)\]$", stripped)
            if m_inline:
                items = [x.strip().strip("\"'") for x in m_inline.group(1).split(",") if x.strip()]
                variants[cur_variant] = items
            elif stripped == "boards:":
                in_boards_list = True
        elif cur_variant is not None and in_boards_list and stripped.startswith("- "):
            variants[cur_variant].append(stripped[2:].strip().strip("\"'"))
    return active, variants


def default_version(repo: Path = REPO) -> str:
    try:
        ts = int(
            subprocess.run(
                ["git", "show", "-s", "--format=%ct", "HEAD"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, ValueError, subprocess.CalledProcessError):
        return "dev"
    return time.strftime("%Y.%m.%d.%H%M", time.gmtime(ts))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_excluded(rel: Path) -> bool:
    for part in rel.parts:
        if part in EXCLUDED_NAMES or part.startswith("."):
            return True
    return rel.suffix.lower() in FORBIDDEN_ARCHIVE_SUFFIXES


def add_file_to_zip(zf: zipfile.ZipFile, src: Path, arcname: str) -> None:
    info = zipfile.ZipInfo(arcname, date_time=ZIP_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zf.writestr(info, src.read_bytes())


def add_tree_to_zip(zf: zipfile.ZipFile, root: Path, prefix: str) -> int:
    count = 0
    for src in sorted(root.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(root)
        if is_excluded(rel):
            continue
        add_file_to_zip(zf, src, f"{prefix}/{rel.as_posix()}")
        count += 1
    return count


def build_hardware_zip(
    *,
    hardware_dir: Path,
    enclosure_dir: Path,
    boards: list[str],
    out_zip: Path,
) -> None:
    missing: list[str] = []
    for name in HARDWARE_ROOT_FILES:
        if not (hardware_dir / name).is_file():
            missing.append(str(hardware_dir / name))
    for board in boards:
        bdir = hardware_dir / board
        if not bdir.is_dir():
            missing.append(str(bdir))
            continue
        for suffix in REQUIRED_BOARD_SUFFIXES:
            req = bdir / f"{board}{suffix}"
            if not req.is_file():
                missing.append(str(req))
    if not enclosure_dir.is_dir():
        missing.append(str(enclosure_dir))
    else:
        for rel in REQUIRED_ENCLOSURE_FILES:
            if not (enclosure_dir / rel).is_file():
                missing.append(str(enclosure_dir / rel))
    if missing:
        raise FileNotFoundError("Missing required hardware release files:\n  " + "\n  ".join(missing))

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(HARDWARE_ROOT_FILES):
            add_file_to_zip(zf, hardware_dir / name, name)
        for board in sorted(boards):
            add_tree_to_zip(zf, hardware_dir / board, f"boards/{board}")
        add_tree_to_zip(zf, enclosure_dir, "enclosure")


def validate_release_dir(out_dir: Path, expected_assets: list[str]) -> None:
    files = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    expected_all = sorted([*expected_assets, "SHA256SUMS.txt"])
    if files != expected_all:
        raise RuntimeError(f"Release directory mismatch: got {files}, expected {expected_all}")
    for name in files:
        p = out_dir / name
        if name == "SHA256SUMS.txt":
            continue
        if p.suffix.lower() in FORBIDDEN_TOP_SUFFIXES:
            raise RuntimeError(f"Forbidden top-level release file: {name}")
        if re.search(r"-(pcb|enclosure)[^/]*\.zip$", name):
            raise RuntimeError(f"Ungrouped discipline-only archive forbidden: {name}")
        if p.stat().st_size == 0:
            raise RuntimeError(f"Empty release asset: {name}")


def render_release_notes(rows: list[tuple[str, str]]) -> str:
    lines = [
        "## Release Assets",
        "",
        "| File | Use |",
        "| :--- | :--- |",
    ]
    for filename, use in rows:
        lines.append(f"| `{filename}` | {use} |")
    lines.append("")
    return "\n".join(lines)


def package_release(
    *,
    spec_path: Path,
    variants_selected: list[str] | None,
    hardware_dir: Path | None,
    enclosure_dir: Path | None,
    firmware_dir: Path,
    out_dir: Path,
    notes_file: Path,
    version: str,
) -> list[Path]:
    _, spec_variants = parse_spec(spec_path)
    if not spec_variants:
        raise RuntimeError(f"No variants defined in {spec_path}")

    target_variants = variants_selected or list(spec_variants)
    for v in target_variants:
        if v not in spec_variants:
            raise ValueError(f"Unknown variant '{v}'; defined in {spec_path}: {sorted(spec_variants)}")

    out_resolved = out_dir.resolve()
    notes_resolved = notes_file.resolve()
    if notes_resolved == out_resolved or out_resolved in notes_resolved.parents:
        raise ValueError(f"--notes-file ({notes_file}) must be outside --out-dir ({out_dir})")

    multi_variant = len(spec_variants) > 1
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    table_rows: list[tuple[str, str]] = []
    asset_names: list[str] = []

    for variant in target_variants:
        boards = spec_variants[variant]
        hw_src = hardware_dir if (hardware_dir and len(target_variants) == 1) else REPO / "hardware/releases" / variant
        if enclosure_dir and len(target_variants) == 1:
            enc_src = enclosure_dir
        else:
            cad_build = REPO / "mechanical/build" / variant
            enc_src = cad_build if cad_build.is_dir() else hw_src / "enclosure"

        prefix = f"{PROJECT_SLUG}-{variant}" if multi_variant else PROJECT_SLUG
        hw_zip_name = f"{prefix}-hardware.zip"
        build_hardware_zip(
            hardware_dir=hw_src,
            enclosure_dir=enc_src,
            boards=boards,
            out_zip=out_dir / hw_zip_name,
        )
        board_paths = ", ".join(f"`boards/{b}/`" for b in sorted(boards))
        table_rows.append(
            (
                hw_zip_name,
                f"Complete `{variant}` manufacturing & assembly package ({board_paths} Gerbers, ODB++, JLCPCB & generic BOM/CPL, routed PCB, 3D model & renders; `enclosure/` JLC3DP print plate, STLs, STEPs & renders; `order_lcsc.csv`, `order_elsewhere.csv`, `assembly_parts.csv`)",
            )
        )
        asset_names.append(hw_zip_name)

        fw_src = firmware_dir if not multi_variant else (firmware_dir / variant if (firmware_dir / variant).is_dir() else firmware_dir)
        for src_name, desc in FIRMWARE_FILES:
            src_bin = fw_src / src_name
            if not src_bin.is_file():
                raise FileNotFoundError(f"Missing firmware image: {src_bin}")
            dst_name = f"{variant}-{src_name}" if multi_variant else src_name
            shutil.copy2(src_bin, out_dir / dst_name)
            table_rows.append((dst_name, desc))
            asset_names.append(dst_name)

    checksum_lines = [f"{sha256_file(out_dir / name)}  {name}" for name in sorted(asset_names)]
    (out_dir / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    table_rows.append(("SHA256SUMS.txt", "SHA-256 checksums for verifying all release assets"))

    validate_release_dir(out_dir, asset_names)

    notes_file.parent.mkdir(parents=True, exist_ok=True)
    notes_file.write_text(render_release_notes(table_rows), encoding="utf-8")

    print(f"Packaged {PROJECT_SLUG} release {version} -> {out_dir}")
    for name in sorted([*asset_names, "SHA256SUMS.txt"]):
        p = out_dir / name
        print(f"  {name:40s} {p.stat().st_size:>10} bytes")
    print(f"Release notes table -> {notes_file}")
    return [out_dir / name for name in sorted([*asset_names, "SHA256SUMS.txt"])]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default=None, help="Release version string (default: git HEAD UTC timestamp)")
    ap.add_argument("--spec", type=Path, default=DEFAULT_SPEC, help="Path to hardware/product/spec.yaml")
    ap.add_argument("--variant", action="append", dest="variants", help="Hardware variant(s) to package (default: all variants in spec.yaml)")
    ap.add_argument("--hardware-dir", type=Path, default=None, help="Directory with <board>/ and order/assembly CSVs")
    ap.add_argument("--enclosure-dir", type=Path, default=None, help="Directory with enclosure STLs, STEPs, print/, and renders/")
    ap.add_argument("--firmware-dir", type=Path, default=REPO / "firmware/build/release", help="Directory with firmware.bin and usb-flash-firmware.bin")
    ap.add_argument("--out-dir", type=Path, default=REPO / "dist/release", help="Output directory for GitHub Release assets")
    ap.add_argument("--notes-file", type=Path, default=REPO / "dist/release-notes.md", help="Output path for Markdown release notes table")
    args = ap.parse_args(argv)

    package_release(
        spec_path=args.spec,
        variants_selected=args.variants,
        hardware_dir=args.hardware_dir,
        enclosure_dir=args.enclosure_dir,
        firmware_dir=args.firmware_dir,
        out_dir=args.out_dir,
        notes_file=args.notes_file,
        version=args.version or default_version(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
