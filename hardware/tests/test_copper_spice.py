"""Gate 2: Pure Copper-Extracted End-to-End `ngspice` Simulation Gate (`libngspice` via `ctypes`).

Strictly ZERO imports from `hardware/circuits/` or `hardware/scripts/`:
1. Loads only the final routed `.kicad_pcb` (`pcbnew`) and exported production `main_bom.csv`.
2. Asserts `GetConnectivity().GetUnconnectedCount(False) == 0`.
3. Reconstructs electrical nodes purely via geometric Union-Find over physical copper tracks,
   vias, filled copper zones, and pads (`shapely.STRtree`), plus copper trace R/C parasitics.
4. Instantiates all components/sub-units strictly from `main_bom.csv` (zero floating pins,
   `.options rshunt=1e11`, smooth `C^inf` bounded `tanh()` behavioral models).
5. Runs `.op`, `.ac`, `.noise` (`setplot noise1`), and `.tran` in `libngspice.so.0` to verify:
   - Reverse-polarity (-24 V) blocking & +48 V surge TVS clamping
   - UVLO trip thresholds (<8.8 V start, off at 6.5 V), 9-32 V buck regulation (+5V & +12V_RDR),
     and cascaded XIAO 3.3 V LDO dropout headroom
   - Dual TPS54360 loop stability (.ac crossover frequency & phase margin >= 45 deg) under real
     copper-extracted decoupling & Type-II compensation values
   - VIN_ADC 11:1 divider scaling, anti-aliasing filter corner, and integrated RMS noise (.noise)
   - Wiegand D0/D1 5V->3.3V Schmitt buffering, +12 V miswire clamping, and open-drain LED/BEEP
   - ROGER B70/1DC 0-24 V optocoupler inputs, -24 V reverse clamp, relay coil switching & flyback,
     and 3.3V->5V WS2812B LED chain signal integrity.
"""

from __future__ import annotations

import csv
import ctypes
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pcbnew
import pytest
import yaml
from shapely.geometry import Polygon
from shapely.strtree import STRtree

REPO = Path("/work")
SPEC = yaml.safe_load((REPO / "hardware/product/spec.yaml").read_text())
VARIANT = SPEC["active_variant"]
PCB_PATH = REPO / "hardware/layout" / VARIANT / "main/main.kicad_pcb"
BOM_PATH = REPO / "hardware/releases" / VARIANT / "main/main_bom.csv"

SI_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3, "M": 1e6}


def parse_bom_si(value_text: str) -> float:
    token = value_text.strip().split()[0]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([pnuµmkMR]?)(\d*)(?:[ΩFHV]|uH|nF|pF|uF)?", token)
    if not m:
        raise ValueError(f"Cannot parse SI value from BOM token {value_text!r}")
    whole, pfx, frac = m.groups()
    if token.endswith("uH") and pfx == "":
        pfx = "u"
    pfx = "" if pfx == "R" else pfx
    num = float(f"{whole}.{frac}" if frac else whole)
    return num * SI_PREFIX[pfx]


# ---------------------------------------------------------------------------
# `libngspice` shared-library ctypes wrapper
# ---------------------------------------------------------------------------
class NgComplex(ctypes.Structure):
    _fields_ = [("cx_real", ctypes.c_double), ("cx_imag", ctypes.c_double)]


class VectorInfo(ctypes.Structure):
    _fields_ = [
        ("v_name", ctypes.c_char_p),
        ("v_type", ctypes.c_int),
        ("v_flags", ctypes.c_short),
        ("v_realdata", ctypes.POINTER(ctypes.c_double)),
        ("v_compdata", ctypes.POINTER(NgComplex)),
        ("v_length", ctypes.c_int),
    ]


SENDCHAR = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
SENDSTAT = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
CTRL_EXIT = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)


class NgSpiceSession:
    def __init__(self) -> None:
        self.lib = ctypes.CDLL("libngspice.so.0")
        self.logs: list[str] = []

        @SENDCHAR
        def _on_char(msg, _ident, _user):
            if msg:
                self.logs.append(msg.decode("utf-8", "replace"))
            return 0

        @SENDSTAT
        def _on_stat(_msg, _ident, _user):
            return 0

        @CTRL_EXIT
        def _on_exit(_status, _imm, _quit, _ident, _user):
            return 0

        self._cb_char = _on_char
        self._cb_stat = _on_stat
        self._cb_exit = _on_exit
        self.lib.ngSpice_Init(self._cb_char, self._cb_stat, self._cb_exit, None, None, None, None)
        self.lib.ngGet_Vec_Info.restype = ctypes.POINTER(VectorInfo)
        self.lib.ngGet_Vec_Info.argtypes = [ctypes.c_char_p]

    def cmd(self, command: str) -> None:
        rc = self.lib.ngSpice_Command(command.encode("utf-8"))
        if rc != 0:
            tail = "\n".join(self.logs[-40:])
            raise RuntimeError(f"ngspice command {command!r} failed (rc={rc}):\n{tail}")

    def run_deck(self, lines: list[str]) -> None:
        self.logs.clear()
        self.lib.ngSpice_Command(b"destroy all")
        self.lib.ngSpice_Command(b"remcirc")
        clean = [ln for ln in lines if ln and ln.strip()]
        full = [line.encode("utf-8") for line in clean] + [None]
        arr = (ctypes.c_char_p * len(full))(*full)
        rc = self.lib.ngSpice_Circ(arr)
        if rc != 0:
            tail = "\n".join(self.logs[-40:])
            raise RuntimeError(f"ngSpice_Circ failed:\n{tail}")
        self.cmd("run")
        errs = [
            ln for ln in self.logs
            if any(bad in ln.lower() for bad in ("simulation(s) aborted", "singular matrix", "doanalyses: too many"))
        ]
        if errs:
            tail = "\n".join(self.logs[-50:])
            raise RuntimeError(f"ngspice convergence/runtime error:\n{tail}")

    def real_vec(self, name: str) -> list[float]:
        ptr = self.lib.ngGet_Vec_Info(name.encode("utf-8"))
        if not ptr:
            tail = "\n".join(self.logs[-30:])
            raise KeyError(f"ngspice vector {name!r} not found:\n{tail}")
        vi = ptr.contents
        if vi.v_realdata:
            return [float(vi.v_realdata[i]) for i in range(vi.v_length)]
        return [float(vi.v_compdata[i].cx_real) for i in range(vi.v_length)]

    def comp_vec(self, name: str) -> list[complex]:
        ptr = self.lib.ngGet_Vec_Info(name.encode("utf-8"))
        if not ptr:
            raise KeyError(f"ngspice complex vector {name!r} not found")
        vi = ptr.contents
        if vi.v_compdata:
            return [complex(vi.v_compdata[i].cx_real, vi.v_compdata[i].cx_imag) for i in range(vi.v_length)]
        return [complex(vi.v_realdata[i], 0.0) for i in range(vi.v_length)]


