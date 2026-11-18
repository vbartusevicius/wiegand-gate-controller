"""Parts order CSV generator (order_lcsc.csv & order_elsewhere.csv) from a release directory."""

from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
STORE = REPO / "hardware/product/lcsc_store.yaml"
LCSC_IN_PART = re.compile(r"\bLCSC (C\d+)\b")
MOUSER_IN_TEXT = re.compile(r"\bMouser (\d{2,3}-[A-Za-z0-9.\-/]+)")
DIGIKEY_IN_TEXT = re.compile(r"\bDigi-Key (\d{2,4}-[A-Za-z0-9.\-/]+)")
TME_IN_TEXT = re.compile(r"\bTME ([A-Za-z0-9][A-Za-z0-9.\-/]+)")
ELSEWHERE_HEADER = ["Item", "Quantity", "Part", "Mouser", "Digi-Key", "TME", "Other sources"]


def board_boms(release: Path) -> list[tuple[str, dict]]:
    rows = []
    for bom in sorted(release.glob("*/*_bom.csv")):
        board = bom.parent.name
        if bom.name != f"{board}_bom.csv":
            continue
        rows += [(board, r) for r in csv.DictReader(bom.open())]
    return rows


def first(pattern: re.Pattern, *texts: str) -> str:
    for text in texts:
        m = pattern.search(text)
        if m:
            return m.group(1)
    return ""


def every(pattern: re.Pattern, *texts: str) -> str:
    found = []
    for text in texts:
        found += [n.rstrip(".,;") for n in pattern.findall(text) if n.rstrip(".,;") not in found]
    return " / ".join(found)


def orders(release: Path) -> dict[str, list[list]]:
    store = yaml.safe_load(STORE.read_text()) or {}
    subs, away = store.get("substitutes", {}), store.get("elsewhere", {})
    lines: dict[str, dict] = {}
    elsewhere, moved = [], {}

    def add(lcsc, qty, mpn, value, footprint, designators):
        if lcsc in away:
            moved.setdefault(lcsc, [0, []])
            moved[lcsc][0] += qty
            moved[lcsc][1] += designators
            return
        if lcsc in subs:
            sub = subs[lcsc]
            lcsc, mpn, value = sub["lcsc"], sub["mpn"], sub.get("value", value)
        line = lines.setdefault(lcsc, {"qty": 0, "mpn": mpn, "value": value, "footprint": footprint, "refs": []})
        line["qty"] += qty
        line["refs"] += designators

    for board, r in board_boms(release):
        if r["LCSC"]:
            add(r["LCSC"], int(r["Qty"]), r["MPN"], r["Value"], r["Package"], [f"{board}:{x}" for x in r["Designators"].split(",")])
    for p in csv.DictReader((release / "assembly_parts.csv").open()):
        qty = int(p["Qty"])
        if qty == 0 or p["Category"] != "electronics":
            continue
        texts = (p["Part"], p["Source"])
        lcsc = first(LCSC_IN_PART, p["Part"])
        if lcsc:
            add(lcsc, qty, p["Part"].split(" (")[0], "", "", [f"off-board:{p['Item']}"])
        else:
            elsewhere.append([p["Item"], qty, p["Part"], every(MOUSER_IN_TEXT, *texts), every(DIGIKEY_IN_TEXT, *texts),
                              every(TME_IN_TEXT, *texts), p["Source"]])
    for lcsc, (qty, refs) in sorted(moved.items()):
        a = away[lcsc]
        elsewhere.append([" ".join(sorted(refs)), qty, a["part"], a.get("mouser", ""), a.get("digikey", ""), a.get("tme", ""), a["source"]])
    lcsc_rows = [[c, v["qty"], v["mpn"], v["value"], v["footprint"], " ".join(sorted(v["refs"]))] for c, v in sorted(lines.items())]
    return {
        "order_lcsc.csv": [["LCSC Part Number", "Quantity", "Manufacturer Part Number", "Value", "Footprint", "Designators"], *lcsc_rows],
        "order_elsewhere.csv": [ELSEWHERE_HEADER, *elsewhere],
    }


def render(rows: list[list]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def write(release: Path) -> None:
    for name, rows in orders(release).items():
        (release / name).write_text(render(rows))


if __name__ == "__main__":
    release = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "hardware/releases/v1"
    write(release)
