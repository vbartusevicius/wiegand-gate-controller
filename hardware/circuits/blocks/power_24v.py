"""9-32 V DC input protection, VIN_ADC monitor, and dual TPS54360 bucks (+5V logic, +12V_RDR reader/aux)."""

from common import block, part, power_flag, src
from skidl import Net

R0805 = "Resistor_SMD:R_0805_2012Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
D_SMA = "Diode_SMD:D_SMA"
FUSE2920 = "Fuse:Fuse_2920_7451Metric"
POWERPAD8 = "Package_SO:TI_SO-PowerPAD-8_ThermalVias"
L_SWPA6045 = "Inductor_SMD:L_Sunlord_SWPA6045S"

RAILS = {
    5.0: {
        "l": ("8.2uH", "ANR6045T8R2M", "C7427168", "APV", "Isat 3.96 A, Irms 2.64 A"),
        "cout": "47u 10V",
        "c5": ("33n 50V", "f_z = 90 Hz"),
        "fb": ("53k6", "10k2"),
    },
    12.0: {
        "l": ("22uH", "SRN6045TA-220M", "C2044314", "Bourns", "Isat 3.3 A, Irms 2.3 A"),
        "cout": "22u 25V",
        "c5": ("18n 50V", "f_z = 165 Hz"),
        "fb": ("140k", "10k"),
    },
}


def res(value, source, ref):
    return part("Device", "R", value, R0805, src(source=source), ref=ref)


def cap(value, source, ref, footprint=C0805):
    return part("Device", "C", value, footprint, src(source=source), ref=ref)


def tps54360(name, vin, vout, gnd, u, l_ref, d_ref, c_refs, r_refs, volts):
    block(f"buck_{name}")
    cfg = RAILS[volts]
    tag = name.upper()
    sw, bst, en, fb, rt, comp, cc = (
        Net(f"{tag}_{n}") for n in ("SW", "BST", "EN", "FB", "RT", "COMP", "CC")
    )
    ic = part(
        "Regulator_Switching",
        "TPS54360DDA",
        "TPS54360DDAR",
        POWERPAD8,
        src(
            mpn="TPS54360DDAR",
            mfr="Texas Instruments",
            lcsc="C44377",
            source=f"TPS54360 4.5-60 V input, 3.5 A buck ({name} {volts:g} V)",
        ),
        ref=u,
    )
    for pin, net in (
        ("1", bst),
        ("2", vin),
        ("3", en),
        ("4", rt),
        ("5", fb),
        ("6", comp),
        ("7", gnd),
        ("8", sw),
        ("9", gnd),
    ):
        ic[pin] += net
    l_val, l_mpn, l_lcsc, l_mfr, l_note = cfg["l"]
    ind = part(
        "Device",
        "L",
        l_val,
        L_SWPA6045,
        src(mpn=l_mpn, mfr=l_mfr, lcsc=l_lcsc, source=f"{l_val} power inductor ({l_note})"),
        ref=l_ref,
    )
    ind[1] += sw
    ind[2] += vout
    diode = part(
        "Device",
        "D_Schottky",
        "B360A",
        D_SMA,
        src(mpn="B360A-13-F", mfr="Diodes Inc", lcsc="C94193", source="60 V 3 A catch diode"),
        ref=d_ref,
    )
    diode["K"] += sw
    diode["A"] += gnd

    c5_val, c5_note = cfg["c5"]
    caps = (
        ("2u2 100V", vin, gnd, "TPS54360 VIN cap 1", C1206),
        ("2u2 100V", vin, gnd, "TPS54360 VIN cap 2", C1206),
        ("100n 100V", vin, gnd, "TPS54360 VIN HF decoupling", C0805),
        ("100n 50V", bst, sw, "TPS54360 BST bootstrap cap", C0805),
        (cfg["cout"], vout, gnd, "TPS54360 VOUT cap 1", C1206),
        (cfg["cout"], vout, gnd, "TPS54360 VOUT cap 2", C1206),
        ("100n 50V", vout, gnd, "TPS54360 VOUT HF decoupling", C0805),
        (c5_val, cc, gnd, f"TPS54360 C5 ({c5_note})", C0805),
        ("68p C0G 50V", comp, gnd, "TPS54360 C8 pole cap", C0805),
    )
    for ref, (val, a, b, source_txt, fp) in zip(c_refs, caps):
        c = cap(val, f"{source_txt} [{name}]", ref, fp)
        c[1] += a
        c[2] += b

    fb_top, fb_bot = cfg["fb"]
    ress = (
        ("511k", vin, en, "TPS54360 UVLO top (8.0 V start)"),
        ("82k5", en, gnd, "TPS54360 UVLO bottom"),
        (fb_top, vout, fb, f"TPS54360 FB top ({volts:g} V)"),
        (fb_bot, fb, gnd, "TPS54360 FB bottom"),
        ("130k", rt, gnd, "TPS54360 RT (743 kHz)"),
        ("53k6", comp, cc, "TPS54360 R4 compensation"),
    )
    for ref, (val, a, b, source_txt) in zip(r_refs, ress):
        r = res(val, f"{source_txt} [{name}]", ref)
        r[1] += a
        r[2] += b


