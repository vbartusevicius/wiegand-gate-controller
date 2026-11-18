# Ordering & Assembly Guide (`v1`)

All frozen manufacturing outputs live under `hardware/releases/v1/`.

## 1. PCB Fabrication & SMT Assembly (JLCPCB)

Upload from `hardware/releases/v1/main/`:

1. **Gerbers:** `main_gerbers.zip` (4-layer `1.6 mm` FR-4, `74.0 x 54.0 mm`).
2. **SMT Assembly BOM & CPL:** `main_bom_jlc.csv` and `main_cpl_jlc.csv`.
   - Every JLC-assembled part in `main_bom_jlc.csv` is verified against JLCPCB/EasyEDA pad geometry and pin names (`hardware/product/jlc_reference.json`).
   - All passives are `0805` or `1206` for easy rework.
   - WAGO 2086 SMD push-in terminals `J2A`–`J5` (`2086-1203` / `2086-1204`) are SMT-assembled by JLCPCB (`C3309626`, `C3309718`).

## 2. Hand-Fit & Off-Board Parts (`order_elsewhere.csv` / `assembly_parts.csv`)

Order separately and solder/assemble after PCB arrival:

| Qty | Part | MPN / Source | Notes |
| :---: | :--- | :--- | :--- |
| 1 | WAGO 2086 2-pole 3.5 mm SMD push-in terminal block | `2086-1202/700-000/997-604` (Digi-Key `2946-2086-1202/700-000/997-604CT-ND` / Mouser) | Hand-solder onto `J1` |
| 1 | Seeed Studio XIAO ESP32-C6 (Pre-Soldered) | `102010636` (Digi-Key `1597-102010636-ND` / Mouser / Seeed) | Plugs into `U3` sockets |
| 2 | Samtec 1x7 2.54 mm female header (`5.08 mm` tall) | `CES-107-02-G-S` (Mouser `200-CES10702GS` / Digi-Key) | Hand-solder onto `U3` |
| 1 | 2.4 GHz U.FL flexible PCB dipole antenna (`100 mm`) | Molex `1461530100` (LCSC `C152350` / Digi-Key `WM13992-ND`) | Connects to XIAO U.FL jack; sticks inside lid |
| 4 | M3 x 12 socket head screws + M3 hex nuts | DIN 912 / DIN 934 stainless | Secures lid to base corner ears |

## 3. 3D-Printed Enclosure (JLC3DP)

Upload `hardware/releases/v1/enclosure/print/enclosure_plate.stl` to **JLC3DP**:

- **Recommended material:** MJF `PA12` (Nylon, grey/black) or UV-stabilised `ASA`.
- **Dimensions:** `78.8 x 58.8 x 27.7 mm` main body (`94.8 mm` width across corner mounting ears).
- Individual STLs (`base_print.stl`, `lid_print.stl`) and STEPs (`base.step`, `lid.step`, `assembly.step`) are also included in `hardware/releases/v1/enclosure/`.

## 4. Initial Firmware Flash

Flash `firmware/build/release/usb-flash-firmware.bin` at offset `0x0` over USB-C before inserting the XIAO ESP32-C6 into the board (or via the `-X` USB-C service cutout):

```bash
python3 firmware/scripts/release_firmware.py
esptool.py --chip esp32c6 write_flash 0x0 firmware/build/release/usb-flash-firmware.bin
```

Subsequent updates can be uploaded directly through the Web UI **System -> Firmware Update (OTA)** tab using `firmware/build/release/firmware.bin`.
