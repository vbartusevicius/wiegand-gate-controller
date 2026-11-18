"""Generate KiCad netlists and assembly_parts.yaml for the active variant (`eda` container)."""

import builtins
import importlib
import io
import json
import logging
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "circuits"))
(Path(__file__).resolve().parents[1] / "build").mkdir(exist_ok=True)
os.chdir(Path(__file__).resolve().parents[1] / "build")

import common
from product_spec import load_spec
from skidl import ERC, KICAD9, generate_netlist, reset, set_default_tool

BUILD = common.REPO_ROOT / "hardware" / "build"
SPEC = common.SPEC_PATH
DERIVED_BEGIN = "# --- BEGIN GENERATED (hardware/scripts/gen_circuits.py) ---"
DERIVED_END = "# --- END GENERATED ---"

UTILITY_ITEMS = [
    {
        "item": "External 2.4 GHz U.FL Adhesive Antenna (optional, recommended)",
        "qty": 1,
        "part": "Molex 1461530100 (100 mm coax, LCSC C152350) or 1461530200 (200 mm)",
        "description": "Optional adhesive flex dipole; plugs into XIAO U.FL jack, routes out the ANT slot, and sticks outside metal gate cabinets (firmware Auto-selects via RSSI)",
        "source": "Mouser 538-1461530100 / Digi-Key WM12218-ND / LCSC C152350",
        "category": "electronics",
    },
    {
        "item": "3D-printed enclosure (base + lid print plate)",
        "qty": 1,
        "part": "enclosure/print/enclosure_plate.stl (MJF PA12 or UV-stabilised ASA)",
        "description": "Compact 78.8 x 58.8 x 27.7 mm enclosure (94.8 mm across ears) sized for the ROGER BH30 battery bay",
        "source": "JLC3DP (PA12 / ASA)",
        "category": "printed",
    },
    {
        "item": "M3 Stainless Fastener Set",
        "qty": 1,
        "part": "4x M3x12 DIN 912 / ISO 4762 socket head screws + 4x M3 hex nuts (DIN 934)",
        "description": "Secures the enclosure lid to base through the 4 corner bosses",
        "source": "Local hardware / McMaster-Carr",
        "category": "utility",
    },
]


def generate_board(variant, name, build_fn):
    reset()
    set_default_tool(KICAD9)
    bdir = BUILD / variant / name
    bdir.mkdir(parents=True, exist_ok=True)
    import skidl as skidl_mod

    skidl_mod.config.backup_lib_file_name = str(BUILD / "gen_circuits_sklib.py")
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    skidl_logger = logging.getLogger("skidl")
    skidl_logger.addHandler(handler)
    with redirect_stdout(buf), redirect_stderr(buf):
        build_fn()
        ERC()
        generate_netlist(file_=str(bdir / f"{name}.net"))
    skidl_logger.removeHandler(handler)
    out = buf.getvalue()
    (bdir / "skidl_log.txt").write_text(out)
    parts = [
        {
            "ref": p.ref,
            "value": p.value,
            "footprint": p.footprint,
            "place": p.fields.get("Place", "misc"),
            "lcsc": p.fields.get("LCSC", ""),
            "mpn": p.fields.get("Manufacturer_Part_Number", ""),
            "mfr": p.fields.get("Manufacturer", ""),
            "assembly": p.fields.get("Assembly", "jlc"),
            "source": p.fields.get("Source", ""),
            "footprint_ref": p.fields.get("Footprint_Reference", ""),
            "stock_optional": p.fields.get("Stock_Optional", "") == "yes",
            "pins": {str(pin.num): pin.name for pin in p.pins},
        }
        for p in builtins.default_circuit.parts
        if not p.ref.startswith("#")
    ]
    (bdir / "parts.json").write_text(json.dumps(parts, indent=1))
    return out


def collect_assembly_parts(variant, spec):
    boards = spec["variants"][variant]["boards"]
    hand_by_mpn = {}
    for b in boards:
        for p in json.loads((BUILD / variant / b / "parts.json").read_text()):
            if p["assembly"] == "hand":
                entry = hand_by_mpn.setdefault(p["mpn"], {"p": p, "locs": []})
                entry["locs"].append(f"{b} {p['ref']}")
    items = []
    if "102010636" in hand_by_mpn:
        locs = ", ".join(hand_by_mpn["102010636"]["locs"])
        items.append(
            {
                "item": "MCU module (socketed)",
                "qty": len(hand_by_mpn["102010636"]["locs"]),
                "part": "Seeed Studio XIAO ESP32C6 Pre-Soldered (SKU 102010636)",
                "description": f"Plugs into two 1x7 2.54 mm female sockets ({locs})",
                "source": "Digi-Key 1597-102010636-ND / Mouser / Seeed Studio",
                "category": "electronics",
            }
        )
        items.append(
            {
                "item": "XIAO sockets (hand-soldered)",
                "qty": 2 * len(hand_by_mpn["102010636"]["locs"]),
                "part": "Samtec CES-107-02-G-S (1x7 2.54 mm female header, 5.08 mm tall)",
                "description": f"Female sockets soldered onto {locs}",
                "source": "Mouser 200-CES10702GS / Digi-Key",
                "category": "electronics",
            }
        )
    if "2086-1202/700-000/997-604" in hand_by_mpn:
        locs = ", ".join(hand_by_mpn["2086-1202/700-000/997-604"]["locs"])
        items.append(
            {
                "item": "2-pole 3.5 mm SMD push-in terminal block",
                "qty": len(hand_by_mpn["2086-1202/700-000/997-604"]["locs"]),
                "part": "WAGO 2086-1202/700-000/997-604 (2-pole 3.5 mm SMD push-in)",
                "description": f"Hand-soldered onto {locs} (not stocked at JLCPCB)",
                "source": "Digi-Key 2946-2086-1202/700-000/997-604CT-ND / Mouser",
                "category": "electronics",
            }
        )
    items.extend(UTILITY_ITEMS)
    out = common.REPO_ROOT / "hardware/circuits/variants" / variant / "assembly_parts.yaml"
    out.write_text("# Generated by hardware/scripts/gen_circuits.py\n" + yaml.safe_dump(items, sort_keys=False))


def main():
    spec = load_spec()
    variant = spec["active_variant"]
    from blocks import mcu_xiao

    net_classes_by_board = {}
    for name in spec["variants"][variant]["boards"]:
        mod = importlib.import_module(f"variants.{variant}.{name}")
        log = generate_board(variant, name, mod.build)
        net_classes_by_board[name] = mod.NET_CLASSES
        errors = [
            line for line in log.splitlines()
            if ("ERROR" in line and not ("No footprint for" in line and "/#" in line))
        ]
        print(f"{variant}/{name}: {len(errors)} SKiDL errors")
        for line in errors:
            print(" ", line)
        if errors:
            sys.exit(1)

    text = SPEC.read_text()
    derived = {"mcu_pins": mcu_xiao.MCU_PINS, "net_classes": net_classes_by_board}
    block = DERIVED_BEGIN + "\n" + yaml.safe_dump({"derived": derived}, sort_keys=False) + DERIVED_END + "\n"
    if DERIVED_BEGIN in text and DERIVED_END in text:
        text = text[: text.index(DERIVED_BEGIN)] + block
    else:
        text = text.rstrip("\n") + "\n\n" + block
    SPEC.write_text(text)
    collect_assembly_parts(variant, spec)


if __name__ == "__main__":
    main()
