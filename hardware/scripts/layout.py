"""Persistent board layout and fastroute autorouting (`eda` container)."""

import itertools
import json
import re
import subprocess
import sys
from pathlib import Path

import kinet2pcb
import pcbnew
import yaml
from shapely.geometry import Polygon

REPO = Path("/work")
sys.path.insert(0, str(REPO / "hardware/circuits"))
from product_spec import load_spec

SPEC = load_spec()
VARIANT = SPEC["active_variant"]
LAYERS = {"F.Cu": pcbnew.F_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu, "B.Cu": pcbnew.B_Cu}

SILK_TEXT_MM = 0.8
SILK_STROKE_MM = 0.14
POWER_CLASS = {"SELV-MAIN": "MAIN-Power"}
MIN_TRACK_UM = 120
LIBRARY_ONLY_DRC = {"lib_footprint_issues", "lib_footprint_mismatch"}


def pos(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(-y))


def rect_points(r):
    return [(r["x0"], r["y0"]), (r["x1"], r["y0"]), (r["x1"], r["y1"]), (r["x0"], r["y1"])]


def edge_seg(board, x0, y0, x1, y1):
    seg = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
    seg.SetLayer(pcbnew.Edge_Cuts)
    seg.SetWidth(pcbnew.FromMM(0.05))
    seg.SetStart(pos(x0, y0))
    seg.SetEnd(pos(x1, y1))
    board.Add(seg)


def zones(board):
    return [board.GetArea(i) for i in range(board.GetAreaCount())]


def add_pour(board, net, layer, region, priority=0):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(LAYERS[layer])
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in rect_points(region):
        p = pos(x, y)
        outline.Append(p.x, p.y)
    zone.SetNet(board.FindNet(net))
    zone.SetAssignedPriority(priority)
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    zone.SetLocalClearance(pcbnew.FromMM(0.2))
    zone.SetMinThickness(pcbnew.FromMM(0.2))
    zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    board.Add(zone)


def clear_frame(board):
    for item in list(board.GetDrawings()):
        if item.GetLayer() in (pcbnew.Edge_Cuts, pcbnew.F_SilkS, pcbnew.B_SilkS):
            board.Remove(item)
    for zone in zones(board):
        board.RemoveNative(zone)


def add_3d_models(board):
    for fp in board.Footprints():
        models = fp.Models()
        for i in reversed(range(len(models))):
            fn = str(models[i].m_Filename)
            if fn.startswith("hardware/circuits/lib/gateway_3d/"):
                del models[i]
        fp_name = str(fp.GetFPID().GetLibItemName())
        if fp_name == "Fuse_2920_7451Metric":
            for i in reversed(range(len(models))):
                del models[i]
            m = pcbnew.FP_3DMODEL()
            m.m_Filename = "${KICAD10_3DMODEL_DIR}/Fuse.3dshapes/Fuse_1210_3225Metric.step"
            m.m_Scale = pcbnew.VECTOR3D(2.3, 2.0, 1.2)
            fp.Add3DModel(m)
        elif fp_name == "TI_SO-PowerPAD-8_ThermalVias":
            for i in reversed(range(len(models))):
                del models[i]
            m = pcbnew.FP_3DMODEL()
            m.m_Filename = "${KICAD10_3DMODEL_DIR}/Package_SO.3dshapes/SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.81mm.step"
            fp.Add3DModel(m)
        elif fp_name in (
            "TerminalBlock_WAGO_2086-1202_SMD",
            "TerminalBlock_WAGO_2086-1203_SMD",
            "TerminalBlock_WAGO_2086-1204_SMD",
        ):
            poles = {"TerminalBlock_WAGO_2086-1202_SMD": 2, "TerminalBlock_WAGO_2086-1203_SMD": 3, "TerminalBlock_WAGO_2086-1204_SMD": 4}[fp_name]
            cx = (poles - 1) * 1.75
            for i in reversed(range(len(models))):
                del models[i]
            m = pcbnew.FP_3DMODEL()
            m.m_Filename = (
                f"${{KICAD10_3DMODEL_DIR}}/TerminalBlock_Phoenix.3dshapes/"
                f"TerminalBlock_Phoenix_PT-1,5-{poles}-3.5-H_1x0{poles}_P3.50mm_Horizontal.step"
            )
            m.m_Offset = pcbnew.VECTOR3D(-cx, -2.0, 0)
            fp.Add3DModel(m)
        elif fp_name == "XIAO_ESP32C6_Header":
            for i in reversed(range(len(models))):
                del models[i]
            for x_off in (-7.62, 7.62):
                sock = pcbnew.FP_3DMODEL()
                sock.m_Filename = "${KICAD10_3DMODEL_DIR}/Connector_PinSocket_2.54mm.3dshapes/PinSocket_1x07_P2.54mm_Vertical.step"
                sock.m_Offset = pcbnew.VECTOR3D(x_off, 7.62, 0)
                fp.Add3DModel(sock)
            mod = pcbnew.FP_3DMODEL()
            mod.m_Filename = "${KICAD10_3DMODEL_DIR}/RF_Module.3dshapes/ESP32-C3-WROOM-02.step"
            mod.m_Offset = pcbnew.VECTOR3D(0, -0.5, 8.5)
            mod.m_Scale = pcbnew.VECTOR3D(0.95, 1.0, 0.85)
            mod.m_Rotation = pcbnew.VECTOR3D(0, 0, 0)
            fp.Add3DModel(mod)
            usbc = pcbnew.FP_3DMODEL()
            usbc.m_Filename = "${KICAD10_3DMODEL_DIR}/Connector_USB.3dshapes/USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.step"
            usbc.m_Offset = pcbnew.VECTOR3D(0, 8.8, 9.8)
            usbc.m_Rotation = pcbnew.VECTOR3D(0, 0, 180)
            fp.Add3DModel(usbc)


