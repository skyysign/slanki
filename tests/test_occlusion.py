import base64
import io
import json
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from PIL import Image

from converter.models import Card, Lecture
from converter.services.backups import export_backup, restore_backup
from converter.services.cards import Draft, add_drafts, update_card, validate_payload
from converter.services.exporting import OCCLUSION_MODEL_ID, export_deck
from converter.services.files import WorkflowError
from converter.services.generation import SCHEMA
from converter.services.occlusion import (
    add_occlusions,
    checked_occlusion,
    masks_from_form,
    occlusion_png,
)
from converter.services.selection import logistics_drafts, recent_questions

from .test_workflow import WorkflowFixture


class ImageOcclusionTests(WorkflowFixture):
    def setUp(self):
        self.page = self.lecture.pages.get(number=4)  # Native text is deliberately absent.
        self.mask = dict(page=4, left=20, top=30, right=220, bottom=130)
        self.values = {
            "page": 4,
            "note_type": "occlusion",
            "front": "Name the hidden part.",
            "back": "",
            "masks": json.dumps([self.mask]),
        }

    def add(self, masks=None):
        return add_occlusions(
            self.lecture, self.page, self.values["front"], "", masks or [self.mask]
        )

    def accept(self, card, **kwargs):
        return update_card(card.pk, card.version, card.front, card.back, "", "accepted", **kwargs)

    def test_mask_pixels_are_opaque_and_answer_reveals_source_even_without_text(self):
        self.assertTrue(self.page.warning)
        self.assertEqual(self.page.text, "")
        question = occlusion_png(self.page, self.mask)
        answer = occlusion_png(self.page, self.mask, answer=True)
        with (
            Image.open(Path(settings.MEDIA_ROOT) / self.page.image) as source,
            Image.open(io.BytesIO(question)) as hidden,
            Image.open(io.BytesIO(answer)) as revealed,
        ):
            self.assertEqual(hidden.size, source.size)
            box = (20, 30, 220, 130)
            self.assertEqual(hidden.crop(box).getextrema(), ((217, 217), (170, 170), (84, 84)))
            self.assertEqual(
                revealed.crop(box).tobytes(), source.convert("RGB").crop(box).tobytes()
            )
            self.assertEqual(hidden.getpixel((0, 0)), source.convert("RGB").getpixel((0, 0)))
        note = self.add()[0]
        self.assertEqual(
            (note.study_card_count, note.note_type, note.source_crop), (1, "occlusion", {})
        )
        self.assertEqual(recent_questions(self.lecture), [])
        self.assertEqual(logistics_drafts(self.lecture), [])

    def test_validation_atomic_creation_and_geometry_aware_dedup_preserve_edits(self):
        invalid = [
            None,
            {},
            [],
            {**self.mask, "page": 1},
            {**self.mask, "left": True},
            {**self.mask, "left": -1},
            {**self.mask, "right": self.page.width + 1},
            {**self.mask, "right": 21},
            {**self.mask, "top": 1.5},
            {**self.mask, "path": "../private.png"},
        ]
        for mask in invalid:
            with self.subTest(mask=mask), self.assertRaises(WorkflowError):
                add_occlusions(self.lecture, self.page, "Prompt", "", [self.mask, mask])
            self.assertFalse(Card.objects.exists())
        for raw in ("[]", "{}", "not JSON", json.dumps([self.mask] * 21), "[" * 2000):
            with self.subTest(raw=raw[:20]), self.assertRaises(WorkflowError):
                masks_from_form({"masks": raw}, self.page)
        other_mask = {**self.mask, "left": 240, "right": 380}
        cards = self.add([self.mask, other_mask, self.mask])
        self.assertEqual(len(cards), 2)
        moved = {**self.mask, "left": 25}
        card = self.accept(cards[0], occlusion=moved)
        self.assertEqual(self.add([self.mask, moved, other_mask]), [])
        card.refresh_from_db()
        self.assertEqual((card.occlusion, card.status, card.version), (moved, "accepted", 2))
        self.assertEqual(card.revisions.get().occlusion, self.mask)

    def test_stale_mask_edits_and_cross_type_attachments_are_rejected(self):
        card = self.add()[0]
        changed = self.accept(card, occlusion={**self.mask, "bottom": 140})
        with self.assertRaisesMessage(WorkflowError, "another tab"):
            self.accept(card, occlusion={**self.mask, "bottom": 150})
        changed.refresh_from_db()
        self.assertEqual(changed.occlusion["bottom"], 140)
        with self.assertRaises(WorkflowError):
            self.accept(changed, occlusion={})
        with self.assertRaises(WorkflowError):
            self.accept(changed, source_crop={**self.mask, "on_question": True})
        basic = self.accepted_card()
        with self.assertRaises(WorkflowError):
            self.accept(basic, occlusion={**self.mask, "page": basic.page.number})
        with self.assertRaises(WorkflowError):
            checked_occlusion(self.mask, self.page, "basic")
        changed.refresh_from_db()
        self.assertEqual(changed.version, 2)

    def test_manual_builder_preview_and_edit_are_source_scoped_and_do_not_generate(self):
        builder = reverse("occlusion_builder", args=[self.lecture.pk])
        self.assertEqual(self.client.get(builder, {"page": 4}).status_code, 200)
        self.assertEqual(self.client.get(builder, {"page": "bad"}).status_code, 400)
        with patch("converter.views.start_generation") as generate:
            preview = self.client.post(reverse("preview_note", args=[self.lecture.pk]), self.values)
            self.assertEqual(preview.status_code, 200)
            content = preview.json()
            self.assertEqual(content["study_cards"], 1)
            self.assertEqual(
                base64.b64decode(content["previews"][0]["question_image"].split(",", 1)[1]),
                occlusion_png(self.page, self.mask),
            )
            self.assertFalse(Card.objects.exists())
            response = self.client.post(builder, self.values)
            self.assertEqual(response.status_code, 302)
            generate.assert_not_called()
        card = Card.objects.get()
        editor = self.client.get(response.url)
        self.assertContains(editor, 'data-single="yes"')
        self.assertNotContains(editor, 'name="crop_enabled"')
        values = {
            **self.values,
            "card_id": str(card.pk),
            "version": card.version,
            "status": "accepted",
            "source_quote": "",
            "page": 1,
        }
        # A forged page cannot move this note away from its immutable source.
        response = self.client.post(reverse("save_card", args=[card.pk]), values)
        self.assertEqual(response.status_code, 302)
        card.refresh_from_db()
        self.assertEqual(card.page_id, self.page.pk)
        self.assertEqual(card.status, "accepted")
        values["masks"] = json.dumps([{**self.mask, "page": 1}])
        self.assertEqual(
            self.client.post(reverse("preview_note", args=[self.lecture.pk]), values).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(reverse("card_occlusion", args=[card.pk, "question"])).content,
            occlusion_png(self.page, self.mask),
        )
        self.assertEqual(
            self.client.get(reverse("card_occlusion", args=[card.pk, "invalid"])).status_code, 404
        )
        self.assertEqual(
            Client(enforce_csrf_checks=True).post(builder, self.values).status_code, 403
        )

    def test_masks_are_manual_only_and_bad_submission_retains_input(self):
        page = self.lecture.pages.first()
        with self.assertRaises(WorkflowError):
            add_drafts(self.lecture, [Draft(page, "Prompt", "", "", "occlusion")])
        payload = {
            "cards": [
                {
                    "page": page.number,
                    "front": "Prompt",
                    "back": "",
                    "note_type": "occlusion",
                    "source_quote": page.text[:30],
                }
            ]
        }
        with self.assertRaises(WorkflowError):
            validate_payload(payload, {page.number: page})
        self.assertNotIn(
            "occlusion",
            SCHEMA["properties"]["cards"]["items"]["properties"]["note_type"]["enum"],
        )
        response = self.client.post(
            reverse("occlusion_builder", args=[self.lecture.pk]),
            {**self.values, "front": "", "back": "Keep my explanation"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Keep my explanation", status_code=400)
        self.assertEqual(json.loads(response.context["masks_json"]), [self.mask])
        self.assertFalse(Card.objects.exists())

    def test_mixed_export_and_backup_preserve_mask_media_revisions_and_identity(self):
        self.accepted_card()
        card = self.accept(self.add()[0], occlusion={**self.mask, "left": 25})
        exported = export_deck(self.lecture)
        notes, cards, media = self.archive_db(exported)
        self.assertEqual(len(cards), 2)
        occluded = next(note for note in notes if note[1] == OCCLUSION_MODEL_ID)
        fields = occluded[3].split("\x1f")
        self.assertIn('class="source-crop"', fields[1])
        self.assertIn('class="source-crop"', fields[2])
        self.assertNotEqual(fields[1], fields[2])
        self.assertNotIn("slides_", fields[1])
        self.assertIn("slides_", fields[4])
        self.assertEqual(len([name for name in media.values() if name.startswith("occlusion_")]), 2)
        backup = export_backup(self.lecture)
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            self.assertEqual(json.loads(archive.read("manifest.json"))["version"], 9)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        with override_settings(MEDIA_ROOT=destination):
            restored = restore_backup(SimpleUploadedFile("backup.zip", backup))
            saved = restored.cards.get(pk=card.pk)
            self.assertEqual(saved.occlusion, card.occlusion)
            self.assertEqual(saved.revisions.get().occlusion, self.mask)
            restored_notes, restored_cards, restored_media = self.archive_db(export_deck(restored))
            self.assertEqual(notes, restored_notes)
            self.assertEqual(len(restored_cards), 2)
            self.assertEqual(media, restored_media)

    def test_invalid_mask_backups_roll_back_without_writing_assets(self):
        self.accept(self.add()[0])
        data = export_backup(self.lecture)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        for mode in ("wrong_page", "revision", "missing", "crop"):
            output = io.BytesIO()
            with (
                zipfile.ZipFile(io.BytesIO(data)) as source,
                zipfile.ZipFile(output, "w") as target,
            ):
                manifest = json.loads(source.read("manifest.json"))
                card = manifest["cards"][0]
                if mode == "wrong_page":
                    card["occlusion"]["page"] = 1
                elif mode == "revision":
                    card["revisions"][0]["occlusion"]["right"] = 0
                elif mode == "missing":
                    card["occlusion"] = {}
                else:
                    card["source_crop"] = {**self.mask, "on_question": True}
                for name in source.namelist():
                    target.writestr(
                        name, json.dumps(manifest) if name == "manifest.json" else source.read(name)
                    )
            destination = Path(self.directory.name) / str(uuid.uuid4())
            destination.mkdir()
            with override_settings(MEDIA_ROOT=destination), self.assertRaises(WorkflowError):
                restore_backup(SimpleUploadedFile("invalid.zip", output.getvalue()))
            self.assertFalse(Lecture.objects.exists())
            self.assertEqual(list(destination.iterdir()), [])
