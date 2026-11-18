"""Hardware verification tests (`eda` container)."""

import json
import subprocess
from pathlib import Path

import pcbnew
import yaml

REPO = Path("/work")
SPEC = yaml.safe_load((REPO / "hardware/product/spec.yaml").read_text())
VARIANT = SPEC["active_variant"]


def test_board_routed_and_drc_clean():
    pcb_path = REPO / "hardware/layout" / VARIANT / "main/main.kicad_pcb"
    assert pcb_path.exists()
    board = pcbnew.LoadBoard(str(pcb_path))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    assert board.GetConnectivity().GetUnconnectedCount(False) == 0

    report = REPO / "hardware/build" / VARIANT / "main/test_drc.json"
    subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb_path)],
        check=True,
        capture_output=True,
    )
    drc = json.loads(report.read_text())
    errors = [v for v in drc["violations"] if v["severity"] == "error"]
    assert errors == [], f"DRC errors: {errors}"


def test_release_files_exist():
    rel = REPO / "hardware/releases" / VARIANT
    for f in (
        "order_lcsc.csv",
        "order_elsewhere.csv",
        "assembly_parts.csv",
        "main/main_gerbers.zip",
        "main/main_odb.zip",
        "main/main_bom_jlc.csv",
        "main/main_cpl_jlc.csv",
        "main/main_bom.csv",
        "main/main_cpl.csv",
    ):
        assert (rel / f).exists(), f"missing release artifact {f}"
