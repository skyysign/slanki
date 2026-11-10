"""Actual Anki backend checks; use an isolated collection, never the user's profile."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.conf import settings
from django.utils.html import strip_tags

from converter.services.cards import Draft, add_drafts, undo_card_edit, update_card
from converter.services.exporting import OCCLUSION_MODEL_ID, REVERSED_MODEL_ID, export_deck
from converter.services.note_types import study_previews
from converter.services.occlusion import add_occlusions
from tests.test_workflow import WorkflowFixture


@skipUnless(importlib.util.find_spec("anki"), "Install requirements-dev.txt for Anki backend tests")
class AnkiImportTests(WorkflowFixture):
    def test_visual_question_covers_reveal_and_updates_preserve_schedule(self):
        from anki.collection import Collection
        from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest

        from converter.models import GenerationRun
        from converter.services.exporting import VISUAL_MODEL_ID
        from converter.services.visual_cards import add_visual_drafts, validate_visual_payload
        from tests.test_visual_rundown import visual_output

        page = self.lecture.pages.get(number=4)
        run = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[4])
        add_visual_drafts(run, page, validate_visual_payload(visual_output(page), page), 1)
        note = self.lecture.cards.get()
        note = update_card(note.pk, 1, note.front, "Answer-only explanation", "", "accepted")
        with TemporaryDirectory(dir=settings.WORK_DIR) as directory:
            folder = Path(directory)
            collection = Collection(str(folder / "visual.anki2"))
            package = folder / "visual.apkg"
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
                self.assertEqual(len(ids), 1)
                card = collection.get_card(ids[0])
                self.assertEqual(card.note().mid, VISUAL_MODEL_ID)
                self.assertIn(card.note()["Hidden"], card.question())
                self.assertNotIn(card.note()["Revealed"], card.question())
                self.assertNotIn("slides_", card.question())
                self.assertNotIn("Answer-only explanation", card.question())
                self.assertIn(card.note()["Revealed"], card.answer())
                self.assertIn("Answer-only explanation", card.answer())
                card.type, card.queue, card.ivl, card.due, card.reps, card.lapses = (
                    2,
                    2,
                    15,
                    40,
                    8,
                    1,
                )
                collection.update_card(card)
                before = card.note()["Hidden"]
                import_package()
                note = update_card(
                    note.pk,
                    note.version,
                    "Edited figure prompt",
                    note.back,
                    "",
                    "accepted",
                    visual_masks=[{**note.visual_masks[0], "right": 240}],
                )
                import_package()
                self.assertEqual(collection.find_cards(""), ids)
                card = collection.get_card(ids[0])
                self.assertEqual(
                    (card.ord, card.ivl, card.due, card.reps, card.lapses), (0, 15, 40, 8, 1)
                )
                self.assertNotEqual(card.note()["Hidden"], before)
                self.assertIn("Edited figure prompt", card.question())
                undo_card_edit(note.pk, note.version)
                import_package()
                self.assertEqual(collection.find_cards(""), ids)
                card = collection.get_card(ids[0])
                self.assertEqual(card.note()["Hidden"], before)
                self.assertEqual(
                    (card.ord, card.ivl, card.due, card.reps, card.lapses), (0, 15, 40, 8, 1)
                )
                self.assertEqual(collection.media.check().missing, [])
            finally:
                collection.close()

    def test_occlusion_mask_edits_and_adding_regions_keep_independent_review_schedules(self):
        from anki.collection import Collection
        from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest

        self.accepted_card()
        page = self.lecture.pages.get(number=4)
        masks = [
            dict(page=4, left=20, top=30, right=220, bottom=130),
            dict(page=4, left=250, top=30, right=420, bottom=130),
        ]
        notes = add_occlusions(
            self.lecture, page, "Name the hidden part.", "Extra explanation", masks
        )
        for note in notes:
            update_card(note.pk, note.version, note.front, note.back, "", "accepted")
        with TemporaryDirectory(dir=settings.WORK_DIR) as directory:
            folder = Path(directory)
            collection = Collection(str(folder / "occlusion.anki2"))
            package = folder / "occlusion.apkg"
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
                self.assertEqual(len(ids), 3)
                schedules = {}
                hidden_fields = {}
                for index, identifier in enumerate(ids):
                    card = collection.get_card(identifier)
                    card.type, card.queue = 2, 2
                    card.ivl, card.due, card.reps, card.lapses = (
                        15 + index,
                        40 + index,
                        8 + index,
                        1,
                    )
                    collection.update_card(card)
                    schedules[identifier] = (card.ord, card.ivl, card.due, card.reps, card.lapses)
                    if card.note().mid == OCCLUSION_MODEL_ID:
                        self.assertEqual(card.ord, 0)
                        hidden_fields[identifier] = card.note()["Hidden"]
                        self.assertIn(card.note()["Hidden"], card.question())
                        self.assertNotIn(card.note()["Revealed"], card.question())
                        self.assertNotIn("Extra explanation", card.question())
                        self.assertNotIn("slides_", card.question())
                        self.assertIn(card.note()["Revealed"], card.answer())
                        self.assertIn("Extra explanation", card.answer())
                        self.assertIn("slides_", card.answer())
                self.assertEqual(len(hidden_fields), 2)
                import_package()
                edited = self.lecture.cards.get(pk=notes[0].pk)
                update_card(
                    edited.pk,
                    edited.version,
                    "Edited image prompt",
                    "Edited explanation",
                    "",
                    "accepted",
                    occlusion={**edited.occlusion, "right": 230},
                )
                import_package()
                self.assertEqual(set(collection.find_cards("")), set(ids))
                changed_images = 0
                for identifier, expected in schedules.items():
                    card = collection.get_card(identifier)
                    self.assertEqual(
                        (card.ord, card.ivl, card.due, card.reps, card.lapses), expected
                    )
                    if (
                        identifier in hidden_fields
                        and card.note()["Hidden"] != hidden_fields[identifier]
                    ):
                        changed_images += 1
                        self.assertIn("Edited image prompt", card.question())
                        self.assertIn("Edited explanation", card.answer())
                self.assertEqual(changed_images, 1)
                added = add_occlusions(
                    self.lecture,
                    page,
                    "A new region",
                    "",
                    [dict(page=4, left=20, top=200, right=200, bottom=260)],
                )[0]
                update_card(added.pk, added.version, added.front, "", "", "accepted")
                import_package()
                self.assertEqual(len(collection.find_cards("")), 4)
                for identifier, expected in schedules.items():
                    card = collection.get_card(identifier)
                    self.assertEqual(
                        (card.ord, card.ivl, card.due, card.reps, card.lapses), expected
                    )
                self.assertEqual(collection.media.check().missing, [])
            finally:
                collection.close()

    def test_reverse_cards_render_both_directions_and_preserve_all_schedules_on_reimport(self):
        from anki.collection import Collection
        from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest

        self.accepted_card()
        page = self.lecture.pages.first()
        add_drafts(self.lecture, [Draft(page, "A {{c3::memory}} example.", "", "", "cloze")])
        cloze = self.lecture.cards.get(note_type="cloze")
        update_card(cloze.pk, cloze.version, cloze.front, "", "", "accepted")
        with TemporaryDirectory(dir=settings.WORK_DIR) as directory:
            folder = Path(directory)
            collection = Collection(str(folder / "reverse.anki2"))
            package = folder / "reverse.apkg"
            try:

                def import_package():
                    package.write_bytes(export_deck(self.lecture))
                    collection.import_anki_package(
                        ImportAnkiPackageRequest(
                            package_path=str(package),
                            options=ImportAnkiPackageOptions(with_scheduling=False),
                        )
                    )

                def set_schedules(ids):
                    result = {}
                    for index, identifier in enumerate(ids):
                        card = collection.get_card(identifier)
                        card.type, card.queue = 2, 2
                        card.ivl, card.due, card.reps, card.lapses = (
                            11 + index,
                            40 + index,
                            6 + index,
                            1,
                        )
                        collection.update_card(card)
                        result[identifier] = (card.ord, card.ivl, card.due, card.reps, card.lapses)
                    return result

                import_package()
                old_ids = collection.find_cards("")
                self.assertEqual(len(old_ids), 2)
                schedules = set_schedules(old_ids)
                add_drafts(
                    self.lecture,
                    [
                        Draft(
                            page,
                            "Retrieval practice",
                            "Trying to recall information from memory",
                            "",
                            "reversed",
                        )
                    ],
                )
                note = self.lecture.cards.get(note_type="reversed")
                crop = dict(
                    page=page.number, left=10, top=20, right=150, bottom=120, on_question=False
                )
                note = update_card(
                    note.pk, note.version, note.front, note.back, "", "accepted", source_crop=crop
                )
                import_package()
                reverse_ids = list(set(collection.find_cards("")) - set(old_ids))
                self.assertEqual(len(reverse_ids), 2)
                self.assertEqual(sorted(collection.get_card(i).ord for i in reverse_ids), [0, 1])
                self.assertEqual(len({collection.get_card(i).nid for i in reverse_ids}), 1)
                schedules.update(set_schedules(reverse_ids))
                for identifier in reverse_ids:
                    card = collection.get_card(identifier)
                    self.assertEqual(card.note().mid, REVERSED_MODEL_ID)
                    self.assertEqual(
                        strip_tags(card.question().rsplit("</style>", 1)[-1]).strip(),
                        note.front if card.ord == 0 else note.back,
                    )
                    self.assertNotIn(note.back if card.ord == 0 else note.front, card.question())
                    self.assertNotIn("<img", card.question())
                    self.assertIn('class="source-crop"', card.answer())
                    self.assertIn("slides_", card.answer())
                # Unchanged reimport, edited sides/crop placement, and crop removal.
                import_package()
                for updated_crop in ({**crop, "on_question": True}, {}):
                    note = update_card(
                        note.pk,
                        note.version,
                        "Edited retrieval term",
                        "Edited definition",
                        "",
                        "accepted",
                        source_crop=updated_crop,
                    )
                    import_package()
                    self.assertEqual(set(collection.find_cards("")), set(schedules))
                    for identifier, expected in schedules.items():
                        card = collection.get_card(identifier)
                        self.assertEqual(
                            (card.ord, card.ivl, card.due, card.reps, card.lapses), expected
                        )
                        if identifier in reverse_ids:
                            question = card.question()
                            self.assertIn(note.front if card.ord == 0 else note.back, question)
                            self.assertNotIn(note.back if card.ord == 0 else note.front, question)
                            self.assertEqual('class="source-crop"' in question, bool(updated_crop))
                            self.assertIn(note.front, card.answer())
                            self.assertIn(note.back, card.answer())
                    self.assertEqual(collection.media.check().missing, [])
            finally:
                collection.close()

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
                    source_crop=dict(
                        page=note.page.number,
                        left=10,
                        top=20,
                        right=210,
                        bottom=120,
                        on_question=True,
                    ),
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
                        self.assertIn('class="source-crop"', card.question())
                        self.assertIn('class="source-crop"', card.answer())
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
                card = update_card(
                    card.id,
                    card.version,
                    "Updated question within the same second?",
                    card.back,
                    card.source_quote,
                    "accepted",
                    source_crop=dict(
                        page=card.page.number,
                        left=10,
                        top=20,
                        right=210,
                        bottom=120,
                        on_question=False,
                    ),
                )
                import_package()
                saved = collection.get_card(ids[0])
                self.assertEqual((saved.id, saved.ivl, saved.due, saved.reps, saved.lapses), before)
                self.assertIn("Updated question within the same second?", saved.note().fields[0])
                self.assertIn("Page 1", saved.answer())
                self.assertIn("<img", saved.answer())
                self.assertNotIn('class="source-crop"', saved.question())
                self.assertIn('class="source-crop"', saved.answer())
                card = update_card(
                    card.id,
                    card.version,
                    card.front,
                    card.back,
                    card.source_quote,
                    "accepted",
                    source_crop={**card.source_crop, "right": 220, "on_question": True},
                )
                import_package()
                saved = collection.get_card(ids[0])
                self.assertEqual((saved.id, saved.ivl, saved.due, saved.reps, saved.lapses), before)
                self.assertIn('class="source-crop"', saved.question())
                update_card(
                    card.id,
                    card.version,
                    card.front,
                    card.back,
                    card.source_quote,
                    "accepted",
                    source_crop={},
                )
                import_package()
                saved = collection.get_card(ids[0])
                self.assertEqual((saved.id, saved.ivl, saved.due, saved.reps, saved.lapses), before)
                self.assertNotIn('class="source-crop"', saved.question())
                self.assertNotIn('class="source-crop"', saved.answer())
                self.assertEqual(collection.media.check().missing, [])
            finally:
                collection.close()
