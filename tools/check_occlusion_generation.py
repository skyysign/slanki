"""One explicitly live Codex image check, using only a generated synthetic diagram."""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def diagram(path):
    """A deterministic diagram whose label positions are known independently of the model."""
    with Image.new("RGB", (1100, 700), "white") as image:
        draw = ImageDraw.Draw(image)
        heading = ImageFont.load_default(size=34)
        font = ImageFont.load_default(size=27)
        draw.text((60, 35), "Neuron: receive, integrate, transmit", fill="#213b43", font=heading)
        # Dendrites, cell body, and a long axon, with labels placed below the structures.
        draw.ellipse((365, 235, 495, 365), fill="#d3e7ee", outline="#213b43", width=4)
        draw.ellipse((403, 276, 449, 322), fill="#739aaf")
        for y in (185, 250, 350, 415):
            draw.line([(385, 300), (255, y), (145, y - 35)], fill="#213b43", width=5)
            draw.line([(255, y), (145, y + 35)], fill="#213b43", width=4)
        draw.line([(495, 300), (945, 300)], fill="#213b43", width=8)
        for x in (540, 650, 760, 870):
            draw.rounded_rectangle(
                (x, 273, x + 75, 327), radius=14, fill="#d3e7ee", outline="#213b43", width=3
            )
        boxes = {}
        for label, origin, target in (
            ("Dendrites", (125, 485), (225, 415)),
            ("Cell body", (360, 485), (430, 365)),
            ("Axon", (775, 485), (805, 330)),
        ):
            draw.line([(origin[0] + 50, origin[1] - 12), target], fill="#66777b", width=2)
            draw.text(origin, label, fill="#213b43", font=font)
            boxes[label] = list(draw.textbbox(origin, label, font=font))
        draw.text(
            (60, 640),
            "SYNTHETIC TEST DIAGRAM",
            fill="#66777b",
            font=ImageFont.load_default(size=18),
        )
        image.save(path, format="PNG")
    return boxes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the signed-in Codex allowance for one image request",
    )
    parser.add_argument("--model", default="", help="Requested model ID; blank uses CLI default")
    parser.add_argument("--reasoning", default="low")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to run one provider request. Routine tests remain offline.")
    folder = ROOT / "data/live-checks" / ("occlusion-" + str(uuid.uuid4()))
    os.environ["SLIDES_DATA_DIR"] = str(folder)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.conf import settings

    from converter.services.connection import login_status
    from converter.services.generation import codex_generate
    from converter.services.occlusion import occlusion_png
    from converter.services.occlusion_suggestions import validate_suggestions

    if login_status()["state"] != "connected":
        raise SystemExit("Connect Codex with ChatGPT before this live check.")
    image = settings.MEDIA_ROOT / "synthetic-neuron.png"
    known_boxes = diagram(image)
    page = SimpleNamespace(number=1, image=image.name, width=1100, height=700, text="")
    report = {
        "provider": "codex",
        "requested_model": args.model or "CLI default",
        "requested_reasoning": args.reasoning,
        "known_label_boxes": known_boxes,
    }
    started = time.monotonic()
    print(
        "Sending ONE synthetic slide image to Codex; no real lecture data is included.", flush=True
    )
    try:
        payload = codex_generate(
            [page], task="occlusion", model=args.model, reasoning_effort=args.reasoning
        )
        report["raw_output"] = payload
        suggestions = validate_suggestions(payload, page)
        report["suggestions"] = suggestions
        for index, suggestion in enumerate(suggestions, 1):
            (folder / f"question-{index}.png").write_bytes(occlusion_png(page, suggestion["mask"]))
        report["status"] = "completed"
        print(
            f"Validated {len(suggestions)} suggestions. Inspect source and question PNGs for actual placement."
        )
    except Exception as exc:
        report["status"], report["error"] = "failed", str(exc)
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        (folder / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Isolated check data: {folder}", flush=True)


if __name__ == "__main__":
    main()
