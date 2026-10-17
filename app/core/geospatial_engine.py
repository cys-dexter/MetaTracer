import io
import math
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

try:
    import pytesseract
except Exception:
    pytesseract = None


TIMEZONE_REGIONS = {
    "-12": {"region": "Baker Island / IDLW", "center_lon": -180.0, "center_lat": 0.0},
    "-11": {"region": "Samoa / Niue", "center_lon": -165.0, "center_lat": -14.0},
    "-10": {"region": "Hawaii-Aleutian (HST)", "center_lon": -157.8, "center_lat": 21.3},
    "-09": {"region": "Alaska (AKST)", "center_lon": -149.9, "center_lat": 61.2},
    "-08": {"region": "US Pacific / Vancouver (PST)", "center_lon": -122.4, "center_lat": 37.7},
    "-07": {"region": "US Mountain / Denver (MST)", "center_lon": -104.9, "center_lat": 39.7},
    "-06": {"region": "US Central / Mexico City (CST)", "center_lon": -87.6, "center_lat": 41.8},
    "-05": {"region": "US Eastern / Bogota / Lima (EST)", "center_lon": -74.0, "center_lat": 40.7},
    "-04": {"region": "Atlantic / Santiago / Caracas", "center_lon": -70.6, "center_lat": -33.4},
    "-03": {"region": "Brazil / Buenos Aires / Greenland", "center_lon": -46.6, "center_lat": -23.5},
    "-02": {"region": "Mid-Atlantic / Fernando de Noronha", "center_lon": -32.4, "center_lat": -3.8},
    "-01": {"region": "Azores / Cape Verde", "center_lon": -25.6, "center_lat": 37.7},
    "+00": {"region": "Western Europe / UK / West Africa (UTC/GMT)", "center_lon": -0.1, "center_lat": 51.5},
    "+01": {"region": "Central Europe / Berlin / Paris / Lagos (CET)", "center_lon": 13.4, "center_lat": 52.5},
    "+02": {"region": "Eastern Europe / Cairo / Johannesburg (EET)", "center_lon": 31.2, "center_lat": 30.0},
    "+03": {"region": "Arabian Peninsula / Moscow / East Africa", "center_lon": 46.7, "center_lat": 24.7},
    "+04": {"region": "Gulf / Dubai / Baku / Tbilisi", "center_lon": 55.3, "center_lat": 25.2},
    "+05": {"region": "Pakistan / Uzbekistan / Maldives", "center_lon": 69.2, "center_lat": 41.3},
    "+06": {"region": "Bangladesh / Kazakhstan / Bhutan", "center_lon": 90.4, "center_lat": 23.8},
    "+07": {"region": "SE Asia / Bangkok / Jakarta / Hanoi", "center_lon": 100.5, "center_lat": 13.7},
    "+08": {"region": "China / Singapore / Perth / Manila", "center_lon": 121.4, "center_lat": 31.2},
    "+09": {"region": "Japan / Tokyo / Seoul", "center_lon": 139.6, "center_lat": 35.6},
    "+10": {"region": "Eastern Australia / Sydney / Brisbane", "center_lon": 151.2, "center_lat": -33.8},
    "+11": {"region": "Solomon Islands / New Caledonia", "center_lon": 166.4, "center_lat": -22.2},
    "+12": {"region": "New Zealand / Auckland / Fiji", "center_lon": 174.7, "center_lat": -36.8},
}

HALF_HOUR_REGIONS = {
    "-09:30": {"region": "Marquesas Islands", "center_lon": -140.0, "center_lat": -9.0},
    "-03:30": {"region": "Newfoundland", "center_lon": -52.7, "center_lat": 47.6},
    "+03:30": {"region": "Iran / Tehran", "center_lon": 51.4, "center_lat": 35.7},
    "+04:30": {"region": "Afghanistan / Kabul", "center_lon": 69.2, "center_lat": 34.5},
    "+05:30": {"region": "India / Sri Lanka", "center_lon": 78.0, "center_lat": 22.0},
    "+05:45": {"region": "Nepal / Kathmandu", "center_lon": 85.3, "center_lat": 27.7},
    "+06:30": {"region": "Myanmar", "center_lon": 96.1, "center_lat": 16.8},
    "+09:30": {"region": "Central Australia / Adelaide", "center_lon": 138.6, "center_lat": -34.9},
}

