import io
import re
from typing import Dict, Any, Optional, Tuple
from PIL import Image, ExifTags

def convert_to_degrees(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        def to_float(v: Any) -> float:
            if isinstance(v, (int, float)):
                return float(v)
            if hasattr(v, "numerator") and hasattr(v, "denominator"):
                return float(v.numerator) / float(v.denominator) if v.denominator != 0 else 0.0
            if isinstance(v, tuple) and len(v) == 2:
                return float(v[0]) / float(v[1]) if v[1] != 0 else 0.0
            return float(v)

        d = to_float(value[0])
        m = to_float(value[1])
        s = to_float(value[2])
        return d + (m / 60.0) + (s / 3600.0)
    except Exception:
        return None

def parse_gps_data(gps_info: Dict[int, Any]) -> Dict[str, Any]:
    named_gps = {}
    for tag_id, val in gps_info.items():
        tag_name = ExifTags.GPSTAGS.get(tag_id, str(tag_id))
        named_gps[tag_name] = val

    lat_raw = named_gps.get("GPSLatitude")
    lat_ref = named_gps.get("GPSLatitudeRef", "N")
    lon_raw = named_gps.get("GPSLongitude")
    lon_ref = named_gps.get("GPSLongitudeRef", "E")
    alt_raw = named_gps.get("GPSAltitude")
    alt_ref = named_gps.get("GPSAltitudeRef", 0)

    latitude = convert_to_degrees(lat_raw)
    longitude = convert_to_degrees(lon_raw)

    if latitude is not None and lat_ref == "S":
        latitude = -latitude
    if longitude is not None and lon_ref == "W":
        longitude = -longitude

    altitude = None
    if alt_raw is not None:
        try:
            if hasattr(alt_raw, "numerator") and hasattr(alt_raw, "denominator"):
                altitude = float(alt_raw.numerator) / float(alt_raw.denominator)
            elif isinstance(alt_raw, tuple) and len(alt_raw) == 2:
                altitude = float(alt_raw[0]) / float(alt_raw[1])
            else:
                altitude = float(alt_raw)
            if alt_ref == 1:
                altitude = -altitude
        except Exception:
            pass

    has_coords = (latitude is not None and longitude is not None)
    
    timestamp = None
    gps_time = named_gps.get("GPSTimeStamp")
    gps_date = named_gps.get("GPSDateStamp")
    if gps_date and gps_time:
        try:
            h = int(gps_time[0])
            m = int(gps_time[1])
            s = int(gps_time[2])
            timestamp = f"{gps_date} {h:02d}:{m:02d}:{s:02d} UTC"
        except Exception:
            pass

    return {
        "has_gps": has_coords,
        "latitude": round(latitude, 6) if latitude is not None else None,
        "longitude": round(longitude, 6) if longitude is not None else None,
        "altitude_meters": round(altitude, 2) if altitude is not None else None,
        "timestamp": timestamp,
        "raw_tags": {k: str(v) for k, v in named_gps.items()}
    }

def format_exif_value(val: Any) -> Any:
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8", errors="replace").strip("\x00")
        except Exception:
            return f"<{len(val)} bytes>"
    if hasattr(val, "numerator") and hasattr(val, "denominator"):
        return f"{val.numerator}/{val.denominator}" if val.denominator != 1 else str(val.numerator)
    if isinstance(val, tuple):
        return tuple(format_exif_value(x) for x in val)
    return str(val)

def extract_xmp(binary_data: bytes) -> Optional[str]:
    xmp_start = binary_data.find(b"<x:xmpmeta")
    if xmp_start != -1:
        xmp_end = binary_data.find(b"</x:xmpmeta>", xmp_start)
        if xmp_end != -1:
            try:
                return binary_data[xmp_start : xmp_end + 12].decode("utf-8", errors="replace")
            except Exception:
                pass
    return None

def extract_metadata(image_bytes: bytes) -> Dict[str, Any]:
    with Image.open(io.BytesIO(image_bytes)) as img:
        img_format = (img.format or "UNKNOWN").lower()
        width, height = img.size
        color_mode = img.mode

        raw_exif = {}
        gps_data = {"has_gps": False}
        has_exif = False

        if hasattr(img, "_getexif"):
            exif_dict = img._getexif()
            if exif_dict:
                has_exif = True
                for tag_id, value in exif_dict.items():
                    tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                    if tag_name == "GPSInfo" and isinstance(value, dict):
                        gps_data = parse_gps_data(value)
                    else:
                        raw_exif[tag_name] = format_exif_value(value)

        camera_info = {
            "make": raw_exif.get("Make"),
            "model": raw_exif.get("Model"),
            "software": raw_exif.get("Software"),
            "lens_model": raw_exif.get("LensModel"),
            "serial_number": raw_exif.get("BodySerialNumber") or raw_exif.get("SerialNumber"),
        }

        temporal_info = {
            "date_time_original": raw_exif.get("DateTimeOriginal"),
            "date_time_digitized": raw_exif.get("DateTimeDigitized"),
            "date_time_modified": raw_exif.get("DateTime"),
            "subsec_time": raw_exif.get("SubSecTimeOriginal") or raw_exif.get("SubSecTime"),
            "offset_time": raw_exif.get("OffsetTimeOriginal") or raw_exif.get("OffsetTime")
        }

        exposure_info = {
            "exposure_time": raw_exif.get("ExposureTime"),
            "f_number": raw_exif.get("FNumber"),
            "iso": raw_exif.get("ISOSpeedRatings") or raw_exif.get("PhotographicSensitivity"),
            "focal_length": raw_exif.get("FocalLength"),
            "flash": raw_exif.get("Flash"),
            "metering_mode": raw_exif.get("MeteringMode"),
            "white_balance": raw_exif.get("WhiteBalance")
        }

        icc_profile_present = "icc_profile" in img.info
        xmp_block = extract_xmp(image_bytes)

        return {
            "has_exif": has_exif,
            "format": img_format,
            "dimensions": {"width": width, "height": height},
            "color_mode": color_mode,
            "camera": camera_info,
            "temporal": temporal_info,
            "exposure": exposure_info,
            "gps": gps_data,
            "icc_profile_present": icc_profile_present,
            "has_xmp": xmp_block is not None,
            "xmp_snippet": xmp_block[:512] if xmp_block else None,
            "all_tags": raw_exif
        }
