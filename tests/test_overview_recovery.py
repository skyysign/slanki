import copy
import json
import uuid
from unittest.mock import patch

from django.urls import reverse

from converter.models import Card, GenerationRun, Page
from converter.services.files import GenerationOutputError, WorkflowError
from converter.services.generation import generation_request, perform_run
from converter.services.lecture_context import (
    checked_context,
    new_context,
    overview_sources,
    resolve_overview,
)

from .test_visual_rundown import rundown_output, visual_output
from .test_workflow import WorkflowFixture


def referenced_topic(source_id):
    return {
        "title": "Synthetic concept",
        "summary": "A source-linked explanation.",
        "priority": "core",
        "source_id": source_id,
    }


def overview_output(pages, sections=None):
    _, evidence = overview_sources(pages, sections)
    return {"topics": [referenced_topic(next(iter(evidence)))]}


class OverviewRecoveryTests(WorkflowFixture):
    def run_record(self, **kwargs):
        return GenerationRun.objects.create(
            lecture=self.lecture,
            page_numbers=[1, 2, 3],
            context_enabled=True,
            card_limit=3,
            **kwargs,
        )

    def test_source_ids_keep_exact_extraction_including_symbols_without_guessing(self):
        page = copy.copy(self.lecture.pages.first())
        page.number = 39
        page.text = (
            "Default premium\ufffd Additional yield. P\u2080 = C/(1+r).\n"
            "Two columns: Moody's  Rating\n" + "Native extraction. " * 45
        )
        material, evidence = overview_sources([page])
        self.assertGreater(len(evidence), 1)
        self.assertEqual(material[0]["page"], 39)
        for source_id, source in evidence.items():
            self.assertIn(source["source_quote"], page.text)
            self.assertLessEqual(len(source["source_quote"]), 240)
            resolved = resolve_overview({"topics": [referenced_topic(source_id)]}, {39: page})[0]
            self.assertEqual(
                (resolved["page"], resolved["source_quote"]), (39, source["source_quote"])
            )
            self.assertNotIn("source_id", resolved)
        for identifier in ("p38:e1", "p39:e999", {}, None):
            with self.subTest(identifier=identifier), self.assertRaises(WorkflowError):
                resolve_overview({"topics": [referenced_topic(identifier)]}, {39: page})
        # Do not accept paraphrases or silently move evidence to a different page.
        legacy = {
            "title": "Topic",
            "summary": "Summary",
            "priority": "core",
            "page": 39,
            "source_quote": "A paraphrase of default risk",
        }
        with self.assertRaisesMessage(WorkflowError, "not present on page 39"):
            resolve_overview({"topics": [legacy]}, {39: page})

    def test_63_page_visual_run_checkpoints_overview_before_processing_images(self):
        page = self.lecture.pages.first()
        self.lecture.pages.filter(number=4).update(warning="", text="A readable synthetic slide.")
        for number in range(5, 64):
            Page.objects.create(
                lecture=self.lecture,
                number=number,
                text=f"Synthetic source page {number}. \ufffd Formula P = C / r.",
                image=page.image,
                width=page.width,
                height=page.height,
            )
        run = self.run_record(visual_enabled=True, reasoning_effort="high")
        run.page_numbers, run.card_limit = list(range(1, 64)), 32
        run.save()
        calls = []

        def generate(pages, cancelled, **kwargs):
            task = kwargs.get("task", "cards")
            calls.append((task, [p.number for p in pages]))
            self.assertEqual(kwargs["reasoning_effort"], "high")
            if task == "overview":
                if kwargs.get("sections") is not None:
                    _, evidence = overview_sources([], kwargs["sections"])
                    return {"topics": [referenced_topic(key) for key in evidence]}
                _, evidence = overview_sources(pages)
                key = next(
                    (key for key in evidence if key.startswith("p39:")), next(iter(evidence))
                )
                return {"topics": [referenced_topic(key)]}
            self.assertEqual(len(GenerationRun.objects.get(pk=run.pk).context_data["sections"]), 6)
            return {"cards": []}

        with patch("converter.services.generation.codex_generate", side_effect=generate):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed", run.error)
        sections = run.context_data["sections"]
        self.assertEqual([len(s["pages"]) for s in sections], [12, 12, 12, 12, 12, 3])
        self.assertTrue(any(topic["page"] == 39 for topic in run.context_data["outline"]))
        self.assertEqual([task for task, _ in calls[:7]], ["overview"] * 7)
        self.assertEqual(run.image_completed_pages, list(range(1, 64)))
        self.assertEqual(run.completed_pages, list(range(1, 64)))

    def test_invalid_overview_is_corrected_automatically_with_visible_progress(self):
        run = self.run_record()
        calls = []

        def generate(pages, cancelled, **kwargs):
            calls.append(kwargs)
            if kwargs.get("task") == "overview":
                if len(calls) == 1:
                    return {"topics": [referenced_topic("p999:e1")]}
                self.assertIn("source_id", kwargs["validation_feedback"])
                status = self.client.get(reverse("run_status", args=[run.pk])).json()
                self.assertEqual(status["status"], "running")
                self.assertIn("automatically (attempt 2 of 3)", status["error"])
                return overview_output(pages)
            return {"cards": []}

        with patch("converter.services.generation.codex_generate", side_effect=generate):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual((run.status, run.error), ("completed", ""))
        self.assertEqual(len(calls), 3)
        self.assertNotIn("validation_feedback", calls[-1])
        self.assertEqual(len(run.context_data["sections"]), 1)

    def test_invalid_response_has_fixed_retry_limit_and_preserves_existing_cards(self):
        self.accepted_card()
        before = list(Card.objects.values())
        run = self.run_record()
        with patch(
            "converter.services.generation.codex_generate",
            return_value={"topics": [referenced_topic("missing")]},
        ) as generate:
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(generate.call_count, 3)
        self.assertEqual(run.status, "failed")
        self.assertIn("after 3 attempts", run.error)
        self.assertEqual(run.context_data["sections"], [])
        self.assertEqual(list(Card.objects.values()), before)
        self.assertContains(
            self.client.get(self.lecture.get_absolute_url()),
            "Lecture overview: 0 of 3 readable pages saved",
        )

    def test_retryable_json_output_is_distinct_from_allowance_and_connection_failures(self):
        run = self.run_record()
        pages = list(self.lecture.pages.filter(warning=""))
        with patch(
            "converter.services.generation.codex_generate",
            side_effect=[
                GenerationOutputError("Invalid JSON"),
                overview_output(pages),
                {"cards": []},
            ],
        ) as generate:
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(generate.call_count, 3)
        for error in (
            WorkflowError("Usage exhausted"),
            WorkflowError("Sign in required"),
            WorkflowError("Timed out"),
        ):
            run = self.run_record()
            with patch(
                "converter.services.generation.codex_generate", side_effect=error
            ) as generate:
                perform_run(run.pk)
            self.assertEqual(generate.call_count, 1)

    def test_retry_cancel_or_worker_replacement_cannot_publish_or_retry_again(self):
        for replacement in (False, True):
            run = self.run_record()
            calls = []

            def generate(pages, cancelled, **kwargs):
                calls.append(kwargs)
                if len(calls) == 2:
                    changes = (
                        {"status": "failed", "worker_token": uuid.uuid4()}
                        if replacement
                        else {"status": "cancelled"}
                    )
                    GenerationRun.objects.filter(pk=run.pk).update(**changes)
                return {"topics": [referenced_topic("missing")]}

            with patch("converter.services.generation.codex_generate", side_effect=generate):
                perform_run(run.pk)
            run.refresh_from_db()
            self.assertEqual(len(calls), 2)
            self.assertEqual(run.context_data["sections"], [])
            self.assertEqual(run.status, "failed" if replacement else "cancelled")

    def test_legacy_section_partitions_resume_and_merge_retries_do_not_reread_sources(self):
        pages = list(self.lecture.pages.all())
        original = resolve_overview(overview_output(pages[:2]), {p.number: p for p in pages[:2]})
        run = self.run_record()
        run.context_data = new_context(self.lecture, pages)
        run.context_data["sections"] = [{"pages": [1, 2], "topics": original}]
        saved = copy.deepcopy(run.context_data["sections"][0])
        run.save()
        calls, merges = [], []

        def generate(source, cancelled, **kwargs):
            calls.append([p.number for p in source])
            if kwargs.get("task") == "overview":
                if "sections" in kwargs:
                    merges.append(kwargs)
                    if len(merges) == 1:
                        # Even an exact source quote cannot be newly introduced in the merge.
                        return {
                            "topics": [
                                {
                                    "title": "Topic",
                                    "summary": "Summary",
                                    "priority": "core",
                                    "page": 1,
                                    "source_quote": pages[0].text[-20:],
                                }
                            ]
                        }
                    return overview_output([], kwargs["sections"])
                return overview_output(source)
            return {"cards": []}

        with (
            patch("converter.services.lecture_context.SECTION_PAGES", 1),
            patch("converter.services.generation.codex_generate", side_effect=generate),
        ):
            checked_context(run.context_data, True, self.lecture, pages)
            perform_run(run.pk)
            run.refresh_from_db()
            checked_context(run.context_data, True, self.lecture, pages)
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(calls, [[3], [], [], [1, 2, 3]])
        self.assertEqual(run.context_data["sections"][0], saved)
        for bad_pages in ([1, 3], [2, 3], [1, 1]):
            bad = copy.deepcopy(run.context_data)
            bad["sections"][0]["pages"] = bad_pages
            with self.assertRaises(WorkflowError):
                checked_context(bad, True, self.lecture, pages)

    def test_visual_and_rundown_validation_retry_only_the_current_request(self):
        for task in ("visual", "rundown"):
            run = GenerationRun.objects.create(
                lecture=self.lecture,
                page_numbers=[1],
                card_limit=1,
                visual_enabled=task == "visual",
                text_enabled=task == "rundown",
                purpose="rundown" if task == "rundown" else "cards",
            )
            calls = []

            def generate(pages, cancelled, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    return {}
                self.assertTrue(kwargs.get("validation_feedback"))
                return visual_output(pages[0]) if task == "visual" else rundown_output(pages)

            with patch("converter.services.generation.codex_generate", side_effect=generate):
                perform_run(run.pk)
            run.refresh_from_db()
            self.assertEqual(run.status, "completed", run.error)
            self.assertEqual(len(calls), 2)

    def test_feedback_is_data_in_the_prompt_and_preserves_parseable_source_json(self):
        page = self.lecture.pages.first()
        prompt, schema = generation_request(
            [page], task="overview", validation_feedback='Bad "source_id"; retry'
        )
        self.assertIn(json.dumps({"error": 'Bad "source_id"; retry'}), prompt)
        sources = json.loads(prompt.split("UNTRUSTED SOURCE DATA (JSON):\n")[1])
        self.assertEqual(sources[0]["page"], page.number)
        self.assertEqual(
            schema["properties"]["topics"]["items"]["required"],
            ["title", "summary", "priority", "source_id"],
        )
