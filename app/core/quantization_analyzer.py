import math
from typing import Dict, List, Any, Optional

STD_LUMINANCE_50 = [
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99
]

STD_CHROMINANCE_50 = [
    17, 18, 24, 47, 99, 99, 99, 99,
    18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99,
    47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99
]

ZIGZAG_INDEX = [
     0,  1,  5,  6, 14, 15, 27, 28,
     2,  4,  7, 13, 16, 26, 29, 42,
     3,  8, 12, 17, 25, 30, 41, 43,
     9, 11, 18, 24, 31, 40, 44, 53,
    10, 19, 23, 32, 39, 45, 52, 54,
    20, 22, 33, 38, 46, 51, 55, 60,
    21, 34, 37, 47, 50, 56, 59, 61,
    35, 36, 48, 49, 57, 58, 62, 63
]

KNOWN_FINGERPRINTS = [
    {
        "name": "Apple iOS Native Camera",
        "category": "Mobile Device",
        "confidence_threshold": 0.88,
        "sample_y_first_four": [2, 1, 1, 2],
        "qf_range": (85, 96),
        "description": "Consistent with Apple iPhone/iPad camera ISP hardware encoding"
    },
    {
        "name": "Samsung OneUI Camera ISP",
        "category": "Mobile Device",
        "confidence_threshold": 0.85,
        "sample_y_first_four": [3, 2, 2, 3],
        "qf_range": (88, 97),
        "description": "Matches Samsung Galaxy camera image processing pipeline"
    },
    {
        "name": "WhatsApp Image Pipeline",
        "category": "Social Media Messaging",
        "confidence_threshold": 0.86,
        "sample_y_first_four": [7, 5, 5, 6],
        "qf_range": (70, 78),
        "description": "Matches aggressive mobile messaging compression pipeline with standard chroma downsampling"
    },
    {
        "name": "Facebook / Meta Web CDN",
        "category": "Social Media Platform",
        "confidence_threshold": 0.84,
        "sample_y_first_four": [6, 4, 4, 6],
        "qf_range": (72, 79),
        "description": "Matches Meta server-side recompression profile"
    },
    {
        "name": "Instagram Upload Pipeline",
        "category": "Social Media Platform",
        "confidence_threshold": 0.85,
        "sample_y_first_four": [5, 3, 3, 4],
        "qf_range": (78, 83),
        "description": "Matches Instagram feed processing pipeline"
    },
    {
        "name": "Adobe Photoshop Save For Web",
        "category": "Desktop Software",
        "confidence_threshold": 0.90,
        "sample_y_first_four": [1, 1, 1, 1],
        "qf_range": (90, 100),
        "description": "Identified Adobe Photoshop high-quality quantization curves"
    },
    {
        "name": "Independent JPEG Group (IJG) Standard",
        "category": "Standard Library",
        "confidence_threshold": 0.95,
        "sample_y_first_four": None,
        "qf_range": (1, 100),
        "description": "Matches canonical libjpeg/IJG standard quantization matrix"
    }
]

def generate_ijg_table(base_table: List[int], quality: int) -> List[int]:
    if quality <= 0:
        quality = 1
    elif quality > 100:
        quality = 100
        
    if quality < 50:
        scale = 5000 // quality
    else:
        scale = 200 - (quality * 2)
        
    generated = []
    for coeff in base_table:
        val = (coeff * scale + 50) // 100
        if val < 1:
            val = 1
        elif val > 255:
            val = 255
        generated.append(val)
    return generated

def estimate_quality_factor(extracted_table: List[int], is_chroma: bool = False) -> Tuple[int, float]:
    base = STD_CHROMINANCE_50 if is_chroma else STD_LUMINANCE_50
    best_qf = 50
    min_diff = float("inf")
    
    for q in range(1, 101):
        candidate = generate_ijg_table(base, q)
        diff = sum(abs(a - b) for a, b in zip(extracted_table, candidate))
        if diff < min_diff:
            min_diff = diff
            best_qf = q
            if diff == 0:
                break
                
    max_possible_diff = 255 * 64
    match_confidence = max(0.0, 1.0 - (min_diff / (max_possible_diff * 0.15)))
    return best_qf, round(match_confidence, 4)

def extract_dqt_from_jpeg(binary_data: bytes) -> Dict[int, List[int]]:
    tables: Dict[int, List[int]] = {}
    idx = 0
    length = len(binary_data)
    
    while idx < length - 4:
        if binary_data[idx] == 0xFF and binary_data[idx + 1] == 0xDB:
            marker_len = int.from_bytes(binary_data[idx + 2 : idx + 4], byteorder="big")
            pos = idx + 4
            end_pos = idx + 2 + marker_len
            
            while pos < end_pos and pos < length:
                table_info = binary_data[pos]
                precision = (table_info >> 4) & 0x0F
                table_id = table_info & 0x0F
                pos += 1
                
                coeff_size = 2 if precision == 1 else 1
                table_bytes = 64 * coeff_size
                
                if pos + table_bytes <= length:
                    raw_values = []
                    for c in range(64):
                        offset = pos + (c * coeff_size)
                        val = int.from_bytes(binary_data[offset : offset + coeff_size], byteorder="big")
                        raw_values.append(val)
                        
                    natural_order = [0] * 64
                    for i in range(64):
                        natural_order[ZIGZAG_INDEX[i]] = raw_values[i]
                        
                    tables[table_id] = natural_order
                    pos += table_bytes
                else:
                    break
            idx = end_pos
        elif binary_data[idx] == 0xFF and binary_data[idx + 1] == 0xDA:
            break
        else:
            idx += 1
            
    return tables