GAZETTEER = [
    (("amman", "عمان"), 31.9539, 35.9106, "Jordan (Amman)", 40, "city", {"arid"}),
    (("jordan", "الأردن", "الاردن"), 31.24, 36.51, "Jordan", 250, "country", {"arid"}),
    (("cairo", "القاهرة"), 30.0444, 31.2357, "Egypt (Cairo)", 40, "city", {"arid"}),
    (("egypt", "مصر"), 26.82, 30.80, "Egypt", 600, "country", {"arid"}),
    (("dubai", "دبي"), 25.2048, 55.2708, "United Arab Emirates (Dubai)", 40, "city", {"arid"}),
    (("abu dhabi", "أبو ظبي", "ابوظبي"), 24.4539, 54.3773, "United Arab Emirates (Abu Dhabi)", 40, "city", {"arid"}),
    (("uae", "united arab emirates", "الإمارات", "الامارات"), 23.42, 53.85, "United Arab Emirates", 300, "country", {"arid"}),
    (("riyadh", "الرياض"), 24.7136, 46.6753, "Saudi Arabia (Riyadh)", 50, "city", {"arid"}),
    (("jeddah", "جدة"), 21.4858, 39.1925, "Saudi Arabia (Jeddah)", 50, "city", {"arid"}),
    (("saudi arabia", "السعودية"), 23.89, 45.08, "Saudi Arabia", 900, "country", {"arid"}),
    (("doha", "الدوحة"), 25.2769, 51.5200, "Qatar (Doha)", 30, "city", {"arid"}),
    (("qatar", "قطر"), 25.35, 51.18, "Qatar", 80, "country", {"arid"}),
    (("kuwait", "الكويت"), 29.3759, 47.9774, "Kuwait", 80, "country", {"arid"}),
    (("beirut", "بيروت"), 33.8938, 35.5018, "Lebanon (Beirut)", 30, "city", {"temperate"}),
    (("lebanon", "لبنان"), 33.85, 35.86, "Lebanon", 90, "country", {"temperate"}),
    (("damascus", "دمشق"), 33.5138, 36.2765, "Syria (Damascus)", 40, "city", {"arid"}),
    (("baghdad", "بغداد"), 33.3152, 44.3661, "Iraq (Baghdad)", 50, "city", {"arid"}),
    (("istanbul", "إسطنبول", "اسطنبول"), 41.0082, 28.9784, "Turkey (Istanbul)", 50, "city", {"temperate"}),
    (("turkey", "türkiye", "turkiye"), 38.96, 35.24, "Turkey", 500, "country", {"temperate", "arid"}),
    (("london",), 51.5074, -0.1278, "United Kingdom (London)", 40, "city", {"temperate"}),
    (("paris",), 48.8566, 2.3522, "France (Paris)", 40, "city", {"temperate"}),
    (("berlin",), 52.5200, 13.4050, "Germany (Berlin)", 40, "city", {"temperate", "cold"}),
    (("madrid",), 40.4168, -3.7038, "Spain (Madrid)", 40, "city", {"temperate", "arid"}),
    (("rome", "roma"), 41.9028, 12.4964, "Italy (Rome)", 40, "city", {"temperate"}),
    (("moscow",), 55.7558, 37.6173, "Russia (Moscow)", 60, "city", {"cold", "temperate"}),
    (("new york",), 40.7128, -74.0060, "United States (New York)", 50, "city", {"temperate", "cold"}),
    (("los angeles",), 34.0522, -118.2437, "United States (Los Angeles)", 60, "city", {"arid", "temperate"}),
    (("usa", "united states"), 39.80, -98.60, "United States", 2500, "country", {"arid", "temperate", "cold", "tropical"}),
    (("tokyo",), 35.6762, 139.6503, "Japan (Tokyo)", 50, "city", {"temperate"}),
    (("japan",), 36.20, 138.25, "Japan", 600, "country", {"temperate", "cold"}),
    (("beijing",), 39.9042, 116.4074, "China (Beijing)", 60, "city", {"temperate"}),
    (("delhi",), 28.6139, 77.2090, "India (Delhi)", 50, "city", {"arid", "tropical"}),
    (("mumbai",), 19.0760, 72.8777, "India (Mumbai)", 50, "city", {"tropical"}),
    (("sydney",), -33.8688, 151.2093, "Australia (Sydney)", 50, "city", {"temperate"}),
    (("sao paulo", "são paulo"), -23.5505, -46.6333, "Brazil (Sao Paulo)", 60, "city", {"tropical", "temperate"}),
    (("lagos",), 6.5244, 3.3792, "Nigeria (Lagos)", 50, "city", {"tropical"}),
    (("nairobi",), -1.2921, 36.8219, "Kenya (Nairobi)", 40, "city", {"tropical", "temperate"}),
    (("johannesburg",), -26.2041, 28.0473, "South Africa (Johannesburg)", 50, "city", {"temperate", "arid"}),
]

