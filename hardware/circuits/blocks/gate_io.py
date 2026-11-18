"""2x Form-C relays (Omron G6S-2F DC5) + 3x EL357N opto-isolated universal 0-24V / dry-contact sense inputs."""

from builtins import NC

from common import block, part, src
from skidl import Net

R0805 = "Resistor_SMD:R_0805_2012Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
D_SMA = "Diode_SMD:D_SMA"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
RELAY_FP = "gateway_fp:Relay_DPDT_Omron_G6S-2F_2A"
OPTO_FP = "gateway_fp:Everlight_EL357N_SOP-4"


def res(value, source, ref):
    return part("Device", "R", value, R0805, src(source=source), ref=ref)


def cap(value, source, ref):
    return part("Device", "C", value, C0805, src(source=source), ref=ref)


def build(gnd, v3, v5, relay1_drv, relay2_drv, in1_mcu, in2_mcu, in3_mcu):
    out = {}

    block("relays")
    for idx, (drv, q_ref, d_ref, k_ref, rb_ref, rpd_ref) in enumerate(
        (
            (relay1_drv, "Q1", "D14", "K1", "R40", "R41"),
            (relay2_drv, "Q2", "D15", "K2", "R42", "R43"),
        ),
        start=1,
    ):
        base = Net(f"R{idx}_BASE")
        coil_n = Net(f"R{idx}_COIL_N")
        com = Net(f"R{idx}_COM")
        no = Net(f"R{idx}_NO")
        nc = Net(f"R{idx}_NC")
        out[f"r{idx}_com"] = com
        out[f"r{idx}_no"] = no
        out[f"r{idx}_nc"] = nc

        rb = res("470R", f"Relay {idx} base resistor", rb_ref)
        rb[1] += drv
        rb[2] += base
        rpd = res("10k", f"Relay {idx} boot pull-down", rpd_ref)
        rpd[1] += base
        rpd[2] += gnd

        q = part(
            "Transistor_BJT",
            "BC847",
            "MMBT3904",
            SOT23,
            src(mpn="MMBT3904(RANGE:100-300)", mfr="CJ", lcsc="C20526", source=f"Relay {idx} coil NPN"),
            ref=q_ref,
        )
        q["B"] += base
        q["E"] += gnd
        q["C"] += coil_n

        dfly = part(
            "Device",
            "D_Schottky",
            "SS14",
            D_SMA,
            src(mpn="SS14", mfr="MDD", lcsc="C2480", source=f"Relay {idx} flyback diode"),
            ref=d_ref,
        )
        dfly["A"] += coil_n
        dfly["K"] += v5

        k = part(
            "gateway",
            "G6S-2F",
            "G6S-2F DC5",
            RELAY_FP,
            src(mpn="G6S-2F DC5", mfr="Omron", lcsc="C16707", source=f"Relay {idx} Form-C (2A 30VDC)"),
            ref=k_ref,
        )
        k["1"] += v5
        k["12"] += coil_n
        # Parallel both DPDT poles for higher current margin & contact reliability
        k["3"] += nc
        k["10"] += nc
        k["4"] += com
        k["9"] += com
        k["5"] += no
        k["8"] += no

    block("opto_inputs")
    for idx, (mcu_net, u_ref, d_ref, r1_ref, r2_ref, rpu_ref, c_ref) in enumerate(
        (
            (in1_mcu, "U8", "D16", "R44", "R45", "R46", "C31"),
            (in2_mcu, "U9", "D17", "R47", "R48", "R49", "C32"),
            (in3_mcu, "U10", "D18", "R50", "R51", "R52", "C33"),
        ),
        start=1,
    ):
        in_p = Net(f"IN{idx}_P")
        in_n = Net(f"IN{idx}_N")
        mid = Net(f"IN{idx}_MID")
        led_a = Net(f"IN{idx}_LED_A")
        out[f"in{idx}_p"] = in_p
        out[f"in{idx}_n"] = in_n

        # Two 2k2 0805 resistors in series = 4.4k: safe up to 30V (<=60 mW per resistor) and reliable down to 5V
        ra = res("2k2", f"IN{idx} opto current limiter A", r1_ref)
        ra[1] += in_p
        ra[2] += mid
        rb = res("2k2", f"IN{idx} opto current limiter B", r2_ref)
        rb[1] += mid
        rb[2] += led_a

        d_rev = part(
            "Diode",
            "BAT54S",
            "BAT54S",
            SOT23,
            src(mpn="BAT54S,215", mfr="Nexperia", lcsc="C47546", source=f"IN{idx} opto reverse clamp"),
            ref=d_ref,
        )
        d_rev[1] += in_n
        d_rev[2] += NC
        d_rev[3] += led_a

        opto = part(
            "gateway",
            "EL357",
            "EL357N",
            OPTO_FP,
            src(mpn="EL357N(C)(TA)-G", mfr="Everlight", lcsc="C42379244", source=f"IN{idx} 3.75kV optocoupler"),
            ref=u_ref,
        )
        opto["1"] += led_a
        opto["2"] += in_n
        opto["3"] += gnd
        opto["4"] += mcu_net

        rpu = res("10k", f"IN{idx} collector pull-up to +3V3", rpu_ref)
        rpu[1] += v3
        rpu[2] += mcu_net
        cf = cap("100n 50V", f"IN{idx} debounce filter", c_ref)
        cf[1] += mcu_net
        cf[2] += gnd

    return out
