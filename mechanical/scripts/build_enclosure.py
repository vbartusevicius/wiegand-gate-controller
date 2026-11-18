"""Parametric CadQuery compact enclosure for Wiegand Gate Controller & JLC3DP print plate.

Coordinate frame = PCB frame:
  PCB: x = 0..74.0, y = 0..54.0, z = 0..1.6 mm
  Base floor: z = -4.5..-2.5 (2.0 mm thick), bottom THT clearance z = -2.5..0.0
  Lid cavity ceiling: z = 20.5, lid roof: z = 20.5..22.5 (total height = 27.0 mm)
"""

import json
from pathlib import Path

import cadquery as cq
import yaml

REPO = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((REPO / "hardware/product/spec.yaml").read_text())
VARIANT = SPEC["active_variant"]
BOARD_SPEC = SPEC["boards"]["main"]

PCB_W = float(BOARD_SPEC["max_outline"]["width"])
PCB_H = float(BOARD_SPEC["max_outline"]["height"])
PCB_T = float(BOARD_SPEC["thickness"])
WALL = float(SPEC["enclosure"]["wall"])
CLEAR = float(SPEC["enclosure"]["min_clearance_to_pcb"])
THT_DROP = 3.2
Z_FLOOR_TOP = -THT_DROP
Z_BASE_BOT = Z_FLOOR_TOP - WALL         # -5.2
Z_CAVITY_TOP = 20.5
Z_LID_TOP = Z_CAVITY_TOP + WALL         # 22.5
Z_SPLIT = 10.5                          # base/lid split plane

X0 = -CLEAR - WALL                      # -2.4
X1 = PCB_W + CLEAR + WALL               # 76.4
Y0 = -CLEAR - WALL                      # -2.4
Y1 = PCB_H + CLEAR + WALL               # 56.4
OUT_W = X1 - X0                         # 78.8
OUT_D = Y1 - Y0                         # 58.8

MIN_PRINT_GAP = 0.6                     # MJF PA12 / SLS anti-fusing clearance
PRINT_SPACING = 8.0                     # spacing between bodies on print plate

# C-shaped spring tab for SW1 (knx-dali-gateway / esp-measurement-platform style):
# round pad over the switch on an arm rooted toward -Y, thinned to `thickness`,
# rounded tactile bump with recessed X on top, plunger behind the pad.
BUTTON_TAB = {
    "pad": 3.0,
    "arm": 2.0,
    "arm_len": 4.2,
    "slot": MIN_PRINT_GAP,
    "thickness": 0.7,
    "nub": 1.4,
    "nub_gap": 0.1,
    "boss": 2.2,
    "boss_height": 0.6,
    "boss_round": 0.25,
}
BUTTON_CROSS = {"bar": 0.5, "depth": 0.35}

# Corner clamping screw ears (M3x12 socket head + M3 nut) on left/right walls
EARS = [
    (X0 - 3.5, 11.0),
    (X0 - 3.5, PCB_H - 11.0),
    (X1 + 3.5, 11.0),
    (X1 + 3.5, PCB_H - 11.0),
]

# UI coordinates from layout_main.yaml
SW1_XY = (41.5, 6.2)
LED_NET_XY = (52.0, 6.2)
LED_GATE_XY = (64.0, 6.2)

# Terminal cutouts from components_main.json bounding boxes (+0.35 mm margin) for WAGO 2086 SMD push-in blocks
BOTTOM_CUTOUTS = ((1.3, 33.2),)
TOP_CUTOUTS = ((1.25, 56.7),)
USB_Y = 27.0


