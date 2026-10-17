import time
import io
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from PIL import Image, ImageDraw

from app.config import (
    APP_NAME,
    APP_SUBTITLE,
    APP_VERSION,
    AUTHOR,
    GITHUB_USER,
    GITHUB_URL,
    MAX_CONTENT_LENGTH,
    BASE_DIR,
)
from app.core.security import (
    validate_upload,
    compute_hashes,
    safe_temp_file,
)
from app.core.exif_extractor import extract_metadata
from app.core.quantization_analyzer import analyze_quantization
from app.core.hex_analyzer import analyze_hex_structure
from app.core.ela_engine import run_error_level_analysis
from app.core.payload_detector import inspect_trailing_payload
from app.core.geospatial_engine import resolve_geospatial_telemetry

app = FastAPI(
    title=f"{APP_NAME} - {APP_SUBTITLE}",
    version=APP_VERSION,
    docs_url="/api/docs",
    redoc_url=None,
)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://unpkg.com; "
            "connect-src 'self' https://*.tile.openstreetmap.org; "
            "frame-ancestors 'none';"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

static_path = BASE_DIR / "app" / "static"
templates_path = BASE_DIR / "app" / "templates"

app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
templates = Jinja2Templates(directory=str(templates_path))
templates.env.cache = None  # تعطيل التخزين المؤقت لتجنب مشاكل مفاتيح بايثون الحديثة

def calculate_overall_risk(
    ela_score: float,
    structural_integrity: float,
    payload_threat: str,
    double_compression_prob: float
) -> dict:
    risk_points = 0.0

    risk_points += (ela_score * 0.35)

    integrity_deficit = max(0.0, 100.0 - structural_integrity)
    risk_points += (integrity_deficit * 0.25)

    if payload_threat == "CRITICAL":
        risk_points += 35.0
    elif payload_threat == "ELEVATED":
        risk_points += 20.0
    elif payload_threat == "MEDIUM":
        risk_points += 10.0

    risk_points += (double_compression_prob * 0.15)
    final_score = round(min(100.0, max(0.0, risk_points)), 1)

    if final_score >= 70.0:
        level = "CRITICAL / HIGH ANOMALY"
        color = "red"
        verdict = "Multiple severe tampering indicators detected: Image integrity is critically compromised with strong evidence of post-capture modification or hidden payload carrier injection."
    elif final_score >= 40.0:
        level = "ELEVATED / SUSPICIOUS"
        color = "amber"
        verdict = "Suspicious forensic signals detected: Inconsistencies observed in compression surface, metadata structure, or secondary quantization layers."
    else:
        level = "LOW / PRISTINE"
        color = "emerald"
        verdict = "High forensic consistency: Structural markers and compression matrices indicate standard authentic capture pipeline."

    return {
        "score": final_score,
        "threat_level": level,
        "color_class": color,
        "executive_verdict": verdict
    }

@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "app_name": APP_NAME,
            "app_subtitle": APP_SUBTITLE,
            "app_version": APP_VERSION,
            "author": AUTHOR,
            "github_user": GITHUB_USER,
            "github_url": GITHUB_URL,
            "max_mb": MAX_CONTENT_LENGTH // (1024 * 1024),
        },
    )

@app.get("/api/health")
async def health_check():
    return {
        "status": "online",
        "service": APP_NAME,
        "version": APP_VERSION,
        "author": AUTHOR,
        "system_time": time.time()
    }