def build(gnd):
    vin_raw = Net("VIN_RAW")
    vin_fused = Net("VIN_FUSED")
    vin_prot = Net("VIN_PROT")
    vin_adc = Net("VIN_ADC")
    v5 = Net("+5V")
    v12 = Net("+12V_RDR")
    for n in (vin_raw, vin_fused, vin_prot, v5, v12):
        power_flag(n)

    block("power_in")
    f1 = part(
        "Device",
        "Polyfuse",
        "1.1A",
        FUSE2920,
        src(mpn="2920L110/60V", mfr="Littelfuse", lcsc="C49318488", source="1.1 A / 60 V input PTC"),
        ref="F1",
    )
    f1[1] += vin_raw
    f1[2] += vin_fused

    d_rev = part(
        "Device",
        "D_Schottky",
        "SS36",
        D_SMA,
        src(mpn="SS36", mfr="MDD", lcsc="C16015", source="60 V 3 A reverse-polarity Schottky"),
        ref="D2",
    )
    d_rev["A"] += vin_fused
    d_rev["K"] += vin_prot

    d_tvs = part(
        "Device",
        "D_Zener",
        "SMAJ36A",
        D_SMA,
        src(mpn="SMAJ36A", mfr="MDD", lcsc="C113967", source="36 V TVS surge clamp (58.1 V max)"),
        ref="D1",
    )
    d_tvs["K"] += vin_prot
    d_tvs["A"] += gnd

    c1 = cap("2u2 100V", "Input 100 V reservoir cap", "C1", C1206)
    c1[1] += vin_prot
    c1[2] += gnd

    block("vin_sense")
    r1 = res("100k", "VIN_PROT 11:1 divider top", "R1")
    r1[1] += vin_prot
    r1[2] += vin_adc
    r2 = res("10k", "VIN_PROT 11:1 divider bottom", "R2")
    r2[1] += vin_adc
    r2[2] += gnd
    c2 = cap("100n 50V", "VIN_ADC anti-aliasing filter", "C2")
    c2[1] += vin_adc
    c2[2] += gnd

    tps54360(
        "5v",
        vin_prot,
        v5,
        gnd,
        "U1",
        "L1",
        "D3",
        ("C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C18"),
        ("R10", "R11", "R12", "R13", "R14", "R15"),
        5.0,
    )
    tps54360(
        "12v",
        vin_prot,
        v12,
        gnd,
        "U2",
        "L2",
        "D9",
        ("C20", "C21", "C22", "C23", "C24", "C25", "C26", "C27", "C28"),
        ("R20", "R21", "R22", "R23", "R24", "R25"),
        12.0,
    )

    return {"vin_raw": vin_raw, "vin_prot": vin_prot, "vin_adc": vin_adc, "v5": v5, "v12": v12}
