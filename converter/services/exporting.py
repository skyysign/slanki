import hashlib
import itertools
import json
import sqlite3
import time
import zipfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import genanki
from django.conf import settings

from .files import WorkflowError, media_path
from .note_types import study_card_count, text_html

MODEL_ID = 1890487183
CLOZE_MODEL_ID = 1890487184
CSS = """.card { font-family: Arial, sans-serif; font-size: 22px; text-align: left;
color: #20342e; background: #fafbf7; padding: 24px; line-height: 1.5; }
.nightMode.card { color: #e7eee8; background: #202825; }
.source { font-size: 14px; opacity: .85; margin-top: 24px; }
.source img { max-width: 100%; height: auto; margin-top: 12px; }
hr { border: 0; border-top: 1px solid #aebdb2; margin: 20px 0; }
.cloze { font-weight: bold; color: #235945; }
.nightMode .cloze { color: #9bcfb5; }"""


class StableNote(genanki.Note):
    def __init__(self, *args, modified, **kwargs):
        super().__init__(*args, **kwargs)
        self.modified = modified

    def write_to_db(self, cursor, timestamp, deck_id, id_gen):
        super().write_to_db(cursor, self.modified, deck_id, id_gen)


def export_deck(lecture):
    cards = list(lecture.cards.filter(status="accepted").select_related("page"))
    if not cards:
        raise WorkflowError("Accept at least one card before exporting.")
    deck_id = int.from_bytes(hashlib.sha256(str(lecture.pk).encode()).digest()[:6], "big")
    # Keep the original note type name and ID so existing Anki imports still match.
    model = genanki.Model(
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
    deck = genanki.Deck(deck_id, lecture.title.replace("::", " — "))
    cloze_model = genanki.Model(
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
    media = {}
    for card in cards:
        study_card_count(card.front, card.note_type)
        image_path = media_path(card.page.image)
        if not image_path.is_file():
            raise WorkflowError(
                f"Source image for page {card.page.number} is missing. Restore a backup before exporting."
            )
        filename = f"slides_{lecture.pk.hex}_{card.page.number}.png"
        media[filename] = image_path
        source = f"{text_html(lecture.title)} · Page {card.page.number}"
        if card.source_quote:
            source += f"<br>{text_html(card.source_quote)}"
        source += f'<br><img src="{filename}">'
        deck.add_note(
            StableNote(
                model=cloze_model if card.note_type == "cloze" else model,
                fields=[text_html(card.front), text_html(card.back), source],
                guid=genanki.guid_for(str(card.pk)),
                modified=card.anki_modified,
            )
        )
    with TemporaryDirectory(dir=settings.WORK_DIR) as directory:
        db_path = Path(directory) / "collection.anki2"
        with closing(sqlite3.connect(db_path)) as connection:
            package = genanki.Package(deck)
            package.write_to_db(
                connection.cursor(), time.time(), itertools.count(int(time.time() * 1000))
            )
            connection.commit()
        output = Path(directory) / "lecture.apkg"
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(db_path, "collection.anki2")
            archive.writestr("media", json.dumps({str(i): name for i, name in enumerate(media)}))
            for index, path in enumerate(media.values()):
                archive.write(path, str(index))
        return output.read_bytes()