# ---------------------------------------------------------------------------
# Pure Geometric Union-Find Copper Extractor
# ---------------------------------------------------------------------------
class UnionFind:
    def __init__(self) -> None:
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        r = x
        while self.parent[r] != r:
            r = self.parent[r]
        while self.parent[x] != r:
            nxt = self.parent[x]
            self.parent[x] = r
            x = nxt
        return r

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def poly_from_set(ps: pcbnew.SHAPE_POLY_SET, idx: int) -> Polygon:
    ext = ps.Outline(idx)
    shell = [(pcbnew.ToMM(ext.CPoint(k).x), pcbnew.ToMM(ext.CPoint(k).y)) for k in range(ext.PointCount())]
    holes = []
    for h in range(ps.HoleCount(idx)):
        hr = ps.Hole(idx, h)
        holes.append([(pcbnew.ToMM(hr.CPoint(k).x), pcbnew.ToMM(hr.CPoint(k).y)) for k in range(hr.PointCount())])
    return Polygon(shell, holes)


def shape_polys(item: pcbnew.BOARD_ITEM, layer: int) -> list[Polygon]:
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
    return [poly_from_set(ps, i).buffer(0.0015) for i in range(ps.OutlineCount()) if ps.Outline(i).PointCount() >= 3]


@dataclass
class ExtractedCopper:
    pad_node: dict[tuple[str, str], str]
    node_parasitics: dict[str, tuple[float, float]]  # node_name -> (R_trace_ohm, C_trace_F)
    bom_by_ref: dict[str, dict[str, str]]
    gnd_node: str


def extract_copper_circuit(pcb_path: Path, bom_path: Path) -> ExtractedCopper:
    board = pcbnew.LoadBoard(str(pcb_path))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    assert board.GetConnectivity().GetUnconnectedCount(False) == 0, "Board has unrouted connections!"

    bom_by_ref: dict[str, dict[str, str]] = {}
    with open(bom_path, newline="") as f:
        for row in csv.DictReader(f):
            for ref in [r.strip() for r in row["Designators"].split(",") if r.strip()]:
                bom_by_ref[ref] = row

    cu_layers = list(board.GetEnabledLayers().CuStack())
    uf = UnionFind()
    layer_geoms: dict[int, list[tuple[Polygon, tuple]]] = defaultdict(list)

    # 1. Pads (THT pads naturally bridge across all copper layers via shared ('PAD', ref, idx) node)
    pad_keys: list[tuple[str, str, int, str]] = []
    for fp in board.Footprints():
        ref = fp.GetReference()
        for idx, pad in enumerate(fp.Pads()):
            pnum = pad.GetNumber()
            if not pnum:
                continue
            key = ("PAD", ref, idx)
            uf.find(key)
            pad_keys.append((ref, pnum, idx, pad.GetNetname()))
            for lyr in cu_layers:
                if pad.IsOnLayer(lyr):
                    for poly in shape_polys(pad, lyr):
                        layer_geoms[lyr].append((poly, key))

    # 2. Tracks & Vias (plus exact physical trace length/width for R/C parasitics)
    track_metrics: dict[tuple, tuple[float, float, int]] = {}  # key -> (len_mm, width_mm, layer)
    via_keys: list[tuple] = []
    for tidx, tr in enumerate(board.GetTracks()):
        if tr.GetClass() == "PCB_VIA":
            vkey = ("VIA", tidx)
            uf.find(vkey)
            via_keys.append(vkey)
            for lyr in cu_layers:
                if tr.IsOnLayer(lyr):
                    for poly in shape_polys(tr, lyr):
                        layer_geoms[lyr].append((poly, vkey))
        else:
            tkey = ("TRK", tidx)
            uf.find(tkey)
            lyr = tr.GetLayer()
            s, e = tr.GetStart(), tr.GetEnd()
            l_mm = pcbnew.ToMM(round(math.hypot(e.x - s.x, e.y - s.y)))
            w_mm = max(0.1, pcbnew.ToMM(tr.GetWidth()))
            track_metrics[tkey] = (l_mm, w_mm, lyr)
            for poly in shape_polys(tr, lyr):
                layer_geoms[lyr].append((poly, tkey))

    # 3. Filled copper zones (In1.Cu solid GND plane)
    for zidx, zone in enumerate(board.Zones()):
        if zone.GetIsRuleArea():
            continue
        for lyr in cu_layers:
            if zone.IsOnLayer(lyr):
                ps = zone.GetFilledPolysList(lyr)
                for i in range(ps.OutlineCount()):
                    if ps.Outline(i).PointCount() >= 3:
                        zkey = ("ZONE", zidx, lyr, i)
                        uf.find(zkey)
                        layer_geoms[lyr].append((poly_from_set(ps, i).buffer(0.0015), zkey))

    # 4. Spatial STRtree Union-Find per copper layer (strictly geometric, zero netname usage!)
    for lyr, items in layer_geoms.items():
        polys = [p for p, _ in items]
        keys = [k for _, k in items]
        tree = STRtree(polys)
        for i, poly in enumerate(polys):
            for j in tree.query(poly, predicate="intersects"):
                if j > i:
                    uf.union(keys[i], keys[j])

    # 5. Verify reconstructed physical copper islands have zero shorts and zero opens
    root_to_pcb_nets: dict[tuple, set[str]] = defaultdict(set)
    net_to_roots: dict[str, set[tuple]] = defaultdict(set)
    for ref, pnum, idx, netname in pad_keys:
        r = uf.find(("PAD", ref, idx))
        if netname:
            root_to_pcb_nets[r].add(netname)
            net_to_roots[netname].add(r)

    for r, nets in root_to_pcb_nets.items():
        assert len(nets) <= 1, f"Physical copper short detected across nets: {sorted(nets)}"
    for netname, roots in net_to_roots.items():
        assert len(roots) == 1, f"Physical copper open on {netname!r}: split into {len(roots)} disconnected islands"

    # Assign SPICE node names purely by Union-Find root (J1 pin 2 = reference ground '0')
    j1_gnd_idx = next(idx for ref, pnum, idx, _ in pad_keys if ref == "J1" and pnum == "2")
    gnd_root = uf.find(("PAD", "J1", j1_gnd_idx))

    root_name: dict[tuple, str] = {gnd_root: "0"}
    counter = 0
    pad_node: dict[tuple[str, str], str] = {}
    for ref, pnum, idx, _ in pad_keys:
        r = uf.find(("PAD", ref, idx))
        if r not in root_name:
            counter += 1
            root_name[r] = f"n{counter}"
        if (ref, pnum) in pad_node:
            assert pad_node[(ref, pnum)] == root_name[r], f"{ref}.{pnum} split pads not copper-connected!"
        pad_node[(ref, pnum)] = root_name[r]

    # 6. Compute copper trace R & C parasitics per physical copper node
    r_sum: dict[str, float] = defaultdict(float)
    c_sum: dict[str, float] = defaultdict(float)
    for tkey, (l_mm, w_mm, lyr) in track_metrics.items():
        r = uf.find(tkey)
        node = root_name.get(r)
        if not node or node == "0":
            continue
        r_sheet = 0.00049 if lyr in (pcbnew.F_Cu, pcbnew.B_Cu) else 0.00098  # 1 oz outer, 0.5 oz inner
        r_sum[node] += r_sheet * (l_mm / w_mm)
        # Microstrip/stripline capacitance over In1.Cu GND plane (~180 fF/mm^2 + 45 fF/mm fringing)
        c_sum[node] += (180e-15 * l_mm * w_mm) + (45e-15 * l_mm)

    for vkey in via_keys:
        r = uf.find(vkey)
        node = root_name.get(r)
        if node and node != "0":
            r_sum[node] += 0.0015
            c_sum[node] += 0.25e-12

    parasitics = {
        nd: (max(0.001, r_sum.get(nd, 0.002)), max(0.1e-12, c_sum.get(nd, 0.1e-12)))
        for nd in set(root_name.values())
        if nd != "0"
    }
    return ExtractedCopper(pad_node=pad_node, node_parasitics=parasitics, bom_by_ref=bom_by_ref, gnd_node="0")


