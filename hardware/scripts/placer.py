"""Deterministic 2-stage Google OR-Tools CP-SAT PCB component placer (`eda` container)."""

from __future__ import annotations

import itertools
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pcbnew
from ortools.sat.python import cp_model

GRID_MM = 0.05
ROTS = (0, 90, 180, 270)
GLOBAL_RAILS = {"+3V3", "+5V", "+5V_XIAO", "+12V_RDR", "+12V_RDR_OUT", "VIN_PROT"}
CRITICAL_NET_SUFFIXES = ("_SW", "_BST", "_FB", "_COMP", "_CC", "_RT", "_EN")


def g_lo(mm: float) -> int:
    return math.floor(round(mm / GRID_MM, 6))


def g_hi(mm: float) -> int:
    return math.ceil(round(mm / GRID_MM, 6))


def g_near(mm: float) -> int:
    return round(mm / GRID_MM)


def set_side(fp: pcbnew.FOOTPRINT, back: bool) -> None:
    if fp.IsFlipped() != back:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)


@dataclass(frozen=True)
class OrientGeom:
    dx0: float
    dy0: float
    dx1: float
    dy1: float
    pads: dict[str, list[tuple[float, float, str]]]
    drill_box: tuple[float, float, float, float] | None


def measure_footprint(fp: pcbnew.FOOTPRINT, side: str, rots: tuple[int, ...] = ROTS) -> dict[int, OrientGeom]:
    orig_pos = fp.GetPosition()
    orig_flip = fp.IsFlipped()
    orig_rot = fp.GetOrientationDegrees()
    back = side == "back"
    out: dict[int, OrientGeom] = {}
    try:
        for rot in rots:
            fp.SetPosition(pcbnew.VECTOR2I(0, 0))
            set_side(fp, back)
            fp.SetOrientationDegrees(rot)
            fp.BuildCourtyardCaches()
            bb = fp.GetCourtyard(pcbnew.B_CrtYd if back else pcbnew.F_CrtYd).BBox()
            cu_layer = pcbnew.B_Cu if back else pcbnew.F_Cu
            pads: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
            drill_pts: list[tuple[float, float, float, float]] = []
            for pad in fp.Pads():
                if pad.IsOnLayer(cu_layer):
                    bb.Merge(pad.GetBoundingBox())
                p = pad.GetPosition()
                px, py = pcbnew.ToMM(p.x), -pcbnew.ToMM(p.y)
                net = pad.GetNetname()
                if net:
                    pads[net].append((px, py, pad.GetNumber()))
                if pad.GetDrillSize().x > 0:
                    pbb = pad.GetBoundingBox()
                    drill_pts.append(
                        (
                            pcbnew.ToMM(pbb.GetLeft()),
                            -pcbnew.ToMM(pbb.GetBottom()),
                            pcbnew.ToMM(pbb.GetRight()),
                            -pcbnew.ToMM(pbb.GetTop()),
                        )
                    )
            if str(fp.GetFPID().GetLibItemName()) == "XIAO_ESP32C6_Header":
                fab = pcbnew.B_Fab if back else pcbnew.F_Fab
                for item in fp.GraphicalItems():
                    if item.GetLayer() == fab and item.Type() == pcbnew.PCB_SHAPE_T:
                        bb.Merge(item.GetBoundingBox())
            dbox = None
            if drill_pts:
                dbox = (
                    min(b[0] for b in drill_pts),
                    min(b[1] for b in drill_pts),
                    max(b[2] for b in drill_pts),
                    max(b[3] for b in drill_pts),
                )
            out[rot] = OrientGeom(
                dx0=pcbnew.ToMM(bb.GetLeft()),
                dy0=-pcbnew.ToMM(bb.GetBottom()),
                dx1=pcbnew.ToMM(bb.GetRight()),
                dy1=-pcbnew.ToMM(bb.GetTop()),
                pads=dict(pads),
                drill_box=dbox,
            )
    finally:
        fp.SetPosition(orig_pos)
        set_side(fp, orig_flip)
        fp.SetOrientationDegrees(orig_rot)
    return out


