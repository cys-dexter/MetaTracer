import io
import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import sanitize_filename, compute_hashes, detect_magic_format
from app.core.payload_detector import calculate_shannon_entropy, inspect_trailing_payload
from app.core.quantization_analyzer import generate_ijg_table, STD_LUMINANCE_50, estimate_quality_factor
from app.core.ela_engine import run_error_level_analysis
from app.core.geospatial_engine import infer_solar_phase, estimate_cct_and_luminance

client = TestClient(app)

def create_dummy_jpeg(add_trailing_payload: bool = False) -> bytes:
    img = Image.new("RGB", (120, 120), color=(30, 45, 60))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 100, 100], fill=(240, 150, 10), outline=(200, 40, 40))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    data = buffer.getvalue()
    if add_trailing_payload:
        data += b"PK\x03\x04HIDDEN_STEGO_ZIP_ARCHIVE_SIMULATION"
    return data

def test_sanitize_filename_traversal():
    assert sanitize_filename("../../../etc/passwd.jpg") == "passwd.jpg"
    assert sanitize_filename("..\\..\\windows\\system32\\cmd.exe.png") == "cmd.exe.png"
    assert sanitize_filename("safe_image.jpeg") == "safe_image.jpeg"
    assert sanitize_filename("") != ""

def test_magic_byte_detection():
    jpeg_bytes = create_dummy_jpeg()
    assert detect_magic_format(jpeg_bytes) == "jpeg"
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    assert detect_magic_format(png_bytes) == "png"
    corrupt_bytes = b"NOT_AN_IMAGE_FILE_DATA"
    assert detect_magic_format(corrupt_bytes) is None

def test_hashes_computation():
    sample = b"forensic_integrity_test"
    h = compute_hashes(sample)
    assert len(h["md5"]) == 32
    assert len(h["sha1"]) == 40
    assert len(h["sha256"]) == 64

def test_quantization_table_generation():
    table_50 = generate_ijg_table(STD_LUMINANCE_50, 50)
    assert table_50 == STD_LUMINANCE_50
    qf, conf = estimate_quality_factor(table_50, is_chroma=False)
    assert qf == 50
    assert conf >= 0.95

def test_trailing_payload_detection():
    jpeg_clean = create_dummy_jpeg(add_trailing_payload=False)
    res_clean = inspect_trailing_payload(jpeg_clean, "jpeg")
    assert res_clean["has_trailing_payload"] is False
    assert res_clean["payload_size_bytes"] == 0

    jpeg_tainted = create_dummy_jpeg(add_trailing_payload=True)
    res_tainted = inspect_trailing_payload(jpeg_tainted, "jpeg")
    assert res_tainted["has_trailing_payload"] is True
    assert res_tainted["payload_size_bytes"] > 0
    assert any(sig["signature_name"].startswith("ZIP") for sig in res_tainted["detected_signatures"])

def test_shannon_entropy():
    zeros = b"\x00" * 1000
    assert calculate_shannon_entropy(zeros) == 0.0
    all_bytes = bytes(range(256))
    assert calculate_shannon_entropy(all_bytes) == 8.0

def test_ela_execution():
    jpeg_bytes = create_dummy_jpeg()
    ela_res = run_error_level_analysis(jpeg_bytes, reference_quality=95, scale_factor=15)
    assert "tampering_likelihood_score" in ela_res
    assert "mean_error" in ela_res
    assert ela_res["images"]["original"].startswith("data:image/jpeg;base64,")
    assert ela_res["images"]["ela"].startswith("data:image/png;base64,")

def test_solar_phase_inference():
    noon = infer_solar_phase(12)
    assert noon["phase"] == "Solar Midday"
    midnight = infer_solar_phase(2)
    assert midnight["phase"] == "Astronomical Night"

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["service"] == "MetaTracer"

def test_sample_endpoint():
    response = client.get("/api/sample")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "risk_evaluation" in data
    assert "quantization" in data
    assert "ela" in data
    assert "payload" in data
    assert "geospatial" in data

def test_analyze_endpoint():
    jpeg_bytes = create_dummy_jpeg(add_trailing_payload=False)
    files = {"file": ("evidence.jpg", jpeg_bytes, "image/jpeg")}
    response = client.post("/api/analyze", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["detected_format"] == "JPEG"
    assert data["risk_evaluation"]["threat_level"] is not None
