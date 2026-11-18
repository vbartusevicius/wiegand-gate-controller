# Agent instructions: Wiegand Gateway

ESP32 access-control gateway for doors and entry gates (primary target: **ROGER BH30/610/HS** with **B70/1DC** controller; reference feature set: **ZKAccess C3-100**, simplified and modernised): C++17 firmware (ESP-IDF via PlatformIO), embedded Web UI, Home Assistant MQTT auto-discovery, OTA updates, SKiDL/KiCad 10 PCBs routed with `fastroute`, and CadQuery enclosures ready for **JLCPCB** and **JLC3DP**.

Nothing has run on physical hardware yet unless explicitly noted. Never claim bench, electrical, RF, EMC or gate-integration validation from host, container or DRC results; state exactly what was verified.

---

## Repository map

- `firmware/`: ESP32 C++17 firmware (PlatformIO / ESP-IDF), embedded gzip Web UI (`firmware/data/`), native Unity tests (`firmware/test/`), and mock Web UI server (`firmware/scripts/`).
- `hardware/`: SKiDL circuit generators (`hardware/circuits/`), committed routed KiCad 10 boards (`hardware/layout/v1/`), JLCPCB/EasyEDA pin-for-pin verification (`hardware/scripts/jlc_parts.py`), fab & assembly exports (`hardware/scripts/fab_outputs.py`, `release.py`), tests (`hardware/tests/`), and frozen manufacturing releases (`hardware/releases/v1/`).
- `mechanical/`: Parametric CadQuery enclosure (`mechanical/scripts/build_enclosure.py`), JLC3DP print plates, fit drawings, 3D renders, and solid/print-rule tests (`mechanical/tests/`).
- `docker/`: One folder per container image (`eda`, `cad`, `lint`, `cpp-lint`), orchestrated from root `compose.yaml`.
- `docs/`: Wiring guide (`docs/wiring.md`, including ROGER B70/1DC) and JLCPCB/JLC3DP ordering instructions (`docs/ordering.md`).

Generated/build outputs (`hardware/build/`, `mechanical/build/`, `firmware/.pio/`, generated `WebAssets.hpp`, generated `BuildVersion.h`) are never edited by hand and are git-ignored (except frozen `hardware/releases/<v>/` manufacturing snapshots).

---

## Containerized toolchain (Docker-first)

All EDA, CAD, linting and firmware compilation/test commands run in Docker via `compose.yaml` profiles. Never require host installations of KiCad, SKiDL, `fastroute`, CadQuery, PlatformIO, `clang-tidy`, or `ruff`.

- `eda` (`docker/eda/Dockerfile`): Multi-arch (`amd64` / `arm64`) Ubuntu 24.04 + KiCad 10 PPA (`kicad`, `kicad-footprints`, `kicad-symbols`, `kicad-templates`, `kicad-packages3d`, `pcbnew` Python bindings, `kicad-cli`), Python venv (`skidl==2.3.0`, `kinet2pcb==1.1.4`, `pyyaml`, `pytest`, `pillow`, `shapely`), `fix_fp_lib_table.py`, and **`fastroute`** (`0.1.14`, SHA-256 pinned per architecture).
- `cad` (`docker/cad/Dockerfile`): `python:3.13-slim-trixie` + `cadquery==2.8.0`, `pyyaml`, `pytest` (plus X11/OpenGL/OSMesa libs for offscreen renders).
- `cpp-lint` (`docker/cpp-lint/Dockerfile`): `python:3.13-slim-trixie` + `clang-format`, `clang-tidy`, `g++`, `make`, `git`, `platformio`.
- `lint` (`docker/lint/Dockerfile`): `python:3.13-slim-trixie` + `ruff`.

Standard invocations from repo root:

- Python lint: `docker compose --profile lint run --rm -T lint check .`
- C++ format/tidy + native tests + firmware build:
  - `docker compose --profile lint run --rm -T cpp-lint "pio test -d firmware -e native"`
  - `docker compose --profile lint run --rm -T cpp-lint "pio test -d firmware -e native_sanitized"`
  - `docker compose --profile lint run --rm -T cpp-lint "cd firmware && pio run -e dev_c6"`
- Full hardware + CAD + release + test pipeline:
  - `python3 hardware/scripts/build.py [--eda] [--cad] [--release] [--test] [--firmware] [--fresh]`

---

## Hardware & PCB pipeline (`hardware/`)