SCRIPT_CLUES = [
    ("Arabic script", r"[\u0600-\u06FF]", 27.0, 40.0, 2800, 0.25),
    ("Hebrew script", r"[\u0590-\u05FF]", 31.5, 35.0, 250, 0.45),
    ("Cyrillic script", r"[\u0400-\u04FF]", 56.0, 45.0, 3500, 0.25),
    ("Japanese kana", r"[\u3040-\u30FF]", 36.2, 138.2, 700, 0.50),
    ("Korean hangul", r"[\uAC00-\uD7AF]", 36.5, 127.8, 400, 0.50),
    ("Thai script", r"[\u0E00-\u0E7F]", 15.3, 101.0, 600, 0.50),
    ("Devanagari script", r"[\u0900-\u097F]", 23.0, 80.0, 1500, 0.35),
    ("Greek script", r"[\u0370-\u03FF]", 39.0, 22.0, 500, 0.45),
    ("Han characters", r"[\u4E00-\u9FFF]", 35.0, 112.0, 2500, 0.20),
]

MACRO_PRIORS = {
    "arid": [
        ("Arabian Peninsula / Levant (arid prior)", 27.0, 42.0, 1800),
        ("North Africa / Sahara (arid prior)", 25.0, 15.0, 2500),
        ("US Southwest / Mexico (arid prior)", 34.0, -108.0, 1800),
        ("Australian interior (arid prior)", -25.0, 134.0, 1800),
    ],
    "temperate": [
        ("Western & Central Europe (temperate prior)", 49.0, 8.0, 1500),
        ("Eastern United States (temperate prior)", 39.0, -80.0, 1500),
        ("East Asia (temperate prior)", 35.0, 115.0, 1800),
    ],
    "tropical": [
        ("Southeast Asia (tropical prior)", 10.0, 105.0, 1800),
        ("Amazon / Central Africa (tropical prior)", -3.0, -55.0, 2500),
    ],
    "cold": [
        ("Northern Europe / Scandinavia (cold prior)", 62.0, 15.0, 1500),
        ("Canada / Alaska (cold prior)", 58.0, -105.0, 2500),
    ],
    "coastal": [
        ("Mediterranean basin (coastal prior)", 36.0, 18.0, 2000),
    ],
}

CLIMATE_TAGS = {"arid", "temperate", "tropical", "cold"}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def lon_diff(a: float, b: float) -> float:
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def extract_header_text(image_bytes: bytes, limit: int = 262144) -> str:
    data = image_bytes[:limit]
    chunks: List[bytes] = []

    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 4 <= len(data) and data[i] == 0xFF:
            marker = data[i + 1]
            if marker in (0xDA, 0xD9):
                break
            if 0xD0 <= marker <= 0xD8 or marker == 0x01:
                i += 2
                continue
            seg_len = int.from_bytes(data[i + 2:i + 4], "big")
            if seg_len < 2:
                break
            if 0xE0 <= marker <= 0xEF or marker == 0xFE:
                chunks.append(data[i + 4:i + 2 + seg_len])
            i += 2 + seg_len
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        i = 8
        while i + 12 <= len(data):
            length = int.from_bytes(data[i:i + 4], "big")
            ctype = data[i + 4:i + 8]
            if ctype == b"IDAT":
                break
            if ctype in (b"tEXt", b"iTXt"):
                chunks.append(data[i + 8:i + 8 + length])
            i += 12 + length
    else:
        chunks.append(data[:65536])

    return b" ".join(chunks).decode("utf-8", errors="ignore").lower()


def ocr_text(image_bytes: bytes) -> str:
    if pytesseract is None:
        return ""
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            gray = img.convert("L")
            gray.thumbnail((1800, 1800))
            for lang in ("eng+ara", None):
                try:
                    if lang:
                        return pytesseract.image_to_string(gray, lang=lang)
                    return pytesseract.image_to_string(gray)
                except Exception:
                    continue
    except Exception:
        pass
    return ""


