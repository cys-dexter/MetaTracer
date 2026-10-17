import zlib
from typing import Dict, List, Any

JPEG_MARKERS = {
    0xD8: {"name": "SOI", "desc": "Start of Image"},
    0xD9: {"name": "EOI", "desc": "End of Image"},
    0xE0: {"name": "APP0", "desc": "JFIF / Standard Application Header"},
    0xE1: {"name": "APP1", "desc": "EXIF / XMP Metadata Segment"},
    0xE2: {"name": "APP2", "desc": "ICC Profile / FlashPix"},
    0xED: {"name": "APP13", "desc": "Photoshop IRB / IPTC Record"},
    0xEE: {"name": "APP14", "desc": "Adobe DCT Encoding Information"},
    0xDB: {"name": "DQT", "desc": "Define Quantization Table(s)"},
    0xC0: {"name": "SOF0", "desc": "Start of Frame (Baseline DCT)"},
    0xC1: {"name": "SOF1", "desc": "Start of Frame (Extended Sequential)"},
    0xC2: {"name": "SOF2", "desc": "Start of Frame (Progressive DCT)"},
    0xC4: {"name": "DHT", "desc": "Define Huffman Table(s)"},
    0xDA: {"name": "SOS", "desc": "Start of Scan (Compressed Entropy Stream)"},
    0xDD: {"name": "DRI", "desc": "Define Restart Interval"},
    0xFE: {"name": "COM", "desc": "Comment Segment"},
}

def format_hex_dump(data: bytes, start_offset: int = 0, max_bytes: int = 256) -> List[Dict[str, str]]:
    lines = []
    chunk = data[start_offset : start_offset + max_bytes]
    for i in range(0, len(chunk), 16):
        row = chunk[i : i + 16]
        offset_str = f"{(start_offset + i):08X}"
        hex_bytes = " ".join(f"{b:02X}" for b in row)
        ascii_chars = "".join(chr(b) if 32 <= b <= 126 else "." for b in row)
        lines.append({
            "offset": offset_str,
            "hex": hex_bytes.ljust(47),
            "ascii": ascii_chars
        })
    return lines

def analyze_jpeg_structure(binary_data: bytes) -> Dict[str, Any]:
    segments = []
    anomalies = []
    length = len(binary_data)
    idx = 0
    has_soi = False
    has_eoi = False
    sof_count = 0
    dqt_count = 0
    sos_seen = False
    eoi_offset = -1

    if length < 4 or binary_data[0] != 0xFF or binary_data[1] != 0xD8:
        anomalies.append("Missing SOI (0xFFD8) marker at file start. Invalid or damaged JPEG header.")
        return {
            "format": "jpeg",
            "segments": segments,
            "anomalies": anomalies,
            "structural_integrity_score": 10.0,
            "has_soi": False,
            "has_eoi": False,
            "eoi_offset": -1
        }

    has_soi = True
    segments.append({
        "offset": f"{0:08X}",
        "raw_offset": 0,
        "marker": "FFD8",
        "name": "SOI",
        "description": "Start of Image",
        "length": 2,
        "anomalous": False
    })
    idx = 2

    while idx < length - 1:
        if binary_data[idx] == 0xFF:
            marker_code = binary_data[idx + 1]
            if marker_code == 0x00 or marker_code == 0xFF:
                idx += 1
                continue

            marker_info = JPEG_MARKERS.get(marker_code, {
                "name": f"UNK_FF{marker_code:02X}",
                "desc": "Non-standard or private marker"
            })

            if marker_code == 0xD9:
                has_eoi = True
                eoi_offset = idx
                segments.append({
                    "offset": f"{idx:08X}",
                    "raw_offset": idx,
                    "marker": f"FF{marker_code:02X}",
                    "name": marker_info["name"],
                    "description": marker_info["desc"],
                    "length": 2,
                    "anomalous": False
                })
                idx += 2
                break

            if marker_code in (0xC0, 0xC1, 0xC2):
                sof_count += 1
            elif marker_code == 0xDB:
                dqt_count += 1

            if idx + 4 <= length:
                seg_length = int.from_bytes(binary_data[idx + 2 : idx + 4], byteorder="big")
            else:
                anomalies.append(f"Truncated segment header at offset 0x{idx:08X}.")
                break

            is_anomalous = False
            if marker_code == 0xDA:
                sos_seen = True
                segments.append({
                    "offset": f"{idx:08X}",
                    "raw_offset": idx,
                    "marker": f"FF{marker_code:02X}",
                    "name": marker_info["name"],
                    "description": marker_info["desc"],
                    "length": seg_length + 2,
                    "anomalous": False
                })
                scan_start = idx + 2 + seg_length
                eoi_pos = binary_data.find(b"\xFF\xD9", scan_start)
                if eoi_pos != -1:
                    has_eoi = True
                    eoi_offset = eoi_pos
                    segments.append({
                        "offset": f"{eoi_pos:08X}",
                        "raw_offset": eoi_pos,
                        "marker": "FFD9",
                        "name": "EOI",
                        "description": "End of Image",
                        "length": 2,
                        "anomalous": False
                    })
                    idx = eoi_pos + 2
                    break
                else:
                    anomalies.append("Missing terminal EOI (0xFFD9) after entropy scan stream.")
                    idx = length
                    break
            else:
                if seg_length < 2 or idx + 2 + seg_length > length:
                    is_anomalous = True
                    anomalies.append(f"Segment 0xFF{marker_code:02X} has invalid declared length {seg_length} bytes.")

                segments.append({
                    "offset": f"{idx:08X}",
                    "raw_offset": idx,
                    "marker": f"FF{marker_code:02X}",
                    "name": marker_info["name"],
                    "description": marker_info["desc"],
                    "length": seg_length + 2,
                    "anomalous": is_anomalous
                })
                idx += 2 + seg_length
        else:
            idx += 1

    if sof_count > 1:
        anomalies.append(f"Multiple Start-of-Frame markers ({sof_count}) detected; possible polyglot or spliced stream.")
    if dqt_count == 0:
        anomalies.append("Missing DQT marker in JPEG container.")
    if not has_eoi:
        anomalies.append("File truncated: No valid EOI marker detected.")

    integrity_score = 100.0 - (len(anomalies) * 22.0)
    integrity_score = max(5.0, min(100.0, integrity_score))

    return {
        "format": "jpeg",
        "segments": segments,
        "segment_count": len(segments),
        "anomalies": anomalies,
        "has_soi": has_soi,
        "has_eoi": has_eoi,
        "eoi_offset": eoi_offset,
        "structural_integrity_score": round(integrity_score, 1)
    }

