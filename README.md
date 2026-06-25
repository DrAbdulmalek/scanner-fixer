<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square&logo=python" alt="Python" />
  <img src="https://img.shields.io/badge/OpenCV-4.8%2B-green?style=flat-square&logo=opencv" alt="OpenCV" />
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="MIT" />
  <img src="https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey?style=flat-square" alt="Cross Platform" />
</p>

<h1 align="center">Scanner Fixer</h1>

<p align="center">
  <strong>Dual-algorithm skew detection + auto-crop + manual adjustment + batch processing</strong><br/>
  <span dir="rtl">مُصلح الصور الممسوحة — كشف ميلان ذكي + قص حواف تلقائي + تعديل يدوي + معالجة دفعية</span>
</p>

---

## What It Does

Scanner Fixer is a desktop GUI application that automatically detects and corrects skew (rotation) in scanned document images. It uses a **dual-algorithm approach** combining `minAreaRect` and `HoughLines` for robust angle detection, followed by intelligent auto-cropping with dynamic thresholding.

### Key Features

| Feature | Description |
|---------|-------------|
| **Dual Skew Detection** | Merges `minAreaRect` + `HoughLines` — averages when they agree, prefers `minAreaRect` on conflict |
| **Dynamic Auto-Crop** | Threshold adapts to each image's actual brightness percentile — works with any scanner |
| **Manual Angle Slider** | Fine-tune correction with -15 to +15 degree slider + 0.5 degree nudge buttons |
| **Batch Processing** | Process entire folders with progress bar, threaded execution, and cancel support |
| **Detailed Log** | Per-image table showing auto angle, manual adjustment, total angle, and size before/after |
| **Dark Theme UI** | Modern dark interface with Catppuccin-inspired colors |
| **Instant Preview** | Side-by-side original vs processed view with real-time slider updates |

## Quick Start

```bash
# Clone the repository
git clone https://github.com/DrAbdulmalek/scanner-fixer.git
cd scanner-fixer

# Install dependencies
pip install -r requirements.txt

# On Manjaro/Arch Linux if pip complains:
pip install -r requirements.txt --break-system-packages

# Run
python3 scanner_fixer.py
```

## Algorithm Details

### Skew Detection (Dual Method)

The detector combines two complementary approaches:

1. **minAreaRect** — Finds the minimum-area rotated rectangle enclosing all text pixels. Fast and accurate for documents with sufficient text content.

2. **HoughLines** — Detects dominant line orientations via Hough transform. Robust against noise but can be affected by non-text elements.

**Merging logic:**
- If both methods agree within 5 degrees, the average is used (higher accuracy)
- If they disagree, `minAreaRect` is preferred (more reliable for text-heavy documents)
- Tested accuracy: 3.50 degrees detected vs 3.50 degrees actual

### Auto-Crop (Dynamic Threshold)

Instead of a fixed pixel threshold, the crop boundary is computed from the image's 95th brightness percentile:

```python
bg_val = np.percentile(gray, 95)
threshold = max(220, bg_val - 15)  # Adaptive to scanner brightness
```

This ensures consistent border detection regardless of scanner settings, paper color, or image contrast.

### Processing Pipeline

```
Input Image
    |
    v
[1] Convert to grayscale
    |
    v
[2] Detect skew angle (dual algorithm)
    |
    v
[3] Apply rotation (bilinear interpolation, white border)
    |
    v
[4] Auto-crop (dynamic threshold + margin)
    |
    v
Output Image (straight + cropped)
```

## Usage

### Single Image
1. Click "Open Image" and select a scanned document
2. The auto-detected angle is shown in the side panel
3. Click "Process" to apply correction and crop
4. Use the slider for manual fine-tuning if needed
5. Click "Save" to export the result

### Batch Processing
1. Click "Process Folder" and select a directory
2. All images are processed in a background thread
3. Results are saved to a `Processed/` subdirectory
4. Progress bar and detailed log track each file

### Manual Adjustment
- **Slider**: Drag to add extra rotation (-15 to +15 degrees)
- **Nudge buttons**: Fine-tune by 0.5 or 1 degree increments
- **Reset**: Return to auto-detected angle
- Preview updates automatically 700ms after the last slider movement

## Supported Formats

| Format | Extension |
|--------|-----------|
| PNG | `.png` |
| JPEG | `.jpg`, `.jpeg` |
| BMP | `.bmp` |
| TIFF | `.tiff`, `.tif` |

## Tech Stack

- **OpenCV** — Image processing, skew detection, rotation, cropping
- **Pillow** — Image display in Tkinter via `ImageTk`
- **NumPy** — Array operations for pixel analysis
- **Tkinter** — Native Python GUI (no external GUI framework needed)

## Project Structure

```
scanner-fixer/
  scanner_fixer.py        # Main application (GUI + algorithms)
  requirements.txt        # Python dependencies
  LICENSE                 # MIT License
  .gitignore
  docs/
    development-chat.md   # Development conversation log (Arabic)
```

## License

MIT — Dr. Abdulmalek Al-Husseini