Follow the sibling workflow (`weather-station` / `knx-dali-gateway` / `esp-measurement-platform`):

1. **Product spec (`hardware/product/spec.yaml`)**: Single source of truth for board outlines, enclosure envelope, voltage domains, and variants.
2. **SKiDL circuits (`hardware/circuits/`)**:
   - Every part carries `Manufacturer`, `Manufacturer_Part_Number`, `LCSC`, `Source`, and `Assembly` (`jlc`, `hand`, or `none`).
   - Passives (`PASSIVES` dict in `common.py`) are **0805 or larger** (no 0603/0402 unless physically unavoidable and explicitly documented) for easy rework/hand-soldering; ICs use leaded packages where available.
   - Create explicit-reference parts last so adding/removing auto-referenced passives does not renumber `R`/`C` designators.
   - `gen_circuits.py` outputs `hardware/build/<v>/<board>/{<board>.net, parts.json}`.
3. **Layout & `fastroute` autorouting (`hardware/scripts/layout.py`)**:
   - Committed `hardware/layout/<v>/<board>/<board>.kicad_pcb` is the source of truth; `layout.py <board> sync` updates frame, outlines, keep-outs, pours, rules, and net classes from `layout_<board>.yaml` while preserving placed components and copper.
   - `layout.py <board> route` runs `kicad-cli pcb drc` on the unrouted board as a baseline, exports Specctra DSN, runs **`fastroute`** (multi-attempt / time-limited), imports the best SES, fixes through-vias if planes are hidden, and checks connectivity + DRC.
   - **Pass/fail rule:** Ignore `fastroute`'s exit code (it exits 0 even with unrouted nets). Routing passes **only** when `kicad-cli pcb drc` shows zero errors beyond the unrouted baseline and `pcbnew` connectivity reports **0 unrouted connections** (never rely on DRC's capped `unconnected_items` list).
   - Never weaken DRC clearances or neck-down rules silently to force a route.
4. **JLCPCB & fab-neutral release (`hardware/scripts/release.py`)**:
   - Refuses any board with DRC errors, unrouted nets, unsourced parts, or failed `jlc_parts.py` EasyEDA pin-for-pin / stock checks (`JLC_LIVE=0` uses the committed `hardware/product/jlc_reference.json` snapshot in CI).
   - Outputs per board in `hardware/releases/<v>/<board>/`:
     - `<board>_gerbers.zip` (Gerber X2 + Excellon PTH/NPTH + IPC-D-356 netlist)
     - `<board>_odb.zip` (ODB++)
     - `<board>_bom_jlc.csv` & `<board>_cpl_jlc.csv` (JLCPCB SMT assembly format, with verified EasyEDA rotation offsets)
     - `<board>_bom.csv` & `<board>_cpl.csv` (generic MPN BOM & KiCad position file)
     - `<board>.glb` (3D board with `kicad-packages3d` models) and `top`/`bottom`/`in1`/`in2`/`overlay` SVG/PNG renders
   - Plus top-level `order_lcsc.csv` / `order_elsewhere.csv` and `enclosure/` print-ready STLs/STEPs + colored VTK renders (`base`, `lid`, `assembly`).

---

## Mechanical & JLC3DP enclosure pipeline (`mechanical/`)

- Built parametrically in **CadQuery** (`mechanical/scripts/build_enclosure.py`) from board outlines and `layout_main.yaml` coordinates, with engraved cover terminal/UI labels and thin `0.4 mm` translucent LED diffuser skins.
- Exports assembled `.stl`/`.step` + **JLC3DP-ready print plates** (`enclosure/print/*.stl`) with parts spaced `>= 6 mm` apart so MJF/SLS/SLA printing never fuses gaps; `render_assembly3d.py` renders colored VTK PNGs and clean SVGs.
- Automated `mechanical/tests/` verify board-to-case clearance, fastener/hole alignment, wall thickness, snap/print rules, and single-solid print meshes.

---

## Target hardware & ROGER BH30/610/HS integration

### ROGER BH30/610/HS (`B70/1DC` controller) facts (from official B70/1DC manual)

- **Accessory power**: Terminals `27 (+24V)` – `28 (COM)` supply 24 V DC (7–10 W max, protected by F2 2A fuse).
- **Control inputs** (all N.O. dry contacts referenced to `21 (COM)`):
  - `23 (AP)` – `21 (COM)`: Open (note: holding `AP` closed inhibits automatic reclosure until released).
  - `24 (CH)` – `21 (COM)`: Close.
  - `25 (PP)` – `21 (COM)`: Step-by-step (Open / Stop / Close).
  - `26 (PED)` – `21 (COM)`: Partial / pedestrian opening (factory default 50%).
  - `22 (ORO)` – `21 (COM)`: Timer / hold-open while closed.
