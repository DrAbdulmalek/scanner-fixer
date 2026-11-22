"""
cli.py
Command-line interface for scanner-fixer.

Usage examples:
    scanner-fixer fix scan.jpg
    scanner-fixer fix scan.jpg --output fixed.jpg --binarize
    scanner-fixer fix scan.jpg --json
    scanner-fixer fix scan.jpg --bypass --output fixed.jpg
    scanner-fixer batch ./scans/ --output-dir ./fixed/
    scanner-fixer batch ./scans/ --json
    scanner-fixer info scan.jpg

Integration contract (docs/INTEGRATION.md):
    - `--json` prints exactly one machine-readable status object to stdout.
    - `--bypass` copies input to output unchanged and reports status
      "bypassed" (explicit, logged bypass — never a silent skip).
    - Exit codes: 0 = success or bypass, 2 = processing failure,
      3 = usage error. An unexpected internal error still exits 1 with a
      traceback (outside the contract).
"""

import click
import json
import shutil
import sys
import time
from pathlib import Path
from .pipeline import fix_scan, fix_scan_batch


# ─── Exit-code contract (docs/INTEGRATION.md) ────────────────────────────────

EXIT_OK = 0
EXIT_PROCESSING_FAILURE = 2
EXIT_USAGE = 3


class ContractGroup(click.Group):
    """
    click.Group that enforces the documented exit-code contract.

    click exits with 2 on usage errors (bad flag, missing argument,
    nonexistent path). The contract reserves 2 for processing failures,
    so usage errors are remapped to 3 here.
    """

    def main(self, *args, **kwargs):
        kwargs["standalone_mode"] = False
        try:
            rv = super().main(*args, **kwargs)
        except SystemExit:
            raise  # explicit ctx.exit (--version): already the right code
        except click.UsageError as e:
            e.show()
            sys.exit(EXIT_USAGE)
        except click.Abort:
            click.echo("Aborted!", err=True)
            sys.exit(1)
        if rv is None:
            rv = EXIT_OK
        sys.exit(rv)


# ─── Status object and bypass helpers ────────────────────────────────────────

def _build_status(input_path, outputs, operations, processing_ms, status, error=None):
    """
    Build the machine-readable status object printed by --json.

    Schema (docs/INTEGRATION.md):
        {"input": str, "outputs": [str], "operations_applied": [str],
         "processing_ms": int, "status": "ok"|"error"|"bypassed",
         "error": null|str}
    """
    return {
        "input": str(input_path),
        "outputs": [str(o) for o in outputs],
        "operations_applied": list(operations),
        "processing_ms": int(round(processing_ms)),
        "status": status,
        "error": error,
    }


def _echo_status(status_obj):
    """Print the status object as the only stdout content."""
    click.echo(json.dumps(status_obj, indent=2, ensure_ascii=False))


def _copy_unchanged(src: Path, dst: Path) -> None:
    """Copy src → dst byte-for-byte (--bypass passthrough)."""
    if src.resolve() == dst.resolve():
        return  # input already at the output location
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _report_failure(input_path, outputs, operations, elapsed_ms, error, json_mode):
    """Report a processing failure (exit code 2) in human or JSON mode."""
    if json_mode:
        _echo_status(_build_status(input_path, outputs, operations,
                                   elapsed_ms, "error", str(error)))
    else:
        click.echo(f"Error: {error}", err=True)
    return EXIT_PROCESSING_FAILURE


@click.group(cls=ContractGroup)
@click.version_option("1.0.0")
def cli():
    """scanner-fixer: Pre-OCR image normalization for scanned documents."""
    pass


@cli.command()
@click.argument("input_path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output file path (default: input_fixed.ext)")
@click.option("--no-crop", is_flag=True, help="Disable border cropping")
@click.option("--no-rotate", is_flag=True, help="Disable 180° rotation correction")
@click.option("--no-deskew", is_flag=True, help="Disable skew correction")
@click.option("--no-enhance", is_flag=True, help="Disable OCR enhancement")
@click.option("--binarize", is_flag=True, help="Convert to black & white (text-only pages)")
@click.option("--deskew-method", default="hough", type=click.Choice(["hough", "projection"]),
              help="Deskew algorithm (default: hough)")