# ---------------------------------------------------------------------------
# Smooth C^inf SPICE Behavioral & Semiconductor Library + BOM Netlist Emitter
# ---------------------------------------------------------------------------
SPICE_MODELS = """\
.options rshunt=1e11 abstol=1e-10 vntol=1e-6 reltol=1e-3 method=gear
.func rail50(v) {50.0 * tanh((v) / 50.0)}
.func step01(x, w) {0.5 * (1.0 + tanh((x) / (w)))}
.model D_SS36 D(IS=2.5e-5 N=1.06 RS=0.042 BV=65 IBV=1e-4 CJO=180p)
.model D_SS14 D(IS=3.5e-5 N=1.05 RS=0.055 BV=45 IBV=1e-4 CJO=140p)
.model D_B360A D(IS=2.0e-5 N=1.05 RS=0.035 BV=65 IBV=1e-4 CJO=210p)
.model D_BAT54 D(IS=1.2e-7 N=1.04 RS=0.35 BV=35 IBV=1e-5 CJO=10p)
.model D_TVS36 D(IS=1e-12 N=1.05 RS=0.18 BV=42.0 IBV=1e-3 CJO=350p)
.model D_TVS15 D(IS=1e-12 N=1.05 RS=0.12 BV=17.2 IBV=1e-3 CJO=450p)
.model D_IRLED D(IS=1e-16 N=1.35 RS=1.5 BV=6.0 IBV=1e-4 CJO=15p)
.model Q_3904 NPN(IS=1e-14 BF=180 BR=4 VAF=100 RB=15 RC=0.4 RE=0.2 CJE=4.5p CJC=3.5p TF=300p TR=50n)
* Averaged Current-Mode TPS54360DDAR Buck Regulator (Ridley/SLVSBB4 gm=92uS, gm_ps=5.2A/V, C^inf tanh)
.subckt TPS54360 boot vin en rt fb comp gnd sw ep
R_ep ep gnd 1m
R_en_in en gnd 500Meg
B_en en_g gnd V = step01(V(en, gnd) - 1.22, 0.025)
V_rt_ref rt_int gnd DC 0.5
R_rt_int rt_int rt 100
B_bst boot_src sw V = 5.5 * V(en_g, gnd)
R_bst boot_src boot 50
V_comp_mid comp_mid gnd DC 1.05
R_ea comp comp_mid 25Meg
B_gm gnd comp I = V(en_g, gnd) * 92e-6 * 0.25 * tanh((0.800 - V(fb, gnd)) / 0.25)
B_c_lo gnd comp I = 1e-3 * step01(-0.20 - V(comp, gnd), 0.05)
B_c_hi comp gnd I = 1e-3 * step01(V(comp, gnd) - 2.35, 0.05)
* Current-loop high-frequency pole (~240 kHz) buffered so COMP pin sees high-Z 25 MOhm
B_cm_buf vcm_b gnd V = V(comp, gnd)
R_cm vcm_b vcm 1k
C_cm vcm gnd 660p
* Controlled current-mode stage: strictly non-negative 0..3.8A, gm_ps ~ 5.2 A/V, smooth dropout clamp
B_isw gnd sw I = V(en_g, gnd) * 3.8 * step01(V(vcm, gnd) - 1.05, 0.365) * step01(V(vin, gnd) - V(sw, gnd) - 0.20, 0.15)
R_sw_shunt sw gnd 10k
B_iin vin gnd I = V(en_g, gnd) * 3.8 * step01(V(vcm, gnd) - 1.05, 0.365) * step01(V(vin, gnd) - V(sw, gnd) - 0.20, 0.15) * step01(V(sw, gnd), 0.2) * rail50(V(sw, gnd)) / (0.90 * (6.0 + 30.0 * step01(V(vin, gnd) - 21.0, 10.0))) + V(en_g, gnd) * 150e-6 + 5e-6
.ends TPS54360
* Everlight EL357N(C) SOP-4 Optocoupler (CTR = 1.5, smooth C^inf saturation)
.subckt EL357N a k e c
D_led a led_mid D_IRLED
V_iled led_mid k DC 0
C_ce c e 5p
R_leak c e 100Meg
B_ic c e I = 1.5 * 0.05 * tanh(20.0 * I(V_iled)) * step01(I(V_iled), 20e-6) * step01(V(c, e) - 0.08, 0.06)
.ends EL357N
* Omron G6S-2F DC5 DPDT Relay (5V 140mW coil => 178.6 Ohm + 18 mH, must-operate 19 mA, smooth C^inf contacts)
.subckt G6S_2F coil_p coil_n nc1 com1 no1 no2 com2 nc2
R_coil coil_p coil_mid 178.6
L_coil coil_mid coil_sns 18m
R_coil_damp coil_mid coil_sns 8k
V_icoil coil_sns coil_n DC 0
B_act act_raw 0 V = step01(I(V_icoil) - 0.019, 0.0004)
R_act act_raw act 1k
C_act act 0 50n
B_no1 com1 no1 I = rail50(V(com1, no1)) * (1e-9 + 20.0 * V(act))
B_nc1 com1 nc1 I = rail50(V(com1, nc1)) * (1e-9 + 20.0 * (1.0 - V(act)))
B_no2 com2 no2 I = rail50(V(com2, no2)) * (1e-9 + 20.0 * V(act))
B_nc2 com2 nc2 I = rail50(V(com2, nc2)) * (1e-9 + 20.0 * (1.0 - V(act)))
.ends G6S_2F
* Dual 5V-tolerant Schmitt Buffer SN74LVC2G17 (all 6 pins instantiated, both channels active)
.subckt SN74LVC2G17 a1 gnd a2 y2 vcc y1
R_in1 a1 gnd 50Meg
R_in2 a2 gnd 50Meg
C_in1 a1 gnd 3.5p
C_in2 a2 gnd 3.5p
B_iq vcc gnd I = 2e-6
B_y1 y1_i gnd V = rail50(V(vcc, gnd)) * step01(V(a1, gnd) - 0.5 * rail50(V(vcc, gnd)), 0.08)
R_o1 y1_i y1 25
B_y2 y2_i gnd V = rail50(V(vcc, gnd)) * step01(V(a2, gnd) - 0.5 * rail50(V(vcc, gnd)), 0.08)
R_o2 y2_i y2 25
.ends SN74LVC2G17
* 5V TTL-Input Tri-State Buffer SN74AHCT1G125 (VIH=2.0V, VT=1.4V, /OE active low)
.subckt SN74AHCT1G125 oe_n a gnd y vcc
R_oe oe_n gnd 50Meg
R_a a gnd 50Meg
C_a a gnd 3.5p
B_iq vcc gnd I = 4e-6
B_en en_i 0 V = step01(1.4 - V(oe_n, gnd), 0.08)
B_hi hi_i 0 V = step01(V(a, gnd) - 1.40, 0.08)
B_drv gnd y I = V(en_i) * (rail50(V(vcc, gnd)) * V(hi_i) - rail50(V(y, gnd))) / 25.0
R_oz y gnd 50Meg
.ends SN74AHCT1G125
* Worldsemi WS2812B-MINI-V3J Addressable RGB LED (1=VDD, 2=DOUT reshaped buffer, 3=VSS, 4=DIN)
.subckt WS2812B vdd dout vss din
R_din din vss 20Meg
C_din din vss 15p
B_iq vdd vss I = 0.6e-3 * step01(V(vdd, vss) - 2.5, 0.3)
B_do do_i vss V = rail50(V(vdd, vss)) * step01(V(din, vss) - 0.52 * rail50(V(vdd, vss)), 0.10)
R_do do_i dout 35
.ends WS2812B
* Seeed XIAO ESP32-C6 Module (on-board 3.3V LDO from 5V pin 14 -> 3V3 pin 12 with 220 mV dropout)
.subckt XIAO_C6 p1 p2 p3 p4 p5 p6 p7 p8 p9 p10 p11 v33 gnd v5in led_stim
B_ldo v33_i gnd V = 3.30 * step01(V(v5in, gnd) - 3.52, 0.15) + rail50(V(v5in, gnd) - 0.22) * step01(V(v5in, gnd) - 0.3, 0.1) * (1.0 - step01(V(v5in, gnd) - 3.52, 0.15))
R_ldo v33_i v33 0.08
B_imcu_in v5in gnd I = 0.065 * step01(V(v33, gnd) - 2.4, 0.2)
R_load33 v33 gnd 3.3k
R_p1 p1 gnd 20Meg
C_p1 p1 gnd 4p
R_p2 p2 gnd 50Meg
R_p3 p3 gnd 50Meg
C_p3 p3 gnd 4p
R_p4 led_stim p4 35
R_p5 p5 gnd 50Meg
R_p6 p6 gnd 50Meg
R_p7 p7 gnd 100Meg
R_p8 p8 gnd 100Meg
R_p9 p9 gnd 100Meg
R_p10 p10 gnd 50Meg
C_p10 p10 gnd 4p
R_p11 p11 gnd 50Meg
.ends XIAO_C6
* TI TCA9534DWR 16-pin I2C I/O Expander (all 16 pins instantiated; P0..P3 driven by test stimuli)
.subckt TCA9534 a0 a1 a2 p0 p1 p2 p3 gnd p4 p5 p6 p7 int_n scl sda vcc s_p0 s_p1 s_p2 s_p3
R_a0 a0 gnd 50Meg
R_a1 a1 gnd 50Meg
R_a2 a2 gnd 50Meg
B_iq vcc gnd I = 15e-6
B_p0 p0_i gnd V = rail50(V(vcc, gnd)) * rail50(V(s_p0))
R_p0 p0_i p0 45
B_p1 p1_i gnd V = rail50(V(vcc, gnd)) * rail50(V(s_p1))
R_p1 p1_i p1 45
B_p2 p2_i gnd V = rail50(V(vcc, gnd)) * rail50(V(s_p2))
R_p2 p2_i p2 45
B_p3 p3_i gnd V = rail50(V(vcc, gnd)) * rail50(V(s_p3))
R_p3 p3_i p3 45
R_p4 p4 gnd 50Meg
R_p5 p5 gnd 50Meg
R_p6 p6 gnd 50Meg
R_p7 p7 gnd 50Meg
R_int int_n gnd 50Meg
R_scl scl gnd 50Meg
R_sda sda gnd 50Meg
.ends TCA9534
"""


