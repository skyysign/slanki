"""Exercise the local UI with an isolated database and headless Chrome.

No provider calls, no access to the user's Anki profile, no edits to real lectures.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data" / "screenshots"
OUTPUT.mkdir(parents=True, exist_ok=True)


def main():
    with TemporaryDirectory(dir=ROOT / "data" / "work") as directory:
        environment = {
            **os.environ,
            "SLIDES_DATA_DIR": directory,
            # Connection UI checks must not inspect or change a real Codex sign-in.
            "SLIDES_CODEX_BINARY": str(Path(directory) / "missing-codex.exe"),
        }
        subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        with (Path(directory) / "server.log").open("wb") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "manage.py",
                    "runserver",
                    f"127.0.0.1:{port}",
                    "--noreload",
                    "--insecure",
                ],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                for _ in range(60):
                    try:
                        urllib.request.urlopen(url, timeout=1).close()
                        break
                    except OSError:
                        if process.poll() is not None:
                            raise RuntimeError("Local test server stopped unexpectedly")
                        time.sleep(0.25)
                else:
                    raise RuntimeError("Local test server did not start")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                    page = browser.new_page(
                        viewport={"width": 1512, "height": 1100}, device_scale_factor=1
                    )
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(url)
                    page.get_by_role("heading", name="Add a lecture").wait_for()
                    page.screenshot(path=str(OUTPUT / "home-desktop.png"), full_page=True)
                    assert page.title() == "Recalloom"
                    page.get_by_role("link", name="Codex connection", exact=True).click()
                    page.get_by_role("link", name="Open the Codex setup guide").wait_for()
                    assert (
                        page.locator("[data-connection-state]").get_attribute(
                            "data-connection-state"
                        )
                        == "missing"
                    )
                    page.screenshot(path=str(OUTPUT / "connection-desktop.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.screenshot(path=str(OUTPUT / "connection-mobile.png"), full_page=True)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.get_by_role("link", name="Your lectures", exact=False).click()
                    page.set_viewport_size({"width": 1512, "height": 1100})
                    page.get_by_label("Title", exact=True).fill("Memory & learning · sample")
                    page.locator("#id_pdf").set_input_files(
                        str(ROOT / "tests/fixtures/synthetic/lecture.pdf")
                    )
                    page.get_by_role("button", name="Open lecture").click()
                    page.get_by_role("heading", name="Memory & learning · sample").wait_for()
                    page.get_by_label("Maximum new cards").fill("2")
                    reasoning = page.get_by_label("Reasoning level", exact=True)
                    assert reasoning.input_value() == "low"
                    assert reasoning.locator("option").all_text_contents() == [
                        "Codex default",
                        "Low",
                        "Medium",
                        "High",
                        "Extra high",
                        "Max",
                    ]
                    page.get_by_label("Learning focus", exact=True).select_option("understanding")
                    page.get_by_label("Card format", exact=True).select_option("mixed")
                    reasoning.select_option("xhigh")
                    assert reasoning.input_value() == "xhigh"
                    page.screenshot(
                        path=str(OUTPUT / "generation-settings-desktop.png"), full_page=True
                    )
                    with page.expect_download() as downloaded_prompt:
                        page.get_by_role("button", name="Download prompt").click()
                    assert "LECTURE PAGE DATA" in Path(downloaded_prompt.value.path()).read_text(
                        encoding="utf-8"
                    )
                    assert "at most 2 cards TOTAL" in Path(
                        downloaded_prompt.value.path()
                    ).read_text(encoding="utf-8")
                    downloaded_text = Path(downloaded_prompt.value.path()).read_text(
                        encoding="utf-8"
                    )
                    assert "LEARNING FOCUS: Understanding" in downloaded_text
                    assert "CARD FORMAT: mixed" in downloaded_text
                    page.locator("#cards-file").set_input_files(
                        str(ROOT / "tests/fixtures/synthetic/cards.json")
                    )
                    page.get_by_role("button", name="Import drafts").click()
                    page.get_by_text("Last batch complete: 5 new drafts.", exact=False).wait_for()
                    assert page.locator("[data-source-image]").evaluate(
                        "img => img.complete && img.naturalWidth > 0"
                    )
                    page.locator("[data-card-form]").get_by_label("Question", exact=True).fill(
                        "What is retrieval practice, in your own words?"
                    )
                    page.get_by_role("button", name="Accept & next").click()
                    page.get_by_text("Card saved. Your changes stay with this lecture.").wait_for()
                    with page.expect_download() as download:
                        page.get_by_role("link", name="Export 1 to Anki").click()
                    assert download.value.suggested_filename.endswith(".apkg")
                    assert Path(download.value.path()).stat().st_size > 1000
                    with page.expect_download() as download:
                        page.get_by_role("link", name="Save backup").click()
                    assert download.value.suggested_filename.endswith(".zip")
                    page.screenshot(path=str(OUTPUT / "lecture-desktop.png"), full_page=True)
                    page.locator("[data-page-select]").select_option(label="Page 2")
                    page.locator("[data-source-image]").evaluate("image => image.decode()")
                    assert (
                        page.locator("[data-source-image]").get_attribute("alt")
                        == "Source slide, page 2"
                    )
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.screenshot(path=str(OUTPUT / "lecture-mobile.png"), full_page=True)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.get_by_role("link", name="All lectures").click()
                    page.screenshot(path=str(OUTPUT / "home-mobile.png"), full_page=True)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.get_by_role("button", name="Try a sample lecture").click()
                    page.get_by_role("heading", name="Memory & learning · sample").wait_for()
                    assert (
                        page.locator(".card-list")
                        .get_by_text("What is retrieval practice, in your own words?", exact=True)
                        .count()
                        == 1
                    )
                    # Seed a failed synthetic run; checking recovery must not call a provider.
                    subprocess.run(
                        [
                            sys.executable,
                            "manage.py",
                            "shell",
                            "-c",
                            """
