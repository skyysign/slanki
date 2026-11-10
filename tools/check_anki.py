"""Anki compatibility gate for Slanki exports (dev only).

Imports .apkg files built by the Recalloom reference exporter (genanki) and by
Slanki's browser exporter (run in Node) into throwaway Anki collections, never
the user's profile, and checks that re-exports keep note identity and review
schedules.

    .venv\\Scripts\\python.exe tools/check_anki.py               # golden synthetic lecture
    .venv\\Scripts\\python.exe tools/check_anki.py --real DIR    # also every backup-*.zip in DIR

Requires requirements-dev.txt (anki, genanki) and Node.js 22.12+.
"""

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import genanki_ref  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "synthetic" / "golden" / "backup-v12.zip"
EXPORTER = ROOT / "app" / "scripts" / "export-fixture.ts"
# Deliberate change against Recalloom (see app/src/export/anki.ts): the Source
# field shows only the images, and mod is at least EXPORT_LAYOUT_REVISION.
LAYOUT_REVISION = int(
    re.search(
        r"EXPORT_LAYOUT_REVISION = (\d+)",
        (ROOT / "app" / "src" / "export" / "anki.ts").read_text(encoding="utf-8"),
    )[1]
)
SOURCE_FIELD = {1890487183: 2, 1890487184: 2, 1890487185: 2, 1890487186: 4, 1890487187: 4}


def slanki_layout(dump):
    """Apply the intended Slanki layout to a Recalloom-exported table dump."""
    for note in dump["notes"]:
        fields = note["flds"].split("\x1f")
        index = SOURCE_FIELD[note["mid"]]
        fields[index] = fields[index][fields[index].index("<img") :]
        note["flds"] = "\x1f".join(fields)
        note["mod"] = max(note["mod"], LAYOUT_REVISION)
    for card in dump["cards"]:
        card["mod"] = max(card["mod"], LAYOUT_REVISION)
    return dump


def slanki_export(backup, folder, name):
    source = folder / f"{name}.zip"
    target = folder / f"{name}-slanki.apkg"
    source.write_bytes(backup)
    subprocess.run(
        ["node", str(EXPORTER), str(source), str(target)],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return target


def reference_export(backup, folder, name):
    target = folder / f"{name}-genanki.apkg"
    target.write_bytes(genanki_ref.export_backup_deck(backup))
    return target


def with_manifest(backup, change):
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files["manifest.json"])
    change(manifest)
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


class Gate:
    def __init__(self, folder):
        from anki.collection import Collection

        self.folder = folder
        self.collection = Collection(str(folder / f"gate-{uuid.uuid4().hex}.anki2"))

    def close(self):
        self.collection.close()

    def load(self, path):
        from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest

        self.collection.import_anki_package(
            ImportAnkiPackageRequest(
                package_path=str(path),
                options=ImportAnkiPackageOptions(with_scheduling=False),
            )
        )

    def state(self):
        col = self.collection
        cards = {}
        for card_id in col.find_cards(""):
            card = col.get_card(card_id)
            note = card.note()
            cards[card_id] = {
                "guid": note.guid,
                "ord": card.ord,
                "schedule": (card.type, card.queue, card.ivl, card.due, card.reps, card.lapses),
                "fields": dict(zip(note.keys(), note.values())),
                "notetype": note.note_type()["name"],
            }
        return {
            "cards": cards,
            "notes": len(col.find_notes("")),
            "notetypes": sorted((m.name, m.id) for m in col.models.all_names_and_ids()),
            "missing_media": list(col.media.check().missing),
        }

    def schedule_everything(self):
        col = self.collection
        for index, card_id in enumerate(sorted(col.find_cards(""))):
            card = col.get_card(card_id)
            card.type, card.queue, card.ivl, card.due, card.reps, card.lapses = (
                2,
                2,
                15 + index,
                40 + index,
                8,
                1,
            )
            col.update_card(card)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("  ok  ", message)


def compare_tables(name, reference, ours):
    left = genanki_ref.comparable(slanki_layout(genanki_ref.dump_apkg(reference.read_bytes())))
    right = genanki_ref.comparable(genanki_ref.dump_apkg(ours.read_bytes()))
    for key in left:
        check(left[key] == right[key], f"{name}: {key} identical to the Recalloom exporter")


