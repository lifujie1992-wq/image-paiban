import json
from pathlib import Path


SLOTS = Path("slots.json")


def main() -> None:
    slots = json.loads(SLOTS.read_text("utf-8"))
    for index, slot in enumerate(slots, start=1):
        if index == 12 or slot.get("id") == "slot_022":
            slot["name"] = f"{slot['name']} / 白框占位"
            slot["x"] = 193
            slot["y"] = 13173
            slot["w"] = 1052
            slot["h"] = 1317
            break
    SLOTS.write_text(json.dumps(slots, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
