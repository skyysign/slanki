"""Actual Anki backend checks; use an isolated collection, never the user's profile."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.conf import settings
from django.utils.html import strip_tags

from converter.services.cards import Draft, add_drafts, update_card
from converter.services.exporting import export_deck
from converter.services.note_types import study_previews
from tests.test_workflow import WorkflowFixture


@skipUnless(importlib.util.find_spec("anki"), "Install requirements-dev.txt for Anki backend tests")
class AnkiImportTests(WorkflowFixture):
    def test_mixed_cloze_rendering_ordinals_media_and_edited_reimport(self):
        from anki.collection import Collection
        from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest

        basic = self.accepted_card()
        page = self.lecture.pages.first()
        front = "{{c1::First}} and {{c1::second}} versus {{c7::third::hint}}."
        add_drafts(self.lecture, [Draft(page, front, "Extra explanation", "", "cloze")])
        note = self.lecture.cards.get(note_type="cloze")
        note = update_card(note.pk, note.version, note.front, note.back, "", "accepted")
        with TemporaryDirectory(dir=settings.WORK_DIR) as directory:
            folder = Path(directory)
            collection = Collection(str(folder / "mixed.anki2"))
            package = folder / "mixed.apkg"
            try:

                def import_package():
                    package.write_bytes(export_deck(self.lecture))
                    collection.import_anki_package(
                        ImportAnkiPackageRequest(
                            package_path=str(package),
                            options=ImportAnkiPackageOptions(with_scheduling=False),
                        )
                    )

                import_package()
                ids = collection.find_cards("")
                self.assertEqual(len(ids), 1 + len(study_previews(note.front, note.back, "cloze")))
                cloze_ids = collection.find_cards('note:"Recalloom — Cloze v1"')
                self.assertEqual(sorted(collection.get_card(i).ord for i in cloze_ids), [0, 6])
                before = {}
                for i in ids:
                    card = collection.get_card(i)
                    if i in cloze_ids:
                        question, answer = strip_tags(card.question()), card.answer()
                        if card.ord == 0:
                            self.assertNotIn("First", question)
                            self.assertNotIn("second", question)
                            self.assertIn("third", question)
                        else:
                            self.assertIn("First", question)
                            self.assertIn("[hint]", question)
                            self.assertNotIn("third", question)
                        self.assertIn("First", answer)
                        self.assertIn("third", answer)
                        self.assertIn("Extra explanation", answer)
                        self.assertIn("<img", answer)
                    card.type, card.queue = 2, 2
                    card.ivl, card.due, card.reps, card.lapses = 19, 51, 8, 1
                    collection.update_card(card)
                    before[i] = (card.ord, card.ivl, card.due, card.reps, card.lapses)
                import_package()
                update_card(
                    note.pk,
                    note.version,
                    front.replace("First", "Updated first"),
                    "Updated extra",
                    "",
                    "accepted",
                )
                update_card(
                    basic.pk,
                    basic.version,
                    "Updated basic?",
                    basic.back,
                    basic.source_quote,
                    "accepted",
                )
                import_package()
                self.assertEqual(set(collection.find_cards("")), set(ids))
                for i in ids:
                    card = collection.get_card(i)
                    self.assertEqual(
                        (card.ord, card.ivl, card.due, card.reps, card.lapses), before[i]
                    )
                    if i in cloze_ids:
                        self.assertIn("Updated first", card.answer())
                        self.assertIn("Updated extra", card.answer())
                self.assertEqual(collection.media.check().missing, [])
            finally:
                collection.close()

    def test_import_update_preserves_schedule(self):
        from anki.collection import Collection
        from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest

        card = self.accepted_card()
        with TemporaryDirectory(dir=settings.WORK_DIR) as directory:
            directory = Path(directory)
            package = directory / "lecture.apkg"
            collection = Collection(str(directory / "collection.anki2"))
            try:

                def import_package():
                    package.write_bytes(export_deck(self.lecture))
                    return collection.import_anki_package(
                        ImportAnkiPackageRequest(
                            package_path=str(package),
                            options=ImportAnkiPackageOptions(with_scheduling=False),
                        )
                    )

                import_package()
                ids = collection.find_cards("")
                self.assertEqual(len(ids), 1)
                existing = collection.get_card(ids[0])
                # Give the imported card a mature review schedule to detect accidental resets.
                existing.type, existing.queue = 2, 2
                existing.ivl, existing.due, existing.reps, existing.lapses = 21, 70, 12, 2
                collection.update_card(existing)
                before = (existing.id, existing.ivl, existing.due, existing.reps, existing.lapses)
                import_package()
                self.assertEqual(collection.find_cards(""), ids)
                saved = collection.get_card(ids[0])
                self.assertEqual((saved.id, saved.ivl, saved.due, saved.reps, saved.lapses), before)
                update_card(
                    card.id,
                    card.version,
                    "Updated question within the same second?",
                    card.back,
                    card.source_quote,
                    "accepted",
                )
                import_package()
                saved = collection.get_card(ids[0])
                self.assertEqual((saved.id, saved.ivl, saved.due, saved.reps, saved.lapses), before)
                self.assertIn("Updated question within the same second?", saved.note().fields[0])
                self.assertIn("Page 1", saved.answer())
                self.assertIn("<img", saved.answer())
                self.assertEqual(collection.media.check().missing, [])
            finally:
                collection.close()
