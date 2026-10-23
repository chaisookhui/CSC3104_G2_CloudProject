"""Environment configuration shared by the HTTP service and CLI."""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

SEAT_MAPS = {
    "dev": {"A": 3, "B": 2, "C": 1, "D": 1},
    "eval": {"A": 20, "B": 10, "C": 5, "D": 5},
}


def settings(overrides=None):
    load_dotenv(ROOT / ".env", override=False)
    database_url = os.getenv("DATABASE_URL")
    config = {
        "DATABASE_URL": database_url,
        "SEAT_MAP_TIER": os.getenv("SEAT_MAP_TIER", "dev"),
        "HOLD_TTL_SECONDS": int(os.getenv("HOLD_TTL_SECONDS", "300")),
        "EXPIRY_SCAN_INTERVAL": float(os.getenv("EXPIRY_SCAN_INTERVAL", "1")),
        "CALLBACK_INTERVAL": float(os.getenv("CALLBACK_INTERVAL", "1")),
        "CALLBACK_TIMEOUT_SECONDS": float(os.getenv("CALLBACK_TIMEOUT_SECONDS", "5")),
        "WAITLIST_URL": os.getenv("WAITLIST_URL", "http://127.0.0.1:5004").rstrip("/"),
        "HOST": os.getenv("HOST", "127.0.0.1"),
        "PORT": int(os.getenv("PORT", "5003")),
    }
    config.update(overrides or {})
    if not config["DATABASE_URL"]:
        raise ValueError("DATABASE_URL is required. Run setup.ps1 or configure the environment.")
    if config["SEAT_MAP_TIER"] not in SEAT_MAPS:
        raise ValueError("SEAT_MAP_TIER must be dev or eval")
    for key in ("HOLD_TTL_SECONDS", "EXPIRY_SCAN_INTERVAL", "CALLBACK_INTERVAL",
                "CALLBACK_TIMEOUT_SECONDS"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive")
    parsed = urlparse(config["WAITLIST_URL"])
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("WAITLIST_URL must be an HTTP(S) service URL")
    return config