def disjoint_fixed_intervals(
    model: cp_model.CpModel,
    rects_mm: list[tuple[float, float, float, float]],
    prefix: str,
) -> tuple[list[cp_model.IntervalVar], list[cp_model.IntervalVar]]:
    int_rects = []
    for x0, y0, x1, y1 in rects_mm:
        gx0, gy0 = g_lo(x0), g_lo(y0)
        gx1, gy1 = max(gx0 + 1, g_hi(x1)), max(gy0 + 1, g_hi(y1))
        int_rects.append((gx0, gy0, gx1, gy1))
    ys = sorted({r[1] for r in int_rects} | {r[3] for r in int_rects})
    active: dict[tuple[int, int], tuple[int, int]] = {}
    disjoint: list[tuple[int, int, int, int]] = []
    for ya, yb in itertools.pairwise(ys):
        xs = sorted((r[0], r[2]) for r in int_rects if r[1] <= ya and yb <= r[3])
        merged_x: list[tuple[int, int]] = []
        for xa, xb in xs:
            if merged_x and xa <= merged_x[-1][1]:
                merged_x[-1] = (merged_x[-1][0], max(merged_x[-1][1], xb))
            else:
                merged_x.append((xa, xb))
        next_active: dict[tuple[int, int], tuple[int, int]] = {}
        for xspan in merged_x:
            if xspan in active and active[xspan][1] == ya:
                next_active[xspan] = (active[xspan][0], yb)
            else:
                next_active[xspan] = (ya, yb)
        for xspan, (y_start, y_end) in active.items():
            if xspan not in next_active or next_active[xspan][0] != y_start:
                disjoint.append((xspan[0], y_start, xspan[1], y_end))
        active = next_active
    for xspan, (y_start, y_end) in active.items():
        disjoint.append((xspan[0], y_start, xspan[1], y_end))

    ivs_x, ivs_y = [], []
    for idx, (gx0, gy0, gx1, gy1) in enumerate(disjoint):
        ivs_x.append(model.NewFixedSizeIntervalVar(gx0, gx1 - gx0, f"{prefix}_fx_{idx}"))
        ivs_y.append(model.NewFixedSizeIntervalVar(gy0, gy1 - gy0, f"{prefix}_fy_{idx}"))
    return ivs_x, ivs_y


def net_weight(net: str) -> int:
    if net == "GND":
        return 0
    if net.endswith(("_COMP", "_CC", "_FB", "_BST", "_RT", "_SW")):
        return 48
    if net.endswith("_EN"):
        return 28
    if net in GLOBAL_RAILS:
        return 2
    if net.startswith(("VIN_", "R1_", "R2_", "WG_", "IN1_", "IN2_", "IN3_", "LED_", "I2C_")):
        return 12
    return 10


def is_passive(ref: str) -> bool:
    return ref.startswith(("R", "C")) and ref[1:].isdigit()


def stage1_halo(ref: str, fp_name: str) -> float:
    if ref in ("U1", "U2"):
        return 1.65
    if ref in ("U4", "U6"):
        return 1.15
    if ref.startswith("U"):
        return 0.75
    if ref.startswith("K"):
        return 0.30
    if ref.startswith(("L", "F")):
        return 0.60
    if "D_SMA" in fp_name:
        return 0.45
    return 0.45


def stage2_escape_halo(ref: str) -> float:
    if ref in ("U1", "U2", "U4", "U5", "U6") or ref.startswith("J"):
        return 0.5
    if ref.startswith(("K", "L", "F", "U", "Q", "D")):
        return 0.3
    return 0.2


def add_fixed_obstacles(
    model: cp_model.CpModel,
    board: pcbnew.BOARD,
    placed_refs: set[str],
    plan: dict,
    halo_fn,
) -> tuple[list[cp_model.IntervalVar], list[cp_model.IntervalVar], list[cp_model.IntervalVar], list[cp_model.IntervalVar]]:
    f_rects: list[tuple[float, float, float, float]] = []
    b_rects: list[tuple[float, float, float, float]] = []
    for k in plan.get("keepouts", []):
        r = (float(k["x0"]), float(k["y0"]), float(k["x1"]), float(k["y1"]))
        if k["side"] in ("front", "both"):
            f_rects.append(r)
        if k["side"] in ("back", "both"):
            b_rects.append(r)

    for lbl in plan["frame"].get("silk_labels", []):
        if lbl.get("layer", "F.SilkS") == "F.SilkS":
            half_w = max(0.7, 0.32 * len(str(lbl["text"])))
            f_rects.append((lbl["x"] - half_w, lbl["y"] - 0.45, lbl["x"] + half_w, lbl["y"] + 0.45))

    for ref in sorted(placed_refs):
        fp = board.FindFootprintByReference(ref)
        side = "back" if fp.IsFlipped() else "front"
        rot = round(fp.GetOrientationDegrees()) % 360
        cx, cy = pcbnew.ToMM(fp.GetPosition().x), -pcbnew.ToMM(fp.GetPosition().y)
        geom = measure_footprint(fp, side, (rot,))[rot]
        halo = halo_fn(ref)
        box = (cx + geom.dx0 - halo, cy + geom.dy0 - halo, cx + geom.dx1 + halo, cy + geom.dy1 + halo)
        if side == "front":
            f_rects.append(box)
        else:
            b_rects.append(box)

        if ref == "U3":
            for row_pads in (range(1, 8), range(8, 15)):
                pts = []
                for pnum in row_pads:
                    pad = fp.FindPadByNumber(str(pnum))
                    pbb = pad.GetBoundingBox()
                    pts.append(
                        (
                            pcbnew.ToMM(pbb.GetLeft()),
                            -pcbnew.ToMM(pbb.GetBottom()),
                            pcbnew.ToMM(pbb.GetRight()),
                            -pcbnew.ToMM(pbb.GetTop()),
                        )
                    )
                b_rects.append(
                    (
                        min(b[0] for b in pts) - 0.45,
                        min(b[1] for b in pts) - 0.45,
                        max(b[2] for b in pts) + 0.45,
                        max(b[3] for b in pts) + 0.45,
                    )
                )
        elif geom.drill_box is not None:
            dx0, dy0, dx1, dy1 = geom.drill_box
            xbox = (cx + dx0 - 0.5, cy + dy0 - 0.5, cx + dx1 + 0.5, cy + dy1 + 0.5)
            if side == "front":
                b_rects.append(xbox)
            else:
                f_rects.append(xbox)

    fx, fy = disjoint_fixed_intervals(model, f_rects, "fobs")
    bx, by = disjoint_fixed_intervals(model, b_rects, "bobs")
    return fx, fy, bx, by