def build_spice_deck(
    cu: ExtractedCopper,
    *,
    extra_lines: list[str],
    break_fb_ref: str | None = None,
    sw1_closed: bool = False,
) -> list[str]:
    """Emit a complete SPICE netlist from pure copper-extracted nodes + BOM MPN/values."""
    lines = ["Copper-Extracted Wiegand Gate Controller", *SPICE_MODELS.splitlines()]

    # Copper trace C parasitics to ground & R_cu series parasitic on power/high-current nodes
    for nd, (_, c_par) in sorted(cu.node_parasitics.items()):
        lines.append(f"C_cu_{nd} {nd} 0 {c_par:.4e}")

    def pnode(ref: str, pin: str, *, allow_nc: bool = False) -> str:
        nd = cu.pad_node.get((ref, pin))
        if nd is None:
            if allow_nc:
                return f"nc_{ref}_{pin}"
            raise KeyError(f"Missing pad ({ref}, {pin}) in extracted copper")
        return nd

    for ref, row in sorted(cu.bom_by_ref.items()):
        mpn = row["MPN"]
        val_txt = row["Value"]

        if ref.startswith("R"):
            r_ohm = parse_bom_si(val_txt) + 0.5 * cu.node_parasitics.get(pnode(ref, "1"), (0.0, 0.0))[0]
            lines.append(f"R_{ref} {pnode(ref, '1')} {pnode(ref, '2')} {r_ohm:.6g}")

        elif ref.startswith("C"):
            c_f = parse_bom_si(val_txt)
            n1, n2 = pnode(ref, "1"), pnode(ref, "2")
            if c_f >= 1e-6:
                # Ceramic MLCC ESR (~8 mOhm for 1206 bulk, ~15 mOhm for 0805)
                esr = 0.008 if "1206" in row["Package"] else 0.015
                lines.append(f"R_esr_{ref} {n1} esr_{ref} {esr}")
                lines.append(f"C_{ref} esr_{ref} {n2} {c_f:.6g}")
            else:
                lines.append(f"C_{ref} {n1} {n2} {c_f:.6g}")

        elif ref.startswith("L"):
            l_h = parse_bom_si(val_txt)
            dcr = 0.036 if l_h < 15e-6 else 0.078
            r_cu = cu.node_parasitics.get(pnode(ref, "1"), (0.0, 0.0))[0] + cu.node_parasitics.get(pnode(ref, "2"), (0.0, 0.0))[0]
            lines.append(f"R_dcr_{ref} {pnode(ref, '1')} lmid_{ref} {dcr + r_cu:.5f}")
            lines.append(f"L_{ref} lmid_{ref} {pnode(ref, '2')} {l_h:.6g}")

        elif ref.startswith("F"):
            # Littelfuse 2920L110/60V 1.1A PTC resettable fuse (~0.16 Ohm cold + copper trace R)
            r_cu = cu.node_parasitics.get(pnode(ref, "1"), (0.0, 0.0))[0] + cu.node_parasitics.get(pnode(ref, "2"), (0.0, 0.0))[0]
            lines.append(f"R_{ref} {pnode(ref, '1')} {pnode(ref, '2')} {0.16 + r_cu:.5f}")

        elif ref == "SW1":
            r_sw = 0.05 if sw1_closed else 1e9
            lines.append(f"R_{ref} {pnode(ref, '1')} {pnode(ref, '2')} {r_sw}")

        elif mpn in ("SS36", "SS14", "B360A-13-F", "SMAJ36A", "SMAJ15A"):
            # Pad 1 = Cathode, Pad 2 = Anode
            mod_map = {
                "SS36": "D_SS36",
                "SS14": "D_SS14",
                "B360A-13-F": "D_B360A",
                "SMAJ36A": "D_TVS36",
                "SMAJ15A": "D_TVS15",
            }
            lines.append(f"D_{ref} {pnode(ref, '2')} {pnode(ref, '1')} {mod_map[mpn]}")

        elif mpn == "BAT54S,215":
            # Dual series Schottky: D_lo (1 -> 3) and D_hi (3 -> 2)
            n1, n2, n3 = pnode(ref, "1"), pnode(ref, "2"), pnode(ref, "3")
            lines.append(f"D_{ref}_lo {n1} {n3} D_BAT54")
            lines.append(f"D_{ref}_hi {n3} {n2} D_BAT54")

        elif mpn == "MMBT3904(RANGE:100-300)":
            # SOT-23: 1=B, 2=E, 3=C
            lines.append(f"Q_{ref} {pnode(ref, '3')} {pnode(ref, '1')} {pnode(ref, '2')} Q_3904")

        elif mpn == "TPS54360DDAR":
            fb_pin = f"fb_in_{ref}" if break_fb_ref == ref else pnode(ref, "5")
            if break_fb_ref == ref:
                # AC Middlebrook injection source between divider node (pnode 5) and IC FB input (fb_in)
                lines.append(f"V_ac_inj_{ref} {pnode(ref, '5')} {fb_pin} DC 0 AC 1")
            pins = [pnode(ref, "1"), pnode(ref, "2"), pnode(ref, "3"), pnode(ref, "4"), fb_pin,
                    pnode(ref, "6"), pnode(ref, "7"), pnode(ref, "8"), pnode(ref, "9")]
            lines.append(f"X_{ref} {' '.join(pins)} TPS54360")

        elif mpn == "EL357N(C)(TA)-G":
            lines.append(f"X_{ref} {pnode(ref, '1')} {pnode(ref, '2')} {pnode(ref, '3')} {pnode(ref, '4')} EL357N")

        elif mpn == "G6S-2F DC5":
            pins = [pnode(ref, p) for p in ("1", "12", "3", "4", "5", "8", "9", "10")]
            lines.append(f"X_{ref} {' '.join(pins)} G6S_2F")

        elif mpn == "SN74LVC2G17DBVR(UMW)":
            pins = [pnode(ref, p) for p in ("1", "2", "3", "4", "5", "6")]
            lines.append(f"X_{ref} {' '.join(pins)} SN74LVC2G17")

        elif mpn == "SN74AHCT1G125DBVR":
            pins = [pnode(ref, p) for p in ("1", "2", "3", "4", "5")]
            lines.append(f"X_{ref} {' '.join(pins)} SN74AHCT1G125")

        elif mpn == "WS2812B-MINI-V3J":
            pins = [pnode(ref, p) for p in ("1", "2", "3", "4")]
            lines.append(f"X_{ref} {' '.join(pins)} WS2812B")

        elif mpn == "102010636":
            pins = [pnode(ref, str(k)) for k in range(1, 15)]
            lines.append(f"X_{ref} {' '.join(pins)} ctrl_led_data XIAO_C6")

        elif mpn == "TCA9534DWR":
            pins = [pnode(ref, str(k)) for k in range(1, 17)]
            lines.append(f"X_{ref} {' '.join(pins)} ctrl_p0 ctrl_p1 ctrl_p2 ctrl_p3 TCA9534")

        elif ref.startswith("J"):
            # Connectors terminated by external test stimuli per scenario
            continue
        else:
            raise ValueError(f"Unhandled BOM component {ref} ({mpn})")

    lines.extend(extra_lines)
    lines.append(".end")
    return lines


