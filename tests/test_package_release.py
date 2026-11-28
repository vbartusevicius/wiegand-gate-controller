"""Unit tests for the shared release asset packager (scripts/package_release.py)."""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import package_release as pr


def make_dummy_board(root: Path, board: str) -> None:
    bdir = root / board
    bdir.mkdir(parents=True, exist_ok=True)
    for suffix in pr.REQUIRED_BOARD_SUFFIXES:
        (bdir / f"{board}{suffix}").write_bytes(f"{board}{suffix}\n".encode())
    renders = bdir / "renders"
    renders.mkdir(exist_ok=True)
    (renders / "top.png").write_bytes(b"PNG")


def make_dummy_enclosure(root: Path) -> None:
    for rel in pr.REQUIRED_ENCLOSURE_FILES:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"{rel}\n".encode())


def make_dummy_firmware(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "usb-flash-firmware.bin").write_bytes(b"USB-FLASH-IMAGE")
    (root / "firmware.bin").write_bytes(b"OTA-APP-IMAGE")


class TestPackageRelease(unittest.TestCase):
    def test_parse_spec_repo(self) -> None:
        active, variants = pr.parse_spec(REPO / "hardware/product/spec.yaml")
        self.assertEqual(active, "v1")
        self.assertEqual(variants, {"v1": ["main"]})

    def test_parse_spec_block_lists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "spec.yaml"
            spec.write_text(
                "active_variant: pro\n"
                "variants:\n"
                "  lite:\n"
                "    boards: [main]\n"
                "  pro:\n"
                "    boards:\n"
                "      - main\n"
                "      - aux\n",
                encoding="utf-8",
            )
            active, variants = pr.parse_spec(spec)
            self.assertEqual(active, "pro")
            self.assertEqual(variants, {"lite": ["main"], "pro": ["main", "aux"]})

    def test_package_real_v1_hardware_and_checksums(self) -> None:
        hw_v1 = REPO / "hardware/releases/v1"
        self.assertTrue(hw_v1.is_dir(), "Expected frozen hardware/releases/v1/")
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            fw_dir = t / "fw"
            make_dummy_firmware(fw_dir)
            out1 = t / "out1"
            out2 = t / "out2"
            notes1 = t / "notes1.md"
            notes2 = t / "notes2.md"

            for out_dir, notes_file in ((out1, notes1), (out2, notes2)):
                pr.package_release(
                    spec_path=REPO / "hardware/product/spec.yaml",
                    variants_selected=None,
                    hardware_dir=hw_v1,
                    enclosure_dir=hw_v1 / "enclosure",
                    firmware_dir=fw_dir,
                    out_dir=out_dir,
                    notes_file=notes_file,
                    version="2026.11.28.0000",
                )

            files = sorted(p.name for p in out1.iterdir())
            self.assertEqual(
                files,
                [
                    "SHA256SUMS.txt",
                    "firmware.bin",
                    "usb-flash-firmware.bin",
                    "wiegand-gate-controller-hardware.zip",
                ],
            )

            # Deterministic zip output across runs
            self.assertEqual(
                pr.sha256_file(out1 / "wiegand-gate-controller-hardware.zip"),
                pr.sha256_file(out2 / "wiegand-gate-controller-hardware.zip"),
            )

            # Verify archive structure and exclusion of clutter
            with zipfile.ZipFile(out1 / "wiegand-gate-controller-hardware.zip") as zf:
                names = set(zf.namelist())
                for req in (
                    "assembly_parts.csv",
                    "order_elsewhere.csv",
                    "order_lcsc.csv",
                    "boards/main/main_gerbers.zip",
                    "boards/main/main_odb.zip",
                    "boards/main/main_bom_jlc.csv",
                    "boards/main/main_cpl_jlc.csv",
                    "boards/main/main_bom.csv",
                    "boards/main/main_cpl.csv",
                    "boards/main/main.kicad_pcb",
                    "boards/main/renders/top.png",
                    "enclosure/print/enclosure_plate.stl",
                    "enclosure/base.stl",
                    "enclosure/lid.stl",
                    "enclosure/assembly.step",
                    "enclosure/renders/assembly.png",
                ):
                    self.assertIn(req, names, f"Missing {req} in hardware zip")
                for n in names:
                    self.assertFalse(Path(n).suffix in pr.FORBIDDEN_ARCHIVE_SUFFIXES, f"Forbidden file in zip: {n}")

            # Verify SHA256SUMS.txt covers every asset accurately
            sums = (out1 / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(sums), 3)
            seen = []
            for line in sums:
                digest, filename = line.split("  ", 1)
                self.assertEqual(len(digest), 64)
                self.assertEqual(digest, hashlib.sha256((out1 / filename).read_bytes()).hexdigest())
                seen.append(filename)
            self.assertEqual(seen, ["firmware.bin", "usb-flash-firmware.bin", "wiegand-gate-controller-hardware.zip"])

            # Verify release notes Markdown table
            notes = notes1.read_text(encoding="utf-8")
            self.assertIn("| File | Use |", notes)
            for fname in files:
                self.assertIn(f"| `{fname}` |", notes)

    def test_strips_clutter_and_isolates_variant_boards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            spec = t / "spec.yaml"
            spec.write_text("active_variant: v1\nvariants:\n  v1:\n    boards: [main]\n", encoding="utf-8")

            hw_dir = t / "hw"
            hw_dir.mkdir()
            for f in pr.HARDWARE_ROOT_FILES:
                (hw_dir / f).write_text("col\n", encoding="utf-8")
            make_dummy_board(hw_dir, "main")
            make_dummy_board(hw_dir, "unrelated_other_variant_board")
            # Drop forbidden clutter inside board and enclosure dirs
            (hw_dir / "main" / "helper.py").write_text("print(1)\n", encoding="utf-8")
            (hw_dir / "main" / "script.sh").write_text("echo 1\n", encoding="utf-8")
            (hw_dir / "main" / "smoke.mjs").write_text("console.log(1)\n", encoding="utf-8")
            (hw_dir / "main" / ".DS_Store").write_bytes(b"junk")

            enc_dir = t / "enc"
            make_dummy_enclosure(enc_dir)
            (enc_dir / "debug.py").write_text("x=1\n", encoding="utf-8")

            fw_dir = t / "fw"
            make_dummy_firmware(fw_dir)
            # Extra loose intermediate files in firmware dir must NOT be copied
            (fw_dir / "firmware.elf").write_bytes(b"ELF")
            (fw_dir / "firmware.map").write_bytes(b"MAP")
            (fw_dir / "meta.json").write_text("{}\n", encoding="utf-8")

            out_dir = t / "out"
            notes_file = t / "notes.md"
            pr.package_release(
                spec_path=spec,
                variants_selected=None,
                hardware_dir=hw_dir,
                enclosure_dir=enc_dir,
                firmware_dir=fw_dir,
                out_dir=out_dir,
                notes_file=notes_file,
                version="1.0",
            )

            self.assertEqual(
                sorted(p.name for p in out_dir.iterdir()),
                ["SHA256SUMS.txt", "firmware.bin", "usb-flash-firmware.bin", "wiegand-gate-controller-hardware.zip"],
            )
            with zipfile.ZipFile(out_dir / "wiegand-gate-controller-hardware.zip") as zf:
                names = zf.namelist()
                self.assertFalse(any("unrelated_other_variant_board" in n for n in names))
                self.assertFalse(any(n.endswith((".py", ".sh", ".mjs", ".DS_Store")) for n in names))

    def test_rejects_notes_file_inside_out_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            out_dir = t / "release-files"
            fw_dir = t / "fw"
            make_dummy_firmware(fw_dir)
            with self.assertRaises(ValueError):
                pr.package_release(
                    spec_path=REPO / "hardware/product/spec.yaml",
                    variants_selected=None,
                    hardware_dir=REPO / "hardware/releases/v1",
                    enclosure_dir=REPO / "hardware/releases/v1/enclosure",
                    firmware_dir=fw_dir,
                    out_dir=out_dir,
                    notes_file=out_dir / "release-notes.md",
                    version="1.0",
                )

    def test_rejects_missing_required_board_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            hw_copy = t / "hw"
            shutil.copytree(REPO / "hardware/releases/v1", hw_copy)
            (hw_copy / "main/main_gerbers.zip").unlink()
            fw_dir = t / "fw"
            make_dummy_firmware(fw_dir)
            with self.assertRaises(FileNotFoundError):
                pr.package_release(
                    spec_path=REPO / "hardware/product/spec.yaml",
                    variants_selected=None,
                    hardware_dir=hw_copy,
                    enclosure_dir=hw_copy / "enclosure",
                    firmware_dir=fw_dir,
                    out_dir=t / "out",
                    notes_file=t / "notes.md",
                    version="1.0",
                )

    def test_multi_variant_naming_and_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            spec = t / "spec.yaml"
            spec.write_text(
                "active_variant: lite\n"
                "variants:\n"
                "  lite:\n"
                "    boards: [main]\n"
                "  pro:\n"
                "    boards: [main, aux]\n",
                encoding="utf-8",
            )
            hw_dir = t / "hw_pro"
            hw_dir.mkdir()
            for f in pr.HARDWARE_ROOT_FILES:
                (hw_dir / f).write_text("col\n", encoding="utf-8")
            make_dummy_board(hw_dir, "main")
            make_dummy_board(hw_dir, "aux")
            enc_dir = t / "enc_pro"
            make_dummy_enclosure(enc_dir)
            fw_dir = t / "fw"
            make_dummy_firmware(fw_dir)
            out_dir = t / "out"
            notes = t / "notes.md"

            pr.package_release(
                spec_path=spec,
                variants_selected=["pro"],
                hardware_dir=hw_dir,
                enclosure_dir=enc_dir,
                firmware_dir=fw_dir,
                out_dir=out_dir,
                notes_file=notes,
                version="1.0",
            )
            self.assertEqual(
                sorted(p.name for p in out_dir.iterdir()),
                [
                    "SHA256SUMS.txt",
                    "pro-firmware.bin",
                    "pro-usb-flash-firmware.bin",
                    "wiegand-gate-controller-pro-hardware.zip",
                ],
            )
            with zipfile.ZipFile(out_dir / "wiegand-gate-controller-pro-hardware.zip") as zf:
                names = set(zf.namelist())
                self.assertIn("boards/main/main_gerbers.zip", names)
                self.assertIn("boards/aux/aux_gerbers.zip", names)


if __name__ == "__main__":
    unittest.main()