def analyze_png_structure(binary_data: bytes) -> Dict[str, Any]:
    chunks = []
    anomalies = []
    length = len(binary_data)
    png_sig = b"\x89PNG\r\n\x1a\n"

    if not binary_data.startswith(png_sig):
        return {
            "format": "png",
            "segments": [],
            "anomalies": ["Missing standard PNG 8-byte magic header."],
            "structural_integrity_score": 0.0,
            "has_soi": False,
            "has_eoi": False,
            "eoi_offset": -1
        }

    chunks.append({
        "offset": f"{0:08X}",
        "raw_offset": 0,
        "marker": "89504E47",
        "name": "PNG_SIG",
        "description": "PNG 8-Byte Magic Header",
        "length": 8,
        "anomalous": False
    })

    idx = 8
    has_ihdr = False
    has_iend = False
    iend_offset = -1

    while idx + 12 <= length:
        data_len = int.from_bytes(binary_data[idx : idx + 4], byteorder="big")
        chunk_type = binary_data[idx + 4 : idx + 8].decode("ascii", errors="replace")
        crc_offset = idx + 8 + data_len

        if crc_offset + 4 > length:
            anomalies.append(f"PNG chunk '{chunk_type}' length {data_len} overflows buffer.")
            break

        chunk_data = binary_data[idx + 4 : crc_offset]
        declared_crc = int.from_bytes(binary_data[crc_offset : crc_offset + 4], byteorder="big")
        actual_crc = zlib.crc32(chunk_data) & 0xFFFFFFFF

        is_anom = False
        if declared_crc != actual_crc:
            is_anom = True
            anomalies.append(f"CRC32 mismatch in chunk '{chunk_type}': expected {actual_crc:08X}, declared {declared_crc:08X}.")

        if chunk_type == "IHDR":
            has_ihdr = True
        elif chunk_type == "IEND":
            has_iend = True
            iend_offset = crc_offset + 4

        chunks.append({
            "offset": f"{idx:08X}",
            "raw_offset": idx,
            "marker": chunk_type,
            "name": chunk_type,
            "description": f"PNG {chunk_type} Chunk",
            "length": data_len + 12,
            "anomalous": is_anom
        })

        idx = crc_offset + 4
        if chunk_type == "IEND":
            break

    if not has_ihdr:
        anomalies.append("Missing mandatory IHDR header chunk.")
    if not has_iend:
        anomalies.append("Missing mandatory IEND trailer chunk.")

    integrity_score = 100.0 - (len(anomalies) * 25.0)
    integrity_score = max(5.0, min(100.0, integrity_score))

    return {
        "format": "png",
        "segments": chunks,
        "segment_count": len(chunks),
        "anomalies": anomalies,
        "has_soi": True,
        "has_eoi": has_iend,
        "eoi_offset": iend_offset,
        "structural_integrity_score": round(integrity_score, 1)
    }

def analyze_hex_structure(binary_data: bytes, file_format: str) -> Dict[str, Any]:
    if file_format == "jpeg":
        struct_res = analyze_jpeg_structure(binary_data)
    elif file_format == "png":
        struct_res = analyze_png_structure(binary_data)
    else:
        struct_res = {
            "format": file_format,
            "segments": [],
            "segment_count": 0,
            "anomalies": [],
            "has_soi": True,
            "has_eoi": True,
            "eoi_offset": len(binary_data),
            "structural_integrity_score": 90.0
        }

    header_dump = format_hex_dump(binary_data, start_offset=0, max_bytes=128)
    tail_offset = max(0, len(binary_data) - 128)
    tail_dump = format_hex_dump(binary_data, start_offset=tail_offset, max_bytes=128)

    struct_res["header_hex_dump"] = header_dump
    struct_res["tail_hex_dump"] = tail_dump
    struct_res["total_byte_size"] = len(binary_data)

    return struct_res