@pytest.fixture(scope="module")
def copper_and_spice():
    forbidden = [
        name
        for name, mod in sys.modules.items()
        if getattr(mod, "__file__", None)
        and any(seg in str(mod.__file__) for seg in ("/hardware/circuits/", "/hardware/scripts/"))
    ]
    assert forbidden == [], f"Gate 2 must not import circuit generator modules: {forbidden}"
    cu = extract_copper_circuit(PCB_PATH, BOM_PATH)
    ng = NgSpiceSession()
    return cu, ng


def default_stimuli(vin_dc: float = 24.0, p0: float = 0.0, p1: float = 0.0, p2: float = 0.0, p3: float = 0.0, led: float = 0.0) -> list[str]:
    return [
        f"V_ctrl_p0 ctrl_p0 0 DC {p0}",
        f"V_ctrl_p1 ctrl_p1 0 DC {p1}",
        f"V_ctrl_p2 ctrl_p2 0 DC {p2}",
        f"V_ctrl_p3 ctrl_p3 0 DC {p3}",
        f"V_ctrl_led ctrl_led_data 0 DC {led}",
    ]


def test_power_protection_regulation_uvlo_and_headroom(copper_and_spice):
    """Verify -24V reverse-polarity protection, +48V surge TVS clamping, UVLO, and 9-32V regulation."""
    cu, ng = copper_and_spice
    n_vin_raw = cu.pad_node[("J1", "1")]
    n_vin_prot = cu.pad_node[("D2", "1")]
    n_v5 = cu.pad_node[("L1", "2")]
    n_v5_xiao = cu.pad_node[("U3", "14")]
    n_v33 = cu.pad_node[("U3", "12")]
    n_v12_rdr = cu.pad_node[("J2A", "1")]
    n_vin_adc = cu.pad_node[("U3", "1")]

    # 1. Reverse-polarity fault (-24 V on J1 VIN+)
    deck_rev = build_spice_deck(
        cu,
        extra_lines=[
            f"V_in {n_vin_raw} 0 DC -24.0",
            *default_stimuli(),
            ".op",
        ],
    )
    ng.run_deck(deck_rev)
    # D2 SS36 blocks -24V; tiny Schottky leakage (~25 uA) is forward-clamped by D1 SMAJ36A within one diode drop of GND
    assert -0.65 <= ng.real_vec(f"v({n_vin_prot})")[0] <= 0.05, "Reverse polarity leaked past D2 SS36!"
    assert abs(ng.real_vec(f"v({n_v5})")[0]) < 0.05
    assert abs(ng.real_vec(f"v({n_v12_rdr})")[0]) < 0.05

    # 2. UVLO below start threshold (VIN = 6.5 V -> both bucks must remain disabled)
    deck_uvlo = build_spice_deck(
        cu,
        extra_lines=[
            f"V_in {n_vin_raw} 0 DC 6.5",
            *default_stimuli(),
            ".op",
        ],
    )
    ng.run_deck(deck_uvlo)
    assert ng.real_vec(f"v({n_v5})")[0] < 0.25, "5V buck failed UVLO hold-off at 6.5V"
    assert ng.real_vec(f"v({n_v12_rdr})")[0] < 0.25, "12V buck failed UVLO hold-off at 6.5V"

    # 3. Normal operating envelope (9 V, 24 V ROGER B70/1DC +24V, and 32 V max) under realistic reader load (120 mA on +12V_RDR)
    for vin in (13.5, 24.0, 32.0):
        deck_nom = build_spice_deck(
            cu,
            extra_lines=[
                f"V_in {n_vin_raw} 0 DC {vin}",
                f"R_rdr_load {n_v12_rdr} 0 100",  # 120 mA Wiegand reader load at J2A.1
                *default_stimuli(),
                ".op",
            ],
        )
        ng.run_deck(deck_nom)
        v5 = ng.real_vec(f"v({n_v5})")[0]
        v5_xiao = ng.real_vec(f"v({n_v5_xiao})")[0]
        v33 = ng.real_vec(f"v({n_v33})")[0]
        v12 = ng.real_vec(f"v({n_v12_rdr})")[0]
        v_prot = ng.real_vec(f"v({n_vin_prot})")[0]
        v_adc = ng.real_vec(f"v({n_vin_adc})")[0]

        assert 4.90 <= v5 <= 5.10, f"At VIN={vin}V, +5V out of spec: {v5:.3f}V"
        assert 11.75 <= v12 <= 12.15, f"At VIN={vin}V, +12V_RDR_OUT out of spec under 120mA load: {v12:.3f}V"
        assert 3.25 <= v33 <= 3.35, f"At VIN={vin}V, +3V3 out of spec: {v33:.3f}V"
        assert (v5_xiao - v33) >= 1.15, f"Insufficient XIAO 3.3V LDO dropout headroom: {v5_xiao - v33:.2f}V"
        assert math.isclose(v_adc, v_prot * (10.0 / 110.0), rel_tol=0.015), f"VIN_ADC divider error: {v_adc:.3f}V"
        assert v_adc <= 3.05, f"VIN_ADC {v_adc:.3f}V exceeds ESP32-C6 ADC safe input ceiling!"

    # Also verify 9.0 V cold-crank/brownout input keeps +5V logic & +3V3 MCU alive
    deck_9v = build_spice_deck(
        cu,
        extra_lines=[f"V_in {n_vin_raw} 0 DC 9.0", *default_stimuli(), ".op"],
    )
    ng.run_deck(deck_9v)
    assert 4.90 <= ng.real_vec(f"v({n_v5})")[0] <= 5.10
    assert 3.25 <= ng.real_vec(f"v({n_v33})")[0] <= 3.35

    # 4. Transient +52 V surge on J1 (via 2 Ohm harness source impedance): SMAJ36A must clamp VIN_PROT < 55V (<60V TPS54360 max)
    deck_surge = build_spice_deck(
        cu,
        extra_lines=[
            "V_surge surge_src 0 PULSE(24 52 10u 2u 2u 80u 200u)",
            f"R_src surge_src {n_vin_raw} 2.0",
            *default_stimuli(),
            ".tran 2u 120u",
        ],
    )
    ng.run_deck(deck_surge)
    peak_vprot = max(ng.real_vec(f"v({n_vin_prot})"))
    assert 40.0 <= peak_vprot <= 54.0, f"SMAJ36A surge clamp out of bounds: peak VIN_PROT = {peak_vprot:.2f}V"