def parse_capture_hour(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    match = re.search(r"\b(\d{2}):(\d{2}):(\d{2})\b", date_str)
    if match:
        return int(match.group(1))
    return None


def parse_capture_datetime(
    date_str: Optional[str], offset_str: Optional[str]
) -> Tuple[Optional[datetime], Optional[int]]:
    dt = None
    if date_str:
        m = re.search(r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", str(date_str))
        if m:
            try:
                dt = datetime(*[int(x) for x in m.groups()])
            except ValueError:
                dt = None

    offset_min = None
    if offset_str:
        m = re.search(r"([+-])(\d{1,2})(?::?(\d{2}))?", str(offset_str))
        if m:
            total = int(m.group(2)) * 60 + int(m.group(3) or 0)
            if total <= 14 * 60:
                offset_min = -total if m.group(1) == "-" else total
    return dt, offset_min


def solar_elevation(lat: float, lon: float, dt_utc: datetime) -> float:
    doy = dt_utc.timetuple().tm_yday
    hours = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    g = 2.0 * math.pi / 365.0 * (doy - 1 + (hours - 12.0) / 24.0)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )
    true_solar_min = hours * 60.0 + eqtime + 4.0 * lon
    ha = math.radians(true_solar_min / 4.0 - 180.0)
    lat_r = math.radians(lat)
    cos_zen = math.sin(lat_r) * math.sin(decl) + math.cos(lat_r) * math.cos(decl) * math.cos(ha)
    cos_zen = max(-1.0, min(1.0, cos_zen))
    return 90.0 - math.degrees(math.acos(cos_zen))


def parse_exposure_value(exposure_dict: Dict[str, Any]) -> Optional[float]:
    try:
        f_num_val = exposure_dict.get("f_number")
        exp_time_val = exposure_dict.get("exposure_time")
        iso_val = exposure_dict.get("iso")

        if not f_num_val or not exp_time_val or not iso_val:
            return None

        def to_num(x: Any) -> float:
            if isinstance(x, (int, float)):
                return float(x)
            if "/" in str(x):
                p = str(x).split("/")
                return float(p[0]) / float(p[1]) if float(p[1]) != 0 else float(p[0])
            return float(x)

        f_number = to_num(f_num_val)
        exp_time = to_num(exp_time_val)
        iso = to_num(iso_val)

        if f_number <= 0 or exp_time <= 0 or iso <= 0:
            return None

        ev_100 = math.log2((f_number ** 2) / exp_time) - math.log2(iso / 100.0)
        return round(ev_100, 2)
    except Exception:
        return None


def estimate_cct_and_luminance(image_bytes: bytes) -> Tuple[float, float, str]:
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            rgb = img.convert("RGB").resize((64, 64), Image.Resampling.BOX)
            arr = np.array(rgb, dtype=np.float32) / 255.0

        lum8 = float(np.mean(arr @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))) * 255.0
        lin = np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)
        r, g, b = (float(np.mean(lin[:, :, i])) for i in range(3))

        X = 0.4124 * r + 0.3576 * g + 0.1805 * b
        Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        Z = 0.0193 * r + 0.1192 * g + 0.9505 * b
        total = X + Y + Z

        if total < 0.004:
            return 4000.0, round(lum8, 1), "Extremely Low Light / Black"

        x = X / total
        y = Y / total
        denom = 0.1858 - y
        if abs(denom) < 0.0001:
            denom = 0.0001

        n = (x - 0.3320) / denom
        cct = (449.0 * (n ** 3)) + (3525.0 * (n ** 2)) + (6823.3 * n) + 5520.33
        cct = max(1800.0, min(14000.0, cct))

        if cct < 3200:
            ill = "Tungsten / Warm Artificial / Low Golden Sun"
        elif cct < 4500:
            ill = "Halogen / Warm Fluorescent / Early Morning"
        elif cct < 6500:
            ill = "Standard Daylight / Midday Sun / Direct Flash"
        else:
            ill = "Overcast Sky / Open Skylight / Blue Shade"

        return round(cct, 0), round(lum8, 1), ill
    except Exception:
        return 5500.0, 128.0, "Standard Daylight Baseline"


def analyze_scene(image_bytes: bytes) -> Dict[str, Any]:
    empty = {
        "available": False,
        "sky_ratio": 0.0,
        "overcast_ratio": 0.0,
        "vegetation_ratio": 0.0,
        "arid_tone_ratio": 0.0,
        "snow_ratio": 0.0,
        "water_ratio": 0.0,
        "neutral_gray_ratio": 0.0,
        "edge_density": 0.0,
        "mean_saturation": 0.0,
        "indoor_hint": False,
        "climates": [],
        "tags": [],
    }
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            small = img.convert("RGB")
            small.thumbnail((192, 192), Image.Resampling.BOX)
            hsv = np.array(small.convert("HSV"), dtype=np.float32)
    except Exception:
        return empty

    h = hsv[:, :, 0] * 360.0 / 255.0
    s = hsv[:, :, 1] / 255.0
    v = hsv[:, :, 2] / 255.0
    rows = h.shape[0]
    top = slice(0, max(1, int(rows * 0.4)))
    low = slice(int(rows * 0.5), rows)

    blue_sky = (h >= 190) & (h <= 250) & (s > 0.12) & (v > 0.45)
    overcast = (s < 0.10) & (v > 0.70)
    vegetation = (h >= 75) & (h <= 165) & (s > 0.20) & (v > 0.15)
    arid_tone = (h >= 20) & (h <= 50) & (s > 0.20) & (s < 0.65) & (v > 0.45)
    snow = (s < 0.08) & (v > 0.85)
    water = (h >= 170) & (h <= 250) & (s > 0.25) & (v > 0.20)
    gray = (s < 0.12) & (v > 0.25) & (v < 0.75)

    gy, gx = np.gradient(v)
    edge_density = float(np.mean(np.hypot(gx, gy) > 0.08))

    sky_ratio = float(np.mean(blue_sky[top]))
    overcast_ratio = float(np.mean(overcast[top]))
    veg_ratio = float(np.mean(vegetation))
    arid_ratio = float(np.mean(arid_tone))
    snow_low = float(np.mean(snow[low]))
    water_low = float(np.mean(water[low]))
    gray_ratio = float(np.mean(gray))
    sat_mean = float(np.mean(s))

    climates: List[str] = []
    tags: List[str] = []
    if arid_ratio > 0.25 and veg_ratio < 0.15:
        climates.append("arid")
    if veg_ratio > 0.30:
        climates.append("temperate")
        if veg_ratio > 0.45 and sat_mean > 0.40:
            climates.append("tropical")
    if snow_low > 0.25:
        climates.append("cold")
    if water_low > 0.25:
        tags.append("coastal")
    if gray_ratio > 0.35 and edge_density > 0.15:
        tags.append("urban")

    indoor_hint = sky_ratio < 0.02 and overcast_ratio < 0.10 and veg_ratio < 0.10 and water_low < 0.05

    return {
        "available": True,
        "sky_ratio": round(sky_ratio, 3),
        "overcast_ratio": round(overcast_ratio, 3),
        "vegetation_ratio": round(veg_ratio, 3),
        "arid_tone_ratio": round(arid_ratio, 3),
        "snow_ratio": round(snow_low, 3),
        "water_ratio": round(water_low, 3),
        "neutral_gray_ratio": round(gray_ratio, 3),
        "edge_density": round(edge_density, 3),
        "mean_saturation": round(sat_mean, 3),
        "indoor_hint": bool(indoor_hint),
        "climates": climates,
        "tags": tags,
    }


