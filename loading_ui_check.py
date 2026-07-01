from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    Path("outputs").mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 820})
        page.goto("http://127.0.0.1:8765", wait_until="networkidle")
        page.evaluate(
            """
            () => {
              const modal = document.getElementById('templateLoadingModal');
              const text = document.getElementById('templateLoadingText');
              text.textContent = '正在读取图层并生成预览，请保持页面打开。';
              modal.hidden = false;
            }
            """
        )
        assert page.get_by_text("正在导入模板").is_visible()
        assert page.get_by_text("上传文件").is_visible()
        page.screenshot(path="outputs/ui_loading.png", full_page=False)
        browser.close()
    print("loading screenshot written")


if __name__ == "__main__":
    main()
