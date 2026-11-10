"""Reference Anki exporter that needs only genanki and Pillow (no Django).

It reproduces converter/services/exporting.py:export_deck from a converter backup
ZIP so the Slanki compatibility gate keeps a trustworthy baseline after the
Django edition is retired. tools/golden.py checks that both produce identical
Anki tables for the synthetic golden lecture.

Usage:
    python tools/genanki_ref.py BACKUP.zip OUT.apkg
    python tools/genanki_ref.py --dump DECK.apkg        # print a JSON table dump
"""

import hashlib
import html
import io
import itertools
import json
import re
import sqlite3
import sys
import time
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

import genanki
from PIL import Image, ImageDraw

MODEL_ID = 1890487183
CLOZE_MODEL_ID = 1890487184
REVERSED_MODEL_ID = 1890487185
OCCLUSION_MODEL_ID = 1890487186
VISUAL_MODEL_ID = 1890487187
CSS = """.card { font-family: Arial, sans-serif; font-size: 22px; text-align: left;
color: #20342e; background: #fafbf7; padding: 24px; line-height: 1.5; }
.nightMode.card { color: #e7eee8; background: #202825; }
.source { font-size: 14px; opacity: .85; margin-top: 24px; }
.source img, .source-crop { max-width: 100%; height: auto; margin-top: 12px; }
hr { border: 0; border-top: 1px solid #aebdb2; margin: 20px 0; }
.cloze { font-weight: bold; color: #235945; }
.nightMode .cloze { color: #9bcfb5; }"""
EDGES = ("left", "top", "right", "bottom")
DERIVED_MEDIA = re.compile(r"\b(crop|occlusion|visual)_([0-9a-f]{32})_[0-9a-f]{16}\.png")


class StableNote(genanki.Note):
    def __init__(self, *args, modified, **kwargs):
        super().__init__(*args, **kwargs)
        self.modified = modified

    def write_to_db(self, cursor, timestamp, deck_id, id_gen):
        super().write_to_db(cursor, self.modified, deck_id, id_gen)


def text_html(text):
    return html.escape(text).replace("\n", "<br>")


def models():
    basic = genanki.Model(
        MODEL_ID,
        "Slides to Anki — Basic v1",
        fields=[{"name": name} for name in ["Question", "Answer", "Source"]],
        templates=[
            {
                "name": "Card",
                "qfmt": "{{Question}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Answer}}<div class="source">{{Source}}</div>',
            }
        ],
        css=CSS,
    )
    cloze = genanki.Model(
        CLOZE_MODEL_ID,
        "Recalloom — Cloze v1",
        fields=[{"name": name} for name in ["Text", "Extra", "Source"]],
        templates=[
            {
                "name": "Cloze",
                "qfmt": "{{cloze:Text}}",
                "afmt": '{{cloze:Text}}<hr id="answer">{{Extra}}<div class="source">{{Source}}</div>',
            }
        ],
        model_type=genanki.Model.CLOZE,
        css=CSS,
    )
    reversed_ = genanki.Model(
        REVERSED_MODEL_ID,
        "Recalloom — Basic + reverse v1",
        fields=[{"name": name} for name in ["Front", "Back", "Source", "QuestionImage"]],
        templates=[
            {
                "name": "Front → back",
                "qfmt": "{{Front}}{{QuestionImage}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Back}}<div class="source">{{Source}}</div>',
            },
            {
                "name": "Back → front",
                "qfmt": "{{Back}}{{QuestionImage}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Front}}<div class="source">{{Source}}</div>',
            },
        ],
        css=CSS,
    )
    occlusion = genanki.Model(
        OCCLUSION_MODEL_ID,
        "Recalloom — Image occlusion v1",
        fields=[{"name": name} for name in ["Prompt", "Hidden", "Revealed", "Extra", "Source"]],
        templates=[
            {
                "name": "Hidden region",
                "qfmt": "{{Prompt}}<br>{{Hidden}}",
                "afmt": '{{Prompt}}<br>{{Revealed}}<hr id="answer">{{Extra}}<div class="source">{{Source}}</div>',
            }
        ],
        css=CSS,
    )
    visual = genanki.Model(
        VISUAL_MODEL_ID,
        "Recalloom - Graph and formula v1",
        fields=[{"name": name} for name in ["Question", "Answer", "Hidden", "Revealed", "Source"]],
        templates=[
            {
                "name": "Interpret the figure",
                "qfmt": "{{Question}}<br>{{Hidden}}",
                "afmt": '{{Question}}<br>{{Revealed}}<hr id="answer">{{Answer}}<div class="source">{{Source}}</div>',
            }
        ],
        css=CSS,
    )
    return {
        "basic": basic,
        "cloze": cloze,
        "reversed": reversed_,
        "occlusion": occlusion,
        "visual": visual,
    }