def phase_from_elevation(elev: float) -> Dict[str, str]:
    if elev < -18:
        return {"phase": "Astronomical Night", "sun_elevation": f"{elev:.1f}° (computed)", "lighting_type": "Artificial / Ambient Moonlight"}
    if elev < -12:
        return {"phase": "Astronomical Twilight", "sun_elevation": f"{elev:.1f}° (computed)", "lighting_type": "Faint Ambient Skylight"}
    if elev < -6:
        return {"phase": "Nautical Twilight", "sun_elevation": f"{elev:.1f}° (computed)", "lighting_type": "Diffused Blue Skylight"}
    if elev < 0:
        return {"phase": "Civil Twilight (Blue Hour)", "sun_elevation": f"{elev:.1f}° (computed)", "lighting_type": "Diffused Blue Skylight"}
    if elev < 10:
        return {"phase": "Golden Hour", "sun_elevation": f"{elev:.1f}° (computed)", "lighting_type": "Warm Raking Light"}
    if elev < 35:
        return {"phase": "Morning / Afternoon", "sun_elevation": f"{elev:.1f}° (computed)", "lighting_type": "Direct Sunlight"}
    if elev < 60:
        return {"phase": "High Sun", "sun_elevation": f"{elev:.1f}° (computed)", "lighting_type": "Strong Direct Daylight"}
    return {"phase": "Solar Midday", "sun_elevation": f"{elev:.1f}° (computed)", "lighting_type": "Harsh Vertical Daylight"}


def infer_solar_phase(hour: int) -> Dict[str, str]:
    if 22 <= hour or hour < 5:
        return {"phase": "Astronomical Night", "sun_elevation": "Negative (Below -18°)", "lighting_type": "Artificial / Ambient Moonlight"}
    elif 5 <= hour < 6:
        return {"phase": "Astronomical / Nautical Twilight", "sun_elevation": "Below Horizon (-12° to -6°)", "lighting_type": "Faint Ambient Skylight"}
    elif 6 <= hour < 8:
        return {"phase": "Sunrise / Morning Golden Hour", "sun_elevation": "Low Angle (0° to 15°)", "lighting_type": "Warm Direct Low-Angle Sunlight"}
    elif 8 <= hour < 11:
        return {"phase": "Mid-Morning", "sun_elevation": "Moderate Angle (15° to 45°)", "lighting_type": "Direct Sunlight"}
    elif 11 <= hour < 14:
        return {"phase": "Solar Midday", "sun_elevation": "High Angle (45° to 80°)", "lighting_type": "Harsh Vertical Daylight"}
    elif 14 <= hour < 17:
        return {"phase": "Late Afternoon", "sun_elevation": "Moderate Angle (45° to 15°)", "lighting_type": "Direct Sunlight"}
    elif 17 <= hour < 19:
        return {"phase": "Sunset / Evening Golden Hour", "sun_elevation": "Low Angle (15° to 0°)", "lighting_type": "Warm Raking Light"}
    elif 19 <= hour < 21:
        return {"phase": "Civil / Nautical Dusk (Blue Hour)", "sun_elevation": "Below Horizon (0° to -12°)", "lighting_type": "Diffused Blue Skylight"}
    return {"phase": "Astronomical Night", "sun_elevation": "Below Horizon", "lighting_type": "Night / Artificial"}


