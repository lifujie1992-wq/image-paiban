from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw


BASE_URL = "http://127.0.0.1:8765"


def request_json(path: str, data: dict | None = None) -> dict:
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8")) from exc


def upload_image(path: Path) -> str:
    boundary = "----codex-boundary"
    payload = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/upload",
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))["id"]


def main() -> None:
    fixture = Path("live_manual_test.png")
    image = Image.new("RGB", (240, 240), (13, 180, 90))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 220, 220), outline=(255, 255, 255), width=12)
    image.save(fixture)

    meta = request_json("/api/meta")
    slot = {
        "id": "manual_live_slot",
        "name": "Manual live slot",
        "x": meta["template"]["width"] // 3,
        "y": meta["template"]["height"] // 3,
        "w": 180,
        "h": 180,
        "source": "manual",
        "layer_key": "",
        "slot_type": "image",
        "visible": True,
    }
    image_id = upload_image(fixture)
    export = request_json(
        "/api/export",
        {
            "assignments": {slot["id"]: image_id},
            "slots": [slot],
            "fit": "cover",
            "renderMode": "fast",
            "format": "png",
        },
    )
    assert export["ok"], export
    out_path = Path("outputs/export.png")
    with Image.open(out_path).convert("RGB") as exported:
        pixel = exported.getpixel((slot["x"] + 40, slot["y"] + 40))
    print(json.dumps({"url": export["url"], "slot": slot, "pixel": pixel}, ensure_ascii=False))


if __name__ == "__main__":
    main()