def layout_dir(board):
    return REPO / "hardware/layout" / VARIANT / board


def build_dir(board):
    path = REPO / "hardware/build" / VARIANT / board
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_plan(board):
    return yaml.safe_load((REPO / "hardware/circuits/variants" / VARIANT / f"layout_{board}.yaml").read_text())


def stored_board_path(board):
    return layout_dir(board) / f"{board}.kicad_pcb"


def fresh_board(board):
    out = build_dir(board) / f"{board}.fresh.kicad_pcb"
    kinet2pcb.kinet2pcb(str(build_dir(board) / f"{board}.net"), str(out), [str(REPO / "hardware/circuits/lib")])
    return pcbnew.LoadBoard(str(out))


def set_side(fp, back):
    if fp.IsFlipped() != back:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)


def carry_over(target, stored):
    moved = 0
    for fp in target.Footprints():
        old = stored.FindFootprintByReference(fp.GetReference())
        if old is None:
            continue
        set_side(fp, old.IsFlipped())
        fp.SetOrientation(old.GetOrientation())
        fp.SetPosition(old.GetPosition())
        fp.SetLocked(old.IsLocked())
        fp.Reference().SetVisible(old.Reference().IsVisible())
        moved += 1
    copied = 0
    for item in stored.GetTracks():
        net = target.FindNet(item.GetNetname())
        if net is None or item.GetNetCode() == 0:
            continue
        if item.GetClass() == "PCB_VIA":
            new = pcbnew.PCB_VIA(target)
            new.SetPosition(item.GetPosition())
            new.SetViaType(pcbnew.VIATYPE_THROUGH)
            new.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            new.SetDrill(item.GetDrillValue())
            new.SetWidth(item.GetWidth(pcbnew.F_Cu))
        elif item.GetClass() == "PCB_ARC":
            new = pcbnew.PCB_ARC(target)
            new.SetStart(item.GetStart())
            new.SetMid(item.GetMid())
            new.SetEnd(item.GetEnd())
            new.SetWidth(item.GetWidth())
            new.SetLayer(item.GetLayer())
        else:
            new = pcbnew.PCB_TRACK(target)
            new.SetStart(item.GetStart())
            new.SetEnd(item.GetEnd())
            new.SetWidth(item.GetWidth())
            new.SetLayer(item.GetLayer())
        new.SetLocked(item.IsLocked())
        target.Add(new)
        new.SetNet(net)
        copied += 1
    return moved, copied


