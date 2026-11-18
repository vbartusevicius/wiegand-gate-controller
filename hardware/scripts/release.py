"""Package a JLCPCB + JLC3DP fabrication release from stored layouts (`eda` container)."""

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import fab_outputs
import jlc_parts
import order_parts
import pcbnew
import yaml

REPO = Path("/work")
sys.path.insert(0, str(REPO / "hardware/circuits"))
from product_spec import load_spec

SPEC = load_spec()
VARIANT = SPEC["active_variant"]
BOARDS = tuple(SPEC["variants"][VARIANT]["boards"])
LIVE = os.environ.get("JLC_LIVE", "1") != "0"


def run(*cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def layout_path(board):
    return REPO / "hardware/layout" / VARIANT / board / f"{board}.kicad_pcb"


def parts(board):
    return json.loads((REPO / "hardware/build" / VARIANT / board / "parts.json").read_text())


def gate(board, out, checks):
    report = out / "drc.json"
    run("kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(layout_path(board)))
    drc = json.loads(report.read_text())
    errors = [v for v in drc["violations"] if v["severity"] == "error"]
    pcb = pcbnew.LoadBoard(str(layout_path(board)))
    pcbnew.ZONE_FILLER(pcb).Fill(pcb.Zones())
    pcb.BuildConnectivity()
    unconn = pcb.GetConnectivity().GetUnconnectedCount(False)
    unsourced = [
        p["ref"] for p in parts(board)
        if not (p["assembly"] == "jlc" and p["lcsc"].startswith("C")
                or p["assembly"] == "hand" and p["mpn"] or p["assembly"] == "none")
    ]
    return (
        [f"{len(errors)} DRC errors"] * bool(errors)
        + [f"{unconn} unrouted"] * bool(unconn)
        + [f"unsourced parts {unsourced}"] * bool(unsourced)
        + [f"{c.ref} ({c.lcsc}): {problem}" for c in checks for problem in c.problems]
    )


def gerber_layers(pcb):
    copper = [pcbnew.LayerName(layer) for layer in pcb.GetEnabledLayers().CuStack()]
    return copper + ["F.Mask", "B.Mask", "F.Paste", "B.Paste", "F.SilkS", "B.SilkS", "Edge.Cuts"]


def assembly_files(board, out, checks):
    checks = [c for c in checks if c.assembly == "jlc"]
    by_ref = {p["ref"]: p for p in parts(board)}
    groups = {}
    for p in by_ref.values():
        if p["assembly"] == "jlc":
            key = (p["value"], p["footprint"].split(":")[1], p["lcsc"])
            groups.setdefault(key, []).append(p["ref"])
    with open(out / f"{board}_bom_jlc.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (value, footprint, lcsc), refs in sorted(groups.items()):
            w.writerow([value, ",".join(sorted(refs)), footprint, lcsc])
    pcb = pcbnew.LoadBoard(str(layout_path(board)))
    with open(out / f"{board}_cpl_jlc.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for c in checks:
            layer = "Bottom" if pcb.FindFootprintByReference(c.ref).IsFlipped() else "Top"
            w.writerow([c.ref, f"{c.placement.x:.3f}mm", f"{c.placement.y:.3f}mm", layer, c.placement.rotation])
    with open(out / f"{board}_assembly_check.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "LCSC", "MPN", "JLCPCB footprint", "Layer", "KiCad rot", "JLC rot", "Stock", "Result"])
        for c in checks:
            fp = pcb.FindFootprintByReference(c.ref)
            kicad = round(fp.GetOrientationDegrees()) % 360
            layer = "Bottom" if fp.IsFlipped() else "Top"
            w.writerow([c.ref, c.lcsc, by_ref[c.ref]["mpn"], c.jlc_footprint, layer, kicad, c.placement.rotation, c.stock, "OK"])


def main(version=VARIANT, boards=BOARDS):
    root = REPO / "hardware/releases" / version
    root.mkdir(parents=True, exist_ok=True)
    failed = False
    for board in boards:
        out = root / board
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        pcb = pcbnew.LoadBoard(str(layout_path(board)))
        checks = jlc_parts.check_board(pcb, parts(board), live=LIVE)
        problems = gate(board, out, checks)
        if problems:
            failed = True
            print(f"{board}: NOT released:")
            for prob in problems:
                print(f"  {prob}")
            continue
        for suffix in (".kicad_pcb", ".kicad_pro", ".kicad_dru"):
            shutil.copy(layout_path(board).with_suffix(suffix), out)
        fab_outputs.export_fab(layout_path(board), parts(board), out, board, gerber_layers(pcb))
        assembly_files(board, out, checks)
        glb = REPO / "hardware/build" / VARIANT / board / f"{board}.glb"
        export_flags = [
            "--grid-origin",
            "--subst-models",
            "--include-tracks",
            "--include-pads",
            "--include-zones",
            "--include-silkscreen",
            "--include-soldermask",
            "--force",
        ]
        run("kicad-cli", "pcb", "export", "glb", *export_flags, "--output", str(glb), str(layout_path(board)))
        shutil.copy(glb, out)
        run("python3", str(REPO / "hardware/scripts/render_board.py"), board, "release")
        shutil.copytree(REPO / "hardware/build" / VARIANT / board / "render/release", out / "renders", ignore=shutil.ignore_patterns("drc.json"))
        print(f"{board}: released cleanly; every JLC part verified pin-for-pin")

    apath = REPO / "hardware/circuits/variants" / VARIANT / "assembly_parts.yaml"
    with open(root / "assembly_parts.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Item", "Qty", "Category", "Part", "Description", "Source"])
        for p in yaml.safe_load(apath.read_text()):
            w.writerow([p["item"], p["qty"], p["category"], p["part"], p["description"], p["source"]])

    enclosure = REPO / "mechanical/build" / VARIANT
    if enclosure.exists():
        shutil.rmtree(root / "enclosure", ignore_errors=True)
        shutil.copytree(enclosure, root / "enclosure")

    if not failed:
        order_parts.write(root)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:] or [VARIANT])))