from converter.models import GenerationRun, Lecture
from converter.services.cards import validate_generated_batch
from converter.services.cards import add_drafts
lecture = Lecture.objects.first()
add_drafts(lecture, [(lecture.pages.first(), 'How long is the exam?', '90 minutes.', '')])
_, issues = validate_generated_batch({'cards': [{
    'front': '<script>Unverified question</script>', 'back': 'Unverified answer',
    'page': 1, 'source_quote': 'An invented excerpt'
}]}, {p.number: p for p in lecture.pages.filter(number=1)})
GenerationRun.objects.create(lecture=lecture, status='failed', page_numbers=[1, 2, 3],
    completed_pages=[1], issues=issues, cards_added=5, error='Synthetic interruption')
""",
                        ],
                        cwd=ROOT,
                        env=environment,
                        check=True,
                        capture_output=True,
                    )
                    page.reload()
                    page.get_by_role(
                        "button", name="Set aside 1 logistics draft", exact=True
                    ).click()
                    page.get_by_text("1 course logistics draft set aside.", exact=False).wait_for()
                    assert (
                        page.locator(".card-list")
                        .get_by_text("How long is the exam?", exact=True)
                        .count()
                        == 0
                    )
                    page.get_by_role("link", name="Set aside", exact=True).click()
                    page.locator(".card-list").get_by_text(
                        "How long is the exam?", exact=True
                    ).wait_for()
                    page.get_by_role("link", name="Drafts", exact=True).click()
                    assert page.get_by_role("button", name="Resume 2 remaining pages").is_enabled()
                    page.get_by_text("1 skipped draft · review details", exact=True).click()
                    page.get_by_role("button", name="View source page 1").click()
                    page.locator("[data-source-image]").evaluate("image => image.decode()")
                    assert page.locator("[data-page-select]").input_value().endswith("/image/")
                    assert (
                        page.locator("[data-source-image]").get_attribute("alt")
                        == "Source slide, page 1"
                    )
                    assert page.locator(".generation-issues script").count() == 0
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(
                        path=str(OUTPUT / "generation-recovery-mobile.png"), full_page=True
                    )
                    page.set_viewport_size({"width": 1512, "height": 1100})
                    page.screenshot(
                        path=str(OUTPUT / "generation-recovery-desktop.png"), full_page=True
                    )
                    # Create, preview, accept and re-edit a cloze without any provider call.
                    generation = page.locator("details.generation-panel").filter(
                        has=page.get_by_text("＋ Create cards", exact=True)
                    )
                    if generation.get_attribute("open") is None:
                        generation.locator("summary").first.click()
                    page.get_by_text("Write a card yourself", exact=True).click()
                    manual = page.locator(".manual-card form")
                    manual.get_by_label("Note format", exact=True).select_option("cloze")
                    front = manual.get_by_label("Cloze text", exact=True)
                    front.fill("Retrieval practice means trying to recall information from memory.")
                    front.evaluate(
                        "el => { const start = el.value.indexOf('recall'); el.setSelectionRange(start, start + 6); }"
                    )
                    manual.get_by_role("button", name="Hide selected text", exact=True).click()
                    assert "{{c1::recall}}" in front.input_value()
                    manual.get_by_role("button", name="Preview cards", exact=True).click()
                    manual.get_by_text("1 Anki review card from this note.", exact=False).wait_for()
                    cloze_text = "Retrieval practice means trying to {{c1::recall}} information from {{c2::memory::where?}}."
                    front.fill(cloze_text)
                    manual.get_by_role("button", name="Preview cards", exact=True).click()
                    manual.get_by_text(
                        "2 Anki review cards from this note.", exact=False
                    ).wait_for()
                    assert manual.locator(".preview-card").count() == 2
                    assert "recall" not in manual.locator(".preview-question").first.inner_text()
                    manual.get_by_role("button", name="Add draft", exact=True).click()
                    page.locator(".card-item").filter(has_text="{{c1::recall}}").click()
                    editor = page.locator("[data-card-form]")
                    assert editor.get_by_label("Cloze text", exact=True).input_value() == cloze_text
                    assert editor.locator(".preview-card").count() == 2
                    editor.get_by_label("Extra explanation (optional)", exact=True).fill(
                        "My checked explanation."
                    )
                    editor.get_by_role("button", name="Preview current text", exact=True).click()
                    editor.get_by_text(
                        "Preview only; edits have not been saved.", exact=False
                    ).wait_for()
                    editor.locator(".preview-card summary").first.click()
                    assert (
                        "My checked explanation."
                        in editor.locator(".preview-answer").first.inner_text()
                    )
                    page.screenshot(path=str(OUTPUT / "cloze-editor-desktop.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=str(OUTPUT / "cloze-editor-mobile.png"), full_page=True)
                    editor.get_by_role("button", name="Accept & next", exact=False).click()
                    page.get_by_role("link", name="Preview export", exact=True).click()
                    page.get_by_role("heading", name="Export preview", exact=True).wait_for()
                    page.get_by_text("3 review cards from 2 accepted notes", exact=False).wait_for()
                    assert page.locator(".preview-card").count() == 3
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=str(OUTPUT / "cloze-export-mobile.png"), full_page=True)
                    page.set_viewport_size({"width": 1512, "height": 1100})
                    page.screenshot(path=str(OUTPUT / "cloze-export-desktop.png"), full_page=True)
                    with page.expect_download() as cloze_export:
                        page.get_by_role("link", name="Export 3 to Anki", exact=False).click()
                    assert Path(cloze_export.value.path()).stat().st_size > 1000
                    assert not errors, errors
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=10)
    print(
        "Browser checks passed: sample import, source image, edit/accept, export, backup, page switch, generation recovery, learning focus/format, cloze selection and unsaved preview, mixed deck preview/export, desktop/mobile layouts, no JavaScript errors."
    )
    print(f"Screenshots: {OUTPUT}")


if __name__ == "__main__":
    main()