def place_parts(board, plan, names):
    parts = plan["parts"]
    refs = list(parts) if not names else [r for r, p in parts.items() if r in names or p.get("block") in names]
    for ref in refs:
        p = parts[ref]
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            sys.exit(f"{ref} is in the layout plan but not in the netlist")
        set_side(fp, p.get("side") == "back")
        fp.SetOrientationDegrees(p.get("rot", 0))
        fp.SetPosition(pos(p["x"], p["y"]))
        fp.SetLocked(bool(p.get("locked", False)))
    return refs


def apply_frame(board, plan):
    clear_frame(board)
    frame = plan["frame"]
    w, h = frame["size"]["x"], frame["size"]["y"]
    board.SetCopperLayerCount(frame["copper_layers"])
    settings = board.GetDesignSettings()
    settings.SetBoardThickness(pcbnew.FromMM(frame["thickness"]))
    settings.m_MinThroughDrill = pcbnew.FromMM(frame["min_drill"])
    settings.m_TrackMinWidth = pcbnew.FromMM(frame["min_track"])
    if "via" in frame:
        settings.m_ViasMinSize = pcbnew.FromMM(frame["via"]["diameter"])
    settings.m_CopperEdgeClearance = pcbnew.FromMM(frame["edge_clearance"])
    settings.m_MinSilkTextHeight = pcbnew.FromMM(0.6)
    corners = [tuple(p) for p in frame["outline"]] if "outline" in frame else rect_points({"x0": 0, "y0": 0, "x1": w, "y1": h})
    for a, b in zip(corners, corners[1:] + corners[:1]):
        edge_seg(board, *a, *b)
    for lbl in frame.get("silk_labels", []):
        txt = pcbnew.PCB_TEXT(board)
        lyr = pcbnew.B_SilkS if lbl.get("layer") == "B.SilkS" else pcbnew.F_SilkS
        txt.SetLayer(lyr)
        txt.SetText(str(lbl["text"]))
        txt.SetPosition(pos(lbl["x"], lbl["y"]))
        size = lbl.get("size", SILK_TEXT_MM)
        txt.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
        if lbl.get("rot"):
            txt.SetTextAngle(pcbnew.EDA_ANGLE(lbl["rot"], pcbnew.DEGREES_T))
        txt.SetTextThickness(pcbnew.FromMM(max(SILK_STROKE_MM, 0.15 * size)))
        if lyr == pcbnew.B_SilkS:
            txt.SetMirrored(True)
        board.Add(txt)
    for line in frame.get("silk_lines", []):
        lyr = pcbnew.B_SilkS if line.get("layer") == "B.SilkS" else pcbnew.F_SilkS
        for a, b in itertools.pairwise(line["points"]):
            seg = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
            seg.SetLayer(lyr)
            seg.SetWidth(pcbnew.FromMM(line.get("width", 0.25)))
            seg.SetStart(pos(*a))
            seg.SetEnd(pos(*b))
            board.Add(seg)
    for layer in frame.get("plane_layers", []):
        board.SetLayerType(LAYERS[layer], pcbnew.LT_POWER)
    for z in frame.get("pours", []):
        for layer in z["layers"]:
            add_pour(board, z["net"], layer, z["region"], z.get("priority", 0))


def fill_zones(board):
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


DRU_4LAYER = """\
(version 1)
(rule jlcpcb_minimum
  (constraint track_width (min 0.12mm))
  (constraint clearance (min 0.2mm))
  (constraint hole_size (min 0.2mm)))
(rule power_track_width
  (constraint track_width (min 0.22mm))
  (condition "A.hasNetclass('MAIN-Power')"))
"""


def neck_down_rule(refs):
    if not refs:
        return ""
    courtyards = " || ".join(f"A.intersectsCourtyard('{r}')" for r in refs)
    return (
        "(rule power_neck_down_at_fine_pitch_pins\n"
        "  (constraint track_width (min 0.15mm))\n"
        f'  (condition "A.hasNetclass(\'MAIN-Power\') && ({courtyards})"))\n'
        "(rule neck_down_at_fine_pitch_pins\n"
        "  (constraint track_width (min 0.1mm))\n"
        f'  (condition "{courtyards}"))\n'
    )


def raised_module_rule(refs):
    if not refs:
        return ""
    either = " || ".join(f"A.Reference == '{r}' || B.Reference == '{r}'" for r in refs)
    return (
        "(rule parts_under_raised_modules\n"
        "  (constraint courtyard_clearance (min -100mm))\n"
        f'  (condition "{either}"))\n'
    )