def png_bytes(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def crop_png(source, crop):
    with Image.open(io.BytesIO(source), formats=["PNG"]) as image:
        with image.crop(tuple(crop[key] for key in EDGES)) as selected:
            return png_bytes(selected)


def occlusion_png(source, mask, *, answer=False):
    with Image.open(io.BytesIO(source), formats=["PNG"]) as original:
        with original.convert("RGB") as image:
            box = (mask["left"], mask["top"], mask["right"] - 1, mask["bottom"] - 1)
            draw = ImageDraw.Draw(image)
            if answer:
                left, top, right, bottom = box
                draw.rectangle(
                    (left - 2, top - 2, right + 2, bottom + 2), outline="#247c57", width=2
                )
            else:
                draw.rectangle(box, fill="#d9aa54")
            return png_bytes(image)


def visual_png(source, crop, masks, *, answer=False):
    with Image.open(io.BytesIO(source), formats=["PNG"]) as original:
        with original.convert("RGB") as canvas:
            if not answer:
                draw = ImageDraw.Draw(canvas)
                for mask in masks:
                    draw.rectangle(
                        (mask["left"], mask["top"], mask["right"] - 1, mask["bottom"] - 1),
                        fill="#e5e8e2",
                    )
            if crop:
                with canvas.crop(tuple(crop[edge] for edge in EDGES)) as framed:
                    return png_bytes(framed)
            return png_bytes(canvas)


def read_backup(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        images = {
            page["number"]: archive.read(f"pages/{page['number']}.png")
            for page in manifest["pages"]
        }
    return manifest, images


def export_backup_deck(data, *, timestamp=None):
    """Return .apkg bytes for the accepted notes in a converter backup ZIP."""
    manifest, images = read_backup(data)
    lecture = manifest["lecture"]
    lecture_uuid = lecture["id"]
    lecture_hex = lecture_uuid.replace("-", "")
    cards = [card for card in manifest["cards"] if card["status"] == "accepted"]
    if not cards:
        raise ValueError("Accept at least one card before exporting.")
    # Django orders by page number, then creation time.
    cards.sort(key=lambda card: (card["page"], datetime.fromisoformat(card["created_at"])))
    deck_id = int.from_bytes(hashlib.sha256(lecture_uuid.encode()).digest()[:6], "big")
    deck = genanki.Deck(deck_id, lecture["title"].replace("::", " — "))
    note_models = models()
    media = {}
    for card in cards:
        note_type = card.get("note_type", "basic")
        crop = card.get("source_crop", {})
        page = card["page"]
        source_png = images[page]
        card_hex = card["id"].replace("-", "")
        filename = f"slides_{lecture_hex}_{page}.png"
        media[filename] = source_png
        source = f"{text_html(lecture['title'])} · Page {page}"
        if card["source_quote"]:
            source += f"<br>{text_html(card['source_quote'])}"
        front = text_html(card["front"])
        question_image = ""
        if crop and note_type != "visual":
            cropped = crop_png(source_png, crop)
            crop_name = f"crop_{card_hex}_{hashlib.sha256(cropped).hexdigest()[:16]}.png"
            media[crop_name] = cropped
            crop_html = f'<br><img class="source-crop" src="{crop_name}">'
            if crop["on_question"]:
                if note_type == "reversed":
                    question_image = crop_html
                else:
                    front += crop_html
            else:
                source += crop_html
        source += f'<br><img src="{filename}">'
        fields = [front, text_html(card["back"]), source]
        if note_type == "reversed":
            fields.append(question_image)
        elif note_type == "visual":
            pictures = []
            for answer in (False, True):
                png = visual_png(source_png, crop, card.get("visual_masks", []), answer=answer)
                name = f"visual_{card_hex}_{hashlib.sha256(png).hexdigest()[:16]}.png"
                media[name] = png
                pictures.append(f'<img class="source-crop" src="{name}">')
            fields = [front, text_html(card["back"]), *pictures, source]
        elif note_type == "occlusion":
            pictures = []
            for answer in (False, True):
                png = occlusion_png(source_png, card["occlusion"], answer=answer)
                name = f"occlusion_{card_hex}_{hashlib.sha256(png).hexdigest()[:16]}.png"
                media[name] = png
                pictures.append(f'<img class="source-crop" src="{name}">')
            fields = [front, *pictures, text_html(card["back"]), source]
        deck.add_note(
            StableNote(
                model=note_models[note_type],
                fields=fields,
                guid=genanki.guid_for(card["id"]),
                modified=card["anki_modified"],
            )
        )
    stamp = time.time() if timestamp is None else timestamp
    output = io.BytesIO()
    with closing(sqlite3.connect(":memory:")) as connection:
        genanki.Package(deck).write_to_db(
            connection.cursor(), stamp, itertools.count(int(stamp * 1000))
        )
        connection.commit()
        database = connection.serialize()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("collection.anki2", database)
        archive.writestr("media", json.dumps({str(i): name for i, name in enumerate(media)}))
        for index, content in enumerate(media.values()):
            archive.writestr(str(index), content)
    return output.getvalue()


def dump_apkg(data):
    """Decode an .apkg into comparable JSON; row IDs are replaced by GUID references."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = [
            {"name": info.filename, "compress_type": info.compress_type}
            for info in archive.infolist()
        ]
        media_map = json.loads(archive.read("media"))
        media = [
            {
                "index": index,
                "name": name,
                "sha256": hashlib.sha256(archive.read(index)).hexdigest(),
            }
            for index, name in media_map.items()
        ]
        database = archive.read("collection.anki2")
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.deserialize(database)
        connection.row_factory = sqlite3.Row
        col = dict(connection.execute("SELECT * FROM col").fetchone())
        for key in ("conf", "models", "decks", "dconf", "tags"):
            col[key + "_text"] = col[key]
            col[key] = json.loads(col[key])
        note_guid = {}
        notes = []
        for row in connection.execute("SELECT * FROM notes ORDER BY id"):
            row = dict(row)
            note_guid[row.pop("id")] = row["guid"]
            notes.append(row)
        cards = []
        for row in connection.execute("SELECT * FROM cards ORDER BY id"):
            row = dict(row)
            row.pop("id")
            row["note_guid"] = note_guid[row.pop("nid")]
            cards.append(row)
        tables = {
            name: [dict(row) for row in connection.execute(f"SELECT * FROM {name}")]
            for name in ("revlog", "graves")
        }
        schema = [
            row[0]
            for row in connection.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
            )
        ]
    return {
        "entries": entries,
        "media": media,
        "col": col,
        "notes": notes,
        "cards": cards,
        "revlog": tables["revlog"],
        "graves": tables["graves"],
        "schema": schema,
    }


def comparable(dump, *, derived_media_names=True):
    """Remove values that legitimately differ between exports of the same notes.

    Model ``mod`` is the export time. When ``derived_media_names`` is true, the
    content-hash suffix of generated crop/occlusion/visual images is masked, because a
    different PNG encoder legitimately produces different bytes for equal pixels.
    """
    result = json.loads(json.dumps(dump))
    for model in result["col"]["models"].values():
        model["mod"] = "<export time>"
    result["col"].pop("models_text")
    if derived_media_names:

        def mask(value):
            return DERIVED_MEDIA.sub(lambda m: f"{m[1]}_{m[2]}_<hash>.png", value)

        for note in result["notes"]:
            note["flds"] = mask(note["flds"])
            note["sfld"] = mask(str(note["sfld"]))
        for item in result["media"]:
            if DERIVED_MEDIA.fullmatch(item["name"]):
                item["name"] = mask(item["name"])
                item["sha256"] = "<derived image>"
    result["notes"].sort(key=lambda note: note["guid"])
    result["cards"].sort(key=lambda card: (card["note_guid"], card["ord"]))
    return result


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        print(json.dumps(dump_apkg(Path(sys.argv[2]).read_bytes()), indent=1, ensure_ascii=False))
    elif len(sys.argv) == 3:
        Path(sys.argv[2]).write_bytes(export_backup_deck(Path(sys.argv[1]).read_bytes()))
    else:
        sys.exit(__doc__)
