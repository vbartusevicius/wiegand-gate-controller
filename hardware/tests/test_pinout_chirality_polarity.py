"""Gate 1: Independent Datasheet Pinout, Footprint Chirality & Polarity Verification (`eda` container).

Operates strictly on the final routed `.kicad_pcb` and exported production `main_bom.csv`
with ZERO imports from `hardware/circuits/` or `hardware/scripts/`.
"""

from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew
import pytest
import yaml

REPO = Path("/work")
SPEC = yaml.safe_load((REPO / "hardware/product/spec.yaml").read_text())
VARIANT = SPEC["active_variant"]
PCB_PATH = REPO / "hardware/layout" / VARIANT / "main/main.kicad_pcb"
REL_PCB_PATH = REPO / "hardware/releases" / VARIANT / "main/main.kicad_pcb"
BOM_PATH = REPO / "hardware/releases" / VARIANT / "main/main_bom.csv"


@pytest.fixture(scope="module")
def board_and_bom():
    assert PCB_PATH.exists(), f"Missing routed board: {PCB_PATH}"
    assert BOM_PATH.exists(), f"Missing exported production BOM: {BOM_PATH}"
    board = pcbnew.LoadBoard(str(PCB_PATH))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()

    bom_by_ref: dict[str, dict[str, str]] = {}
    with open(BOM_PATH, newline="") as f:
        for row in csv.DictReader(f):
            for ref in [r.strip() for r in row["Designators"].split(",") if r.strip()]:
                assert ref not in bom_by_ref, f"Duplicate designator {ref} in BOM"
                bom_by_ref[ref] = row
    return board, bom_by_ref


def pad_nets(fp: pcbnew.FOOTPRINT) -> dict[str, str]:
    out: dict[str, str] = {}
    for pad in fp.Pads():
        num = pad.GetNumber()
        if not num:
            continue
        net = pad.GetNetname()
        if num in out:
            assert out[num] == net, f"{fp.GetReference()} duplicate pad {num} has mismatched nets: {out[num]} vs {net}"
        out[num] = net
    return out


def mount_view_xy(fp: pcbnew.FOOTPRINT, x_nm: int, y_nm: int) -> tuple[float, float]:
    """Transform KiCad board coordinates into the component's right-handed mounting-face view (+X right, +Y up)."""
    cx, cy = pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)
    dx = pcbnew.ToMM(x_nm) - cx
    dy = pcbnew.ToMM(y_nm) - cy
    return (dx, dy) if fp.IsFlipped() else (dx, -dy)


def shoelace_area(pts: list[tuple[float, float]]) -> float:
    n = len(pts)
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))


def test_zero_circuit_generator_imports(board_and_bom):
    forbidden = [
        name
        for name, mod in sys.modules.items()
        if getattr(mod, "__file__", None)
        and any(seg in str(mod.__file__) for seg in ("/hardware/circuits/", "/hardware/scripts/"))
    ]
    assert forbidden == [], f"Independent verification gate must not import generator modules: {forbidden}"

    board, bom_by_ref = board_and_bom
    pcb_refs = {fp.GetReference() for fp in board.Footprints() if not fp.IsDNP()}
    assert pcb_refs == set(bom_by_ref), (
        f"PCB vs BOM designator mismatch: only_pcb={sorted(pcb_refs - set(bom_by_ref))}, "
        f"only_bom={sorted(set(bom_by_ref) - pcb_refs)}"
    )
    assert REL_PCB_PATH.exists(), "Release .kicad_pcb snapshot missing"


