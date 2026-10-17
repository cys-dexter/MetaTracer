"""
geo_telemetry.py  (v2)

Photo geolocation by evidence fusion.

What's new vs v1
  1. Full city database (GeoNames SQLite) with population / timezone disambiguation
  2. Stronger OCR: more languages, status-bar pass, domains (.jo), phone prefixes,
     currencies, licence plates, country names
  3. Deeper metadata: EXIF extras, MakerNote strings, XMP, IPTC, embedded thumbnail,
     filename patterns, software -> evidence + integrity (tamper) flags
  +  Network clues: GPSProcessingMethod (GPS vs Wi-Fi/cell fix), operator names in
     status bars of screenshots, radio hints, optional uploader-IP (kept separate)
  4. Optional local vision model (GeoCLIP / StreetCLIP) as one more candidate source
  5. Shadow analysis (object height + shadow length + time -> sun-elevation locus)
  6. Analyst notes as evidence, multi-candidate map hint, reverse-search links
  7. Optional cloud vision (off by default; sends the image to an external API)
  8. Confidence calibration + evaluation helper

CLI
  python geo_telemetry.py build-geonames cities15000.txt geonames.sqlite
  python geo_telemetry.py analyze photo.jpg [--notes "taken in Jordan"]
"""
import html
import io
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageOps

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------------
# Config / weights / calibration
# ----------------------------------------------------------------------------
DEFAULT_WEIGHTS = {
    "tags_city": 0.88,          # IPTC / XMP city fields
    "tags_free_text": 0.60,     # description, comment, keywords, filename
    "analyst": 0.85,
    "embedded_city": 0.80,
    "embedded_country": 0.55,
    "ocr_city": 0.50,
    "ocr_country": 0.35,
    "tld": 0.40,
    "phone_intl": 0.55,
    "phone_local": 0.35,
    "currency": 0.30,
    "plate": 0.25,
    "carrier_top": 0.40,
    "carrier_full": 0.28,
    "timezone": 0.35,
    "biome": 0.18,
    "vision_max": 0.50,
    "cloud_max": 0.60,
    "upload_ip": 0.08,
}


