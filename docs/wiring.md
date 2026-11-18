# Wiring & ROGER BH30/610/HS (`B70/1DC`) Guide

> **Safety notice:** Disconnect mains power from the gate controller before wiring. All gateway terminals (`J1`–`J5`) are SELV/low-voltage (<= 32 V DC); never connect AC mains to any terminal on the gateway.

## Board Terminal Pinout (`v1`)

All field terminals are **WAGO 2086** 3.5 mm pitch SMD push-in CAGE CLAMP connectors (`0.14–1.5 mm²`, solid or ferruled wire; press the push-button on the front entry face to release).

### Bottom Edge (`-Y`)

| Box Label | Terminal | Pin | PCB Label | Function |
| :--- | :--- | :--- | :--- | :--- |
| `PWR` | `J1` (2P) | 1 | `VIN+` (`V+`) | 9–32 V DC supply input (1.1 A PTC fused + reverse-polarity protected) |
| `PWR` | `J1` (2P) | 2 | `GND` | Supply ground |
| `WIEGAND` | `J2A` (3P) | 1 | `12V` | +12 V DC reader supply (1.1 A PTC fused, TVS clamped) |
| `WIEGAND` | `J2A` (3P) | 2 | `GND` | Reader ground |
| `WIEGAND` | `J2A` (3P) | 3 | `D0` | Wiegand Data 0 (5 V pull-up, Schmitt buffered) |
| `WIEGAND` | `J2B` (3P) | 1 | `D1` | Wiegand Data 1 (5 V pull-up, Schmitt buffered) |
| `WIEGAND` | `J2B` (3P) | 2 | `LED` | Reader LED control (open-drain to GND, active-low default) |
| `WIEGAND` | `J2B` (3P) | 3 | `BEEP` | Reader Buzzer control (open-drain to GND, active-low default) |

### Top Edge (`+Y`)

| Box Label | Terminal | Pin | PCB Label | Function |
| :--- | :--- | :--- | :--- | :--- |
| `RELAY 1` | `J3A` (3P) | 1 | `R1C` (`COM`) | Relay 1 Common (potential-free dry contact, 2 A / 30 V DC max) |
| `RELAY 1` | `J3A` (3P) | 2 | `R1O` (`NO`) | Relay 1 Normally Open (`R1_NO`) |
| `RELAY 1` | `J3A` (3P) | 3 | `R1X` (`NC`) | Relay 1 Normally Closed (`R1_NC`) |
| `RELAY 2` | `J3B` (3P) | 1 | `R2C` (`COM`) | Relay 2 Common (potential-free dry contact, 2 A / 30 V DC max) |
| `RELAY 2` | `J3B` (3P) | 2 | `R2O` (`NO`) | Relay 2 Normally Open (`R2_NO`) |
| `RELAY 2` | `J3B` (3P) | 3 | `R2X` (`NC`) | Relay 2 Normally Closed (`R2_NC`) |
| `SENSORS` | `J4` (4P) | 1 | `IN1+` | Opto Input 1 anode (`+`, 5–24 V DC active or via `+12` pull-up) |
| `SENSORS` | `J4` (4P) | 2 | `IN1-` | Opto Input 1 cathode (`-`) |
| `SENSORS` | `J4` (4P) | 3 | `IN2+` | Opto Input 2 anode (`+`) |
| `SENSORS` | `J4` (4P) | 4 | `IN2-` | Opto Input 2 cathode (`-`) |
| `EXIT / 12V` | `J5` (4P) | 1 | `IN3+` | Opto Input 3 anode (`+`, default REX / exit / pedestrian input) |
| `EXIT / 12V` | `J5` (4P) | 2 | `IN3-` | Opto Input 3 cathode (`-`) |
| `EXIT / 12V` | `J5` (4P) | 3 | `+12` (`+12V`) | +12 V DC auxiliary wetting supply (shared with fused `+12V_RDR_OUT`) |
| `EXIT / 12V` | `J5` (4P) | 4 | `GND` | Auxiliary ground |

## ROGER BH30/610/HS (`B70/1DC`) Wiring

### Recommended Mode: `gate_dual` + `roger_b70`

| Gateway Terminal | ROGER `B70/1DC` Terminal | Notes |
| :--- | :--- | :--- |
| `J1.1 (VIN+)` | `27 (+24V)` | 24 V DC accessory output (F2 2 A protected) |
| `J1.2 (GND)` | `28 (COM)` | Accessory ground |
| `J3A.1 (R1C)` | `21 (COM)` | Common reference for control inputs |
| `J3A.2 (R1O)` | `23 (AP)` | Open command (or `25 (PP)` in `gate_pulse` mode) |
| `J3B.1 (R2C)` | `21 (COM)` | Bridge from `J3A.1` (`21 COM`) |
| `J3B.2 (R2O)` | `24 (CH)` | Close command (or `26 (PED)` in `gate_pulse` mode) |
| `J4.1 (IN1+)` | `8 (+SC)` | 24 V gate indicator: 0 V = closed, blinking = moving, 24 V = open |
| `J4.2 (IN1-)` | `9 (COM)` | `+SC` return |
| `J4.3 (IN2+)` | `J5.3 (+12)` | Wetting voltage for optional `COR` dry contact |
| `J4.4 (IN2-)` | `6 (COR)` | Optional Management System confirm; bridge `7 (COR)` -> `J5.4 (GND)` |

- **B70/1DC parameters:** Ensure standby/low-power mode does not turn off `+SC`, and `+SC` is configured as Gate Open Indicator rather than photocell test. To use `COR` on `IN2`, set `B70/1DC` `par. 20 != 00`.

## Dry-Contact Switches (Reed, Dual Limits, REX Button)

Because `IN1`–`IN3` are isolated `EL357N` optocoupler inputs (`4.4 kΩ` series resistance), dry contacts simply switch `+12V` from `J5.3 (+12)` into `INx+` with `INx-` tied to `J5.4 (GND)` (or switch the ground side with `INx+` tied to `+12` and `INx-` switched to `GND`):

- **Single reed (`single_reed`)**: `J5.3 (+12)` -> reed switch -> `J4.1 (IN1+)`, and `J4.2 (IN1-)` -> `J5.4 (GND)`.
- **Dual limit switches (`dual_limit`)**: Closed limit on `IN1`, Open limit on `IN2`, wired the same way.
- **REX / Exit / Pedestrian button (`IN3`)**: `J5.3 (+12)` -> N.O. pushbutton -> `J5.1 (IN3+)`, and `J5.2 (IN3-)` -> `J5.4 (GND)`.

## XIAO ESP32-C6 & Antenna Setup

- Plug the **Molex 1461530100** U.FL dipole antenna onto the XIAO ESP32-C6 U.FL connector and adhere it inside the enclosure lid (away from the `24 V` power inductors `L1`/`L2`). Firmware drives `GPIO3 = LOW`, `GPIO14 = HIGH` to select the external U.FL antenna.
- **USB-C flashing (`-X` wall cutout):** `D5` blocks USB-C 5 V from back-feeding the 5 V rail, so USB-C flashing is safe while disconnected or powered. Avoid plugging USB-C into an ungrounded laptop while the gate controller is live if earth-loop currents are possible.
- **Restart / Recovery button (`SW1`):**
  - Short tap: Restart ESP32-C6
  - Hold 5 s: Launch Wi-Fi AP setup portal (`Wiegand-Gate-Controller-XXXX`)
  - Hold 10 s: Factory reset stored config & users