def test_footprint_jedec_ccw_chirality(board_and_bom):
    """Verify counter-clockwise JEDEC top-view pin winding on every >=3-pin package across F.Cu and B.Cu."""
    board, bom_by_ref = board_and_bom
    checked = 0
    for ref, row in sorted(bom_by_ref.items()):
        fp = board.FindFootprintByReference(ref)
        mpn = row["MPN"]
        if ref.startswith("J"):
            # Terminal blocks: two inline SMD pads per pole, monotonic pole spacing along connector axis
            by_pole: dict[int, list[tuple[float, float]]] = defaultdict(list)
            for pad in fp.Pads():
                if pad.GetNumber().isdigit():
                    by_pole[int(pad.GetNumber())].append(mount_view_xy(fp, pad.GetPosition().x, pad.GetPosition().y))
            poles = sorted(by_pole)
            assert len(poles) >= 2
            centers = [(sum(p[0] for p in by_pole[k]) / len(by_pole[k]), sum(p[1] for p in by_pole[k]) / len(by_pole[k])) for k in poles]
            step_x = [centers[i + 1][0] - centers[i][0] for i in range(len(centers) - 1)]
            step_y = [centers[i + 1][1] - centers[i][1] for i in range(len(centers) - 1)]
            # Strictly 3.50 mm monotonic pitch along primary axis
            pitches = [math.hypot(dx, dy) for dx, dy in zip(step_x, step_y)]
            for pitch in pitches:
                assert math.isclose(pitch, 3.5, abs_tol=0.05), f"{ref} ({mpn}) unexpected pole pitch {pitch:.3f} mm"
            continue

        # Group pads by numeric pin number
        grouped: dict[int, list[tuple[float, float]]] = defaultdict(list)
        for pad in fp.Pads():
            if pad.GetNumber().isdigit():
                grouped[int(pad.GetNumber())].append(mount_view_xy(fp, pad.GetPosition().x, pad.GetPosition().y))
        if len(grouped) < 3:
            continue

        # Separate central exposed thermal pad (pin 9 on SOIC-8-EP) from perimeter pins
        perim_nums = sorted(grouped)
        if mpn == "TPS54360DDAR":
            assert 9 in grouped, f"{ref} missing exposed thermal pad 9"
            ep_pts = grouped.pop(9)
            perim_nums = sorted(grouped)
            ep_cx = sum(p[0] for p in ep_pts) / len(ep_pts)
            ep_cy = sum(p[1] for p in ep_pts) / len(ep_pts)
            assert math.hypot(ep_cx, ep_cy) < 0.25, f"{ref} thermal pad not centered: ({ep_cx:.2f}, {ep_cy:.2f})"

        pts = [
            (sum(p[0] for p in grouped[n]) / len(grouped[n]), sum(p[1] for p in grouped[n]) / len(grouped[n]))
            for n in perim_nums
        ]
        area = shoelace_area(pts)
        side = "B.Cu" if fp.IsFlipped() else "F.Cu"
        assert area > 0.2, (
            f"{ref} ({mpn} on {side}) failed JEDEC CCW chirality check: signed shoelace area = {area:.3f} mm^2 <= 0 "
            f"(mirrored footprint or inverted pin order!)"
        )
        checked += 1

    assert checked >= 22, f"Expected >=22 multi-pin active/relay/diode packages checked, got {checked}"