def domain_at(regions, x, y):
    return next(
        (d for d, areas in regions.items() for r in (areas if isinstance(areas, list) else [areas])
         if r["x0"] <= x <= r["x1"] and r["y0"] <= y <= r["y1"]),
        None,
    )


def net_classes(board, frame):
    found = {}
    for fp in board.Footprints():
        for pad in fp.Pads():
            if not pad.GetNetname():
                continue
            p = pad.GetPosition()
            domain = domain_at(frame["domain_regions"], pcbnew.ToMM(p.x), -pcbnew.ToMM(p.y))
            found.setdefault(pad.GetNetname(), set()).add(domain)
    classes = {}
    for net, domains in found.items():
        domains.discard(None)
        if not domains:
            domains = {"SELV-MAIN"}
        domain = domains.pop()
        classes[net] = POWER_CLASS[domain] if net in frame["power_nets"] else domain
    return classes


def project_net_settings(classes, power_width=0.35, signal_width=0.2, via=(0.6, 0.3)):
    def netclass(name, priority, width):
        return {
            "name": name, "priority": priority, "clearance": 0.2, "track_width": width,
            "via_diameter": via[0], "via_drill": via[1], "microvia_diameter": 0.3,
            "microvia_drill": 0.1, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
            "diff_pair_width": 0.2, "wire_width": 6, "bus_width": 12, "line_style": 0,
            "pcb_color": "rgba(0,0,0,0)", "schematic_color": "rgba(0,0,0,0)",
        }
    defs = [netclass("Default", 2147483647, signal_width)]
    defs += [netclass(d, 2, signal_width) for d in POWER_CLASS]
    defs += [netclass(p, 1, power_width) for p in POWER_CLASS.values()]
    patterns = [{"netclass": c, "pattern": n} for n, c in sorted(classes.items())]
    return defs, patterns


def write_rules(board, plan, pcb_path):
    frame = plan["frame"]
    dru = DRU_4LAYER + neck_down_rule(frame.get("fine_pitch_power_pads", [])) + raised_module_rule(frame.get("raised_modules", []))
    pcb_path.with_suffix(".kicad_dru").write_text(dru)
    pro_path = pcb_path.with_suffix(".kicad_pro")
    project = json.loads(pro_path.read_text()) if pro_path.exists() else {}
    via = frame.get("via", {})
    defs, patterns = project_net_settings(
        net_classes(board, frame),
        frame.get("power_track_width", 0.35),
        frame.get("signal_track_width", 0.2),
        (via.get("diameter", 0.6), via.get("drill", 0.3)),
    )
    project.setdefault("net_settings", {}).update({"classes": defs, "netclass_patterns": patterns})
    pro_path.write_text(json.dumps(project, indent=2))


def body_box(fp):
    fp.BuildCourtyardCaches()
    bb = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd).BBox()
    if str(fp.GetFPID().GetLibItemName()) == "XIAO_ESP32C6_Header":
        fab = pcbnew.B_Fab if fp.IsFlipped() else pcbnew.F_Fab
        for item in fp.GraphicalItems():
            if item.GetLayer() == fab and item.Type() == pcbnew.PCB_SHAPE_T:
                bb.Merge(item.GetBoundingBox())
    return bb


def export_components(board, plan, out):
    heights = plan.get("heights", {})
    comps = []
    for fp in board.Footprints():
        bb = body_box(fp)
        p = fp.GetPosition()
        comps.append({
            "ref": fp.GetReference(),
            "value": fp.GetValue(),
            "footprint": str(fp.GetFPID().GetLibItemName()),
            "x": round(pcbnew.ToMM(p.x), 3),
            "y": round(-pcbnew.ToMM(p.y), 3),
            "rot": fp.GetOrientation().AsDegrees(),
            "side": "back" if fp.IsFlipped() else "front",
            "tht": any(pad.GetDrillSize().x > 0 for pad in fp.Pads()),
            "height": heights.get(fp.GetReference(), heights.get("default", 1.2)),
            "pads": [[round(pcbnew.ToMM(pad.GetPosition().x), 3), round(-pcbnew.ToMM(pad.GetPosition().y), 3), pad.GetNumber()]
                     for pad in fp.Pads() if pad.GetNumber() and pad.GetNumber() != "MP"],
            "bbox": {"x0": round(pcbnew.ToMM(bb.GetLeft()), 3), "x1": round(pcbnew.ToMM(bb.GetRight()), 3),
                     "y0": round(-pcbnew.ToMM(bb.GetBottom()), 3), "y1": round(-pcbnew.ToMM(bb.GetTop()), 3)},
        })
    out.write_text(json.dumps(comps, indent=1))