def _load_config() -> Tuple[Dict[str, float], List[List[float]]]:
    weights = dict(DEFAULT_WEIGHTS)
    calib: List[List[float]] = []
    path = os.environ.get("GEO_CONFIG") or os.path.join(HERE, "geo_config.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            weights.update({k: float(v) for k, v in cfg.get("weights", {}).items()})
            calib = [[float(a), float(b)] for a, b in cfg.get("calibration", [])]
        except Exception:
            pass
    return weights, calib


WEIGHTS, CALIBRATION = _load_config()


def W(name: str) -> float:
    return WEIGHTS[name]


def calibrate_confidence(raw: float) -> float:
    """Piecewise-linear map raw -> calibrated using geo_config.json['calibration']."""
    if not CALIBRATION:
        return raw
    pts = sorted(CALIBRATION)
    if raw <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if raw <= x1:
            t = 0.0 if x1 == x0 else (raw - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return pts[-1][1]


# ----------------------------------------------------------------------------
# Static tables
# ----------------------------------------------------------------------------
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

# Built-in fallback gazetteer (used when no GeoNames DB is present, and for country-level names)
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

# code: (name, lat, lon, radius_km, dial_prefix, tld, currency_tokens)
COUNTRIES: Dict[str, Tuple[str, float, float, float, Optional[str], str, Tuple[str, ...]]] = {
    "JO": ("Jordan", 31.24, 36.51, 250, "962", "jo", ("jod", "jd", "د.أ", "دينار اردني", "دينار أردني")),
    "EG": ("Egypt", 26.82, 30.80, 600, "20", "eg", ("egp", "جنيه")),
    "AE": ("United Arab Emirates", 23.42, 53.85, 300, "971", "ae", ("aed", "dirham", "درهم")),
    "SA": ("Saudi Arabia", 23.89, 45.08, 900, "966", "sa", ("sar", "ريال سعودي", "ر.س")),
    "QA": ("Qatar", 25.35, 51.18, 80, "974", "qa", ("qar", "ريال قطري")),
    "KW": ("Kuwait", 29.31, 47.48, 80, "965", "kw", ("kwd", "دينار كويتي")),
    "BH": ("Bahrain", 26.07, 50.56, 40, "973", "bh", ("bhd", "دينار بحريني")),
    "OM": ("Oman", 21.47, 55.98, 450, "968", "om", ("omr", "ريال عماني")),
    "LB": ("Lebanon", 33.85, 35.86, 90, "961", "lb", ("lbp", "ليرة لبنانية")),
    "SY": ("Syria", 34.80, 38.99, 250, "963", "sy", ("syp", "ليرة سورية")),
    "IQ": ("Iraq", 33.22, 43.68, 400, "964", "iq", ("iqd", "دينار عراقي")),
    "PS": ("Palestine", 31.95, 35.23, 80, "970", "ps", ()),
    "IL": ("Israel", 31.05, 34.85, 200, "972", "il", ("ils", "₪", "שקל", "شيكل")),
    "TR": ("Turkey", 38.96, 35.24, 500, "90", "tr", ("try", "₺")),
    "IR": ("Iran", 32.43, 53.69, 700, "98", "ir", ("irr",)),
    "MA": ("Morocco", 31.79, -7.09, 400, "212", "ma", ("درهم مغربي",)),
    "DZ": ("Algeria", 28.03, 1.66, 900, "213", "dz", ("dzd",)),
    "TN": ("Tunisia", 33.89, 9.54, 250, "216", "tn", ("tnd",)),
    "LY": ("Libya", 26.34, 17.23, 800, "218", "ly", ("lyd",)),
    "SD": ("Sudan", 12.86, 30.22, 700, "249", "sd", ()),
    "YE": ("Yemen", 15.55, 48.52, 400, "967", "ye", ("yer",)),
    "GB": ("United Kingdom", 54.0, -2.5, 500, "44", "uk", ("gbp", "£")),
    "IE": ("Ireland", 53.4, -8.2, 200, "353", "ie", ()),
    "FR": ("France", 46.6, 2.2, 500, "33", "fr", ()),
    "DE": ("Germany", 51.2, 10.4, 400, "49", "de", ()),
    "ES": ("Spain", 40.2, -3.6, 500, "34", "es", ()),
    "IT": ("Italy", 42.8, 12.5, 500, "39", "it", ()),
    "NL": ("Netherlands", 52.2, 5.3, 120, "31", "nl", ()),
    "BE": ("Belgium", 50.6, 4.7, 100, "32", "be", ()),
    "CH": ("Switzerland", 46.8, 8.2, 130, "41", "ch", ("chf",)),
    "AT": ("Austria", 47.6, 14.1, 200, "43", "at", ()),
    "SE": ("Sweden", 62.0, 15.0, 700, "46", "se", ("sek",)),
    "NO": ("Norway", 61.0, 9.0, 700, "47", "no", ("nok",)),
    "DK": ("Denmark", 56.0, 10.0, 200, "45", "dk", ("dkk",)),
    "FI": ("Finland", 64.0, 26.0, 600, "358", "fi", ()),
    "PL": ("Poland", 52.0, 19.4, 350, "48", "pl", ("pln", "zł")),
    "GR": ("Greece", 39.0, 22.0, 400, "30", "gr", ()),
    "RU": ("Russia", 61.5, 90.0, 3500, "7", "ru", ("rub", "₽")),
    "UA": ("Ukraine", 49.0, 31.4, 500, "380", "ua", ("uah", "₴")),
    "US": ("United States", 39.8, -98.6, 2500, None, "us", ()),
    "CA": ("Canada", 56.0, -96.0, 2500, None, "ca", ("cad",)),
    "MX": ("Mexico", 23.6, -102.5, 1000, "52", "mx", ("mxn",)),
    "BR": ("Brazil", -10.0, -52.0, 2000, "55", "br", ("brl", "r$")),
    "AR": ("Argentina", -34.0, -64.0, 1200, "54", "ar", ("ars",)),
    "IN": ("India", 22.0, 79.0, 1400, "91", "in", ("inr", "₹")),
    "PK": ("Pakistan", 30.0, 70.0, 700, "92", "pk", ("pkr",)),
    "BD": ("Bangladesh", 23.8, 90.4, 250, "880", "bd", ("bdt", "৳")),
    "CN": ("China", 35.0, 103.0, 2000, "86", "cn", ("cny", "rmb", "人民币")),
    "JP": ("Japan", 36.2, 138.2, 600, "81", "jp", ("jpy", "円")),
    "KR": ("South Korea", 36.5, 127.8, 300, "82", "kr", ("krw", "₩")),
    "TH": ("Thailand", 15.3, 101.0, 600, "66", "th", ("thb", "฿")),
    "VN": ("Vietnam", 16.0, 107.8, 700, "84", "vn", ("vnd", "₫")),
    "ID": ("Indonesia", -2.5, 118.0, 2000, "62", "id", ("idr",)),
    "MY": ("Malaysia", 4.2, 102.0, 500, "60", "my", ("myr",)),
    "SG": ("Singapore", 1.35, 103.8, 25, "65", "sg", ("sgd",)),
    "PH": ("Philippines", 12.9, 121.8, 700, "63", "ph", ("php", "₱")),
    "AU": ("Australia", -25.0, 134.0, 2000, "61", "au", ("aud",)),
    "NZ": ("New Zealand", -41.0, 174.0, 700, "64", "nz", ("nzd",)),
    "ZA": ("South Africa", -29.0, 24.0, 700, "27", "za", ("zar",)),
    "NG": ("Nigeria", 9.1, 8.7, 500, "234", "ng", ("ngn", "₦")),
    "KE": ("Kenya", 0.2, 37.9, 400, "254", "ke", ("kes",)),
    "ET": ("Ethiopia", 9.1, 40.5, 500, "251", "et", ("etb",)),
}

DIAL_TO_CC = {v[4]: k for k, v in COUNTRIES.items() if v[4]}
TLD_TO_CC = {v[5]: k for k, v in COUNTRIES.items()}
COUNTRY_NAME_TO_CC = {v[0].lower(): k for k, v in COUNTRIES.items()}
COUNTRY_NAME_TO_CC.update({"uk": "GB", "great britain": "GB", "england": "GB", "usa": "US",
                           "uae": "AE", "emirates": "AE", "korea": "KR", "türkiye": "TR", "turkiye": "TR"})

# Mobile operators -> countries. Non-ASCII names are only trusted inside the status-bar band.
CARRIERS: Dict[str, List[str]] = {
    "zain": ["JO", "KW", "SA", "IQ", "BH", "SD"], "umniah": ["JO"], "orange": ["JO", "EG", "FR", "ES", "PL", "BE"],
    "stc": ["SA", "KW", "BH"], "mobily": ["SA"], "etisalat": ["AE", "EG"], "ooredoo": ["QA", "KW", "OM", "IQ"],
    "omantel": ["OM"], "batelco": ["BH"], "jawwal": ["PS"], "turkcell": ["TR"], "turk telekom": ["TR"],
    "vodafone": ["GB", "DE", "IT", "ES", "EG", "TR", "IE"], "telstra": ["AU"], "optus": ["AU"],
    "verizon": ["US"], "at&t": ["US"], "t-mobile": ["US", "DE"], "airtel": ["IN", "NG", "KE"], "jio": ["IN"],
    "mtn": ["NG", "ZA"], "safaricom": ["KE"], "docomo": ["JP"], "softbank": ["JP"], "sk telecom": ["KR"],
    "china mobile": ["CN"], "dtac": ["TH"], "viettel": ["VN"], "telkomsel": ["ID"], "singtel": ["SG"],
    "megafon": ["RU"], "beeline": ["RU"], "kyivstar": ["UA"], "bouygues": ["FR"], "sfr": ["FR"],
    "زين": ["JO", "KW", "SA", "IQ", "BH"], "امنية": ["JO"], "اورانج": ["JO", "EG"], "اتصالات": ["AE", "EG"],
    "موبايلي": ["SA"], "جوال": ["PS"], "اريدو": ["QA", "KW", "OM"],
}

LICENCE_PLATES = [
    ("GB plate format", r"\b[A-Z]{2}\d{2}\s?[A-Z]{3}\b", "GB"),
    ("FR plate format", r"\b[A-Z]{2}-\d{3}-[A-Z]{2}\b", "FR"),
    ("IT plate format", r"\b[A-Z]{2}\s?\d{3}\s?[A-Z]{2}\b", "IT"),
    ("ES plate format", r"\b\d{4}\s?[BCDFGHJKLMNPRSTVWXYZ]{3}\b", "ES"),
    ("DE plate format", r"\b[A-ZÄÖÜ]{1,3}-[A-Z]{1,2}\s?\d{1,4}[EH]?\b", "DE"),
]

STOP_NAMES = {
    "reading", "orange", "mobile", "nice", "bath", "hull", "normal", "center", "central", "union", "market",
    "park", "city", "east", "west", "north", "south", "royal", "victoria", "george", "america", "santa",
    "home", "world", "global", "grand", "bonus", "mission", "chance", "paradise", "texas", "salem", "lima",
    "turkey", "jordan", "georgia", "india", "china", "japan", "egypt", "kuwait", "qatar", "lebanon", "syria",
}

REVERSE_SEARCH_LINKS = {
    "Google Lens": "https://lens.google.com/",
    "Yandex Images": "https://yandex.com/images/",
    "TinEye": "https://tineye.com/",
    "Bing Visual Search": "https://www.bing.com/visualsearch",
}


# ----------------------------------------------------------------------------
# Basic math / text helpers
# ----------------------------------------------------------------------------
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def lon_diff(a: float, b: float) -> float:
    return abs(((a - b + 180.0) % 360.0) - 180.0)


_AR_MAP = str.maketrans({"ى": "ي", "ة": "ه"})


def norm(s: str) -> str:
    """Accent/diacritic-insensitive lowercase form used for city-name matching."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.lower().translate(_AR_MAP).replace("ـ", "")


TOKEN_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


def mk(source: str, label: str, lat: float, lon: float, radius: float, weight: float,
       climates: Optional[set] = None) -> Dict[str, Any]:
    return {
        "source": source, "label": label, "lat": float(lat), "lon": float(lon),
        "radius": float(radius), "weight": float(weight),
        "climates": set(climates) if climates else None, "flags": [],
    }


def country_candidate(cc: str, source: str, weight: float, note: str = "") -> Optional[Dict[str, Any]]:
    e = COUNTRIES.get(cc)
    if not e:
        return None
    c = mk(source, e[0] + (f" ({note})" if note else ""), e[1], e[2], e[3], weight)
    return c


# ----------------------------------------------------------------------------
# (1) City database (GeoNames)
# ----------------------------------------------------------------------------
def build_geonames_db(txt_path: str, db_path: str) -> int:
    """Convert a GeoNames dump (cities15000.txt / cities5000.txt) into a SQLite file."""
    if os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
    con.executescript(
        "CREATE TABLE cities(id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL, cc TEXT, pop INTEGER, tz TEXT);"
        "CREATE TABLE aliases(alias TEXT, id INTEGER);"
    )
    n = 0
    with open(txt_path, encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 18:
                continue
            gid = int(p[0])
            names = {norm(x) for x in [p[1], p[2]] + (p[3].split(",") if p[3] else []) if x}
            names = {x for x in names if 3 <= len(x) <= 40 and not re.search(r"\d", x)}
            con.execute("INSERT INTO cities VALUES (?,?,?,?,?,?,?)",
                        (gid, p[1], float(p[4]), float(p[5]), p[8], int(p[14] or 0), p[17]))
            con.executemany("INSERT INTO aliases VALUES (?,?)", [(a, gid) for a in names])
            n += 1
    con.execute("CREATE INDEX idx_alias ON aliases(alias)")
    con.commit()
    con.close()
    return n


class CityIndex:
    def __init__(self, db_path: str):
        self.rows: Dict[int, Tuple] = {}
        self.alias: Dict[str, List[int]] = defaultdict(list)
        con = sqlite3.connect(db_path)
        for r in con.execute("SELECT id,name,lat,lon,cc,pop,tz FROM cities"):
            self.rows[r[0]] = r
        for a, i in con.execute("SELECT alias,id FROM aliases"):
            self.alias[a].append(i)
        con.close()


_CITY_INDEX: Any = None


def get_city_index() -> Optional[CityIndex]:
    global _CITY_INDEX
    if _CITY_INDEX is None:
        path = os.environ.get("GEONAMES_DB") or os.path.join(HERE, "geonames.sqlite")
        try:
            _CITY_INDEX = CityIndex(path) if os.path.exists(path) else False
        except Exception:
            _CITY_INDEX = False
    return _CITY_INDEX or None


_TZ_CACHE: Dict[Tuple[str, int, int], Optional[int]] = {}


def tz_offset_minutes(tz: str, when: Optional[datetime]) -> Optional[int]:
    if not tz or ZoneInfo is None:
        return None
    when = when or datetime.now()
    key = (tz, when.year, when.month)
    if key not in _TZ_CACHE:
        try:
            off = datetime(when.year, when.month, 15, 12, tzinfo=ZoneInfo(tz)).utcoffset()
            _TZ_CACHE[key] = int(off.total_seconds() // 60)
        except Exception:
            _TZ_CACHE[key] = None
    return _TZ_CACHE[key]


def _pick_row(rows: List[Tuple], offset_min: Optional[int], when: Optional[datetime]) -> Tuple:
    def score(r):
        s = math.log10(r[5] + 1)
        if offset_min is not None and tz_offset_minutes(r[6], when) == offset_min:
            s += 3.0
        return s
    return max(rows, key=score)


def match_cities(text: str, source: str, weight: float, idx: Optional[CityIndex],
                 offset_min: Optional[int], when: Optional[datetime],
                 strict: bool, max_hits: int = 12) -> List[Dict[str, Any]]:
    """Match 1-3 word n-grams against the GeoNames alias index.
    strict=True (OCR / free text): skip short/common names and tiny towns to limit false positives."""
    if not idx or not text:
        return []
    toks = TOKEN_RE.findall(norm(text))
    used = [False] * len(toks)
    out: List[Dict[str, Any]] = []
    for n in (3, 2, 1):
        for i in range(len(toks) - n + 1):
            if any(used[i:i + n]):
                continue
            key = " ".join(toks[i:i + n])
            ids = idx.alias.get(key)
            if not ids:
                continue
            if strict and n == 1 and (len(key) < 5 or key in STOP_NAMES):
                continue
            rows = [idx.rows[j] for j in ids]
            best = _pick_row(rows, offset_min, when)
            if strict and best[5] < (150000 if n == 1 else 20000):
                continue
            rivals = [r for r in rows if r is not best and r[5] >= 0.3 * best[5]
                      and haversine_km(best[2], best[3], r[2], r[3]) > 150]
            w = weight * (0.65 if rivals else 1.0)
            pop = best[5]
            radius = 35.0 if pop > 1_000_000 else 25.0 if pop > 200_000 else 15.0
            c = mk(source, f"{best[1]}, {best[4]}", best[2], best[3], radius, w)
            c["flags"].append(f"geonames_pop_{pop}")
            if rivals:
                c["flags"].append("ambiguous_name_" + str(len(rivals) + 1) + "_places")
            if offset_min is not None and tz_offset_minutes(best[6], when) == offset_min:
                c["flags"].append("city_timezone_matches_offset")
            for k in range(i, i + n):
                used[k] = True
            out.append(c)
            if len(out) >= max_hits:
                return out
    return out


# ----------------------------------------------------------------------------
# (3) Deep metadata: EXIF extras, MakerNote, XMP, IPTC, thumbnail, filename
# ----------------------------------------------------------------------------
def jpeg_segments(data: bytes):
    if data[:2] != b"\xff\xd8":
        return
    i = 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        m = data[i + 1]
        if m in (0xDA, 0xD9):
            break
        if 0xD0 <= m <= 0xD8 or m == 0x01:
            i += 2
            continue
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if seg_len < 2:
            break
        yield m, data[i + 4:i + 2 + seg_len]
        i += 2 + seg_len


def _dec(b: bytes) -> str:
    try:
        return b.decode("utf-8").strip("\x00 ")
    except UnicodeDecodeError:
        return b.decode("latin-1", errors="ignore").strip("\x00 ")


IPTC_NAMES = {5: "object_name", 25: "keywords", 90: "city", 92: "sublocation", 95: "state",
              100: "country_code", 101: "country", 120: "caption"}


def _iptc_records(data: bytes) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    i = 0
    while i + 5 <= len(data) and data[i] == 0x1C:
        rec, ds = data[i + 1], data[i + 2]
        size = int.from_bytes(data[i + 3:i + 5], "big")
        i += 5
        if size & 0x8000:
            break
        val = data[i:i + size]
        i += size
        if rec == 2 and ds in IPTC_NAMES:
            txt = _dec(val)
            if ds == 25:
                out.setdefault("keywords", []).append(txt)
            else:
                out[IPTC_NAMES[ds]] = txt
    return out


def parse_iptc(app13: bytes) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not app13.startswith(b"Photoshop 3.0\x00"):
        return out
    p = 14
    while p + 12 <= len(app13) and app13[p:p + 4] == b"8BIM":
        rid = int.from_bytes(app13[p + 4:p + 6], "big")
        nlen = app13[p + 6]
        q = p + 7 + nlen
        if (1 + nlen) % 2:
            q += 1
        size = int.from_bytes(app13[q:q + 4], "big")
        q += 4
        if rid == 0x0404:
            out.update(_iptc_records(app13[q:q + size]))
        p = q + size + (size % 2)
    return out


def _xmp_val(xmp: str, tag: str) -> Optional[str]:
    m = re.search(re.escape(tag) + r'\s*=\s*"([^"]*)"', xmp)
    if m:
        return html.unescape(m.group(1)).strip() or None
    m = re.search(r"<" + re.escape(tag) + r"[^>]*>(.*?)</" + re.escape(tag) + ">", xmp, re.S)
    if m:
        v = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        return re.sub(r"\s+", " ", v) or None
    return None


def _xmp_coord(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    m = re.match(r"\s*(\d+(?:\.\d+)?)(?:[,:](\d+(?:\.\d+)?))?(?:[,:](\d+(?:\.\d+)?))?\s*([NSEW])\s*$", s)
    if not m:
        return None
    v = float(m.group(1)) + float(m.group(2) or 0) / 60 + float(m.group(3) or 0) / 3600
    return -v if m.group(4) in "SW" else v


def parse_xmp(raw: bytes) -> Dict[str, Any]:
    a = raw.find(b"<x:xmpmeta")
    if a < 0:
        return {}
    b = raw.find(b"</x:xmpmeta>", a)
    xmp = raw[a:(b + 12 if b > 0 else a + 200000)].decode("utf-8", errors="ignore")
    out: Dict[str, Any] = {"present": True}
    fields = {"city": "photoshop:City", "state": "photoshop:State", "country": "photoshop:Country",
              "country_code": "Iptc4xmpCore:CountryCode", "location": "Iptc4xmpCore:Location",
              "description": "dc:description", "title": "dc:title", "subject": "dc:subject",
              "creator_tool": "xmp:CreatorTool"}
    for k, tag in fields.items():
        v = _xmp_val(xmp, tag)
        if v:
            out[k] = v
    lat = _xmp_coord(_xmp_val(xmp, "exif:GPSLatitude"))
    lon = _xmp_coord(_xmp_val(xmp, "exif:GPSLongitude"))
    if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180:
        out["gps"] = (lat, lon)
    agents = [x[0] or x[1] for x in re.findall(r'stEvt:softwareAgent="([^"]+)"|<stEvt:softwareAgent>([^<]+)<', xmp)]
    if agents:
        out["edit_agents"] = sorted(set(agents))
    return out


def _to_text(v: Any) -> str:
    if isinstance(v, bytes):
        if v[:8] in (b"ASCII\x00\x00\x00", b"UNICODE\x00", b"JIS\x00\x00\x00\x00\x00"):
            body = v[8:]
            return (body.decode("utf-16", errors="ignore") if v[:7] == b"UNICODE" else _dec(body)).strip()
        return _dec(v)
    return str(v).strip()


def read_exif_fields(image_bytes: bytes) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            out["format"] = img.format
            out["size"] = img.size
            ex = img.getexif()
            for tag, name in {0x010F: "make", 0x0110: "model", 0x0131: "software", 0x010E: "description",
                              0x013B: "artist", 0x0132: "datetime"}.items():
                v = ex.get(tag)
                if v:
                    out[name] = _to_text(v)
            sub = ex.get_ifd(0x8769)
            for tag, name in {0x9286: "user_comment", 0x9003: "dto", 0x9011: "offset_original",
                              0xA434: "lens_model", 0xA431: "body_serial"}.items():
                v = sub.get(tag)
                if v:
                    out[name] = _to_text(v)
            mn = sub.get(0x927C)
            if isinstance(mn, (bytes, bytearray)):
                strings = re.findall(rb"[ -~]{5,}", bytes(mn))
                out["maker_note_strings"] = " | ".join(s.decode("ascii") for s in strings[:40])[:2000]
            gps = ex.get_ifd(0x8825)
            if gps:
                out["gps_ifd"] = {int(k): v for k, v in gps.items()}
                m = gps.get(0x001B)
                if m:
                    out["gps_method"] = _to_text(m)
    except Exception:
        pass
    return out


def _rat(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return float(x[0]) / float(x[1])


def metadata_from_image(image_bytes: bytes) -> Dict[str, Any]:
    """Minimal metadata dict in the shape resolve_geospatial_telemetry expects (handy for CLI/tests)."""
    f = read_exif_fields(image_bytes)
    meta: Dict[str, Any] = {"gps": {}, "temporal": {}, "exposure": {}}
    g = f.get("gps_ifd") or {}
    try:
        if 2 in g and 4 in g:
            d, m, s = (_rat(x) for x in g[2])
            lat = d + m / 60 + s / 3600
            d, m, s = (_rat(x) for x in g[4])
            lon = d + m / 60 + s / 3600
            if str(g.get(1, "N")).upper().startswith("S"):
                lat = -lat
            if str(g.get(3, "E")).upper().startswith("W"):
                lon = -lon
            meta["gps"] = {"has_gps": True, "latitude": lat, "longitude": lon,
                           "altitude_meters": _rat(g[6]) if 6 in g else None}
    except Exception:
        pass
    meta["temporal"] = {"date_time_original": f.get("dto") or f.get("datetime"),
                        "offset_time": f.get("offset_original")}
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            ex = img.getexif()
            sub = ex.get_ifd(0x8769)
            meta["exposure"] = {"f_number": sub.get(0x829D), "exposure_time": sub.get(0x829A),
                                "iso": sub.get(0x8827),
                                "flash": ("Flash fired" if (sub.get(0x9209) or 0) & 1 else "Flash did not fire")}
    except Exception:
        pass
    return meta


def _walk_strings(obj: Any, key_re: re.Pattern, prefix: str = "") -> List[str]:
    out: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _walk_strings(v, key_re, str(k))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out += _walk_strings(v, key_re, prefix)
    elif isinstance(obj, str) and key_re.search(prefix):
        out.append(obj)
    return out


EDITOR_RE = re.compile(r"photoshop|lightroom|gimp|snapseed|picsart|canva|facetune|pixelmator|affinity|paint\.net|"
                       r"capture one|darktable|adobe|photoscape|lightx|vsco|remini", re.I)
FILENAME_PATTERNS = [
    ("whatsapp", re.compile(r"(IMG-\d{8}-WA\d+|WhatsApp[ _]Image)", re.I)),
    ("screenshot", re.compile(r"screen[ _-]?shot", re.I)),
    ("facebook", re.compile(r"FB_IMG", re.I)),
    ("snapchat", re.compile(r"snapchat", re.I)),
    ("telegram", re.compile(r"telegram|photo_\d{4}-\d{2}-\d{2}", re.I)),
    ("pixel_camera", re.compile(r"PXL_\d{8}_\d{6,9}")),
    ("generic_camera", re.compile(r"(IMG|DSC|DJI|PHOTO)[_-]?\d{4,}", re.I)),
]


def _thumbnail_check(image_bytes: bytes) -> Optional[Dict[str, Any]]:
    if image_bytes[:2] != b"\xff\xd8":
        return None
    for marker, payload in jpeg_segments(image_bytes[:4_000_000]):
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            s = payload.find(b"\xff\xd8\xff", 12)
            e = payload.rfind(b"\xff\xd9")
            if s < 0 or e <= s:
                return None
            try:
                with Image.open(io.BytesIO(payload[s:e + 2])) as t, Image.open(io.BytesIO(image_bytes)) as m:
                    tw, th = t.size
                    mw, mh = m.size
                    a = np.asarray(t.convert("L").resize((32, 32), Image.Resampling.BOX), dtype=np.float32).ravel()
                    b = np.asarray(m.convert("L").resize((32, 32), Image.Resampling.BOX), dtype=np.float32).ravel()
                aspect_diff = abs((tw / th) - (mw / mh)) / max(tw / th, 1e-6)
                corr = float(np.corrcoef(a, b)[0, 1]) if a.std() > 1e-3 and b.std() > 1e-3 else 1.0
                return {"thumb_size": [tw, th], "corr": round(corr, 3), "aspect_diff": round(aspect_diff, 3)}
            except Exception:
                return None
    return None


def deep_metadata(image_bytes: bytes, metadata: Dict[str, Any], filename: Optional[str] = None) -> Dict[str, Any]:
    raw = image_bytes[:4_000_000]
    exif = read_exif_fields(image_bytes)
    iptc: Dict[str, Any] = {}
    for marker, payload in jpeg_segments(raw):
        if marker == 0xED:
            iptc.update(parse_iptc(payload))
    xmp = parse_xmp(raw)
    flags: List[str] = []

    # filename
    finfo: Dict[str, Any] = {"name": filename, "kinds": []}
    if filename:
        base = os.path.basename(filename)
        finfo["kinds"] = [k for k, rx in FILENAME_PATTERNS if rx.search(base)]
        m = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", base)
        if m:
            try:
                finfo["date"] = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date().isoformat()
            except ValueError:
                pass

    # software / editing traces
    software = " ".join(filter(None, [exif.get("software"), xmp.get("creator_tool")]))
    if software and EDITOR_RE.search(software):
        flags.append(f"edited_with:{EDITOR_RE.search(software).group(0).lower()}")
    for a in xmp.get("edit_agents", []):
        if EDITOR_RE.search(a):
            flags.append(f"xmp_history_editor:{a}")
    low = raw.lower()
    if b"c2pa" in low or b"jumbf" in low or b"contentcredentials" in low:
        flags.append("content_credentials_c2pa_present")
    if re.search(rb"midjourney|stable diffusion|dall-e|firefly|generative", low):
        flags.append("possible_ai_generation_marker")

    # stripped / platform-recompressed
    if not exif.get("make") and not exif.get("model") and not (exif.get("dto") or exif.get("datetime")):
        flags.append("camera_metadata_stripped")
    if "whatsapp" in finfo["kinds"]:
        flags.append("whatsapp_file_name_exif_normally_removed")
    if "screenshot" in finfo["kinds"] or (exif.get("format") == "PNG" and not exif.get("make")):
        finfo["likely_screenshot"] = True

    # thumbnail vs main image
    thumb = _thumbnail_check(image_bytes)
    if thumb:
        if thumb["corr"] < 0.5:
            flags.append("embedded_thumbnail_differs_from_image")
        if thumb["aspect_diff"] > 0.03:
            flags.append("embedded_thumbnail_aspect_mismatch")

    # date in filename vs EXIF
    temporal = metadata.get("temporal", {}) or {}
    cap = temporal.get("date_time_original") or exif.get("dto")
    if cap and finfo.get("date"):
        m = re.search(r"(\d{4})[:\-](\d{2})[:\-](\d{2})", str(cap))
        if m and "pixel_camera" not in finfo["kinds"]:
            exif_day = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            try:
                d = abs((datetime.fromisoformat(exif_day) - datetime.fromisoformat(finfo["date"])).days)
                if d > 1:
                    flags.append(f"filename_date_differs_from_exif_by_{d}_days")
            except ValueError:
                pass

    # location-ish free text from every source
    key_re = re.compile(r"location|place|city|country|desc|comment|title|keyword|caption|address|region|state", re.I)
    free = [exif.get("description"), exif.get("user_comment"), exif.get("maker_note_strings"),
            xmp.get("description"), xmp.get("title"), xmp.get("subject"), iptc.get("caption"),
            iptc.get("object_name"), " ".join(iptc.get("keywords", []))]
    free += _walk_strings(metadata, key_re)
    if filename:
        free.append(re.sub(r"[_\-.]+", " ", os.path.splitext(os.path.basename(filename))[0]))
    struct = [iptc.get(k) for k in ("city", "sublocation", "state", "country")] + \
             [xmp.get(k) for k in ("city", "state", "country", "location")]

    return {
        "exif": exif, "iptc": iptc, "xmp": xmp, "thumbnail": thumb, "filename": finfo,
        "integrity_flags": flags, "software": software or None,
        "gps_method": exif.get("gps_method") or (metadata.get("gps", {}) or {}).get("processing_method"),
        "struct_text": " , ".join(x for x in struct if x),
        "free_text": " . ".join(x for x in free if x),
    }


# ----------------------------------------------------------------------------
# (2) OCR: languages, status-bar pass, pattern clues
# ----------------------------------------------------------------------------
_OCR_LANGS: Optional[str] = None
OCR_PREF = ("eng", "ara", "tur", "fas", "heb", "rus", "fra", "deu", "spa", "ita", "por", "ell", "ukr",
            "chi_sim", "jpn", "kor", "tha", "hin")


def ocr_languages() -> str:
    global _OCR_LANGS
    if _OCR_LANGS is None:
        env = os.environ.get("GEO_OCR_LANGS")
        if env:
            _OCR_LANGS = env
        elif pytesseract is None:
            _OCR_LANGS = ""
        else:
            try:
                have = set(pytesseract.get_languages(config=""))
            except Exception:
                have = {"eng"}
            _OCR_LANGS = "+".join([l for l in OCR_PREF if l in have][:5] or ["eng"])
    return _OCR_LANGS


def _run_ocr(img: Image.Image, psm: Optional[int] = None) -> str:
    cfg = f"--psm {psm}" if psm else ""
    for lang in (ocr_languages(), "eng", None):
        try:
            if lang:
                return pytesseract.image_to_string(img, lang=lang, config=cfg)
            return pytesseract.image_to_string(img, config=cfg)
        except Exception:
            continue
    return ""


def ocr_bundle(image_bytes: bytes) -> Dict[str, str]:
    """full: whole image. top: upscaled top band (status bar of screenshots), normal + inverted."""
    if pytesseract is None:
        return {"full": "", "top": ""}
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            gray = ImageOps.autocontrast(img.convert("L"))
        big = gray.copy()
        big.thumbnail((2400, 2400))
        full = _run_ocr(big)
        w, h = gray.size
        band = gray.crop((0, 0, w, max(40, int(h * 0.09))))
        scale = max(1.0, 1400.0 / max(1, w))
        band = band.resize((int(band.width * scale), int(band.height * scale)), Image.Resampling.LANCZOS)
        top = _run_ocr(band, 6) + "\n" + _run_ocr(ImageOps.invert(band), 6)
        return {"full": full, "top": top}
    except Exception:
        return {"full": "", "top": ""}


def ocr_text(image_bytes: bytes) -> str:  # backward compatible
    return ocr_bundle(image_bytes)["full"]


_TLD_RE = re.compile(r"\b[a-z0-9-]{3,}\.(?:(?:co|com|gov|edu|org|net)\.)?(" +
                     "|".join(sorted(TLD_TO_CC, key=len, reverse=True)) + r")\b(?![\w-])")
_PHONE_RE = re.compile(r"(?<![\w+])(?:\+|00)\s?(\d{1,3})(?=[\s\-.()]*\d{2})")
_PHONE_LOCAL = [
    (re.compile(r"(?<!\d)07[789][\s\-]?\d{3}[\s\-]?\d{4}(?!\d)"), "JO"),
    (re.compile(r"(?<!\d)07\d{3}[\s\-]?\d{6}(?!\d)"), "GB"),
]


def pattern_clues(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    low = text.lower()

    for m in list(_TLD_RE.finditer(low))[:3]:
        cc = TLD_TO_CC.get(m.group(1))
        c = country_candidate(cc, "ocr domain", W("tld"), f".{m.group(1)} domain") if cc else None
        if c:
            out.append(c)

    for m in list(_PHONE_RE.finditer(text))[:3]:
        digits = m.group(1)
        cc = next((DIAL_TO_CC[digits[:n]] for n in (3, 2, 1) if digits[:n] in DIAL_TO_CC), None)
        c = country_candidate(cc, "ocr phone", W("phone_intl"), f"+{digits[:3]} dial prefix") if cc else None
        if c:
            out.append(c)
    for rx, cc in _PHONE_LOCAL:
        if rx.search(text):
            c = country_candidate(cc, "ocr phone", W("phone_local"), "national mobile number format")
            if c:
                out.append(c)

    for cc, e in COUNTRIES.items():
        for tok in e[6]:
            if tok.isascii() and tok.replace("$", "").isalpha() or tok == "r$":
                pat = (r"\d\s?" + re.escape(tok) + r"(?![a-z])") if len(tok) <= 2 else \
                      (r"(?<![a-z])" + re.escape(tok) + r"(?![a-z])")
                hit = re.search(pat, low)
            else:
                hit = tok in low
            if hit:
                c = country_candidate(cc, "ocr currency", W("currency"), f"currency '{tok}'")
                if c:
                    out.append(c)
                break

    up = text.upper()
    plates = 0
    for label, rx, cc in LICENCE_PLATES:
        if plates >= 2:
            break
        if re.search(rx, up):
            c = country_candidate(cc, "ocr plate", W("plate"), label)
            if c:
                out.append(c)
                plates += 1

    for name, cc in COUNTRY_NAME_TO_CC.items():
        if len(name) >= 4 and re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", low):
            c = country_candidate(cc, "ocr signage", W("ocr_country"))
            if c:
                out.append(c)
    return out


# ----------------------------------------------------------------------------
# Network clues
# ----------------------------------------------------------------------------
def classify_gps_method(method: Optional[str]) -> Tuple[str, float, float, Optional[str]]:
    """-> (source_type, radius_km, confidence_pct, warning)"""
    if not method:
        return "GPS Fix (positioning method not recorded)", 0.05, 96.0, None
    m = method.upper()
    if "MANUAL" in m:
        return "Manually entered / edited location", 0.05, 55.0, "Location was entered or edited by hand"
    if "FUSED" in m:
        return "Fused location (GPS + Wi-Fi + sensors)", 0.1, 95.0, None
    if any(k in m for k in ("NETWORK", "WLAN", "WIFI", "WI-FI")):
        return "Network-assisted fix (Wi-Fi / cell positioning, not satellite)", 0.5, 88.0, \
            "Position came from network positioning, accuracy is typically 50-500 m"
    if "CELL" in m:
        return "Cell-tower fix", 3.0, 75.0, "Position came from cell towers, accuracy is typically 1-5 km"
    return "Hardware GPS Receiver Satellite Fix", 0.05, 98.5, None


RADIO_RE = re.compile(r"(?<![a-z0-9])(5g\+?|4g\+?|3g|lte|volte|wi-?fi|e-?sim|hotspot|airplane)(?![a-z0-9])", re.I)


def network_analysis(ocr: Dict[str, str], deep: Dict[str, Any], upload_context: Optional[Dict[str, Any]],
                     use_upload_ip: bool) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    info: Dict[str, Any] = {"carriers": [], "radio_hints": [], "gps_method": deep.get("gps_method"),
                            "likely_screenshot": bool(deep["filename"].get("likely_screenshot")), "notes": []}
    cands: List[Dict[str, Any]] = []
    top, full = ocr.get("top", "").lower(), ocr.get("full", "").lower()
    info["radio_hints"] = sorted({m.group(1).lower() for m in RADIO_RE.finditer(top)})

    for name, codes in CARRIERS.items():
        nname = name.lower()
        pat = (r"(?<![a-z0-9])" + re.escape(nname) + r"(?![a-z0-9])") if nname.isascii() else re.escape(nname)
        in_top = re.search(pat, top)
        in_full = re.search(pat, full) if nname.isascii() else None  # non-ASCII names only trusted in status bar
        if not (in_top or in_full):
            continue
        base = W("carrier_top") if in_top else W("carrier_full")
        w = base / math.sqrt(len(codes))
        info["carriers"].append({"name": name, "countries": codes, "where": "status bar" if in_top else "image text"})
        for cc in codes:
            c = country_candidate(cc, "network operator", w, f"operator '{name}'")
            if c:
                c["clue"] = f"operator:{name}"
                cands.append(c)

    if info["carriers"]:
        info["notes"].append("Operator names narrow the country but do not give a location; "
                             "roaming and shared brand names (Orange, Vodafone, Zain) are common.")
    if info["gps_method"]:
        info["notes"].append(f"GPS processing method recorded as '{info['gps_method']}'.")
    if upload_context:
        info["upload_context"] = {k: upload_context[k] for k in ("client_ip_country", "client_ip_city")
                                  if k in upload_context}
        info["notes"].append("Upload IP shows where the file was uploaded from, not where it was taken.")
        cc = (upload_context.get("client_ip_country") or "").upper()
        if use_upload_ip and cc in COUNTRIES:
            c = country_candidate(cc, "upload ip", W("upload_ip"), "uploader location - not capture location")
            if c:
                cands.append(c)
    return info, cands


# ----------------------------------------------------------------------------
# Time / exposure / photometry (unchanged logic)
# ----------------------------------------------------------------------------
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
        "available": False, "sky_ratio": 0.0, "overcast_ratio": 0.0, "vegetation_ratio": 0.0,
        "arid_tone_ratio": 0.0, "snow_ratio": 0.0, "water_ratio": 0.0, "neutral_gray_ratio": 0.0,
        "edge_density": 0.0, "mean_saturation": 0.0, "indoor_hint": False, "climates": [], "tags": [],
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
        "sky_ratio": round(sky_ratio, 3), "overcast_ratio": round(overcast_ratio, 3),
        "vegetation_ratio": round(veg_ratio, 3), "arid_tone_ratio": round(arid_ratio, 3),
        "snow_ratio": round(snow_low, 3), "water_ratio": round(water_low, 3),
        "neutral_gray_ratio": round(gray_ratio, 3), "edge_density": round(edge_density, 3),
        "mean_saturation": round(sat_mean, 3), "indoor_hint": bool(indoor_hint),
        "climates": climates, "tags": tags,
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
    ev: Optional[float], cct: float, luminance: float, solar_phase: str, flash_fired: bool,
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


# ----------------------------------------------------------------------------
# (5) Shadow analysis
# ----------------------------------------------------------------------------
def shadow_elevation(object_height: float, shadow_length: float) -> float:
    return math.degrees(math.atan2(object_height, shadow_length))


def shadow_locus(elev_deg: float, dt_utc: datetime, err_deg: float = 2.0, step: float = 2.0) -> List[List[float]]:
    """Grid points where the computed sun elevation matches the shadow-derived elevation."""
    tol = max(1.5, err_deg)
    pts: List[List[float]] = []
    lat = -80.0
    while lat <= 80.0:
        lon = -180.0
        while lon < 180.0:
            if abs(solar_elevation(lat, lon, dt_utc) - elev_deg) <= tol:
                pts.append([round(lat, 1), round(lon, 1)])
            lon += step
        lat += step
    return pts


# ----------------------------------------------------------------------------
# Candidate sources
# ----------------------------------------------------------------------------
def match_gazetteer(corpus: str, source: str, city_weight: float, country_weight: float) -> List[Dict[str, Any]]:
    found = []
    for names, lat, lon, region, radius, level, climates in GAZETTEER:
        hit = any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", corpus) for n in names)
        if hit:
            found.append({
                "source": source, "label": region, "lat": lat, "lon": lon, "radius": float(radius),
                "weight": city_weight if level == "city" else country_weight,
                "climates": set(climates), "flags": [],
            })
    return found


def script_clues(text: str) -> List[Dict[str, Any]]:
    found = []
    for name, pattern, lat, lon, radius, weight in SCRIPT_CLUES:
        if len(re.findall(pattern, text)) >= 5:
            found.append({
                "source": "ocr script", "label": f"{name} detected in image text", "lat": lat, "lon": lon,
                "radius": float(radius), "weight": weight, "climates": None, "flags": [],
            })
    return found


def timezone_candidate(offset_min: Optional[int]) -> Optional[Dict[str, Any]]:
    if offset_min is None:
        return None
    sign = "+" if offset_min >= 0 else "-"
    hh, mm = divmod(abs(offset_min), 60)
    entry = HALF_HOUR_REGIONS.get(f"{sign}{hh:02d}:{mm:02d}") if mm else TIMEZONE_REGIONS.get(f"{sign}{hh:02d}")
    if not entry:
        return None
    return {
        "source": "timezone", "label": entry["region"], "lat": entry["center_lat"], "lon": entry["center_lon"],
        "radius": 1000.0, "weight": W("timezone"), "climates": None, "flags": [],
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
                "source": "pixel biome prior", "label": label, "lat": lat, "lon": lon,
                "radius": float(radius), "weight": W("biome"),
                "climates": {key} if key in CLIMATE_TAGS else None, "flags": [], "clue": "biome",
            })
    return out


def _text_candidates(text: str, source: str, city_w: float, country_w: float, idx: Optional[CityIndex],
                     offset_min: Optional[int], when: Optional[datetime], strict: bool) -> List[Dict[str, Any]]:
    if not text or not text.strip():
        return []
    cands = match_gazetteer(text.lower(), source, city_w, country_w)
    cands += match_cities(text, source, city_w, idx, offset_min, when, strict)
    for name, cc in COUNTRY_NAME_TO_CC.items():
        if len(name) >= 4 and re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", text.lower()):
            c = country_candidate(cc, source, country_w)
            if c:
                cands.append(c)
    return cands


def analyst_candidates(notes: Optional[str], idx: Optional[CityIndex], offset_min: Optional[int],
                       when: Optional[datetime]) -> List[Dict[str, Any]]:
    if not notes:
        return []
    cands = _text_candidates(notes, "analyst note", W("analyst"), W("analyst") - 0.2, idx, offset_min, when, False)
    for m in re.finditer(r"(-?\d{1,2}\.\d{2,})\s*[,;/ ]\s*(-?\d{1,3}\.\d{2,})", notes):
        lat, lon = float(m.group(1)), float(m.group(2))
        if abs(lat) <= 90 and abs(lon) <= 180:
            cands.append(mk("analyst note", f"Coordinates given by analyst ({lat:.4f}, {lon:.4f})", lat, lon, 1.0, 0.9))
    return cands


# --- (4) local vision models (optional) -------------------------------------
_GEOCLIP = None
_STREETCLIP = None


def local_vision_candidates(image_bytes: bytes, which: str, notes: List[str]) -> List[Dict[str, Any]]:
    global _GEOCLIP, _STREETCLIP
    out: List[Dict[str, Any]] = []
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((1024, 1024))
        if which == "geoclip":
            from geoclip import GeoCLIP  # pip install geoclip
            if _GEOCLIP is None:
                _GEOCLIP = GeoCLIP()
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                rgb.save(tmp, "JPEG")
                path = tmp.name
            try:
                gps, probs = _GEOCLIP.predict(path, top_k=5)
            finally:
                os.unlink(path)
            for (lat, lon), p in zip(gps.tolist(), probs.tolist()):
                w = min(W("vision_max"), 0.12 + 0.5 * float(p))
                c = mk("vision model", f"GeoCLIP guess (p={float(p):.2f})", lat, lon, 400, w)
                c["flags"].append("model_guess_not_direct_evidence")
                c["clue"] = "vision:geoclip"
                out.append(c)
        elif which == "streetclip":
            import torch
            from transformers import CLIPModel, CLIPProcessor
            if _STREETCLIP is None:
                _STREETCLIP = (CLIPModel.from_pretrained("geolocal/StreetCLIP"),
                               CLIPProcessor.from_pretrained("geolocal/StreetCLIP"))
            model, proc = _STREETCLIP
            codes = list(COUNTRIES)
            texts = [f"A street view photo from {COUNTRIES[c][0]}." for c in codes]
            inputs = proc(text=texts, images=rgb, return_tensors="pt", padding=True)
            with torch.no_grad():
                probs = model(**inputs).logits_per_image.softmax(dim=1)[0]
            top = torch.topk(probs, 5)
            for p, i in zip(top.values.tolist(), top.indices.tolist()):
                c = country_candidate(codes[i], "vision model", min(W("vision_max"), 0.10 + 0.5 * p),
                                      f"StreetCLIP p={p:.2f}")
                if c:
                    c["flags"].append("model_guess_not_direct_evidence")
                    c["clue"] = "vision:streetclip"
                    out.append(c)
    except Exception as e:  # missing package / weights / GPU etc.
        notes.append(f"Local vision model '{which}' unavailable: {type(e).__name__}: {str(e)[:120]}")
    return out


# --- (7) cloud vision (optional, off by default) ----------------------------
CLOUD_PROMPT = (
    "You are assisting a photo-geolocation workflow. Using only visible evidence (landmarks, signage, language, "
    "architecture, vegetation, terrain, road markings, driving side, plug/socket types, vehicles), list up to 3 "
    "candidate locations. Reply with JSON only: "
    '{"candidates":[{"place":str,"lat":float,"lon":float,"radius_km":float,"confidence":0-1,"reasoning":str}]}. '
    "If there is not enough evidence, return an empty list."
)


def cloud_vision_candidates(image_bytes: bytes, notes: List[str]) -> List[Dict[str, Any]]:
    if os.environ.get("GEO_CLOUD_VISION") != "1" or not os.environ.get("ANTHROPIC_API_KEY"):
        return []
    out: List[Dict[str, Any]] = []
    try:
        import base64
        import anthropic
        with Image.open(io.BytesIO(image_bytes)) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((1568, 1568))
            buf = io.BytesIO()
            rgb.save(buf, "JPEG", quality=88)
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=os.environ.get("GEO_CLOUD_MODEL", "claude-sonnet-5-5"), max_tokens=1000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(buf.getvalue()).decode()}},
                {"type": "text", "text": CLOUD_PROMPT}]}])
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        for item in data.get("candidates", [])[:3]:
            conf = float(item.get("confidence", 0.3))
            c = mk("cloud vision", str(item.get("place", "cloud guess")), float(item["lat"]), float(item["lon"]),
                   max(5.0, float(item.get("radius_km", 100))), min(W("cloud_max"), 0.10 + 0.5 * conf))
            c["reasoning"] = str(item.get("reasoning", ""))[:300]
            c["clue"] = "cloud"
            c["flags"].append("model_guess_not_direct_evidence")
            out.append(c)
        notes.append("Cloud vision enabled: the image was sent to an external API.")
    except Exception as e:
        notes.append(f"Cloud vision failed: {type(e).__name__}: {str(e)[:120]}")
    return out


# ----------------------------------------------------------------------------
# Collect / score / fuse
# ----------------------------------------------------------------------------
def dedupe_same_source(cands: List[Dict[str, Any]], km: float = 25.0) -> List[Dict[str, Any]]:
    """Two matches from the same source about the same spot are one piece of evidence: keep the strongest."""
    out: List[Dict[str, Any]] = []
    for c in sorted(cands, key=lambda x: x["weight"], reverse=True):
        if any(o["source"] == c["source"] and haversine_km(o["lat"], o["lon"], c["lat"], c["lon"]) <= km
               for o in out):
            continue
        out.append(c)
    return out


def collect_candidates(
    metadata: Dict[str, Any],
    image_bytes: bytes,
    offset_min: Optional[int],
    scene: Dict[str, Any],
    ctx: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    ctx = ctx or {}
    deep = ctx.get("deep") or {"struct_text": "", "free_text": "", "iptc": {}, "xmp": {}}
    ocr = ctx.get("ocr") or {"full": "", "top": ""}
    when = ctx.get("capture_dt")
    idx = get_city_index()
    cands: List[Dict[str, Any]] = []

    # embedded text: whole header blob (gazetteer only) + structured IPTC/XMP + free text (GeoNames)
    embedded = (str(metadata) + " " + extract_header_text(image_bytes)).lower()
    cands += match_gazetteer(embedded, "embedded text", W("embedded_city"), W("embedded_country"))
    cands += _text_candidates(deep["struct_text"], "embedded text", W("tags_city"), W("embedded_country"),
                              idx, offset_min, when, False)
    cands += _text_candidates(deep["free_text"], "embedded text", W("tags_free_text"), W("embedded_country") - 0.1,
                              idx, offset_min, when, True)
    cc = (deep["iptc"].get("country_code") or deep["xmp"].get("country_code") or "").upper()
    if cc in COUNTRIES:
        c = country_candidate(cc, "embedded text", W("embedded_country") + 0.1, "country code tag")
        if c:
            cands.append(c)

    # OCR
    full = ocr.get("full", "")
    if full.strip():
        cands += _text_candidates(full, "ocr signage", W("ocr_city"), W("ocr_country"), idx, offset_min, when, True)
        cands += script_clues(full)
        cands += pattern_clues(full)

    # network / operator clues
    cands += ctx.get("network_candidates", [])

    # analyst notes and models
    cands += analyst_candidates(ctx.get("analyst_notes"), idx, offset_min, when)
    cands += ctx.get("model_candidates", [])

    tz = timezone_candidate(offset_min)
    if tz:
        cands.append(tz)
    cands += biome_priors(scene, offset_min)
    return dedupe_same_source(cands)


NON_INDEPENDENT = ("timezone", "pixel biome prior", "upload ip")


def score_candidates(
    cands: List[Dict[str, Any]],
    scene: Dict[str, Any],
    offset_min: Optional[int],
    capture_dt: Optional[datetime],
    luminance: float,
    ev: Optional[float],
    flash_fired: bool,
    shadow_elev: Optional[float] = None,
    shadow_err: float = 2.0,
) -> None:
    tz_lon = (offset_min / 60.0) * 15.0 if offset_min is not None else None
    scene_climates = set(scene.get("climates", []))
    outdoor_bright = (ev is not None and ev >= 11.0) or (
        scene.get("sky_ratio", 0.0) > 0.20 and luminance > 120.0 and not flash_fired
    )
    dt_utc = capture_dt - timedelta(minutes=offset_min) if capture_dt and offset_min is not None else None

    for c in cands:
        s = c["weight"]
        independent = c["source"] not in NON_INDEPENDENT

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
            if shadow_elev is not None and independent:
                diff = abs(elev - shadow_elev)
                if diff <= 2 * shadow_err:
                    s = min(0.97, s + 0.06)
                    c["flags"].append("consistent_with_shadow_geometry")
                elif diff > 15:
                    s *= 0.5
                    c["flags"].append("inconsistent_with_shadow_geometry")

        c["score"] = max(0.0, min(0.97, s))


def fuse_candidates(cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cands:
        return None

    for c in cands:
        supporters = [
            o for o in cands
            if o is not c and haversine_km(c["lat"], c["lon"], o["lat"], o["lon"]) <= max(c["radius"], o["radius"])
            and not (c.get("clue") and c.get("clue") == o.get("clue"))  # alternatives of one clue are not extra proof
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
        "lat": refine["lat"], "lon": refine["lon"], "radius": refine["radius"],
        "confidence": best["aggregate"], "label": refine["label"],
        "sources": sorted({c["source"] for c in group}), "group": group, "alternatives": alternatives,
    }


def reliability_class(conf: float) -> str:
    if conf >= 0.75:
        return "HIGH"
    if conf >= 0.50:
        return "MEDIUM"
    if conf >= 0.30:
        return "LOW"
    return "SPECULATIVE"


def build_map_hint(
    has_coords: bool, lat: Optional[float], lon: Optional[float], radius_km: float, direct: bool = False,
    others: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not has_coords or lat is None or lon is None:
        return {"show": False, "latitude": None, "longitude": None, "radius_km": 0.0, "zoom_hint": None,
                "candidates": [], "reverse_search": REVERSE_SEARCH_LINKS}
    if direct:
        zoom = 13
    elif radius_km > 1500:
        zoom = 3
    elif radius_km > 500:
        zoom = 5
    elif radius_km > 100:
        zoom = 7
    else:
        zoom = 10
    cand_list = [{"label": "primary", "latitude": lat, "longitude": lon, "radius_km": radius_km, "primary": True}]
    for o in others or []:
        cand_list.append({"label": o["region"], "latitude": o["latitude"], "longitude": o["longitude"],
                          "radius_km": o["uncertainty_radius_km"], "confidence_score": o["confidence_score"],
                          "primary": False})
    return {"show": True, "latitude": lat, "longitude": lon, "radius_km": radius_km, "zoom_hint": zoom,
            "candidates": cand_list, "reverse_search": REVERSE_SEARCH_LINKS}


# ----------------------------------------------------------------------------
# GPS sanity checks (tamper hints)
# ----------------------------------------------------------------------------
def gps_consistency_checks(lat: float, lon: float, capture_dt: Optional[datetime], offset_min: Optional[int],
                           luminance: float, scene: Dict[str, Any], flash_fired: bool) -> List[str]:
    warns: List[str] = []
    if offset_min is not None and lon_diff(lon, offset_min / 60.0 * 15.0) > 45.0:
        warns.append("GPS longitude is far from where the recorded timezone offset points: "
                     "the offset or the coordinates may have been altered or the clock was not set to local time.")
    if capture_dt is not None and offset_min is not None:
        elev = solar_elevation(lat, lon, capture_dt - timedelta(minutes=offset_min))
        if elev < -6.0 and luminance > 140.0 and not flash_fired and scene.get("sky_ratio", 0) > 0.10:
            warns.append("Timestamp implies darkness at the GPS position but the image shows bright sky.")
    return warns


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------
def _fmt_coord(lat: float, lon: float, approx: bool = False) -> str:
    t = "~" if approx else ""
    p = 2 if approx else 4
    return f"{t}{abs(lat):.{p}f}° {'N' if lat >= 0 else 'S'}, {t}{abs(lon):.{p}f}° {'E' if lon >= 0 else 'W'}"


def resolve_geospatial_telemetry(
    metadata: Dict[str, Any],
    image_bytes: bytes,
    *,
    filename: Optional[str] = None,
    analyst_notes: Optional[str] = None,
    upload_context: Optional[Dict[str, Any]] = None,
    use_upload_ip: bool = False,
    shadow: Optional[Dict[str, float]] = None,
    use_vision: Optional[str] = None,
) -> Dict[str, Any]:
    """
    shadow:  {"object_height": 1.8, "shadow_length": 2.4, "error_deg": 2.0}   (same length units)
    use_vision: None | "geoclip" | "streetclip"   (env GEO_VISION is used when None)
    upload_context: {"client_ip_country": "JO"}   (kept separate unless use_upload_ip=True)
    """
    metadata = metadata or {}
    filename = filename or metadata.get("filename") or (metadata.get("file") or {}).get("name")
    deep = deep_metadata(image_bytes, metadata, filename)

    temporal = metadata.get("temporal", {}) or {}
    exposure = metadata.get("exposure", {}) or {}
    capture_date = temporal.get("date_time_original") or deep["exif"].get("dto")
    offset_str = temporal.get("offset_time") or deep["exif"].get("offset_original")
    capture_dt, offset_min = parse_capture_datetime(capture_date, offset_str)
    capture_hour = capture_dt.hour if capture_dt else parse_capture_hour(capture_date)

    flash_val = str(exposure.get("flash", "")).lower()
    flash_fired = "fired" in flash_val and "not" not in flash_val
    cct, luminance, illuminant_type = estimate_cct_and_luminance(image_bytes)
    scene = analyze_scene(image_bytes)

    integrity = {"flags": list(deep["integrity_flags"]), "thumbnail": deep["thumbnail"],
                 "software": deep["software"], "filename": deep["filename"], "warnings": []}

    # ---- direct GPS (EXIF, else XMP copy) --------------------------------
    gps_info = metadata.get("gps", {}) or {}
    direct: Optional[Tuple[float, float, Optional[float], str]] = None
    if gps_info.get("has_gps") and gps_info.get("latitude") is not None and gps_info.get("longitude") is not None:
        direct = (gps_info["latitude"], gps_info["longitude"], gps_info.get("altitude_meters"), "EXIF_DIRECT")
    elif deep["xmp"].get("gps"):
        lat_x, lon_x = deep["xmp"]["gps"]
        direct = (lat_x, lon_x, None, "XMP_GPS")
        integrity["flags"].append("exif_gps_missing_but_xmp_gps_present")

    network_info: Dict[str, Any] = {"gps_method": deep["gps_method"], "carriers": [], "radio_hints": [], "notes": []}

    if direct:
        lat, lon, alt, mode = direct
        src_type, radius, conf_pct, warn = classify_gps_method(deep["gps_method"])
        if mode == "XMP_GPS":
            src_type, radius, conf_pct = "GPS copy found in XMP (EXIF GPS stripped)", max(radius, 0.1), 92.0
        warnings = ([warn] if warn else []) + gps_consistency_checks(lat, lon, capture_dt, offset_min, luminance,
                                                                      scene, flash_fired)
        if warnings and any("altered" in w or "darkness" in w for w in warnings):
            conf_pct = min(conf_pct, 70.0)
        integrity["warnings"] = warnings
        network_info["notes"] = ([f"GPS processing method recorded as '{deep['gps_method']}'."]
                                 if deep["gps_method"] else [])
        notes = ["Coordinates read directly from embedded metadata without modification."] + warnings + \
                [f"Integrity flag: {f}" for f in integrity["flags"]]
        return {
            "mode": mode, "has_coordinates": True, "latitude": lat, "longitude": lon, "altitude_meters": alt,
            "uncertainty_radius_km": radius, "confidence_score": conf_pct, "reliability": "HIGH" if conf_pct >= 75 else "MEDIUM",
            "source_type": src_type,
            "map": build_map_hint(True, lat, lon, radius, True),
            "alternative_candidates": [],
            "telemetry": {
                "geographic_region": "GPS Fix (EXIF)" if mode == "EXIF_DIRECT" else "GPS Fix (XMP)",
                "coordinate_display": _fmt_coord(lat, lon),
                "timestamp_utc": gps_info.get("timestamp") or "N/A",
                "altitude_display": f"{alt:.1f} m" if alt is not None else "Sea level / Unspecified",
            },
            "evidence": [], "integrity": integrity, "network": network_info,
            "forensic_notes": " ".join(notes),
        }

    # ---- inference fallback ----------------------------------------------
    model_notes: List[str] = []
    ocr = ocr_bundle(image_bytes)
    network_info, net_cands = network_analysis(ocr, deep, upload_context, use_upload_ip)

    model_cands: List[Dict[str, Any]] = []
    vision = use_vision or os.environ.get("GEO_VISION")
    if vision in ("geoclip", "streetclip"):
        model_cands += local_vision_candidates(image_bytes, vision, model_notes)
    model_cands += cloud_vision_candidates(image_bytes, model_notes)

    shadow_elev = None
    shadow_out = None
    if shadow and shadow.get("object_height") and shadow.get("shadow_length"):
        shadow_elev = shadow_elevation(float(shadow["object_height"]), float(shadow["shadow_length"]))
        err = float(shadow.get("error_deg", 2.0))
        if capture_dt is not None and offset_min is not None:
            locus = shadow_locus(shadow_elev, capture_dt - timedelta(minutes=offset_min), err)
            shadow_out = {"sun_elevation_deg": round(shadow_elev, 1), "error_deg": err,
                          "locus_points": locus[::max(1, len(locus) // 400)], "locus_point_count": len(locus),
                          "note": "Locations where the sun had this elevation at the capture time (needs correct "
                                  "timestamp and offset). Intersect with other evidence."}
        else:
            shadow_out = {"sun_elevation_deg": round(shadow_elev, 1), "error_deg": err, "locus_points": [],
                          "note": "No timestamp/offset in metadata, so no locus can be drawn."}

    ev_100 = parse_exposure_value(exposure)
    ctx = {"deep": deep, "ocr": ocr, "capture_dt": capture_dt, "network_candidates": net_cands,
           "analyst_notes": analyst_notes, "model_candidates": model_cands}
    cands = collect_candidates(metadata, image_bytes, offset_min, scene, ctx)
    score_candidates(cands, scene, offset_min, capture_dt, luminance, ev_100, flash_fired,
                     shadow_elev, float((shadow or {}).get("error_deg", 2.0)))
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
        notes.append(f"Estimate fused from {len(fused['group'])} supporting evidence item(s): {', '.join(fused['sources'])}.")
        if fused["confidence"] < 0.30:
            notes.append("Evidence is weak; treat the result as a broad regional prior, not a location.")
        if set(fused["sources"]) <= {"vision model", "cloud vision", "timezone", "pixel biome prior"}:
            notes.append("No text-based evidence supports this estimate; it relies on model guesses and priors only.")
    else:
        notes.append("No textual, temporal, or pixel-derived regional evidence was available.")

    seen_flags = set()
    for c in cands:
        for flag in c["flags"]:
            if flag.startswith(("contradicts", "climate_mismatch", "sun_below", "inconsistent_with_shadow")):
                key = (c["label"], flag)
                if key not in seen_flags:
                    seen_flags.add(key)
                    notes.append(f"{c['label']}: {flag.replace('_', ' ')}.")

    if sun_at_estimate is not None and sun_at_estimate < -6.0 and luminance > 140.0 and not flash_fired:
        notes.append("Timestamp implies darkness at the estimated location, but the pixels are bright: timestamp or location may be unreliable.")
    notes += [f"Integrity flag: {f}" for f in integrity["flags"]]
    notes += model_notes + network_info.get("notes", [])

    has_coords = fused is not None
    lat_v = fused["lat"] if has_coords else None
    lon_v = fused["lon"] if has_coords else None
    raw_conf = fused["confidence"] if has_coords else 0.0
    conf = calibrate_confidence(raw_conf)

    evidence = [
        {"source": c["source"], "label": c["label"], "weight": round(c["weight"], 2),
         "adjusted_score": round(c["score"], 2), "radius_km": c["radius"], "flags": c["flags"],
         **({"reasoning": c["reasoning"]} if c.get("reasoning") else {})}
        for c in sorted(cands, key=lambda c: c["score"], reverse=True)[:10]
    ]

    alternatives = (
        [{"region": a["label"], "latitude": a["lat"], "longitude": a["lon"],
          "confidence_score": round(calibrate_confidence(a["aggregate"]) * 100, 1),
          "uncertainty_radius_km": a["radius"]} for a in fused["alternatives"]]
        if has_coords else []
    )

    result = {
        "mode": "INFERENCE_FALLBACK",
        "has_coordinates": has_coords,
        "latitude": round(lat_v, 4) if has_coords else None,
        "longitude": round(lon_v, 4) if has_coords else None,
        "uncertainty_radius_km": fused["radius"] if has_coords else 0.0,
        "confidence_score": round(conf * 100, 1),
        "raw_confidence_score": round(raw_conf * 100, 1),
        "confidence_calibrated": bool(CALIBRATION),
        "reliability": reliability_class(conf) if has_coords else "NONE",
        "source_type": (
            "Multi-Evidence Fusion: " + " + ".join(fused["sources"]) if has_coords
            else "Photometric & Environmental Analysis (No Regional Evidence)"
        ),
        "telemetry": {
            "coordinate_display": _fmt_coord(lat_v, lon_v, True) if has_coords
            else "Unavailable (GPS Stripped & No Regional Clues)",
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
            "city_database": "GeoNames" if get_city_index() else "built-in (40 places) - build geonames.sqlite",
            "ocr_languages": ocr_languages(),
        },
        "map": build_map_hint(has_coords, lat_v, lon_v, fused["radius"] if has_coords else 0.0, False, alternatives),
        "alternative_candidates": alternatives,
        "evidence": evidence,
        "integrity": integrity,
        "network": network_info,
        "forensic_notes": " ".join(notes),
    }
    if shadow_out:
        result["shadow"] = shadow_out
    return result


# ----------------------------------------------------------------------------
# (8) Calibration helpers
# ----------------------------------------------------------------------------
def evaluate_cases(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    cases: [{"metadata": {...}, "image_bytes": b"...", "lat": 31.95, "lon": 35.91, "kwargs": {...}}, ...]
    Returns per-case error and a reliability table (raw confidence bucket -> hit rate), where a 'hit' means
    the true point lies inside the reported uncertainty radius.
    """
    rows = []
    for c in cases:
        r = resolve_geospatial_telemetry(c.get("metadata", {}), c["image_bytes"], **c.get("kwargs", {}))
        if not r["has_coordinates"]:
            rows.append({"error_km": None, "hit": False, "raw_conf": 0.0, "radius_km": 0.0})
            continue
        err = haversine_km(r["latitude"], r["longitude"], c["lat"], c["lon"])
        rows.append({"error_km": round(err, 1), "hit": err <= max(r["uncertainty_radius_km"], 1.0),
                     "raw_conf": r.get("raw_confidence_score", r["confidence_score"]) / 100.0, "radius_km": r["uncertainty_radius_km"],
                     "mode": r["mode"]})
    buckets: Dict[int, List[bool]] = defaultdict(list)
    for r in rows:
        buckets[min(9, int(r["raw_conf"] * 10))].append(r["hit"])
    table = [{"raw_range": f"{b / 10:.1f}-{(b + 1) / 10:.1f}", "n": len(v), "hit_rate": round(sum(v) / len(v), 2)}
             for b, v in sorted(buckets.items())]
    suggested = [[(b + 0.5) / 10, round(sum(v) / len(v), 3)] for b, v in sorted(buckets.items()) if len(v) >= 3]
    return {"cases": rows, "reliability_table": table, "suggested_calibration": suggested,
            "median_error_km": (float(np.median([r["error_km"] for r in rows if r["error_km"] is not None]))
                                if any(r["error_km"] is not None for r in rows) else None)}


def save_calibration(table: List[List[float]], path: Optional[str] = None) -> str:
    path = path or os.path.join(HERE, "geo_config.json")
    cfg: Dict[str, Any] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    cfg["calibration"] = table
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return path


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "build-geonames":
        print(f"{build_geonames_db(args[1], args[2])} cities written to {args[2]}")
    elif len(args) >= 2 and args[0] == "analyze":
        data = open(args[1], "rb").read()
        notes_arg = args[args.index("--notes") + 1] if "--notes" in args else None
        out = resolve_geospatial_telemetry(metadata_from_image(data), data, filename=args[1], analyst_notes=notes_arg)
        print(json.dumps(out, indent=2, ensure_ascii=False, default=lambda o: sorted(o) if isinstance(o, set) else str(o)))
    else:
        print(__doc__)