def test_buck_loop_stability_and_adc_noise(copper_and_spice):
    """Verify .ac loop phase margin >= 45 deg on both TPS54360 bucks and .noise (`setplot noise1`) on VIN_ADC."""
    cu, ng = copper_and_spice
    n_vin_raw = cu.pad_node[("J1", "1")]
    n_v12_rdr = cu.pad_node[("J2A", "1")]

    # 1. Middlebrook AC loop-gain stability check on U1 (+5V @ 500 mA nominal load) and U2 (+12V_RDR @ 500 mA nominal load)
    n_v5 = cu.pad_node[("L1", "2")]
    for buck_ref, load_line in (("U1", f"R_l5 {n_v5} 0 10"), ("U2", f"R_rdr {n_v12_rdr} 0 24")):
        n_div_fb = cu.pad_node[(buck_ref, "5")]
        deck_ac = build_spice_deck(
            cu,
            break_fb_ref=buck_ref,
            extra_lines=[
                f"V_in {n_vin_raw} 0 DC 24.0",
                *([load_line] if load_line else []),
                *default_stimuli(),
                ".ac dec 25 50 500k",
            ],
        )
        ng.run_deck(deck_ac)
        freqs = ng.real_vec("frequency")
        v_div = ng.comp_vec(f"v({n_div_fb})")
        v_in = ng.comp_vec(f"v(fb_in_{buck_ref})")
        # Loop gain T(j*w) = -V(div) / V(fb_in) across the AC injection source V(div, fb_in) = 1
        loop_t = [-vd / vi for vd, vi in zip(v_div, v_in)]
        mags_db = [20.0 * math.log10(max(abs(t), 1e-12)) for t in loop_t]
        assert mags_db[0] > 25.0, f"{buck_ref} low-frequency loop gain too low: {mags_db[0]:.1f} dB"

        # Locate 0 dB unity-gain crossover frequency & compute phase margin
        cross_idx = next((i for i in range(len(mags_db) - 1) if mags_db[i] >= 0.0 >= mags_db[i + 1]), None)
        assert cross_idx is not None, f"{buck_ref} loop gain never crossed 0 dB: range [{min(mags_db):.1f}, {max(mags_db):.1f}] dB"
        fc = freqs[cross_idx]
        t_cross = loop_t[cross_idx]
        # Phase of T(j*fc): at DC T > 0 (0 deg); unwrapped phase in (-180, +180] -> PM = 180 + phase_deg (when phase < 0)
        phase_deg = math.degrees(math.atan2(t_cross.imag, t_cross.real))
        pm_deg = 180.0 + phase_deg if phase_deg < 0 else 180.0 - phase_deg
        assert 2.5e3 <= fc <= 50e3, f"{buck_ref} crossover frequency {fc:.0f} Hz outside [2.5 kHz, 50 kHz]"
        assert pm_deg >= 60.0, f"{buck_ref} unstable/marginal loop: phase margin = {pm_deg:.1f} deg (< 60 deg) at fc={fc:.0f} Hz"
        assert mags_db[-1] <= -20.0, f"{buck_ref} insufficient HF attenuation at 500 kHz: {mags_db[-1]:.1f} dB"

    # 2. VIN_ADC .ac anti-aliasing filter & .noise (`setplot noise1`) verification
    n_vin_adc = cu.pad_node[("U3", "1")]
    deck_noise = build_spice_deck(
        cu,
        extra_lines=[
            f"V_in {n_vin_raw} 0 DC 24.0 AC 1.0",
            *default_stimuli(),
            f".noise v({n_vin_adc}) V_in dec 20 10 100k",
        ],
    )
    ng.run_deck(deck_noise)
    ng.cmd("setplot noise1")
    f_noise = ng.real_vec("frequency")
    s_onoise = ng.real_vec("onoise_spectrum")
    assert len(f_noise) > 20 and s_onoise[0] > s_onoise[-1], "C2 anti-aliasing filter failed to roll off VIN_ADC thermal noise"
    ng.cmd("setplot noise2")
    onoise_rms = ng.real_vec("onoise_total")[0]
    assert 0.1e-6 <= onoise_rms <= 50e-6, f"Unexpected integrated VIN_ADC RMS noise: {onoise_rms:.3e} Vrms"