def replace_scenario(name, backup, folder):
    """Recalloom/genanki deck in Anki with reviews, then the Slanki re-export."""
    print(f"[{name}] Recalloom deck with reviews, then Slanki re-export")
    reference = reference_export(backup, folder, name)
    ours = slanki_export(backup, folder, name)
    compare_tables(name, reference, ours)
    gate = Gate(folder)
    try:
        gate.load(reference)
        gate.schedule_everything()
        before = gate.state()
        gate.load(ours)
        after = gate.state()
        check(after["notes"] == before["notes"], f"{name}: no duplicate notes ({after['notes']})")
        check(
            set(after["cards"]) == set(before["cards"]),
            f"{name}: same card IDs ({len(after['cards'])})",
        )
        check(after["notetypes"] == before["notetypes"], f"{name}: no duplicate note types")
        check(
            all(
                after["cards"][i]["schedule"] == before["cards"][i]["schedule"]
                for i in before["cards"]
            ),
            f"{name}: every review schedule preserved",
        )

        def content(fields):
            # Derived images (crops, masks, covers) get new content-hash names; pixels match.
            return {
                key: genanki_ref.DERIVED_MEDIA.sub(lambda m: f"{m[1]}_{m[2]}_<hash>.png", value)
                for key, value in fields.items()
                if key != "Source"
            }

        check(
            all(
                content(after["cards"][i]["fields"]) == content(before["cards"][i]["fields"])
                for i in before["cards"]
            ),
            f"{name}: question and answer fields unchanged",
        )
        check(
            all(
                re.fullmatch(
                    r'(<img class="source-crop" src="[^"]+"><br>)?<img src="slides_\w+\.png">',
                    card["fields"]["Source"],
                )
                for card in after["cards"].values()
            ),
            f"{name}: existing cards updated to show only the slide below the answer",
        )
        check(after["missing_media"] == [], f"{name}: no missing media")
    finally:
        gate.close()


