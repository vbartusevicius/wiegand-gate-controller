"""Wiegand reader front-end: fused 12V reader power, 5V->3.3V Schmitt D0/D1, open-drain LED & BEEP."""

from common import block, part, src
from skidl import Net

R0805 = "Resistor_SMD:R_0805_2012Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
D_SMA = "Diode_SMD:D_SMA"
FUSE2920 = "Fuse:Fuse_2920_7451Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
BUF_FP = "gateway_fp:TI_SN74LVC2G17_SOT-23-6"


def res(value, source, ref):
    return part("Device", "R", value, R0805, src(source=source), ref=ref)


def cap(value, source, ref):
    return part("Device", "C", value, C0805, src(source=source), ref=ref)


def build(gnd, v3, v5, v12, wg_led_drv, wg_beep_drv, wg_d0_mcu, wg_d1_mcu):
    v12_rdr = Net("+12V_RDR_OUT")
    wg_d0_term = Net("WG_D0_TERM")
    wg_d1_term = Net("WG_D1_TERM")
    wg_d0_in = Net("WG_D0_IN")
    wg_d1_in = Net("WG_D1_IN")
    wg_led_term = Net("WG_LED_TERM")
    wg_beep_term = Net("WG_BEEP_TERM")
    wg_led_col = Net("WG_LED_COL")
    wg_beep_col = Net("WG_BEEP_COL")

    block("wiegand_pwr")
    f2 = part(
        "Device",
        "Polyfuse",
        "1.1A",
        FUSE2920,
        src(mpn="2920L110/60V", mfr="Littelfuse", lcsc="C49318488", source="Reader/Aux +12V 1.1A PTC"),
        ref="F2",
    )
    f2[1] += v12
    f2[2] += v12_rdr

    d8 = part(
        "Device",
        "D_Zener",
        "SMAJ15A",
        D_SMA,
        src(mpn="SMAJ15A", mfr="Littelfuse", lcsc="C148216", source="15V TVS clamp on +12V reader supply"),
        ref="D8",
    )
    d8["K"] += v12_rdr
    d8["A"] += gnd
    c8 = cap("100n 50V", "+12V_RDR_OUT HF decoupling", "C8")
    c8[1] += v12_rdr
    c8[2] += gnd

    block("wiegand_data")
    u6 = part(
        "gateway",
        "SN74LVC2G17",
        "SN74LVC2G17",
        BUF_FP,
        src(
            mpn="SN74LVC2G17DBVR(UMW)",
            mfr="UMW",
            lcsc="C7394037",
            source="Dual 5V-tolerant Schmitt buffer (D0/D1 -> 3.3V ESP32)",
        ),
        ref="U6",
    )
    u6["2"] += gnd
    u6["5"] += v3
    u6["1"] += wg_d0_in
    u6["6"] += wg_d0_mcu
    u6["3"] += wg_d1_in
    u6["4"] += wg_d1_mcu

    c30 = cap("100n 50V", "SN74LVC2G17 decoupling", "C30")
    c30[1] += v3
    c30[2] += gnd

    for idx, (term, buf_in, d_ref, r_pu_ref, r_ser_ref) in enumerate(
        (
            (wg_d0_term, wg_d0_in, "D10", "R30", "R31"),
            (wg_d1_term, wg_d1_in, "D11", "R32", "R33"),
        )
    ):
        r_pu = res("10k", f"Wiegand D{idx} 5V pull-up", r_pu_ref)
        r_pu[1] += v5
        r_pu[2] += term
        r_ser = res("330R", f"Wiegand D{idx} series protection", r_ser_ref)
        r_ser[1] += term
        r_ser[2] += buf_in
        d_clp = part(
            "Diode",
            "BAT54S",
            "BAT54S",
            SOT23,
            src(mpn="BAT54S,215", mfr="Nexperia", lcsc="C47546", source=f"Wiegand D{idx} clamp to GND/+5V"),
            ref=d_ref,
        )
        d_clp[1] += gnd
        d_clp[2] += v5
        d_clp[3] += buf_in

    block("wiegand_fb")
    for name, drv, col, term, q_ref, d_ref, r_b, r_pd, r_ser in (
        ("LED", wg_led_drv, wg_led_col, wg_led_term, "Q3", "D12", "R34", "R35", "R36"),
        ("BEEP", wg_beep_drv, wg_beep_col, wg_beep_term, "Q4", "D13", "R37", "R38", "R39"),
    ):
        base = Net(f"WG_{name}_BASE")
        rb = res("1k", f"Wiegand {name} NPN base resistor", r_b)
        rb[1] += drv
        rb[2] += base
        rpd = res("10k", f"Wiegand {name} boot pull-down", r_pd)
        rpd[1] += base
        rpd[2] += gnd
        q = part(
            "Transistor_BJT",
            "BC847",
            "MMBT3904",
            SOT23,
            src(mpn="MMBT3904(RANGE:100-300)", mfr="CJ", lcsc="C20526", source=f"Wiegand {name} open-drain"),
            ref=q_ref,
        )
        q["B"] += base
        q["E"] += gnd
        q["C"] += col
        rser = res("330R", f"Wiegand {name} series protection", r_ser)
        rser[1] += col
        rser[2] += term
        d_clp = part(
            "Diode",
            "BAT54S",
            "BAT54S",
            SOT23,
            src(mpn="BAT54S,215", mfr="Nexperia", lcsc="C47546", source=f"Wiegand {name} clamp"),
            ref=d_ref,
        )
        d_clp[1] += gnd
        d_clp[2] += v5
        d_clp[3] += col

    return {
        "v12_rdr": v12_rdr,
        "wg_d0_term": wg_d0_term,
        "wg_d1_term": wg_d1_term,
        "wg_d0_mcu": wg_d0_mcu,
        "wg_d1_mcu": wg_d1_mcu,
        "wg_led_term": wg_led_term,
        "wg_beep_term": wg_beep_term,
    }
