"""
Expert Radiology – Signature Generator Microservice
Local Flask server for generating doctor email/document signatures.
"""

from flask import Flask, render_template, request, jsonify, send_file
from PIL import Image, ImageEnhance, ImageOps, ImageDraw, ImageFont
import os
import io
import base64
import json
import math
import re
from pathlib import Path
from werkzeug.utils import secure_filename

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"

for d in [UPLOAD_DIR, OUTPUT_DIR, ASSETS_DIR]:
    d.mkdir(exist_ok=True)

# ─── Fonts ────────────────────────────────────────────────────────────────────
# Resolution order: bundled assets (Docker-safe) → Linux system → macOS system
def _resolve_font(name: str) -> str | None:
    candidates = [
        BASE_DIR / "assets" / "fonts" / name,                           # bundled (primary)
        Path(f"/usr/share/fonts/truetype/liberation/{name}"),            # Linux
        Path(f"/usr/share/fonts/truetype/liberation2/{name}"),
        Path(f"/Library/Fonts/{name}"),                                  # macOS
        Path(f"/System/Library/Fonts/{name}"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None

FONT_REGULAR = _resolve_font("LiberationSans-Regular.ttf")
FONT_BOLD    = _resolve_font("LiberationSans-Bold.ttf")

def load_font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    # Last-resort: PIL default is bitmap and won't scale — raise so it's visible
    raise RuntimeError(
        "Could not load a scalable font. "
        "Make sure assets/fonts/LiberationSans-*.ttf are present."
    )

# ─── App ──────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

ALLOWED = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def find_upload(name: str) -> Path | None:
    """Return the uploaded file for a slot (signature / headshot / logo)."""
    for ext in ALLOWED:
        p = UPLOAD_DIR / f"{name}{ext}"
        if p.exists():
            return p
    return None


def img_to_b64(img: Image.Image, fmt="JPEG", quality=92) -> str:
    buf = io.BytesIO()
    if fmt == "JPEG" and img.mode in ("RGBA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
        img = bg
    img.save(buf, fmt, quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def open_and_flatten(path: Path) -> Image.Image:
    """Open any image and return an RGBA version."""
    img = Image.open(str(path)).convert("RGBA")
    return img


def apply_enhancements(img: Image.Image, contrast=1.0, brightness=1.0, saturation=1.0) -> Image.Image:
    rgb = img.convert("RGB")
    if contrast != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    if brightness != 1.0:
        rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
    if saturation != 1.0:
        rgb = ImageEnhance.Color(rgb).enhance(saturation)
    # Re-attach alpha if original had it
    if img.mode == "RGBA":
        r, g, b = rgb.split()
        a = img.split()[3]
        return Image.merge("RGBA", (r, g, b, a))
    return rgb


def crop_and_resize(img: Image.Image, crop: dict | None, target_size: tuple) -> Image.Image:
    """Apply Cropper.js coordinates then resize."""
    if crop:
        x = max(0, int(crop.get("x", 0)))
        y = max(0, int(crop.get("y", 0)))
        w = max(1, int(crop.get("width", img.width)))
        h = max(1, int(crop.get("height", img.height)))
        x2 = min(img.width,  x + w)
        y2 = min(img.height, y + h)
        img = img.crop((x, y, x2, y2))
    img = img.resize(target_size, Image.LANCZOS)
    return img


def paste_rgba(canvas: Image.Image, overlay: Image.Image, pos: tuple):
    """Paste an RGBA image onto an RGB canvas handling transparency."""
    if canvas.mode != "RGBA":
        canvas = canvas.convert("RGBA")
    if overlay.mode != "RGBA":
        overlay = overlay.convert("RGBA")
    tmp = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    tmp.paste(overlay, pos)
    canvas = Image.alpha_composite(canvas, tmp)
    return canvas.convert("RGB")


# ─── Signature image builder ─────────────────────────────────────────────────

def build_signature_image(data: dict) -> Image.Image:
    """
    data keys:
      name            – full name including title (e.g. "Syed Adil Aftab, MD")
      title           – clinical specialty (e.g. "Neuroradiologist")
      board_certified – bool, adds the ABR line when True
      specialization  – fellowship specialization
      university      – training institution
      sig_contrast, sig_brightness
      headshot_crop   – {x,y,width,height} from Cropper.js, or null
      headshot_brightness, headshot_saturation
      canvas_width    – total output width in px  (default 820)
      text_size       – base font size in px       (default 22)
      sig_max_w       – signature image max width  (default 300)
      sig_max_h       – signature image max height (default 130)
      head_size       – headshot square side px    (default 210)
      logo_max_w      – logo max width px          (default 260)
      logo_max_h      – logo max height px         (default 100)
    """
    # ── layout constants (all user-overridable)
    CW         = int(data.get("canvas_width", 820))
    PAD        = 36
    TEXT_SIZE  = int(data.get("text_size",   22))
    SIG_MAX_W  = int(data.get("sig_max_w",  300))
    SIG_MAX_H  = int(data.get("sig_max_h",  130))
    HEAD_SIZE  = int(data.get("head_size",  210))   # square
    LOGO_MAX_W = int(data.get("logo_max_w", 260))
    LOGO_MAX_H = int(data.get("logo_max_h", 100))
    TEXT_GAP   = max(4, int(TEXT_SIZE * 0.22))   # ~22% leading — tight but readable

    # ── fonts  (name line bold, body regular; sizes scale with TEXT_SIZE)
    fn   = load_font(FONT_REGULAR, TEXT_SIZE)
    fn_b = load_font(FONT_BOLD,    TEXT_SIZE + 2)   # name just slightly larger

    # ── build text lines  (name is printed as-is — no automatic title suffix)
    name  = data.get("name", "Doctor Name").strip()
    title = data.get("title", "Radiologist").strip()
    board = data.get("board_certified", False)
    spec  = data.get("specialization", "Radiology").strip()
    univ  = data.get("university", "University").strip()

    lines = [
        (name,                                                         fn_b),  # bold, no auto-suffix
        (f"Clinical {title}, Expert Radiology™",                      fn),
    ]
    if board:
        lines.append(("Board Certified, Diagnostic Radiology, American Board of Radiology", fn))
    lines.append((f"Fellowship trained in {spec}, {univ}",            fn))

    # ── measure text block height
    dummy = Image.new("RGB", (10, 10))
    draw  = ImageDraw.Draw(dummy)
    line_heights = []
    for text, font in lines:
        bb = draw.textbbox((0, 0), text, font=font)
        line_heights.append(bb[3] - bb[1])
    TEXT_BLOCK_H = sum(line_heights) + TEXT_GAP * (len(lines) - 1)

    # ── signature image
    sig_img_resized = None
    sig_path = find_upload("signature")
    if sig_path:
        sig_raw = open_and_flatten(sig_path)
        sig_raw = apply_enhancements(
            sig_raw,
            contrast=float(data.get("sig_contrast", 1.0)),
            brightness=float(data.get("sig_brightness", 1.0)),
        )
        ratio = min(SIG_MAX_W / sig_raw.width, SIG_MAX_H / sig_raw.height)
        nw, nh = int(sig_raw.width * ratio), int(sig_raw.height * ratio)
        sig_img_resized = sig_raw.resize((nw, nh), Image.LANCZOS)

    # ── headshot (always square)
    head_img = None
    head_path = find_upload("headshot")
    if head_path:
        head_raw = open_and_flatten(head_path)
        head_raw = crop_and_resize(
            head_raw,
            crop=data.get("headshot_crop"),
            target_size=(HEAD_SIZE, HEAD_SIZE),
        )
        head_raw = apply_enhancements(
            head_raw,
            brightness=float(data.get("headshot_brightness", 1.0)),
            saturation=float(data.get("headshot_saturation", 1.0)),
        )
        head_img = head_raw

    # ── logo (default from assets, override via upload)
    logo_img = None
    logo_path = find_upload("logo") or (ASSETS_DIR / "logo.png" if (ASSETS_DIR / "logo.png").exists() else None)
    if logo_path and Path(logo_path).exists():
        logo_raw = open_and_flatten(logo_path)
        ratio = min(LOGO_MAX_W / logo_raw.width, LOGO_MAX_H / logo_raw.height, 1.0)
        lw, lh = int(logo_raw.width * ratio), int(logo_raw.height * ratio)
        logo_img = logo_raw.resize((lw, lh), Image.LANCZOS)

    # ── calculate canvas height
    sig_h    = sig_img_resized.size[1] if sig_img_resized else 0
    bottom_h = max(HEAD_SIZE if head_img else 0, logo_img.size[1] if logo_img else 0)
    canvas_h = PAD + sig_h + 20 + TEXT_BLOCK_H + 30 + bottom_h + PAD

    # ── draw canvas
    canvas = Image.new("RGB", (CW, canvas_h), (255, 255, 255))
    y = PAD

    # Signature image
    if sig_img_resized:
        canvas = paste_rgba(canvas, sig_img_resized, (PAD, y))
        y += sig_img_resized.size[1] + 20

    # Text block
    draw = ImageDraw.Draw(canvas)
    for text, font in lines:
        draw.text((PAD, y), text, font=font, fill=(0, 0, 0))
        bb = draw.textbbox((PAD, y), text, font=font)
        y += (bb[3] - bb[1]) + TEXT_GAP

    y += 28  # gap before bottom section

    # Headshot
    if head_img:
        canvas = paste_rgba(canvas, head_img, (PAD, y))

    # Logo – vertically centred next to headshot
    if logo_img:
        lw, lh = logo_img.size
        logo_x = PAD + (HEAD_SIZE + 40 if head_img else 0)
        logo_y = y + (bottom_h - lh) // 2
        canvas = paste_rgba(canvas, logo_img, (logo_x, logo_y))

    return canvas


# ─── Filename helper ─────────────────────────────────────────────────────────

def make_filename(name: str) -> str:
    """
    Build a safe JPG filename from the doctor's name.
    "Syed Adil Aftab, MD"  →  "Dr.Syed_Adil_Aftab_MD.jpg"
    """
    clean = name.strip()
    clean = re.sub(r",\s*", "_", clean)          # comma + optional space → _
    clean = re.sub(r"\s+", "_", clean)            # remaining spaces → _
    clean = re.sub(r"[^\w._-]", "", clean)        # drop anything unsafe
    clean = re.sub(r"_+", "_", clean).strip("_")  # collapse duplicate _
    return f"Dr.{clean}.jpg"


# Tracks the filename of the most recently generated signature (in-memory)
_last_filename: str = "signature.jpg"


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload/<slot>", methods=["POST"])
def upload(slot: str):
    """slot: signature | headshot | logo"""
    if slot not in ("signature", "headshot", "logo"):
        return jsonify({"error": "Invalid slot"}), 400
    if "file" not in request.files:
        return jsonify({"error": "No file attached"}), 400

    f = request.files["file"]
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED:
        return jsonify({"error": f"File type {ext} not allowed"}), 400

    # Remove any previous file for this slot
    for old_ext in ALLOWED:
        old = UPLOAD_DIR / f"{slot}{old_ext}"
        if old.exists():
            old.unlink()

    save_path = UPLOAD_DIR / f"{slot}{ext}"
    f.save(str(save_path))

    # Return a small preview
    img = Image.open(str(save_path))
    img.thumbnail((400, 400))
    preview_b64 = img_to_b64(img, fmt="JPEG", quality=80)
    return jsonify({"success": True, "preview": preview_b64,
                    "width": img.width, "height": img.height})


@app.route("/api/preview", methods=["POST"])
def preview():
    """Generate a preview image (lower quality, faster)."""
    data = request.json or {}
    try:
        img = build_signature_image(data)
        img.thumbnail((700, 700))
        return jsonify({"image": img_to_b64(img, fmt="JPEG", quality=80)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate", methods=["POST"])
def generate():
    """Generate the final high-quality JPG and return it."""
    global _last_filename
    data = request.json or {}
    try:
        img      = build_signature_image(data)
        filename = make_filename(data.get("name", "Doctor"))
        _last_filename = filename
        out_path = OUTPUT_DIR / filename
        img.save(str(out_path), "JPEG", quality=95, subsampling=0)
        b64 = img_to_b64(img, fmt="JPEG", quality=95)
        return jsonify({"image": b64, "filename": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download")
def download():
    out_path = OUTPUT_DIR / _last_filename
    if not out_path.exists():
        return jsonify({"error": "No signature generated yet"}), 404
    return send_file(str(out_path), as_attachment=True,
                     download_name=_last_filename, mimetype="image/jpeg")


@app.route("/api/status")
def status():
    """Return which asset slots have been uploaded."""
    slots = {}
    for slot in ("signature", "headshot", "logo"):
        p = find_upload(slot)
        slots[slot] = p.name if p else None
    return jsonify(slots)


@app.route("/api/clear/<slot>", methods=["DELETE"])
def clear_slot(slot: str):
    """Remove an uploaded image for a slot."""
    if slot not in ("signature", "headshot", "logo"):
        return jsonify({"error": "Invalid slot"}), 400
    for ext in ALLOWED:
        p = UPLOAD_DIR / f"{slot}{ext}"
        if p.exists():
            p.unlink()
    return jsonify({"success": True})


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n✅  Expert Radiology – Signature Generator")
    print("    Open http://localhost:5050 in your browser\n")
    app.run(host="0.0.0.0", port=5050, debug=False)
