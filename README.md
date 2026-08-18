# MD Sign Creator

> **Local microservice** for generating professional doctor signature images for Expert Radiology™.  
> All data stays on your machine — no external API calls, no PHI exposure.

[![Build & Push to GHCR](https://github.com/SethSterling22/MD_Sign_Creator/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/SethSterling22/MD_Sign_Creator/actions/workflows/docker-publish.yml)
![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey?logo=flask)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker)

---

## Overview

MD Sign Creator is a **Flask-based web microservice** that generates standardized physician signature images (`.jpg`) for use in radiology reports, emails, and medical documents.

A physician's signature block contains:

```
[Signature image — with adjustable contrast & brightness]

[Full Name, MD]                          ← bold, user-defined title suffix
Clinical [Specialty], Expert Radiology™
Board Certified, Diagnostic Radiology, American Board of Radiology   ← optional
Fellowship trained in [Specialization], [University]

[Headshot photo — square crop]           [Expert Radiology logo]
```

---

## Features

| Feature | Details |
|---|---|
| **Form-based data entry** | Name, clinical title, specialization, university, board certification toggle |
| **Signature upload** | Drag-and-drop; adjustable contrast & brightness sliders with reset buttons |
| **Headshot upload** | Drag-and-drop with interactive **1:1 square crop** (Cropper.js) and an optional adjustable black border |
| **Color adjustments** | Per-image brightness and saturation controls |
| **Layout controls** | Canvas width, font size, and individual size sliders for every section |
| **Default logo** | Expert Radiology logo auto-loaded from `assets/logo.png` — no prompt needed |
| **Live preview** | One-click server-side preview rendered with Pillow |
| **JPG export** | High-quality (95 q) JPEG download with white background |
| **Fully local** | Zero external requests; suitable for PHI-adjacent workflows |
| **Docker-ready** | Multi-arch image (`amd64` + `arm64`) published to GHCR on every push |

---

## Tech Stack & Dependencies

### Python packages (`requirements.txt`)

| Package | Version | Role |
|---|---|---|
| **Flask** | `>=3.0` | Web framework — routes, template rendering, JSON API |
| **Pillow** | `>=10.0` | Image composition, font rendering, color enhancement, JPEG export |
| **Werkzeug** | `>=3.0` | File upload handling (`secure_filename`) |
| **Gunicorn** | `>=21.0` | Production WSGI server used inside the Docker container |

### Frontend (CDN, no build step)

| Library | Version | Role |
|---|---|---|
| **Cropper.js** | `1.6.1` | Interactive square crop for headshot photos |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves the single-page UI |
| `POST` | `/api/upload/<slot>` | Upload image for `signature`, `headshot`, or `logo` |
| `POST` | `/api/preview` | Generate and return a base64 preview JPEG |
| `POST` | `/api/generate` | Generate final high-quality JPEG, return base64 + save to disk |
| `GET` | `/api/download` | Download the last generated `signature.jpg` |
| `GET` | `/api/status` | Return which image slots are currently filled |
| `DELETE` | `/api/clear/<slot>` | Remove the uploaded image for a slot |

All `POST` endpoints that generate images accept a JSON body:

```json
{
  "name": "Syed Adil Aftab, MD",
  "title": "Neuroradiologist",
  "board_certified": true,
  "specialization": "Neuroradiology",
  "university": "University of Chicago Medical Center",
  "sig_contrast": 1.4,
  "sig_brightness": 1.0,
  "headshot_crop": { "x": 20, "y": 10, "width": 400, "height": 400 },
  "headshot_brightness": 1.0,
  "headshot_saturation": 1.1,
  "headshot_border": true,
  "headshot_border_width": 2,
  "canvas_width": 820,
  "text_size": 22,
  "sig_max_w": 300,
  "sig_max_h": 130,
  "head_size": 210,
  "logo_max_w": 260,
  "logo_max_h": 100
}
```

---

## File Structure

```
MD_Sign_Creator/
│
├── .github/
│   └── workflows/
│       └── docker-publish.yml      # CI/CD — builds & pushes to GHCR
│
├── docker/
│   └── Dockerfile                  # Container definition (python:3.11-slim + gunicorn)
│
├── signature_service/              # Application root (copied into /app in Docker)
│   │
│   ├── app.py                      # Flask app — all routes + image generation logic
│   │
│   ├── templates/
│   │   └── index.html              # Single-page UI (HTML + CSS + vanilla JS)
│   │
│   ├── assets/
│   │   ├── logo.png                # Expert Radiology default logo (auto-loaded)
│   │   └── fonts/
│   │       ├── LiberationSans-Regular.ttf   # Bundled font — works in any environment
│   │       └── LiberationSans-Bold.ttf
│   │
│   ├── uploads/                    # Runtime: user-uploaded images (gitignored)
│   ├── output/                     # Runtime: generated signature.jpg (gitignored)
│   └── run.sh                      # Convenience script for running locally
│
├── requirements.txt                # Python dependencies (Flask, Pillow, Gunicorn…)
├── .gitignore
├── LICENSE
└── README.md
```

---

## Quick Start

### Option A — Run locally (Python)

```bash
# 1. Clone
git clone https://github.com/SethSterling22/MD_Sign_Creator.git
cd MD_Sign_Creator

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server
cd signature_service
python app.py
# → http://localhost:5050
```

Or use the convenience script:

```bash
cd signature_service && ./run.sh
```

### Option B — Docker (from source)

```bash
# Build
docker build -t md-sign-creator -f docker/Dockerfile .

# Run
docker run -d -p 5000:5000 --name md-sign-creator md-sign-creator
# → http://localhost:5000
```

### Option C — Pull from GHCR

```bash
docker pull ghcr.io/sethsterling22/md_sign_creator:latest

docker run -d -p 5000:5000 --name md-sign-creator \
  ghcr.io/sethsterling22/md_sign_creator:latest
# → http://localhost:5000
```

> **Persistent uploads:** to keep uploaded images between container restarts, mount a volume:
> ```bash
> docker run -d -p 5000:5000 \
>   -v $(pwd)/uploads:/app/uploads \
>   -v $(pwd)/output:/app/output \
>   ghcr.io/sethsterling22/md_sign_creator:latest
> ```

---

## CI/CD — GitHub Actions

The workflow at `.github/workflows/docker-publish.yml` triggers on every push to `main`:

```
push to main
     │
     ▼
Checkout → QEMU (multi-arch) → Buildx
     │
     ▼
Login to ghcr.io  (GITHUB_TOKEN — no secrets needed)
     │
     ▼
Build linux/amd64 + linux/arm64
     │
     ├── tag: latest
     ├── tag: main
     └── tag: sha-<commit>
     │
     ▼
Push → ghcr.io/sethsterling22/md_sign_creator
```

Pull requests trigger a **build-only** run (no push) for validation.

---

## Roadmap

- [ ] ClickUp integration — read diplomas and auto-fill credential fields
- [ ] AI-assisted credential extraction from uploaded documents
- [ ] Batch generation for multiple doctors
- [ ] Email signature HTML export (in addition to JPG)

---

## License

See [LICENSE](LICENSE).