def determine_archetype(
    ev: Optional[float],
    cct: float,
    luminance: float,
    solar_phase: str,
    flash_fired: bool,
    scene: Optional[Dict[str, Any]] = None,
) -> str:
    if flash_fired:
        return "Studio / Direct Electronic Strobe"

    if ev is not None:
        if ev >= 13.0:
            return "Direct Outdoor Daylight (Clear Sky)"
        elif ev >= 10.0:
            if "Golden Hour" in solar_phase or cct < 3600:
                return "Outdoor Golden Hour / Sunset"
            return "Outdoor Overcast / Open Shade"
        elif ev >= 6.0:
            return "Deep Shade Outdoor or High-Illumination Interior"
        elif ev >= 3.0:
            if cct < 3500:
                return "Warm Domestic / Commercial Interior"
            return "Commercial / Office Fluorescent Interior"
        return "Night Exterior or Dark Interior"

    if scene and scene.get("available"):
        if scene["sky_ratio"] > 0.15 and luminance > 110.0:
            return "Outdoor Daylight (Sky Detected in Frame)"
        if scene["indoor_hint"] and luminance > 60.0:
            return "Interior Scene (No Sky / Landscape Cues)"

    if luminance > 170.0 and cct >= 5000:
        return "Bright Outdoor Daylight (Estimated from Luminance)"
    elif luminance < 50.0:
        return "Low-Light / Night Scene (Estimated from Luminance)"
    elif cct < 3400:
        return "Warm Interior Illumination (Estimated from CCT)"
    return "Mixed Daylight / Interior Scene"


def match_gazetteer(corpus: str, source: str, city_weight: float, country_weight: float) -> List[Dict[str, Any]]:
    found = []
    for names, lat, lon, region, radius, level, climates in GAZETTEER:
        hit = any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", corpus) for n in names)
        if hit:
            found.append({
                "source": source,
                "label": region,
                "lat": lat,
                "lon": lon,
                "radius": float(radius),
                "weight": city_weight if level == "city" else country_weight,
                "climates": set(climates),
                "flags": [],
            })
    return found


def script_clues(text: str) -> List[Dict[str, Any]]:
    found = []
    for name, pattern, lat, lon, radius, weight in SCRIPT_CLUES:
        if len(re.findall(pattern, text)) >= 5:
            found.append({
                "source": "ocr script",
                "label": f"{name} detected in image text",
                "lat": lat,
                "lon": lon,
                "radius": float(radius),
                "weight": weight,
                "climates": None,
                "flags": [],
            })
    return found


def timezone_candidate(offset_min: Optional[int]) -> Optional[Dict[str, Any]]:
    if offset_min is None:
        return None
    sign = "+" if offset_min >= 0 else "-"
    hh, mm = divmod(abs(offset_min), 60)
    entry = None
    if mm:
        entry = HALF_HOUR_REGIONS.get(f"{sign}{hh:02d}:{mm:02d}")
    else:
        entry = TIMEZONE_REGIONS.get(f"{sign}{hh:02d}")
    if not entry:
        return None
    return {
        "source": "timezone",
        "label": entry["region"],
        "lat": entry["center_lat"],
        "lon": entry["center_lon"],
        "radius": 1000.0,
        "weight": 0.35,
        "climates": None,
        "flags": [],
    }


def biome_priors(scene: Dict[str, Any], offset_min: Optional[int]) -> List[Dict[str, Any]]:
    if not scene.get("available") or scene.get("indoor_hint"):
        return []
    tz_lon = (offset_min / 60.0) * 15.0 if offset_min is not None else None
    keys = list(scene["climates"]) + [t for t in scene["tags"] if t == "coastal"]
    out = []
    for key in keys:
        for label, lat, lon, radius in MACRO_PRIORS.get(key, []):
            if tz_lon is not None and lon_diff(lon, tz_lon) > 40.0:
                continue
            out.append({
                "source": "pixel biome prior",
                "label": label,
                "lat": lat,
                "lon": lon,
                "radius": float(radius),
                "weight": 0.18,
                "climates": {key} if key in CLIMATE_TAGS else None,
                "flags": [],
            })
    return out


def collect_candidates(
    metadata: Dict[str, Any],
    image_bytes: bytes,
    offset_min: Optional[int],
    scene: Dict[str, Any],
) -> List[Dict[str, Any]]:
    embedded = (str(metadata) + " " + extract_header_text(image_bytes)).lower()
    cands = match_gazetteer(embedded, "embedded text", 0.80, 0.55)

    ocr = ocr_text(image_bytes)
    if ocr.strip():
        cands += match_gazetteer(ocr.lower(), "ocr signage", 0.50, 0.35)
        cands += script_clues(ocr)

    tz = timezone_candidate(offset_min)
    if tz:
        cands.append(tz)

    cands += biome_priors(scene, offset_min)
    return cands