def test_independent_datasheet_mpn_pin_roles(board_and_bom):
    """Audit every IC, optocoupler, transistor, LED, and relay pin against standalone datasheet pin-role rules."""
    board, bom_by_ref = board_and_bom

    # Build net -> list[(ref, pin_num, mpn, value)] map strictly from PCB pads + BOM
    net_members: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    fp_pads: dict[str, dict[str, str]] = {}
    for ref, row in bom_by_ref.items():
        fp = board.FindFootprintByReference(ref)
        pn = pad_nets(fp)
        fp_pads[ref] = pn
        for num, net in pn.items():
            if net:
                net_members[net].append((ref, num, row["MPN"], row["Value"]))

    def peers_on(net: str, exclude_ref: str) -> list[tuple[str, str, str, str]]:
        return [m for m in net_members.get(net, []) if m[0] != exclude_ref]

    def other_net_of_2pin(ref_2p: str, net_here: str) -> str:
        nets = list(fp_pads[ref_2p].values())
        assert len(nets) == 2
        return nets[1] if nets[0] == net_here else nets[0]

    for ref, row in sorted(bom_by_ref.items()):
        mpn = row["MPN"]
        pn = fp_pads[ref]

        if mpn == "TPS54360DDAR":
            # TI TPS54360DDAR (SLVSBB4): 1=BOOT, 2=VIN, 3=EN, 4=RT/CLK, 5=FB, 6=COMP, 7=GND, 8=SW, 9=PowerPAD(GND)
            assert set(pn) == {"1", "2", "3", "4", "5", "6", "7", "8", "9"}
            assert pn["2"] == "VIN_PROT"
            assert pn["7"] == "GND" and pn["9"] == "GND"
            sw_net = pn["8"]
            assert sw_net.endswith("_SW")
            # Pin 1 (BOOT) must connect via 100nF bootstrap capacitor to Pin 8 (SW)
            boot_peers = peers_on(pn["1"], ref)
            assert len(boot_peers) == 1 and boot_peers[0][0].startswith("C") and boot_peers[0][3].startswith("100n")
            assert other_net_of_2pin(boot_peers[0][0], pn["1"]) == sw_net
            # Pin 8 (SW) must connect to inductor L + Schottky catch diode cathode (pin 1) + bootstrap cap
            sw_peers = peers_on(sw_net, ref)
            ind_refs = [r for r, _, _, _ in sw_peers if r.startswith("L")]
            dio_peers = [(r, pnum, dmpn) for r, pnum, dmpn, _ in sw_peers if r.startswith("D")]
            assert len(ind_refs) == 1 and len(dio_peers) == 1
            assert dio_peers[0][1] == "1" and dio_peers[0][2] == "B360A-13-F"
            assert other_net_of_2pin(dio_peers[0][0], sw_net) == "GND"
            vout_net = other_net_of_2pin(ind_refs[0], sw_net)
            assert vout_net in ("+5V", "+12V_RDR")
            # Pin 3 (EN): UVLO resistor divider between VIN_PROT and GND
            en_others = {other_net_of_2pin(r, pn["3"]) for r, _, _, _ in peers_on(pn["3"], ref) if r.startswith("R")}
            assert en_others == {"VIN_PROT", "GND"}, f"{ref} EN divider nets wrong: {en_others}"
            # Pin 4 (RT/CLK): timing resistor to GND
            rt_peers = peers_on(pn["4"], ref)
            assert len(rt_peers) == 1 and rt_peers[0][0].startswith("R") and rt_peers[0][3] == "130k"
            assert other_net_of_2pin(rt_peers[0][0], pn["4"]) == "GND"
            # Pin 5 (FB): divider between VOUT and GND checking exact feedback ratio for 0.8V Vref
            fb_res = {other_net_of_2pin(r, pn["5"]): val for r, _, _, val in peers_on(pn["5"], ref) if r.startswith("R")}
            assert set(fb_res) == {vout_net, "GND"}, f"{ref} FB divider nets wrong: {fb_res}"
            if vout_net == "+5V":
                assert fb_res["+5V"] == "53k6" and fb_res["GND"] == "10k2"
            else:
                assert fb_res["+12V_RDR"] == "140k" and fb_res["GND"] == "10k"
            # Pin 6 (COMP): HF pole cap (68p) to GND + series R-C compensation to GND
            comp_peers = peers_on(pn["6"], ref)
            comp_caps = [r for r, _, _, val in comp_peers if r.startswith("C") and val.startswith("68p")]
            comp_res = [r for r, _, _, val in comp_peers if r.startswith("R") and val == "53k6"]
            assert len(comp_caps) == 1 and other_net_of_2pin(comp_caps[0], pn["6"]) == "GND"
            assert len(comp_res) == 1
            cc_net = other_net_of_2pin(comp_res[0], pn["6"])
            cc_caps = [r for r, _, _, _ in peers_on(cc_net, comp_res[0]) if r.startswith("C")]
            assert len(cc_caps) == 1 and other_net_of_2pin(cc_caps[0], cc_net) == "GND"

        elif mpn == "102010636":
            # Seeed Studio XIAO ESP32-C6 module pinout
            assert pn["12"] == "+3V3" and pn["13"] == "GND" and pn["14"] == "+5V_XIAO"
            assert pn["1"] == "VIN_ADC" and pn["2"] == "BTN_RESTART"
            assert pn["3"] == "WG_D0_MCU" and pn["10"] == "WG_D1_MCU"
            assert pn["4"] == "LED_DATA"
            assert pn["5"] == "I2C_SDA" and pn["6"] == "I2C_SCL"
            assert pn["11"] == "EXP_INT"
            assert pn["7"] == "" and pn["8"] == "" and pn["9"] == ""

        elif mpn == "TCA9534DWR":
            # TI TCA9534DWR SOIC-16: 1=A0, 2=A1, 3=A2, 4..7=P0..P3, 8=GND, 9..12=P4..P7, 13=/INT, 14=SCL, 15=SDA, 16=VCC
            assert pn["8"] == "GND" and pn["16"] == "+3V3"
            assert all(pn[p] in ("GND", "+3V3") for p in ("1", "2", "3"))
            assert pn["13"] == "EXP_INT" and pn["14"] == "I2C_SCL" and pn["15"] == "I2C_SDA"
            assert {pn["4"], pn["5"], pn["6"], pn["7"]} == {"RELAY1_DRV", "RELAY2_DRV", "WG_LED_DRV", "WG_BEEP_DRV"}
            assert {pn["9"], pn["10"], pn["11"]} == {"IN1_MCU", "IN2_MCU", "IN3_MCU"}

        elif mpn == "SN74AHCT1G125DBVR":
            # TI 74AHCT1G125 SOT-23-5: 1=/OE(GND), 2=A(3.3V in), 3=GND, 4=Y(5V out), 5=VCC(+5V)
            assert pn["1"] == "GND" and pn["3"] == "GND" and pn["5"] == "+5V"
            assert pn["2"] == "LED_DATA" and pn["4"] == "LED_BUF"

        elif mpn == "SN74LVC2G17DBVR(UMW)":
            # Dual Schmitt buffer SOT-23-6 (asymmetric!): 1=1A, 2=GND, 3=2A, 4=2Y, 5=VCC(+3V3), 6=1Y
            assert pn["2"] == "GND" and pn["5"] == "+3V3"
            assert pn["1"] == "WG_D0_IN" and pn["6"] == "WG_D0_MCU"
            assert pn["3"] == "WG_D1_IN" and pn["4"] == "WG_D1_MCU"

        elif mpn == "WS2812B-MINI-V3J":
            # Worldsemi WS2812B-MINI-V3J: 1=VDD(+5V), 2=DOUT, 3=VSS(GND), 4=DIN
            assert pn["1"] == "+5V" and pn["3"] == "GND"
            if ref == "D6":
                assert pn["4"] == "LED_DIN" and pn["2"] == "LED_CHAIN1"
            elif ref == "D7":
                assert pn["4"] == "LED_CHAIN1" and pn["2"] == ""

        elif mpn == "EL357N(C)(TA)-G":
            # Everlight EL357N SOP-4: 1=Anode, 2=Cathode, 3=Emitter(GND), 4=Collector(MCU pull-up)
            assert pn["3"] == "GND"
            assert pn["1"].endswith("_LED_A") and pn["2"].endswith("_N") and pn["4"].endswith("_MCU")
            ch = pn["1"].split("_")[0]
            assert pn["2"].startswith(ch) and pn["4"].startswith(ch)

        elif mpn == "MMBT3904(RANGE:100-300)":
            # SOT-23 NPN: 1=B, 2=E(GND), 3=C(low-side switched load)
            assert pn["2"] == "GND"
            assert pn["1"].endswith("_BASE")
            assert pn["3"] in ("R1_COIL_N", "R2_COIL_N", "WG_LED_COL", "WG_BEEP_COL")
            b_res = {other_net_of_2pin(r, pn["1"]) for r, _, _, _ in peers_on(pn["1"], ref) if r.startswith("R")}
            assert "GND" in b_res and len(b_res) == 2

        elif mpn == "G6S-2F DC5":
            # Omron G6S-2F DPDT relay: 1=Coil+(+5V), 12=Coil-, 3&10=NC, 4&9=COM, 5&8=NO
            assert pn["1"] == "+5V" and pn["12"].endswith("_COIL_N")
            assert pn["3"] == pn["10"] and pn["3"].endswith("_NC")
            assert pn["4"] == pn["9"] and pn["4"].endswith("_COM")
            assert pn["5"] == pn["8"] and pn["5"].endswith("_NO")
            # Contacts must be completely isolated from board rails/GND
            for cpin in ("3", "4", "5"):
                assert pn[cpin] not in ("GND", "+3V3", "+5V", "+12V_RDR", "+12V_RDR_OUT", "VIN_RAW", "VIN_PROT")


