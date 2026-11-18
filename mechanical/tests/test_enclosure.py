"""Mechanical & JLC3DP print-rule tests (`cad` container)."""

import json
from pathlib import Path

import cadquery as cq
import yaml

REPO = Path("/work")
SPEC = yaml.safe_load((REPO / "hardware/product/spec.yaml").read_text())
BUILD = REPO / "mechanical/build" / SPEC["active_variant"]


def test_enclosure_solids_and_dimensions():
    summary = json.loads((BUILD / "enclosure_summary.json").read_text())
    assert summary["base_solids"] == 1
    assert summary["lid_solids"] == 1
    assert summary["plate_solids"] == 2
    assert summary["pcb_mm"] == [
        SPEC["boards"]["main"]["max_outline"]["width"],
        SPEC["boards"]["main"]["max_outline"]["height"],
        SPEC["boards"]["main"]["thickness"],
    ]
    w, d, h = summary["outer_mm"]
    env = SPEC["envelope"]
    assert w <= env["outer_width"]
    assert d <= env["outer_depth"]
    assert h <= env["outer_height"]


def test_print_plate_meshes_valid():
    base = cq.importers.importStep(str(BUILD / "base.step"))
    bb = base.val().BoundingBox()
    assert 78.0 < bb.xlen <= 98.0
    assert 58.0 < bb.ylen <= 60.0
    assert 14.0 <= bb.zlen <= 16.0
    lid = cq.importers.importStep(str(BUILD / "lid.step"))
    lbb = lid.val().BoundingBox()
    assert len(lid.solids().vals()) == 1
    assert 20.0 <= lbb.zlen <= 22.0
    assert lbb.zmin >= SPEC["boards"]["main"]["thickness"]
    assert (BUILD / "print/enclosure_plate.stl").stat().st_size > 10000
    assert (BUILD / "print/base_print.stl").stat().st_size > 5000
    assert (BUILD / "print/lid_print.stl").stat().st_size > 5000
    assert (BUILD / "assembly.step").stat().st_size > 50000
    for view in ("base", "lid", "assembly"):
        assert (BUILD / f"renders/{view}.svg").stat().st_size > 2000
        assert (BUILD / f"renders/{view}.png").stat().st_size > 2000