def mm_box(box, grow=0.0):
    return (pcbnew.ToMM(box.GetLeft()) - grow, pcbnew.ToMM(box.GetTop()) - grow,
            pcbnew.ToMM(box.GetRight()) + grow, pcbnew.ToMM(box.GetBottom()) + grow)


def boxes_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def place_references_inside(board, frame, hidden_refs=()):
    w, h = frame["size"]["x"], frame["size"]["y"]
    inside = Polygon([(0.2, -0.2), (w - 0.2, -0.2), (w - 0.2, -(h - 0.2)), (0.2, -(h - 0.2))])
    pads = {False: [], True: []}
    taken = {False: [], True: []}
    for item in board.GetDrawings():
        if item.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            taken[item.GetLayer() == pcbnew.B_SilkS].append(mm_box(item.GetBoundingBox(), 0.15))
    for fp in board.Footprints():
        for pad in fp.Pads():
            for back in (False, True):
                if pad.IsOnLayer(pcbnew.B_Cu if back else pcbnew.F_Cu):
                    pads[back].append(mm_box(pad.GetBoundingBox(), 0.15))
        for item in fp.GraphicalItems():
            if item.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                taken[item.GetLayer() == pcbnew.B_SilkS].append(mm_box(item.GetBoundingBox(), 0.15))
    for fp in board.Footprints():
        ref = fp.Reference()
        if fp.GetReference() in hidden_refs:
            ref.SetVisible(False)
            continue
        ref.SetVisible(True)
        ref.SetTextAngle(pcbnew.EDA_ANGLE(0, pcbnew.DEGREES_T))
        x0, y0, x1, y1 = mm_box(fp.GetBoundingBox(False, False))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        tx0, ty0, tx1, ty1 = mm_box(ref.GetBoundingBox())
        dx, dy = (tx1 - tx0) / 2 + 0.2, (ty1 - ty0) / 2 + 0.2
        placed = False
        for x, y in ((cx, y0 - dy), (cx, y1 + dy), (x0 - dx, cy), (x1 + dx, cy), (cx, cy)):
            ref.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
            box = mm_box(ref.GetBoundingBox(), 0.05)
            fits = inside.contains(Polygon([(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]))
            if fits and not any(boxes_overlap(box, o) for o in pads[fp.IsFlipped()] + taken[fp.IsFlipped()]):
                taken[fp.IsFlipped()].append(box)
                placed = True
                break
        if not placed:
            ref.SetVisible(False)


def save(board, plan, board_name, hidden_refs=()):
    path = stored_board_path(board_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    for fp in board.Footprints():
        ref = fp.Reference()
        ref.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(SILK_TEXT_MM), pcbnew.FromMM(SILK_TEXT_MM)))
        ref.SetTextThickness(pcbnew.FromMM(SILK_STROKE_MM))
        if fp.GetReference() in hidden_refs:
            ref.SetVisible(False)
    if plan["frame"].get("silk_inside"):
        place_references_inside(board, plan["frame"], hidden_refs)
    add_3d_models(board)
    fill_zones(board)
    board.Save(str(path))
    write_rules(board, plan, path)
    export_components(board, plan, build_dir(board_name) / f"components_{board_name}.json")


def current_board(board_name, plan):
    board = fresh_board(board_name)
    stored = stored_board_path(board_name)
    if stored.exists():
        old = pcbnew.LoadBoard(str(stored))
        moved, copied = carry_over(board, old)
        new_refs = [fp.GetReference() for fp in board.Footprints() if old.FindFootprintByReference(fp.GetReference()) is None]
        if new_refs:
            place_parts(board, plan, new_refs)
        print(f"{board_name}: kept {moved} footprints, {copied} tracks/vias, placed new {new_refs or 'none'}")
    else:
        placed = place_parts(board, plan, list(plan["parts"]))
        print(f"{board_name}: new layout, placed {len(placed)} planned parts")
    apply_frame(board, plan)
    return board