def fixed_pad_coords(board: pcbnew.BOARD, placed_refs: set[str]) -> dict[str, list[tuple[int, int, str, str]]]:
    by_net: dict[str, list[tuple[int, int, str, str]]] = defaultdict(list)
    seen = set()
    for ref in sorted(placed_refs):
        fp = board.FindFootprintByReference(ref)
        for pad in fp.Pads():
            net = pad.GetNetname()
            num = pad.GetNumber()
            if not net or not num or (ref, num, net) in seen:
                continue
            seen.add((ref, num, net))
            p = pad.GetPosition()
            by_net[net].append((g_near(pcbnew.ToMM(p.x)), g_near(-pcbnew.ToMM(p.y)), ref, num))
    return by_net


def solve_cp_sat(model: cp_model.CpModel, time_limit_s: float, seed: int, label: str) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.random_seed = int(seed)
    solver.parameters.num_search_workers = 4
    solver.parameters.interleave_search = True
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"CP-SAT placement failed in {label}: {solver.StatusName(status)}")
    print(
        f"  [{label}] status={solver.StatusName(status)} "
        f"obj={solver.ObjectiveValue():.0f} wall={solver.WallTime():.2f}s"
    )
    return solver


def place_board(board: pcbnew.BOARD, plan: dict, parts_meta_path: Path) -> None:
    parts_meta = {p["ref"]: p for p in json.loads(parts_meta_path.read_text())}
    w_mm, h_mm = float(plan["frame"]["size"]["x"]), float(plan["frame"]["size"]["y"])
    gw, gh = g_near(w_mm), g_near(h_mm)
    pcfg = plan["placement"]
    seed = int(pcfg.get("seed", 42))
    edge_margin = float(pcfg.get("edge_margin", 0.7))
    heights = plan.get("heights", {})
    b_max_h = float(pcfg.get("back_max_height", 2.5))
    f_max_h = float(pcfg.get("front_max_height", 18.5))

    # 1. Place locked mechanical/UI anchors
    anchors = plan["anchors"]
    placed_refs: set[str] = set()
    for ref, a in anchors.items():
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            raise KeyError(f"Anchor {ref} missing from board netlist")
        set_side(fp, a.get("side", "front") == "back")
        fp.SetOrientationDegrees(a.get("rot", 0))
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(a["x"]), pcbnew.FromMM(-a["y"])))
        fp.SetLocked(True)
        placed_refs.add(ref)

    front_refs = set(pcfg.get("front_refs", []))
    front_blocks = set(pcfg.get("front_blocks", []))
    block_regions = pcfg.get("block_regions", {})
    ref_regions = pcfg.get("ref_regions", {})
    ref_rotations = pcfg.get("allowed_rotations", {})

    def part_side(ref: str) -> str:
        blk = parts_meta[ref]["place"]
        side = "front" if (ref in front_refs or blk in front_blocks) else "back"
        h_part = float(heights.get(ref, heights.get("default", 1.4)))
        if side == "back" and h_part > b_max_h:
            raise ValueError(f"{ref} height {h_part} mm exceeds B.Cu clearance limit {b_max_h} mm")
        if side == "front" and h_part > f_max_h:
            raise ValueError(f"{ref} height {h_part} mm exceeds F.Cu cavity height {f_max_h} mm")
        return side

    def region_for(ref: str) -> dict:
        if ref in ref_regions:
            return ref_regions[ref]
        return block_regions.get(parts_meta[ref]["place"], {})

    all_refs = sorted(fp.GetReference() for fp in board.Footprints())
    stage1_refs = [r for r in all_refs if r not in placed_refs and not is_passive(r)]
    passive_refs = [r for r in all_refs if r not in placed_refs and is_passive(r)]

    # 2. Stage 1: Solve all active ICs, relays, inductors, fuses, optos, BJTs, and diodes simultaneously
    m1 = cp_model.CpModel()
    fx, fy, bx, by = add_fixed_obstacles(
        m1, board, placed_refs, plan, lambda r: 0.4 if r.startswith("J") else 0.45
    )
    fixed_pads = fixed_pad_coords(board, placed_refs)

    s1_vars = {}
    dyn_pads: dict[str, list[tuple[cp_model.IntVar, cp_model.IntVar, str]]] = defaultdict(list)

    for ref in stage1_refs:
        fp = board.FindFootprintByReference(ref)
        fp_name = str(fp.GetFPID().GetLibItemName())
        side = part_side(ref)
        reg = region_for(ref)
        rx0 = g_hi(max(edge_margin, float(reg.get("x0", edge_margin))))
        ry0 = g_hi(max(edge_margin, float(reg.get("y0", edge_margin))))
        rx1 = g_lo(min(w_mm - edge_margin, float(reg.get("x1", w_mm - edge_margin))))
        ry1 = g_lo(min(h_mm - edge_margin, float(reg.get("y1", h_mm - edge_margin))))

        rots = tuple(ref_rotations.get(ref, ROTS))
        geoms = measure_footprint(fp, side, rots)
        halo = stage1_halo(ref, fp_name)

        cx = m1.NewIntVar(rx0, rx1, f"cx_{ref}")
        cy = m1.NewIntVar(ry0, ry1, f"cy_{ref}")
        xs = m1.NewIntVar(-200, gw + 200, f"xs_{ref}")
        ys = m1.NewIntVar(-200, gh + 200, f"ys_{ref}")
        xw = m1.NewIntVar(1, gw + 400, f"xw_{ref}")
        yw = m1.NewIntVar(1, gh + 400, f"yw_{ref}")
        xe = m1.NewIntVar(-200, gw + 200, f"xe_{ref}")
        ye = m1.NewIntVar(-200, gh + 200, f"ye_{ref}")
        ivx = m1.NewIntervalVar(xs, xw, xe, f"ivx_{ref}")
        ivy = m1.NewIntervalVar(ys, yw, ye, f"ivy_{ref}")
        if side == "front":
            fx.append(ivx)
            fy.append(ivy)
        else:
            bx.append(ivx)
            by.append(ivy)

        o_vars = {r: m1.NewBoolVar(f"o_{ref}_{r}") for r in rots}
        m1.AddExactlyOne(list(o_vars.values()))

        for r, gm in geoms.items():
            ox0 = g_lo(gm.dx0 - halo)
            oy0 = g_lo(gm.dy0 - halo)
            ox1 = max(ox0 + 1, g_hi(gm.dx1 + halo))
            oy1 = max(oy0 + 1, g_hi(gm.dy1 + halo))
            m1.Add(xs == cx + ox0).OnlyEnforceIf(o_vars[r])
            m1.Add(xw == ox1 - ox0).OnlyEnforceIf(o_vars[r])
            m1.Add(ys == cy + oy0).OnlyEnforceIf(o_vars[r])
            m1.Add(yw == oy1 - oy0).OnlyEnforceIf(o_vars[r])
            m1.Add(cx + g_lo(gm.dx0) >= rx0).OnlyEnforceIf(o_vars[r])
            m1.Add(cx + g_hi(gm.dx1) <= rx1).OnlyEnforceIf(o_vars[r])
            m1.Add(cy + g_lo(gm.dy0) >= ry0).OnlyEnforceIf(o_vars[r])
            m1.Add(cy + g_hi(gm.dy1) <= ry1).OnlyEnforceIf(o_vars[r])

        # Cross-face keepout for thermal-via ICs (e.g., TPS54360 PowerPAD-8 on F.Cu -> B.Cu)
        if any(gm.drill_box is not None for gm in geoms.values()):
            dxs = m1.NewIntVar(-200, gw + 200, f"dxs_{ref}")
            dys = m1.NewIntVar(-200, gh + 200, f"dys_{ref}")
            dxw = m1.NewIntVar(1, gw + 400, f"dxw_{ref}")
            dyw = m1.NewIntVar(1, gh + 400, f"dyw_{ref}")
            dxe = m1.NewIntVar(-200, gw + 200, f"dxe_{ref}")
            dye = m1.NewIntVar(-200, gh + 200, f"dye_{ref}")
            divx = m1.NewIntervalVar(dxs, dxw, dxe, f"divx_{ref}")
            divy = m1.NewIntervalVar(dys, dyw, dye, f"divy_{ref}")
            if side == "front":
                bx.append(divx)
                by.append(divy)
            else:
                fx.append(divx)
                fy.append(divy)
            for r, gm in geoms.items():
                assert gm.drill_box is not None
                bx0, by0, bx1, by1 = gm.drill_box
                gox0, goy0 = g_lo(bx0 - 0.55), g_lo(by0 - 0.55)
                gox1, goy1 = max(gox0 + 1, g_hi(bx1 + 0.55)), max(goy0 + 1, g_hi(by1 + 0.55))
                m1.Add(dxs == cx + gox0).OnlyEnforceIf(o_vars[r])
                m1.Add(dxw == gox1 - gox0).OnlyEnforceIf(o_vars[r])
                m1.Add(dys == cy + goy0).OnlyEnforceIf(o_vars[r])
                m1.Add(dyw == goy1 - goy0).OnlyEnforceIf(o_vars[r])

        # Exact rotated pad coordinates per net
        nets_on_fp = sorted({net for gm in geoms.values() for net in gm.pads if net != "GND"})
        for net in nets_on_fp:
            px = m1.NewIntVar(0, gw, f"px_{ref}_{net}")
            py = m1.NewIntVar(0, gh, f"py_{ref}_{net}")
            for r, gm in geoms.items():
                pts = gm.pads[net]
                mx = round(sum(p[0] for p in pts) / len(pts) / GRID_MM)
                my = round(sum(p[1] for p in pts) / len(pts) / GRID_MM)
                m1.Add(px == cx + mx).OnlyEnforceIf(o_vars[r])
                m1.Add(py == cy + my).OnlyEnforceIf(o_vars[r])
            dyn_pads[net].append((px, py, ref))

        s1_vars[ref] = (side, cx, cy, o_vars)

    m1.AddNoOverlap2D(fx, fy)
    m1.AddNoOverlap2D(bx, by)

    obj1 = []
    all_nets1 = sorted((set(fixed_pads) | set(dyn_pads)) - {"GND"})
    for net in all_nets1:
        w = net_weight(net)
        if w <= 0 or not dyn_pads.get(net):
            continue
        f_pts = fixed_pads.get(net, [])
        d_pts = dyn_pads[net]
        total_pins = len(f_pts) + len(d_pts)
        if total_pins < 2:
            continue
        if total_pins <= 4 and net not in GLOBAL_RAILS:
            pts = [(x, y) for x, y, _, _ in f_pts] + [(vx, vy) for vx, vy, _ in d_pts]
            for i in range(len(pts)):
                for j in range(i + 1, len(pts)):
                    if isinstance(pts[i][0], int) and isinstance(pts[j][0], int):
                        continue
                    adx = m1.NewIntVar(0, gw, f"s1_dx_{net}_{i}_{j}")
                    ady = m1.NewIntVar(0, gh, f"s1_dy_{net}_{i}_{j}")
                    m1.AddAbsEquality(adx, pts[i][0] - pts[j][0])
                    m1.AddAbsEquality(ady, pts[i][1] - pts[j][1])
                    obj1.append(w * (adx + ady))
        else:
            xmin = m1.NewIntVar(0, gw, f"s1_xmin_{net}")
            xmax = m1.NewIntVar(0, gw, f"s1_xmax_{net}")
            ymin = m1.NewIntVar(0, gh, f"s1_ymin_{net}")
            ymax = m1.NewIntVar(0, gh, f"s1_ymax_{net}")
            xs_all = [x for x, _, _, _ in f_pts] + [vx for vx, _, _ in d_pts]
            ys_all = [y for _, y, _, _ in f_pts] + [vy for _, vy, _ in d_pts]
            m1.AddMinEquality(xmin, xs_all)
            m1.AddMaxEquality(xmax, xs_all)
            m1.AddMinEquality(ymin, ys_all)
            m1.AddMaxEquality(ymax, ys_all)
            obj1.append(w * ((xmax - xmin) + (ymax - ymin)))

    # Keep same-block Stage-1 components compactly clustered (e.g. U1+L1+D3, U2+L2+D9, U8+D16, K1+Q1+D14)
    by_block: dict[str, list[str]] = defaultdict(list)
    for ref in stage1_refs:
        by_block[parts_meta[ref]["place"]].append(ref)
    for blk, refs in sorted(by_block.items()):
        if len(refs) < 2:
            continue
        bxmin = m1.NewIntVar(0, gw, f"blk_xmin_{blk}")
        bxmax = m1.NewIntVar(0, gw, f"blk_xmax_{blk}")
        bymin = m1.NewIntVar(0, gh, f"blk_ymin_{blk}")
        bymax = m1.NewIntVar(0, gh, f"blk_ymax_{blk}")
        m1.AddMinEquality(bxmin, [s1_vars[r][1] for r in refs])
        m1.AddMaxEquality(bxmax, [s1_vars[r][1] for r in refs])
        m1.AddMinEquality(bymin, [s1_vars[r][2] for r in refs])
        m1.AddMaxEquality(bymax, [s1_vars[r][2] for r in refs])
        obj1.append(6 * ((bxmax - bxmin) + (bymax - bymin)))

    m1.Minimize(sum(obj1))
    sol1 = solve_cp_sat(m1, float(pcfg.get("stage1_time_s", 35.0)), seed, "Stage1-Actives")

    for ref, (side, cx, cy, o_vars) in s1_vars.items():
        fp = board.FindFootprintByReference(ref)
        rot = next(r for r, v in o_vars.items() if sol1.Value(v))
        set_side(fp, side == "back")
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(sol1.Value(cx) * GRID_MM), pcbnew.FromMM(-sol1.Value(cy) * GRID_MM)))
        fp.SetLocked(False)
        placed_refs.add(ref)

    # 3. Stage 2: Solve passives in logical batches with boolean `is_vert` (0/90 width/height swap)
    batches: list[tuple[str, list[str]]] = []
    for batch_cfg in pcfg["passive_batches"]:
        b_name = batch_cfg["name"]
        b_blocks = set(batch_cfg["blocks"])
        b_refs = [r for r in passive_refs if parts_meta[r]["place"] in b_blocks]
        if b_refs:
            batches.append((b_name, b_refs))
    assigned = {r for _, rs in batches for r in rs}
    leftover = [r for r in passive_refs if r not in assigned]
    if leftover:
        batches.append(("misc", leftover))

    # Map each block -> active/anchor refs in that block so decoupling caps hug their exact target IC pins
    block_parents: dict[str, list[str]] = defaultdict(list)
    for ref in placed_refs:
        if ref in parts_meta:
            block_parents[parts_meta[ref]["place"]].append(ref)
    explicit_parents: dict[str, str] = pcfg.get("decoupling_parents", {})

    for b_idx, (b_name, b_refs) in enumerate(batches):
        m2 = cp_model.CpModel()
        fx2, fy2, bx2, by2 = add_fixed_obstacles(m2, board, placed_refs, plan, stage2_escape_halo)
        fpads2 = fixed_pad_coords(board, placed_refs)

        p_vars = {}
        dpads2: dict[str, list[tuple[cp_model.IntVar, cp_model.IntVar, str, str]]] = defaultdict(list)

        for ref in b_refs:
            fp = board.FindFootprintByReference(ref)
            side = part_side(ref)
            reg = region_for(ref)
            rx0 = g_hi(max(edge_margin, float(reg.get("x0", edge_margin))))
            ry0 = g_hi(max(edge_margin, float(reg.get("y0", edge_margin))))
            rx1 = g_lo(min(w_mm - edge_margin, float(reg.get("x1", w_mm - edge_margin))))
            ry1 = g_lo(min(h_mm - edge_margin, float(reg.get("y1", h_mm - edge_margin))))

            geoms = measure_footprint(fp, side, ROTS)
            halo = 0.2
            # Symmetric 2-pin SMD passive: 0/180 share horizontal size, 90/270 share vertical size
            gh0 = geoms[0]
            gv0 = geoms[90]
            hx0, hy0 = g_lo(gh0.dx0 - halo), g_lo(gh0.dy0 - halo)
            hx1, hy1 = max(hx0 + 1, g_hi(gh0.dx1 + halo)), max(hy0 + 1, g_hi(gh0.dy1 + halo))
            vx0, vy0 = g_lo(gv0.dx0 - halo), g_lo(gv0.dy0 - halo)
            vx1, vy1 = max(vx0 + 1, g_hi(gv0.dx1 + halo)), max(vy0 + 1, g_hi(gv0.dy1 + halo))

            cx = m2.NewIntVar(rx0, rx1, f"cx_{ref}")
            cy = m2.NewIntVar(ry0, ry1, f"cy_{ref}")
            is_vert = m2.NewBoolVar(f"vert_{ref}")
            o_vars = {r: m2.NewBoolVar(f"o_{ref}_{r}") for r in ROTS}
            m2.AddExactlyOne(list(o_vars.values()))
            m2.Add(o_vars[90] + o_vars[270] == 1).OnlyEnforceIf(is_vert)
            m2.Add(o_vars[0] + o_vars[180] == 1).OnlyEnforceIf(is_vert.Not())

            xs = m2.NewIntVar(-200, gw + 200, f"xs_{ref}")
            ys = m2.NewIntVar(-200, gh + 200, f"ys_{ref}")
            xw = m2.NewIntVar(1, gw + 400, f"xw_{ref}")
            yw = m2.NewIntVar(1, gh + 400, f"yw_{ref}")
            xe = m2.NewIntVar(-200, gw + 200, f"xe_{ref}")
            ye = m2.NewIntVar(-200, gh + 200, f"ye_{ref}")
            ivx = m2.NewIntervalVar(xs, xw, xe, f"ivx_{ref}")
            ivy = m2.NewIntervalVar(ys, yw, ye, f"ivy_{ref}")

            m2.Add(xs == cx + hx0).OnlyEnforceIf(is_vert.Not())
            m2.Add(xw == hx1 - hx0).OnlyEnforceIf(is_vert.Not())
            m2.Add(ys == cy + hy0).OnlyEnforceIf(is_vert.Not())
            m2.Add(yw == hy1 - hy0).OnlyEnforceIf(is_vert.Not())
            m2.Add(cx + g_lo(gh0.dx0) >= rx0).OnlyEnforceIf(is_vert.Not())
            m2.Add(cx + g_hi(gh0.dx1) <= rx1).OnlyEnforceIf(is_vert.Not())
            m2.Add(cy + g_lo(gh0.dy0) >= ry0).OnlyEnforceIf(is_vert.Not())
            m2.Add(cy + g_hi(gh0.dy1) <= ry1).OnlyEnforceIf(is_vert.Not())

            m2.Add(xs == cx + vx0).OnlyEnforceIf(is_vert)
            m2.Add(xw == vx1 - vx0).OnlyEnforceIf(is_vert)
            m2.Add(ys == cy + vy0).OnlyEnforceIf(is_vert)
            m2.Add(yw == vy1 - vy0).OnlyEnforceIf(is_vert)
            m2.Add(cx + g_lo(gv0.dx0) >= rx0).OnlyEnforceIf(is_vert)
            m2.Add(cx + g_hi(gv0.dx1) <= rx1).OnlyEnforceIf(is_vert)
            m2.Add(cy + g_lo(gv0.dy0) >= ry0).OnlyEnforceIf(is_vert)
            m2.Add(cy + g_hi(gv0.dy1) <= ry1).OnlyEnforceIf(is_vert)

            if side == "front":
                fx2.append(ivx)
                fy2.append(ivy)
            else:
                bx2.append(ivx)
                by2.append(ivy)

            pad_vars_for_ref = {}
            for pad in fp.Pads():
                pnum = pad.GetNumber()
                net = pad.GetNetname()
                if not pnum or not net:
                    continue
                px = m2.NewIntVar(0, gw, f"px_{ref}_{pnum}")
                py = m2.NewIntVar(0, gh, f"py_{ref}_{pnum}")
                for r, gm in geoms.items():
                    pt = next((x, y) for x, y, n in gm.pads[net] if n == pnum)
                    m2.Add(px == cx + g_near(pt[0])).OnlyEnforceIf(o_vars[r])
                    m2.Add(py == cy + g_near(pt[1])).OnlyEnforceIf(o_vars[r])
                pad_vars_for_ref[(pnum, net)] = (px, py)
                if net != "GND":
                    dpads2[net].append((px, py, ref, pnum))

            p_vars[ref] = (side, cx, cy, o_vars, pad_vars_for_ref)

        m2.AddNoOverlap2D(fx2, fy2)
        m2.AddNoOverlap2D(bx2, by2)

        obj2 = []
        # Target-IC pin anchoring for passives on global rails (decoupling, pull-ups, bootstrap, UVLO)
        # and secondary series compensation caps (*_CC -> parent IC *_COMP pin)
        comp_pin_by_tag = {}
        for uref in ("U1", "U2"):
            ufp = board.FindFootprintByReference(uref)
            if ufp is not None and uref in placed_refs:
                cpad = ufp.FindPadByNumber("6")
                if cpad is not None:
                    comp_pin_by_tag[cpad.GetNetname().split("_")[0]] = (
                        g_near(pcbnew.ToMM(cpad.GetPosition().x)),
                        g_near(-pcbnew.ToMM(cpad.GetPosition().y)),
                    )

        for ref in b_refs:
            blk = parts_meta[ref]["place"]
            _, _, _, _, pad_map = p_vars[ref]
            for (pnum, net), (px, py) in pad_map.items():
                if net.endswith("_CC"):
                    tag = net.split("_")[0]
                    if tag in comp_pin_by_tag:
                        tx, ty = comp_pin_by_tag[tag]
                        adx = m2.NewIntVar(0, gw, f"cc_dx_{ref}_{pnum}")
                        ady = m2.NewIntVar(0, gh, f"cc_dy_{ref}_{pnum}")
                        m2.AddAbsEquality(adx, px - tx)
                        m2.AddAbsEquality(ady, py - ty)
                        obj2.append(18 * (adx + ady))
                if net == "GND":
                    continue
                if net in GLOBAL_RAILS:
                    target_refs = [explicit_parents[ref]] if ref in explicit_parents else block_parents.get(blk, [])
                    candidates = [
                        (tx, ty) for tx, ty, tref, _ in fpads2.get(net, []) if tref in target_refs
                    ]
                    if not candidates:
                        candidates = [(tx, ty) for tx, ty, _, _ in fpads2.get(net, [])]
                    if candidates:
                        tx = round(sum(c[0] for c in candidates) / len(candidates))
                        ty = round(sum(c[1] for c in candidates) / len(candidates))
                        adx = m2.NewIntVar(0, gw, f"anc_dx_{ref}_{pnum}")
                        ady = m2.NewIntVar(0, gh, f"anc_dy_{ref}_{pnum}")
                        m2.AddAbsEquality(adx, px - tx)
                        m2.AddAbsEquality(ady, py - ty)
                        obj2.append(16 * (adx + ady))

        # Local signal/switching/analog nets L1 pad-to-pad Manhattan distance
        for net, d_pts in sorted(dpads2.items()):
            if net in GLOBAL_RAILS or net == "GND":
                continue
            w = net_weight(net)
            f_pts = fpads2.get(net, [])
            pts = [(x, y) for x, y, _, _ in f_pts] + [(vx, vy) for vx, vy, _, _ in d_pts]
            if len(pts) < 2:
                continue
            if len(pts) <= 5:
                for i in range(len(pts)):
                    for j in range(i + 1, len(pts)):
                        if isinstance(pts[i][0], int) and isinstance(pts[j][0], int):
                            continue
                        adx = m2.NewIntVar(0, gw, f"s2_{b_idx}_dx_{net}_{i}_{j}")
                        ady = m2.NewIntVar(0, gh, f"s2_{b_idx}_dy_{net}_{i}_{j}")
                        m2.AddAbsEquality(adx, pts[i][0] - pts[j][0])
                        m2.AddAbsEquality(ady, pts[i][1] - pts[j][1])
                        obj2.append(w * (adx + ady))
            else:
                xmin = m2.NewIntVar(0, gw, f"s2_{b_idx}_xmin_{net}")
                xmax = m2.NewIntVar(0, gw, f"s2_{b_idx}_xmax_{net}")
                ymin = m2.NewIntVar(0, gh, f"s2_{b_idx}_ymin_{net}")
                ymax = m2.NewIntVar(0, gh, f"s2_{b_idx}_ymax_{net}")
                m2.AddMinEquality(xmin, [p[0] for p in pts])
                m2.AddMaxEquality(xmax, [p[0] for p in pts])
                m2.AddMinEquality(ymin, [p[1] for p in pts])
                m2.AddMaxEquality(ymax, [p[1] for p in pts])
                obj2.append(w * ((xmax - xmin) + (ymax - ymin)))

        m2.Minimize(sum(obj2))
        sol2 = solve_cp_sat(m2, float(pcfg.get("stage2_time_s", 15.0)), seed + b_idx + 1, f"Stage2-{b_name}")

        for ref, (side, cx, cy, o_vars, _) in p_vars.items():
            fp = board.FindFootprintByReference(ref)
            rot = next(r for r, v in o_vars.items() if sol2.Value(v))
            set_side(fp, side == "back")
            fp.SetOrientationDegrees(rot)
            fp.SetPosition(
                pcbnew.VECTOR2I(pcbnew.FromMM(sol2.Value(cx) * GRID_MM), pcbnew.FromMM(-sol2.Value(cy) * GRID_MM))
            )
            fp.SetLocked(False)
            placed_refs.add(ref)