def score_candidates(
    cands: List[Dict[str, Any]],
    scene: Dict[str, Any],
    offset_min: Optional[int],
    capture_dt: Optional[datetime],
    luminance: float,
    ev: Optional[float],
    flash_fired: bool,
) -> None:
    tz_lon = (offset_min / 60.0) * 15.0 if offset_min is not None else None
    scene_climates = set(scene.get("climates", []))
    outdoor_bright = (ev is not None and ev >= 11.0) or (
        scene.get("sky_ratio", 0.0) > 0.20 and luminance > 120.0 and not flash_fired
    )
    dt_utc = capture_dt - timedelta(minutes=offset_min) if capture_dt and offset_min is not None else None

    for c in cands:
        s = c["weight"]
        independent = c["source"] not in ("timezone", "pixel biome prior")

        if tz_lon is not None and independent and c["radius"] < 1500:
            if lon_diff(c["lon"], tz_lon) > 37.5:
                s *= 0.4
                c["flags"].append("contradicts_timezone_offset")
            else:
                s = min(0.97, s + 0.05)

        if independent and c["climates"] and scene_climates:
            if c["climates"] & scene_climates:
                s = min(0.97, s + 0.05)
                c["flags"].append("climate_consistent_with_pixels")
            else:
                s *= 0.85
                c["flags"].append("climate_mismatch_with_pixels")

        if dt_utc is not None and c["radius"] < 1500:
            elev = solar_elevation(c["lat"], c["lon"], dt_utc)
            c["sun_elevation_deg"] = round(elev, 1)
            if outdoor_bright and elev < -6.0:
                s *= 0.4
                c["flags"].append("sun_below_horizon_but_scene_is_bright")

        c["score"] = max(0.0, min(0.97, s))


