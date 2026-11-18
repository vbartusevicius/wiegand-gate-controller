"""MCU, I2C expander, Restart button, and 2x RGB WS2812B LEDs block."""

from builtins import NC

from common import block, part, power_flag, src
from skidl import Net

R0805 = "Resistor_SMD:R_0805_2012Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
D_SMA = "Diode_SMD:D_SMA"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
XIAO_FP = "gateway_fp:XIAO_ESP32C6_Header"
SW_B3U = "Button_Switch_SMD:SW_SPST_B3U-1000P"
TCA_FP = "gateway_fp:TI_TCA9534DWR_SOIC-16"
LED_FP = "gateway_fp:LED_WS2812B-MINI-V3J"

MCU_PINS = {
    "vin_adc": {"pin": "D0/GPIO0", "net": "VIN_ADC", "note": "ADC1_CH0 supply monitor (11:1)"},
    "btn_restart": {"pin": "D1/GPIO1", "net": "BTN_RESTART", "note": "Restart / AP setup / Factory reset button"},
    "wg_d0": {"pin": "D2/GPIO2", "net": "WG_D0_MCU", "note": "Wiegand D0 Schmitt-buffered ISR input"},
    "led_data": {"pin": "D3/GPIO21", "net": "LED_DATA", "note": "2x WS2812B-MINI-V3J RGB LEDs via 5V buffer"},
    "i2c_sda": {"pin": "D4/GPIO22", "net": "I2C_SDA", "note": "PCA9534/TCA9534 I2C SDA"},
    "i2c_scl": {"pin": "D5/GPIO23", "net": "I2C_SCL", "note": "PCA9534/TCA9534 I2C SCL"},
    "wg_d1": {"pin": "D9/GPIO20", "net": "WG_D1_MCU", "note": "Wiegand D1 Schmitt-buffered ISR input"},
    "exp_int": {"pin": "D10/GPIO18", "net": "EXP_INT", "note": "TCA9534 /INT active LOW"},
}


def res(value, source, ref):
    return part("Device", "R", value, R0805, src(source=source), ref=ref)


def cap(value, source, ref):
    return part("Device", "C", value, C0805, src(source=source), ref=ref)


