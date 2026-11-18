"""Shared helpers for SKiDL circuit sources (0805+ passives, verified JLCPCB/LCSC parts)."""

from pathlib import Path

from product_spec import spec_path
from skidl import KICAD9 as KICAD
from skidl import Net, Part

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = spec_path()
PROJECT_LIB = Path(__file__).resolve().parent / "lib" / "gateway.kicad_sym"

PLACE_BLOCK = "misc"


def block(name):
    """Set the functional block recorded on subsequently created parts."""
    global PLACE_BLOCK
    PLACE_BLOCK = name


PASSIVES = {
    ("R", "120R", "0805"): ("C17437", "UNI-ROYAL", "0805W8F1200T5E"),
    ("R", "330R", "0805"): ("C17630", "UNI-ROYAL", "0805W8F3300T5E"),
    ("R", "390R", "0805"): ("C17655", "UNI-ROYAL", "0805W8F3900T5E"),
    ("R", "470R", "0805"): ("C17710", "UNI-ROYAL", "0805W8F4700T5E"),
    ("R", "1k", "0805"): ("C17513", "UNI-ROYAL", "0805W8F1001T5E"),
    ("R", "2k2", "0805"): ("C17520", "UNI-ROYAL", "0805W8F2201T5E"),
    ("R", "4k7", "0805"): ("C17673", "UNI-ROYAL", "0805W8F4701T5E"),
    ("R", "6k49", "0805"): ("C17769", "UNI-ROYAL", "0805W8F6491T5E"),
    ("R", "10k", "0805"): ("C17414", "UNI-ROYAL", "0805W8F1002T5E"),
    ("R", "10k2", "0805"): ("C17402", "UNI-ROYAL", "0805W8F1022T5E"),
    ("R", "53k6", "0805"): ("C21398", "UNI-ROYAL", "0805W8F5362T5E"),
    ("R", "82k5", "0805"): ("C276314", "YAGEO", "RC0805FR-0782K5L"),
    ("R", "100k", "0805"): ("C149504", "UNI-ROYAL", "0805W8F1003T5E"),
    ("R", "130k", "0805"): ("C17450", "UNI-ROYAL", "0805W8F1303T5E"),
    ("R", "140k", "0805"): ("C17460", "UNI-ROYAL", "0805W8F1403T5E"),
    ("R", "511k", "0805"): ("C17735", "UNI-ROYAL", "0805W8F5113T5E"),
    ("C", "68p C0G 50V", "0805"): ("C107120", "YAGEO", "CC0805JRNPO9BN680"),
    ("C", "18n 50V", "0805"): ("C520032", "YAGEO", "CC0805JRX7R9BB183"),
    ("C", "33n 50V", "0805"): ("C107150", "YAGEO", "CC0805KRX7R9BB333"),
    ("C", "100n 50V", "0805"): ("C49678", "YAGEO", "CC0805KRX7R9BB104"),
    ("C", "100n 100V", "0805"): ("C106243", "YAGEO", "CC0805KKX7R0BB104"),
    ("C", "1u 50V", "0805"): ("C28323", "Samsung", "CL21B105KBFNNNE"),
    ("C", "2u2 100V", "1206"): ("C170101", "Samsung", "CL31B225KCHSNNE"),
    ("C", "10u 10V", "0805"): ("C17024", "Samsung", "CL21A106KPFNNNE"),
    ("C", "22u 25V", "1206"): ("C12891", "Samsung", "CL31A226KAHNNNE"),
    ("C", "47u 10V", "1206"): ("C96123", "Samsung", "CL31A476MPHNNNE"),
}


def passive_source(symbol, value, footprint):
    package = footprint.split(":")[1].split("_")[1]
    key = (symbol, value.split(" 1%")[0], package)
    if key not in PASSIVES:
        raise KeyError(f"no verified LCSC part for {key}; add it to PASSIVES")
    lcsc, mfr, mpn = PASSIVES[key]
    return {"Manufacturer": mfr, "Manufacturer_Part_Number": mpn, "LCSC": lcsc}


def part(lib, symbol, value="", footprint="", fields=None, ref=None):
    """Instantiate a stock or project-library part with sourcing fields."""
    lib_ref = str(PROJECT_LIB) if lib == "gateway" else lib
    p = Part(lib_ref, symbol, tool=KICAD, tag=PLACE_BLOCK, **({"ref": ref} if ref else {}))
    if value:
        p.value = value
    if footprint:
        p.footprint = footprint
    p.fields["Place"] = PLACE_BLOCK
    p.fields["Assembly"] = "jlc"
    for key, val in (fields or {}).items():
        p.fields[key] = val
    if lib == "Device" and symbol in ("R", "C"):
        for key, val in passive_source(symbol, value, footprint).items():
            p.fields[key] = val
    return p


def src(mpn="", mfr="", lcsc="", source="", hand=False, footprint_ref="", board_only=False, stock_optional=False):
    fields = {
        "Manufacturer": mfr,
        "Manufacturer_Part_Number": mpn,
        "LCSC": lcsc,
        "Source": source,
        "Footprint_Reference": footprint_ref,
    }
    if board_only:
        fields["Assembly"] = "none"
    if hand:
        fields["Assembly"] = "hand"
    if stock_optional:
        fields["Stock_Optional"] = "yes"
    return fields


def power(name):
    net = Net(name)
    sym = Part("power", name, tool=KICAD, tag="power")
    sym.footprint = ""
    sym["1"] += net
    return net


def power_flag(net):
    flag = Part("power", "PWR_FLAG", tool=KICAD, tag="power")
    flag.footprint = ""
    flag["1"] += net
