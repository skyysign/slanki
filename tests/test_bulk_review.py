from django.core import signing
from django.test import Client
from django.urls import reverse

from converter.models import Card, CardRevision, Lecture
from converter.services.cards import Draft, add_drafts, fingerprint, keep_drafts, update_card
from converter.services.files import WorkflowError
from converter.services.occlusion import add_occlusions

from .test_workflow import WorkflowFixture


class BulkReviewTests(WorkflowFixture):
    def setUp(self):
        self.drafts()
        self.url = reverse("keep_all_drafts", args=[self.lecture.pk])

    def token(self):
        return self.client.get(self.lecture.get_absolute_url()).context["keep_drafts_token"]

    def test_keep_all_preserves_edits_sources_formats_and_existing_decisions(self):
        first, ready, aside = list(self.lecture.cards.all())[:3]
        crop = dict(
            page=first.page.number, left=10, top=10, right=100, bottom=100, on_question=True
        )
        first = update_card(
            first.pk,
            1,
            "An edited question",
            first.back,
            first.source_quote,
            "draft",
            source_crop=crop,
        )
        ready = update_card(ready.pk, 1, ready.front, ready.back, ready.source_quote, "accepted")
        aside = update_card(aside.pk, 1, aside.front, aside.back, aside.source_quote, "rejected")
        page = first.page
        add_drafts(
            self.lecture,
            [
                Draft(page, "{{c1::Recall}} helps {{c2::memory}}.", "", "", "cloze"),
                Draft(page, "Retrieval", "Recall from memory", "", "reversed"),
            ],
        )
        add_occlusions(
            self.lecture,
            self.lecture.pages.get(number=4),
            "Name this region.",
            "",
            [dict(page=4, left=20, top=30, right=220, bottom=130)],
        )
        Card.objects.create(
            lecture=self.lecture,
            page=page,
            note_type="visual",
            front="Explain this graph.",
            back="A synthetic answer.",
            fingerprint=fingerprint("Explain this graph."),
            source_crop=dict(
                page=page.number, left=10, top=10, right=300, bottom=200, on_question=True
            ),
            visual_masks=[dict(page=page.number, left=20, top=20, right=100, bottom=70)],
        )
        before = {card.pk: card for card in self.lecture.cards.all()}
        expected = [card for card in before.values() if card.status == "draft"]
        total = sum(card.study_card_count for card in expected)
        token = self.token()
        response = self.client.post(self.url, {"drafts": token}, follow=True)
        self.assertContains(response, f"Kept {len(expected)} drafts ({total} Anki cards)")
        self.assertEqual(response.context["counts"]["draft"], 0)
        self.assertNotContains(response, 'data-open-dialog="keep-drafts"')
        fields = (
            "lecture_id",
            "page_id",
            "fingerprint",
            "note_type",
            "front",
            "back",
            "source_quote",
            "source_crop",
            "occlusion",
            "visual_masks",
            "run_id",
        )
        for card in self.lecture.cards.all():
            original = before[card.pk]
            self.assertEqual(
                [getattr(card, key) for key in fields], [getattr(original, key) for key in fields]
            )
            if original.status == "draft":
                self.assertEqual((card.status, card.version), ("accepted", original.version + 1))
                self.assertGreater(card.anki_modified, original.anki_modified)
                revision = card.revisions.get(version=original.version)
                self.assertEqual((revision.front, revision.status), (original.front, "draft"))
            else:
                self.assertEqual(
                    (card.status, card.version, card.anki_modified),
                    (original.status, original.version, original.anki_modified),
                )
        revisions = CardRevision.objects.count()
        self.assertEqual(self.client.post(self.url, {"drafts": token}).status_code, 400)
        self.assertEqual(CardRevision.objects.count(), revisions)

    def test_new_drafts_after_confirmation_snapshot_are_not_kept(self):
        token = self.token()
        page = self.lecture.pages.first()
        add_drafts(self.lecture, [Draft(page, "A later draft?", "A later answer.", "")])
        response = self.client.post(self.url, {"drafts": token}, follow=True)
        self.assertContains(response, "Kept 5 drafts (5 Anki cards)")
        self.assertEqual(self.lecture.cards.filter(status="draft").get().front, "A later draft?")

    def test_stale_confirmation_does_not_overwrite_edits_or_other_decisions(self):
        for status in ("draft", "rejected"):
            with self.subTest(status=status):
                token = self.token()
                card = self.lecture.cards.filter(status="draft").first()
                update_card(
                    card.pk, card.version, "A newer edit", card.back, card.source_quote, status
                )
                revisions = CardRevision.objects.count()
                response = self.client.post(self.url, {"drafts": token})
                self.assertContains(response, "Nothing was kept", status_code=400)
                card.refresh_from_db()
                self.assertEqual((card.front, card.status), ("A newer edit", status))
                self.assertFalse(self.lecture.cards.filter(status="accepted").exists())
                self.assertEqual(CardRevision.objects.count(), revisions)

    def test_invalid_source_rolls_back_entire_batch(self):
        token = self.token()
        card = self.lecture.cards.last()
        Card.objects.filter(pk=card.pk).update(source_quote="Absent supporting excerpt")
        response = self.client.post(self.url, {"drafts": token})
        self.assertContains(response, "source excerpt is not present", status_code=400)
        self.assertEqual(self.lecture.cards.filter(status="draft", version=1).count(), 5)
        self.assertEqual(CardRevision.objects.count(), 0)

    def test_confirmation_requires_csrf_post_and_signed_lecture_specific_snapshot(self):
        token = self.token()
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(
            Client(enforce_csrf_checks=True).post(self.url, {"drafts": token}).status_code, 403
        )
        other = Lecture.objects.create(
            title="Another lecture",
            sha256="f" * 64,
            original_name="other.pdf",
            original_file="other.pdf",
        )
        self.assertEqual(
            self.client.post(
                reverse("keep_all_drafts", args=[other.pk]), {"drafts": token}
            ).status_code,
            400,
        )
        for invalid in ("", token + "tampered"):
            self.assertEqual(self.client.post(self.url, {"drafts": invalid}).status_code, 400)
        snapshot = signing.loads(token, salt="keep-drafts")
        for versions in ({}, {str(other.pk): 1}, {str(self.lecture.cards.first().pk): True}):
            with self.assertRaises(WorkflowError):
                keep_drafts(self.lecture, versions)
        self.assertEqual(len(snapshot["versions"]), 5)
        self.assertEqual(self.lecture.cards.filter(status="draft").count(), 5)

    def test_deleted_draft_invalidates_the_whole_snapshot(self):
        token = self.token()
        self.lecture.cards.first().delete()
        response = self.client.post(self.url, {"drafts": token})
        self.assertContains(response, "Nothing was kept", status_code=400)
        self.assertEqual(self.lecture.cards.filter(status="draft", version=1).count(), 4)
        self.assertEqual(CardRevision.objects.count(), 0)
