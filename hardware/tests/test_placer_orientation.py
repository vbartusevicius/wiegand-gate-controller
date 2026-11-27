"""Unit & board-level tests for 2-pin passive orientation, shared-parent attraction, and 180-deg uncrossing."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pcbnew
import pytest
import yaml

REPO = Path("/work")
SPEC = yaml.safe_load((REPO / "hardware/product/spec.yaml").read_text())
VARIANT = SPEC["active_variant"]
PCB_PATH = REPO / "hardware/layout" / VARIANT / "main/main.kicad_pcb"
PLACER_PATH = REPO / "hardware/scripts/placer.py"


@pytest.fixture(scope="module")
def placer_mod():
    """Load placer.py privately without leaving it in sys.modules (preserves Gate 1/2 isolation checks)."""
    spec = importlib.util.spec_from_file_location("_placer_under_test", PLACER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)
    return mod


def _make_rect_pad(fp: pcbnew.FOOTPRINT, num: str, x_mm: float, y_mm: float, sx: float, sy: float, net: pcbnew.NETINFO_ITEM) -> None:
    pad = pcbnew.PAD(fp)
    pad.SetNumber(num)
    pad.SetShape(pcbnew.PAD_SHAPE_RECT)
    pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    pad.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(-y_mm)))
    pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(sx), pcbnew.FromMM(sy)))
    pad.SetLayerSet(pad.SMDMask())
    pad.SetNet(net)
    fp.Add(pad)


def _add_courtyard(fp: pcbnew.FOOTPRINT, hx: float, hy: float) -> None:
    rect = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_RECT)
    rect.SetLayer(pcbnew.F_CrtYd)
    rect.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(-hx), pcbnew.FromMM(-hy)))
    rect.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(hx), pcbnew.FromMM(hy)))
    rect.SetWidth(pcbnew.FromMM(0.05))
    fp.Add(rect)


def _build_ic_and_bypass_board() -> tuple[pcbnew.BOARD, pcbnew.FOOTPRINT, pcbnew.FOOTPRINT]:
    board = pcbnew.BOARD()
    net_vcc = pcbnew.NETINFO_ITEM(board, "+3V3")
    net_gnd = pcbnew.NETINFO_ITEM(board, "GND")
    board.Add(net_vcc)
    board.Add(net_gnd)

    # Board outline 74 x 54 mm
    for (x0, y0), (x1, y1) in (((0, 0), (74, 0)), ((74, 0), (74, 54)), ((74, 54), (0, 54)), ((0, 54), (0, 0))):
        seg = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x0), pcbnew.FromMM(-y0)))
        seg.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(-y1)))
        board.Add(seg)

    # Parent IC U1 with adjacent VCC (top, y=+1.0) and GND (bottom, y=-1.0) pins on its +X edge (2.0 mm pitch)
    u1 = pcbnew.FOOTPRINT(board)
    u1.SetReference("U1")
    u1.SetValue("IC_TEST")
    _add_courtyard(u1, 2.5, 2.5)
    _make_rect_pad(u1, "1", 2.0, 1.0, 1.0, 0.6, net_vcc)
    _make_rect_pad(u1, "2", 2.0, -1.0, 1.0, 0.6, net_gnd)
    u1.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(15.0), pcbnew.FromMM(-25.0)))
    u1.SetLocked(True)
    board.Add(u1)

    # Distant board ground connector J1 (50 mm away in +X) pulling any naive global GND centroid far right & up
    j1 = pcbnew.FOOTPRINT(board)
    j1.SetReference("J1")
    j1.SetValue("GND_DISTANT")
    _add_courtyard(j1, 2.0, 5.0)
    for k, dy in enumerate((-3.0, -1.0, 1.0, 3.0), start=1):
        _make_rect_pad(j1, str(k), 0.0, dy, 1.2, 1.2, net_gnd)
    j1.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(65.0), pcbnew.FromMM(-45.0)))
    j1.SetLocked(True)
    board.Add(j1)

    # 2-pin 0805 bypass capacitor C1 (pad 1=+3V3 at -1.0, pad 2=GND at +1.0 in local 0-deg frame)
    c1 = pcbnew.FOOTPRINT(board)
    c1.SetReference("C1")
    c1.SetValue("100n 50V")
    _add_courtyard(c1, 1.7, 0.95)
    _make_rect_pad(c1, "1", -1.0, 0.0, 1.0, 1.2, net_vcc)
    _make_rect_pad(c1, "2", 1.0, 0.0, 1.0, 1.2, net_gnd)
    board.Add(c1)

    return board, u1, c1


def test_bypass_cap_uncrosses_and_aligns_to_ic_local_vcc_gnd(placer_mod):
    """A bypass cap placed upside-down & off-center beside an IC's VCC/GND pins must flip 180 deg and center."""
    board, u1, c1 = _build_ic_and_bypass_board()

    # Place C1 vertically (rot=90: pad 1 at y=-1.0, pad 2 at y=+1.0 => UPSIDE DOWN relative to U1 VCC=+1, GND=-1!)
    # and shifted +1.4 mm in Y away from U1's VCC/GND midpoint (y=25.0)
    c1.SetOrientationDegrees(90)
    c1.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(19.5), pcbnew.FromMM(-26.4)))

    stats = placer_mod.uncross_and_align_passives(board)
    assert stats["flips"] == 1, f"Expected upside-down bypass cap to flip 180 deg, got {stats}"
    assert stats["aligned"] == 1, f"Expected bypass cap to align to adjacent pin-pair midpoint, got {stats}"

    # Verify pad 1 (+3V3) is now above pad 2 (GND) matching U1.VCC (y=26.0) & U1.GND (y=24.0), never facing J1 (y=45)
    p1 = c1.FindPadByNumber("1").GetPosition()
    p2 = c1.FindPadByNumber("2").GetPosition()
    y_vcc_cap = -pcbnew.ToMM(p1.y)
    y_gnd_cap = -pcbnew.ToMM(p2.y)
    y_vcc_ic = -pcbnew.ToMM(u1.FindPadByNumber("1").GetPosition().y)
    y_gnd_ic = -pcbnew.ToMM(u1.FindPadByNumber("2").GetPosition().y)

    assert y_vcc_cap > y_gnd_cap, f"Cap still upside down: C1.VCC y={y_vcc_cap:.2f}, C1.GND y={y_gnd_cap:.2f}"
    assert math.isclose(-pcbnew.ToMM(c1.GetPosition().y), 0.5 * (y_vcc_ic + y_gnd_ic), abs_tol=0.1)