def sync(board_name):
    plan = load_plan(board_name)
    save(current_board(board_name, plan), plan, board_name)


def tidy_silk(board_name):
    plan = load_plan(board_name)
    path = stored_board_path(board_name)
    report = build_dir(board_name) / "silk_drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--output", str(report), str(path)],
                   capture_output=True, check=False)
    clashing = {
        item["description"].split("Reference field of ")[1].split()[0]
        for v in json.loads(report.read_text())["violations"]
        if v["type"] in ("silk_overlap", "silk_over_copper", "silk_edge_clearance")
        for item in v["items"] if item["description"].startswith("Reference field of ")
    }
    save(current_board(board_name, plan), plan, board_name, clashing)


def with_inset_boundary(dsn_text, frame):
    inset = (frame["edge_clearance"] + 0.05) * 1000

    def rewrite(match):
        nums = [float(n) for n in match.group(2).split()]
        shrunk = Polygon(list(zip(nums[::2], nums[1::2]))).buffer(-inset, join_style="mitre")
        return match.group(1) + "  ".join(f"{x:.0f} {y:.0f}" for x, y in shrunk.exterior.coords) + ")"

    return re.sub(r"(\(boundary\s+\(path pcb 0\s+)([-\d.\s]+)\)", rewrite, dsn_text, count=1)


def with_net_classes(dsn_text, nets, net_settings):
    start = dsn_text.index("    (class ")
    end = dsn_text.index("  (wiring")
    via = dsn_text[start:end].split("(use_via ")[1].split(")")[0]
    assigned = {p["pattern"]: p["netclass"] for p in net_settings["netclass_patterns"]}
    classes = {c["name"]: c for c in net_settings["classes"]}
    groups = {}
    for net in nets:
        groups.setdefault(assigned.get(net, "Default"), []).append(net)
    blocks = []
    for cls, members in sorted(groups.items()):
        blocks.append(
            f'    (class {cls} {" ".join(members)}\n'
            f'      (circuit\n        (use_via {via})\n      )\n'
            f'      (rule\n        (width {classes[cls]["track_width"] * 1000:.0f})\n'
            f'        (clearance {(classes[cls]["clearance"] + 0.01) * 1000:.0f})\n'
            f'      )\n    )\n'
        )
    return dsn_text[:start] + "".join(blocks) + "  )\n" + dsn_text[end:]


def export_dsn(board_name):
    plan = load_plan(board_name)
    board = current_board(board_name, plan)
    for zone in zones(board):
        if not zone.GetIsRuleArea():
            board.RemoveNative(zone)
    for track in list(board.GetTracks()):
        if not track.IsLocked():
            board.RemoveNative(track)
    routable = build_dir(board_name) / f"{board_name}.routable.kicad_pcb"
    board.Save(str(routable))
    write_rules(board, plan, routable)
    dsn = build_dir(board_name) / f"{board_name}.dsn"
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        sys.exit("DSN export failed")
    nets = sorted(str(n) for n in board.GetNetsByName() if str(n))
    project = json.loads(routable.with_suffix(".kicad_pro").read_text())
    dsn.write_text(with_inset_boundary(with_net_classes(dsn.read_text(), nets, project["net_settings"]), plan["frame"]))


def drc_violations(pcb_path, report):
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb_path)],
                   capture_output=True, check=True)
    return [v for v in json.loads(report.read_text())["violations"] if v["type"] not in LIBRARY_ONLY_DRC]


def drc_key(violation):
    return violation["type"], tuple(sorted(item["description"] for item in violation.get("items", [])))


def unconnected(board):
    fill_zones(board)
    board.BuildConnectivity()
    return board.GetConnectivity().GetUnconnectedCount(False)


def unrouted_baseline(board_name):
    stored = stored_board_path(board_name)
    board = pcbnew.LoadBoard(str(stored))
    for track in list(board.GetTracks()):
        if not track.IsLocked():
            board.RemoveNative(track)
    connections = unconnected(board)
    path = build_dir(board_name) / f"{board_name}.unrouted.kicad_pcb"
    board.Save(str(path))
    for suffix in (".kicad_dru", ".kicad_pro"):
        path.with_suffix(suffix).write_text(stored.with_suffix(suffix).read_text())
    return connections, drc_violations(path, build_dir(board_name) / "unrouted_drc.json")


