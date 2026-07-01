from pathlib import Path

from PIL import Image, ImageDraw

from app import OUTPUT_DIR, app


def main() -> None:
    fixture = Path("test_asset.png")
    image = Image.new("RGB", (900, 1200), (230, 70, 65))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 820, 1120), outline=(255, 255, 255), width=20)
    draw.text((120, 140), "TEST IMAGE", fill=(255, 255, 255))
    image.save(fixture)

    client = app.test_client()
    meta = client.get("/api/meta")
    assert meta.status_code == 200, meta.get_data(as_text=True)
    slots = meta.get_json()["slots"]
    if not slots:
        detect = client.post("/api/detect-slots")
        assert detect.status_code == 200, detect.get_data(as_text=True)
        slots = detect.get_json()["slots"]
    assert slots, "no slots"

    with fixture.open("rb") as handle:
        upload = client.post("/api/upload", data={"file": (handle, fixture.name)})
    assert upload.status_code == 200, upload.get_data(as_text=True)
    image_id = upload.get_json()["id"]
    thumb_url = upload.get_json()["thumbUrl"]
    assert thumb_url.startswith("/api/thumb/"), thumb_url

    export = client.post(
        "/api/export",
        json={
            "assignments": {slots[0]["id"]: image_id},
            "fit": "cover",
            "format": "jpg",
        },
    )
    assert export.status_code == 200, export.get_data(as_text=True)

    output = OUTPUT_DIR / "export.jpg"
    assert output.exists(), "export file missing"
    with Image.open(output) as exported:
        print("export", output, exported.size, output.stat().st_size)

    manual_slot = {
        "id": "manual_test_slot",
        "name": "Manual test slot",
        "x": 10,
        "y": 10,
        "w": 120,
        "h": 120,
        "source": "manual",
        "layer_key": "",
        "slot_type": "image",
        "visible": True,
    }
    export = client.post(
        "/api/export",
        json={
            "assignments": {manual_slot["id"]: image_id},
            "slots": [manual_slot],
            "fit": "cover",
            "format": "png",
        },
    )
    assert export.status_code == 200, export.get_data(as_text=True)

    output = OUTPUT_DIR / "export.png"
    assert output.exists(), "manual slot export file missing"
    with Image.open(output).convert("RGB") as exported:
        pixel = exported.getpixel((manual_slot["x"] + 20, manual_slot["y"] + 20))
        assert pixel[0] > 180 and pixel[1] < 120 and pixel[2] < 120, pixel
        print("manual export", output, exported.size, output.stat().st_size, pixel)

    clear = client.post("/api/slots/clear")
    assert clear.status_code == 200, clear.get_data(as_text=True)
    meta = client.get("/api/meta")
    assert meta.status_code == 200, meta.get_data(as_text=True)
    assert meta.get_json()["slots"] == []


if __name__ == "__main__":
    main()
