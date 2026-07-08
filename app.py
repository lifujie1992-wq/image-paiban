from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import re
import shutil
import urllib.error
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat
from psd_tools import PSDImage


Image.MAX_IMAGE_PIXELS = max(Image.MAX_IMAGE_PIXELS or 0, 500_000_000)

BASE_DIR = Path(__file__).resolve().parent


def load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text("utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env(BASE_DIR / ".env.local")

TEMPLATE_PATH = Path(
    os.environ.get(
        "PSB_TEMPLATE",
        r"D:\BaiduNetdiskDownload\基础版测试款\原始模版\1.psb",
    )
)
CACHE_DIR = BASE_DIR / "cache"
UPLOAD_DIR = BASE_DIR / "uploads"
THUMB_DIR = BASE_DIR / "thumbs"
OUTPUT_DIR = BASE_DIR / "outputs"
TEMPLATE_DIR = BASE_DIR / "templates_store"
STYLE_EXAMPLE_DIR = BASE_DIR / "style_examples"
CONFIG_PATH = BASE_DIR / "slots.json"
ACTIVE_TEMPLATE_PATH = BASE_DIR / "active_template.json"
TEMPLATE_INDEX_PATH = TEMPLATE_DIR / "templates.json"
MODEL_SETTINGS_PATH = BASE_DIR / "model_settings.json"
ASSET_ANALYSIS_PATH = BASE_DIR / "asset_analysis.json"

PREVIEW_MAX_WIDTH = 760
PREVIEW_MAX_HEIGHT = 9000
CACHE_VERSION = "v7-scale-shape-detect"
PROTECTED_LAYER_MAX_AREA = 160_000
BLACK_SLOT_THRESHOLD = 45
BLACK_SLOT_MIN_SIDE = 72
BLACK_SLOT_MIN_FILL = 0.42
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "").strip()
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "240"))
QWEN_MATCH_MAX_ASSETS = int(os.environ.get("QWEN_MATCH_MAX_ASSETS", "80"))
VISION_MATCH_PROVIDER = os.environ.get("VISION_MATCH_PROVIDER", "api").strip().lower()
VISION_API_KEY = (os.environ.get("VISION_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
VISION_API_BASE_URL = os.environ.get("VISION_API_BASE_URL", "https://usage.aiproxy.top").strip().rstrip("/")
if VISION_API_BASE_URL and not re.match(r"^https?://", VISION_API_BASE_URL, re.I):
    VISION_API_BASE_URL = f"https://{VISION_API_BASE_URL}"
if VISION_API_BASE_URL and not re.search(r"/v1/?$", VISION_API_BASE_URL):
    VISION_API_BASE_URL = f"{VISION_API_BASE_URL}/v1"
VISION_API_MODEL = os.environ.get("VISION_API_MODEL", "gpt-5.5").strip()
VISION_API_TIMEOUT = int(os.environ.get("VISION_API_TIMEOUT", str(OLLAMA_TIMEOUT)))
PSD_TEMPLATE_EXTENSIONS = {".psd", ".psb"}
RASTER_TEMPLATE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
STYLE_SAMPLE_MAX_PIXELS = int(os.environ.get("STYLE_SAMPLE_MAX_PIXELS", "18000000"))
STYLE_SAMPLE_MAX_EDGE = int(os.environ.get("STYLE_SAMPLE_MAX_EDGE", "18000"))
STYLE_SEMANTIC_SLOTS_PER_CALL = int(os.environ.get("STYLE_SEMANTIC_SLOTS_PER_CALL", "4"))
STYLE_SEMANTIC_MAX_WIDTH = int(os.environ.get("STYLE_SEMANTIC_MAX_WIDTH", "1800"))
STYLE_SEMANTIC_MAX_HEIGHT = int(os.environ.get("STYLE_SEMANTIC_MAX_HEIGHT", "3800"))
ASSET_ANALYSIS_BATCH_SIZE = int(os.environ.get("ASSET_ANALYSIS_BATCH_SIZE", "1"))
ASSET_ANALYSIS_MAX_WIDTH = int(os.environ.get("ASSET_ANALYSIS_MAX_WIDTH", "760"))
ASSET_ANALYSIS_MAX_HEIGHT = int(os.environ.get("ASSET_ANALYSIS_MAX_HEIGHT", "980"))
ASSET_ANALYSIS_QUALITY = int(os.environ.get("ASSET_ANALYSIS_QUALITY", "72"))
ASSET_ANALYSIS_TIMEOUT = int(os.environ.get("ASSET_ANALYSIS_TIMEOUT", "30"))
ASSET_ANALYSIS_WORKERS = int(os.environ.get("ASSET_ANALYSIS_WORKERS", "4"))
CONTACT_SHEET_THUMB = int(os.environ.get("CONTACT_SHEET_THUMB", "180"))
CONTACT_SHEET_MAX_WIDTH = int(os.environ.get("CONTACT_SHEET_MAX_WIDTH", "1000"))
MATCH_INCLUDE_REFERENCE_IMAGE = os.environ.get("MATCH_INCLUDE_REFERENCE_IMAGE", "").strip().lower() in {"1", "true", "yes"}
MATCH_USE_VISION_API = os.environ.get("MATCH_USE_VISION_API", "").strip().lower() in {"1", "true", "yes"}
MATCH_SCAN_ASSETS_WITH_API = os.environ.get("MATCH_SCAN_ASSETS_WITH_API", "1").strip().lower() in {"1", "true", "yes"}
AUTO_MATCH_MIN_SIDE = int(os.environ.get("AUTO_MATCH_MIN_SIDE", "180"))
AUTO_MATCH_MIN_AREA = int(os.environ.get("AUTO_MATCH_MIN_AREA", "45000"))
AUTO_MATCH_MIN_SCORE = float(os.environ.get("AUTO_MATCH_MIN_SCORE", "50"))
STYLE_SLOT_SEMANTIC_KEYS = (
    "semanticHint",
    "referenceRole",
    "preferredContent",
    "referenceText",
    "avoidContent",
    "semanticReason",
    "semanticUpdatedAt",
)
EXPORT_SPLIT_MIN_PART_HEIGHT = int(os.environ.get("EXPORT_SPLIT_MIN_PART_HEIGHT", "3500"))
EXPORT_SPLIT_EXPLICIT_MIN_PART_HEIGHT = int(os.environ.get("EXPORT_SPLIT_EXPLICIT_MIN_PART_HEIGHT", "300"))
EXPORT_SPLIT_FULL_WIDTH_SLOT_RATIO = float(os.environ.get("EXPORT_SPLIT_FULL_WIDTH_SLOT_RATIO", "0.92"))


def normalize_ollama_host(value: str) -> str:
    value = (value or "http://127.0.0.1:11434").strip()
    if not re.match(r"^https?://", value, re.I):
        value = f"http://{value}"
    value = value.replace("://0.0.0.0", "://127.0.0.1")
    return value.rstrip("/")


OLLAMA_HOST = normalize_ollama_host(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))


def normalize_vision_api_base_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if not value:
        value = "https://usage.aiproxy.top"
    if not re.match(r"^https?://", value, re.I):
        value = f"https://{value}"
    if not re.search(r"/v1/?$", value):
        value = f"{value}/v1"
    return value.rstrip("/")


def model_settings_defaults() -> dict[str, Any]:
    provider = VISION_MATCH_PROVIDER or "api"
    return {
        "provider": provider,
        "baseUrl": OLLAMA_HOST if provider == "ollama" else normalize_vision_api_base_url(VISION_API_BASE_URL),
        "model": (OLLAMA_VISION_MODEL if provider == "ollama" else VISION_API_MODEL) or "gpt-5.5",
        "apiKey": VISION_API_KEY,
        "timeout": VISION_API_TIMEOUT,
    }


def normalize_model_base_url(value: str, provider: str) -> str:
    if provider == "ollama":
        return normalize_ollama_host(value or OLLAMA_HOST)
    return normalize_vision_api_base_url(value)


def normalize_model_settings(settings: dict[str, Any], include_key: bool = False) -> dict[str, Any]:
    defaults = model_settings_defaults()
    provider = str(settings.get("provider") or defaults["provider"] or "api").strip().lower()
    if provider not in {"api", "ollama"}:
        provider = "api"
    try:
        timeout = int(settings.get("timeout") or defaults["timeout"])
    except (TypeError, ValueError):
        timeout = int(defaults["timeout"])
    timeout = max(15, min(600, timeout))
    api_key = str(settings.get("apiKey") if settings.get("apiKey") is not None else defaults["apiKey"]).strip()
    normalized = {
        "provider": provider,
        "baseUrl": normalize_model_base_url(str(settings.get("baseUrl") or defaults["baseUrl"]), provider),
        "model": str(settings.get("model") or defaults["model"]).strip(),
        "timeout": timeout,
        "hasApiKey": bool(api_key),
    }
    if include_key:
        normalized["apiKey"] = api_key
    return normalized


def read_model_settings(include_key: bool = False) -> dict[str, Any]:
    settings = model_settings_defaults()
    if MODEL_SETTINGS_PATH.exists():
        try:
            saved = json.loads(MODEL_SETTINGS_PATH.read_text("utf-8-sig"))
            if isinstance(saved, dict):
                settings.update(saved)
        except Exception:
            pass
    return normalize_model_settings(settings, include_key=include_key)


def write_model_settings(settings: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    normalized = normalize_model_settings(settings, include_key=True)
    MODEL_SETTINGS_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), "utf-8")
    return normalize_model_settings(normalized, include_key=False)


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
_OCR_ENGINE: Any | None = None


@dataclass
class Slot:
    id: str
    name: str
    x: int
    y: int
    w: int
    h: int
    source: str
    layer_key: str
    visible: bool = True
    shape: str = "rect"