def make_base():
    cx, cy = PCB_W / 2, PCB_H / 2
    base = cq.Workplane("XY").workplane(offset=Z_BASE_BOT).center(cx, cy).rect(OUT_W, OUT_D).extrude(Z_SPLIT - Z_BASE_BOT)
    # Inner cavity above floor
    cavity = (
        cq.Workplane("XY")
        .workplane(offset=Z_FLOOR_TOP)
        .center(cx, cy)
        .rect(PCB_W + 2 * CLEAR, PCB_H + 2 * CLEAR)
        .extrude(Z_SPLIT - Z_FLOOR_TOP + 1.0)
    )
    base = base.cut(cavity)

    # 4 PCB support ledges in verified B.Cu component-free zones (z = Z_FLOOR_TOP .. 0.0)
    for lx, ly in ((1.5, 15.0), (1.5, 39.0), (PCB_W - 1.5, 4.0), (PCB_W - 1.5, 26.0)):
        ledge = cq.Workplane("XY").workplane(offset=Z_FLOOR_TOP).center(lx, ly).rect(3.0, 3.0).extrude(THT_DROP)
        base = base.union(ledge)

    # M3 clamping ears + mounting zip-tie/screw tabs
    for ex, ey in EARS:
        ear = cq.Workplane("XY").workplane(offset=Z_BASE_BOT).center(ex, ey).circle(4.5).extrude(Z_SPLIT - Z_BASE_BOT)
        nut_hex = cq.Workplane("XY").workplane(offset=Z_BASE_BOT - 0.1).center(ex, ey).polygon(6, 6.3).extrude(2.6)
        hole = cq.Workplane("XY").workplane(offset=Z_BASE_BOT - 0.1).center(ex, ey).circle(1.7).extrude(Z_SPLIT - Z_BASE_BOT + 1.0)
        base = base.union(ear).cut(nut_hex).cut(hole)

    # Side mounting lugs (for screwing or zip-tying inside ROGER BH30 battery compartment)
    for lx, ly in ((X0 - 4.0, cy), (X1 + 4.0, cy)):
        lug = cq.Workplane("XY").workplane(offset=Z_BASE_BOT).center(lx, ly).rect(8.0, 14.0).extrude(4.0)
        slot = cq.Workplane("XY").workplane(offset=Z_BASE_BOT - 0.1).center(lx, ly).rect(3.5, 8.0).extrude(4.5)
        base = base.union(lug).cut(slot)

    # Cutouts for bottom WAGO 2086 terminals J1, J2A, J2B on -Y wall (z = 1.5..Z_SPLIT, closed by lid)
    for wx0, wx1 in BOTTOM_CUTOUTS:
        cut = (
            cq.Workplane("XY")
            .workplane(offset=1.5)
            .center((wx0 + wx1) / 2, Y0 + WALL / 2)
            .rect(wx1 - wx0, WALL + 2.0)
            .extrude(Z_SPLIT - 1.4)
        )
        base = base.cut(cut)

    # Cutouts for top WAGO 2086 terminals J3A, J3B, J4, J5 on +Y wall (z = 1.5..Z_SPLIT, closed by lid)
    for wx0, wx1 in TOP_CUTOUTS:
        cut = (
            cq.Workplane("XY")
            .workplane(offset=1.5)
            .center((wx0 + wx1) / 2, Y1 - WALL / 2)
            .rect(wx1 - wx0, WALL + 2.0)
            .extrude(Z_SPLIT - 1.4)
        )
        base = base.cut(cut)

    # USB-C service cutout on -X wall
    usb_cut = (
        cq.Workplane("XY")
        .workplane(offset=7.5)
        .center(X0 + WALL / 2, USB_Y)
        .rect(WALL + 2.0, 11.0)
        .extrude(Z_SPLIT - 7.0)
    )
    # Optional external U.FL antenna coax exit notch on +X wall (z = Z_SPLIT-3.2 .. Z_SPLIT)
    ant_cut = (
        cq.Workplane("XY")
        .workplane(offset=Z_SPLIT - 3.2)
        .center(X1 - WALL / 2, USB_Y)
        .rect(WALL + 2.0, 3.2)
        .extrude(3.7)
    )
    base = base.cut(usb_cut).cut(ant_cut)
    return base


# Lid engraved legends: (text, (x, y), size_mm, rot_deg)
# Pin coordinates match hardware/circuits/variants/v1/layout_main.yaml
def lid_legends():
    lbl_y = SW1_XY[1] + 4.8
    return [
        ("WIEGAND GATE CONTROLLER", (PCB_W * 0.5, PCB_H * 0.56), 3.1, 0),
        # Bottom edge row (aligned with RST / NET / GATE)
        ("PWR", (5.5, lbl_y), 2.3, 0),
        ("WIEGAND", (21.4, lbl_y), 2.3, 0),
        ("RST", (SW1_XY[0], lbl_y), 2.5, 0),
        ("NET", (LED_NET_XY[0], lbl_y), 2.5, 0),
        ("GATE", (LED_GATE_XY[0], lbl_y), 2.5, 0),
        # Left USB-C & Right ANT edges
        ("USB", (2.2, USB_Y), 2.2, 90),
        ("ANT", (PCB_W - 2.2, USB_Y), 2.2, 90),
        # Bottom terminal pins (J1, J2A, J2B at y = 3.8)
        ("V+", (3.75, 3.8), 1.9, 90),
        ("GND", (7.25, 3.8), 1.9, 90),
        ("12V", (12.10, 3.8), 1.9, 90),
        ("GND", (15.60, 3.8), 1.9, 90),
        ("D0", (19.10, 3.8), 1.9, 90),
        ("D1", (23.70, 3.8), 1.9, 90),
        ("LED", (27.20, 3.8), 1.9, 90),
        ("BEEP", (30.70, 3.8), 1.8, 90),
        # Top edge group headers
        ("RELAY 1", (7.2, 43.2), 2.1, 0),
        ("RELAY 2", (18.8, 43.2), 2.1, 0),
        ("SENSORS", (33.0, 43.2), 2.1, 0),
        ("EXIT / 12V", (49.0, 43.2), 2.1, 0),
        # Top terminal pins (J3A, J3B, J4, J5 at y = 50.0)
        ("NC", (3.70, 50.0), 1.9, 90),
        ("NO", (7.20, 50.0), 1.9, 90),
        ("COM", (10.70, 50.0), 1.8, 90),
        ("NC", (15.30, 50.0), 1.9, 90),
        ("NO", (18.80, 50.0), 1.9, 90),
        ("COM", (22.30, 50.0), 1.8, 90),
        ("IN2-", (27.75, 50.0), 1.8, 90),
        ("IN2+", (31.25, 50.0), 1.8, 90),
        ("IN1-", (34.75, 50.0), 1.8, 90),
        ("IN1+", (38.25, 50.0), 1.8, 90),
        ("GND", (43.75, 50.0), 1.8, 90),
        ("+12V", (47.25, 50.0), 1.8, 90),
        ("IN3-", (50.75, 50.0), 1.8, 90),
        ("IN3+", (54.25, 50.0), 1.8, 90),
    ]