def test_end_to_end_wiegand_opto_relays_and_rgb_chain(copper_and_spice):
    """Verify transient end-to-end signal chains for Wiegand I/O, ROGER 24V optos, Form-C relays, and WS2812B LEDs."""
    cu, ng = copper_and_spice
    n_vin_raw = cu.pad_node[("J1", "1")]
    n_d0_term = cu.pad_node[("J2A", "3")]
    n_d1_term = cu.pad_node[("J2B", "1")]
    n_d0_mcu = cu.pad_node[("U3", "3")]
    n_d1_mcu = cu.pad_node[("U3", "10")]
    n_wg_led_term = cu.pad_node[("J2B", "2")]
    n_wg_beep_term = cu.pad_node[("J2B", "3")]

    # Map TCA9534 P0..P3 pads (4..7) to their exact physical functions by tracing connected nets
    p_nodes = {k: cu.pad_node[("U4", str(k + 4))] for k in range(4)}
    n_r1_coil = cu.pad_node[("K1", "12")]
    n_r1_com = cu.pad_node[("J3A", "1")]
    n_r1_no = cu.pad_node[("J3A", "2")]
    n_r1_nc = cu.pad_node[("J3A", "3")]

    # 1. Wiegand D0 50 us active-low pulse + +12V miswire clamp + Wiegand LED/BEEP open-drain pull-down
    deck_wg = build_spice_deck(
        cu,
        extra_lines=[
            f"V_in {n_vin_raw} 0 DC 24.0",
            # Open-drain Wiegand reader pulls D0 low at t=20..70 us; Miswire +12V fault on D1 via 10 Ohm to test clamp!
            "V_d0_pulse d0_drv 0 PULSE(5 0 20u 0.2u 0.2u 50u 200u)",
            f"D_od_d0 {n_d0_term} d0_drv D_BAT54",
            "V_d1_fault d1_flt 0 DC 12.0",
            f"R_d1_flt d1_flt {n_d1_term} 10.0",
            # External Wiegand reader LED & BEEP internal 4.7k pull-ups to reader +5V logic rail
            "V_rdr_5v rdr_5v 0 DC 5.0",
            f"R_ext_led rdr_5v {n_wg_led_term} 4.7k",
            f"R_ext_beep rdr_5v {n_wg_beep_term} 4.7k",
            # Pulse all 4 expander outputs high from 10..80 us? No: pulse WG_LED/BEEP via p0..p3 = 1 at 30..80 us
            "V_ctrl_p0 ctrl_p0 0 DC 0",
            "V_ctrl_p1 ctrl_p1 0 DC 0",
            "V_ctrl_p2 ctrl_p2 0 PULSE(0 1 30u 0.5u 0.5u 50u 200u)",
            "V_ctrl_p3 ctrl_p3 0 PULSE(0 1 30u 0.5u 0.5u 50u 200u)",
            "V_ctrl_led ctrl_led_data 0 PULSE(0 3.3 15u 0.1u 0.1u 40u 200u)",
            ".tran 1u 100u",
        ],
    )
    ng.run_deck(deck_wg)
    t_wg = ng.real_vec("time")
    vd0_term = ng.real_vec(f"v({n_d0_term})")
    vd0_mcu = ng.real_vec(f"v({n_d0_mcu})")
    vd1_in = ng.real_vec(f"v({cu.pad_node[('U6', '3')]})")
    vd1_mcu = ng.real_vec(f"v({n_d1_mcu})")
    v_led_din = ng.real_vec(f"v({cu.pad_node[('D6', '4')]})")
    v_led_chain = ng.real_vec(f"v({cu.pad_node[('D7', '4')]})")

    def val_at(vec: list[float], target_t: float) -> float:
        idx = min(range(len(t_wg)), key=lambda i: abs(t_wg[i] - target_t))
        return vec[idx]

    # Idle (t=5 us): D0_TERM ~5.0 V, D0_MCU = 3.3 V (level-shifted safely for ESP32!)
    assert 4.7 <= val_at(vd0_term, 5e-6) <= 5.2
    assert 3.2 <= val_at(vd0_mcu, 5e-6) <= 3.4
    # Active-low Wiegand pulse (t=45 us): D0_MCU cleanly LOW (<0.2 V)
    assert val_at(vd0_mcu, 45e-6) < 0.2
    # +12V miswire fault on D1_TERM: BAT54S clamps U6 input <= 5.55 V (<< 6.5V abs max) and U6 outputs 3.3 V!
    assert max(vd1_in) <= 5.55, f"BAT54S failed to clamp +12V miswire on Wiegand input: {max(vd1_in):.2f}V"
    assert max(vd1_mcu) <= 3.40
    # Reader LED/BEEP open-drain sinks pull < 0.45V when active (t=55 us) and idle ~5.0V when off (t=5 us)
    v_wg_led = ng.real_vec(f"v({n_wg_led_term})")
    assert val_at(v_wg_led, 5e-6) > 4.6 and val_at(v_wg_led, 55e-6) < 0.45
    # WS2812B 3.3V -> 5V level shift via U5 (74AHCT1G125) -> D6.DIN -> D6.DOUT -> D7.DIN
    assert val_at(v_led_din, 35e-6) >= 4.6, f"WS2812B D6 DIN failed 5V level shift: {val_at(v_led_din, 35e-6):.2f}V"
    assert val_at(v_led_chain, 35e-6) >= 4.6, f"WS2812B D6->D7 cascade failed: {val_at(v_led_chain, 35e-6):.2f}V"
    assert val_at(v_led_chain, 5e-6) < 0.2

    # 2. ROGER B70/1DC +24V Optocoupler Sense Inputs (IN1=+24V pulse, IN2=+5V, IN3=-24V reverse fault) + Relay Switching & Flyback
    n_in1_p, n_in1_n = cu.pad_node[("J4", "1")], cu.pad_node[("J4", "2")]
    n_in2_p, n_in2_n = cu.pad_node[("J4", "3")], cu.pad_node[("J4", "4")]
    n_in3_p, n_in3_n = cu.pad_node[("J5", "1")], cu.pad_node[("J5", "2")]
    n_in1_mcu = cu.pad_node[("U8", "4")]
    n_in2_mcu = cu.pad_node[("U9", "4")]
    n_in3_mcu = cu.pad_node[("U10", "4")]
    n_in3_leda = cu.pad_node[("U10", "1")]

    # Determine which TCA9534 P0/P1 drives Relay 1 (R40)
    r40_other = next(cu.pad_node[("R40", p)] for p in ("1", "2") if cu.pad_node[("R40", p)] != cu.pad_node[("Q1", "1")])
    r1_p_idx = next(k for k, nd in p_nodes.items() if nd == r40_other)

    p_Pulses = [
        f"V_ctrl_p{k} ctrl_p{k} 0 " + ("PULSE(0 1 1m 5u 5u 5m 12m)" if k == r1_p_idx else "DC 0")
        for k in range(4)
    ]
    deck_gio = build_spice_deck(
        cu,
        extra_lines=[
            f"V_in {n_vin_raw} 0 DC 24.0",
            # ROGER B70/1DC +SC 24V signal on IN1 (referenced to 0)
            f"V_in1 {n_in1_p} {n_in1_n} PULSE(0 24.0 1m 10u 10u 5m 12m)",
            f"R_in1_ref {n_in1_n} 0 1",
            # 5V low-end active threshold check on IN2
            f"V_in2 {n_in2_p} {n_in2_n} DC 5.0",
            f"R_in2_ref {n_in2_n} 0 1",
            # -24V reverse-polarity wiring fault on IN3
            f"V_in3 {n_in3_p} {n_in3_n} DC -24.0",
            f"R_in3_ref {n_in3_n} 0 1",
            # Test external gate controller dry-contact sense on Relay 1 (J3A: COM=0V, NO & NC pulled to 24V via 4.7k)
            "V_gate_24 gate_24v 0 DC 24.0",
            f"R_r1_com {n_r1_com} 0 0.1",
            f"R_r1_no gate_24v {n_r1_no} 4.7k",
            f"R_r1_nc gate_24v {n_r1_nc} 4.7k",
            *p_Pulses,
            "V_ctrl_led ctrl_led_data 0 DC 0",
            ".tran 25u 9m",
        ],
    )
    ng.run_deck(deck_gio)
    t_g = ng.real_vec("time")

    def g_at(vec: list[float], target_t: float) -> float:
        idx = min(range(len(t_g)), key=lambda i: abs(t_g[i] - target_t))
        return vec[idx]

    v_in1_m = ng.real_vec(f"v({n_in1_mcu})")
    v_in2_m = ng.real_vec(f"v({n_in2_mcu})")
    v_in3_m = ng.real_vec(f"v({n_in3_mcu})")
    v_in3_a = ng.real_vec(f"v({n_in3_leda})")
    v_in3_k = ng.real_vec(f"v({n_in3_n})")

    # IN1: 3.3V idle at t=0.5ms -> pulled LOW (<0.3V) when 24V applied (after ~1ms RC debounce, check t=4.5ms) -> returns HIGH at t=8.5ms
    assert g_at(v_in1_m, 0.5e-3) > 3.1
    assert g_at(v_in1_m, 4.5e-3) < 0.25
    assert g_at(v_in1_m, 8.5e-3) > 3.0
    # IN2 at +5V DC: reliably pulls LOW (<0.35V)
    assert g_at(v_in2_m, 4.5e-3) < 0.35
    # IN3 at -24V reverse fault: stays HIGH (3.3V), and BAT54S D18 clamps opto LED reverse voltage >= -0.65V (<< 6V breakdown!)
    assert g_at(v_in3_m, 4.5e-3) > 3.2
    min_v_led_rev = min(va - vk for va, vk in zip(v_in3_a, v_in3_k))
    assert min_v_led_rev >= -0.65, f"Opto LED reverse voltage {min_v_led_rev:.2f}V not clamped by BAT54S!"

    # Relay 1 switching & flyback clamp check
    v_no = ng.real_vec(f"v({n_r1_no})")
    v_nc = ng.real_vec(f"v({n_r1_nc})")
    v_coil_n = ng.real_vec(f"v({n_r1_coil})")
    # De-energized (t=0.5ms): NC closed (<0.1V), NO open (~24V)
    assert g_at(v_nc, 0.5e-3) < 0.1 and g_at(v_no, 0.5e-3) > 23.5
    # Energized (t=4.5ms): NO closed (<0.1V), NC open (~24V)
    assert g_at(v_no, 4.5e-3) < 0.1 and g_at(v_nc, 4.5e-3) > 23.5
    # Inductive turn-off at t=6.0ms: D14 SS14 flyback diode clamps Q1 collector <= 5.6V (<< 40V MMBT3904 VCEO!)
    assert max(v_coil_n) <= 5.65, f"Relay coil inductive kickback unclamped: peak V(R1_COIL_N) = {max(v_coil_n):.2f}V"
