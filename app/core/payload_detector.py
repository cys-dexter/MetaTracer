import math
import re
from typing import Dict, List, Any

KNOWN_SIGNATURES = [
    {"name": "ZIP Archive / Embedded Office Document", "sig": b"PK\x03\x04", "type": "Archive/Document"},
    {"name": "ZIP Empty / End of Central Directory", "sig": b"PK\x05\x06", "type": "Archive"},
    {"name": "RAR Archive", "sig": b"Rar!\x1a\x07", "type": "Archive"},
    {"name": "7-Zip Archive", "sig": b"7z\xbc\xaf\x27\x1c", "type": "Archive"},
    {"name": "GZIP Compressed Stream", "sig": b"\x1f\x8b", "type": "Archive"},
    {"name": "Adobe PDF Document", "sig": b"%PDF-", "type": "Document"},
    {"name": "Windows PE / Executable binary", "sig": b"MZ", "type": "Executable"},
    {"name": "Linux ELF Executable binary", "sig": b"\x7fELF", "type": "Executable"},
    {"name": "PHP Web Script Payload", "sig": b"<?php", "type": "Script"},
    {"name": "HTML / JavaScript Payload", "sig": b"<script", "type": "Script"},
    {"name": "Unix Shell Script", "sig": b"#!/bin", "type": "Script"},
    {"name": "PowerShell Script Trigger", "sig": b"powershell", "type": "Script"}
]

def calculate_shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    length = len(data)
    freq = {}
    for b in data:
        freq[b] = freq.get(b, 0) + 1
    entropy = 0.0
    for count in freq.values():
        p = count / length
        entropy -= p * math.log2(p)
    return round(entropy, 4)

def extract_ascii_strings(data: bytes, min_length: int = 4, max_count: int = 20) -> List[str]:
    pattern = re.compile(rb"[\x20-\x7E]{" + str(min_length).encode() + rb",}")
    matches = pattern.findall(data[:4096])
    strings = []
    for m in matches[:max_count]:
        try:
            strings.append(m.decode("ascii"))
        except UnicodeDecodeError:
            pass
    return strings

def detect_payload_signatures(payload_data: bytes) -> List[Dict[str, str]]:
    detected = []
    check_window = payload_data[:1024]
    for item in KNOWN_SIGNATURES:
        pos = check_window.find(item["sig"])
        if pos != -1:
            detected.append({
                "signature_name": item["name"],
                "category": item["type"],
                "offset_within_payload": f"{pos:04X}"
            })
    return detected

def inspect_trailing_payload(binary_data: bytes, file_format: str) -> Dict[str, Any]:
    file_size = len(binary_data)
    trailer_offset = -1

    if file_format == "jpeg":
        pos = binary_data.rfind(b"\xFF\xD9")
        if pos != -1:
            trailer_offset = pos + 2
    elif file_format == "png":
        pos = binary_data.rfind(b"IEND")
        if pos != -1 and pos + 8 <= file_size:
            trailer_offset = pos + 8
    elif file_format == "gif":
        pos = binary_data.rfind(b"\x3B")
        if pos != -1:
            trailer_offset = pos + 1
    elif file_format == "webp":
        if file_size >= 8 and binary_data[:4] == b"RIFF":
            riff_len = int.from_bytes(binary_data[4:8], byteorder="little")
            declared_size = riff_len + 8
            if file_size > declared_size:
                trailer_offset = declared_size

    has_payload = False
    payload_size = 0
    payload_ratio = 0.0
    entropy = 0.0
    entropy_category = "None"
    signatures_found = []
    extracted_strings = []
    hex_preview = []

    if trailer_offset != -1 and trailer_offset < file_size:
        payload_data = binary_data[trailer_offset:]
        payload_size = len(payload_data)

        if payload_size > 0:
            has_payload = True
            payload_ratio = round((payload_size / file_size) * 100, 2)
            entropy = calculate_shannon_entropy(payload_data)

            if entropy > 7.2:
                entropy_category = "High (Encrypted ciphertext, compressed ZIP/archive, or stego carrier)"
            elif entropy >= 4.0:
                entropy_category = "Moderate (Uncompressed code, structured text, scripts, or PE headers)"
            else:
                entropy_category = "Low (Repetitive patterns, null-byte padding, or sparse data)"

            signatures_found = detect_payload_signatures(payload_data)
            extracted_strings = extract_ascii_strings(payload_data)

            sample = payload_data[:256]
            for i in range(0, len(sample), 16):
                row = sample[i : i + 16]
                offset_str = f"{(trailer_offset + i):08X}"
                hex_str = " ".join(f"{b:02X}" for b in row)
                ascii_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in row)
                hex_preview.append({
                    "offset": offset_str,
                    "hex": hex_str.ljust(47),
                    "ascii": ascii_str
                })

    threat_level = "LOW"
    if has_payload:
        if any(sig["category"] in ("Executable", "Script") for sig in signatures_found) or entropy > 7.3:
            threat_level = "CRITICAL"
        elif signatures_found or payload_size > 1024:
            threat_level = "ELEVATED"
        else:
            threat_level = "MEDIUM"

    return {
        "has_trailing_payload": has_payload,
        "threat_level": threat_level,
        "file_size": file_size,
        "expected_eof_offset": f"{trailer_offset:08X}" if trailer_offset != -1 else "N/A",
        "payload_size_bytes": payload_size,
        "payload_size_formatted": f"{payload_size / 1024:.2f} KB" if payload_size >= 1024 else f"{payload_size} bytes",
        "payload_ratio_percentage": payload_ratio,
        "shannon_entropy": entropy,
        "entropy_assessment": entropy_category,
        "detected_signatures": signatures_found,
        "extracted_strings": extracted_strings,
        "hex_preview": hex_preview
    }
