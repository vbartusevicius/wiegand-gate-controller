"""Fab-house neutral PCB / PCBA outputs (`eda` container)."""

from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pcbnew


def run(*cmd: str) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def annotated_board(pcb_path: Path, parts: list[dict], workdir: Path) -> Path:
    by_ref = {p["ref"]: p for p in parts}
    pcb = pcbnew.LoadBoard(str(pcb_path))
    for fp in pcb.GetFootprints():
        p = by_ref.get(fp.GetReference())
        if p is None:
            continue
        for name, value in (("MPN", p.get("mpn", "")), ("Manufacturer", p.get("mfr", "")), ("LCSC", p.get("lcsc", ""))):
            if value:
                fp.SetField(name, value)
        if p["assembly"] == "none":
            fp.SetDNP(True)
            fp.SetExcludedFromBOM(True)
            fp.SetExcludedFromPosFiles(True)
    out = workdir / pcb_path.name
    for suffix in (".kicad_pro", ".kicad_dru"):
        if pcb_path.with_suffix(suffix).exists():
            shutil.copy(pcb_path.with_suffix(suffix), workdir)
    pcbnew.SaveBoard(str(out), pcb)
    return out


def bom(pcb: pcbnew.BOARD, parts: list[dict], path: Path) -> None:
    lines: dict[tuple, list[str]] = {}
    for p in parts:
        if p["assembly"] == "none":
            continue
        fp = pcb.FindFootprintByReference(p["ref"])
        kind = "THT" if fp is not None and fp.GetAttributes() & pcbnew.FP_THROUGH_HOLE else "SMD"
        how = "machine" if p["assembly"] == "jlc" else "hand-fit"
        key = (p["value"], p["footprint"].split(":")[-1], kind, p.get("mfr", ""), p.get("mpn", ""), p.get("lcsc", ""), how)
        lines.setdefault(key, []).append(p["ref"])
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Line", "Qty", "Designators", "Value", "Package", "Type", "Manufacturer", "MPN", "LCSC", "Assembly"])
        for i, (key, refs) in enumerate(sorted(lines.items(), key=lambda kv: min(kv[1])), 1):
            value, package, kind, mfr, mpn, lcsc, how = key
            w.writerow([i, len(refs), ",".join(sorted(refs)), value, package, kind, mfr, mpn, lcsc, how])


def export_fab(pcb_path: Path, parts: list[dict], out: Path, name: str, gerber_layers: list[str]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        board = annotated_board(pcb_path, parts, work)
        run("kicad-cli", "pcb", "export", "odb", "--output", str(out / f"{name}_odb.zip"), "--units", "mm",
            "--compression", "zip", str(board))
        gerbers = work / "gerbers"
        gerbers.mkdir()
        run("kicad-cli", "pcb", "export", "gerbers", "--output", f"{gerbers}/", "--layers", ",".join(gerber_layers),
            "--no-protel-ext", str(board))
        run("kicad-cli", "pcb", "export", "drill", "--output", f"{gerbers}/", "--format", "excellon",
            "--excellon-separate-th", str(board))
        run("kicad-cli", "pcb", "export", "ipcd356", "--output", str(gerbers / f"{name}-netlist.ipc"), str(board))
        with zipfile.ZipFile(out / f"{name}_gerbers.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(gerbers.iterdir()):
                z.write(f, f.name)
        run("kicad-cli", "pcb", "export", "pos", "--output", str(out / f"{name}_cpl.csv"), "--format", "csv",
            "--units", "mm", "--side", "both", "--exclude-dnp", str(board))
        bom(pcbnew.LoadBoard(str(board)), parts, out / f"{name}_bom.csv")
