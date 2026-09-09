"""Actual Anki backend checks; use an isolated collection, never the user's profile."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.conf import settings

from converter.services.cards import update_card
from converter.services.exporting import export_deck
from tests.test_workflow import WorkflowFixture


@skipUnless(importlib.util.find_spec("anki"), "Install requirements-dev.txt for Anki backend tests")
class AnkiImportTests(WorkflowFixture):
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