@click.option("--use-tesseract", is_flag=True, help="Use Tesseract OSD for rotation detection")
@click.option("--report", is_flag=True,
              help="Print processing report as JSON (ignored with --json)")
@click.option("--json", "json_mode", is_flag=True,
              help="Print one machine-readable status object to stdout (and nothing else)")
@click.option("--bypass", is_flag=True,
              help="No-op passthrough: copy input to output unchanged (status \"bypassed\"); "
                   "overrides all processing flags")
def fix(input_path, output, no_crop, no_rotate, no_deskew, no_enhance,
        binarize, deskew_method, use_tesseract, report, json_mode, bypass):
    """Fix a single scanned image."""

    input_path = Path(input_path)

    if output is None:
        output = input_path.parent / f"{input_path.stem}_fixed{input_path.suffix}"
    output = Path(output)

    if bypass:
        return _run_fix_bypass(input_path, output, json_mode)

    do_crop = not no_crop
    do_rotate = not no_rotate
    do_deskew = not no_deskew
    do_enhance = not no_enhance

    operations = [name for enabled, name in (
        (do_crop, "crop"),
        (do_rotate, "rotate"),
        (do_deskew, "deskew"),
        (do_enhance, "enhance"),
    ) if enabled]
    if binarize:
        operations.append("binarize")

    if not json_mode:
        click.echo(f"Processing: {input_path.name}")

    start = time.perf_counter()
    try:
        result = fix_scan(
            input_path=input_path,
            output_path=output,
            do_crop=do_crop,
            do_rotate=do_rotate,
            do_deskew=do_deskew,
            do_enhance=do_enhance,
            binarize=binarize,
            deskew_method=deskew_method,
            use_tesseract_osd=use_tesseract,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return _report_failure(input_path, [], operations, elapsed_ms, e, json_mode)
    elapsed_ms = (time.perf_counter() - start) * 1000

    if not output.exists():
        error = f"Processing finished but no output was written: {output}"
        return _report_failure(input_path, [], operations, elapsed_ms, error, json_mode)

    if json_mode:
        _echo_status(_build_status(input_path, [output], operations, elapsed_ms, "ok"))
        return EXIT_OK

    click.echo(f"✓ Saved: {output}")

    if report:
        click.echo(json.dumps(result["report"], indent=2, ensure_ascii=False))
    else:
        r = result["report"]
        if r.get("rotation_applied_deg"):
            click.echo(f"  Rotation corrected: {r['rotation_applied_deg']}°")
        if r.get("skew_corrected_deg"):
            click.echo(f"  Skew corrected: {r['skew_corrected_deg']}°")
        click.echo(f"  Final size: {r['final_size']}")

    return EXIT_OK


def _run_fix_bypass(input_path: Path, output: Path, json_mode: bool):
    """--bypass: copy input to output unchanged; report status "bypassed"."""
    start = time.perf_counter()
    try:
        _copy_unchanged(input_path, output)
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return _report_failure(input_path, [output], [], elapsed_ms, e, json_mode)
    elapsed_ms = (time.perf_counter() - start) * 1000

    if json_mode:
        _echo_status(_build_status(input_path, [output], [], elapsed_ms, "bypassed"))
    else:
        click.echo(f"✓ Bypassed (--bypass): {input_path.name} → {output} (copied unchanged)")
    return EXIT_OK


@cli.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--output-dir", "-o", default=None, help="Output directory (default: input_dir/fixed)")
@click.option("--ext", default="jpg,png,tif,tiff,bmp", help="Comma-separated file extensions")
@click.option("--binarize", is_flag=True, help="Convert to black & white")
@click.option("--suffix", default="_fixed", help="Suffix added to output filenames")
@click.option("--json", "json_mode", is_flag=True,
              help="Print one machine-readable status object to stdout (and nothing else)")
@click.option("--bypass", is_flag=True,
              help="No-op passthrough: copy all images to the output directory unchanged "
                   "(status \"bypassed\")")
def batch(input_dir, output_dir, ext, binarize, suffix, json_mode, bypass):
    """Process all images in a directory."""

    input_dir = Path(input_dir)

    if output_dir is None:
        output_dir = input_dir / "fixed"
    output_dir = Path(output_dir)

    extensions = [f".{e.strip().lstrip('.')}" for e in ext.split(",")]
    paths = [
        p for p in sorted(input_dir.iterdir())
        if p.suffix.lower() in extensions
    ]

    operations = ["crop", "deskew", "enhance"]
    if binarize:
        operations.append("binarize")

    start = time.perf_counter()

    if not paths:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if json_mode:
            _echo_status(_build_status(input_dir, [], operations, elapsed_ms, "ok"))
        else:
            click.echo(f"No images found in {input_dir}")
        return EXIT_OK

    if bypass:
        return _run_batch_bypass(input_dir, paths, output_dir, suffix,
                                 start, json_mode)

    if not json_mode:
        click.echo(f"Found {len(paths)} images → {output_dir}")

    try:
        results = fix_scan_batch(
            input_paths=paths,
            output_dir=output_dir,
            suffix=suffix,
            binarize=binarize,
            quiet=json_mode,  # keep stdout clean for the JSON status object
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return _report_failure(input_dir, [], operations, elapsed_ms, e, json_mode)

    elapsed_ms = (time.perf_counter() - start) * 1000

    outputs, errors = [], []
    for r in results:
        name = r.get("input", "?")
        if r.get("status") == "ok":
            saved = r.get("report", {}).get("saved_to")
            if saved and Path(saved).exists():
                outputs.append(Path(saved))
            else:
                errors.append(f"{name}: output file missing")
        else:
            errors.append(f"{name}: {r.get('error')}")

    if json_mode:
        status = "ok" if not errors else "error"
        error = None if not errors else \
            f"{len(errors)}/{len(results)} files failed: " + "; ".join(errors)
        _echo_status(_build_status(input_dir, outputs, operations, elapsed_ms, status, error))
    else:
        for err in errors:
            click.echo(f"  Error: {err}", err=True)
        click.echo(f"\nDone: {len(outputs)} OK, {len(errors)} errors")

    return EXIT_OK if not errors else EXIT_PROCESSING_FAILURE


def _run_batch_bypass(input_dir, paths, output_dir, suffix, start, json_mode):
    """--bypass for batch: copy every image unchanged; report status "bypassed"."""
    outputs = []
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        for path in paths:
            out = output_dir / f"{path.stem}{suffix}{path.suffix}"
            _copy_unchanged(path, out)
            outputs.append(out)
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return _report_failure(input_dir, outputs, [], elapsed_ms, e, json_mode)

    elapsed_ms = (time.perf_counter() - start) * 1000

    if json_mode:
        _echo_status(_build_status(input_dir, outputs, [], elapsed_ms, "bypassed"))
    else:
        click.echo(f"✓ Bypassed (--bypass): {len(outputs)} images copied unchanged → {output_dir}")
    return EXIT_OK


@cli.command()
@click.argument("input_path", type=click.Path(exists=True))
def info(input_path):
    """Show image info and estimated DPI without processing."""
    import cv2
    from .enhance import get_estimated_dpi

    img = cv2.imread(str(input_path))
    if img is None:
        click.echo(f"Error: Cannot read {input_path}")
        return

    h, w = img.shape[:2]
    channels = img.shape[2] if len(img.shape) == 3 else 1
    dpi = get_estimated_dpi(img)

    click.echo(f"File:     {input_path}")
    click.echo(f"Size:     {w} x {h} px")
    click.echo(f"Channels: {channels} ({'color' if channels == 3 else 'grayscale'})")
    click.echo(f"Est. DPI: {dpi or 'unknown'}")


if __name__ == "__main__":
    cli()
