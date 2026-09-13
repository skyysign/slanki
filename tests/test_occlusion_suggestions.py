import copy
import json
import threading
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import Client
from django.urls import reverse

from converter.models import Card, GenerationRun
from converter.services.acp import generate_acp
from converter.services.deletion import delete_lecture
from converter.services.files import WorkflowError
from converter.services.generation import claude_generate, codex_generate
from converter.services.lecture_context import new_context
from converter.services.occlusion_suggestions import (
    SUGGESTION_SCHEMA,
    SuggestionJobs,
    slide_image,
    validate_suggestions,
)

from .test_workflow import WorkflowFixture


class OcclusionSuggestionTests(WorkflowFixture):
    def setUp(self):
        self.page = self.lecture.pages.get(number=4)
        self.item = {
            "label": "Visible label",
            "reason": "Recall the labelled part.",
            "left": 20,
            "top": 30,
            "right": 200,
            "bottom": 100,
        }
        self.output = {"suggestions": [self.item]}
        self.manager = SuggestionJobs()
        self.addCleanup(self.finish_jobs)

    def finish_jobs(self):
        self.manager.shutdown()

    def test_validation_is_atomic_bounded_and_deduplicates_exact_regions(self):
        self.assertEqual(validate_suggestions({"suggestions": []}, self.page), [])
        checked = validate_suggestions({"suggestions": [self.item, self.item]}, self.page)
        self.assertEqual(len(checked), 1)
        self.assertEqual(checked[0]["mask"]["page"], 4)
        bad = [None, {"cards": []}, {"suggestions": "wrong"}, {"suggestions": [self.item] * 7}]
        for change in (
            {"left": True},
            {"right": self.page.width + 1},
            {"top": -1},
            {"right": 21},
            {"bottom": 30},
            {"left": "20"},
            {"label": ""},
            {"reason": "x" * 301},
            {"path": "other.png"},
            {"page": 99},
        ):
            bad.append({"suggestions": [self.item, {**self.item, **change}]})
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(WorkflowError):
                validate_suggestions(payload, self.page)
        self.assertFalse(Card.objects.exists())

    def test_codex_attaches_only_the_selected_png_and_keeps_text_in_stdin(self):
        expected = slide_image(self.page)
        outline = [{"title": "Untrusted overview", "summary": "Only planning context"}]
        staged = []

        def process(command, **kwargs):
            self.assertEqual(command.count("--image"), 1)
            image = Path(command[command.index("--image") + 1])
            staged.append(image)
            self.assertEqual(image.parent, Path(kwargs["cwd"]))
            self.assertEqual(image.read_bytes(), expected)
            self.assertNotIn(str(self.lecture.pk), " ".join(command))
            text = kwargs["stdin"].read().decode("utf-8")
            data = json.loads(text.split("UNTRUSTED SLIDE DATA (JSON):\n")[1])
            self.assertEqual(
                (data["page"], data["width"], data["height"]),
                (4, self.page.width, self.page.height),
            )
            self.assertEqual(data["overview"], outline)
            self.assertEqual(
                json.loads(Path(command[command.index("--output-schema") + 1]).read_text()),
                SUGGESTION_SCHEMA,
            )
            for flag in (
                "--ignore-user-config",
                "--ephemeral",
                "shell_tool",
                "unified_exec",
                "multi_agent",
            ):
                self.assertIn(flag, command)
            Path(command[command.index("--output-last-message") + 1]).write_text(
                json.dumps(self.output)
            )
            return Mock(returncode=0, poll=Mock(return_value=0))

        with (
            patch("converter.services.generation.codex_executable", return_value="codex.exe"),
            patch("converter.services.generation.subprocess.Popen", side_effect=process),
        ):
            self.assertEqual(
                codex_generate([self.page], task="occlusion", lecture_context=outline), self.output
            )
        self.assertFalse(staged[0].exists())
        for provider in ("claude", "gemini", "kimi"):
            with (
                self.subTest(provider=provider),
                patch("subprocess.Popen") as launch,
                self.assertRaises(WorkflowError),
            ):
                if provider == "claude":
                    claude_generate([self.page], task="occlusion")
                else:
                    generate_acp(provider, [self.page], task="occlusion")
            launch.assert_not_called()
        wrong = copy.copy(self.page)
        wrong.width += 1
        with self.assertRaises(WorkflowError):
            slide_image(wrong)

    def test_requests_are_deduplicated_cancellable_and_late_results_cannot_publish(self):
        entered, released = threading.Event(), threading.Event()

        def blocked(pages, cancelled, **kwargs):
            entered.set()
            released.wait(timeout=2)
            self.assertTrue(cancelled())
            return self.output

        with patch("converter.services.generation.codex_generate", side_effect=blocked) as generate:
            job = self.manager.start(self.page, "", "low")
            self.assertTrue(entered.wait(timeout=1))
            again = self.manager.start(self.page, "", "high")
            self.assertEqual(job["id"], again["id"])
            self.assertEqual(again["reasoning_effort"], "low")
            with self.assertRaises(WorkflowError):
                self.manager.start(self.lecture.pages.get(number=1), "", "low")
            with self.assertRaises(WorkflowError):
                self.manager.get(job["id"], uuid.uuid4())
            self.manager.cancel(job["id"], uuid.uuid4())
            self.assertEqual(self.manager.get(job["id"], self.lecture.pk)["status"], "running")
            self.manager.cancel(job["id"], self.lecture.pk)
            released.set()
            self.manager.jobs[job["id"]].thread.join(timeout=2)
            self.assertEqual(generate.call_count, 1)
        state = self.manager.get(job["id"], self.lecture.pk)
        self.assertEqual((state["status"], state["suggestions"]), ("cancelled", []))
        self.assertFalse(Card.objects.exists())

    def test_success_failure_and_expiration_preserve_existing_notes(self):
        accepted = self.accepted_card()
        before = (accepted.pk, accepted.front, accepted.back, accepted.version)
        for payload in (
            self.output,
            {"suggestions": []},
            {"suggestions": [{**self.item, "left": -1}]},
            RuntimeError("private detail"),
        ):
            with patch("converter.services.generation.codex_generate", side_effect=[payload]):
                result = self.manager.start(self.page, "", "low")
                job = self.manager.jobs[result["id"]]
                job.thread.join(timeout=2)
            state = self.manager.get(job.id, self.lecture.pk)
            self.assertNotIn("private detail", state["error"])
            self.assertEqual(
                state["status"],
                "completed" if payload in (self.output, {"suggestions": []}) else "failed",
            )
        accepted.refresh_from_db()
        self.assertEqual((accepted.pk, accepted.front, accepted.back, accepted.version), before)
        job.created -= 901
        with self.assertRaises(WorkflowError):
            self.manager.get(job.id, self.lecture.pk)

    def test_routes_require_consent_csrf_and_lecture_scoped_overview(self):
        url = reverse("start_occlusion_suggestions", args=[self.lecture.pk])
        values = {"page": 4, "provider": "codex", "reasoning_effort": "low"}
        pages = list(self.lecture.pages.all())
        context = new_context(self.lecture, pages)
        context.update(sections=[{"pages": context["pages"], "topics": []}], outline=[])
        overview = GenerationRun.objects.create(
            lecture=self.lecture,
            status="completed",
            page_numbers=[1],
            context_enabled=True,
            context_data=context,
        )
        with (
            patch(
                "converter.views.suggestion_jobs.start",
                return_value={"id": str(uuid.uuid4()), "status": "running"},
            ) as start,
            patch("converter.views.checked_model_settings"),
            patch(
                "converter.services.connection.login_status", return_value={"state": "connected"}
            ) as auth,
        ):
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(self.client.post(url, values).status_code, 400)
            auth.assert_not_called()
            self.assertEqual(
                Client(enforce_csrf_checks=True)
                .post(url, {**values, "consent": "yes"})
                .status_code,
                403,
            )
            for change in ({"provider": "claude"}, {"page": "bad"}, {"overview": "bad"}):
                self.assertEqual(
                    self.client.post(url, {**values, "consent": "yes", **change}).status_code, 400
                )
            start.assert_not_called()
            self.assertEqual(
                self.client.post(
                    url, {**values, "consent": "yes", "overview": str(uuid.uuid4())}
                ).status_code,
                404,
            )
            response = self.client.post(
                url, {**values, "consent": "yes", "overview": str(overview.pk)}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(start.call_args.args[0], self.page)
            self.assertEqual(start.call_args.args[3], [])
            self.client.post(url, {**values, "consent": "yes"})
            self.assertIsNone(start.call_args.args[3])
        self.assertFalse(Card.objects.exists())

    def test_set_deletion_cancels_only_after_commit(self):
        with patch(
            "converter.services.occlusion_suggestions.suggestion_jobs.cancel_lecture"
        ) as cancel:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                delete_lecture(self.lecture.pk)
                cancel.assert_not_called()
            # Avoid deleting fixture media; execute only the cancellation callback.
            callbacks[-1]()
            cancel.assert_called_once_with(self.lecture.pk)
