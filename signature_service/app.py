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
from pathlib import Path
from werkzeug.utils import secure_filename

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"

for d in [UPLOAD_DIR, OUTPUT_DIR, ASSETS_DIR]:
    d.mkdir(exist_ok=True)

# ─── Fonts (Liberation Sans ≈ Arial) ─────────────────────────────────────────
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_BOLD    = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

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
      name, title, board_certified (bool), specialization, university
      sig_contrast, sig_brightness
      headshot_crop   (dict with x,y,width,height or null)
      headshot_brightness, headshot_saturation
      canvas_width  (default 780)
    """
    CW      = int(data.get("canvas_width", 780))
    PAD     = 36
    SIG_MAX_W, SIG_MAX_H = 280, 110
    HEAD_W,  HEAD_H      = 200, 200      # square headshot
    LOGO_MAX_W, LOGO_MAX_H = 240, 90
    TEXT_GAP = 8

    # ── fonts  (Arial 12 ≈ 16 px at 96 DPI; name slightly larger in bold)
    fn   = load_font(FONT_REGULAR, 16)
    fn_b = load_font(FONT_BOLD,    18)
    fn_sm = load_font(FONT_REGULAR, 14)

    # ── build text lines
    name      = data.get("name", "Doctor Name").strip()
    title     = data.get("title", "Radiologist").strip()
    board     = data.get("board_certified", False)
    spec      = data.get("specialization", "Radiology").strip()
    univ      = data.get("university", "University").strip()

    lines = [
        (f"{name}, MD", fn_b),
        (f"Clinical {title}, Expert Radiology™", fn),
    ]
    if board:
        lines.append(("Board Certified, Diagnostic Radiology, American Board of Radiology", fn))
    lines.append((f"Fellowship trained in {spec}, {univ}", fn))

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

    # ── headshot
    head_img = None
    head_path = find_upload("headshot")
    if head_path:
        head_raw = open_and_flatten(head_path)
        head_raw = crop_and_resize(
            head_raw,
            crop=data.get("headshot_crop"),
            target_size=(HEAD_W, HEAD_H),
        )
        head_raw = apply_enhancements(
            head_raw,
            brightness=float(data.get("headshot_brightness", 1.0)),
            saturation=float(data.get("headshot_saturation", 1.0)),
        )
        head_img = head_raw

    # ── logo
    logo_img = None
    logo_path = find_upload("logo") or (ASSETS_DIR / "logo.png" if (ASSETS_DIR / "logo.png").exists() else None)
    if logo_path and Path(logo_path).exists():
        logo_raw = open_and_flatten(logo_path)
        ratio = min(LOGO_MAX_W / logo_raw.width, LOGO_MAX_H / logo_raw.height, 1.0)
        lw, lh = int(logo_raw.width * ratio), int(logo_raw.height * ratio)
        logo_img = logo_raw.resize((lw, lh), Image.LANCZOS)

    # ── calculate canvas height
    sig_h   = sig_img_resized.size[1] if sig_img_resized else 0
    bottom_h = max(HEAD_H if head_img else 0, logo_img.size[1] if logo_img else 0)
    canvas_h = PAD + sig_h + 20 + TEXT_BLOCK_H + 30 + bottom_h + PAD

    # ── draw canvas
    canvas = Image.new("RGB", (CW, canvas_h), (255, 255, 255))

    y = PAD

    # Signature
    if sig_img_resized:
        canvas = paste_rgba(canvas, sig_img_resized, (PAD, y))
        y += sig_img_resized.size[1] + 20

    # Text
    draw = ImageDraw.Draw(canvas)
    for i, (text, font) in enumerate(lines):
        draw.text((PAD, y), text, font=font, fill=(0, 0, 0))
        bb = draw.textbbox((PAD, y), text, font=font)
        y += (bb[3] - bb[1]) + TEXT_GAP

    y += 30  # gap before bottom section

    # Headshot
    if head_img:
        canvas = paste_rgba(canvas, head_img, (PAD, y))

    # Logo – vertically centred next to headshot
    if logo_img:
        lw, lh = logo_img.size
        logo_x = PAD + (HEAD_W + 40 if head_img else 0)
        logo_y = y + (bottom_h - lh) // 2
        canvas = paste_rgba(canvas, logo_img, (logo_x, logo_y))

    return canvas


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
    data = request.json or {}
    try:
        img = build_signature_image(data)
        out_path = OUTPUT_DIR / "signature.jpg"
        img.save(str(out_path), "JPEG", quality=95, subsampling=0)
        b64 = img_to_b64(img, fmt="JPEG", quality=95)
        return jsonify({"image": b64, "filename": "signature.jpg"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download")
def download():
    out_path = OUTPUT_DIR / "signature.jpg"
    if not out_path.exists():
        return jsonify({"error": "No signature generated yet"}), 404
    return send_file(str(out_path), as_attachment=True, download_name="signature.jpg",
                     mimetype="image/jpeg")


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