def make_lid_legend_solids(z_top: float = Z_LID_TOP, depth: float = 0.45):
    solids = []
    for txt, (x, y), size, rot in lid_legends():
        t = cq.Workplane("XY").workplane(offset=z_top).text(txt, size, -depth, font="DejaVu Sans", kind="bold")
        if rot:
            t = t.rotate((0, 0, 0), (0, 0, 1), rot)
        solids.append(t.translate((x, y, 0)))
    return solids


def make_lid():
    cx, cy = PCB_W / 2, PCB_H / 2
    lid = cq.Workplane("XY").workplane(offset=Z_SPLIT).center(cx, cy).rect(OUT_W, OUT_D).extrude(Z_LID_TOP - Z_SPLIT)
    cavity = (
        cq.Workplane("XY")
        .workplane(offset=Z_SPLIT - 0.5)
        .center(cx, cy)
        .rect(PCB_W + 2 * CLEAR, PCB_H + 2 * CLEAR)
        .extrude(Z_CAVITY_TOP - Z_SPLIT + 0.5)
    )
    lid = lid.cut(cavity)

    # M3 clamping ears on lid
    for ex, ey in EARS:
        ear = cq.Workplane("XY").workplane(offset=Z_SPLIT).center(ex, ey).circle(4.5).extrude(Z_LID_TOP - Z_SPLIT)
        cbore = cq.Workplane("XY").workplane(offset=Z_LID_TOP - 3.2).center(ex, ey).circle(3.0).extrude(3.5)
        hole = cq.Workplane("XY").workplane(offset=Z_SPLIT - 0.2).center(ex, ey).circle(1.7).extrude(Z_LID_TOP - Z_SPLIT + 0.5)
        lid = lid.union(ear).cut(cbore).cut(hole)

    # USB-C service cutout on -X wall (crosses Z_SPLIT = 10.5)
    usb_cut = cq.Workplane("XY").workplane(offset=Z_SPLIT - 0.2).center(X0 + WALL / 2, USB_Y).rect(WALL + 2.0, 11.0).extrude(2.5)
    lid = lid.cut(usb_cut)

    # PCB hold-down corner pins from lid ceiling (stop at z = PCB_T + 0.3 mm over bare zones)
    for px, py in ((1.8, 39.0), (PCB_W - 1.8, 4.0)):
        pin = cq.Workplane("XY").workplane(offset=PCB_T + 0.3).center(px, py).circle(1.3).extrude(Z_CAVITY_TOP - PCB_T - 0.2)
        lid = lid.union(pin)

    # Compliant C-shaped Restart button tab rotated horizontally (-X root)
    # so RST, NET, GATE labels align along the same horizontal line above
    bx, by = SW1_XY
    bt = BUTTON_TAB
    root_x = bx - bt["arm_len"]

    def tab_solid(grow, z0, z1):
        pad = (
            cq.Workplane("XY")
            .workplane(offset=z0)
            .center(bx, by)
            .circle(bt["pad"] / 2 + grow)
            .extrude(z1 - z0)
        )
        arm = (
            cq.Workplane("XY")
            .workplane(offset=z0)
            .center((root_x + bx) / 2, by)
            .rect(bx - root_x, bt["arm"] + 2 * grow)
            .extrude(z1 - z0)
        )
        return pad.union(arm)

    through = (Z_CAVITY_TOP - 1.0, Z_LID_TOP + 1.0)
    tab_back = Z_LID_TOP - bt["thickness"]
    c_slot = tab_solid(bt["slot"], *through).cut(tab_solid(0.0, *through))
    thin_pocket = tab_solid(0.0, Z_CAVITY_TOP - 1.0, tab_back)

    bump = (
        cq.Workplane("XY")
        .workplane(offset=Z_LID_TOP - 0.01)
        .center(bx, by)
        .circle(bt["boss"] / 2)
        .extrude(bt["boss_height"] + 0.01)
        .faces(">Z")
        .edges()
        .fillet(bt["boss_round"])
    )
    cross_len = bt["boss"] + 0.6
    cross_bar = cq.Workplane("XY").box(cross_len, BUTTON_CROSS["bar"], BUTTON_CROSS["depth"] + 1.0, centered=(True, True, False))
    cross = (
        cross_bar.rotate((0, 0, 0), (0, 0, 1), 45)
        .union(cross_bar.rotate((0, 0, 0), (0, 0, 1), -45))
        .translate((bx, by, Z_LID_TOP + bt["boss_height"] - BUTTON_CROSS["depth"]))
    )
    bump = bump.cut(cross)

    sw1_top_z = PCB_T + 1.5
    plunger = (
        cq.Workplane("XY")
        .workplane(offset=sw1_top_z + bt["nub_gap"])
        .center(bx, by)
        .circle(bt["nub"] / 2)
        .extrude(tab_back + 0.01 - (sw1_top_z + bt["nub_gap"]))
    )
    lid = lid.cut(c_slot).cut(thin_pocket).union(plunger).union(bump)

    # 2x RGB LED blind light-pipe cavities + baffles over D6 (NET) and D7 (GATE),
    # capped by a 0.4 mm translucent plastic skin at the top surface
    led_skin = 0.4
    for lx, ly in (LED_NET_XY, LED_GATE_XY):
        baffle = (
            cq.Workplane("XY")
            .workplane(offset=3.8)
            .center(lx, ly)
            .circle(2.2)
            .circle(1.3)
            .extrude(Z_LID_TOP - led_skin - 3.8)
        )
        pocket = (
            cq.Workplane("XY")
            .workplane(offset=Z_CAVITY_TOP - 0.5)
            .center(lx, ly)
            .circle(1.3)
            .extrude((Z_LID_TOP - led_skin) - (Z_CAVITY_TOP - 0.5))
        )
        lid = lid.union(baffle).cut(pocket)

    # Engraved top legend (0.45 mm deep) — UI, terminals, and pinout
    for lbl in make_lid_legend_solids(Z_LID_TOP, 0.45):
        lid = lid.cut(lbl)
    return lid