def build(gnd, v3, v5, vin_adc, wg_d0_mcu, wg_d1_mcu):
    v5_xiao = Net("+5V_XIAO")
    btn_restart = Net("BTN_RESTART")
    led_data = Net("LED_DATA")
    led_buf = Net("LED_BUF")
    led_chain = Net("LED_CHAIN1")
    sda = Net("I2C_SDA")
    scl = Net("I2C_SCL")
    exp_int = Net("EXP_INT")

    relay1_drv = Net("RELAY1_DRV")
    relay2_drv = Net("RELAY2_DRV")
    wg_led_drv = Net("WG_LED_DRV")
    wg_beep_drv = Net("WG_BEEP_DRV")
    in1_mcu = Net("IN1_MCU")
    in2_mcu = Net("IN2_MCU")
    in3_mcu = Net("IN3_MCU")
    exp_p7 = Net("EXP_P7")

    block("mcu_power")
    d5 = part(
        "Device",
        "D_Schottky",
        "SS14",
        D_SMA,
        src(mpn="SS14", mfr="MDD", lcsc="C2480", source="Blocks USB-C back-feed into +5V"),
        ref="D5",
    )
    d5["A"] += v5
    d5["K"] += v5_xiao
    power_flag(v5_xiao)
    c4 = cap("10u 10V", "XIAO 5V decoupling", "C4")
    c4[1] += v5_xiao
    c4[2] += gnd
    c3 = cap("10u 10V", "XIAO 3V3 decoupling", "C3")
    c3[1] += v3
    c3[2] += gnd

    block("mcu")
    u3 = part(
        "gateway",
        "XIAO_ESP32C6",
        "XIAO ESP32C6",
        XIAO_FP,
        src(mpn="102010636", mfr="Seeed Studio", hand=True, source="XIAO ESP32-C6 on 2x 1x7 sockets"),
        ref="U3",
    )
    for pin, net in (
        ("1", vin_adc),
        ("2", btn_restart),
        ("3", wg_d0_mcu),
        ("4", led_data),
        ("5", sda),
        ("6", scl),
        ("7", NC),
        ("8", NC),
        ("9", NC),
        ("10", wg_d1_mcu),
        ("11", exp_int),
        ("12", v3),
        ("13", gnd),
        ("14", v5_xiao),
    ):
        u3[pin] += net

    # Restart / AP Setup / Factory Reset button
    r_btn = res("10k", "SW1 pull-up to +3V3", "R3")
    r_btn[1] += v3
    r_btn[2] += btn_restart
    c_btn = cap("100n 50V", "SW1 debounce filter", "C5")
    c_btn[1] += btn_restart
    c_btn[2] += gnd
    sw1 = part(
        "Switch",
        "SW_Push",
        "RESTART",
        SW_B3U,
        src(mpn="B3U-1000P", mfr="Omron", lcsc="C231329", source="Tap=Restart, 5s=AP setup, 10s=Reset"),
        ref="SW1",
    )
    sw1[1] += btn_restart
    sw1[2] += gnd

    # I2C pull-ups + EXP_INT pull-up
    r5 = res("2k2", "I2C SDA pull-up", "R5")
    r5[1] += v3
    r5[2] += sda
    r6 = res("2k2", "I2C SCL pull-up", "R6")
    r6[1] += v3
    r6[2] += scl
    r7 = res("10k", "TCA9534 /INT pull-up", "R7")
    r7[1] += v3
    r7[2] += exp_int

    # TCA9534DWR I2C I/O Expander @ 0x20 (A0=A1=A2=GND)
    block("expander")
    u4 = part(
        "gateway",
        "TCA9534",
        "TCA9534DWR",
        TCA_FP,
        src(mpn="TCA9534DWR", mfr="TI", lcsc="C2870609", source="8-bit I2C I/O expander @ 0x20"),
        ref="U4",
    )
    u4["1"] += gnd
    u4["2"] += gnd
    u4["3"] += gnd
    u4["4"] += relay1_drv
    u4["5"] += relay2_drv
    u4["6"] += wg_led_drv
    u4["7"] += wg_beep_drv
    u4["8"] += gnd
    u4["9"] += in1_mcu
    u4["10"] += in2_mcu
    u4["11"] += in3_mcu
    u4["12"] += exp_p7
    u4["13"] += exp_int
    u4["14"] += scl
    u4["15"] += sda
    u4["16"] += v3

    c6 = cap("100n 50V", "TCA9534 decoupling", "C6")
    c6[1] += v3
    c6[2] += gnd
    r_p7 = res("10k", "Spare P7 pull-down", "R4")
    r_p7[1] += exp_p7
    r_p7[2] += gnd

    # 2x RGB Status LEDs (WS2812B-MINI-V3J) via 5V level buffer SN74AHCT1G125
    block("rgb_leds")
    u5 = part(
        "74xGxx",
        "74AHCT1G125",
        "74AHCT1G125",
        SOT23_5,
        src(mpn="SN74AHCT1G125DBVR", mfr="TI", lcsc="C7484", source="3.3V->5V RGB LED buffer"),
        ref="U5",
    )
    u5[1] += gnd
    u5[2] += led_data
    u5[3] += gnd
    u5[4] += led_buf
    u5[5] += v5
    c_u5 = cap("100n 50V", "74AHCT1G125 decoupling", "C9")
    c_u5[1] += v5
    c_u5[2] += gnd
    r_led = res("330R", "WS2812B DIN series resistor", "R16")
    r_led[1] += led_buf
    r_led[2] += (led_din := Net("LED_DIN"))

    d6 = part(
        "gateway",
        "WS2812B-MINI-V3J",
        "WS2812B-MINI-V3J",
        LED_FP,
        src(mpn="WS2812B-MINI-V3J", mfr="Worldsemi", lcsc="C22371519", source="LED 0: Net/Auth RGB"),
        ref="D6",
    )
    d6["DIN"] += led_din
    d6["VDD"] += v5
    d6["GND"] += gnd
    d6["DOUT"] += led_chain
    c_d6 = cap("100n 50V", "LED 0 decoupling", "C19")
    c_d6[1] += v5
    c_d6[2] += gnd

    d7 = part(
        "gateway",
        "WS2812B-MINI-V3J",
        "WS2812B-MINI-V3J",
        LED_FP,
        src(mpn="WS2812B-MINI-V3J", mfr="Worldsemi", lcsc="C22371519", source="LED 1: Gate/Door RGB"),
        ref="D7",
    )
    d7["DIN"] += led_chain
    d7["VDD"] += v5
    d7["GND"] += gnd
    d7["DOUT"] += NC
    c_d7 = cap("100n 50V", "LED 1 decoupling", "C29")
    c_d7[1] += v5
    c_d7[2] += gnd

    return {
        "relay1_drv": relay1_drv,
        "relay2_drv": relay2_drv,
        "wg_led_drv": wg_led_drv,
        "wg_beep_drv": wg_beep_drv,
        "in1_mcu": in1_mcu,
        "in2_mcu": in2_mcu,
        "in3_mcu": in3_mcu,
    }