def ensure_dirs() -> None:
    for path in (CACHE_DIR, UPLOAD_DIR, THUMB_DIR, OUTPUT_DIR, TEMPLATE_DIR, STYLE_EXAMPLE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def is_path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def template_slots_path(template_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", template_id)
    return TEMPLATE_DIR / f"{safe_id}.slots.json"


def template_state_path(template_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", template_id)
    return TEMPLATE_DIR / f"{safe_id}.state.json"


def template_style_profile_path(template_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", template_id)
    return TEMPLATE_DIR / f"{safe_id}.style.json"


def template_style_example_dir(template_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", template_id)
    return STYLE_EXAMPLE_DIR / safe_id


def default_template_name(path: Path) -> str:
    name = path.stem
    if name.startswith("template_") and len(name) > 18:
        return f"模板 {name[-8:]}"
    return name or "未命名模板"


def normalize_template_record(record: dict[str, Any]) -> dict[str, Any] | None:
    path_text = str(record.get("path") or "").strip()
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists():
        return None
    now = timestamp()
    return {
        "id": str(record.get("id") or uuid.uuid4().hex),
        "name": str(record.get("name") or default_template_name(path)),
        "path": str(path.resolve()),
        "originalName": str(record.get("originalName") or path.name),
        "createdAt": str(record.get("createdAt") or now),
        "updatedAt": str(record.get("updatedAt") or now),
    }


def read_template_records_raw() -> list[dict[str, Any]]:
    if not TEMPLATE_INDEX_PATH.exists():
        return []
    data = json.loads(TEMPLATE_INDEX_PATH.read_text("utf-8"))
    records = data.get("templates", []) if isinstance(data, dict) else data
    if not isinstance(records, list):
        return []
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        normalized_record = normalize_template_record(record)
        if normalized_record:
            normalized.append(normalized_record)
    return normalized


def write_template_records(records: list[dict[str, Any]]) -> None:
    ensure_dirs()
    TEMPLATE_INDEX_PATH.write_text(
        json.dumps({"templates": records}, ensure_ascii=False, indent=2),
        "utf-8",
    )


def legacy_active_data() -> dict[str, Any]:
    if not ACTIVE_TEMPLATE_PATH.exists():
        return {}
    try:
        data = json.loads(ACTIVE_TEMPLATE_PATH.read_text("utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def upsert_template_record(path: Path, name: str | None = None, original_name: str | None = None) -> dict[str, Any]:
    records = read_template_records_raw()
    path = path.resolve()
    now = timestamp()
    for record in records:
        if Path(record["path"]).resolve() == path:
            if name:
                record["name"] = name
            if original_name:
                record["originalName"] = original_name
            record["updatedAt"] = now
            write_template_records(records)
            return record

    record = {
        "id": uuid.uuid4().hex,
        "name": name or default_template_name(path),
        "path": str(path),
        "originalName": original_name or path.name,
        "createdAt": now,
        "updatedAt": now,
    }
    records.append(record)
    write_template_records(records)
    return record


def active_template_record(
    allow_missing: bool = False,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    records = records if records is not None else read_template_records_raw()
    data = legacy_active_data()
    active_id = str(data.get("id") or "")
    active_path = str(data.get("path") or "")
    active: dict[str, Any] | None = None

    if active_id:
        active = next((record for record in records if record["id"] == active_id), None)
    if active is None and active_path:
        active = next(
            (record for record in records if Path(record["path"]).resolve() == Path(active_path).resolve()),
            None,
        )

    if active is None:
        if allow_missing:
            return None
        raise FileNotFoundError("尚未导入模板")

    if not Path(active["path"]).exists():
        if allow_missing:
            return None
        raise FileNotFoundError(f"找不到模板文件：{active['path']}")

    desired_active_data = {"id": active["id"], "path": active["path"], "name": active["name"]}
    if data != desired_active_data:
        ACTIVE_TEMPLATE_PATH.write_text(json.dumps(desired_active_data, ensure_ascii=False, indent=2), "utf-8")
    return active


def ensure_template_library() -> list[dict[str, Any]]:
    records = read_template_records_raw()
    legacy_data = legacy_active_data()
    legacy_path_text = str(legacy_data.get("path") or "").strip()
    legacy_had_template_id = bool(legacy_data.get("id"))
    migrated_record_id: str | None = None
    changed = False

    if legacy_path_text:
        legacy_path = Path(legacy_path_text)
        if legacy_path.exists() and not any(Path(record["path"]).resolve() == legacy_path.resolve() for record in records):
            migrated_record_id = str(legacy_data.get("id") or uuid.uuid4().hex)
            records.append(
                {
                    "id": migrated_record_id,
                    "name": str(legacy_data.get("name") or default_template_name(legacy_path)),
                    "path": str(legacy_path.resolve()),
                    "originalName": str(legacy_data.get("originalName") or legacy_path.name),
                    "createdAt": str(legacy_data.get("createdAt") or timestamp()),
                    "updatedAt": str(legacy_data.get("updatedAt") or timestamp()),
                }
            )
            changed = True

    if changed:
        write_template_records(records)

    # One-time compatibility path: migrate pre-library slots.json only to the
    # legacy active template that just entered the library. Never use it as a
    # fallback for newly imported templates.
    if migrated_record_id and not legacy_had_template_id and CONFIG_PATH.exists():
        slot_path = template_slots_path(migrated_record_id)
        if not slot_path.exists():
            slot_path.write_text(CONFIG_PATH.read_text("utf-8"), "utf-8")

    return records


def active_template_path() -> Path:
    ensure_template_library()
    active = active_template_record()
    assert active is not None
    return Path(active["path"])


def has_active_template() -> bool:
    try:
        active_template_path()
        return True
    except FileNotFoundError:
        return False


def set_active_template(path: Path, name: str | None = None, original_name: str | None = None) -> dict[str, Any]:
    record = upsert_template_record(path, name=name, original_name=original_name)
    ACTIVE_TEMPLATE_PATH.write_text(
        json.dumps({"id": record["id"], "path": record["path"], "name": record["name"]}, ensure_ascii=False, indent=2),
        "utf-8",
    )
    return record


def set_active_template_id(template_id: str) -> dict[str, Any]:
    records = ensure_template_library()
    record = next((item for item in records if item["id"] == template_id), None)
    if not record:
        raise FileNotFoundError("找不到模板")
    ACTIVE_TEMPLATE_PATH.write_text(
        json.dumps({"id": record["id"], "path": record["path"], "name": record["name"]}, ensure_ascii=False, indent=2),
        "utf-8",
    )
    return record


def template_payloads() -> list[dict[str, Any]]:
    records = ensure_template_library()
    active = active_template_record(allow_missing=True, records=records)
    active_id = active["id"] if active else None
    payloads: list[dict[str, Any]] = []
    for record in records:
        path = Path(record["path"])
        slot_path = template_slots_path(record["id"])
        slot_count = 0
        if slot_path.exists():
            try:
                slot_data = json.loads(slot_path.read_text("utf-8"))
                if isinstance(slot_data, list):
                    slot_count = len(slot_data)
            except json.JSONDecodeError:
                slot_count = 0
        state_path = template_state_path(record["id"])
        assigned_count = 0
        if state_path.exists():
            try:
                state_data = json.loads(state_path.read_text("utf-8-sig"))
                assignments = state_data.get("assignments") if isinstance(state_data, dict) else {}
                if isinstance(assignments, dict):
                    assigned_count = len([value for value in assignments.values() if assigned_asset_id(value)])
            except json.JSONDecodeError:
                assigned_count = 0
        payloads.append(
            {
                **record,
                "active": record["id"] == active_id,
                "exists": path.exists(),
                "sizeMB": round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0,
                "slotCount": slot_count,
                "assignedCount": assigned_count,
            }
        )
    return payloads


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(exc: RequestEntityTooLarge) -> Any:
    return jsonify({"error": "模板文件太大，当前上传失败"}), 413


@app.errorhandler(Exception)
def handle_exception(exc: Exception) -> Any:
    if isinstance(exc, HTTPException):
        return jsonify({"error": exc.description}), exc.code or 500
    return jsonify({"error": str(exc)}), 500


def cache_key() -> str:
    template_path = active_template_path()
    stat = template_path.stat()
    text = f"{CACHE_VERSION}|{template_path}|{stat.st_size}|{stat.st_mtime_ns}"
    overlay_path = template_companion_overlay_path(template_path)
    if overlay_path.exists():
        overlay_stat = overlay_path.stat()
        text += f"|overlay|{overlay_stat.st_size}|{overlay_stat.st_mtime_ns}"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def template_cache_paths() -> tuple[Path, Path, Path]:
    key = cache_key()
    return (
        CACHE_DIR / f"template_{key}.png",
        CACHE_DIR / f"preview_{key}.jpg",
        CACHE_DIR / f"meta_{key}.json",
    )


def template_overlay_path() -> Path:
    return CACHE_DIR / f"overlay_{cache_key()}.png"


def template_overlay_preview_path() -> Path:
    return CACHE_DIR / f"overlay_preview_{cache_key()}.png"


def is_psd_template_path(path: Path) -> bool:
    return path.suffix.lower() in PSD_TEMPLATE_EXTENSIONS


def is_raster_template_path(path: Path) -> bool:
    return path.suffix.lower() in RASTER_TEMPLATE_EXTENSIONS


def template_companion_overlay_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.overlay.png")


def template_companion_split_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.splits.json")


def psd_slice_split_positions(psd: PSDImage) -> list[int]:
    try:
        slices_resource = psd.image_resources.get_data(1050)
    except Exception:
        return []
    data = getattr(slices_resource, "data", {})
    slices = data.get(b"slices", []) if hasattr(data, "get") else []
    positions: list[int] = []
    for item in slices:
        if not hasattr(item, "get"):
            continue
        bounds = item.get(b"bounds", {})
        if not hasattr(bounds, "get"):
            continue
        try:
            left = int(bounds.get(b"Left", -1))
            right = int(bounds.get(b"Rght", -1))
            top = int(bounds.get(b"Top ", -1))
            bottom = int(bounds.get(b"Btom", -1))
        except (TypeError, ValueError):
            continue
        if left <= 0 and right >= int(psd.width) and 0 < top < bottom <= int(psd.height):
            positions.append(top)
    return sorted(set(positions))


def psd_guide_split_positions(psd: PSDImage) -> list[int]:
    try:
        guide_resource = psd.image_resources.get_data(1032)
    except Exception:
        return []
    positions: list[int] = []
    for raw_position, direction in getattr(guide_resource, "data", []):
        if int(direction) != 1:
            continue
        try:
            positions.append(int(round(float(raw_position) / 32)))
        except (TypeError, ValueError):
            continue
    return sorted(set(positions))


def extract_psd_split_positions(path: Path, width: int, height: int) -> list[int]:
    if not is_psd_template_path(path):
        return []
    try:
        psd = PSDImage.open(path)
    except Exception:
        return []
    positions = psd_slice_split_positions(psd) or psd_guide_split_positions(psd)
    return normalize_split_positions(
        positions,
        width or int(psd.width),
        height or int(psd.height),
        min_part_height=EXPORT_SPLIT_EXPLICIT_MIN_PART_HEIGHT,
    )


def normalize_split_positions(
    values: Any,
    width: int,
    height: int,
    min_part_height: int | None = None,
) -> list[int]:
    del width
    min_height = max(400, int(min_part_height or EXPORT_SPLIT_MIN_PART_HEIGHT))
    positions: list[int] = []
    if not isinstance(values, list):
        return positions
    parsed: list[int] = []
    for value in values:
        try:
            y = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        parsed.append(y)
    for y in sorted(set(parsed)):
        if y < min_height or y > height - min_height:
            continue
        if positions and y - positions[-1] < min_height:
            continue
        positions.append(y)
    return positions


def read_template_split_guides(path: Path, width: int, height: int) -> list[int]:
    split_path = template_companion_split_path(path)
    if not split_path.exists():
        return extract_psd_split_positions(path, width, height)
    try:
        raw = json.loads(split_path.read_text("utf-8-sig"))
    except Exception:
        return extract_psd_split_positions(path, width, height)
    values = raw.get("splitPositions") if isinstance(raw, dict) else raw
    positions = normalize_split_positions(
        values,
        width,
        height,
        min_part_height=EXPORT_SPLIT_EXPLICIT_MIN_PART_HEIGHT,
    )
    return positions or extract_psd_split_positions(path, width, height)


def write_template_split_guides(path: Path, positions: list[int], width: int, height: int) -> None:
    normalized = normalize_split_positions(
        positions,
        width,
        height,
        min_part_height=EXPORT_SPLIT_EXPLICIT_MIN_PART_HEIGHT,
    )
    split_path = template_companion_split_path(path)
    if normalized:
        split_path.write_text(
            json.dumps({"splitPositions": normalized}, ensure_ascii=False, indent=2),
            "utf-8",
        )
    elif split_path.exists():
        split_path.unlink()


def load_raster_template(path: Path) -> tuple[Image.Image, Image.Image]:
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGBA")
    overlay_path = template_companion_overlay_path(path)
    if overlay_path.exists():
        overlay = ImageOps.exif_transpose(Image.open(overlay_path)).convert("RGBA")
        if overlay.size != image.size:
            overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    else:
        overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    return image, overlay


def load_psd() -> PSDImage:
    template_path = active_template_path()
    if not template_path.exists():
        raise FileNotFoundError(f"找不到模板文件：{template_path}")
    if not is_psd_template_path(template_path):
        raise ValueError("Current template is a composite image, not a PSD/PSB source.")
    return PSDImage.open(template_path)


def layer_slots(psd: PSDImage) -> list[Slot]:
    slots: list[Slot] = []
    min_area = 120 * 120
    skip_names = {
        "背景",
        "图层 23",
        "图层 40",
    }

    def walk(layers: Any, prefix: str = "") -> None:
        for layer in layers:
            name = str(layer.name or "").strip()
            label = f"{prefix}/{name}" if prefix else name
            if layer.is_group():
                walk(layer, label)
                continue

            bbox = layer.bbox
            x1, y1, x2, y2 = map(int, bbox)
            w = x2 - x1
            h = y2 - y1
            area = w * h
            if w <= 0 or h <= 0:
                continue
            if area < min_area:
                continue
            if name in skip_names:
                continue
            if layer.kind not in {"pixel", "smartobject"}:
                continue

            slot_id = f"slot_{len(slots) + 1:03d}"
            layer_key = f"{label}|{x1},{y1},{x2},{y2}|{layer.kind}"
            slots.append(
                Slot(
                    id=slot_id,
                    name=label,
                    x=x1,
                    y=y1,
                    w=w,
                    h=h,
                    source=layer.kind,
                    layer_key=layer_key,
                    visible=bool(layer.visible),
                )
            )

    walk(psd)
    slots.sort(key=lambda item: (item.y, item.x, item.h * item.w))
    return slots


def find_background_layer(psd: PSDImage) -> Any | None:
    def walk(layers: Any) -> Any | None:
        for layer in layers:
            if layer.is_group():
                found = walk(layer)
                if found is not None:
                    return found
                continue
            x1, y1, x2, y2 = map(int, layer.bbox)
            is_full_size = x1 <= 0 and y1 <= 0 and x2 >= psd.width and y2 >= psd.height
            if layer.kind == "pixel" and is_full_size and str(layer.name).strip() == "背景":
                return layer
        return None

    return walk(psd)


def alpha_composite_clipped(canvas: Image.Image, image: Image.Image, x: int, y: int) -> None:
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    left = max(0, x)
    top = max(0, y)
    right = min(canvas.width, x + image.width)
    bottom = min(canvas.height, y + image.height)
    if right <= left or bottom <= top:
        return

    crop_left = left - x
    crop_top = top - y
    crop = image.crop((crop_left, crop_top, crop_left + right - left, crop_top + bottom - top))
    canvas.alpha_composite(crop, (left, top))


def layer_key_for(layer: Any, label: str) -> str:
    x1, y1, x2, y2 = map(int, layer.bbox)
    return f"{label}|{x1},{y1},{x2},{y2}|{layer.kind}"


def fast_template_image(psd: PSDImage, skip_layer_keys: set[str] | None = None) -> Image.Image:
    skip_layer_keys = skip_layer_keys or set()
    canvas = Image.new("RGBA", (psd.width, psd.height), (255, 255, 255, 255))

    def draw(layers: Any, prefix: str = "") -> None:
        for layer in layers:
            name = str(layer.name or "").strip()
            label = f"{prefix}/{name}" if prefix else name
            if not layer.visible:
                continue
            if layer.is_group():
                draw(layer, label)
                continue
            if layer.kind not in {"pixel", "smartobject", "shape", "type"}:
                continue
            if layer_key_for(layer, label) in skip_layer_keys:
                continue
            try:
                image = layer.composite()
            except Exception:
                continue
            if image is None:
                continue
            x1, y1, _, _ = map(int, layer.bbox)
            alpha_composite_clipped(canvas, image, x1, y1)

    draw(psd)
    return canvas


def is_dark_slot_placeholder_image(image: Image.Image) -> bool:
    rgba = image.convert("RGBA")
    if rgba.width < BLACK_SLOT_MIN_SIDE or rgba.height < BLACK_SLOT_MIN_SIDE:
        return False
    rgba.thumbnail((96, 96), Image.Resampling.LANCZOS)
    pixels = list(rgba.getdata())
    if not pixels:
        return False
    alpha_pixels = [pixel for pixel in pixels if pixel[3] >= 16]
    if not alpha_pixels:
        return False
    fill = len(alpha_pixels) / len(pixels)
    if fill < BLACK_SLOT_MIN_FILL:
        return False
    dark = [
        pixel
        for pixel in alpha_pixels
        if pixel[0] <= BLACK_SLOT_THRESHOLD + 20
        and pixel[1] <= BLACK_SLOT_THRESHOLD + 20
        and pixel[2] <= BLACK_SLOT_THRESHOLD + 20
    ]
    return len(dark) / len(alpha_pixels) >= 0.82


def clear_dark_placeholder_pixels(crop: Image.Image) -> Image.Image:
    if not is_dark_slot_placeholder_image(crop):
        return crop
    cleaned = crop.convert("RGBA")
    red, green, blue, alpha = cleaned.split()
    max_dark = BLACK_SLOT_THRESHOLD + 20
    red_mask = red.point(lambda value: 255 if value <= max_dark else 0)
    green_mask = green.point(lambda value: 255 if value <= max_dark else 0)
    blue_mask = blue.point(lambda value: 255 if value <= max_dark else 0)
    alpha_mask = alpha.point(lambda value: 255 if value >= 16 else 0)
    erase_mask = ImageChops.multiply(red_mask, green_mask)
    erase_mask = ImageChops.multiply(erase_mask, blue_mask)
    erase_mask = ImageChops.multiply(erase_mask, alpha_mask)
    cleaned.putalpha(ImageChops.subtract(alpha, erase_mask))
    return cleaned


def strip_slot_regions_from_overlay(overlay: Image.Image) -> Image.Image:
    try:
        slots = read_slots()
    except Exception:
        slots = []
    if not slots:
        return overlay
    result = overlay.copy().convert("RGBA")
    for slot in slots:
        if str(slot.get("source") or "") != "black-region":
            continue
        box = slot_crop_box(slot, result.width, result.height)
        if not box:
            continue
        crop = result.crop(box)
        if not crop.getbbox():
            continue
        # Existing composite templates can carry the old black placeholder in
        # the companion overlay. Clear the placeholder pixels, but keep logos,
        # text, and other protected artwork that sit above a replaceable image.
        cleaned = clear_dark_placeholder_pixels(crop)
        if cleaned is not crop:
            result.paste(cleaned, box)
    return result


def protected_overlay_image(psd: PSDImage) -> Image.Image:
    canvas = Image.new("RGBA", (psd.width, psd.height), (255, 255, 255, 0))

    def should_protect(layer: Any, image: Image.Image) -> bool:
        x1, y1, x2, y2 = map(int, layer.bbox)
        area = max(0, x2 - x1) * max(0, y2 - y1)
        if layer.kind == "type":
            return True
        if layer.kind in {"pixel", "shape", "smartobject"} and area <= PROTECTED_LAYER_MAX_AREA:
            return not is_dark_slot_placeholder_image(image)
        return False

    def draw(layers: Any) -> None:
        for layer in layers:
            if not layer.visible:
                continue
            if layer.is_group():
                draw(layer)
                continue
            try:
                image = layer.composite()
            except Exception:
                continue
            if image is None:
                continue
            if not should_protect(layer, image):
                continue
            x1, y1, _, _ = map(int, layer.bbox)
            alpha_composite_clipped(canvas, image, x1, y1)

    draw(psd)
    return canvas


def is_decorative_slot(slot: Slot | dict[str, Any]) -> bool:
    source = slot.source if isinstance(slot, Slot) else str(slot.get("source"))
    w = slot.w if isinstance(slot, Slot) else int(slot.get("w", 0))
    h = slot.h if isinstance(slot, Slot) else int(slot.get("h", 0))
    return source == "smartobject" and w * h <= PROTECTED_LAYER_MAX_AREA


def default_slots(slots: list[Slot]) -> list[Slot]:
    visible = []
    for slot in slots:
        if not slot.visible:
            continue
        if slot.w < 180 or slot.h < 180:
            continue
        if is_decorative_slot(slot):
            continue
        if slot.w >= 1450 and slot.h >= 1800:
            continue
        if slot.h > 2600:
            continue
        visible.append(slot)
    return visible[:32]


def ensure_slot_layer_keys(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = [slot for slot in slots if not is_decorative_slot(slot)]
    removed = len(filtered) != len(slots)
    slots = filtered

    template_path = active_template_path()
    if not is_psd_template_path(template_path):
        if removed:
            write_slots(slots)
        return slots

    if all(slot.get("layer_key") for slot in slots):
        if removed:
            write_slots(slots)
        return slots

    generated = layer_slots(load_psd())
    by_id = {slot.id: slot.layer_key for slot in generated}
    by_signature = {
        (slot.name, slot.x, slot.y, slot.w, slot.h, slot.source): slot.layer_key
        for slot in generated
    }

    changed = False
    for slot in slots:
        if slot.get("layer_key"):
            continue
        key = by_id.get(str(slot.get("id")))
        if not key:
            signature = (
                str(slot.get("name")),
                int(slot.get("x")),
                int(slot.get("y")),
                int(slot.get("w")),
                int(slot.get("h")),
                str(slot.get("source")),
            )
            key = by_signature.get(signature)
        if key:
            slot["layer_key"] = key
            changed = True

    if changed or removed:
        write_slots(slots)
    return slots


def read_slots() -> list[dict[str, Any]]:
    ensure_template_library()
    active = active_template_record()
    assert active is not None
    slot_path = template_slots_path(active["id"])
    if slot_path.exists():
        return ensure_slot_layer_keys(json.loads(slot_path.read_text("utf-8-sig")))
    return []


def read_or_detect_slots() -> list[dict[str, Any]]:
    slots = read_slots()
    if slots:
        return slots
    return detect_and_save_slots()


def clear_slots() -> None:
    active = active_template_record()
    assert active is not None
    slot_path = template_slots_path(active["id"])
    if slot_path.exists():
        slot_path.unlink()


def dark_pixel_mask(image: Image.Image) -> Image.Image:
    rgba = ImageOps.exif_transpose(image).convert("RGBA")
    red, green, blue, alpha = rgba.split()
    threshold = BLACK_SLOT_THRESHOLD
    red_mask = red.point(lambda value: 255 if value <= threshold else 0)
    green_mask = green.point(lambda value: 255 if value <= threshold else 0)
    blue_mask = blue.point(lambda value: 255 if value <= threshold else 0)
    alpha_mask = alpha.point(lambda value: 255 if value >= 16 else 0)
    return ImageChops.multiply(ImageChops.multiply(ImageChops.multiply(red_mask, green_mask), blue_mask), alpha_mask)


def connected_mask_components(mask: Image.Image) -> list[dict[str, int]]:
    width, height = mask.size
    data = mask.tobytes()
    parent: list[int] = [0]
    runs: list[tuple[int, int, int, int]] = []

    def make_label() -> int:
        parent.append(len(parent))
        return len(parent) - 1

    def find(label: int) -> int:
        while parent[label] != label:
            parent[label] = parent[parent[label]]
            label = parent[label]
        return label

    def union(left: int, right: int) -> int:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left
        return root_left

    previous: list[tuple[int, int, int]] = []
    for y in range(height):
        row = data[y * width : (y + 1) * width]
        current: list[tuple[int, int, int]] = []
        x = 0
        previous_index = 0
        while x < width:
            while x < width and row[x] == 0:
                x += 1
            if x >= width:
                break
            start = x
            while x < width and row[x] != 0:
                x += 1
            end = x - 1

            while previous_index < len(previous) and previous[previous_index][1] < start:
                previous_index += 1
            overlapping: list[int] = []
            probe = previous_index
            while probe < len(previous) and previous[probe][0] <= end:
                overlapping.append(previous[probe][2])
                probe += 1
            label = make_label() if not overlapping else find(overlapping[0])
            for other in overlapping[1:]:
                label = union(label, other)
            current.append((start, end, label))
            runs.append((y, start, end, label))
        previous = current

    components: dict[int, dict[str, int]] = {}
    for y, start, end, label in runs:
        root = find(label)
        item = components.setdefault(
            root,
            {"x1": start, "y1": y, "x2": end, "y2": y, "pixels": 0},
        )
        item["x1"] = min(item["x1"], start)
        item["y1"] = min(item["y1"], y)
        item["x2"] = max(item["x2"], end)
        item["y2"] = max(item["y2"], y)
        item["pixels"] += end - start + 1
    return list(components.values())


def detect_black_slot_shape(mask: Image.Image, item: dict[str, Any]) -> str:
    width = int(item["w"])
    height = int(item["h"])
    if width <= 0 or height <= 0:
        return "rect"
    ratio = width / height
    fill = float(item.get("fill") or 0)
    if ratio < 0.82 or ratio > 1.22:
        return "rect"
    if fill < 0.58 or fill > 0.88:
        return "rect"

    x = int(item["x"])
    y = int(item["y"])
    crop = mask.crop((x, y, x + width, y + height))
    corner = max(4, min(width, height) // 6)
    corners = [
        crop.crop((0, 0, corner, corner)),
        crop.crop((width - corner, 0, width, corner)),
        crop.crop((0, height - corner, corner, height)),
        crop.crop((width - corner, height - corner, width, height)),
    ]
    corner_pixels = corner * corner * 4
    corner_dark = 0
    for corner_crop in corners:
        corner_dark += sum(1 for value in corner_crop.tobytes() if value)
    if corner_pixels and corner_dark / corner_pixels > 0.18:
        return "rect"
    return "circle"


def black_region_slots_from_image(image: Image.Image) -> list[dict[str, Any]]:
    mask = dark_pixel_mask(image)
    width, height = mask.size
    image_area = width * height
    min_area = max(5_000, int(image_area * 0.00008))
    max_area = int(image_area * 0.65)
    candidates: list[dict[str, Any]] = []
    for component in connected_mask_components(mask):
        x1 = component["x1"]
        y1 = component["y1"]
        x2 = component["x2"]
        y2 = component["y2"]
        box_w = x2 - x1 + 1
        box_h = y2 - y1 + 1
        area = box_w * box_h
        pixels = component["pixels"]
        fill = pixels / area if area else 0
        if box_w < BLACK_SLOT_MIN_SIDE or box_h < BLACK_SLOT_MIN_SIDE:
            continue
        if area < min_area or area > max_area:
            continue
        if fill < BLACK_SLOT_MIN_FILL:
            continue
        candidate = {
            "x": x1,
            "y": y1,
            "w": box_w,
            "h": box_h,
            "pixels": pixels,
            "fill": fill,
        }
        candidate["shape"] = detect_black_slot_shape(mask, candidate)
        candidates.append(candidate)

    candidates.sort(key=lambda item: (item["y"], item["x"], item["h"] * item["w"]))
    slots: list[dict[str, Any]] = []
    for index, item in enumerate(candidates, start=1):
        slots.append(
            {
                "id": f"black_{index:03d}",
                "name": f"黑色图片位 {index}",
                "x": int(item["x"]),
                "y": int(item["y"]),
                "w": int(item["w"]),
                "h": int(item["h"]),
                "source": "black-region",
                "layer_key": "",
                "slot_type": "image",
                "shape": str(item.get("shape") or "rect"),
                "visible": True,
            }
        )
    return slots


def detect_black_slots() -> list[dict[str, Any]]:
    build_template_cache()
    template_png, _, _ = template_cache_paths()
    with Image.open(template_png) as image:
        return black_region_slots_from_image(image)


def detect_and_save_slots() -> list[dict[str, Any]]:
    slots = detect_black_slots()
    if not slots:
        template_path = active_template_path()
        if is_psd_template_path(template_path):
            psd = load_psd()
            slots = [asdict(slot) for slot in default_slots(layer_slots(psd))]
        else:
            slots = []
    write_slots(slots)
    return read_slots()


def write_slots(slots: list[dict[str, Any]]) -> None:
    ensure_dirs()
    ensure_template_library()
    active = active_template_record()
    assert active is not None
    template_slots_path(active["id"]).write_text(
        json.dumps(normalize_slots(slots), ensure_ascii=False, indent=2),
        "utf-8",
    )


def normalize_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(slots, start=1):
        normalized.append(
            {
                "id": str(raw.get("id") or f"slot_{index:03d}"),
                "name": str(raw.get("name") or f"槽位 {index}"),
                "x": int(raw["x"]),
                "y": int(raw["y"]),
                "w": int(raw["w"]),
                "h": int(raw["h"]),
                "source": str(raw.get("source") or "manual"),
                "layer_key": str(raw.get("layer_key") or ""),
                "slot_type": str(raw.get("slot_type") or raw.get("type") or "image"),
                "visible": bool(raw.get("visible", True)),
                "shape": "circle" if str(raw.get("shape") or "").lower() == "circle" else "rect",
            }
        )
    return normalized


def slot_id_set(slots: list[dict[str, Any]]) -> set[str]:
    return {str(slot.get("id")) for slot in slots if slot.get("id")}


def is_auto_match_slot(slot: dict[str, Any]) -> bool:
    if not slot.get("visible", True):
        return False
    w = int(slot.get("w", 0))
    h = int(slot.get("h", 0))
    if w <= 0 or h <= 0:
        return False
    return min(w, h) >= AUTO_MATCH_MIN_SIDE and w * h >= AUTO_MATCH_MIN_AREA


def auto_match_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [slot for slot in slots if is_auto_match_slot(slot)]


def style_match_target_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = active_template_record(allow_missing=True)
    profile = read_style_profile(active["id"]) if active else {"slots": {}}
    learned_slots = profile.get("slots") if isinstance(profile.get("slots"), dict) else {}
    learned_by_index = learned_slot_by_index(learned_slots)
    has_answer_key = any(
        isinstance(item, dict) and slot_semantic_hint(item)
        for item in learned_slots.values()
    )
    if not has_answer_key:
        return auto_match_slots(slots)
    targets: list[dict[str, Any]] = []
    for index, slot in enumerate(slots, start=1):
        if not slot.get("visible", True):
            continue
        if int(slot.get("w", 0)) <= 0 or int(slot.get("h", 0)) <= 0:
            continue
        slot_id = str(slot.get("id") or "")
        learned = learned_slots.get(slot_id) if isinstance(learned_slots.get(slot_id), dict) else learned_by_index.get(index)
        if isinstance(learned, dict) and slot_semantic_hint(learned):
            targets.append(slot)
    return targets or auto_match_slots(slots)


def image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            return int(image.width), int(image.height)
    except Exception:
        return 0, 0


def asset_payload(image_id: str, name: str | None = None) -> dict[str, Any] | None:
    image_id = Path(str(image_id or "")).name
    if not image_id:
        return None
    image_path = UPLOAD_DIR / image_id
    if not image_path.exists():
        return None

    thumb_name = f"{Path(image_id).stem}.jpg"
    thumb_path = THUMB_DIR / thumb_name
    width, height = image_size(image_path)
    return {
        "id": image_id,
        "url": f"/api/upload/{image_id}",
        "thumbUrl": f"/api/thumb/{thumb_name}" if thumb_path.exists() else f"/api/upload/{image_id}",
        "name": str(name or image_id),
        "width": width,
        "height": height,
    }


def assigned_asset_id(value: Any) -> str:
    if isinstance(value, dict):
        return Path(str(value.get("assetId") or value.get("id") or "")).name
    return Path(str(value or "")).name


def normalize_transform(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    try:
        x = float(value.get("x", 0) or 0)
    except (TypeError, ValueError):
        x = 0
    try:
        y = float(value.get("y", 0) or 0)
    except (TypeError, ValueError):
        y = 0
    try:
        scale = float(value.get("scale", 1) or 1)
    except (TypeError, ValueError):
        scale = 1
    return {"x": round(x, 4), "y": round(y, 4), "scale": max(0.2, min(5.0, round(scale, 4)))}


def normalize_template_state(raw: dict[str, Any] | None, valid_slot_ids: set[str] | None = None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    raw_assets = raw.get("assets") if isinstance(raw.get("assets"), list) else []
    raw_assignments = raw.get("assignments") if isinstance(raw.get("assignments"), dict) else {}
    raw_transforms = raw.get("transforms") if isinstance(raw.get("transforms"), dict) else {}

    assets_by_id: dict[str, dict[str, Any]] = {}
    for item in raw_assets:
        if not isinstance(item, dict):
            continue
        image_id = assigned_asset_id(item)
        asset = asset_payload(image_id, str(item.get("name") or image_id))
        if asset:
            assets_by_id[asset["id"]] = asset

    assignments: dict[str, str] = {}
    for slot_id, value in raw_assignments.items():
        slot_id = str(slot_id)
        if valid_slot_ids is not None and slot_id not in valid_slot_ids:
            continue
        image_id = assigned_asset_id(value)
        asset = assets_by_id.get(image_id) or asset_payload(image_id)
        if not asset:
            continue
        assets_by_id[asset["id"]] = asset
        assignments[slot_id] = asset["id"]

    transforms = {
        str(slot_id): normalize_transform(raw_transforms.get(slot_id))
        for slot_id in assignments
    }
    fit = str(raw.get("fit") or "cover")
    if fit not in {"cover", "contain"}:
        fit = "cover"

    return {
        "assets": list(assets_by_id.values()),
        "assignments": assignments,
        "transforms": transforms,
        "fit": fit,
    }


def read_template_state(template_id: str | None = None, slots: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if template_id is None:
        active = active_template_record()
        assert active is not None
        template_id = active["id"]
    state_path = template_state_path(template_id)
    valid_slot_ids = slot_id_set(slots) if slots is not None else None
    if not state_path.exists():
        return normalize_template_state({}, valid_slot_ids)
    try:
        return normalize_template_state(json.loads(state_path.read_text("utf-8-sig")), valid_slot_ids)
    except json.JSONDecodeError:
        return normalize_template_state({}, valid_slot_ids)


def write_template_state(
    state: dict[str, Any],
    template_id: str | None = None,
    slots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ensure_dirs()
    if template_id is None:
        active = active_template_record()
        assert active is not None
        template_id = active["id"]
    normalized = normalize_template_state(state, slot_id_set(slots) if slots is not None else None)
    template_state_path(template_id).write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        "utf-8",
    )
    return normalized


def render_psd_template(path: Path) -> tuple[PSDImage, Image.Image, Image.Image]:
    psd = PSDImage.open(path)
    image = fast_template_image(psd)
    overlay = protected_overlay_image(psd)
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    if overlay.mode != "RGBA":
        overlay = overlay.convert("RGBA")
    return psd, image, overlay


def build_template_cache() -> dict[str, Any]:
    ensure_dirs()
    template_png, preview_jpg, meta_json = template_cache_paths()
    overlay_png = template_overlay_path()
    overlay_preview_png = template_overlay_preview_path()
    if (
        template_png.exists()
        and preview_jpg.exists()
        and meta_json.exists()
        and overlay_png.exists()
        and overlay_preview_png.exists()
    ):
        return json.loads(meta_json.read_text("utf-8"))

    template_path = active_template_path()
    if is_psd_template_path(template_path):
        _, image, overlay = render_psd_template(template_path)
    elif is_raster_template_path(template_path):
        image, overlay = load_raster_template(template_path)
    else:
        raise ValueError(f"Unsupported template format: {template_path.suffix}")

    overlay = strip_slot_regions_from_overlay(overlay)
    image.save(template_png)
    overlay.save(overlay_png)

    preview = image.convert("RGB")
    ratio = min(1.0, PREVIEW_MAX_WIDTH / preview.width, PREVIEW_MAX_HEIGHT / preview.height)
    preview_size = (int(preview.width * ratio), int(preview.height * ratio))
    preview = preview.resize(preview_size, Image.Resampling.LANCZOS)
    preview.save(preview_jpg, quality=88, optimize=True)

    overlay_preview = overlay.resize(preview_size, Image.Resampling.LANCZOS)
    overlay_preview.save(overlay_preview_png, optimize=True)

    meta = {
        "width": image.width,
        "height": image.height,
        "previewWidth": preview.width,
        "previewHeight": preview.height,
        "scale": preview.width / image.width,
        "scaleX": preview.width / image.width,
        "scaleY": preview.height / image.height,
        "templateImage": f"/api/template-image?kind=full",
        "topOverlayImage": f"/api/template-image?kind=overlay",
        "topOverlayPreviewImage": f"/api/template-image?kind=overlay-preview",
        "previewImage": f"/api/template-image?kind=preview",
    }
    meta_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    return meta


def slots_from_rendered_psd(psd: PSDImage, image: Image.Image) -> list[dict[str, Any]]:
    slots = black_region_slots_from_image(image)
    if not slots:
        slots = [asdict(slot) for slot in default_slots(layer_slots(psd))]
    return slots


def offset_appended_slots(
    slots: list[dict[str, Any]],
    x_offset: int,
    y_offset: int,
    existing_ids: set[str],
) -> list[dict[str, Any]]:
    appended: list[dict[str, Any]] = []
    next_index = len(existing_ids) + 1
    for raw in normalize_slots(slots):
        while True:
            slot_id = f"slot_{next_index:03d}"
            next_index += 1
            if slot_id not in existing_ids:
                break
        existing_ids.add(slot_id)
        appended.append(
            {
                **raw,
                "id": slot_id,
                "name": f"{raw['name']} - appended",
                "x": int(raw["x"]) + x_offset,
                "y": int(raw["y"]) + y_offset,
            }
        )
    return appended


def save_composite_template(
    base_image: Image.Image,
    base_overlay: Image.Image,
    appended_image: Image.Image,
    appended_overlay: Image.Image,
) -> Path:
    width = max(base_image.width, appended_image.width)
    height = base_image.height + appended_image.height
    target = TEMPLATE_DIR / f"template_combo_{uuid.uuid4().hex}.png"
    overlay_target = template_companion_overlay_path(target)

    composite = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    composite.alpha_composite(base_image.convert("RGBA"), (0, 0))
    composite.alpha_composite(appended_image.convert("RGBA"), (0, base_image.height))
    composite.save(target, optimize=True)

    composite_overlay = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    composite_overlay.alpha_composite(base_overlay.convert("RGBA"), (0, 0))
    composite_overlay.alpha_composite(appended_overlay.convert("RGBA"), (0, base_image.height))
    composite_overlay.save(overlay_target, optimize=True)
    return target


def cover_fit(image: Image.Image, width: int, height: int) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGBA")
    src_ratio = image.width / image.height
    dst_ratio = width / height
    if src_ratio > dst_ratio:
        new_h = height
        new_w = round(height * src_ratio)
    else:
        new_w = width
        new_h = round(width / src_ratio)
    resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = max(0, (new_w - width) // 2)
    top = max(0, (new_h - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def contain_fit(image: Image.Image, width: int, height: int) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGBA")
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    left = (width - image.width) // 2
    top = (height - image.height) // 2
    canvas.alpha_composite(image, (left, top))
    return canvas


def transform_fit(
    image: Image.Image,
    width: int,
    height: int,
    fit_mode: str,
    transform: dict[str, Any] | None,
) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGBA")
    if width <= 0 or height <= 0 or image.width <= 0 or image.height <= 0:
        return Image.new("RGBA", (max(1, width), max(1, height)), (255, 255, 255, 0))

    if fit_mode == "contain":
        base_scale = min(width / image.width, height / image.height)
    else:
        base_scale = max(width / image.width, height / image.height)

    transform = transform or {}
    zoom = max(0.2, min(5.0, float(transform.get("scale") or 1)))
    offset_x = int(round(float(transform.get("x") or 0)))
    offset_y = int(round(float(transform.get("y") or 0)))
    target_w = max(1, int(round(image.width * base_scale * zoom)))
    target_h = max(1, int(round(image.height * base_scale * zoom)))
    resized = image.resize((target_w, target_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    left = int(round((width - target_w) / 2 + offset_x))
    top = int(round((height - target_h) / 2 + offset_y))
    alpha_composite_clipped(canvas, resized, left, top)
    return canvas


def apply_slot_shape(image: Image.Image, slot: dict[str, Any]) -> Image.Image:
    if str(slot.get("shape") or "rect").lower() != "circle":
        return image
    image = image.convert("RGBA")
    width, height = image.size
    diameter = max(1, min(width, height))
    left = (width - diameter) // 2
    top = (height - diameter) // 2
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((left, top, left + diameter, top + diameter), fill=255)
    alpha = image.getchannel("A")
    image.putalpha(ImageChops.multiply(alpha, mask))
    return image


def visual_feature(image: Image.Image) -> list[float]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    original_width = max(1, image.width)
    original_height = max(1, image.height)
    small = image.resize((64, 64), Image.Resampling.LANCZOS)
    stat = ImageStat.Stat(small)

    features: list[float] = []
    features.extend((value / 255) * 1.35 for value in stat.mean[:3])
    features.extend((value / 128) * 0.75 for value in stat.stddev[:3])

    histogram = small.histogram()
    total = 64 * 64
    for channel in range(3):
        base = channel * 256
        for bucket in range(8):
            start = base + bucket * 32
            features.append((sum(histogram[start : start + 32]) / total) * 1.6)

    gray = ImageOps.grayscale(small)
    gray_stat = ImageStat.Stat(gray)
    gray_mean = (gray_stat.mean[0] or 0) / 255
    edge_mean = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0] / 255
    aspect = max(-2.0, min(2.0, math.log(original_width / original_height))) / 2
    features.append(gray_mean)
    features.append(edge_mean * 1.1)
    features.append(aspect * 1.2)

    grid = ImageOps.grayscale(image.resize((8, 8), Image.Resampling.LANCZOS))
    grid_mean = sum(grid.getdata()) / 64 / 255
    features.extend(((value / 255) - grid_mean) * 0.35 for value in grid.getdata())
    return features


def visual_score(reference: list[float], candidate: list[float]) -> float:
    if not reference or not candidate:
        return 0.0
    length = min(len(reference), len(candidate))
    distance = math.sqrt(sum((reference[index] - candidate[index]) ** 2 for index in range(length)) / length)
    return round(max(0.0, min(100.0, (1 - distance) * 100)), 1)


def slot_crop_box(slot: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int] | None:
    left = max(0, int(slot["x"]))
    top = max(0, int(slot["y"]))
    right = min(width, int(slot["x"]) + int(slot["w"]))
    bottom = min(height, int(slot["y"]) + int(slot["h"]))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def scaled_slot_crop_box(
    slot: dict[str, Any],
    source_width: int,
    source_height: int,
    template_width: int,
    template_height: int,
) -> tuple[int, int, int, int] | None:
    if template_width <= 0 or template_height <= 0:
        return None
    scale_x = source_width / template_width
    scale_y = source_height / template_height
    left = max(0, int(round(int(slot["x"]) * scale_x)))
    top = max(0, int(round(int(slot["y"]) * scale_y)))
    right = min(source_width, int(round((int(slot["x"]) + int(slot["w"])) * scale_x)))
    bottom = min(source_height, int(round((int(slot["y"]) + int(slot["h"])) * scale_y)))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def style_sample_target_size(width: int, height: int) -> tuple[int, int]:
    pixels = max(1, width * height)
    scale = min(
        1.0,
        STYLE_SAMPLE_MAX_EDGE / max(1, width),
        STYLE_SAMPLE_MAX_EDGE / max(1, height),
        math.sqrt(STYLE_SAMPLE_MAX_PIXELS / pixels) if pixels > STYLE_SAMPLE_MAX_PIXELS else 1.0,
    )
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def open_style_sample_image(path: Path) -> Image.Image:
    old_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(path) as image:
            target_size = style_sample_target_size(int(image.width), int(image.height))
            try:
                image.draft("RGB", target_size)
            except Exception:
                pass
            image = ImageOps.exif_transpose(image).convert("RGB")
            if image.size != target_size and (
                image.width * image.height > STYLE_SAMPLE_MAX_PIXELS
                or image.width > STYLE_SAMPLE_MAX_EDGE
                or image.height > STYLE_SAMPLE_MAX_EDGE
            ):
                image.thumbnail(target_size, Image.Resampling.LANCZOS)
            return image.copy()
    finally:
        Image.MAX_IMAGE_PIXELS = old_limit


def read_style_profile(template_id: str | None = None) -> dict[str, Any]:
    if template_id is None:
        active = active_template_record()
        assert active is not None
        template_id = active["id"]
    profile_path = template_style_profile_path(template_id)
    if not profile_path.exists():
        return {"version": 1, "templateId": template_id, "exampleCount": 0, "slots": {}}
    try:
        data = json.loads(profile_path.read_text("utf-8-sig"))
    except json.JSONDecodeError:
        data = {}
    slots = data.get("slots") if isinstance(data, dict) and isinstance(data.get("slots"), dict) else {}
    profile = dict(data) if isinstance(data, dict) else {}
    profile["version"] = 1
    profile["templateId"] = template_id
    profile["exampleCount"] = int(data.get("exampleCount") or 0) if isinstance(data, dict) else 0
    profile["updatedAt"] = str(data.get("updatedAt") or "") if isinstance(data, dict) else ""
    profile["slots"] = slots
    return profile


def write_style_profile(profile: dict[str, Any], template_id: str | None = None) -> dict[str, Any]:
    ensure_dirs()
    if template_id is None:
        active = active_template_record()
        assert active is not None
        template_id = active["id"]
    profile["templateId"] = template_id
    profile["version"] = 1
    profile["updatedAt"] = timestamp()
    template_style_profile_path(template_id).write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        "utf-8",
    )
    return profile


def update_slot_profile(
    profile: dict[str, Any],
    slot: dict[str, Any],
    feature: list[float],
    slot_index: int | None = None,
    sample_name: str = "",
    visual_source: str = "content-sample",
) -> None:
    slots = profile.setdefault("slots", {})
    slot_id = str(slot["id"])
    current = slots.get(slot_id) if isinstance(slots.get(slot_id), dict) else {}
    old_feature = current.get("feature") if isinstance(current.get("feature"), list) else []
    old_count = int(current.get("count") or 0)
    if old_feature and len(old_feature) == len(feature) and old_count > 0:
        new_count = old_count + 1
        merged = [
            round((float(old_feature[index]) * old_count + feature[index]) / new_count, 6)
            for index in range(len(feature))
        ]
    else:
        new_count = 1
        merged = [round(float(value), 6) for value in feature]
    examples = current.get("examples") if isinstance(current.get("examples"), list) else []
    examples.append(
        {
            "name": sample_name,
            "feature": [round(float(value), 6) for value in feature],
            "source": visual_source,
            "createdAt": timestamp(),
        }
    )
    examples = examples[-240:]
    slot_data = {
        "name": str(slot.get("name") or slot_id),
        "index": slot_index,
        "ratio": round(int(slot.get("w", 1)) / max(1, int(slot.get("h", 1))), 6),
        "feature": merged,
        "examples": examples,
        "count": new_count,
        "visualSource": visual_source,
        "updatedAt": timestamp(),
    }
    for key in STYLE_SLOT_SEMANTIC_KEYS:
        if current.get(key):
            slot_data[key] = current[key]
    slots[slot_id] = slot_data


def leading_number(value: str) -> int | None:
    match = re.match(r"^\D*(\d+)", Path(value).stem)
    if not match:
        return None
    return int(match.group(1))


def slot_number_from_label(value: str, max_number: int) -> int | None:
    parts = [part for part in re.split(r"[\\/]+", value) if part]
    parent_parts = parts[:-1]
    for part in reversed(parent_parts):
        text = Path(part).stem
        match = re.search(r"(?:slot|图片位|图位|坑位|位置|位|#)?\s*0*(\d{1,3})", text, re.IGNORECASE)
        if match:
            number = int(match.group(1))
            if 1 <= number <= max_number:
                return number

    number = leading_number(parts[-1] if parts else value)
    if number is not None and 1 <= number <= max_number:
        return number
    return None


def content_sample_slot(filename: str, image: Image.Image, slots: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, int | None, str]:
    valid_slots = [
        (index, slot)
        for index, slot in enumerate(slots, start=1)
        if slot.get("visible", True) and int(slot.get("w", 0)) > 0 and int(slot.get("h", 0)) > 0
    ]
    if not valid_slots:
        return None, None, "没有可学习图片位"
    numbered = slot_number_from_label(filename, len(slots))
    if numbered is not None:
        return slots[numbered - 1], numbered, "按文件名/文件夹编号学习"
    if len(valid_slots) == 1:
        return valid_slots[0][1], valid_slots[0][0], "单图片位学习"
    return None, None, "内容样本未标注图片位编号"


def is_reference_sheet_image(image: Image.Image) -> bool:
    return image.height >= 2400 and image.height >= image.width * 2


def visible_image_slots(slots: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    return [
        (index, slot)
        for index, slot in enumerate(slots, start=1)
        if slot.get("visible", True) and int(slot.get("w", 0)) > 0 and int(slot.get("h", 0)) > 0
    ]


def reference_sheet_slot_range(slot: dict[str, Any], image_height: int, template_height: int) -> tuple[int, int]:
    slot_y = int(slot.get("y", 0))
    slot_h = int(slot.get("h", 0))
    center_ratio = (slot_y + slot_h / 2) / max(1, template_height)
    slot_image_h = max(1, int(round(image_height * slot_h / max(1, template_height))))
    pad = max(80, int(round(slot_image_h * 0.35)))
    top = int(round(center_ratio * image_height - slot_image_h / 2 - pad))
    bottom = int(round(center_ratio * image_height + slot_image_h / 2 + pad))
    top = max(0, min(image_height - 1, top))
    bottom = max(top + 1, min(image_height, bottom))
    return top, bottom


def text_value(value: Any, max_length: int = 360) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_length:
        return text
    return f"{text[:max_length - 3]}..."


def learned_slot_by_index(learned_slots: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for learned in learned_slots.values():
        if not isinstance(learned, dict):
            continue
        try:
            index = int(learned.get("index") or 0)
        except (TypeError, ValueError):
            index = 0
        if index > 0:
            result.setdefault(index, learned)
    return result


def slot_semantic_hint(learned: dict[str, Any] | None) -> str:
    if not isinstance(learned, dict):
        return ""
    parts = []
    labels = (
        ("role", "referenceRole"),
        ("preferred", "preferredContent"),
        ("referenceText", "referenceText"),
        ("avoid", "avoidContent"),
        ("reason", "semanticReason"),
    )
    for label, key in labels:
        value = text_value(learned.get(key), 220)
        if value:
            parts.append(f"{label}: {value}")
    if not parts:
        value = text_value(learned.get("semanticHint"), 520)
        if value:
            parts.append(value)
    return "; ".join(parts)


def slot_answer_contract(learned: dict[str, Any] | None) -> str:
    if not isinstance(learned, dict):
        return ""
    parts = []
    labels = (
        ("role", "referenceRole", 260),
        ("mustPrefer", "preferredContent", 520),
        ("answerText", "referenceText", 640),
        ("mustAvoid", "avoidContent", 360),
        ("why", "semanticReason", 360),
    )
    for label, key, limit in labels:
        value = text_value(learned.get(key), limit)
        if value:
            parts.append(f"{label}: {value}")
    if not parts:
        return slot_semantic_hint(learned)
    return " | ".join(parts)


def semantic_kind_from_text(text: str) -> str:
    text = str(text or "").lower()
    if any(word in text for word in ("尺码", "尺碼", "size chart", "size table", "尺寸表")):
        return "size_chart"
    if any(word in text for word in ("体重", "體重", "weight guide", "weight recommendation")):
        return "weight_guide"
    if any(word in text for word in ("水洗", "洗护", "洗滌", "洗涤", "care instruction", "wash label")):
        return "wash_label"
    if any(word in text for word in ("吊牌", "合格证", "合格證", "tag information", "hang tag", "certificate")):
        return "hang_tag"
    if any(word in text for word in ("面料", "纹理", "細節", "细节", "fabric", "detail", "领口", "袖口", "纽扣")):
        return "detail"
    if any(word in text for word in ("模特", "model", "全身", "半身", "正面", "背面", "穿搭")):
        return "model"
    return ""


def asset_kind_from_entry(entry: dict[str, Any]) -> str:
    analysis = entry.get("analysis") if isinstance(entry.get("analysis"), dict) else {}
    analysis_text = " ".join(
        text_value(analysis.get(key), 240)
        for key in ("kind", "description", "modelView", "bodyCrop", "garmentFocus", "visibleText", "suitableFor", "avoidFor")
        if analysis.get(key)
    )
    kind = semantic_kind_from_text(analysis_text)
    if kind:
        return kind
    name = str(entry.get("assetName") or entry.get("name") or entry.get("assetId") or "")
    kind = semantic_kind_from_text(name)
    if kind:
        return kind
    try:
        width = int(entry.get("width") or 0)
        height = int(entry.get("height") or 0)
    except (TypeError, ValueError):
        width = 0
        height = 0
    ratio = width / height if height else 1
    if width <= 420 and height <= 220:
        return "weight_guide"
    if ratio >= 2.4 and height <= 700:
        return "size_chart"
    if width <= 1600 and height >= 2400 and height / max(1, width) >= 1.8:
        return "hang_tag"
    return ""


def compatible_asset_for_slot(learned: dict[str, Any] | None, entry: dict[str, Any]) -> bool:
    asset_kind = asset_kind_from_entry(entry)
    slot_kind = semantic_kind_from_text(slot_semantic_hint(learned))
    if not slot_kind:
        return True
    label_kinds = {"size_chart", "weight_guide", "wash_label", "hang_tag"}
    compatible = {
        "size_chart": {"size_chart"},
        "weight_guide": {"weight_guide"},
        "wash_label": {"wash_label", "hang_tag"},
        "hang_tag": {"hang_tag", "wash_label"},
    }
    if slot_kind in label_kinds:
        return bool(asset_kind) and asset_kind in compatible.get(slot_kind, set())
    if not asset_kind:
        return True
    if asset_kind in label_kinds:
        return asset_kind in compatible.get(slot_kind, set())
    return True


def apply_slot_semantic_result(
    profile: dict[str, Any],
    result: dict[str, Any],
    slots: list[dict[str, Any]],
) -> int:
    raw_slots = result.get("slots") if isinstance(result.get("slots"), list) else []
    if not raw_slots:
        return 0
    profile_slots = profile.setdefault("slots", {})
    slot_by_id = {str(slot["id"]): (index, slot) for index, slot in enumerate(slots, start=1)}
    slot_by_index = {str(index): slot for index, slot in enumerate(slots, start=1)}
    updated = 0
    for raw in raw_slots:
        if not isinstance(raw, dict):
            continue
        slot_id = str(raw.get("slotId") or "").strip()
        if not slot_id and raw.get("slotIndex") is not None:
            slot = slot_by_index.get(str(raw.get("slotIndex")))
            slot_id = str(slot["id"]) if slot else ""
        if slot_id not in slot_by_id:
            continue
        slot_index, slot = slot_by_id[slot_id]
        current = profile_slots.get(slot_id) if isinstance(profile_slots.get(slot_id), dict) else {}
        current.update(
            {
                "name": str(slot.get("name") or slot_id),
                "index": int(current.get("index") or slot_index),
                "referenceRole": text_value(raw.get("role") or raw.get("referenceRole"), 260),
                "preferredContent": text_value(raw.get("preferredContent") or raw.get("preferred"), 420),
                "referenceText": text_value(raw.get("referenceText") or raw.get("text"), 520),
                "avoidContent": text_value(raw.get("avoidContent") or raw.get("avoid"), 260),
                "semanticReason": text_value(raw.get("reason") or raw.get("semanticReason"), 360),
                "semanticUpdatedAt": timestamp(),
            }
        )
        current["semanticHint"] = slot_semantic_hint(current)
        profile_slots[slot_id] = current
        updated += 1
    return updated


def semantic_slot_chunks(
    slots: list[dict[str, Any]],
    image_height: int,
    template_height: int,
) -> list[list[tuple[int, dict[str, Any], int, int]]]:
    entries = [
        (index, slot, *reference_sheet_slot_range(slot, image_height, template_height))
        for index, slot in visible_image_slots(slots)
    ]
    chunks: list[list[tuple[int, dict[str, Any], int, int]]] = []
    current: list[tuple[int, dict[str, Any], int, int]] = []
    for entry in entries:
        if current and len(current) >= max(1, STYLE_SEMANTIC_SLOTS_PER_CALL):
            chunks.append(current)
            current = []
        current.append(entry)
    if current:
        chunks.append(current)
    return chunks


def learn_reference_sheet_semantics(
    profile: dict[str, Any],
    image: Image.Image,
    slots: list[dict[str, Any]],
    template_height: int,
    filename: str,
) -> tuple[int, list[str]]:
    model_settings = read_model_settings(include_key=True)
    if model_settings.get("provider") == "ollama" or not model_settings.get("apiKey"):
        return 0, []
    chunks = semantic_slot_chunks(slots, image.height, template_height)
    if not chunks:
        return 0, []

    total_updated = 0
    errors: list[str] = []
    summaries: list[str] = []

    def request_semantic_chunk(
        chunk: list[tuple[int, dict[str, Any], int, int]],
        label: str,
    ) -> dict[str, Any]:
        top = max(0, min(entry[2] for entry in chunk) - 60)
        bottom = min(image.height, max(entry[3] for entry in chunk) + 60)
        crop = image.crop((0, top, image.width, bottom))
        slot_lines = []
        for slot_index, slot, slot_top, slot_bottom in chunk:
            rel_center = round((((slot_top + slot_bottom) / 2) - top) / max(1, bottom - top), 3)
            slot_lines.append(
                f"{slot_index}. slotId={slot['id']} name={slot.get('name')} "
                f"templateY={slot.get('y')} size={slot.get('w')}x{slot.get('h')} relativeCenter={rel_center}"
            )
        prompt = (
            "/no_think\n"
            "This is a vertical crop from a Chinese annotated ecommerce reference sheet. "
            "Read the Chinese notes and inspect the nearby product images. "
            "Map the notes to the listed template slots by vertical order and relative position. "
            "For each slot, infer what kind of product asset should be inserted later. "
            "Be specific about clothing ecommerce roles such as hero/model front/back/side/full-body, "
            "fabric texture, collar/cuff/buttons, size chart, body-weight recommendation, wash label, packaging, "
            "social proof, detail explainer, or closing image.\n"
            "Return only compact JSON, no markdown. Format:\n"
            '{"summary":"short Chinese summary","slots":[{"slotIndex":1,"slotId":"...","role":"...",'
            '"preferredContent":"...","referenceText":"important Chinese words read from the sheet",'
            '"avoidContent":"...","reason":"short Chinese reason"}]}\n\n'
            f"Reference file: {filename}\n"
            f"Chunk: {label}/{len(chunks)}\n"
            "Slots in this crop:\n" + "\n".join(slot_lines)
        )
        payload = {
            "model": str(model_settings.get("model") or VISION_API_MODEL),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_to_base64_fit(crop, STYLE_SEMANTIC_MAX_WIDTH, STYLE_SEMANTIC_MAX_HEIGHT)}"
                            },
                        },
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": 1800 if len(chunk) <= 2 else 2200,
        }
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = vision_api_request(
                    payload,
                    timeout=int(model_settings.get("timeout") or VISION_API_TIMEOUT),
                    settings=model_settings,
                )
                choices = response.get("choices") if isinstance(response.get("choices"), list) else []
                message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
                content = str(message.get("content") or response.get("response") or "")
                return extract_json_object(content)
            except Exception as exc:
                last_error = exc
        raise RuntimeError(str(last_error or "semantic request failed"))

    def process_semantic_chunk(
        chunk: list[tuple[int, dict[str, Any], int, int]],
        label: str,
    ) -> None:
        nonlocal total_updated
        try:
            parsed = request_semantic_chunk(chunk, label)
            summary = text_value(parsed.get("summary"), 500)
            if summary:
                summaries.append(summary)
            total_updated += apply_slot_semantic_result(profile, parsed, slots)
        except Exception as exc:
            if len(chunk) > 1:
                midpoint = max(1, len(chunk) // 2)
                process_semantic_chunk(chunk[:midpoint], f"{label}a")
                process_semantic_chunk(chunk[midpoint:], f"{label}b")
                return
            errors.append(f"semantic chunk {label}: {exc}")

    for chunk_index, chunk in enumerate(chunks, start=1):
        process_semantic_chunk(chunk, str(chunk_index))

    if summaries:
        profile["referenceSummary"] = text_value(" | ".join(summaries), 1200)
    if total_updated:
        profile["referenceSemanticCount"] = len(
            [
                item
                for item in profile.get("slots", {}).values()
                if isinstance(item, dict) and slot_semantic_hint(item)
            ]
        )
        profile["referenceUpdatedAt"] = timestamp()
    return total_updated, errors


def learn_reference_sheet_image(
    profile: dict[str, Any],
    image: Image.Image,
    slots: list[dict[str, Any]],
    template_height: int,
    filename: str,
) -> int:
    if template_height <= 0:
        return 0
    visible_slots = visible_image_slots(slots)
    if not visible_slots:
        return 0

    learned = 0
    min_crop_h = min(image.height, max(120, image.height // max(8, len(visible_slots) * 2)))
    for slot_index, slot in visible_slots:
        slot_y = int(slot.get("y", 0))
        slot_h = int(slot.get("h", 0))
        center_ratio = (slot_y + slot_h / 2) / template_height
        crop_h = max(min_crop_h, int(round(image.height * slot_h / template_height * 1.2)))
        crop_h = min(image.height, crop_h)
        top = int(round(center_ratio * image.height - crop_h / 2))
        top = max(0, min(image.height - crop_h, top))
        crop = image.crop((0, top, image.width, top + crop_h))
        update_slot_profile(profile, slot, visual_feature(crop), slot_index, filename, "reference-sheet")
        learned += 1
    return learned


def learn_style_image(
    profile: dict[str, Any],
    image: Image.Image,
    slots: list[dict[str, Any]],
    template_width: int,
    template_height: int,
    filename: str,
) -> tuple[int, str]:
    template_ratio = template_width / template_height if template_height else 1
    source_ratio = image.width / image.height if image.height else template_ratio
    ratio_delta = abs(source_ratio - template_ratio) / template_ratio if template_ratio else 0

    if ratio_delta <= 0.12:
        crop_count = 0
        for slot_index, slot in enumerate(slots, start=1):
            if not slot.get("visible", True):
                continue
            if int(slot.get("w", 0)) <= 0 or int(slot.get("h", 0)) <= 0:
                continue
            box = scaled_slot_crop_box(slot, image.width, image.height, template_width, template_height)
            if not box:
                continue
            crop = image.crop(box)
            update_slot_profile(profile, slot, visual_feature(crop), slot_index, filename, "finished-output")
            crop_count += 1
        return crop_count, "整图裁切学习" if crop_count else "没有可学习图片位"

    slot, slot_index, reason = content_sample_slot(filename, image, slots)
    if not slot:
        if is_reference_sheet_image(image):
            crop_count = learn_reference_sheet_image(profile, image, slots, template_height, filename)
            if crop_count:
                return crop_count, "参考长图按模板纵向位置学习"
        return 0, reason
    update_slot_profile(profile, slot, visual_feature(image), slot_index, filename, "content-sample")
    return 1, f"{reason}：{slot.get('name') or slot.get('id')}"


def learn_style_examples(files: list[Any], slots: list[dict[str, Any]]) -> dict[str, Any]:
    active = active_template_record()
    assert active is not None
    build_template_cache()
    template_png, _, _ = template_cache_paths()
    with Image.open(template_png) as template_image:
        template_width, template_height = template_image.size

    profile = read_style_profile(active["id"])
    example_dir = template_style_example_dir(active["id"])
    example_dir.mkdir(parents=True, exist_ok=True)

    accepted = 0
    skipped: list[str] = []
    learned_crops = 0
    semantic_hints = 0
    semantic_errors: list[str] = []
    allowed_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

    for file in files:
        if not file or not getattr(file, "filename", ""):
            continue
        ext = Path(file.filename).suffix.lower() or ".jpg"
        if ext not in allowed_exts:
            skipped.append(file.filename)
            continue
        target = example_dir / f"example_{uuid.uuid4().hex}{ext}"
        file.save(target)
        try:
            with Image.open(target) as image:
                try:
                    image.draft("RGB", style_sample_target_size(int(image.width), int(image.height)))
                except Exception:
                    pass
                image = ImageOps.exif_transpose(image).convert("RGB")
                if (
                    image.width * image.height > STYLE_SAMPLE_MAX_PIXELS
                    or image.width > STYLE_SAMPLE_MAX_EDGE
                    or image.height > STYLE_SAMPLE_MAX_EDGE
                ):
                    image.thumbnail(style_sample_target_size(image.width, image.height), Image.Resampling.LANCZOS)
                crop_count, reason = learn_style_image(
                    profile,
                    image,
                    slots,
                    template_width,
                    template_height,
                    file.filename,
                )
                if crop_count:
                    accepted += 1
                    learned_crops += crop_count
                    if is_reference_sheet_image(image):
                        updated, errors = learn_reference_sheet_semantics(
                            profile,
                            image,
                            slots,
                            template_height,
                            file.filename,
                        )
                        semantic_hints += updated
                        semantic_errors.extend(errors)
                else:
                    skipped.append(f"{file.filename}（{reason}）")
        except Exception as exc:
            skipped.append(f"{file.filename}: {exc}")

    profile["exampleCount"] = int(profile.get("exampleCount") or 0) + accepted
    profile = write_style_profile(profile, active["id"])
    profiled_slots = len(
        [
            item
            for item in profile.get("slots", {}).values()
            if isinstance(item, dict) and item.get("feature")
        ]
    )
    return {
        "profile": profile,
        "accepted": accepted,
        "skipped": skipped,
        "learnedCrops": learned_crops,
        "profiledSlots": profiled_slots,
        "semanticHints": semantic_hints,
        "semanticErrors": semantic_errors,
    }


def slot_reference_features(slots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    active = active_template_record(allow_missing=True)
    profile = read_style_profile(active["id"]) if active else {"slots": {}}
    learned_slots = profile.get("slots") if isinstance(profile.get("slots"), dict) else {}

    def learned_visual_is_reference_sheet(learned: dict[str, Any]) -> bool:
        source = str(learned.get("visualSource") or "").strip().lower()
        if source == "reference-sheet":
            return True
        examples = learned.get("examples") if isinstance(learned.get("examples"), list) else []
        example_sources = [
            str(item.get("source") or "").strip().lower()
            for item in examples
            if isinstance(item, dict)
        ]
        if example_sources and all(source == "reference-sheet" for source in example_sources):
            return True
        # Compatibility for profiles learned before source tagging: annotated
        # reference sheets provide semantics, but their visual crops include
        # surrounding notes, so they should not drive color/texture fallback.
        if profile.get("referenceSemanticCount") and slot_semantic_hint(learned):
            try:
                count = int(learned.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            if count <= max(1, int(profile.get("exampleCount") or 1)):
                return True
        return False

    learned_by_index: dict[int, dict[str, Any]] = {}
    for learned in learned_slots.values():
        if not isinstance(learned, dict):
            continue
        if learned_visual_is_reference_sheet(learned):
            continue
        try:
            index = int(learned.get("index") or 0)
        except (TypeError, ValueError):
            index = 0
        if index > 0 and learned.get("feature"):
            learned_by_index.setdefault(index, learned)

    references: dict[str, dict[str, Any]] = {}
    for index, slot in enumerate(slots, start=1):
        slot_id = str(slot["id"])
        learned = learned_slots.get(slot_id) if isinstance(learned_slots.get(slot_id), dict) else learned_by_index.get(index)
        if learned and learned_visual_is_reference_sheet(learned):
            learned = None
        feature = learned.get("feature") if learned and isinstance(learned.get("feature"), list) else None
        if feature:
            examples = learned.get("examples") if isinstance(learned.get("examples"), list) else []
            example_features = [
                [float(value) for value in item.get("feature", [])]
                for item in examples
                if isinstance(item, dict) and isinstance(item.get("feature"), list)
            ]
            references[slot_id] = {
                "feature": [float(value) for value in feature],
                "examples": example_features,
                "source": "learned",
                "count": int(learned.get("count") or 0),
            }

    build_template_cache()
    template_png, _, _ = template_cache_paths()
    template = Image.open(template_png).convert("RGB")
    for slot in slots:
        slot_id = str(slot["id"])
        if slot_id in references:
            continue
        if not slot.get("visible", True):
            continue
        if int(slot.get("w", 0)) <= 0 or int(slot.get("h", 0)) <= 0:
            continue
        box = slot_crop_box(slot, template.width, template.height)
        if not box:
            continue
        crop = template.crop(box)
        references[slot_id] = {"feature": visual_feature(crop), "examples": [], "source": "template", "count": 0}
    return references


def reference_score(slot_reference: dict[str, Any], asset_feature: list[float]) -> float:
    examples = slot_reference.get("examples") if isinstance(slot_reference.get("examples"), list) else []
    scores = [
        visual_score(example, asset_feature)
        for example in examples
        if isinstance(example, list) and example
    ]
    if scores:
        scores.sort(reverse=True)
        top_scores = scores[: min(5, len(scores))]
        return round(sum(top_scores) / len(top_scores), 1)
    return visual_score(slot_reference["feature"], asset_feature)


def current_ollama_host() -> str:
    try:
        settings = read_model_settings(include_key=True)
        if settings.get("provider") == "ollama":
            return normalize_ollama_host(str(settings.get("baseUrl") or OLLAMA_HOST))
    except Exception:
        pass
    return OLLAMA_HOST


def ollama_request(path: str, payload: dict[str, Any] | None = None, timeout: int | None = None) -> dict[str, Any]:
    url = f"{current_ollama_host()}{path}"
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_obj = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request_obj, timeout=timeout or OLLAMA_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def vision_api_request(
    payload: dict[str, Any],
    timeout: int | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = settings or read_model_settings(include_key=True)
    api_key = str(settings.get("apiKey") or "").strip()
    if not api_key:
        raise RuntimeError("大模型 API 密钥未配置")
    url = f"{normalize_vision_api_base_url(str(settings.get('baseUrl') or '')).rstrip('/')}/chat/completions"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_obj = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout or int(settings.get("timeout") or VISION_API_TIMEOUT)) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Vision API HTTP {exc.code}: {body[:500]}") from exc


def ollama_model_names() -> list[str]:
    return [str(item.get("name")) for item in ollama_models() if item.get("name")]


def ollama_models() -> list[dict[str, Any]]:
    try:
        data = ollama_request("/api/tags", None, timeout=8)
    except Exception:
        return []
    models = data.get("models") if isinstance(data, dict) else []
    return [item for item in models if isinstance(item, dict) and item.get("name")]


def qwen_vision_model() -> str:
    if OLLAMA_VISION_MODEL:
        return OLLAMA_VISION_MODEL
    models = ollama_models()
    names = [str(item.get("name")) for item in models if item.get("name")]
    vision_qwen = [
        item
        for item in models
        if "vision" in {str(cap).lower() for cap in item.get("capabilities", [])}
        and "qwen" in str(item.get("name", "")).lower()
    ]
    for target in ("my-qwen:latest", "qwen3.6-hauhau-v:latest"):
        found = next((item.get("name") for item in vision_qwen if item.get("name") == target), None)
        if found:
            return str(found)
    non_thinking = [
        item
        for item in vision_qwen
        if "thinking" not in {str(cap).lower() for cap in item.get("capabilities", [])}
    ]
    if non_thinking:
        return str(non_thinking[0]["name"])
    preferred = [
        "qwen3-vl:4b",
        "qwen3-vl",
        "qwen2.5-vl",
        "qwen2-vl",
    ]
    for target in preferred:
        found = next((name for name in names if name == target or name.startswith(f"{target}:")), None)
        if found:
            return found
    found = next((name for name in names if "qwen" in name.lower() and "vl" in name.lower()), None)
    if found:
        return found
    found = next((name for name in names if "qwen" in name.lower() and name.lower().endswith("-v:latest")), None)
    if found:
        return found
    return "qwen3-vl:4b"


def image_to_base64(image: Image.Image, max_width: int = 1280) -> str:
    image = ImageOps.exif_transpose(image).convert("RGB")
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=86, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def image_to_base64_fit(
    image: Image.Image,
    max_width: int = 1280,
    max_height: int = 3200,
    quality: int = 84,
) -> str:
    image = ImageOps.exif_transpose(image).convert("RGB")
    scale = min(
        1.0,
        max_width / max(1, image.width),
        max_height / max(1, image.height),
    )
    if scale < 1.0:
        image = image.resize(
            (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale)))),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def latest_reference_sheet_path(template_id: str | None) -> Path | None:
    if not template_id:
        return None
    example_dir = template_style_example_dir(template_id)
    if not example_dir.exists():
        return None
    candidates = sorted(
        [
            path
            for path in example_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates[:8]:
        try:
            with Image.open(path) as image:
                if is_reference_sheet_image(image):
                    return path
        except Exception:
            continue
    return None


def read_asset_analysis_cache() -> dict[str, Any]:
    if not ASSET_ANALYSIS_PATH.exists():
        return {}
    try:
        data = json.loads(ASSET_ANALYSIS_PATH.read_text("utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_asset_analysis_cache(cache: dict[str, Any]) -> None:
    ASSET_ANALYSIS_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")


def fallback_asset_analysis(entry: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(entry.get(key) or "") for key in ("assetName", "assetId"))
    kind = asset_kind_from_entry({"assetName": text, "width": entry.get("width"), "height": entry.get("height")}) or "unknown"
    return {
        "source": "fallback",
        "kind": kind,
        "description": text_value(f"未完成视觉扫描，按文件名和尺寸判断：{text}", 260),
        "modelView": "",
        "bodyCrop": "",
        "garmentFocus": "",
        "visibleText": "",
        "suitableFor": kind,
        "avoidFor": "",
        "confidence": 35,
    }


def normalize_asset_analysis(raw: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    normalized = {
        "source": text_value(raw.get("source") or "vision-scan", 40),
        "kind": text_value(raw.get("kind") or raw.get("type"), 80),
        "description": text_value(raw.get("description") or raw.get("summary"), 520),
        "tags": [text_value(tag, 40) for tag in tags[:16] if text_value(tag, 40)],
        "modelView": text_value(raw.get("modelView") or raw.get("view"), 80),
        "bodyCrop": text_value(raw.get("bodyCrop") or raw.get("crop"), 80),
        "poseScene": text_value(raw.get("poseScene") or raw.get("scene"), 180),
        "garmentFocus": text_value(raw.get("garmentFocus") or raw.get("focus"), 220),
        "visibleText": text_value(raw.get("visibleText") or raw.get("ocrText") or raw.get("text"), 360),
        "suitableFor": text_value(raw.get("suitableFor"), 260),
        "avoidFor": text_value(raw.get("avoidFor"), 220),
        "confidence": max(0, min(100, int(float(raw.get("confidence") or 60)))),
    }
    if not normalized["description"]:
        normalized.update(fallback_asset_analysis(entry))
    return normalized


def asset_cache_record_valid(record: Any, entry: dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    path = entry.get("path")
    if not isinstance(path, Path) or not path.exists():
        return False
    stat = path.stat()
    return (
        int(record.get("size") or -1) == int(stat.st_size)
        and int(record.get("mtimeNs") or -1) == int(stat.st_mtime_ns)
        and isinstance(record.get("analysis"), dict)
    )


def analyze_asset_batch(
    batch: list[dict[str, Any]],
    model_settings: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    use_api = model_settings.get("provider") != "ollama"
    model = str(model_settings.get("model") or (VISION_API_MODEL if use_api else qwen_vision_model()))
    prompt = (
        "/no_think\n"
        "You are scanning local ecommerce source images before template placement. "
        "For every image, identify exactly what it contains and what template role it should satisfy. "
        "Pay attention to model pose, front/back/side, full-body/half-body/detail crop, fabric texture, collar/cuff/buttons, "
        "size chart, body-weight recommendation, hang tag/certificate, wash label/care label, packaging, visible Chinese text, and whether the image is text-heavy. "
        "Return only compact JSON, no markdown. Format:\n"
        '{"assets":[{"label":"A01","assetId":"...","kind":"model|fabric_detail|craft_detail|size_chart|weight_guide|hang_tag|wash_label|packaging|flatlay|other",'
        '"description":"中文具体描述","tags":["..."],"modelView":"front/back/side/none","bodyCrop":"full_body/half_body/upper_body/detail/none",'
        '"poseScene":"...","garmentFocus":"...","visibleText":"读到的重要文字","suitableFor":"适合放到哪些图片位","avoidFor":"不适合放到哪些图片位","confidence":0-100}]}\n\n'
        "Images are supplied in the same order as this list:\n"
        + "\n".join(
            f"{entry['label']}: assetId={entry['assetId']} name={entry['assetName']} size={entry['width']}x{entry['height']}"
            for entry in batch
        )
    )
    if use_api:
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for entry in batch:
            content_parts.append({"type": "text", "text": f"Image {entry['label']} assetId={entry['assetId']} name={entry['assetName']}"})
            with Image.open(entry["path"]) as image:
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_to_base64_fit(image, ASSET_ANALYSIS_MAX_WIDTH, ASSET_ANALYSIS_MAX_HEIGHT, ASSET_ANALYSIS_QUALITY)}"
                        },
                    }
                )
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content_parts}],
            "temperature": 0,
            "max_tokens": 900 + len(batch) * 520,
        }
        response = vision_api_request(
            payload,
            timeout=min(ASSET_ANALYSIS_TIMEOUT, int(model_settings.get("timeout") or VISION_API_TIMEOUT)),
            settings=model_settings,
        )
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
        content = str(message.get("content") or response.get("response") or "")
    else:
        images: list[str] = []
        for entry in batch:
            with Image.open(entry["path"]) as image:
                images.append(image_to_base64_fit(image, ASSET_ANALYSIS_MAX_WIDTH, ASSET_ANALYSIS_MAX_HEIGHT, ASSET_ANALYSIS_QUALITY))
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt, "images": images}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "top_p": 0.8, "num_predict": 900 + len(batch) * 520},
        }
        response = ollama_request("/api/chat", payload, timeout=min(ASSET_ANALYSIS_TIMEOUT, int(model_settings.get("timeout") or OLLAMA_TIMEOUT)))
        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        content = str(message.get("content") or response.get("response") or message.get("thinking") or "")
    parsed = extract_json_object(content)
    raw_assets = parsed.get("assets") if isinstance(parsed.get("assets"), list) else []
    by_label = {str(item.get("label") or "").upper().strip(): item for item in raw_assets if isinstance(item, dict)}
    by_id = {assigned_asset_id(str(item.get("assetId") or "")): item for item in raw_assets if isinstance(item, dict)}
    result: dict[str, dict[str, Any]] = {}
    for entry in batch:
        raw = by_label.get(str(entry["label"]).upper()) or by_id.get(str(entry["assetId"])) or {}
        result[str(entry["assetId"])] = normalize_asset_analysis(raw, entry)
    return result


def analyze_asset_entries(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not entries:
        return {}
    cache = read_asset_analysis_cache()
    model_settings = read_model_settings(include_key=True)
    results: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for entry in entries:
        asset_id = str(entry["assetId"])
        record = cache.get(asset_id)
        if asset_cache_record_valid(record, entry):
            results[asset_id] = normalize_asset_analysis(record.get("analysis") or {}, entry)
        else:
            pending.append(entry)

    if not pending:
        return results

    if not MATCH_SCAN_ASSETS_WITH_API or (model_settings.get("provider") != "ollama" and not model_settings.get("apiKey")):
        for entry in pending:
            results[str(entry["assetId"])] = fallback_asset_analysis(entry)
        return results

    batch_size = max(1, min(3, ASSET_ANALYSIS_BATCH_SIZE))
    batches = [pending[start : start + batch_size] for start in range(0, len(pending), batch_size)]
    workers = max(1, min(ASSET_ANALYSIS_WORKERS, len(batches)))
    analyzed_by_id: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_batch = {
            executor.submit(analyze_asset_batch, batch, model_settings): batch
            for batch in batches
        }
        for future in as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                analyzed = future.result()
            except Exception:
                analyzed = {str(entry["assetId"]): fallback_asset_analysis(entry) for entry in batch}
            analyzed_by_id.update(analyzed)

    changed = False
    for entry in pending:
        asset_id = str(entry["assetId"])
        analysis = analyzed_by_id.get(asset_id) or fallback_asset_analysis(entry)
        results[asset_id] = analysis
        path = entry.get("path")
        if isinstance(path, Path) and path.exists() and str(analysis.get("source") or "") != "fallback":
            stat = path.stat()
            cache[asset_id] = {
                "size": int(stat.st_size),
                "mtimeNs": int(stat.st_mtime_ns),
                "name": str(entry.get("assetName") or asset_id),
                "analysis": analysis,
                "updatedAt": timestamp(),
            }
            changed = True
    if changed:
        write_asset_analysis_cache(cache)
    return results


def asset_analysis_line(analysis: dict[str, Any]) -> str:
    tags = analysis.get("tags") if isinstance(analysis.get("tags"), list) else []
    return (
        f"scanSource={text_value(analysis.get('source'), 40) or 'unknown'} scanKind={text_value(analysis.get('kind'), 80) or 'unknown'} "
        f"desc={text_value(analysis.get('description'), 420)} "
        f"tags={','.join(text_value(tag, 30) for tag in tags[:12])} "
        f"view={text_value(analysis.get('modelView'), 80)} crop={text_value(analysis.get('bodyCrop'), 80)} "
        f"focus={text_value(analysis.get('garmentFocus'), 180)} text={text_value(analysis.get('visibleText'), 240)} "
        f"suitable={text_value(analysis.get('suitableFor'), 220)} avoid={text_value(analysis.get('avoidFor'), 180)}"
    )


def asset_contact_sheet(
    asset_ids: list[str],
    asset_names: dict[str, str] | None = None,
    asset_dimensions: dict[str, tuple[int, int]] | None = None,
) -> tuple[Image.Image, list[dict[str, Any]]]:
    selected = asset_ids[:QWEN_MATCH_MAX_ASSETS]
    asset_names = asset_names or {}
    asset_dimensions = asset_dimensions or {}
    entries: list[dict[str, Any]] = []
    for index, asset_id in enumerate(selected, start=1):
        image_id = assigned_asset_id(asset_id)
        image_path = UPLOAD_DIR / image_id
        if not image_id or not image_path.exists():
            continue
        width, height = asset_dimensions.get(image_id, (0, 0))
        if not width or not height:
            width, height = image_size(image_path)
        entries.append(
            {
                "label": f"A{index:02d}",
                "assetId": image_id,
                "assetName": str(asset_names.get(image_id) or image_id),
                "width": int(width or 0),
                "height": int(height or 0),
                "path": image_path,
            }
        )

    if not entries:
        raise RuntimeError("没有可供 Qwen-VL 查看和匹配的素材图片")

    thumb = max(120, min(260, CONTACT_SHEET_THUMB))
    label_height = 44
    cell_w = thumb + 28
    cell_h = thumb + label_height + 28
    cols = min(5, max(1, math.ceil(math.sqrt(len(entries)))))
    rows = math.ceil(len(entries) / cols)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), (245, 246, 248))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for index, entry in enumerate(entries):
        col = index % cols
        row = index // cols
        x = col * cell_w + 14
        y = row * cell_h + 14
        draw.rectangle((x - 4, y - 4, x + thumb + 4, y + thumb + label_height + 8), fill=(255, 255, 255), outline=(180, 190, 200))
        try:
            thumb_path = THUMB_DIR / f"{Path(str(entry['assetId'])).stem}.jpg"
            source_path = thumb_path if thumb_path.exists() else entry["path"]
            with Image.open(source_path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
                paste_x = x + (thumb - image.width) // 2
                paste_y = y + (thumb - image.height) // 2
                sheet.paste(image, (paste_x, paste_y))
        except Exception:
            draw.rectangle((x, y, x + thumb, y + thumb), fill=(230, 230, 230))
        draw.rectangle((x, y, x + 54, y + 28), fill=(0, 0, 0))
        draw.text((x + 7, y + 8), entry["label"], fill=(255, 255, 255), font=font)
        name = entry["assetName"]
        if len(name) > 26:
            name = f"{name[:23]}..."
        draw.text((x, y + thumb + 8), f"{entry['label']} {name}", fill=(28, 35, 45), font=font)
    return sheet, entries


def contains_any_text(text: str, words: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(word.lower() in lowered for word in words)


def keyword_alignment_score(answer_text: str, asset_text: str) -> float:
    groups = (
        (("front", "正面", "正脸", "正身"), ("front", "正面", "正脸", "正身"), 7),
        (("back", "背面", "后背", "背影"), ("back", "背面", "后背", "背影"), 8),
        (("side", "侧面", "侧身", "侧拍"), ("side", "侧面", "侧身", "侧拍"), 5),
        (("full_body", "全身", "整身"), ("full_body", "全身", "整身"), 7),
        (("half_body", "半身", "上半身"), ("half_body", "upper_body", "半身", "上半身"), 6),
        (("fabric", "面料", "纹理", "肌理"), ("fabric", "texture", "面料", "纹理", "肌理"), 11),
        (("collar", "领口"), ("collar", "领口"), 7),
        (("cuff", "袖口"), ("cuff", "袖口"), 7),
        (("button", "纽扣", "扣子"), ("button", "buttons", "纽扣", "扣子"), 7),
        (("size chart", "尺码", "尺码表"), ("size chart", "尺码", "尺码表"), 18),
        (("weight", "体重", "身高", "推荐"), ("weight", "体重", "身高", "推荐"), 17),
        (("wash", "水洗", "洗护", "成分"), ("wash", "care", "水洗", "洗护", "成分"), 18),
        (("hang tag", "吊牌", "合格证", "tag information"), ("hang tag", "certificate", "吊牌", "合格证", "tag information"), 17),
        (("packaging", "包装"), ("packaging", "包装"), 8),
        (("留白", "横图", "横版"), ("landscape", "横图", "横版", "留白"), 5),
    )
    score = 0.0
    for answer_words, asset_words, weight in groups:
        if contains_any_text(answer_text, answer_words):
            score += weight if contains_any_text(asset_text, asset_words) else -min(5, weight / 2)
    return score


def answer_key_fill_score(slot: dict[str, Any], learned: dict[str, Any] | None, entry: dict[str, Any]) -> float:
    answer_text = slot_answer_contract(learned)
    analysis = entry.get("analysis") if isinstance(entry.get("analysis"), dict) else {}
    asset_text = " ".join(
        [
            str(entry.get("assetName") or ""),
            str(entry.get("assetId") or ""),
            asset_analysis_line(analysis),
        ]
    )
    slot_kind = semantic_kind_from_text(answer_text)
    asset_kind = asset_kind_from_entry(entry)
    label_kinds = {"size_chart", "weight_guide", "wash_label", "hang_tag"}
    score = 46.0

    if slot_kind and asset_kind:
        if slot_kind == asset_kind:
            score += 34
        elif slot_kind == "detail" and asset_kind == "detail":
            score += 30
        elif slot_kind == "model" and asset_kind == "model":
            score += 28
        elif slot_kind in label_kinds or asset_kind in label_kinds:
            score -= 34
        else:
            score += 6
    elif slot_kind:
        score -= 4
    else:
        score += 4

    score += keyword_alignment_score(answer_text, asset_text)

    try:
        slot_ratio = int(slot.get("w") or 1) / max(1, int(slot.get("h") or 1))
        asset_ratio = int(entry.get("width") or 1) / max(1, int(entry.get("height") or 1))
        ratio_delta = abs(slot_ratio - asset_ratio)
        if ratio_delta < 0.35:
            score += 4
        elif ratio_delta > 1.4:
            score -= 4
    except Exception:
        pass

    confidence = analysis.get("confidence") if isinstance(analysis, dict) else None
    try:
        score += (float(confidence) - 60) / 10
    except (TypeError, ValueError):
        pass
    return max(25.0, min(92.0, score))


def learned_slots_for_current_template(slots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    active = active_template_record(allow_missing=True)
    profile = read_style_profile(active["id"]) if active else {"slots": {}}
    learned_slots = profile.get("slots") if isinstance(profile.get("slots"), dict) else {}
    learned_by_index = learned_slot_by_index(learned_slots)
    result: dict[str, dict[str, Any]] = {}
    for index, slot in enumerate(slots, start=1):
        slot_id = str(slot.get("id") or "")
        learned = learned_slots.get(slot_id) if isinstance(learned_slots.get(slot_id), dict) else learned_by_index.get(index)
        if isinstance(learned, dict):
            result[slot_id] = learned
    return result


def complete_matches_by_fill_principle(
    slots: list[dict[str, Any]],
    asset_ids: list[str],
    asset_names: dict[str, str] | None = None,
    asset_dimensions: dict[str, tuple[int, int]] | None = None,
    existing_matches: list[dict[str, Any]] | None = None,
    entries: list[dict[str, Any]] | None = None,
    learned_by_slot_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    existing_matches = [match for match in (existing_matches or []) if match.get("slotId") and match.get("assetId")]
    if entries is None:
        asset_names = asset_names or {}
        asset_dimensions = asset_dimensions or {}
        entries = []
        for index, asset_id in enumerate(asset_ids[:QWEN_MATCH_MAX_ASSETS], start=1):
            image_id = assigned_asset_id(asset_id)
            image_path = UPLOAD_DIR / image_id
            if not image_id or not image_path.exists():
                continue
            width, height = asset_dimensions.get(image_id, (0, 0))
            if not width or not height:
                width, height = image_size(image_path)
            entries.append(
                {
                    "label": f"A{index:02d}",
                    "assetId": image_id,
                    "assetName": str(asset_names.get(image_id) or image_id),
                    "width": int(width or 0),
                    "height": int(height or 0),
                    "path": image_path,
                }
            )
        analyses = analyze_asset_entries(entries)
        for entry in entries:
            entry["analysis"] = analyses.get(str(entry["assetId"])) or fallback_asset_analysis(entry)
    else:
        missing = [entry for entry in entries if not isinstance(entry.get("analysis"), dict)]
        if missing:
            analyses = analyze_asset_entries(missing)
            for entry in missing:
                entry["analysis"] = analyses.get(str(entry["assetId"])) or fallback_asset_analysis(entry)
    learned_by_slot_id = learned_by_slot_id or learned_slots_for_current_template(slots)

    used_slots = {str(match["slotId"]) for match in existing_matches}
    used_assets = {str(match["assetId"]) for match in existing_matches}
    slot_by_id = {str(slot["id"]): slot for slot in slots}
    candidates: list[dict[str, Any]] = []
    for slot in slots:
        slot_id = str(slot["id"])
        if slot_id in used_slots:
            continue
        learned = learned_by_slot_id.get(slot_id)
        for entry in entries:
            asset_id = str(entry["assetId"])
            if asset_id in used_assets:
                continue
            score = answer_key_fill_score(slot, learned, entry)
            candidates.append(
                {
                    "slotId": slot_id,
                    "slotName": str(slot.get("name") or slot_id),
                    "assetId": asset_id,
                    "assetName": str(entry.get("assetName") or asset_id),
                    "score": round(score, 1),
                    "source": "answer-key-fill",
                    "learnedCount": int(learned.get("count") or 0) if isinstance(learned, dict) else 0,
                    "reason": "填满原则补位：按参考图文字意图和本地素材扫描结果选择最接近的一张",
                    "assetLabel": str(entry.get("label") or ""),
                }
            )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    completed = list(existing_matches)
    for candidate in candidates:
        slot_id = str(candidate["slotId"])
        asset_id = str(candidate["assetId"])
        if slot_id in used_slots or asset_id in used_assets:
            continue
        if slot_id not in slot_by_id:
            continue
        used_slots.add(slot_id)
        used_assets.add(asset_id)
        completed.append(candidate)
        if len(used_slots) >= len(slots) or len(used_assets) >= len(entries):
            break
    return completed


def strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    return text.strip()


def extract_json_object(text: str) -> dict[str, Any]:
    text = strip_thinking(text)
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    if not text.strip().startswith("{"):
        preview = re.sub(r"\s+", " ", text).strip()[:260]
        raise ValueError(f"Qwen-VL did not return JSON content: {preview}")
    return json.loads(text)


def slot_hint(slot: dict[str, Any], index: int, total: int, template_height: int) -> str:
    w = int(slot.get("w", 0))
    h = int(slot.get("h", 0))
    y = int(slot.get("y", 0))
    ratio = w / h if h else 1
    band = y / max(1, template_height)
    if index == 1 or band < 0.16:
        return "顶部/主视觉，通常放主模特、封面、强展示图"
    if band > 0.78:
        return "靠近底部，常放尺码表、体重推荐、细节说明或收尾图"
    if w >= 1200:
        return "横向大图位，适合场景图、整身图或强展示图"
    if ratio < 0.55:
        return "窄竖图位，适合竖版模特、局部细节"
    if ratio > 1.35:
        return "横图位，适合横向细节、表格、说明图"
    if w < 520 or h < 650:
        return "小图位，适合局部细节、卖点图、小说明图"
    return "中部图位，适合模特图、局部细节或面料展示"


def qwen_vl_match_assets(
    slots: list[dict[str, Any]],
    asset_ids: list[str],
    asset_names: dict[str, str] | None = None,
    asset_dimensions: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    model_settings = read_model_settings(include_key=True)
    use_api = model_settings.get("provider") != "ollama"
    if use_api:
        model = str(model_settings.get("model") or VISION_API_MODEL)
    else:
        configured_model = str(model_settings.get("model") or "").strip()
        model = configured_model if configured_model and configured_model != "gpt-5.5" else qwen_vision_model()
    build_template_cache()
    _, _, meta_json = template_cache_paths()
    template_meta = json.loads(meta_json.read_text("utf-8"))
    template_height = int(template_meta.get("height") or 1)
    sheet, entries = asset_contact_sheet(asset_ids, asset_names, asset_dimensions)
    asset_analyses = analyze_asset_entries(entries)
    for entry in entries:
        entry["analysis"] = asset_analyses.get(str(entry["assetId"])) or fallback_asset_analysis(entry)
    sheet_b64 = image_to_base64(sheet, max_width=CONTACT_SHEET_MAX_WIDTH)
    active = active_template_record(allow_missing=True)
    reference_sheet_b64 = ""
    if active and MATCH_INCLUDE_REFERENCE_IMAGE:
        reference_sheet_path = latest_reference_sheet_path(active["id"])
        if reference_sheet_path:
            try:
                with open_style_sample_image(reference_sheet_path) as reference_sheet:
                    reference_sheet_b64 = image_to_base64_fit(reference_sheet, 760, 2200, 66)
            except Exception:
                reference_sheet_b64 = ""
    profile = read_style_profile(active["id"]) if active else {"slots": {}}
    learned_slots = profile.get("slots") if isinstance(profile.get("slots"), dict) else {}
    learned_by_index_map = learned_slot_by_index(learned_slots)
    reference_summary = text_value(profile.get("referenceSummary"), 900)

    slot_lines: list[str] = []
    learned_by_slot_id: dict[str, dict[str, Any]] = {}
    semantic_count = 0
    for index, slot in enumerate(slots, start=1):
        w = int(slot.get("w", 0))
        h = int(slot.get("h", 0))
        ratio = round(w / h, 3) if h else 1
        slot_id = str(slot["id"])
        learned = learned_slots.get(slot_id) if isinstance(learned_slots.get(slot_id), dict) else learned_by_index_map.get(index)
        if isinstance(learned, dict):
            learned_by_slot_id[slot_id] = learned
        answer_contract = slot_answer_contract(learned)
        if answer_contract:
            semantic_count += 1
        slot_lines.append(
            f"{index}. slotId={slot_id} name={slot.get('name')} "
            f"pos=({slot.get('x')},{slot.get('y')}) size={w}x{h} aspect={ratio} "
            f"genericHint={slot_hint(slot, index, len(slots), template_height)} "
            f"ANSWER_KEY={answer_contract or 'none'}"
        )

    asset_lines = [
        f"{entry['label']}: assetId={entry['assetId']} name={entry['assetName']} "
        f"size={entry['width']}x{entry['height']} assetKind={asset_kind_from_entry(entry) or 'unknown'} "
        f"ASSET_SCAN={asset_analysis_line(entry.get('analysis') if isinstance(entry.get('analysis'), dict) else {})}"
        for entry in entries
    ]
    prompt = (
        "/no_think\n"
        "You are matching ecommerce long-image assets to template slots. "
        "The attached contact sheet contains candidate asset thumbnails. Each thumbnail has a label such as A01 or A02.\n"
        "Use the visual content, slot position, slot size, the learned answer key extracted from the user's annotated reference sheet, "
        "and ASSET_SCAN descriptions produced by scanning each local source image.\n"
        f"Learned reference summary: {reference_summary or 'none'}\n"
        f"Slots with learned reference notes: {semantic_count}/{len(slots)}. "
        "Treat every ANSWER_KEY as an authoritative slot contract, not a loose style hint. "
        "When ANSWER_KEY exists, it overrides generic ecommerce layout habits. "
        "Fill as many slots as possible. A slot should receive the best available asset for role/mustPrefer/answerText while avoiding mustAvoid. "
        "ASSET_SCAN is the primary evidence for each local image; use the contact sheet only as a visual cross-check. "
        "If no asset perfectly satisfies the ANSWER_KEY, choose the closest remaining asset and give a lower score instead of omitting the slot. "
        "Use genericHint only for slots without ANSWER_KEY.\n"
        "Strict rules: do not place model photos into fabric/detail/size-chart/weight-guide/tag/wash-label slots; "
        "do not place fabric, tag, chart, or text-heavy images into model/lifestyle slots unless the ANSWER_KEY explicitly asks for that kind. "
        "Respect sequence requirements from the reference text, including front/back/side/full-body/half-body, left/right whitespace, repeated or non-repeated poses, "
        "fabric texture, collar/cuff/buttons, size chart, body-weight recommendation, hang tag, wash label, packaging, and closing image. "
        "Use each asset at most once. Return one match per slot until either slots or assets run out. Give high scores only for exact answer-key matches.\n\n"
        "Images supplied: IMAGE 1 is the compressed candidate asset contact sheet. "
        "The user's annotated reference sheet has already been read into ANSWER_KEY text above.\n\n"
        + "Slots:\n" + "\n".join(slot_lines) + "\n\n"
        "Assets:\n" + "\n".join(asset_lines) + "\n\n"
        "Return only compact JSON, no markdown and no explanation. Format:\n"
        f'{{"matches":[{{"slotId":"...","assetLabel":"A01","score":0-100,"reason":"short Chinese reason"}}]}}\n'
        f"Target match count: {min(len(slots), len(entries))}."
    )
    if use_api:
        def request_match_with_sheet(sheet_image_b64: str, include_reference_image: bool = False) -> dict[str, Any]:
            content_parts: list[dict[str, Any]] = [
                {"type": "text", "text": f"{prompt}\n\nIMAGE 1: candidate asset contact sheet."},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{sheet_image_b64}"},
                },
            ]
            if include_reference_image and reference_sheet_b64:
                content_parts.extend(
                    [
                        {"type": "text", "text": "IMAGE 2: annotated reference answer sheet from the user. Treat this as the correct answer card."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{reference_sheet_b64}"},
                        },
                    ]
                )
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": content_parts,
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 2600,
            }
            return vision_api_request(
                payload,
                timeout=int(model_settings.get("timeout") or VISION_API_TIMEOUT),
                settings=model_settings,
            )

        try:
            response = request_match_with_sheet(sheet_b64, include_reference_image=bool(reference_sheet_b64))
        except RuntimeError as exc:
            if "HTTP 413" not in str(exc):
                raise
            response = request_match_with_sheet(image_to_base64(sheet, max_width=640), include_reference_image=False)
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
        content = str(message.get("content") or response.get("response") or "")
    else:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": f"{prompt}\n\nImage order: 1=candidate asset contact sheet, 2=annotated answer sheet if present.",
                    "images": [sheet_b64] + ([reference_sheet_b64] if reference_sheet_b64 else []),
                }
            ],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.8,
                "num_predict": 2600,
            },
        }
        response = ollama_request("/api/chat", payload)
        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        content = str(message.get("content") or response.get("response") or "")
        if not content.strip():
            content = str(message.get("thinking") or response.get("thinking") or "")
    parsed = extract_json_object(content)
    raw_matches = parsed.get("matches") if isinstance(parsed.get("matches"), list) else []

    label_to_asset = {entry["label"].upper(): entry for entry in entries}
    asset_by_id = {entry["assetId"]: entry for entry in entries}
    slot_by_id = {str(slot["id"]): slot for slot in slots}
    slot_by_index = {str(index): slot for index, slot in enumerate(slots, start=1)}
    matches: list[dict[str, Any]] = []
    for raw in raw_matches:
        if not isinstance(raw, dict):
            continue
        slot_id = str(raw.get("slotId") or "")
        if not slot_id and raw.get("slotIndex") is not None:
            slot = slot_by_index.get(str(raw.get("slotIndex")))
            slot_id = str(slot["id"]) if slot else ""
        asset_label = str(raw.get("assetLabel") or raw.get("label") or "").upper().strip()
        if asset_label and re.fullmatch(r"A\d+", asset_label):
            asset_label = f"A{int(asset_label[1:]):02d}"
        elif asset_label and re.fullmatch(r"\d+", asset_label):
            asset_label = f"A{int(asset_label):02d}"
        entry = label_to_asset.get(asset_label)
        if not entry and raw.get("assetId"):
            entry = asset_by_id.get(assigned_asset_id(str(raw.get("assetId"))))
        slot = slot_by_id.get(slot_id)
        if not entry or not slot:
            continue
        try:
            score = float(raw.get("score", 82))
        except (TypeError, ValueError):
            score = 82
        if score <= 0:
            continue
        if not compatible_asset_for_slot(learned_by_slot_id.get(slot_id), entry):
            continue
        learned = learned_by_slot_id.get(slot_id)
        learned_count = int(learned.get("count") or 0) if isinstance(learned, dict) else 0
        matches.append(
            {
                "slotId": slot_id,
                "slotName": str(slot.get("name") or slot_id),
                "assetId": entry["assetId"],
                "assetName": entry["assetName"],
                "score": max(0, min(100, round(score, 1))),
                "source": "answer-key-api" if use_api and learned_count else ("answer-key-qwen" if learned_count else ("vision-api" if use_api else "qwen-vl")),
                "learnedCount": learned_count,
                "reason": str(raw.get("reason") or ("Vision API visual match" if use_api else "Qwen-VL visual match")),
                "assetLabel": entry["label"],
            }
        )

    matches.sort(key=lambda item: item["score"], reverse=True)
    used_slots: set[str] = set()
    used_assets: set[str] = set()
    unique_matches: list[dict[str, Any]] = []
    for match in matches:
        if match["slotId"] in used_slots or match["assetId"] in used_assets:
            continue
        used_slots.add(match["slotId"])
        used_assets.add(match["assetId"])
        unique_matches.append(match)
    unique_matches = complete_matches_by_fill_principle(
        slots,
        asset_ids,
        asset_names,
        asset_dimensions,
        existing_matches=unique_matches,
        entries=entries,
        learned_by_slot_id=learned_by_slot_id,
    )
    if not unique_matches:
        raise RuntimeError("Qwen-VL returned no usable matches")
    return {"matches": unique_matches, "model": model, "raw": content, "provider": "api" if use_api else "ollama"}


def style_match_assets(slots: list[dict[str, Any]], asset_ids: list[str]) -> list[dict[str, Any]]:
    slot_features = slot_reference_features(slots)

    asset_features: dict[str, list[float]] = {}
    for asset_id in asset_ids:
        image_id = assigned_asset_id(asset_id)
        image_path = UPLOAD_DIR / image_id
        if not image_id or not image_path.exists():
            continue
        try:
            with Image.open(image_path) as image:
                asset_features[image_id] = visual_feature(image)
        except Exception:
            continue

    candidates: list[dict[str, Any]] = []
    slot_by_id = {str(slot["id"]): slot for slot in slots}
    for slot_id, slot_reference in slot_features.items():
        for asset_id, asset_feature in asset_features.items():
            score = reference_score(slot_reference, asset_feature)
            slot = slot_by_id.get(slot_id, {})
            asset = asset_payload(asset_id) or {"id": asset_id, "name": asset_id}
            candidates.append(
                {
                    "slotId": slot_id,
                    "slotName": str(slot.get("name") or slot_id),
                    "assetId": asset_id,
                    "assetName": str(asset.get("name") or asset_id),
                    "score": score,
                    "source": slot_reference.get("source", "template"),
                    "learnedCount": int(slot_reference.get("count") or 0),
                }
            )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    used_slots: set[str] = set()
    used_assets: set[str] = set()
    matches: list[dict[str, Any]] = []
    for candidate in candidates:
        slot_id = str(candidate["slotId"])
        asset_id = str(candidate["assetId"])
        if slot_id in used_slots or asset_id in used_assets:
            continue
        used_slots.add(slot_id)
        used_assets.add(asset_id)
        matches.append(candidate)
        if len(used_slots) >= len(slot_features):
            break
    return matches


def make_thumb(source: Path, thumb_name: str, max_size: int = 360) -> Path:
    target = THUMB_DIR / thumb_name
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        image.save(target, quality=82, optimize=True)
    return target


def ocr_engine() -> Any:
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def run_ocr(path: Path) -> list[str]:
    result, _ = ocr_engine()(str(path))
    lines: list[str] = []
    for item in result or []:
        if len(item) >= 2 and item[1]:
            lines.append(str(item[1]).strip())
    return [line for line in lines if line]


def parse_product_info(lines: list[str]) -> dict[str, Any]:
    text = "\n".join(lines)
    compact = re.sub(r"\s+", "", text)

    fields: dict[str, Any] = {
        "brand": "",
        "number": "",
        "fabric": "",
        "sizes": [],
        "weights": [],
        "rawText": text,
    }

    brand_match = re.search(r"(?:品牌|BRAND)[:：]?\s*([A-Za-z0-9\u4e00-\u9fa5-]+)", text, re.I)
    if brand_match:
        fields["brand"] = brand_match.group(1).strip()

    fabric_match = re.search(r"(?:商品面料|面料|材质|FABRIC)(?:/商品面料)?[:：]?\s*([^\n]+)", text, re.I)
    if fabric_match:
        fields["fabric"] = re.sub(r"^[/:：\s]+", "", fabric_match.group(1).strip())

    number_match = re.search(r"(?:货号|编号|MUMBER|NUMBER)[:：]?\s*([A-Za-z0-9-]+)", text, re.I)
    if number_match:
        fields["number"] = number_match.group(1).strip()

    size_lines = [line for line in lines if re.search(r"尺码|SIZE|\bXS\b|\bXL\b|\b2XL\b|\b3XL\b", line, re.I)]
    size_text = "\n".join(size_lines) if size_lines else text
    size_text = re.sub(r"(?<=[MLFS])(?=XL|L|M|S|F|\dXL)", " ", size_text, flags=re.I)
    size_names = re.findall(r"(?:XS|XXL|2XL|3XL|4XL|5XL|XL|S|M|L|F)", size_text, re.I)
    size_names = [size.upper().replace("XXL", "2XL") for size in size_names]
    seen = []
    for size in size_names:
        if size not in seen:
            seen.append(size)
    fields["sizes"] = seen[:8]

    weights = re.findall(r"(\d{2,3}\s*[-~—]\s*\d{2,3}\s*(?:斤|F)?)", compact)
    fields["weights"] = [weight.replace(" ", "").replace("F", "斤") for weight in weights[:8]]
    return fields


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", size)


def draw_product_info(result: Image.Image, info: dict[str, Any]) -> None:
    if not info:
        return
    draw = ImageDraw.Draw(result)
    black = (55, 55, 55, 255)
    small = font(32)
    normal = font(38)

    brand = str(info.get("brand") or "").strip()
    number = str(info.get("number") or "").strip()
    fabric = str(info.get("fabric") or "").strip()
    sizes = info.get("sizes") or []
    weights = info.get("weights") or []

    if brand:
        draw.text((520, 16300), brand, fill=black, font=normal)
    if number:
        draw.text((1210, 16298), number, fill=black, font=normal)
    if fabric:
        draw.text((610, 16380), fabric[:22], fill=black, font=normal)

    # 尺码表区域：当前模板默认列为 M/L/XL，先覆盖常见的尺码与体重建议。
    size_y = 17491
    for idx, size in enumerate(sizes[:5]):
        draw.text((72, size_y + 100 + idx * 100), str(size), fill=black, font=small)

    weight_y = 18152
    for idx, weight in enumerate(weights[:5]):
        draw.text((640, weight_y + 100 + idx * 100), str(weight), fill=black, font=small)


def draw_text_in_slot(result: Image.Image, lines: list[str], slot: dict[str, Any]) -> None:
    if not lines:
        return
    draw = ImageDraw.Draw(result)
    x = int(slot["x"])
    y = int(slot["y"])
    w = int(slot["w"])
    h = int(slot["h"])
    size = max(20, min(42, h // max(5, len(lines) + 1)))
    line_font = font(size)
    line_height = int(size * 1.35)
    max_chars = max(6, w // max(1, size))
    yy = y + 12
    for raw in lines:
        line = str(raw).strip()
        while line and yy + line_height <= y + h:
            chunk = line[:max_chars]
            draw.text((x + 12, yy), chunk, fill=(45, 45, 45, 255), font=line_font)
            yy += line_height
            line = line[max_chars:]
        if yy + line_height > y + h:
            break


def clear_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for item in path.iterdir():
        if item.is_file():
            item.unlink()


def cut_inside_slot(y: int, slots: list[dict[str, Any]], margin: int = 10) -> bool:
    for slot in slots:
        if not slot.get("visible", True):
            continue
        top = int(slot.get("y", 0))
        bottom = top + int(slot.get("h", 0))
        if top + margin < y < bottom - margin:
            return True
    return False


def row_near_slot(y: int, slot_ranges: list[tuple[int, int]], margin: int = 24) -> bool:
    return any(top - margin <= y <= bottom + margin for top, bottom in slot_ranges)


def detect_dark_separator_bands(image: Image.Image, slots: list[dict[str, Any]]) -> list[int]:
    width, height = image.size
    if width <= 0 or height <= EXPORT_SPLIT_MIN_PART_HEIGHT * 2:
        return []

    sample_width = min(360, max(120, width // 3))
    sample = image.convert("RGB").resize((sample_width, height), Image.Resampling.BOX)
    pixels = sample.load()
    slot_ranges = [
        (int(slot.get("y", 0)), int(slot.get("y", 0)) + int(slot.get("h", 0)))
        for slot in slots
        if int(slot.get("h", 0)) > 0
    ]
    dark_rows: list[int] = []

    for y in range(height):
        if row_near_slot(y, slot_ranges):
            continue
        dark = 0
        total = 0
        for x in range(sample_width):
            r, g, b = pixels[x, y]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            total += lum
            if lum < 72:
                dark += 1
        dark_frac = dark / sample_width
        avg = total / sample_width
        if dark_frac >= 0.92 and avg <= 72:
            dark_rows.append(y)

    groups: list[list[int]] = []
    for y in dark_rows:
        if not groups or y - groups[-1][-1] > 8:
            groups.append([y])
        else:
            groups[-1].append(y)

    positions: list[int] = []
    for group in groups:
        top = group[0]
        bottom = group[-1]
        band_height = bottom - top + 1
        if band_height < 12:
            continue
        cut = (top + bottom) // 2
        if not cut_inside_slot(cut, slots):
            positions.append(cut)
    return positions


def detect_full_width_section_starts(image: Image.Image, slots: list[dict[str, Any]]) -> list[int]:
    width, height = image.size
    positions: list[int] = []
    edge_margin = max(16, int(width * 0.03))
    min_width = int(width * EXPORT_SPLIT_FULL_WIDTH_SLOT_RATIO)
    for slot in slots:
        if not slot.get("visible", True):
            continue
        x = int(slot.get("x", 0))
        y = int(slot.get("y", 0))
        w = int(slot.get("w", 0))
        if y <= 0 or y >= height:
            continue
        reaches_edges = x <= edge_margin and x + w >= width - edge_margin
        if w >= min_width and reaches_edges and not cut_inside_slot(y, slots):
            positions.append(y)
    return positions


def detect_export_split_positions(image: Image.Image, slots: list[dict[str, Any]]) -> list[int]:
    width, height = image.size
    template_guides = read_template_split_guides(active_template_path(), width, height)
    if template_guides:
        safe_template_guides = [
            y for y in template_guides
            if not cut_inside_slot(y, slots)
        ]
        return normalize_split_positions(
            safe_template_guides,
            width,
            height,
            min_part_height=EXPORT_SPLIT_EXPLICIT_MIN_PART_HEIGHT,
        )

    candidates = [
        *detect_dark_separator_bands(image, slots),
        *detect_full_width_section_starts(image, slots),
    ]
    safe_candidates = [
        y for y in sorted(set(candidates))
        if not cut_inside_slot(y, slots)
    ]
    return normalize_split_positions(safe_candidates, width, height)


def export_ranges(height: int, positions: list[int]) -> list[tuple[int, int]]:
    points = [0, *positions, height]
    ranges: list[tuple[int, int]] = []
    for top, bottom in zip(points, points[1:]):
        if bottom - top <= 0:
            continue
        ranges.append((top, bottom))
    return ranges


def export_image_bytes(image: Image.Image, output_format: str) -> bytes:
    buffer = io.BytesIO()
    if output_format == "png":
        image.save(buffer, format="PNG")
    else:
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        background.save(buffer, format="JPEG", quality=95, optimize=True)
    return buffer.getvalue()


def save_export_image(image: Image.Image, path: Path, output_format: str) -> None:
    if output_format == "png":
        image.save(path)
    else:
        path.write_bytes(export_image_bytes(image, output_format))


def save_split_zip(
    image: Image.Image,
    positions: list[int],
    output_format: str,
    target: Path,
) -> int:
    extension = "png" if output_format == "png" else "jpg"
    ranges = export_ranges(image.height, positions)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, (top, bottom) in enumerate(ranges, start=1):
            part = image.crop((0, top, image.width, bottom))
            archive.writestr(f"export_{index:02d}.{extension}", export_image_bytes(part, output_format))
    return len(ranges)


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/model-settings")
def api_get_model_settings() -> Any:
    return jsonify({"ok": True, "settings": read_model_settings(include_key=False)})


@app.post("/api/model-settings")
def api_save_model_settings() -> Any:
    payload = request.get_json(force=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid settings payload"}), 400
    current = read_model_settings(include_key=True)
    api_key = str(payload.get("apiKey") or "").strip()
    if payload.get("clearApiKey"):
        current["apiKey"] = ""
    elif api_key:
        current["apiKey"] = api_key
    for key in ("provider", "baseUrl", "model", "timeout"):
        if key in payload:
            current[key] = payload.get(key)
    settings = write_model_settings(current)
    return jsonify({"ok": True, "settings": settings})


@app.get("/api/meta")
def api_meta() -> Any:
    if not has_active_template():
        return jsonify(
            {
                "empty": True,
                "templates": template_payloads(),
                "activeTemplateId": None,
                "template": {
                    "width": 2400,
                    "height": 1800,
                    "previewWidth": 1200,
                    "previewHeight": 900,
                    "scale": 0.5,
                    "templateImage": "",
                    "topOverlayImage": "",
                    "topOverlayPreviewImage": "",
                    "previewImage": "",
                },
                "slots": [],
                "assets": [],
                "assignments": {},
                "transforms": {},
                "fit": "cover",
            }
    )
    try:
        meta = build_template_cache()
        slots = read_or_detect_slots()
        active = active_template_record(allow_missing=True)
        template_state = read_template_state(active["id"], slots) if active else normalize_template_state({})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(
        {
            "template": meta,
            "slots": slots,
            **template_state,
            "templates": template_payloads(),
            "activeTemplateId": active["id"] if active else None,
        }
    )


@app.post("/api/new-template")
def api_new_template() -> Any:
    if ACTIVE_TEMPLATE_PATH.exists():
        ACTIVE_TEMPLATE_PATH.unlink()
    return jsonify(
        {
            "ok": True,
            "empty": True,
            "templates": template_payloads(),
            "activeTemplateId": None,
            "assets": [],
            "assignments": {},
            "transforms": {},
            "fit": "cover",
        }
    )


@app.get("/api/templates")
def api_templates() -> Any:
    active = active_template_record(allow_missing=True, records=ensure_template_library())
    return jsonify({"templates": template_payloads(), "activeTemplateId": active["id"] if active else None})


@app.post("/api/templates/<template_id>/activate")
def api_activate_template(template_id: str) -> Any:
    try:
        record = set_active_template_id(template_id)
        meta = build_template_cache()
        slots = read_or_detect_slots()
        template_state = read_template_state(record["id"], slots)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(
        {
            "ok": True,
            "template": meta,
            "slots": slots,
            **template_state,
            "templates": template_payloads(),
            "activeTemplateId": record["id"],
        }
    )


@app.patch("/api/templates/<template_id>")
def api_rename_template(template_id: str) -> Any:
    payload = request.get_json(force=True)
    name = str(payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "模板名称不能为空"}), 400
    records = ensure_template_library()
    record = next((item for item in records if item["id"] == template_id), None)
    if not record:
        return jsonify({"error": "找不到模板"}), 404
    record["name"] = name
    record["updatedAt"] = timestamp()
    write_template_records(records)
    active = active_template_record(allow_missing=True, records=records)
    if active and active["id"] == template_id:
        ACTIVE_TEMPLATE_PATH.write_text(
            json.dumps({"id": record["id"], "path": record["path"], "name": record["name"]}, ensure_ascii=False, indent=2),
            "utf-8",
        )
    return jsonify({"ok": True, "templates": template_payloads(), "activeTemplateId": active["id"] if active else None})


@app.delete("/api/templates/<template_id>")
def api_delete_template(template_id: str) -> Any:
    records = ensure_template_library()
    index = next((idx for idx, item in enumerate(records) if item["id"] == template_id), None)
    if index is None:
        return jsonify({"error": "找不到模板"}), 404
    active_data = legacy_active_data()
    record = records.pop(index)
    was_active = active_data.get("id") == template_id or active_data.get("path") == record["path"]

    slot_path = template_slots_path(record["id"])
    if slot_path.exists():
        slot_path.unlink()
    state_path = template_state_path(record["id"])
    if state_path.exists():
        state_path.unlink()
    profile_path = template_style_profile_path(record["id"])
    if profile_path.exists():
        profile_path.unlink()
    example_dir = template_style_example_dir(record["id"])
    if example_dir.exists() and is_path_under(example_dir, STYLE_EXAMPLE_DIR):
        shutil.rmtree(example_dir)

    template_path = Path(record["path"])
    if template_path.exists() and is_path_under(template_path, TEMPLATE_DIR):
        template_path.unlink()
    companion_overlay = template_companion_overlay_path(template_path)
    if companion_overlay.exists() and is_path_under(companion_overlay, TEMPLATE_DIR):
        companion_overlay.unlink()
    companion_splits = template_companion_split_path(template_path)
    if companion_splits.exists() and is_path_under(companion_splits, TEMPLATE_DIR):
        companion_splits.unlink()

    write_template_records(records)
    if was_active:
        if records:
            next_record = records[min(index, len(records) - 1)]
            ACTIVE_TEMPLATE_PATH.write_text(
                json.dumps(
                    {"id": next_record["id"], "path": next_record["path"], "name": next_record["name"]},
                    ensure_ascii=False,
                    indent=2,
                ),
                "utf-8",
            )
        elif ACTIVE_TEMPLATE_PATH.exists():
            ACTIVE_TEMPLATE_PATH.unlink()
    current_active = active_template_record(allow_missing=True, records=records)
    return jsonify(
        {
            "ok": True,
            "templates": template_payloads(),
            "activeTemplateId": current_active["id"] if current_active else None,
        }
    )


@app.get("/api/template-image")
def api_template_image() -> Any:
    build_template_cache()
    template_png, preview_jpg, _ = template_cache_paths()
    overlay_png = template_overlay_path()
    overlay_preview_png = template_overlay_preview_path()
    kind = request.args.get("kind", "preview")
    if kind == "full":
        return send_file(template_png)
    if kind == "overlay":
        return send_file(overlay_png)
    if kind == "overlay-preview":
        return send_file(overlay_preview_png)
    return send_file(preview_jpg)


@app.post("/api/slots")
def api_slots() -> Any:
    payload = request.get_json(force=True)
    slots = payload.get("slots", [])
    write_slots(slots)
    return jsonify({"ok": True, "slots": read_slots()})


@app.post("/api/slots/clear")
def api_clear_slots() -> Any:
    clear_slots()
    return jsonify({"ok": True, "slots": []})


@app.post("/api/template-state")
def api_template_state() -> Any:
    if not has_active_template():
        return jsonify({"error": "当前没有活动模板"}), 400
    payload = request.get_json(force=True)
    active = active_template_record()
    assert active is not None
    slots = read_slots()
    template_state = write_template_state(payload if isinstance(payload, dict) else {}, active["id"], slots)
    return jsonify({"ok": True, **template_state})


@app.post("/api/style-examples")
def api_style_examples() -> Any:
    if not has_active_template():
        return jsonify({"error": "当前没有活动模板"}), 400
    raw_slots = request.form.get("slots", "")
    try:
        parsed_slots = json.loads(raw_slots) if raw_slots else None
    except json.JSONDecodeError:
        parsed_slots = None
    slots = normalize_slots(parsed_slots) if isinstance(parsed_slots, list) else read_slots()
    if not slots:
        return jsonify({"error": "当前模板还没有图片位，先识别或新增图片位"}), 400
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "没有收到成片图片"}), 400

    result = learn_style_examples(files, slots)
    return jsonify(
        {
            "ok": True,
            "accepted": result["accepted"],
            "skipped": result["skipped"],
            "learnedCrops": result["learnedCrops"],
            "profiledSlots": result["profiledSlots"],
            "semanticHints": result.get("semanticHints", 0),
            "semanticErrors": result.get("semanticErrors", []),
            "exampleCount": result["profile"].get("exampleCount", 0),
        }
    )


@app.post("/api/style-profile/clear")
def api_clear_style_profile() -> Any:
    if not has_active_template():
        return jsonify({"error": "当前没有活动模板"}), 400
    active = active_template_record()
    assert active is not None
    profile_path = template_style_profile_path(active["id"])
    if profile_path.exists():
        profile_path.unlink()
    return jsonify({"ok": True, "exampleCount": 0, "profiledSlots": 0})


@app.post("/api/auto-match-style")
def api_auto_match_style() -> Any:
    if not has_active_template():
        return jsonify({"error": "当前没有活动模板"}), 400
    payload = request.get_json(force=True)
    payload_slots = payload.get("slots")
    all_slots = normalize_slots(payload_slots) if isinstance(payload_slots, list) and payload_slots else read_or_detect_slots()
    ordered_slots = style_match_target_slots(all_slots)
    raw_asset_ids = payload.get("assetIds") if isinstance(payload.get("assetIds"), list) else []
    raw_assets = payload.get("assets") if isinstance(payload.get("assets"), list) else []
    asset_names: dict[str, str] = {}
    asset_dimensions: dict[str, tuple[int, int]] = {}
    for item in raw_asset_ids + raw_assets:
        if not isinstance(item, dict):
            continue
        image_id = assigned_asset_id(item)
        if image_id and item.get("name"):
            asset_names[image_id] = str(item.get("name"))
        if image_id:
            try:
                width = int(item.get("width") or 0)
                height = int(item.get("height") or 0)
            except (TypeError, ValueError):
                width = 0
                height = 0
            if width > 0 and height > 0:
                asset_dimensions[image_id] = (width, height)
    asset_ids = [assigned_asset_id(item) for item in raw_asset_ids]
    asset_ids = [asset_id for asset_id in dict.fromkeys(asset_ids) if asset_id]

    if not ordered_slots:
        return jsonify({"error": "当前模板还没有图片位"}), 400
    if not asset_ids:
        return jsonify({"error": "没有可用于视觉匹配的素材"}), 400

    engine = "qwen-vl"
    model = ""
    qwen_error = ""
    if not MATCH_USE_VISION_API:
        try:
            matches = complete_matches_by_fill_principle(ordered_slots, asset_ids, asset_names, asset_dimensions)
            engine = "answer-key-api-scan-fill" if MATCH_SCAN_ASSETS_WITH_API else "answer-key-fill"
        except Exception as fallback_exc:
            return jsonify({"error": f"快速填满失败：{fallback_exc}"}), 500
        qwen_error = "final-vision-match-disabled; asset-content-scan-enabled" if MATCH_SCAN_ASSETS_WITH_API else "vision-api-disabled-fast-fill"
    else:
        try:
            qwen_result = qwen_vl_match_assets(ordered_slots, asset_ids, asset_names, asset_dimensions)
            matches = qwen_result["matches"]
            model = str(qwen_result.get("model") or "")
            engine = "vision-api" if qwen_result.get("provider") == "api" else "qwen-vl"
        except Exception as exc:
            qwen_error = str(exc)
            active = active_template_record(allow_missing=True)
            profile = read_style_profile(active["id"]) if active else {"slots": {}}
            learned_slots = profile.get("slots") if isinstance(profile.get("slots"), dict) else {}
            semantic_count = len(
                [
                    item
                    for item in learned_slots.values()
                    if isinstance(item, dict) and slot_semantic_hint(item)
                ]
            )
            if semantic_count:
                try:
                    matches = complete_matches_by_fill_principle(ordered_slots, asset_ids, asset_names, asset_dimensions)
                    engine = "answer-key-fill"
                except Exception as fallback_exc:
                    return jsonify({"error": f"答案卡匹配失败，填满补位也失败：{qwen_error}；补位错误：{fallback_exc}"}), 500
                if not matches:
                    return jsonify({"error": f"答案卡匹配没有可用结果：{qwen_error}"}), 500
            else:
                try:
                    matches = style_match_assets(ordered_slots, asset_ids)
                    engine = "local-feature"
                except Exception as fallback_exc:
                    return jsonify({"error": f"视觉匹配失败：Qwen-VL={qwen_error}；本地特征={fallback_exc}"}), 500

    assignments = {match["slotId"]: match["assetId"] for match in matches}
    transforms = {match["slotId"]: {"x": 0, "y": 0, "scale": 1} for match in matches}
    learned_matches = len(
        [
            match
            for match in matches
            if int(match.get("learnedCount") or 0) > 0 or "learned" in str(match.get("source") or "")
        ]
    )
    return jsonify(
        {
            "ok": True,
            "matches": matches,
            "assignments": assignments,
            "transforms": transforms,
            "matched": len(matches),
            "engine": engine,
            "model": model,
            "qwenError": qwen_error,
            "learnedMatched": learned_matches,
            "slotCount": len(ordered_slots),
            "totalSlotCount": len(all_slots),
            "skippedSlotCount": len(all_slots) - len(ordered_slots),
            "assetCount": len(asset_ids),
        }
    )


@app.post("/api/detect-slots")
def api_detect_slots() -> Any:
    try:
        slots = detect_and_save_slots()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "slots": slots})


@app.post("/api/template/append")
def api_template_append() -> Any:
    if not has_active_template():
        return jsonify({"error": "当前没有可追加的模板"}), 400
    ensure_dirs()
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "没有收到要追加的 PSD/PSB 模板"}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in PSD_TEMPLATE_EXTENSIONS:
        return jsonify({"error": "只能追加 PSD/PSB 模板"}), 400

    source_path = TEMPLATE_DIR / f"template_part_{uuid.uuid4().hex}{ext}"
    current = active_template_record()
    assert current is not None
    current_slots = read_or_detect_slots()
    current_state = read_template_state(current["id"], current_slots)

    try:
        build_template_cache()
        template_png, _, _ = template_cache_paths()
        with Image.open(template_png) as image:
            base_image = image.convert("RGBA").copy()
        with Image.open(template_overlay_path()) as image:
            base_overlay = image.convert("RGBA").copy()

        file.save(source_path)
        psd, appended_image, appended_overlay = render_psd_template(source_path)
        appended_slots = slots_from_rendered_psd(psd, appended_image)
        y_offset = base_image.height
        appended_slots = offset_appended_slots(appended_slots, 0, y_offset, {slot["id"] for slot in current_slots})

        composite_path = save_composite_template(base_image, base_overlay, appended_image, appended_overlay)
        base_split_guides = read_template_split_guides(Path(current["path"]), base_image.width, base_image.height)
        appended_split_guides = read_template_split_guides(source_path, appended_image.width, appended_image.height)
        split_guides = [
            *base_split_guides,
            y_offset,
            *[y_offset + y for y in appended_split_guides],
        ]
        write_template_split_guides(
            composite_path,
            split_guides,
            max(base_image.width, appended_image.width),
            base_image.height + appended_image.height,
        )
        name = f"{current.get('name') or Path(current['path']).stem} + {Path(file.filename).stem}"
        record = set_active_template(composite_path, name=name, original_name=f"{current.get('originalName') or current['name']} + {file.filename}")
        write_slots([*current_slots, *appended_slots])
        template_state = write_template_state(current_state, record["id"], [*current_slots, *appended_slots])
        meta = build_template_cache()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        if source_path.exists() and is_path_under(source_path, TEMPLATE_DIR):
            source_path.unlink()

    return jsonify(
        {
            "ok": True,
            "template": meta,
            "slots": read_slots(),
            **template_state,
            "templates": template_payloads(),
            "activeTemplateId": record["id"],
        }
    )


@app.post("/api/template")
def api_template_upload() -> Any:
    ensure_dirs()
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "没有收到 PSD/PSB 模板"}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in {".psd", ".psb"}:
        return jsonify({"error": "只支持 PSD/PSB 模板"}), 400
    target = TEMPLATE_DIR / f"template_{uuid.uuid4().hex}{ext}"
    file.save(target)
    record = set_active_template(target, name=Path(file.filename).stem, original_name=file.filename)
    template_slots_path(record["id"]).write_text("[]", "utf-8")
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    ensure_dirs()
    meta = build_template_cache()
    write_template_split_guides(
        target,
        extract_psd_split_positions(target, int(meta["width"]), int(meta["height"])),
        int(meta["width"]),
        int(meta["height"]),
    )
    slots = detect_and_save_slots()
    write_template_state({}, record["id"])
    return jsonify(
        {
            "ok": True,
            "template": meta,
            "slots": slots,
            "assets": [],
            "assignments": {},
            "transforms": {},
            "fit": "cover",
            "templates": template_payloads(),
            "activeTemplateId": record["id"],
        }
    )


@app.post("/api/upload")
def api_upload() -> Any:
    ensure_dirs()
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "没有收到图片文件"}), 400
    ext = Path(file.filename).suffix.lower() or ".png"
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
        return jsonify({"error": "只支持常见图片格式"}), 400
    filename = f"{uuid.uuid4().hex}{ext}"
    target = UPLOAD_DIR / filename
    file.save(target)
    thumb_name = f"{Path(filename).stem}.jpg"
    make_thumb(target, thumb_name)
    width, height = image_size(target)
    return jsonify(
        {
            "id": filename,
            "url": f"/api/upload/{filename}",
            "thumbUrl": f"/api/thumb/{thumb_name}",
            "name": file.filename,
            "width": width,
            "height": height,
        }
    )


@app.get("/api/upload/<filename>")
def api_upload_file(filename: str) -> Any:
    return send_file(UPLOAD_DIR / filename)


@app.get("/api/thumb/<filename>")
def api_thumb_file(filename: str) -> Any:
    return send_file(THUMB_DIR / filename)


@app.post("/api/recognize-product-info")
def api_recognize_product_info() -> Any:
    ensure_dirs()
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "没有收到水洗标/尺码图片"}), 400

    all_lines: list[str] = []
    saved: list[str] = []
    for file in files:
        if not file or not file.filename:
            continue
        ext = Path(file.filename).suffix.lower() or ".png"
        filename = f"ocr_{uuid.uuid4().hex}{ext}"
        target = UPLOAD_DIR / filename
        file.save(target)
        saved.append(filename)
        all_lines.extend(run_ocr(target))

    info = parse_product_info(all_lines)
    return jsonify({"ok": True, "files": saved, "lines": all_lines, "info": info})


@app.post("/api/export")
def api_export() -> Any:
    ensure_dirs()
    build_template_cache()
    payload = request.get_json(force=True)
    assignments = payload.get("assignments", {})
    transforms = payload.get("transforms", {})
    fit_mode = payload.get("fit", "cover")
    render_mode = payload.get("renderMode", "fast")
    output_format = payload.get("format", "jpg").lower()
    payload_slots = payload.get("slots")
    ordered_slots = normalize_slots(payload_slots) if isinstance(payload_slots, list) else read_slots()
    slots = {slot["id"]: slot for slot in ordered_slots}

    if render_mode == "precise" and is_psd_template_path(active_template_path()):
        replaced_layer_keys = {
            str(slot.get("layer_key"))
            for slot in ordered_slots
            if assignments.get(slot["id"]) and slot.get("layer_key")
        }
        result = fast_template_image(load_psd(), skip_layer_keys=replaced_layer_keys)
    else:
        template_png, _, _ = template_cache_paths()
        result = Image.open(template_png).convert("RGBA")

    def draw_assigned_slot(slot: dict[str, Any]) -> None:
        slot_id = slot["id"]
        image_id = assignments.get(slot_id)
        if isinstance(image_id, dict):
            image_id = image_id.get("assetId") or image_id.get("id")
        if not image_id or slot_id not in slots:
            return
        image_path = UPLOAD_DIR / str(image_id)
        if not image_path.exists():
            return
        with Image.open(image_path) as src:
            slot_transform = transforms.get(slot_id) if isinstance(transforms, dict) else None
            fitted = transform_fit(src, int(slot["w"]), int(slot["h"]), fit_mode, slot_transform)
            fitted = apply_slot_shape(fitted, slot)
        alpha_composite_clipped(result, fitted, int(slot["x"]), int(slot["y"]))

    for slot in reversed(ordered_slots):
        draw_assigned_slot(slot)

    overlay = Image.open(template_overlay_path()).convert("RGBA")
    alpha_composite_clipped(result, overlay, 0, 0)

    clear_dir(OUTPUT_DIR)
    if payload.get("splitByDividers"):
        split_positions = detect_export_split_positions(result, ordered_slots)
        out = OUTPUT_DIR / "export_split.zip"
        part_count = save_split_zip(result, split_positions, output_format, out)
        return jsonify(
            {
                "ok": True,
                "url": f"/api/output/{out.name}",
                "filename": out.name,
                "kind": "zip",
                "parts": part_count,
                "splitPositions": split_positions,
            }
        )

    if output_format == "png":
        out = OUTPUT_DIR / "export.png"
    else:
        out = OUTPUT_DIR / "export.jpg"
    save_export_image(result, out, output_format)

    return jsonify({"ok": True, "url": f"/api/output/{out.name}", "filename": out.name, "kind": output_format})


@app.get("/api/output/<filename>")
def api_output(filename: str) -> Any:
    output_path = OUTPUT_DIR / filename
    return send_file(output_path, as_attachment=output_path.suffix.lower() == ".zip")


@app.post("/api/reset-cache")
def api_reset_cache() -> Any:
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    ensure_dirs()
    return jsonify({"ok": True})


if __name__ == "__main__":
    ensure_dirs()
    app.run(host="0.0.0.0", port=8765, debug=False)
