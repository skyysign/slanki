import base64
import io
import json
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from converter.models import Card, Lecture
from converter.services.backups import export_backup, restore_backup
from converter.services.cards import update_card
from converter.services.crops import checked_crop, crop_png
from converter.services.exporting import export_deck
from converter.services.files import WorkflowError

from .test_workflow import WorkflowFixture


class SourceCropTests(WorkflowFixture):
    def setUp(self):
        self.card = self.accepted_card()
        self.crop = dict(
            page=self.card.page.number, left=10, top=20, right=210, bottom=120, on_question=True
        )

    def save_crop(self, crop):
        self.card = update_card(
            self.card.pk,
            self.card.version,
            self.card.front,
            self.card.back,
            self.card.source_quote,
            "accepted",
            source_crop=crop,
        )
        return self.card

    def form_values(self):
        return {
            "front": self.card.front,
            "back": self.card.back,
            "source_quote": self.card.source_quote,
            "status": self.card.status,
            "note_type": self.card.note_type,
            "version": self.card.version,
            "card_id": str(self.card.pk),
            "crop_present": "yes",
            "crop_enabled": "yes",
            "crop_on_question": "yes",
            **{"crop_" + key: self.crop[key] for key in ("left", "top", "right", "bottom")},
        }

    def test_crop_pixels_export_media_and_question_answer_placement(self):
        self.save_crop(self.crop)
        cropped = crop_png(self.card.page, self.crop)
        with (
            Image.open(io.BytesIO(cropped)) as actual,
            Image.open(Path(settings.MEDIA_ROOT) / self.card.page.image) as source,
        ):
            self.assertEqual(actual.size, (200, 100))
            with source.crop((10, 20, 210, 120)) as expected:
                self.assertEqual(actual.tobytes(), expected.tobytes())
        data = export_deck(self.lecture)
        notes, cards, media = self.archive_db(data)
        crop_name = next(name for name in media.values() if name.startswith("crop_"))
        self.assertEqual(len(media), 2)  # Crop plus complete source slide.
        fields = notes[0][3].split("\x1f")
        self.assertIn(crop_name, fields[0])
        self.assertNotIn(crop_name, fields[2])
        self.assertIn("slides_", fields[2])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            index = next(index for index, name in media.items() if name == crop_name)
            self.assertEqual(archive.read(index), cropped)
        self.save_crop({**self.crop, "on_question": False})
        answer_notes, _, _ = self.archive_db(export_deck(self.lecture))
        fields = answer_notes[0][3].split("\x1f")
        self.assertNotIn(crop_name, fields[0])
        self.assertIn(crop_name, fields[2])
        self.save_crop({**self.crop, "right": 220})
        _, _, changed_media = self.archive_db(export_deck(self.lecture))
        self.assertNotIn(crop_name, changed_media.values())
        self.save_crop({})
        removed_notes, _, removed_media = self.archive_db(export_deck(self.lecture))
        self.assertEqual(len(removed_media), 1)
        self.assertEqual(removed_notes[0][0], notes[0][0])

    def test_geometry_validation_and_stale_edits_preserve_saved_crop_and_history(self):
        invalid = [
            None,
            [],
            {"path": "../secret"},
            {**self.crop, "page": 99},
            {**self.crop, "left": -1},
            {**self.crop, "right": self.card.page.width + 1},
            {**self.crop, "right": 11},
            {**self.crop, "top": 0.1},
            {**self.crop, "left": True},
            {**self.crop, "on_question": "yes"},
        ]
        for crop in invalid:
            with self.subTest(crop=crop), self.assertRaises(WorkflowError):
                checked_crop(crop, self.card.page)
        stale_version = self.card.version
        self.save_crop(self.crop)
        with self.assertRaisesMessage(WorkflowError, "another tab"):
            update_card(
                self.card.pk,
                stale_version,
                "Stale edit?",
                self.card.back,
                self.card.source_quote,
                "accepted",
                source_crop={},
            )
        self.card.refresh_from_db()
        self.assertEqual(self.card.source_crop, self.crop)
        self.card = update_card(
            self.card.pk,
            self.card.version,
            "A text-only edit?",
            self.card.back,
            self.card.source_quote,
            "accepted",
        )
        self.assertEqual(self.card.source_crop, self.crop)
        self.assertEqual(
            self.card.revisions.get(version=self.card.version - 1).source_crop, self.crop
        )

    def test_preview_is_unsaved_and_bad_form_does_not_accept_note(self):
        url = reverse("preview_note", args=[self.lecture.pk])
        values = self.form_values()
        with patch("converter.services.generation.codex_generate") as provider:
            response = self.client.post(url, values)
            provider.assert_not_called()
        self.assertEqual(response.status_code, 200)
        decoded = base64.b64decode(response.json()["crop_image"].split(",", 1)[1])
        self.assertEqual(decoded, crop_png(self.card.page, self.crop))
        self.assertTrue(response.json()["crop_on_question"])
        self.card.refresh_from_db()
        self.assertEqual(self.card.source_crop, {})
        self.assertEqual(self.client.post(url, {**values, "card_id": "invalid"}).status_code, 400)
        self.assertEqual(
            self.client.post(url, {**values, "card_id": str(uuid.uuid4())}).status_code, 404
        )
        save = reverse("save_card", args=[self.card.pk])
        self.assertEqual(self.client.post(save, {**values, "crop_right": 0}).status_code, 400)
        self.card.refresh_from_db()
        self.assertEqual(self.card.source_crop, {})
        self.assertEqual(self.client.post(save, values).status_code, 302)
        self.card.refresh_from_db()
        self.assertEqual(self.card.source_crop, self.crop)
        self.assertEqual(
            self.client.get(reverse("card_crop", args=[self.card.pk])).content, decoded
        )
        self.assertContains(
            self.client.get(reverse("preview_export", args=[self.lecture.pk])),
            reverse("card_crop", args=[self.card.pk]),
        )

    def test_missing_or_mismatched_source_image_fails_before_save_or_export(self):
        page = self.card.page
        with patch("converter.services.crops.Image.open", side_effect=OSError):
            self.assertEqual(
                self.client.post(
                    reverse("save_card", args=[self.card.pk]), self.form_values()
                ).status_code,
                400,
            )
        self.card.refresh_from_db()
        self.assertEqual(self.card.source_crop, {})
        page.width += 1
        with self.assertRaisesMessage(WorkflowError, "dimensions"):
            crop_png(page, self.crop)
        self.save_crop(self.crop)
        with (
            patch("converter.services.crops.Image.open", side_effect=OSError),
            self.assertRaises(WorkflowError),
        ):
            export_deck(self.lecture)

    def test_backup_roundtrip_preserves_crops_revisions_and_export_identity(self):
        self.save_crop({**self.crop, "on_question": False})
        self.save_crop(self.crop)
        expected = self.archive_db(export_deck(self.lecture))
        expected_png = crop_png(self.card.page, self.crop)
        data = export_backup(self.lecture)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        with override_settings(MEDIA_ROOT=destination):
            restored = restore_backup(SimpleUploadedFile("backup.zip", data))
            saved = restored.cards.get(pk=self.card.pk)
            self.assertEqual(saved.source_crop, self.crop)
            self.assertEqual(
                saved.revisions.get(version=saved.version - 1).source_crop,
                {**self.crop, "on_question": False},
            )
            actual = self.archive_db(export_deck(restored))
            self.assertEqual(actual[0], expected[0])
            self.assertEqual(actual[2], expected[2])
            self.assertEqual(crop_png(saved.page, saved.source_crop), expected_png)

    def test_invalid_backup_crops_roll_back_and_legacy_notes_restore_without_crops(self):
        self.save_crop(self.crop)
        data = export_backup(self.lecture)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        for mode in ("wrong_page", "bad_revision", "legacy"):
            output = io.BytesIO()
            with (
                zipfile.ZipFile(io.BytesIO(data)) as source,
                zipfile.ZipFile(output, "w") as target,
            ):
                manifest = json.loads(source.read("manifest.json"))
                note = next(note for note in manifest["cards"] if note["id"] == str(self.card.pk))
                if mode == "wrong_page":
                    note["source_crop"]["page"] = 99
                elif mode == "bad_revision":
                    note["revisions"][0]["source_crop"] = {**self.crop, "right": -1}
                else:
                    manifest["version"] = 5
                    for run in manifest["runs"]:
                        for key in (
                            "text_enabled",
                            "occlusion_enabled",
                            "image_completed_pages",
                            "suggestions",
                        ):
                            run.pop(key)
                        run.pop("context_enabled")
                        run.pop("context_data")
                        for key in ("visual_enabled", "purpose", "rundown_data"):
                            run.pop(key)
                    for card in manifest["cards"]:
                        card.pop("source_crop")
                        card.pop("occlusion")
                        card.pop("visual_masks")
                        for revision in card["revisions"]:
                            revision.pop("source_crop")
                            revision.pop("occlusion")
                            revision.pop("visual_masks")
                for name in source.namelist():
                    target.writestr(
                        name, json.dumps(manifest) if name == "manifest.json" else source.read(name)
                    )
            destination = Path(self.directory.name) / str(uuid.uuid4())
            destination.mkdir()
            with override_settings(MEDIA_ROOT=destination):
                if mode == "legacy":
                    restored = restore_backup(SimpleUploadedFile("legacy.zip", output.getvalue()))
                    self.assertEqual(restored.cards.get(pk=self.card.pk).source_crop, {})
                    self.assertFalse(restored.cards.exclude(source_crop={}).exists())
                else:
                    with self.assertRaises(WorkflowError):
                        restore_backup(SimpleUploadedFile("invalid.zip", output.getvalue()))
                    self.assertFalse(Lecture.objects.exists())
                    self.assertEqual(list(destination.iterdir()), [])


class TickableFormatTests(WorkflowFixture):
    @patch("converter.views.start_generation")
    def test_checkbox_combinations_and_empty_invalid_selection(self, start):
        for formats, expected in [
            (["basic"], "basic"),
            (["cloze"], "cloze"),
            (["cloze", "basic"], "mixed"),
            (["reversed"], "reversed"),
            (["reversed", "basic"], "basic_reversed"),
            (["cloze", "reversed"], "cloze_reversed"),
            (["reversed", "cloze", "basic"], "all"),
            ([], None),
            (["mixed"], None),
            (["basic", "basic"], None),
        ]:
            values = {"pages": [1], "consent": "yes", "formats_present": "yes", "formats": formats}
            start.reset_mock()
            prompt = self.client.post(reverse("prompt", args=[self.lecture.pk]), values)
            generate = self.client.post(reverse("generate", args=[self.lecture.pk]), values)
            if expected:
                self.assertContains(prompt, f"CARD FORMAT: {expected}")
                self.assertEqual(generate.status_code, 302)
                self.assertEqual(start.call_args.kwargs["card_format"], expected)
            else:
                self.assertEqual(prompt.status_code, 400)
                self.assertEqual(generate.status_code, 400)
                start.assert_not_called()