def test_buses_and_two_pin_passives(board_and_bom):
    """Verify non-swapped I2C (+ unique slave addresses) & Wiegand channels, and zero shorted/open 2-pin passives."""
    board, bom_by_ref = board_and_bom
    fp_pads = {ref: pad_nets(board.FindFootprintByReference(ref)) for ref in bom_by_ref}

    # 1. I2C bus integrity + unique 7-bit address audit
    sda_net, scl_net = fp_pads["U3"]["5"], fp_pads["U3"]["6"]
    assert sda_net != scl_net and sda_net == "I2C_SDA" and scl_net == "I2C_SCL"
    assert fp_pads["U4"]["15"] == sda_net and fp_pads["U4"]["14"] == scl_net
    for bus_net in (sda_net, scl_net):
        pullups = [
            ref
            for ref, row in bom_by_ref.items()
            if ref.startswith("R") and set(fp_pads[ref].values()) == {bus_net, "+3V3"} and row["Value"] == "2k2"
        ]
        assert len(pullups) == 1, f"Expected exactly one 2.2k pull-up to +3V3 on {bus_net}, found {pullups}"

    i2c_addrs = {}
    for ref, row in bom_by_ref.items():
        if row["MPN"] == "TCA9534DWR":
            a0 = 1 if fp_pads[ref]["1"] == "+3V3" else 0
            a1 = 1 if fp_pads[ref]["2"] == "+3V3" else 0
            a2 = 1 if fp_pads[ref]["3"] == "+3V3" else 0
            addr = 0x20 | (a2 << 2) | (a1 << 1) | a0
            assert addr not in i2c_addrs, f"Duplicate I2C address 0x{addr:02x} between {i2c_addrs[addr]} and {ref}"
            i2c_addrs[addr] = ref
    assert i2c_addrs == {0x20: "U4"}

    # 2. Wiegand D0 / D1 non-swapped end-to-end continuity from terminal blocks to MCU ISR pins
    assert fp_pads["J2A"]["3"] == "WG_D0_TERM" and fp_pads["J2B"]["1"] == "WG_D1_TERM"
    assert set(fp_pads["R31"].values()) == {"WG_D0_TERM", fp_pads["U6"]["1"]}
    assert fp_pads["U6"]["6"] == fp_pads["U3"]["3"] == "WG_D0_MCU"
    assert set(fp_pads["R33"].values()) == {"WG_D1_TERM", fp_pads["U6"]["3"]}
    assert fp_pads["U6"]["4"] == fp_pads["U3"]["10"] == "WG_D1_MCU"

    # 3. Zero shorted or open 2-pin passives/fuses/inductors/switches
    two_pin_count = 0
    for ref in sorted(bom_by_ref):
        if ref.startswith(("R", "C", "L", "F")) or ref == "SW1":
            pn = fp_pads[ref]
            assert set(pn) == {"1", "2"}, f"{ref} expected pads 1 & 2, got {set(pn)}"
            assert pn["1"] != "" and pn["2"] != "", f"{ref} has open/unconnected pad: {pn}"
            assert pn["1"] != pn["2"], f"{ref} has both pads shorted to same net {pn['1']!r}"
            two_pin_count += 1
    assert two_pin_count == 80, f"Expected 80 two-pin passives/fuses/inductors/switches, checked {two_pin_count}"