def test_stage2_shared_parent_attraction_prevents_flipped_bypass_cap(placer_mod, tmp_path):
    """Stage-2 CP-SAT solver must orient a bypass cap toward its parent IC's local VCC/GND pins, not distant GND."""
    board, u1, c1 = _build_ic_and_bypass_board()
    parts_meta = tmp_path / "parts.json"
    parts_meta.write_text(
        json.dumps(
            [
                {"ref": "U1", "place": "ic_blk"},
                {"ref": "J1", "place": "conn_blk"},
                {"ref": "C1", "place": "ic_blk"},
            ]
        )
    )
    plan = {
        "frame": {"size": {"x": 74.0, "y": 54.0}, "silk_labels": []},
        "heights": {"default": 1.4},
        "anchors": {
            "U1": {"x": 15.0, "y": 25.0, "rot": 0, "side": "front"},
            "J1": {"x": 65.0, "y": 45.0, "rot": 0, "side": "front"},
        },
        "keepouts": [],
        "placement": {
            "seed": 42,
            "edge_margin": 1.0,
            "front_blocks": ["ic_blk", "conn_blk"],
            "stage1_time_s": 5.0,
            "stage2_time_s": 5.0,
            "passive_batches": [{"name": "ic_passives", "blocks": ["ic_blk"]}],
        },
    }

    placer_mod.place_board(board, plan, parts_meta)
    p1 = c1.FindPadByNumber("1").GetPosition()
    p2 = c1.FindPadByNumber("2").GetPosition()
    u1_vcc = u1.FindPadByNumber("1").GetPosition()
    u1_gnd = u1.FindPadByNumber("2").GetPosition()

    d_direct = math.hypot(pcbnew.ToMM(p1.x - u1_vcc.x), pcbnew.ToMM(p1.y - u1_vcc.y)) + math.hypot(
        pcbnew.ToMM(p2.x - u1_gnd.x), pcbnew.ToMM(p2.y - u1_gnd.y)
    )
    d_swapped = math.hypot(pcbnew.ToMM(p2.x - u1_vcc.x), pcbnew.ToMM(p2.y - u1_vcc.y)) + math.hypot(
        pcbnew.ToMM(p1.x - u1_gnd.x), pcbnew.ToMM(p1.y - u1_gnd.y)
    )
    assert d_direct < d_swapped, f"Stage-2 placed bypass cap upside-down: direct={d_direct:.2f}mm >= swapped={d_swapped:.2f}mm"
    assert d_direct < 8.0, f"Bypass cap drifted away from U1 VCC/GND pins: total pad distance={d_direct:.2f}mm"


def test_routed_board_has_no_upside_down_symmetric_passives(placer_mod):
    """Committed main.kicad_pcb must have zero symmetric 2-pin passives needing a 180-deg uncross flip."""
    board = pcbnew.LoadBoard(str(PCB_PATH))
    plan = yaml.safe_load((REPO / "hardware/circuits/variants" / VARIANT / "layout_main.yaml").read_text())
    stats = placer_mod.uncross_and_align_passives(board, plan)
    assert stats["flips"] == 0, f"Found {stats['flips']} upside-down 2-pin passives on committed board"
