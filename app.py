from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from PIL import Image, ImageDraw, ImageFont, ImageOps
from psd_tools import PSDImage


BASE_DIR = Path(__file__).resolve().parent
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
CONFIG_PATH = BASE_DIR / "slots.json"
ACTIVE_TEMPLATE_PATH = BASE_DIR / "active_template.json"

PREVIEW_MAX_WIDTH = 900
CACHE_VERSION = "v2"
PROTECTED_LAYER_MAX_AREA = 160_000

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


def ensure_dirs() -> None:
    for path in (CACHE_DIR, UPLOAD_DIR, THUMB_DIR, OUTPUT_DIR, TEMPLATE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def active_template_path() -> Path:
    if ACTIVE_TEMPLATE_PATH.exists():
        data = json.loads(ACTIVE_TEMPLATE_PATH.read_text("utf-8"))
        path = Path(data.get("path", ""))
        if path.exists():
            return path
    raise FileNotFoundError("尚未导入模板")


def has_active_template() -> bool:
    try:
        active_template_path()
        return True
    except FileNotFoundError:
        return False


def set_active_template(path: Path) -> None:
    ACTIVE_TEMPLATE_PATH.write_text(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2), "utf-8")


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


def load_psd() -> PSDImage:
    template_path = active_template_path()
    if not template_path.exists():
        raise FileNotFoundError(f"找不到模板文件：{template_path}")
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


def protected_overlay_image(psd: PSDImage) -> Image.Image:
    canvas = Image.new("RGBA", (psd.width, psd.height), (255, 255, 255, 0))

    def should_protect(layer: Any) -> bool:
        x1, y1, x2, y2 = map(int, layer.bbox)
        area = max(0, x2 - x1) * max(0, y2 - y1)
        if layer.kind == "type":
            return True
        if layer.kind == "shape":
            return area <= PROTECTED_LAYER_MAX_AREA
        if layer.kind == "smartobject":
            return area <= PROTECTED_LAYER_MAX_AREA
        return False

    def draw(layers: Any) -> None:
        for layer in layers:
            if not layer.visible:
                continue
            if layer.is_group():
                draw(layer)
                continue
            if not should_protect(layer):
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
    if CONFIG_PATH.exists():
        return ensure_slot_layer_keys(json.loads(CONFIG_PATH.read_text("utf-8")))
    return []


def clear_slots() -> None:
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()


def detect_and_save_slots() -> list[dict[str, Any]]:
    psd = load_psd()
    slots = [asdict(slot) for slot in default_slots(layer_slots(psd))]
    write_slots(slots)
    return read_slots()


def write_slots(slots: list[dict[str, Any]]) -> None:
    CONFIG_PATH.write_text(json.dumps(normalize_slots(slots), ensure_ascii=False, indent=2), "utf-8")


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
            }
        )
    return normalized


def build_template_cache() -> dict[str, Any]:
    ensure_dirs()
    template_png, preview_jpg, meta_json = template_cache_paths()
    overlay_png = template_overlay_path()
    if template_png.exists() and preview_jpg.exists() and meta_json.exists() and overlay_png.exists():
        return json.loads(meta_json.read_text("utf-8"))

    psd = load_psd()
    image = fast_template_image(psd)
    overlay = protected_overlay_image(psd)
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    image.save(template_png)
    overlay.save(overlay_png)

    preview = image.convert("RGB")
    ratio = min(1.0, PREVIEW_MAX_WIDTH / preview.width)
    preview_size = (int(preview.width * ratio), int(preview.height * ratio))
    preview = preview.resize(preview_size, Image.Resampling.LANCZOS)
    preview.save(preview_jpg, quality=88, optimize=True)

    meta = {
        "width": image.width,
        "height": image.height,
        "previewWidth": preview.width,
        "previewHeight": preview.height,
        "scale": preview.width / image.width,
        "templateImage": f"/api/template-image?kind=full",
        "topOverlayImage": f"/api/template-image?kind=overlay",
        "previewImage": f"/api/template-image?kind=preview",
    }
    meta_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    return meta


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


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/meta")
def api_meta() -> Any:
    if not has_active_template():
        return jsonify(
            {
                "empty": True,
                "template": {
                    "width": 2400,
                    "height": 1800,
                    "previewWidth": 1200,
                    "previewHeight": 900,
                    "scale": 0.5,
                    "templateImage": "",
                    "topOverlayImage": "",
                    "previewImage": "",
                },
                "slots": [],
            }
    )
    try:
        meta = build_template_cache()
        slots = read_slots()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"template": meta, "slots": slots})


@app.post("/api/new-template")
def api_new_template() -> Any:
    if ACTIVE_TEMPLATE_PATH.exists():
        ACTIVE_TEMPLATE_PATH.unlink()
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
    return jsonify({"ok": True, "empty": True})


@app.get("/api/template-image")
def api_template_image() -> Any:
    build_template_cache()
    template_png, preview_jpg, _ = template_cache_paths()
    overlay_png = template_overlay_path()
    kind = request.args.get("kind", "preview")
    if kind == "full":
        return send_file(template_png)
    if kind == "overlay":
        return send_file(overlay_png)
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


@app.post("/api/detect-slots")
def api_detect_slots() -> Any:
    try:
        slots = detect_and_save_slots()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "slots": slots})


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
    set_active_template(target)
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    ensure_dirs()
    meta = build_template_cache()
    return jsonify({"ok": True, "template": meta, "slots": []})


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
    return jsonify(
        {
            "id": filename,
            "url": f"/api/upload/{filename}",
            "thumbUrl": f"/api/thumb/{thumb_name}",
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
    fit_mode = payload.get("fit", "cover")
    render_mode = payload.get("renderMode", "fast")
    output_format = payload.get("format", "jpg").lower()
    payload_slots = payload.get("slots")
    ordered_slots = normalize_slots(payload_slots) if isinstance(payload_slots, list) else read_slots()
    slots = {slot["id"]: slot for slot in ordered_slots}

    if render_mode == "precise":
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
        if not image_id or slot_id not in slots:
            return
        image_path = UPLOAD_DIR / str(image_id)
        if not image_path.exists():
            return
        with Image.open(image_path) as src:
            if fit_mode == "contain":
                fitted = contain_fit(src, int(slot["w"]), int(slot["h"]))
            else:
                fitted = cover_fit(src, int(slot["w"]), int(slot["h"]))
        alpha_composite_clipped(result, fitted, int(slot["x"]), int(slot["y"]))

    for slot in reversed(ordered_slots):
        draw_assigned_slot(slot)

    overlay = Image.open(template_overlay_path()).convert("RGBA")
    alpha_composite_clipped(result, overlay, 0, 0)

    clear_dir(OUTPUT_DIR)
    if output_format == "png":
        out = OUTPUT_DIR / "export.png"
        result.save(out)
    else:
        out = OUTPUT_DIR / "export.jpg"
        background = Image.new("RGB", result.size, (255, 255, 255))
        background.paste(result, mask=result.split()[-1])
        background.save(out, quality=95, optimize=True)

    return jsonify({"ok": True, "url": f"/api/output/{out.name}"})


@app.get("/api/output/<filename>")
def api_output(filename: str) -> Any:
    return send_file(OUTPUT_DIR / filename, as_attachment=False)


@app.post("/api/reset-cache")
def api_reset_cache() -> Any:
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    ensure_dirs()
    return jsonify({"ok": True})


if __name__ == "__main__":
    ensure_dirs()
    app.run(host="0.0.0.0", port=8765, debug=False)
