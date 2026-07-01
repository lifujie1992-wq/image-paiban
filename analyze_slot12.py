from collections import deque

from PIL import Image

from app import template_cache_paths


def main() -> None:
    im = Image.open(template_cache_paths()[0]).convert("RGB")
    x, y, w, h = 60, 12679, 1320, 1981
    crop = im.crop((x, y, x + w, y + h))
    pixels = crop.load()
    white = set()
    for yy in range(h):
        for xx in range(w):
            r, g, b = pixels[xx, yy]
            if r > 245 and g > 245 and b > 245:
                white.add((xx, yy))

    seen = set()
    components = []
    for point in list(white):
        if point in seen:
            continue
        stack = [point]
        seen.add(point)
        xs = []
        ys = []
        while stack:
            cx, cy = stack.pop()
            xs.append(cx)
            ys.append(cy)
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) in white and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        if len(xs) > 1000:
            components.append((len(xs), min(xs), min(ys), max(xs) + 1, max(ys) + 1))

    components.sort(reverse=True)
    for count, x1, y1, x2, y2 in components[:20]:
        print(count, "abs", x + x1, y + y1, "size", x2 - x1, y2 - y1)


if __name__ == "__main__":
    main()