def fuse_candidates(cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cands:
        return None

    for c in cands:
        supporters = [
            o for o in cands
            if o is not c and haversine_km(c["lat"], c["lon"], o["lat"], o["lon"]) <= max(c["radius"], o["radius"])
        ]
        miss = 1.0 - c["score"]
        for o in supporters:
            miss *= 1.0 - o["score"] * 0.8
        c["support"] = supporters
        c["aggregate"] = min(0.92, 1.0 - miss)

    best = max(cands, key=lambda c: (c["aggregate"], -c["radius"]))
    group = [best] + best["support"]
    refine = min(group, key=lambda c: c["radius"])

    alternatives = []
    for c in sorted(cands, key=lambda c: c["aggregate"], reverse=True):
        if c is best or c in best["support"]:
            continue
        if all(haversine_km(c["lat"], c["lon"], a["lat"], a["lon"]) > 300 for a in alternatives):
            alternatives.append(c)
        if len(alternatives) == 3:
            break

    return {
        "lat": refine["lat"],
        "lon": refine["lon"],
        "radius": refine["radius"],
        "confidence": best["aggregate"],
        "label": refine["label"],
        "sources": sorted({c["source"] for c in group}),
        "group": group,
        "alternatives": alternatives,
    }


def reliability_class(conf: float) -> str:
    if conf >= 0.75:
        return "HIGH"
    if conf >= 0.50:
        return "MEDIUM"
    if conf >= 0.30:
        return "LOW"
    return "SPECULATIVE"


def resolve_geospatial_telemetry(metadata: Dict[str, Any], image_bytes: bytes) -> Dict[str, Any]:
    gps_info = metadata.get("gps", {}) or {}
    if gps_info.get("has_gps") and gps_info.get("latitude") is not None and gps_info.get("longitude") is not None:
        lat = gps_info["latitude"]
        lon = gps_info["longitude"]
        alt = gps_info.get("altitude_meters")

        return {
            "mode": "EXIF_DIRECT",
            "has_coordinates": True,
            "latitude": lat,
            "longitude": lon,
            "altitude_meters": alt,
            "uncertainty_radius_km": 0.05,
            "confidence_score": 98.5,
            "reliability": "HIGH",
            "source_type": "Hardware GPS Receiver Satellite Fix",
            "telemetry": {
                "coordinate_display": f"{abs(lat):.4f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.4f}° {'E' if lon >= 0 else 'W'}",
                "timestamp_utc": gps_info.get("timestamp") or "N/A",
                "altitude_display": f"{alt:.1f} m" if alt is not None else "Sea level / Unspecified",
            },
            "evidence": [],
            "forensic_notes": "Coordinates verified directly from embedded EXIF GPS sub-directory without modification.",
        }

    temporal = metadata.get("temporal", {}) or {}
    exposure = metadata.get("exposure", {}) or {}

    capture_date = temporal.get("date_time_original")
    offset_str = temporal.get("offset_time")
    capture_dt, offset_min = parse_capture_datetime(capture_date, offset_str)
    capture_hour = capture_dt.hour if capture_dt else parse_capture_hour(capture_date)

    ev_100 = parse_exposure_value(exposure)
    cct, luminance, illuminant_type = estimate_cct_and_luminance(image_bytes)
    scene = analyze_scene(image_bytes)

    flash_val = str(exposure.get("flash", "")).lower()
    flash_fired = "fired" in flash_val and "not" not in flash_val

    cands = collect_candidates(metadata, image_bytes, offset_min, scene)
    score_candidates(cands, scene, offset_min, capture_dt, luminance, ev_100, flash_fired)
    fused = fuse_candidates(cands)

    solar = infer_solar_phase(capture_hour if capture_hour is not None else 12)
    sun_at_estimate = None
    if fused and capture_dt is not None and offset_min is not None:
        dt_utc = capture_dt - timedelta(minutes=offset_min)
        sun_at_estimate = solar_elevation(fused["lat"], fused["lon"], dt_utc)
        solar = phase_from_elevation(sun_at_estimate)

    archetype = determine_archetype(ev_100, cct, luminance, solar["phase"], flash_fired, scene)

    notes: List[str] = []
    if fused:
        for c in fused["group"]:
            for flag in c["flags"]:
                if flag.startswith(("contradicts", "climate_mismatch", "sun_below")):
                    notes.append(f"{c['label']}: {flag.replace('_', ' ')}")
        strongest = fused["group"][0]["source"] if fused["group"] else "n/a"
        notes.insert(0, f"Estimate fused from {len(fused['group'])} supporting evidence item(s): {', '.join(fused['sources'])}.")
        if fused["confidence"] < 0.30:
            notes.append("Evidence is weak; treat the result as a broad regional prior, not a location.")
    else:
        notes.append("No textual, temporal, or pixel-derived regional evidence was available.")

    if capture_dt is not None and offset_min is not None and scene.get("available"):
        elev_hint = None
        if sun_at_estimate is not None:
            elev_hint = sun_at_estimate
        if elev_hint is not None and elev_hint < -6.0 and luminance > 140.0 and not flash_fired:
            notes.append("Timestamp implies darkness at the estimated location, but the pixels are bright: timestamp or location may be unreliable.")

    has_coords = fused is not None
    lat_v = fused["lat"] if has_coords else None
    lon_v = fused["lon"] if has_coords else None
    conf = fused["confidence"] if has_coords else 0.0

    evidence = [
        {
            "source": c["source"],
            "label": c["label"],
            "weight": round(c["weight"], 2),
            "adjusted_score": round(c["score"], 2),
            "radius_km": c["radius"],
            "flags": c["flags"],
        }
        for c in sorted(cands, key=lambda c: c["score"], reverse=True)[:8]
    ]

    alternatives = (
        [
            {
                "region": a["label"],
                "latitude": a["lat"],
                "longitude": a["lon"],
                "confidence_score": round(a["aggregate"] * 100, 1),
                "uncertainty_radius_km": a["radius"],
            }
            for a in fused["alternatives"]
        ]
        if has_coords
        else []
    )

    return {
        "mode": "INFERENCE_FALLBACK",
        "has_coordinates": has_coords,
        "latitude": round(lat_v, 4) if has_coords else None,
        "longitude": round(lon_v, 4) if has_coords else None,
        "uncertainty_radius_km": fused["radius"] if has_coords else 0.0,
        "confidence_score": round(conf * 100, 1),
        "reliability": reliability_class(conf) if has_coords else "NONE",
        "source_type": (
            "Multi-Evidence Fusion: " + " + ".join(fused["sources"])
            if has_coords
            else "Photometric & Environmental Analysis (No Regional Evidence)"
        ),
        "telemetry": {
            "coordinate_display": (
                f"~{abs(lat_v):.2f}° {'N' if lat_v >= 0 else 'S'}, ~{abs(lon_v):.2f}° {'E' if lon_v >= 0 else 'W'}"
                if has_coords
                else "Unavailable (GPS Stripped & No Regional Clues)"
            ),
            "geographic_region": fused["label"] if has_coords else "Unresolved / GPS Stripped",
            "environmental_archetype": archetype,
            "calculated_exposure_value_ev100": ev_100 if ev_100 is not None else "N/A (Optical tags stripped)",
            "estimated_color_temperature_kelvin": f"{cct:.0f} K",
            "illuminant_category": illuminant_type,
            "solar_phase": solar["phase"],
            "sun_elevation_estimate": solar["sun_elevation"],
            "ambient_lighting_classification": solar["lighting_type"],
            "capture_hour_local": f"{capture_hour:02d}:00" if capture_hour is not None else "Unknown (Timestamp stripped)",
            "timezone_offset_detected": offset_str or "None (EXIF OffsetTime absent)",
            "pixel_scene_profile": scene,
            "pixel_climate_hints": scene.get("climates", []) + scene.get("tags", []),
        },
        "alternative_candidates": alternatives,
        "evidence": evidence,
        "forensic_notes": " ".join(notes),
    }