def widen_narrow_tracks(board_name):
    path = stored_board_path(board_name)
    report = build_dir(board_name) / "track_width_drc.json"

    def errors():
        subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(path)],
                       capture_output=True, check=True)
        return [v for v in json.loads(report.read_text())["violations"] if v["severity"] == "error"]

    before = errors()
    narrow = {
        i["uuid"]: pcbnew.FromMM(float(re.search(r"min width ([\d.]+) mm", v["description"]).group(1)))
        for v in before if v["type"] == "track_width" for i in v["items"]
    }
    if not narrow:
        return 0
    board = pcbnew.LoadBoard(str(path))
    tracks = {t.m_Uuid.AsString(): t for t in board.GetTracks() if t.m_Uuid.AsString() in narrow}
    old = {u: t.GetWidth() for u, t in tracks.items()}
    for u, t in tracks.items():
        t.SetWidth(narrow[u])
    board.Save(str(path))
    known = {drc_key(v) for v in before}
    clashing = {i["uuid"] for v in errors() if drc_key(v) not in known for i in v["items"]} & tracks.keys()
    if clashing:
        board = pcbnew.LoadBoard(str(path))
        for t in board.GetTracks():
            if t.m_Uuid.AsString() in clashing:
                t.SetWidth(old[t.m_Uuid.AsString()])
        board.Save(str(path))
    return len(tracks) - len(clashing)


def import_ses(board_name):
    plan = load_plan(board_name)
    board = current_board(board_name, plan)
    ses = build_dir(board_name) / f"{board_name}.ses"
    if not pcbnew.ImportSpecctraSES(board, str(ses)):
        sys.exit("SES import failed")
    save(board, plan, board_name)
    widened = widen_narrow_tracks(board_name)
    if widened:
        print(f"{board_name}: widened {widened} necked power tracks")


def route(board_name, time_limit=300, attempts=3):
    connections, baseline = unrouted_baseline(board_name)
    known = {drc_key(v) for v in baseline}
    export_dsn(board_name)
    bdir = build_dir(board_name)
    dsn, ses, report = bdir / f"{board_name}.dsn", bdir / f"{board_name}.ses", bdir / "fastroute_report.json"
    for attempt in range(1, attempts + 1):
        ses.unlink(missing_ok=True)
        run = subprocess.run(
            ["fastroute", "-de", str(dsn), "-do", str(ses), f"--max-time={time_limit}",
             f"--router.min_trace_width_um={MIN_TRACK_UM}", f"--report={report}", "--diagnose"],
            capture_output=True, text=True, check=False,
        )
        if run.returncode or not ses.exists():
            sys.exit(f"{board_name}: fastroute failed:\n{run.stdout[-1500:]}\n{run.stderr[-1500:]}")
        stats = json.loads(report.read_text())["stats"]
        print(f"{board_name}: attempt {attempt}: fastroute routed {stats['connections'] - stats['unrouted']}/{stats['connections']}, {stats['vias']} vias")
        import_ses(board_name)
        board = pcbnew.LoadBoard(str(stored_board_path(board_name)))
        left = unconnected(board)
        real = [v for v in drc_violations(stored_board_path(board_name), bdir / "routed_drc.json") if drc_key(v) not in known]
        errors = [v for v in real if v["severity"] == "error"]
        print(f"{board_name}: connectivity unrouted={left}/{connections}, DRC errors beyond baseline={len(errors)}")
        if not errors and not left:
            return
    sys.exit(f"{board_name}: routing failed after {attempts} attempts: {len(errors)} DRC errors, {left} unrouted")


if __name__ == "__main__":
    name, command, *args = sys.argv[1:]
    if command == "sync":
        sync(name)
    elif command == "tidy-silk":
        tidy_silk(name)
    elif command == "route":
        route(name, *(int(a) for a in args))
    elif command == "place":
        plan = load_plan(name)
        b = current_board(name, plan)
        place_parts(b, plan, args)
        save(b, plan, name)
    elif command == "unroute":
        plan = load_plan(name)
        b = current_board(name, plan)
        for tr in list(b.GetTracks()):
            b.Remove(tr)
        save(b, plan, name)
    else:
        sys.exit(f"unknown command: {command}")
