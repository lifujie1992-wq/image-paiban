from pathlib import Path

from PIL import Image

from app import OUTPUT_DIR, app, template_overlay_path


def find_overlay_pixel() -> tuple[int, int, tuple[int, int, int, int]]:
    overlay = Image.open(template_overlay_path()).convert("RGBA")
    step = max(1, min(overlay.width, overlay.height) // 200)
    for y in range(0, overlay.height, step):
        for x in range(0, overlay.width, step):
            pixel = overlay.getpixel((x, y))
            if pixel[3] > 200:
                return x, y, pixel
    raise AssertionError("no opaque overlay pixel found")


def main() -> None:
    client = app.test_client()
    meta = client.get("/api/meta")
    assert meta.status_code == 200, meta.get_data(as_text=True)

    x, y, overlay_pixel = find_overlay_pixel()
    fixture = Path("overlay_order_asset.png")
    Image.new("RGB", (120, 120), (255, 0, 0)).save(fixture)
    with fixture.open("rb") as handle:
        upload = client.post("/api/upload", data={"file": (handle, fixture.name)})
    assert upload.status_code == 200, upload.get_data(as_text=True)
    image_id = upload.get_json()["id"]

    slot = {
        "id": "manual_overlay_order",
        "name": "Overlay order",
        "x": max(0, x - 20),
        "y": max(0, y - 20),
        "w": 80,
        "h": 80,
        "source": "manual",
        "layer_key": "",
        "slot_type": "image",
        "visible": True,
    }
    export = client.post(
        "/api/export",
        json={
            "assignments": {slot["id"]: image_id},
            "slots": [slot],
            "fit": "cover",
            "format": "png",
        },
    )
    assert export.status_code == 200, export.get_data(as_text=True)
    with Image.open(OUTPUT_DIR / "export.png").convert("RGBA") as result:
        out_pixel = result.getpixel((x, y))

    assert out_pixel[:3] == overlay_pixel[:3], {
        "position": (x, y),
        "overlay": overlay_pixel,
        "export": out_pixel,
    }
    print("overlay order ok", (x, y), overlay_pixel, out_pixel)


if __name__ == "__main__":
    main()