def export_parts(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    pdir = out_dir / "print"
    pdir.mkdir(parents=True, exist_ok=True)

    base = make_base()
    lid = make_lid()

    cq.exporters.export(base, str(out_dir / "base.stl"))
    cq.exporters.export(base, str(out_dir / "base.step"))
    cq.exporters.export(lid, str(out_dir / "lid.stl"))
    cq.exporters.export(lid, str(out_dir / "lid.step"))

    assy = cq.Assembly()
    assy.add(base, name="base", color=cq.Color("gray25"))
    assy.add(lid, name="lid", color=cq.Color("slategray"))
    assy.save(str(out_dir / "assembly.step"))

    # JLC3DP print plate: base upright (z=0 on bed) and lid flipped upside-down (z=0 on bed), >= 8 mm apart
    base_bed = base.translate((0, 0, -Z_BASE_BOT))
    lid_bed = lid.rotate((PCB_W / 2, PCB_H / 2, Z_LID_TOP), (PCB_W / 2 + 1, PCB_H / 2, Z_LID_TOP), 180).translate((0, OUT_D + PRINT_SPACING, -Z_LID_TOP + 22.5))
    # Align lid_bed bottom z to 0
    lid_zmin = lid_bed.val().BoundingBox().zmin
    lid_bed = lid_bed.translate((0, 0, -lid_zmin))
    plate = base_bed.union(lid_bed)
    cq.exporters.export(plate, str(pdir / "enclosure_plate.stl"))
    cq.exporters.export(base_bed, str(pdir / "base_print.stl"))
    cq.exporters.export(lid_bed, str(pdir / "lid_print.stl"))

    # Export fit check JSON
    summary = {
        "outer_mm": [round(OUT_W, 2), round(OUT_D, 2), round(Z_LID_TOP - Z_BASE_BOT, 2)],
        "pcb_mm": [PCB_W, PCB_H, PCB_T],
        "base_solids": len(base.solids().vals()),
        "lid_solids": len(lid.solids().vals()),
        "plate_solids": len(plate.solids().vals()),
    }
    (out_dir / "enclosure_summary.json").write_text(json.dumps(summary, indent=2))
    print("Enclosure exported:", json.dumps(summary))


if __name__ == "__main__":
    export_parts(REPO / "mechanical/build" / VARIANT)
