from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app import app


def main() -> None:
    path = Path("ocr_fixture.png")
    image = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 42)
    draw.text((40, 40), "BRAND/品牌：MUZI", fill="black", font=font)
    draw.text((40, 110), "FABRIC/商品面料：棉100%", fill="black", font=font)
    draw.text((40, 180), "尺码表(cm) M L XL", fill="black", font=font)
    draw.text((40, 250), "体重 90-110斤 110-125斤 125-140斤", fill="black", font=font)
    image.save(path)

    client = app.test_client()
    with path.open("rb") as handle:
        resp = client.post("/api/recognize-product-info", data={"files": (handle, path.name)})
    print(resp.status_code)
    print(resp.get_data(as_text=True)[:1000])


if __name__ == "__main__":
    main()
