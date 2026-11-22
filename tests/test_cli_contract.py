"""
Tests for the scanner-fixer CLI integration contract (docs/INTEGRATION.md).
Run with: pytest tests/test_cli_contract.py -v
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scanner_fixer.cli import EXIT_OK, EXIT_PROCESSING_FAILURE, EXIT_USAGE, cli


# ─── Fixtures ────────────────────────────────────────────────────────────────

STATUS_KEYS = {"input", "outputs", "operations_applied",
               "processing_ms", "status", "error"}


def make_tiny_page(directory, name="tiny.png", size=40):
    """Tiny synthetic scan: white page with a dark content block."""
    img = np.ones((size, size, 3), dtype=np.uint8) * 255
    img[size // 4: 3 * size // 4, size // 4: 3 * size // 4] = 30
    path = Path(directory) / name
    cv2.imwrite(str(path), img)
    return path


# ─── fix: default human mode ─────────────────────────────────────────────────

class TestFixDefaultMode:
    def test_human_output_and_exit_zero(self, tmp_path):
        img = make_tiny_page(tmp_path)
        out = tmp_path / "out.png"
        result = CliRunner().invoke(cli, ["fix", str(img), "--output", str(out)])
        assert result.exit_code == EXIT_OK
        assert out.exists()
        assert "Processing:" in result.output
        assert "✓ Saved" in result.output
        assert "{" not in result.output  # no JSON on stdout by default

    def test_json_still_keeps_human_default(self, tmp_path):
        # --json must not change the default mode, only add a machine mode
        img = make_tiny_page(tmp_path)
        result = CliRunner().invoke(cli, ["fix", str(img), "--report"])
        assert result.exit_code == EXIT_OK
        assert "✓ Saved" in result.output


# ─── fix: --json status object ───────────────────────────────────────────────

class TestFixJson:
    def test_emits_valid_json_with_required_keys(self, tmp_path):
        img = make_tiny_page(tmp_path)
        out = tmp_path / "out.png"
        result = CliRunner().invoke(
            cli, ["fix", str(img), "--output", str(out), "--json"])
        assert result.exit_code == EXIT_OK

        status = json.loads(result.output)  # stdout holds a single JSON object
        assert set(status) == STATUS_KEYS
        assert status["status"] == "ok"
        assert status["error"] is None
        assert status["input"] == str(img)
        assert status["outputs"] == [str(out)]
        assert Path(status["outputs"][0]).exists()
        assert "crop" in status["operations_applied"]
        assert "enhance" in status["operations_applied"]
        assert isinstance(status["processing_ms"], int)
        assert status["processing_ms"] >= 0

    def test_unreadable_image_reports_error_status(self, tmp_path):
        fake = tmp_path / "corrupt.png"
        fake.write_text("not an image")
        result = CliRunner().invoke(cli, ["fix", str(fake), "--json"])
        assert result.exit_code == EXIT_PROCESSING_FAILURE

        status = json.loads(result.output)
        assert status["status"] == "error"
        assert status["error"] is not None
        assert status["outputs"] == []


# ─── fix: --bypass passthrough ───────────────────────────────────────────────

class TestFixBypass:
    def test_bypassed_status_and_exit_zero(self, tmp_path):
        img = make_tiny_page(tmp_path)
        out = tmp_path / "out.png"
        result = CliRunner().invoke(
            cli, ["fix", str(img), "--output", str(out), "--bypass", "--json"])
        assert result.exit_code == EXIT_OK

        status = json.loads(result.output)
        assert status["status"] == "bypassed"
        assert status["error"] is None
        assert status["operations_applied"] == []
        assert status["outputs"] == [str(out)]
        assert out.read_bytes() == img.read_bytes()  # copied unchanged

    def test_bypass_overrides_processing_flags(self, tmp_path):
        # Call site stays identical: same flags, only --bypass toggled
        img = make_tiny_page(tmp_path)
        out = tmp_path / "out.png"
        result = CliRunner().invoke(
            cli, ["fix", str(img), "--output", str(out), "--binarize",
                  "--no-crop", "--deskew-method", "projection",
                  "--bypass", "--json"])
        assert result.exit_code == EXIT_OK

        status = json.loads(result.output)
        assert status["status"] == "bypassed"
        assert out.read_bytes() == img.read_bytes()

    def test_bypass_human_mode_announces_choice(self, tmp_path):
        img = make_tiny_page(tmp_path)
        out = tmp_path / "out.png"
        result = CliRunner().invoke(
            cli, ["fix", str(img), "--output", str(out), "--bypass"])
        assert result.exit_code == EXIT_OK
        assert "Bypassed" in result.output
        assert out.read_bytes() == img.read_bytes()


# ─── exit-code contract ──────────────────────────────────────────────────────

class TestExitCodes:
    def test_missing_input_path_exits_3(self, tmp_path):
        result = CliRunner().invoke(cli, ["fix", str(tmp_path / "missing.png")])
        assert result.exit_code == EXIT_USAGE

    def test_unknown_option_exits_3(self, tmp_path):
        img = make_tiny_page(tmp_path)
        result = CliRunner().invoke(cli, ["fix", str(img), "--not-a-flag"])
        assert result.exit_code == EXIT_USAGE

    def test_unreadable_image_exits_2(self, tmp_path):
        fake = tmp_path / "corrupt.png"
        fake.write_text("not an image")
        result = CliRunner().invoke(cli, ["fix", str(fake)])
        assert result.exit_code == EXIT_PROCESSING_FAILURE

    def test_console_entry_raises_system_exit(self, tmp_path):
        # The console script runs sys.exit(cli(...)); check the same in-process
        img = make_tiny_page(tmp_path)
        with pytest.raises(SystemExit) as excinfo:
            cli(["fix", str(img), "--bypass"])
        assert excinfo.value.code == EXIT_OK

    def test_console_entry_usage_error_code(self):
        with pytest.raises(SystemExit) as excinfo:
            cli(["fix", "/nonexistent/path/image.png"])
        assert excinfo.value.code == EXIT_USAGE


# ─── batch: folder in, images out ────────────────────────────────────────────

class TestBatchContract:
    def test_batch_json_ok(self, tmp_path):
        src = tmp_path / "scans"
        src.mkdir()
        make_tiny_page(src, "a.png")
        make_tiny_page(src, "b.png")
        out_dir = tmp_path / "fixed"

        result = CliRunner().invoke(
            cli, ["batch", str(src), "--output-dir", str(out_dir), "--json"])
        assert result.exit_code == EXIT_OK

        status = json.loads(result.output)
        assert status["status"] == "ok"
        assert status["error"] is None
        assert status["input"] == str(src)
        assert len(status["outputs"]) == 2
        assert all(Path(o).exists() for o in status["outputs"])
        assert set(status["operations_applied"]) == {"crop", "deskew", "enhance"}

    def test_batch_bypass_copies_unchanged(self, tmp_path):
        src = tmp_path / "scans"
        src.mkdir()
        make_tiny_page(src, "a.png")
        out_dir = tmp_path / "fixed"

        result = CliRunner().invoke(
            cli, ["batch", str(src), "--output-dir", str(out_dir),
                  "--bypass", "--json"])
        assert result.exit_code == EXIT_OK

        status = json.loads(result.output)
        assert status["status"] == "bypassed"
        assert status["operations_applied"] == []
        copied = Path(status["outputs"][0])
        assert copied.name == "a_fixed.png"
        assert copied.read_bytes() == (src / "a.png").read_bytes()

    def test_batch_partial_failure_exits_2(self, tmp_path):
        src = tmp_path / "scans"
        src.mkdir()
        make_tiny_page(src, "good.png")
        (src / "corrupt.png").write_text("not an image")

        result = CliRunner().invoke(
            cli, ["batch", str(src), "--output-dir", str(tmp_path / "fixed"),
                  "--json"])
        assert result.exit_code == EXIT_PROCESSING_FAILURE

        status = json.loads(result.output)
        assert status["status"] == "error"
        assert status["error"] is not None
        assert len(status["outputs"]) == 1  # the good image still comes out

    def test_batch_empty_dir_json_ok(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = CliRunner().invoke(cli, ["batch", str(empty), "--json"])
        assert result.exit_code == EXIT_OK

        status = json.loads(result.output)
        assert status["status"] == "ok"
        assert status["outputs"] == []
