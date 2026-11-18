"""V1 main board (74.0 x 54.0 mm, 4 layers, 1.6 mm):
  Bottom edge (-y), WAGO 2086 SMD push-in terminals (3.5 mm pitch, side entry):
    - J1  (2086-1202, 2P): 1=VIN+ (9-32V), 2=GND
    - J2A (2086-1203, 3P): 1=+12V_RDR, 2=GND, 3=WG_D0
    - J2B (2086-1203, 3P): 1=WG_D1, 2=WG_LED, 3=WG_BEEP
  Top edge (+y), WAGO 2086 SMD push-in terminals (3.5 mm pitch, side entry):
    - J3A (2086-1203, 3P): 1=R1_COM, 2=R1_NO, 3=R1_NC
    - J3B (2086-1203, 3P): 1=R2_COM, 2=R2_NO, 3=R2_NC
    - J4  (2086-1204, 4P): 1=IN1+, 2=IN1-, 3=IN2+, 4=IN2-
    - J5  (2086-1204, 4P): 1=IN3+, 2=IN3-, 3=+12V_AUX, 4=GND
"""

from blocks import gate_io, mcu_xiao, power_24v, wiegand_io
from common import block, part, power, power_flag, src

WAGO_2P = "gateway_fp:TerminalBlock_WAGO_2086-1202_SMD"
WAGO_3P = "gateway_fp:TerminalBlock_WAGO_2086-1203_SMD"
WAGO_4P = "gateway_fp:TerminalBlock_WAGO_2086-1204_SMD"


def term2(value, ref, source):
    return part(
        "Connector",
        "Screw_Terminal_01x02",
        value,
        WAGO_2P,
        src(mpn="2086-1202/700-000/997-604", mfr="WAGO", hand=True, source=source),
        ref=ref,
    )


def term3(value, ref, source):
    return part(
        "Connector",
        "Screw_Terminal_01x03",
        value,
        WAGO_3P,
        src(mpn="2086-1203/700-000/997-605", mfr="WAGO", lcsc="C3309626", source=source),
        ref=ref,
    )


def term4(value, ref, source):
    return part(
        "Connector",
        "Screw_Terminal_01x04",
        value,
        WAGO_4P,
        src(mpn="2086-1204/700-000/997-605", mfr="WAGO", lcsc="C3309718", source=source),
        ref=ref,
    )


def build():
    gnd = power("GND")
    v3 = power("+3V3")
    power_flag(gnd)
    power_flag(v3)

    pwr = power_24v.build(gnd)
    v5, v12, vin_adc = pwr["v5"], pwr["v12"], pwr["vin_adc"]

    # Create nets bridged between wiegand_io / gate_io and mcu_xiao
    from skidl import Net

    wg_d0_mcu = Net("WG_D0_MCU")
    wg_d1_mcu = Net("WG_D1_MCU")

    # Build MCU first? Wait: mcu_xiao creates relay/led/beep/in nets, wiegand_io & gate_io consume them
    mcu = mcu_xiao.build(gnd, v3, v5, vin_adc, wg_d0_mcu, wg_d1_mcu)
    wg = wiegand_io.build(
        gnd, v3, v5, v12, mcu["wg_led_drv"], mcu["wg_beep_drv"], wg_d0_mcu, wg_d1_mcu
    )

    gio = gate_io.build(
        gnd,
        v3,
        v5,
        mcu["relay1_drv"],
        mcu["relay2_drv"],
        mcu["in1_mcu"],
        mcu["in2_mcu"],
        mcu["in3_mcu"],
    )

    block("terminals_bottom")
    j1 = term2("PWR", "J1", "1:VIN+, 2:GND")
    j1[1] += pwr["vin_raw"]
    j1[2] += gnd

    j2a = term3("WIEGAND_A", "J2A", "1:+12V, 2:GND, 3:D0")
    j2a[1] += wg["v12_rdr"]
    j2a[2] += gnd
    j2a[3] += wg["wg_d0_term"]

    j2b = term3("WIEGAND_B", "J2B", "1:D1, 2:LED, 3:BEEP")
    j2b[1] += wg["wg_d1_term"]
    j2b[2] += wg["wg_led_term"]
    j2b[3] += wg["wg_beep_term"]

    block("terminals_top")
    j3a = term3("RELAY_1", "J3A", "1:R1_COM, 2:R1_NO, 3:R1_NC")
    j3a[1] += gio["r1_com"]
    j3a[2] += gio["r1_no"]
    j3a[3] += gio["r1_nc"]

    j3b = term3("RELAY_2", "J3B", "1:R2_COM, 2:R2_NO, 3:R2_NC")
    j3b[1] += gio["r2_com"]
    j3b[2] += gio["r2_no"]
    j3b[3] += gio["r2_nc"]

    j4 = term4("SENSE_1_2", "J4", "1:IN1+, 2:IN1-, 3:IN2+, 4:IN2-")
    j4[1] += gio["in1_p"]
    j4[2] += gio["in1_n"]
    j4[3] += gio["in2_p"]
    j4[4] += gio["in2_n"]

    j5 = term4("SENSE_3_AUX", "J5", "1:IN3+, 2:IN3-, 3:+12V_AUX, 4:GND")
    j5[1] += gio["in3_p"]
    j5[2] += gio["in3_n"]
    j5[3] += wg["v12_rdr"]
    j5[4] += gnd


NET_CLASSES = {
    "SELV-MAIN": [
        "GND",
        "+3V3",
        "+5V",
        "+5V_XIAO",
        "+12V_RDR",
        "+12V_RDR_OUT",
        "VIN_ADC",
        "BTN_RESTART",
        "LED_DATA",
        "LED_BUF",
        "LED_DIN",
        "LED_CHAIN1",
        "I2C_SDA",
        "I2C_SCL",
        "EXP_INT",
        "EXP_P7",
        "WG_D0_TERM",
        "WG_D1_TERM",
        "WG_D0_IN",
        "WG_D1_IN",
        "WG_D0_MCU",
        "WG_D1_MCU",
        "WG_LED_DRV",
        "WG_BEEP_DRV",
        "WG_LED_TERM",
        "WG_BEEP_TERM",
        "WG_LED_COL",
        "WG_BEEP_COL",
        "WG_LED_BASE",
        "WG_BEEP_BASE",
        "RELAY1_DRV",
        "RELAY2_DRV",
        "R1_BASE",
        "R2_BASE",
        "R1_COIL_N",
        "R2_COIL_N",
        "R1_COM",
        "R1_NO",
        "R1_NC",
        "R2_COM",
        "R2_NO",
        "R2_NC",
        "IN1_MCU",
        "IN2_MCU",
        "IN3_MCU",
        "IN1_P",
        "IN1_N",
        "IN1_MID",
        "IN1_LED_A",
        "IN2_P",
        "IN2_N",
        "IN2_MID",
        "IN2_LED_A",
        "IN3_P",
        "IN3_N",
        "IN3_MID",
        "IN3_LED_A",
        "Net-*",
    ],
    "MAIN-Power": [
        "VIN_RAW",
        "VIN_FUSED",
        "VIN_PROT",
        "+5V",
        "+5V_XIAO",
        "+12V_RDR",
        "+12V_RDR_OUT",
        "5V_SW",
        "12V_SW",
        "R1_COM",
        "R1_NO",
        "R1_NC",
        "R2_COM",
        "R2_NO",
        "R2_NC",
    ],
}