@app.post("/api/analyze")
async def analyze_image_endpoint(
    file: UploadFile = File(...),
    ela_quality: int = Form(95),
    ela_scale: int = Form(15)
):
    start_time = time.perf_counter()

    content = await file.read()
    filename = file.filename or "unknown.bin"
    content_type = file.content_type or "application/octet-stream"

    safe_name, detected_format = validate_upload(filename, content, content_type)
    hashes = compute_hashes(content)

    with safe_temp_file(content, suffix=Path(safe_name).suffix) as _:
        metadata = extract_metadata(content)
        quant_result = analyze_quantization(content, detected_format)
        hex_result = analyze_hex_structure(content, detected_format)
        ela_result = run_error_level_analysis(content, reference_quality=ela_quality, scale_factor=ela_scale)
        payload_result = inspect_trailing_payload(content, detected_format)
        geospatial_result = resolve_geospatial_telemetry(metadata, content)

    double_comp_prob = 0.0
    if quant_result.get("double_compression"):
        double_comp_prob = quant_result["double_compression"].get("double_compression_probability", 0.0)

    risk_evaluation = calculate_overall_risk(
        ela_score=ela_result["tampering_likelihood_score"],
        structural_integrity=hex_result["structural_integrity_score"],
        payload_threat=payload_result["threat_level"],
        double_compression_prob=double_comp_prob
    )

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return JSONResponse({
        "success": True,
        "filename": safe_name,
        "detected_format": detected_format.upper(),
        "file_size": len(content),
        "file_size_formatted": f"{len(content) / 1024:.2f} KB" if len(content) < 1048576 else f"{len(content) / 1048576:.2f} MB",
        "hashes": hashes,
        "processing_time_ms": elapsed_ms,
        "risk_evaluation": risk_evaluation,
        "quantization": quant_result,
        "hex_structure": hex_result,
        "ela": ela_result,
        "payload": payload_result,
        "geospatial": geospatial_result,
        "metadata": metadata
    })

@app.get("/api/sample")
async def get_forensic_sample():
    start_time = time.perf_counter()

    sample_img = Image.new("RGB", (640, 480), color=(22, 33, 50))
    draw = ImageDraw.Draw(sample_img)
    draw.rectangle([60, 60, 580, 420], fill=(30, 41, 59), outline=(56, 189, 248), width=3)
    draw.ellipse([220, 140, 420, 340], fill=(245, 158, 11), outline=(239, 68, 68), width=4)
    draw.line([100, 100, 540, 380], fill=(16, 185, 129), width=2)

    img_stream = io.BytesIO()
    sample_img.save(img_stream, format="JPEG", quality=82)
    clean_bytes = img_stream.getvalue()

    simulated_trailing = b"PK\x03\x04METATRACER_INJECTED_PAYLOAD_TEST_DATA_DEFENSIVE_AUDIT_EXIF_DEEP_FORENSICS_2026"
    test_bytes = clean_bytes + simulated_trailing

    hashes = compute_hashes(test_bytes)
    metadata = extract_metadata(test_bytes)
    quant_result = analyze_quantization(test_bytes, "jpeg")
    hex_result = analyze_hex_structure(test_bytes, "jpeg")
    ela_result = run_error_level_analysis(test_bytes, reference_quality=95, scale_factor=15)
    payload_result = inspect_trailing_payload(test_bytes, "jpeg")
    geospatial_result = resolve_geospatial_telemetry(metadata, test_bytes)

    double_comp_prob = quant_result.get("double_compression", {}).get("double_compression_probability", 0.0)

    risk_evaluation = calculate_overall_risk(
        ela_score=ela_result["tampering_likelihood_score"],
        structural_integrity=hex_result["structural_integrity_score"],
        payload_threat=payload_result["threat_level"],
        double_compression_prob=double_comp_prob
    )

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return JSONResponse({
        "success": True,
        "filename": "sample_forensic_evidence.jpg",
        "detected_format": "JPEG",
        "file_size": len(test_bytes),
        "file_size_formatted": f"{len(test_bytes) / 1024:.2f} KB",
        "hashes": hashes,
        "processing_time_ms": elapsed_ms,
        "risk_evaluation": risk_evaluation,
        "quantization": quant_result,
        "hex_structure": hex_result,
        "ela": ela_result,
        "payload": payload_result,
        "geospatial": geospatial_result,
        "metadata": metadata
    })