- **Open/closed state signals**:
  - `8 (+SC)` – `9 (COM)`: 24 V DC Gate Open Indicator output (max 3 W): **0 V when closed**, **pulsing/blinking while moving**, **steady 24 V when open** (requires standby/low-power mode disabled and `+SC` not assigned to photocell test).
  - `6 – 7 (COR)`: Potential-free dry-contact relay output; when configured for Management System mode (`par. 20 != 00`), signals **completely open**, **completely closed**, or **alarm/unlocked/low-battery**.
  - Plus dedicated gateway dry-contact sense inputs for external magnetic reed / limit switches (for doors or gates without `+SC`/`COR`).
- **RS-485 (`16 COM`, `17 LNA`, `18 LNB`)**: Proprietary Roger Master/Slave bus (undocumented wire protocol). Omitted from the compact `v1` (`74.0 x 54.0 mm`) hardware to fit the ROGER BH30 battery compartment; can be added as a future board variant if reverse-engineered.

### Electrical & safety rules

- Wiegand `D0`/`D1` lines idle at ~5 V and may sit on long outdoor cable runs: protect with 5 V-tolerant level shifting/Schmitt buffering and TVS/ESD clamping; drive reader `LED` / `BEEP` via open-drain outputs.
- Sense inputs must accept both dry-contact switches (reed/REX) and 12–24 V DC active signals (such as `B70/1DC` `+SC`) via optocouplers or clamped resistor-divider stages.
- Relay outputs must be potential-free (isolated dry contacts, rated for inductive strike/solenoid/gate loads with flyback/snubber consideration where appropriate).

---

## Firmware & Web UI architecture (`firmware/`)

- **Composition root**: `firmware/src/firmware/main.cpp` only wires dependencies and tasks; business logic lives in focused modules under `firmware/src/{core,access,gate,wiegand,mqtt,web}/` (`ISensorDecoder`, `IRelayPolicy`, `IGatewayObserver`, `IMqttPublisher`, `RestartButton`) so host native tests (`pio test -e native`) run the core logic without ESP-IDF hardware.
- **Core features**:
  - Local credential store in NVS + SPIFFS (`/storage/users.json`) for Wiegand cards/fobs + keypad PINs, per-user relay target, and access log ring buffer.
  - Configurable **Gate / Door profiles** (`IRelayPolicy`): single pulse (`PP` or strike), dual open/close relays (`AP`/`CH`), hold-open (`ORO`/maglock), dual doors, and configurable open/closed sensing (`ISensorDecoder`: single reed NO/NC, dual open+closed limit switches, blinking status + confirm, or timer fallback).
  - Configurable **Wiegand reader** settings (bit length auto/26/34/37/58, keypad buffering, buzzer/LED polarity & feedback timings).
  - **Web UI** (`firmware/data/` → gzip-packed into `WebAssets.hpp` by `pack_webui.py`, never hand-edited): Overview, Users & Keys (with "enroll last scanned tag"), Gate & Reader (visual scenario cards & live terminal diagram), Network (Wi-Fi & MQTT), and System (OTA dropzone & maintenance).
  - **Home Assistant**: MQTT Auto-Discovery (`lock` or `cover` entity depending on door/gate mode, `binary_sensor` for contact/moving/fault, `sensor` for last tag/user, `button` for trigger/reboot) + availability LWT.
  - **Versioning**: Derived from git/UTC build metadata at build time; never hard-code `FW_VERSION`.

---

## Devin Desktop stability notes

- Even with `.vscode/settings.json` disabling VS Code diff zones, SCM decorations, and file watchers, Devin Desktop's chat webview (`devin-webapp-host`) computes inline JS diffs (`r.diff`) on the Electron renderer thread for edit tool calls, which can cause `UnresponsiveSampleError` freezes/crashes after large or heavily batched edits.
- Keep edits small/focused, start a fresh session (`/clear`) between major phases, or run heavy multi-file generation from a terminal via the `devin` CLI instead of the Desktop chat view. Prune old sessions in `~/.local/share/devin/cli/sessions.db` with `devin rm --force <session-id>` when needed.

