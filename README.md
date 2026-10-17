# MetaTracer (ExifDeepForensics)

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-amber.svg)](LICENSE)
[![Security Audited](https://img.shields.io/badge/Security-Hardened-emerald.svg)](#security-architecture--hardening)
[![Author](https://img.shields.io/badge/Author-AHMAD-cyan.svg)](https://github.com/cys-dexter)

**MetaTracer** is a high-assurance, defensive digital media forensics platform engineered to conduct deep binary inspection, tamper detection, and hidden payload extraction on digital image containers. Developed by **AHMAD** ([`cys-dexter`](https://github.com/cys-dexter)), MetaTracer bypasses common forensic evasion tactics—such as social media EXIF stripping and recompression laundering—by directly interrogating the underlying discrete cosine transform (DCT) quantization tables, structural container markers, error level variances, and post-EOF byte distributions.

---

## Key Forensic Capabilities

### 1. Deep Media Forensics (DQT Table & Encoder Fingerprinting)
Social media platforms (e.g., WhatsApp, Meta/Facebook, Instagram, X/Twitter) strip EXIF metadata to protect user privacy or reduce bandwidth. MetaTracer bypasses this barrier by extracting the raw 8x8 Luminance ($Y$) and Chrominance ($C_b/C_r$) Quantization Tables (`0xFFDB` markers) directly from the JPEG binary container:
- **Estimated Quality Factor (QF):** Reconstructs original encode quality using inverse Independent JPEG Group (IJG) matrix algorithms.
- **Encoder Fingerprinting:** Matches quantization curves against known platform signatures (Apple iOS ISP, Samsung OneUI, Adobe Photoshop Save For Web, WhatsApp mobile pipelines, Meta CDN).
- **Double Compression Detection:** Measures coefficient periodicity, factorability, and rounding error histograms to detect whether an image has undergone multiple save cycles.

### 2. Tampering & Splicing Detection (Error Level Analysis - ELA)
- Re-compresses suspect imagery at known reference quality levels (default 95 QF) and calculates the pixel-wise difference matrix $\Delta = |I_{\text{orig}} - I_{\text{recompressed}}|$.
- Amplifies differences (15x-20x) to expose localized regions that compress at different rates due to splicing, cloning, inpainting, or digital tampering.
- Generates dual visualization modes: High-contrast amplified difference map and thermal HSV/RGB error heatmaps.
- Computes forensic statistical indices: Mean Error, Max Error, Standard Deviation, and High-Variance Pixel Surface Ratio.

### 3. Hidden Payload & Steganography Detection
- Parses container structural termination boundaries:
  - **JPEG:** End of Image marker (`0xFFD9`).
  - **PNG:** `IEND` chunk header + 4-byte CRC sequence (`0x49 0x45 0x4E 0x44` + CRC).
  - **GIF:** File trailer byte (`0x3B`).
  - **WebP:** RIFF chunk length boundary check.
- **Trailing Byte Extraction:** Quantifies extra bytes appended after the legitimate EOF marker.
- **Shannon Entropy Calculation:** Computes entropy ($H = -\sum p_i \log_2 p_i$) on trailing data to classify payload density:
  - Low ($H < 3.0$): Zero padding or repetitive text scripts.
  - Moderate ($4.0 \le H \le 6.8$): Plain ASCII scripts, HTML/JS payloads, shell commands.
  - High ($H > 7.2$): Encrypted payloads, compressed ZIP/RAR/7z archives, or steganographic ciphertext.
- **Magic Signature Scanner:** Scans trailing data for embedded archives (`PK\x03\x04`, `7z`, `Rar!`), executables (`MZ`, `\x7fELF`), and scripts (`<?php`, `<script`, `#!/bin`).

### 4. Smart Geospatial & Environmental Fallback Engine
When satellite GPS tags are preserved in EXIF, MetaTracer maps exact latitude, longitude, and altitude with sub-meter precision. When GPS metadata is stripped:
- **Photometric Exposure Value ($EV_{100}$):** Calculates scene illumination from optical tags ($F$-number, Exposure Time, ISO).
- **Correlated Color Temperature (CCT):** Estimates Kelvin rating via McCamy's chromaticity algorithm to categorize scene illuminants (tungsten, fluorescent, daylight, skylight).
- **Solar Phase Analysis:** Maps capture timestamps to solar elevations (Astronomical Dawn, Golden Hour, Solar Midday, Blue Hour, Night).
- **Timezone Longitude Correlation:** Translates `OffsetTime` markers into geographic candidate meridians with clear uncertainty boundaries.

### 5. Structural Hex & Container Integrity Parser
- Validates sequence and byte offsets of container markers: `SOI`, `APP0` (JFIF), `APP1` (EXIF/XMP), `APP2` (ICC), `DQT`, `SOF0/SOF2`, `DHT`, `SOS`, and `EOI`.
- Detects structural anomalies: multiple frame headers (polyglot containers), premature SOS, invalid segment lengths, and corrupted CRCs.
- Renders formatted byte inspection tables (Offset, Hex Bytes, ASCII) for header and trailer boundaries.

---

## Security Architecture & Hardening

MetaTracer is designed according to defensive cybersecurity standards:
- **Path Traversal Prevention:** Uploaded filenames are stripped of all directory delimiters (`../`, `..\`), null bytes (`\x00`), and non-alphanumeric characters, isolating uploads into safe, randomized representations.
- **MIME & Magic Signature Enforcement:** Verifies true binary signatures (`\xFF\xD8\xFF`, `\x89PNG\r\n\x1a\n`, `RIFF...WEBP`) against claimed HTTP Content-Type headers to block polyglot file execution and disguised scripts.
- **Payload & Memory Thresholds:** Hard upload limit enforced at 25MB (`MAX_CONTENT_LENGTH`).
- **Decompression Bomb Protection:** Pillow's `MAX_IMAGE_PIXELS` is strictly constrained to 50 million pixels to prevent Denial-of-Service (DoS) memory exhaustion from malicious decompression bombs.
- **Ephemeral Storage Lifecycle:** Analysis processes execute within scoped context managers (`safe_temp_file`) using cryptographically random temporary file prefixes, guaranteeing immediate deletion upon request completion or abnormal termination.
- **Strict HTTP Security Headers:** Enforces Content Security Policy (`CSP`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection`, and `Referrer-Policy`.
- **Zero-Dependency Core Analysis:** Critical forensic engines (DQT extraction, Shannon entropy calculation, hex structure verification, and mathematical matrix calculations) are implemented natively with pure algorithmic foundations.

---

## Project Structure

```
MetaTracer/
├── .github/
│   └── workflows/
│       └── ci.yml
├── .gitignore
├── Dockerfile
├── LICENSE
├── README.md
├── docker-compose.yml
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── ela_engine.py
│   │   ├── exif_extractor.py
│   │   ├── geospatial_engine.py
│   │   ├── hex_analyzer.py
│   │   ├── payload_detector.py
│   │   ├── quantization_analyzer.py
│   │   └── security.py
│   ├── static/
│   │   ├── css/
│   │   │   └── styles.css
│   │   ├── img/
│   │   │   └── logo.svg
│   │   └── js/
│   │       ├── app.js
│   │       ├── ela_slider.js
│   │       └── hex_viewer.js
│   └── templates/
│       └── index.html
└── tests/
    ├── __init__.py
    └── test_forensics.py
```

---

## Installation & Running

### Prerequisites
- Python 3.10, 3.11, 3.12, or 3.14
- pip (Python Package Installer)
- Git

---

### Linux / macOS Installation (Terminal)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/cys-dexter/MetaTracer.git
   cd MetaTracer
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Launch the MetaTracer forensic server:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

5. **Access the application:**
   Open your browser and navigate to:
   ```
   http://127.0.0.1:8000
   ```

---

### Windows Installation (Command Prompt - CMD)

1. **Clone the repository:**
   ```cmd
   git clone https://github.com/cys-dexter/MetaTracer.git
   cd MetaTracer
   ```

2. **Create and activate a virtual environment:**
   ```cmd
   python -m venv venv
   venv\Scripts\activate.bat
   ```

3. **Install dependencies:**
   ```cmd
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Launch the application:**
   ```cmd
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

5. **Open in Browser:**
   Navigate to `http://127.0.0.1:8000`.

---

### Windows Installation (PowerShell)

1. **Clone the repository:**
   ```powershell
   git clone https://github.com/cys-dexter/MetaTracer.git
   Set-Location MetaTracer
   ```

2. **Create and activate a virtual environment:**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
   *(If script execution is disabled, enable it for the current process: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`)*

3. **Install dependencies:**
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Launch MetaTracer:**
   ```powershell
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

5. **Access the web UI:**
   Navigate to `http://127.0.0.1:8000`.

---

### Docker & Docker Compose Deployment

To deploy MetaTracer in an isolated container:

```bash
docker compose up -d --build
```

View running logs:
```bash
docker compose logs -f
```

Stop the container:
```bash
docker compose down
```

---

## Running the Automated Test Suite

Run the full forensic validation suite using `pytest`:

```bash
pytest tests/ -v
```

The test suite validates:
- Path traversal sanitization and directory traversal denial
- Binary magic byte validation against spoofed headers
- Cryptographic hash generation (MD5, SHA1, SHA256)
- Independent JPEG Group (IJG) quantization matrix calculation
- Trailing hidden payload identification and Shannon entropy calculation
- Error Level Analysis (ELA) difference generation
- Solar elevation and photometric environmental inference
- Health and API analysis endpoints

---

## API Reference

### 1. Health Status
- **Method:** `GET`
- **Endpoint:** `/api/health`
- **Response:**
  ```json
  {
    "status": "online",
    "service": "MetaTracer",
    "version": "1.0.0",
    "author": "AHMAD"
  }
  ```

### 2. Generate Forensic Specimen
- **Method:** `GET`
- **Endpoint:** `/api/sample`
- **Description:** Generates an in-memory synthetic forensic specimen with embedded quantization matrices and an injected payload, running the full analysis pipeline without requiring local file uploads.

### 3. Analyze Image Evidence
- **Method:** `POST`
- **Endpoint:** `/api/analyze`
- **Content-Type:** `multipart/form-data`
- **Parameters:**
  - `file`: Image file binary (JPEG, PNG, WebP, TIFF).
  - `ela_quality`: Reference recompression quality factor (integer 50-100, default 95).
  - `ela_scale`: Error level difference amplification multiplier (integer 5-40, default 15).
- **Response:** Comprehensive forensic JSON document containing risk scores, DQT matrices, ELA imagery, trailing payload data, geospatial telemetry, and structural segment trees.

---

## Author & Attribution

- **Project Lead & Developer:** AHMAD
- **GitHub Handle:** [@cys-dexter](https://github.com/cys-dexter)
- **Repository:** [https://github.com/cys-dexter/MetaTracer](https://github.com/cys-dexter/MetaTracer)
- **Field:** Cybersecurity & Digital Forensics Engineering

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for complete terms.
