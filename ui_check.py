from pathlib import Path

from playwright.sync_api import sync_playwright


def check_viewport(page, width: int, height: int, name: str) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto("http://127.0.0.1:8765", wait_until="networkidle")
    page.screenshot(path=f"outputs/ui_{name}.png", full_page=False)
    for text in ["图版工作台", "图片位", "导出图片"]:
        assert page.get_by_text(text).first.is_visible(), text
    box = page.locator("#canvas").bounding_box()
    assert box and box["width"] > 100 and box["height"] > 100, box


def main() -> None:
    Path("outputs").mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        check_viewport(page, 1440, 900, "desktop")
        check_viewport(page, 390, 844, "mobile")
        browser.close()
    print("ui screenshots written")


if __name__ == "__main__":
    main()