def test_diode_polarity_and_silkscreen_marks(board_and_bom):
    """Verify DC Anode/Cathode bias and physical silkscreen cathode/Pin-1 mark proximity on every diode/TVS/LED."""
    board, bom_by_ref = board_and_bom
    nominal_dc_v = {
        "GND": 0.0,
        "+3V3": 3.3,
        "+5V_XIAO": 4.7,
        "+5V": 5.0,
        "5V_SW": 5.0,
        "+12V_RDR": 12.0,
        "+12V_RDR_OUT": 12.0,
        "12V_SW": 12.0,
        "VIN_RAW": 24.0,
        "VIN_FUSED": 24.0,
        "VIN_PROT": 23.7,
        "R1_COIL_N": 5.0,  # idle off-state collector at +5V via coil
        "R2_COIL_N": 5.0,
        "WG_D0_IN": 5.0,
        "WG_D1_IN": 5.0,
        "WG_LED_COL": 5.0,
        "WG_BEEP_COL": 5.0,
    }

    for ref, row in sorted(bom_by_ref.items()):
        fp = board.FindFootprintByReference(ref)
        mpn = row["MPN"]
        pn = pad_nets(fp)
        silk_layer = pcbnew.B_SilkS if fp.IsFlipped() else pcbnew.F_SilkS

        if mpn in ("SMAJ36A", "SMAJ15A", "B360A-13-F", "SS14", "SS36"):
            # KiCad D_SMA: Pad 1 = Cathode (K), Pad 2 = Anode (A)
            k_net, a_net = pn["1"], pn["2"]
            vk, va = nominal_dc_v[k_net], nominal_dc_v[a_net]
            if ref in ("D2", "D5"):
                # Forward series reverse-blocking Schottky: V(Anode) > V(Cathode)
                assert va > vk, f"{ref} ({mpn}) series blocking diode reversed: A={a_net}({va}V), K={k_net}({vk}V)"
            else:
                # Reverse-biased TVS / buck catch / relay flyback diode: V(Cathode) >= V(Anode) in idle DC
                assert vk >= va and not (vk == 0.0 and va == 0.0), (
                    f"{ref} ({mpn}) clamp/catch/flyback diode forward-shorted in DC: A={a_net}({va}V), K={k_net}({vk}V)"
                )

            # Physical silkscreen cathode mark proximity: silk shapes on mounting face must be closer to K (pad 1) than A (pad 2)
            p1 = fp.FindPadByNumber("1").GetPosition()
            p2 = fp.FindPadByNumber("2").GetPosition()
            k_xy = (pcbnew.ToMM(p1.x), pcbnew.ToMM(p1.y))
            a_xy = (pcbnew.ToMM(p2.x), pcbnew.ToMM(p2.y))
            silk_pts = []
            for g in fp.GraphicalItems():
                if g.GetLayer() == silk_layer:
                    bb = g.GetBoundingBox()
                    silk_pts.append(
                        ((pcbnew.ToMM(bb.GetLeft()) + pcbnew.ToMM(bb.GetRight())) / 2,
                         (pcbnew.ToMM(bb.GetTop()) + pcbnew.ToMM(bb.GetBottom())) / 2)
                    )
            assert silk_pts, f"{ref} ({mpn}) missing physical silkscreen polarity marking"
            sx = sum(p[0] for p in silk_pts) / len(silk_pts)
            sy = sum(p[1] for p in silk_pts) / len(silk_pts)
            dk = math.hypot(sx - k_xy[0], sy - k_xy[1])
            da = math.hypot(sx - a_xy[0], sy - a_xy[1])
            assert dk < da, f"{ref} silkscreen cathode mark closer to Anode ({da:.2f}mm) than Cathode ({dk:.2f}mm)"

        elif mpn == "BAT54S,215":
            # Nexperia BAT54S SOT-23 dual series Schottky: 1=Anode1, 2=Cathode2, 3=Common(K1/A2)
            if pn["2"] != "":
                # Dual rail clamp between GND (1) and +5V (2)
                assert pn["1"] == "GND" and pn["2"] == "+5V", f"{ref} BAT54S rail clamp reversed: {pn}"
                assert 0.0 <= nominal_dc_v[pn["3"]] <= 5.0
            else:
                # Single reverse-protection diode across opto LED (1=INx_N -> 3=INx_LED_A)
                assert pn["1"].endswith("_N") and pn["3"].endswith("_LED_A"), f"{ref} opto clamp wrong: {pn}"

        elif mpn == "WS2812B-MINI-V3J":
            # Verify physical silkscreen Pin-1 circle is closest to Pad 1 (VDD)
            pad_xy = {
                p.GetNumber(): (pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
                for p in fp.Pads()
                if p.GetNumber()
            }
            circles = [
                g for g in fp.GraphicalItems()
                if g.GetLayer() == silk_layer and g.Type() == pcbnew.PCB_SHAPE_T and g.GetShape() == pcbnew.SHAPE_T_CIRCLE
            ]
            assert len(circles) == 1, f"{ref} missing silkscreen Pin-1 dot"
            c_bb = circles[0].GetBoundingBox()
            cx = (pcbnew.ToMM(c_bb.GetLeft()) + pcbnew.ToMM(c_bb.GetRight())) / 2
            cy = (pcbnew.ToMM(c_bb.GetTop()) + pcbnew.ToMM(c_bb.GetBottom())) / 2
            nearest = min(pad_xy, key=lambda n: math.hypot(cx - pad_xy[n][0], cy - pad_xy[n][1]))
            assert nearest == "1", f"{ref} silkscreen Pin-1 dot closest to pad {nearest}, expected pad 1"

        elif ref in ("U4", "U6", "U8", "U9", "U10"):
            pad_xy = {
                p.GetNumber(): (pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
                for p in fp.Pads()
                if p.GetNumber()
            }
            circles = [
                g for g in fp.GraphicalItems()
                if g.GetLayer() == silk_layer and g.Type() == pcbnew.PCB_SHAPE_T and g.GetShape() == pcbnew.SHAPE_T_CIRCLE
            ]
            assert len(circles) == 1, f"{ref} missing silkscreen Pin-1 dot"
            c_bb = circles[0].GetBoundingBox()
            cx = (pcbnew.ToMM(c_bb.GetLeft()) + pcbnew.ToMM(c_bb.GetRight())) / 2
            cy = (pcbnew.ToMM(c_bb.GetTop()) + pcbnew.ToMM(c_bb.GetBottom())) / 2
            nearest = min(pad_xy, key=lambda n: math.hypot(cx - pad_xy[n][0], cy - pad_xy[n][1]))
            assert nearest == "1", f"{ref} silkscreen Pin-1 dot closest to pad {nearest}, expected pad 1"