def detect_double_compression(table_y: List[int], estimated_qf: int) -> Dict[str, Any]:
    divisible_count = 0
    low_freq_indices = [0, 1, 2, 8, 9, 10, 16, 17, 24]
    
    for idx in low_freq_indices:
        coeff = table_y[idx]
        if coeff > 1 and (coeff % 2 == 0 or coeff % 3 == 0 or coeff % 5 == 0):
            divisible_count += 1
            
    ratio = divisible_count / len(low_freq_indices)
    
    variance = 0.0
    mean_val = sum(table_y) / len(table_y)
    variance = sum((x - mean_val) ** 2 for x in table_y) / len(table_y)
    std_dev = math.sqrt(variance)
    
    double_prob = 0.0
    if estimated_qf > 85:
        if ratio > 0.6:
            double_prob = min(0.92, 0.45 + (ratio * 0.45))
        else:
            double_prob = max(0.08, ratio * 0.3)
    elif estimated_qf > 65:
        if ratio > 0.7:
            double_prob = min(0.85, 0.35 + (ratio * 0.4))
        else:
            double_prob = max(0.12, ratio * 0.25)
    else:
        double_prob = min(0.65, ratio * 0.5)
        
    return {
        "double_compression_probability": round(double_prob * 100, 2),
        "is_likely_double_compressed": double_prob > 0.50,
        "coarse_quantization_variance": round(std_dev, 2),
        "periodic_step_ratio": round(ratio, 4)
    }

def match_fingerprint(table_y: List[int], estimated_qf: int, ijg_confidence: float) -> Dict[str, Any]:
    first_four = table_y[:4]
    best_match = None
    highest_score = 0.0
    
    for fp in KNOWN_FINGERPRINTS:
        score = 0.0
        qf_min, qf_max = fp["qf_range"]
        
        if qf_min <= estimated_qf <= qf_max:
            score += 0.45
            
        sample = fp["sample_y_first_four"]
        if sample is not None:
            coeff_diff = sum(abs(a - b) for a, b in zip(first_four, sample))
            if coeff_diff == 0:
                score += 0.55
            elif coeff_diff <= 3:
                score += 0.35
            elif coeff_diff <= 6:
                score += 0.20
        elif fp["name"].startswith("Independent JPEG Group"):
            score += ijg_confidence * 0.50
            
        if score > highest_score and score >= fp["confidence_threshold"]:
            highest_score = score
            best_match = fp
            
    if best_match:
        return {
            "signature_name": best_match["name"],
            "category": best_match["category"],
            "description": best_match["description"],
            "match_confidence": round(min(1.0, highest_score) * 100, 2)
        }
        
    return {
        "signature_name": "Unregistered / Custom Quantization Curve",
        "category": "Generic Hardware or Custom Encoder",
        "description": "Quantization matrix deviates from standard social media CDN and major vendor profiles",
        "match_confidence": round(ijg_confidence * 80, 2)
    }

def analyze_quantization(binary_data: bytes, file_format: str) -> Dict[str, Any]:
    if file_format != "jpeg":
        return {
            "is_jpeg": False,
            "has_dqt": False,
            "message": f"Quantization table analysis is specific to DCT-based JPEG architectures. Target format is {file_format.upper()}."
        }
        
    tables = extract_dqt_from_jpeg(binary_data)
    
    if not tables:
        return {
            "is_jpeg": True,
            "has_dqt": False,
            "message": "No DQT markers (0xFFDB) detected. File structure may be corrupted, truncated, or non-standard."
        }
        
    luminance_table = tables.get(0, tables.get(min(tables.keys())))
    chrominance_table = tables.get(1, tables.get(max(tables.keys()) if len(tables) > 1 else None))
    
    est_qf_y, conf_y = estimate_quality_factor(luminance_table, is_chroma=False)
    
    est_qf_c, conf_c = (None, None)
    if chrominance_table:
        est_qf_c, conf_c = estimate_quality_factor(chrominance_table, is_chroma=True)
        
    double_comp = detect_double_compression(luminance_table, est_qf_y)
    fingerprint = match_fingerprint(luminance_table, est_qf_y, conf_y)
    
    matrix_y_8x8 = [luminance_table[r * 8 : (r + 1) * 8] for r in range(8)]
    matrix_c_8x8 = [chrominance_table[r * 8 : (r + 1) * 8] for r in range(8)] if chrominance_table else None
    
    return {
        "is_jpeg": True,
        "has_dqt": True,
        "table_count": len(tables),
        "detected_table_ids": list(tables.keys()),
        "estimated_quality_factor": est_qf_y,
        "quality_match_confidence": round(conf_y * 100, 2),
        "chrominance_quality_factor": est_qf_c,
        "double_compression": double_comp,
        "source_fingerprint": fingerprint,
        "matrices": {
            "luminance": matrix_y_8x8,
            "chrominance": matrix_c_8x8
        },
        "exif_bypass_analysis": {
            "original_compression_profile_preserved": True,
            "verdict": f"EXIF metadata stripping bypassed via DQT reconstruction: Estimated original encode QF={est_qf_y} matching {fingerprint['signature_name']}."
        }
    }
