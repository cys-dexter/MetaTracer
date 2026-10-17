import io
import base64
import numpy as np
from PIL import Image, ImageChops, ImageEnhance
from typing import Dict, Any

def run_error_level_analysis(
    image_bytes: bytes,
    reference_quality: int = 95,
    scale_factor: int = 15
) -> Dict[str, Any]:
    with Image.open(io.BytesIO(image_bytes)) as img:
        original = img.convert("RGB")
        orig_width, orig_height = original.size

        max_dimension = 1920
        if orig_width > max_dimension or orig_height > max_dimension:
            original.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        recompressed_stream = io.BytesIO()
        original.save(recompressed_stream, format="JPEG", quality=reference_quality)
        recompressed_stream.seek(0)
        recompressed = Image.open(recompressed_stream).convert("RGB")

        diff = ImageChops.difference(original, recompressed)

        enhancer = ImageEnhance.Brightness(diff)
        amplified = enhancer.enhance(float(scale_factor))

        diff_np = np.array(diff, dtype=np.float32)
        channel_errors = np.mean(diff_np, axis=2)

        mean_error = float(np.mean(channel_errors))
        std_error = float(np.std(channel_errors))
        max_error = float(np.max(channel_errors))

        threshold_suspicious = 12.0
        high_error_pixels = int(np.sum(channel_errors > threshold_suspicious))
        total_pixels = channel_errors.size
        high_error_ratio = (high_error_pixels / total_pixels) if total_pixels > 0 else 0.0

        tampering_score = 0.0
        if mean_error > 8.0 or std_error > 6.0:
            tampering_score += 35.0
        if high_error_ratio > 0.15:
            tampering_score += 40.0
        elif high_error_ratio > 0.05:
            tampering_score += 25.0
        if max_error > 40.0:
            tampering_score += 25.0

        tampering_score = round(min(100.0, max(5.0, tampering_score)), 1)

        norm_errors = np.clip(channel_errors * (255.0 / (max_error if max_error > 0 else 1.0)), 0, 255).astype(np.uint8)
        
        heatmap_rgb = np.zeros((norm_errors.shape[0], norm_errors.shape[1], 3), dtype=np.uint8)
        val = norm_errors.astype(np.float32) / 255.0

        heatmap_rgb[:, :, 0] = np.clip(np.where(val > 0.5, (val - 0.5) * 2.0 * 255, 0), 0, 255).astype(np.uint8)
        heatmap_rgb[:, :, 1] = np.clip(np.where(val <= 0.5, val * 2.0 * 255, (1.0 - val) * 2.0 * 255), 0, 255).astype(np.uint8)
        heatmap_rgb[:, :, 2] = np.clip(np.where(val <= 0.5, (0.5 - val) * 2.0 * 255, 0), 0, 255).astype(np.uint8)

        heatmap_img = Image.fromarray(heatmap_rgb)

        orig_b64_stream = io.BytesIO()
        original.save(orig_b64_stream, format="JPEG", quality=88)
        orig_b64 = base64.b64encode(orig_b64_stream.getvalue()).decode("ascii")

        ela_b64_stream = io.BytesIO()
        amplified.save(ela_b64_stream, format="PNG")
        ela_b64 = base64.b64encode(ela_b64_stream.getvalue()).decode("ascii")

        heat_b64_stream = io.BytesIO()
        heatmap_img.save(heat_b64_stream, format="PNG")
        heat_b64 = base64.b64encode(heat_b64_stream.getvalue()).decode("ascii")

        verdict = "Uniform compression surface: No localized manipulation detected."
        if tampering_score >= 65.0:
            verdict = "High probability of localized tampering, splicing, or composite modifications detected."
        elif tampering_score >= 40.0:
            verdict = "Moderate variance detected; possible selective retouching, text overlay, or re-saving."

        return {
            "mean_error": round(mean_error, 2),
            "max_error": round(max_error, 2),
            "std_dev_error": round(std_error, 2),
            "high_variance_pixel_ratio": round(high_error_ratio * 100, 2),
            "tampering_likelihood_score": tampering_score,
            "forensic_verdict": verdict,
            "dimensions": {"width": orig_width, "height": orig_height},
            "reference_quality": reference_quality,
            "scale_factor": scale_factor,
            "images": {
                "original": f"data:image/jpeg;base64,{orig_b64}",
                "ela": f"data:image/png;base64,{ela_b64}",
                "heatmap": f"data:image/png;base64,{heat_b64}"
            }
        }
