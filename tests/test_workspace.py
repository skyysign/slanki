from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from converter.services.cards import undo_card_edit, update_card
from converter.services.files import WorkflowError

from .test_workflow import WorkflowFixture


class WorkspaceTests(WorkflowFixture):
    def test_empty_lecture_has_source_tools_and_invalid_import_keeps_library_counts(self):
        response = self.client.get(self.lecture.get_absolute_url())
        self.assertContains(response, "data-page-select")
        self.assertContains(response, "data-figure-question")
        self.assertContains(response, 'data-open-dialog="manual-card"')
        self.drafts()
        response = self.client.post(
            reverse("upload"), {"pdf": SimpleUploadedFile("bad.pdf", b"invalid PDF")}
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "data-open-on-load", status_code=400)
        self.assertContains(response, "Review 5 drafts", status_code=400)

    def test_new_workspace_defaults_to_qa_and_cloze_without_reverse(self):
        self.drafts()
        response = self.client.get(self.lecture.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_formats"], ("basic", "cloze"))
        self.assertContains(response, "Study guide")
        self.assertContains(response, "data-auto-preview")
        self.assertContains(response, "data-set-aside")
        self.assertNotContains(response, 'value="reversed" checked')
        self.assertNotContains(response, "Turn your slides into cards you can trust")

    def test_keep_next_and_undo_restore_saved_content_and_identity(self):
        self.drafts()
        card = self.lecture.cards.first()
        before = (card.pk, card.fingerprint, card.page_id, card.front, card.back, card.source_quote)
        crop = dict(page=card.page.number, left=10, top=10, right=100, bottom=100, on_question=True)
        response = self.client.post(
            reverse("save_card", args=[card.pk]),
            {
                "version": card.version,
                "front": "Edited in the new workspace",
                "back": card.back,
                "source_quote": card.source_quote,
                "status": "draft",
                "action": "accept_next",
                "crop_present": "yes",
                "crop_enabled": "yes",
                "crop_on_question": "yes",
                "crop_left": 10,
                "crop_top": 10,
                "crop_right": 100,
                "crop_bottom": 100,
            },
        )
        self.assertEqual(response.status_code, 302)
        card.refresh_from_db()
        self.assertEqual((card.status, card.version, card.source_crop), ("accepted", 2, crop))
        self.assertIn(f"undo={card.pk}&undo_version=2", response.url)
        page = self.client.get(response.url)
        self.assertContains(page, "Undo last change")
        undone = self.client.post(reverse("undo_card", args=[card.pk]), {"version": 2})
        self.assertEqual(undone.status_code, 302)
        card.refresh_from_db()
        self.assertEqual(
            (card.pk, card.fingerprint, card.page_id, card.front, card.back, card.source_quote),
            before,
        )
        self.assertEqual((card.status, card.source_crop, card.version), ("draft", {}, 3))
        self.assertEqual(card.revisions.count(), 2)

    def test_set_aside_next_keeps_edits_and_stale_undo_cannot_overwrite_another_tab(self):
        self.drafts()
        card = self.lecture.cards.first()
        response = self.client.post(
            reverse("save_card", args=[card.pk]),
            {
                "version": 1,
                "front": "Edited before setting aside",
                "back": card.back,
                "source_quote": card.source_quote,
                "status": "draft",
                "action": "reject_next",
            },
        )
        self.assertEqual(response.status_code, 302)
        card.refresh_from_db()
        self.assertEqual((card.front, card.status), ("Edited before setting aside", "rejected"))
        edited = update_card(
            card.pk, 2, "Another tab's newer edit", card.back, card.source_quote, "accepted"
        )
        self.assertEqual(
            self.client.post(reverse("undo_card", args=[card.pk]), {"version": 2}).status_code, 400
        )
        card.refresh_from_db()
        self.assertEqual((card.front, card.status, card.version), (edited.front, "accepted", 3))

    def test_undo_requires_csrf_post_valid_version_and_a_previous_revision(self):
        self.drafts()
        card = self.lecture.cards.first()
        url = reverse("undo_card", args=[card.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(
            Client(enforce_csrf_checks=True).post(url, {"version": 1}).status_code, 403
        )
        self.assertEqual(self.client.post(url, {"version": "bad"}).status_code, 400)
        with self.assertRaises(WorkflowError):
            undo_card_edit(card.pk, 1)
        self.assertIsNone(
            self.client.get(
                self.lecture.get_absolute_url(), {"undo": "bad", "undo_version": "bad"}
            ).context["undo_card"]
        )

    def test_library_prioritises_existing_work_and_search(self):
        self.drafts()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Search your lectures")
        self.assertContains(response, "Review 5 drafts")
        self.assertNotContains(response, 'class="hero"')