def synthetic_scenarios(folder):
    backup = GOLDEN.read_bytes()
    replace_scenario("golden", backup, folder)

    print("[golden] Slanki edits, new notes and renames")
    gate = Gate(folder)
    try:
        gate.load(slanki_export(backup, folder, "base"))
        gate.schedule_everything()
        base = gate.state()

        manifest = json.loads(zipfile.ZipFile(io.BytesIO(backup)).read("manifest.json"))
        accepted = [c for c in manifest["cards"] if c["status"] == "accepted"]
        basic = next(c for c in accepted if c["note_type"] == "basic")
        occlusion = next(c for c in accepted if c["note_type"] == "occlusion")
        reverse = next(c for c in accepted if c["note_type"] == "reversed")

        def edit(m):
            for card in m["cards"]:
                if card["id"] == basic["id"]:
                    card["front"] = "Edited in Slanki?"
                    card["anki_modified"] = max(card["anki_modified"], LAYOUT_REVISION) + 10
                if card["id"] == occlusion["id"]:
                    card["occlusion"] = {
                        **card["occlusion"],
                        "right": card["occlusion"]["right"] - 20,
                    }
                    card["anki_modified"] = max(card["anki_modified"], LAYOUT_REVISION) + 10
                if card["id"] == reverse["id"]:
                    card["back"] = "Edited back side"
                    card["anki_modified"] = max(card["anki_modified"], LAYOUT_REVISION) + 10

        edited = with_manifest(backup, edit)
        gate.load(slanki_export(edited, folder, "edited"))
        after = gate.state()
        check(set(after["cards"]) == set(base["cards"]), "edit: same card IDs")
        check(
            all(
                after["cards"][i]["schedule"] == base["cards"][i]["schedule"] for i in base["cards"]
            ),
            "edit: schedules preserved",
        )
        changed = {
            after["cards"][i]["guid"]
            for i in base["cards"]
            if after["cards"][i]["fields"] != base["cards"][i]["fields"]
        }
        expected = {genanki_ref.genanki.guid_for(c["id"]) for c in (basic, occlusion, reverse)}
        check(changed == expected, "edit: exactly the three edited notes changed")
        check(
            any(
                "Edited in Slanki?" in next(iter(c["fields"].values()))
                for c in after["cards"].values()
            ),
            "edit: new question text imported",
        )
        check(after["missing_media"] == [], "edit: no missing media")

        def add(m):
            page = 3
            created = "2026-11-10T12:00:00+00:00"
            for front, back, kind in (
                ("Spaced practice", "Distributing study over time", "reversed"),
                ("{{c1::Massed}} practice groups study; {{c2::spacing}} spreads it.", "", "cloze"),
            ):
                note_id = str(uuid.uuid4())
                m["cards"].append(
                    {
                        "id": note_id,
                        "page": page,
                        "front": front,
                        "note_type": kind,
                        "back": back,
                        "source_quote": "",
                        "source_crop": {},
                        "occlusion": {},
                        "visual_masks": [],
                        "status": "accepted",
                        "fingerprint": hashlib.sha256(note_id.encode()).hexdigest(),
                        "version": 1,
                        "anki_modified": 1794310000,
                        "run": None,
                        "created_at": created,
                        "updated_at": created,
                        "revisions": [],
                    }
                )

        grown = with_manifest(edited, add)
        before_add = gate.state()
        gate.load(slanki_export(grown, folder, "grown"))
        after = gate.state()
        added = set(after["cards"]) - set(before_add["cards"])
        check(
            len(added) == 4, "new notes: one reverse note (2 cards) and one 2-blank cloze (2 cards)"
        )
        check(
            all(
                after["cards"][i]["schedule"] == before_add["cards"][i]["schedule"]
                for i in before_add["cards"]
            ),
            "new notes: existing schedules preserved",
        )

        renamed = with_manifest(grown, lambda m: m["lecture"].update(title="Renamed lecture"))
        before_rename = gate.state()
        gate.load(slanki_export(renamed, folder, "renamed"))
        after = gate.state()
        check(after["notes"] == before_rename["notes"], "rename: no duplicate notes")
        check(set(after["cards"]) == set(before_rename["cards"]), "rename: same card IDs")
        check(
            all(
                after["cards"][i]["schedule"] == before_rename["cards"][i]["schedule"]
                for i in before_rename["cards"]
            ),
            "rename: schedules preserved",
        )
    finally:
        gate.close()

    print("[golden] Slanki deck imported twice into a fresh collection")
    gate = Gate(folder)
    try:
        package = slanki_export(backup, folder, "twice")
        gate.load(package)
        first = gate.state()
        gate.load(package)
        second = gate.state()
        check(set(first["cards"]) == set(second["cards"]), "repeat import: same card IDs")
        check(second["notes"] == first["notes"], "repeat import: no duplicates")
    finally:
        gate.close()


def package_check(path, folder):
    """Import a deck downloaded from the browser app and render every card."""
    print(f"[{path.name}] browser-built deck in a fresh collection")
    gate = Gate(folder)
    try:
        gate.load(path)
        state = gate.state()
        check(state["notes"] > 0, f"imported {state['notes']} notes / {len(state['cards'])} cards")
        col = gate.collection
        rendered = 0
        for card_id in state["cards"]:
            card = col.get_card(card_id)
            if card.question().strip() and card.answer().strip():
                rendered += 1
        check(rendered == len(state["cards"]), "every card renders a question and an answer")
        check(state["missing_media"] == [], "no missing media")
        gate.load(path)
        check(
            gate.state()["cards"].keys() == state["cards"].keys(), "re-import keeps the same cards"
        )
    finally:
        gate.close()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--real", type=Path, help="folder with backup-*.zip files to check read-only"
    )
    parser.add_argument(
        "--apkg", type=Path, action="append", default=[], help="deck exported by the app"
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="slanki-anki-gate-") as directory:
        folder = Path(directory)
        synthetic_scenarios(folder)
        if args.real:
            backups = sorted(args.real.glob("backup-*.zip"))
            if not backups:
                raise SystemExit(f"No backup-*.zip files in {args.real}")
            for index, path in enumerate(backups, 1):
                # Real lecture names stay out of the output; data remains in the temp folder.
                data = path.read_bytes()
                manifest = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
                if not any(card["status"] == "accepted" for card in manifest["cards"]):
                    print(f"[real-{index}] skipped: no accepted notes to export")
                    continue
                replace_scenario(f"real-{index}", data, folder)
        for path in args.apkg:
            package_check(path, folder)
    print("Anki compatibility gate passed.")


if __name__ == "__main__":
    main()
