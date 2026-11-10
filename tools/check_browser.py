"""Exercise the local UI with an isolated database and headless Chrome.

No provider calls, no access to the user's Anki profile, no edits to real lectures.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data" / "screenshots"
OUTPUT.mkdir(parents=True, exist_ok=True)


def open_creation(page):
    dialog = page.locator("#create-cards")
    if not dialog.is_visible():
        page.locator('[data-open-dialog="create-cards"]').first.click()
    for selector in (".scope-selector", ".advanced-generation", ".ai-preferences"):
        details = dialog.locator(selector)
        if details.get_attribute("open") is None:
            details.locator("summary").first.click()
    return dialog


def open_manual(page):
    if page.locator("#create-cards").is_visible():
        page.locator("#create-cards [data-close-dialog]").click()
    button = page.locator('[data-open-dialog="manual-card"]')
    if not button.is_visible():
        page.locator("[data-show-source]").first.click()
    button.click()
    return page.locator("#manual-card form")


def open_queue(page):
    details = page.locator(".card-queue")
    if details.count() and details.get_attribute("open") is None:
        details.locator("summary").first.click()


def edit_current(page, tool=None):
    editor = page.locator("[data-card-form]")
    fields = editor.locator("[data-edit-fields]")
    if fields.count() and fields.get_attribute("open") is None:
        fields.locator("summary").first.click()
    if tool:
        details = editor.locator(tool)
        if details.get_attribute("open") is None:
            details.locator("summary").first.click()
    return editor


def preview_current(editor):
    editor.get_by_role("button", name="Preview current card", exact=True).click()
    expect(editor.locator("[data-preview-output]")).to_have_attribute("aria-busy", "false")


def lecture_action(page, label):
    menu = page.locator(".header-actions>.workspace-menu")
    if menu.get_attribute("open") is None:
        menu.locator("summary").click()
    page.get_by_role("link", name=label, exact=True).click()


def open_sample(page):
    sample = page.get_by_role("button", name="Try a sample lecture", exact=False)
    if not sample.is_visible():
        page.locator('[data-open-dialog="add-lecture"]').click()
        sample = page.locator("#add-lecture").get_by_role(
            "button", name="Try a sample lecture", exact=False
        )
    sample.click()


def check_review_shortcuts(page):
    # Undo a keep, edit again, then use keyboard decisions without losing identities.
    page.keyboard.press("z")
    page.get_by_text("Last change undone.", exact=False).wait_for()
    editor = edit_current(page)
    front = editor.get_by_label("Question", exact=True)
    front.fill("What is retrieval practice, in your own words?")
    page.get_by_role("heading", name="Memory & learning", exact=False).click()
    page.keyboard.press("a")
    page.get_by_text("Card saved.", exact=False).wait_for()
    page.keyboard.press("s")
    page.get_by_text("Card saved.", exact=False).wait_for()
    assert (
        page.get_by_role("navigation", name="Filter cards")
        .get_by_role("link", name="Set aside", exact=False)
        .inner_text()
        .endswith("1")
    )
    page.keyboard.press("z")
    page.get_by_text("Last change undone.", exact=False).wait_for()
    assert (
        page.get_by_role("navigation", name="Filter cards")
        .get_by_role("link", name="Set aside", exact=False)
        .inner_text()
        .endswith("0")
    )
    preferences = page.evaluate("JSON.parse(sessionStorage.getItem('recalloom:ai-preferences:v1'))")
    assert set(preferences) == {"provider", "model", "effort"}
    assert preferences == {"provider": "codex", "model": "synthetic-codex", "effort": "xhigh"}


def check_bulk_review(page):
    page.set_viewport_size({"width": 1512, "height": 1100})
    editor = edit_current(page)
    front = editor.get_by_label("Question", exact=True)
    original = front.input_value()
    front.fill(original + " Edited before keeping all.")
    page.get_by_role("button", name="Keep all drafts", exact=True).click()
    dialog = page.get_by_role("dialog", name="Keep all drafts?", exact=True)
    expect(dialog.get_by_role("button", name="Keep 5 drafts", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("alert")).to_have_text(
        "Save your current edits before keeping all drafts."
    )
    dialog.get_by_role("button", name="Back to review", exact=True).click()
    assert front.input_value() == original + " Edited before keeping all."
    editor.get_by_role("button", name="Set aside", exact=False).click()
    page.get_by_text("Card saved. Your changes stay with this lecture.").wait_for()
    page.get_by_role("button", name="Keep all drafts", exact=True).click()
    expect(dialog.get_by_role("button", name="Keep 4 drafts", exact=True)).to_be_enabled()
    expect(dialog).to_contain_text("4 Anki cards")
    page.screenshot(path=str(OUTPUT / "keep-all-desktop.png"), full_page=True)
    dialog.get_by_role("button", name="Back to review", exact=True).click()
    filters = page.get_by_role("navigation", name="Filter cards")
    assert filters.get_by_role("link", name="To review", exact=False).inner_text().endswith("4")
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Keep all drafts", exact=True).click()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(OUTPUT / "keep-all-mobile.png"), full_page=True)
    dialog.get_by_role("button", name="Keep 4 drafts", exact=True).click()
    page.get_by_role("status").filter(has_text="Kept 4 drafts (4 Anki cards)").wait_for()
    expect(page.get_by_role("button", name="Keep all drafts", exact=True)).to_have_count(0)
    assert filters.get_by_role("link", name="To review", exact=False).inner_text().endswith("0")
    assert filters.get_by_role("link", name="Ready", exact=False).inner_text().endswith("4")
    assert filters.get_by_role("link", name="Set aside", exact=False).inner_text().endswith("1")
    expect(page.get_by_role("link", name="Export to Anki", exact=False)).to_be_visible()


def check_slide_viewer(page, browser, errors):
    url = page.url
    front = page.locator("#id_front").input_value()
    version = page.locator('[data-card-form] [name="version"]').input_value()
    tabs = len(page.context.pages)
    page.locator("[data-source-link]").click()
    viewer = page.get_by_role("dialog", name="Source slide", exact=False)
    image = viewer.locator("[data-slide-image]")
    expect(image).to_be_visible()
    viewport = viewer.locator("[data-slide-viewport]")
    zoom = viewer.locator("[data-slide-zoom]")
    initial_zoom = int(zoom.inner_text().rstrip("%"))
    assert (
        image.bounding_box()["width"] > page.locator("[data-source-image]").bounding_box()["width"]
    )
    viewer.get_by_role("button", name="Actual size", exact=True).click()
    assert zoom.inner_text() == "100%"
    for _ in range(4):
        viewer.get_by_role("button", name="Zoom in", exact=True).click()
    assert int(zoom.inner_text().rstrip("%")) > 200
    box = viewport.bounding_box()
    left = viewport.evaluate("el => el.scrollLeft")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 - 95, box["y"] + box["height"] / 2 - 30, steps=6)
    page.mouse.up()
    assert viewport.evaluate("el => el.scrollLeft") > left
    before_wheel = int(zoom.inner_text().rstrip("%"))
    page.mouse.wheel(0, -180)
    expect(zoom).not_to_have_text(f"{before_wheel}%")
    assert int(zoom.inner_text().rstrip("%")) > before_wheel
    viewer.get_by_role("button", name="Fit", exact=True).click()
    assert abs(int(zoom.inner_text().rstrip("%")) - initial_zoom) <= 1
    viewport.dblclick()
    assert int(zoom.inner_text().rstrip("%")) > initial_zoom
    page.keyboard.press("0")
    assert abs(int(zoom.inner_text().rstrip("%")) - initial_zoom) <= 1
    page.keyboard.press("a")
    assert page.url == url
    assert page.locator('[data-card-form] [name="version"]').input_value() == version
    viewer.get_by_role("button", name="Next slide", exact=True).click()
    expect(viewer.locator("[data-slide-title]")).to_have_text("Source slide · Page 2")
    expect(viewport).to_have_attribute("aria-busy", "false")
    assert (
        page.locator("[data-page-select]").evaluate("el => el.selectedOptions[0].dataset.page")
        == "2"
    )
    page.keyboard.press("ArrowRight")
    expect(viewer.locator("[data-slide-title]")).to_have_text("Source slide · Page 3")
    expect(viewport).to_have_attribute("aria-busy", "false")
    viewer.get_by_role("button", name="Previous slide", exact=True).click()
    expect(viewport).to_have_attribute("aria-busy", "false")
    viewer.get_by_role("button", name="Previous slide", exact=True).click()
    expect(viewport).to_have_attribute("aria-busy", "false")
    expect(viewer.get_by_role("button", name="Previous slide", exact=True)).to_be_disabled()
    page.screenshot(path=str(OUTPUT / "slide-viewer-desktop.png"), full_page=True)
    page.keyboard.press("Escape")
    expect(viewer).not_to_be_visible()
    assert page.url == url and len(page.context.pages) == tabs
    assert page.locator("#id_front").input_value() == front
    assert page.locator("[data-source-link]").evaluate("el => document.activeElement === el")

    # Missing-image errors are recoverable, and never affect note data.
    selected = page.locator("[data-page-select] option:checked")
    original = selected.get_attribute("value")
    png = page.request.get(page.locator("[data-source-link]").evaluate("el => el.href")).body()
    bad_url = "/missing-slide-for-browser-check.png"
    attempts = []

    def serve_image(route):
        attempts.append(True)
        if len(attempts) == 1:
            route.fulfill(status=404, body="Missing")
        else:
            route.fulfill(content_type="image/png", body=png)

    page.route("**/missing-slide-for-browser-check.png", serve_image)
    selected.evaluate("(el, url) => { el.value = url; }", bad_url)
    page.locator("[data-source-link]").evaluate("(el, url) => { el.href = url; }", bad_url)
    page.locator("[data-source-link]").click()
    expect(viewer.get_by_role("alert")).to_contain_text("could not be loaded")
    expect(viewer.get_by_role("button", name="Zoom in", exact=True)).to_be_disabled()
    viewer.get_by_role("button", name="Try again", exact=True).click()
    expect(viewer.locator("[data-slide-image]")).to_be_visible()
    viewer.get_by_role("button", name="Close slide viewer", exact=True).click()
    selected.evaluate("(el, value) => { el.value = value; }", original)
    page.locator("[data-source-link]").evaluate("(el, value) => { el.href = value; }", original)
    page.unroute("**/missing-slide-for-browser-check.png")

    touch_context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    touch_page = touch_context.new_page()
    touch_page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        touch_page.goto(url)
        touch_page.locator(".editor-heading [data-show-source]").click()
        touch_page.locator("[data-source-link]").click()
        touch_viewer = touch_page.locator("[data-slide-viewer]")
        expect(touch_viewer.locator("[data-slide-image]")).to_be_visible()
        touch_zoom = touch_viewer.locator("[data-slide-zoom]")
        start_zoom = int(touch_zoom.inner_text().rstrip("%"))
        touch_box = touch_viewer.locator("[data-slide-viewport]").bounding_box()
        x, y = touch_box["x"] + touch_box["width"] / 2, touch_box["y"] + touch_box["height"] / 2
        cdp = touch_context.new_cdp_session(touch_page)
        cdp.send(
            "Input.dispatchTouchEvent",
            {
                "type": "touchStart",
                "touchPoints": [{"x": x - 35, "y": y, "id": 1}, {"x": x + 35, "y": y, "id": 2}],
            },
        )
        cdp.send(
            "Input.dispatchTouchEvent",
            {
                "type": "touchMove",
                "touchPoints": [{"x": x - 90, "y": y, "id": 1}, {"x": x + 90, "y": y, "id": 2}],
            },
        )
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        expect(touch_zoom).not_to_have_text(f"{start_zoom}%")
        assert int(touch_zoom.inner_text().rstrip("%")) > start_zoom
        assert touch_page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        touch_page.screenshot(path=str(OUTPUT / "slide-viewer-mobile.png"), full_page=True)
        touch_viewer.get_by_role("button", name="Close slide viewer", exact=True).tap()
        expect(touch_viewer).not_to_be_visible()
        assert len(touch_context.pages) == 1
    finally:
        touch_context.close()


def check_mask_manipulation(page, form):
    """Exercise real pointer geometry, cancellation, and history without saving notes."""

    def masks():
        return json.loads(form.locator('[name="masks"]').input_value())

    def drag(locator, dx, dy, *, cancel=False):
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + dx, y + dy, steps=5)
        if cancel:
            page.keyboard.press("Escape")
        page.mouse.up()

    def undo():
        form.get_by_role("button", name="Undo", exact=True).click()

    original = masks()
    region = form.locator('[data-mask-index="1"]')
    drag(region, 24, 18)
    moved = masks()
    assert len(moved) == 2 and moved[0] == original[0]
    assert moved[1]["left"] > original[1]["left"] and moved[1]["top"] > original[1]["top"]
    assert moved[1]["right"] - moved[1]["left"] == original[1]["right"] - original[1]["left"]
    assert moved[1]["bottom"] - moved[1]["top"] == original[1]["bottom"] - original[1]["top"]
    assert int(form.get_by_label("Region left", exact=True).input_value()) == moved[1]["left"]
    undo()
    assert masks() == original
    for edge in ("nw", "n", "ne", "e", "se", "s", "sw", "w"):
        drag(
            form.locator(f'.mask-handle[data-mask-edge="{edge}"]'),
            -8 if "w" in edge else 8 if "e" in edge else 0,
            -8 if "n" in edge else 8 if "s" in edge else 0,
        )
        resized = masks()
        assert len(resized) == 2 and resized[0] == original[0]
        for key, direction in (("left", "w"), ("right", "e"), ("top", "n"), ("bottom", "s")):
            assert (resized[1][key] != original[1][key]) == (direction in edge)
        undo()
        assert masks() == original
    drag(region, -2000, -2000)
    bounded = masks()[1]
    assert bounded["left"] == bounded["top"] == 0
    assert bounded["right"] == original[1]["right"] - original[1]["left"]
    assert bounded["bottom"] == original[1]["bottom"] - original[1]["top"]
    undo()
    drag(form.locator('.mask-handle[data-mask-edge="nw"]'), 2000, 2000)
    tiny = masks()[1]
    assert tiny["right"] - tiny["left"] == tiny["bottom"] - tiny["top"] == 2
    undo()
    drag(region, 30, 20, cancel=True)
    assert masks() == original
    drag(form.locator('.mask-handle[data-mask-edge="se"]'), 20, 20, cancel=True)
    assert masks() == original
    canvas = form.locator("[data-mask-stage]")
    canvas.focus()
    page.keyboard.press("Shift+ArrowRight")
    assert masks()[1]["left"] == original[1]["left"] + 10
    undo()
    # Drawing over an existing region is an explicit mode, then returns to editing.
    form.get_by_role("button", name="Draw new region", exact=True).click()
    drag(region, 22, 18)
    assert len(masks()) == 3
    assert (
        form.get_by_role("button", name="Draw new region", exact=True).get_attribute("aria-pressed")
        == "false"
    )
    undo()
    assert masks() == original
    # Reaching the creation cap must not disable editing existing regions.
    for _ in range(18):
        form.get_by_role("button", name="Add region", exact=True).click()
    assert len(masks()) == 20
    drag(form.locator('[data-mask-index="19"]'), 25, 25)
    assert len(masks()) == 20 and masks()[19]["left"] > 0
    undo()
    for _ in range(18):
        undo()
    assert masks() == original


def check_automatic_correction_progress(page, environment):
    subprocess.run(
        [
            sys.executable,
            "manage.py",
            "shell",
            "-c",
            """
from converter.models import GenerationRun, Lecture
from converter.services.lecture_context import new_context
lecture = Lecture.objects.first()
context = new_context(lecture, list(lecture.pages.all()))
context['sections'] = [{'pages': [1], 'topics': []}]
GenerationRun.objects.create(lecture=lecture, page_numbers=[1, 2, 3], status='running', card_limit=3,
    context_enabled=True, context_data=context, visual_enabled=True)
""",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
    )
    page.reload()
    page.get_by_text("reading lecture context, 1 of 3 readable pages saved", exact=False).wait_for()
    subprocess.run(
        [
            sys.executable,
            "manage.py",
            "shell",
            "-c",
            """
from converter.models import GenerationRun
GenerationRun.objects.filter(status='running').update(
    error='Correcting the lecture overview automatically (attempt 2 of 3). Saved work is kept.')
""",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
    )
    page.get_by_text("Correcting generated output", exact=False).wait_for()
    assert "attempt 2 of 3" in page.locator("[data-run-message]").inner_text()
    assert page.get_by_role("button", name="Resume", exact=False).count() == 0
    assert page.locator("progress").get_attribute("value") == "1"
    page.screenshot(path=str(OUTPUT / "automatic-overview-correction.png"), full_page=True)
    page.get_by_role("button", name="Stop generation", exact=True).click()
    page.get_by_text("Generation stopped.", exact=False).wait_for()
    page.locator(".workspace-activity>summary").click()
    assert (
        "Lecture overview: 1 of 3 readable pages saved" in page.locator(".workspace").inner_text()
    )
    # Remove only this isolated synthetic run so the existing recovery scenario continues.
    subprocess.run(
        [
            sys.executable,
            "manage.py",
            "shell",
            "-c",
            """
from converter.models import GenerationRun
GenerationRun.objects.filter(status='cancelled', error__startswith='Correcting the lecture overview automatically').delete()
""",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
    )
    page.reload()


def check_visual_questions_and_rundown(page, environment):
    page.set_viewport_size({"width": 1512, "height": 1100})
    subprocess.run(
        [
            sys.executable,
            "manage.py",
            "shell",
            "-c",
            """
from unittest.mock import patch
from converter.models import GenerationRun, Lecture
from converter.services.generation import perform_run
from tests.test_visual_rundown import visual_output, rundown_output
lecture = Lecture.objects.first()
run = GenerationRun.objects.create(lecture=lecture, page_numbers=[4], card_limit=1,
    text_enabled=False, visual_enabled=True)
with patch('converter.services.generation.codex_generate', side_effect=lambda pages, *a, **kw: visual_output(pages[0])):
    perform_run(run.pk)
run.refresh_from_db()
assert run.status == 'completed', run.error
run = GenerationRun.objects.create(lecture=lecture, page_numbers=[1, 2, 3], purpose='rundown')
with patch('converter.services.generation.codex_generate', side_effect=lambda pages, *a, **kw: rundown_output(pages)):
    perform_run(run.pk)
run.refresh_from_db()
assert run.status == 'completed', run.error
""",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
    )
    page.reload()
    open_queue(page)
    page.locator(".card-item").filter(has_text="What relationship does the figure").click()
    editor = edit_current(page, "[data-source-tool]:has([data-occlusion-editor])")
    assert editor.locator('[data-occlusion-editor][data-visual="yes"]').count() == 1
    assert "one card" in editor.locator("[data-mask-status]").inner_text()
    editor.get_by_label("Region right", exact=True).fill("250")
    editor.get_by_label("Region top", exact=True).focus()
    preview_current(editor)
    editor.get_by_text("One visual question.", exact=False).wait_for()
    assert "One visual question" in editor.locator("[data-preview-output]").inner_text()
    previews = editor.locator("[data-preview-output] img")
    assert previews.count() == 2
    assert previews.nth(0).get_attribute("src") != previews.nth(1).get_attribute("src")
    editor.locator('[name="status"]').select_option("accepted")
    editor.get_by_role("button", name="Save changes", exact=True).click()
    page.get_by_text("Card saved.", exact=False).wait_for()
    assert page.get_by_label("Region right", exact=True).input_value() == "250"
    page.set_viewport_size({"width": 1512, "height": 1100})
    page.screenshot(path=str(OUTPUT / "visual-question-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(OUTPUT / "visual-question-mobile.png"), full_page=True)
    page.locator(".editor-heading [data-show-source]").click()
    assert page.locator(".source-panel").is_visible()
    assert not page.locator(".editor-panel").is_visible()
    page.screenshot(path=str(OUTPUT / "workspace-source-mobile.png"), full_page=True)
    page.locator("[data-hide-source]").click()
    assert page.locator(".editor-panel").is_visible()

    page.get_by_role("link", name="Study guide", exact=True).click()
    page.get_by_role("heading", name="Study guide", exact=True).wait_for()
    assert page.locator(".rundown-topic").count() == 3
    assert page.locator(".rundown-topic script").count() == 0
    assert page.locator(".rundown-formula").count() == 3
    page.get_by_role("link", name="Concept on page 2", exact=True).click()
    page.locator("#concept-2 summary").click()
    page.locator("#concept-2 img").evaluate("image => image.decode()")
    with page.expect_download() as guide:
        page.get_by_role("link", name="Download study guide (.md)", exact=True).click()
    assert "Source excerpt:" in Path(guide.value.path()).read_text(encoding="utf-8")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(OUTPUT / "lecture-rundown-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1512, "height": 1100})
    page.screenshot(path=str(OUTPUT / "lecture-rundown-desktop.png"), full_page=True)
    page.goto(page.url.split("rundown/")[0] + "anatomy/")
    page.get_by_role("heading", name="Anatomy & labelled diagrams", exact=True).wait_for()
    assert page.get_by_role("link", name="Draw masks manually", exact=True).is_visible()
    page.get_by_role("link", name="Cards", exact=True).click()


def main():
    with TemporaryDirectory(dir=ROOT / "data" / "work") as directory:
        environment = {
            **os.environ,
            "SLIDES_DATA_DIR": directory,
            # Connection UI checks must not inspect or change a real Codex sign-in.
            "SLIDES_CODEX_BINARY": str(Path(directory) / "missing-codex.exe"),
            "SLIDES_CLAUDE_BINARY": str(Path(directory) / "missing-claude.exe"),
            "SLIDES_GEMINI_BINARY": str(Path(directory) / "missing-gemini.exe"),
            "SLIDES_KIMI_BINARY": str(Path(directory) / "missing-kimi.exe"),
        }
        for provider in ("codex", "claude", "gemini", "kimi"):
            levels = {
                "codex": ["", "low", "medium", "high", "xhigh", "max"],
                "claude": ["", "low", "medium", "high"],
                "gemini": [""],
                "kimi": ["", "low", "high", "max"],
            }[provider]
            default_effort = "low" if "low" in levels else ""
            models = [
                {
                    "id": "",
                    "label": "CLI default",
                    "efforts": levels,
                    "default_effort": default_effort,
                },
                {
                    "id": "synthetic-" + provider,
                    "label": "Synthetic " + provider,
                    "efforts": levels,
                    "default_effort": default_effort,
                },
            ]
            if provider == "claude":
                models.append(
                    {
                        "id": "synthetic-haiku",
                        "label": "Synthetic Haiku",
                        "efforts": [""],
                        "default_effort": "",
                    }
                )
            if provider == "kimi":
                models.append(
                    {
                        "id": "kimi-code/toggle",
                        "label": "Synthetic thinking toggle",
                        "efforts": ["", "off", "on"],
                        "default_effort": "",
                    }
                )
            (Path(directory) / f"models-{provider}.json").write_text(
                json.dumps({"models": models, "updated_at": 1}), encoding="utf-8"
            )
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
                    page.get_by_role("heading", name="Your lectures", exact=True).wait_for()
                    page.screenshot(path=str(OUTPUT / "home-desktop.png"), full_page=True)
                    assert page.title() == "Your lectures · Recalloom"
                    page.get_by_role("link", name="AI connections", exact=True).click()
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
                    # First installation: only a placeholder is available until
                    # discovery finishes. Use synthetic metadata, never a CLI.
                    catalog_path = Path(directory) / "models-codex.json"
                    cached_catalog = catalog_path.read_text(encoding="utf-8")
                    catalog_path.unlink()
                    discovery = {**json.loads(cached_catalog), "message": "Synthetic models ready"}
                    page.route(
                        "**/connections/codex/models/refresh/",
                        lambda route: route.fulfill(json=discovery),
                    )
                    page.locator('[data-open-dialog="add-lecture"]').click()
                    page.get_by_label("Title", exact=True).fill("Memory & learning · sample")
                    page.locator("#id_pdf").set_input_files(
                        str(ROOT / "tests/fixtures/synthetic/lecture.pdf")
                    )
                    page.get_by_role("button", name="Open lecture").click()
                    page.get_by_role("heading", name="Memory & learning · sample").wait_for()
                    open_creation(page)
                    page.get_by_text("Synthetic models ready", exact=True).wait_for()
                    catalog_path.write_text(cached_catalog, encoding="utf-8")
                    page.unroute("**/connections/codex/models/refresh/")
                    page.get_by_label("Maximum new cards").fill("2")
                    reasoning = page.get_by_role("combobox", name="Reasoning level", exact=True)
                    assert reasoning.input_value() == "low"
                    assert reasoning.locator("option").count() == 6
                    provider = page.get_by_role("combobox", name="AI provider", exact=True)
                    model = page.get_by_role("combobox", name="Model", exact=True)
                    page.locator('input[name="consent"]').check()
                    provider.select_option("claude")
                    assert not page.locator('input[name="consent"]').is_checked()
                    assert (
                        "Anthropic through Claude Code"
                        in page.locator("[data-consent-provider]").inner_text()
                    )
                    assert reasoning.locator("option").count() == 4
                    model.select_option("synthetic-haiku")
                    assert reasoning.is_disabled()
                    assert reasoning.input_value() == ""
                    model.select_option("synthetic-claude")
                    assert reasoning.is_enabled()
                    assert reasoning.locator('option[value="xhigh"]').count() == 0
                    provider.select_option("gemini")
                    model.select_option("synthetic-gemini")
                    assert reasoning.is_disabled()
                    assert reasoning.input_value() == ""
                    assert (
                        "Google through Gemini CLI"
                        in page.locator("[data-consent-provider]").inner_text()
                    )
                    page.locator('input[name="consent"]').check()
                    provider.select_option("kimi")
                    assert not page.locator('input[name="consent"]').is_checked()
                    model.select_option("synthetic-kimi")
                    assert reasoning.locator('option[value="max"]').count() == 1
                    assert reasoning.locator('option[value="on"]').count() == 0
                    reasoning.select_option("max")
                    model.select_option("kimi-code/toggle")
                    assert reasoning.locator('option[value="max"]').count() == 0
                    reasoning.select_option("off")
                    assert (
                        "Moonshot AI through Kimi Code"
                        in page.locator("[data-consent-provider]").inner_text()
                    )
                    provider.select_option("codex")
                    assert reasoning.locator("option").count() == 6
                    page.get_by_role("group", name="Learning focus", exact=True).get_by_role(
                        "radio", name="Understanding", exact=True
                    ).check()
                    formats = page.get_by_role("group", name="Card formats", exact=True)
                    assert formats.get_by_role(
                        "checkbox", name="Basic Q/A", exact=True
                    ).is_checked()
                    formats.get_by_role("checkbox", name="Cloze", exact=True).check()
                    images = formats.get_by_role("checkbox", name="Graphs & formulas", exact=True)
                    page.locator('input[name="consent"]').check()
                    images.check()
                    assert not page.locator('input[name="consent"]').is_checked()
                    assert page.locator("[data-image-only]").is_enabled()
                    assert page.locator("[data-image-only]").is_checked()
                    assert page.locator("[data-image-sharing]").is_visible()
                    assert page.get_by_role(
                        "button", name="Download prompt", exact=True
                    ).is_disabled()
                    provider.select_option("claude")
                    assert images.evaluate("input => input.validationMessage")
                    provider.select_option("codex")
                    assert not images.evaluate("input => input.validationMessage")
                    images.uncheck()
                    assert page.locator("[data-image-only]").is_disabled()
                    assert not page.locator("[data-image-only]").is_checked()
                    model.select_option("synthetic-codex")
                    reasoning.select_option("xhigh")
                    assert reasoning.input_value() == "xhigh"
                    lecture_context = page.locator("[data-lecture-context]")
                    consent = page.locator('input[name="consent"]')
                    assert lecture_context.is_checked()
                    consent.check()
                    lecture_context.uncheck()
                    assert not consent.is_checked()
                    assert (
                        page.locator("[data-context-sharing]").inner_text() == "selected slide text"
                    )
                    consent.check()
                    lecture_context.check()
                    assert not consent.is_checked()
                    assert (
                        "all readable slides" in page.locator("[data-context-sharing]").inner_text()
                    )
                    page.locator('input[name="pages"][value="3"]').uncheck()
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
                    context_only = json.loads(downloaded_text.splitlines()[1])["context_only_pages"]
                    assert [source["page"] for source in context_only] == [3]
                    page.locator('input[name="pages"][value="3"]').check()
                    page.locator("#create-cards [data-close-dialog]").click()
                    page.locator(".header-actions>.workspace-menu summary").click()
                    page.get_by_role("button", name="Use an external chat", exact=True).click()
                    page.locator("#cards-file").set_input_files(
                        str(ROOT / "tests/fixtures/synthetic/cards.json")
                    )
                    page.get_by_role("button", name="Import drafts").click()
                    page.locator("[data-card-form]").wait_for()
                    edit_current(page)
                    assert page.locator("[data-source-image]").evaluate(
                        "img => img.complete && img.naturalWidth > 0"
                    )
                    page.locator("[data-card-form]").get_by_label("Question", exact=True).fill(
                        "What is retrieval practice, in your own words?"
                    )
                    check_slide_viewer(page, browser, errors)
                    page.get_by_role("button", name="Keep & next").click()
                    page.get_by_text("Card saved. Your changes stay with this lecture.").wait_for()
                    check_review_shortcuts(page)
                    with page.expect_download() as download:
                        lecture_action(page, "Export 1 to Anki")
                    assert download.value.suggested_filename.endswith(".apkg")
                    assert Path(download.value.path()).stat().st_size > 1000
                    with page.expect_download() as download:
                        lecture_action(page, "Save backup")
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
                    page.locator(".back-link").click()
                    page.screenshot(path=str(OUTPUT / "home-mobile.png"), full_page=True)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    open_sample(page)
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
from converter.services.lecture_context import new_context
lecture = Lecture.objects.first()
add_drafts(lecture, [(lecture.pages.first(), 'How long is the exam?', '90 minutes.', '')])
_, issues = validate_generated_batch({'cards': [{
    'front': '<script>Unverified question</script>', 'back': 'Unverified answer',
    'page': 1, 'source_quote': 'An invented excerpt'
}]}, {p.number: p for p in lecture.pages.filter(number=1)})
source = lecture.pages.get(number=2)
topic = {'title': '<script>Spaced practice</script>', 'summary': 'Distribute study sessions over time.',
    'priority': 'core', 'page': 2, 'source_quote': source.text[:60]}
context = new_context(lecture, list(lecture.pages.all()))
context['sections'] = [{'pages': context['pages'], 'topics': [topic]}]
context['outline'] = [topic]
GenerationRun.objects.create(lecture=lecture, status='failed', page_numbers=[1, 2, 3],
    completed_pages=[1], issues=issues, cards_added=5, error='Synthetic interruption',
    context_enabled=True, context_data=context)
""",
                        ],
                        cwd=ROOT,
                        env=environment,
                        check=True,
                        capture_output=True,
                    )
                    page.reload()
                    overview = page.locator(".lecture-context")
                    check_automatic_correction_progress(page, environment)
                    page.locator(".workspace-activity>summary").click()
                    overview.locator("summary").click()
                    assert overview.locator("script").count() == 0
                    assert "Spaced practice" in overview.inner_text()
                    overview.get_by_role("button", name="View source page 2", exact=True).click()
                    assert (
                        page.locator("[data-source-image]").get_attribute("alt")
                        == "Source slide, page 2"
                    )
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(
                        path=str(OUTPUT / "lecture-overview-mobile.png"), full_page=True
                    )
                    overview.locator("summary").click()
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
                    page.get_by_role("navigation", name="Filter cards").get_by_role(
                        "link", name="Set aside", exact=False
                    ).click()
                    open_queue(page)
                    page.locator(".card-list").get_by_text(
                        "How long is the exam?", exact=True
                    ).wait_for()
                    page.get_by_role("navigation", name="Filter cards").get_by_role(
                        "link", name="To review", exact=False
                    ).click()
                    page.locator(".workspace-activity>summary").click()
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
                    manual = open_manual(page)
                    manual.get_by_role("group", name="Note format", exact=True).get_by_role(
                        "radio", name="Cloze", exact=True
                    ).check()
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
                    open_queue(page)
                    page.locator(".card-item").filter(has_text="{{c1::recall}}").click()
                    editor = edit_current(page)
                    assert editor.get_by_label("Cloze text", exact=True).input_value() == cloze_text
                    assert editor.locator(".preview-card").count() == 2
                    editor.locator(".crop-editor summary").click()
                    editor.get_by_label("Include a source crop on this note", exact=True).check()
                    crop_image = editor.locator("[data-crop-stage] img")
                    crop_image.evaluate("image => image.decode()")
                    crop_image.scroll_into_view_if_needed()
                    box = crop_image.bounding_box()
                    page.mouse.move(box["x"] + box["width"] * 0.15, box["y"] + box["height"] * 0.15)
                    page.mouse.down()
                    page.mouse.move(
                        box["x"] + box["width"] * 0.7, box["y"] + box["height"] * 0.6, steps=8
                    )
                    page.mouse.up()
                    assert (
                        int(editor.get_by_label("Right", exact=True).input_value())
                        > int(editor.get_by_label("Left", exact=True).input_value())
                        > 0
                    )
                    assert editor.locator("[data-crop-selection]").is_visible()
                    editor.get_by_label("Show the crop on the question too", exact=True).check()
                    editor.get_by_label("Extra explanation (optional)", exact=True).fill(
                        "My checked explanation."
                    )
                    preview_current(editor)
                    editor.get_by_text(
                        "Preview only; edits have not been saved.", exact=False
                    ).wait_for()
                    assert editor.locator(".preview-question .source-crop").count() == 2
                    editor.locator(".preview-question .source-crop").first.evaluate(
                        "image => image.decode()"
                    )
                    if editor.locator(".preview-card details").first.get_attribute("open") is None:
                        editor.locator(".preview-card summary").first.click()
                    assert (
                        "My checked explanation."
                        in editor.locator(".preview-answer").first.inner_text()
                    )
                    page.screenshot(path=str(OUTPUT / "cloze-editor-desktop.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=str(OUTPUT / "cloze-editor-mobile.png"), full_page=True)
                    editor.get_by_role("button", name="Keep & next", exact=False).click()
                    lecture_action(page, "Preview export")
                    page.get_by_role("heading", name="Export preview", exact=True).wait_for()
                    page.get_by_text("3 review cards from 2 accepted notes", exact=False).wait_for()
                    assert page.locator(".preview-card").count() == 3
                    assert page.locator(".preview-question .source-crop").count() == 2
                    page.locator(".preview-question .source-crop").first.evaluate(
                        "image => image.decode()"
                    )
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=str(OUTPUT / "cloze-export-mobile.png"), full_page=True)
                    page.set_viewport_size({"width": 1512, "height": 1100})
                    page.screenshot(path=str(OUTPUT / "cloze-export-desktop.png"), full_page=True)
                    with page.expect_download() as cloze_export:
                        page.get_by_role("link", name="Export 3 to Anki", exact=False).click()
                    assert Path(cloze_export.value.path()).stat().st_size > 1000
                    page.get_by_role("link", name="Back to lecture", exact=False).click()
                    # Reverse cards remain opt-in, and count twice in the shared limit.
                    open_creation(page)
                    formats = page.get_by_role("group", name="Card formats", exact=True)
                    formats.get_by_role("checkbox", name="Basic Q/A", exact=True).uncheck()
                    formats.get_by_role("checkbox", name="Cloze", exact=True).uncheck()
                    formats.get_by_role("checkbox", name="Basic + reverse", exact=True).check()
                    limit = page.get_by_label("Maximum new cards", exact=True)
                    limit.fill("1")
                    assert not limit.evaluate("input => input.checkValidity()")
                    limit.fill("3")
                    with page.expect_download() as reverse_prompt:
                        page.get_by_role("button", name="Download prompt", exact=True).click()
                    prompt_text = Path(reverse_prompt.value.path()).read_text(encoding="utf-8")
                    assert "CARD FORMAT: reversed" in prompt_text
                    assert "each reversed note costs 2" in prompt_text
                    for label in ("Basic Q/A", "Cloze"):
                        formats.get_by_role("checkbox", name=label, exact=True).check()
                    assert limit.get_attribute("min") == "1"
                    page.screenshot(
                        path=str(OUTPUT / "reverse-formats-desktop.png"), full_page=True
                    )
                    manual = open_manual(page)
                    manual.get_by_role("radio", name="Basic + reverse", exact=True).check()
                    manual.get_by_label("Front (prompt for card 1)", exact=True).fill(
                        "Bidirectional sample term"
                    )
                    manual.get_by_label("Back (prompt for card 2)", exact=True).fill(
                        "Bidirectional sample definition"
                    )
                    manual.get_by_role("button", name="Preview cards", exact=True).click()
                    manual.get_by_text(
                        "2 Anki review cards from this note.", exact=False
                    ).wait_for()
                    assert manual.locator(".preview-question").all_text_contents() == [
                        "Bidirectional sample term",
                        "Bidirectional sample definition",
                    ]
                    assert "Back → front" in manual.locator(".preview-card").last.inner_text()
                    manual.get_by_role("button", name="Add draft", exact=True).click()
                    open_queue(page)
                    page.locator(".card-item").filter(has_text="Bidirectional sample term").click()
                    editor = edit_current(page)
                    assert editor.locator(".preview-card").count() == 2
                    editor.get_by_label("Back (prompt for card 2)", exact=True).fill(
                        "Edited bidirectional definition"
                    )
                    preview_current(editor)
                    editor.get_by_text(
                        "Preview only; edits have not been saved.", exact=False
                    ).wait_for()
                    assert (
                        editor.locator(".preview-question").last.inner_text()
                        == "Edited bidirectional definition"
                    )
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=str(OUTPUT / "reverse-editor-mobile.png"), full_page=True)
                    editor.get_by_role("button", name="Keep & next", exact=False).click()
                    lecture_action(page, "Preview export")
                    page.get_by_text("5 review cards from 3 accepted notes", exact=False).wait_for()
                    assert page.locator(".preview-card").count() == 5
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    with page.expect_download() as reverse_export:
                        page.get_by_role("link", name="Export 5 to Anki", exact=False).click()
                    assert Path(reverse_export.value.path()).stat().st_size > 1000
                    page.set_viewport_size({"width": 1512, "height": 1100})
                    page.screenshot(path=str(OUTPUT / "reverse-export-desktop.png"), full_page=True)
                    # Manual image occlusion works on the image-only slide without inference.
                    page.get_by_role("link", name="Back to lecture", exact=False).click()
                    open_creation(page)
                    page.locator("#create-cards [data-close-dialog]").click()
                    page.locator(".source-tools .workspace-menu summary").click()
                    page.get_by_role("link", name="Anatomy & diagrams", exact=True).click()
                    page.get_by_role("link", name="Draw masks manually", exact=True).click()
                    page.get_by_label("Source page", exact=True).select_option("4")
                    page.get_by_role("button", name="Use page", exact=True).click()
                    builder = page.locator("[data-card-form]")
                    builder.get_by_label("Prompt", exact=True).fill("Image occlusion sample")
                    image = builder.locator("[data-mask-stage] img")
                    image.evaluate("image => image.decode()")
                    image.scroll_into_view_if_needed()
                    box = image.bounding_box()
                    for left, right in ((0.1, 0.3), (0.5, 0.75)):
                        page.mouse.move(
                            box["x"] + box["width"] * left, box["y"] + box["height"] * 0.2
                        )
                        page.mouse.down()
                        page.mouse.move(
                            box["x"] + box["width"] * right, box["y"] + box["height"] * 0.5, steps=8
                        )
                        page.mouse.up()
                    assert builder.locator("[data-mask-list] button").count() == 2
                    masks = json.loads(builder.locator('[name="masks"]').input_value())
                    assert all(mask["page"] == 4 and mask["right"] > mask["left"] for mask in masks)
                    check_mask_manipulation(page, builder)
                    # Suggestion transport is mocked: no image or text leaves this test.
                    page.get_by_text("Suggest regions with AI", exact=True).click()
                    suggestion_form = page.locator("[data-suggestion-form]")
                    suggestion_results = page.locator("[data-suggestion-results]")
                    suggestion_form.locator('[name="consent"]').check()
                    suggestion_form.locator('[name="overview"]').uncheck()
                    assert not suggestion_form.locator('[name="consent"]').is_checked()
                    suggestion_form.locator('[name="overview"]').check()
                    suggestion_form.locator('[name="consent"]').check()
                    suggestion_state = {
                        "id": "synthetic-job",
                        "status": "completed",
                        "page": 4,
                        "model": "synthetic-codex",
                        "reasoning_effort": "low",
                        "context_used": True,
                        "suggestions": [
                            {
                                "label": "<script>Visible label</script>",
                                "reason": "Recall this label.",
                                "mask": {
                                    "page": 4,
                                    "left": 20,
                                    "top": 30,
                                    "right": 180,
                                    "bottom": 100,
                                },
                            }
                        ],
                        "error": "",
                    }
                    page.route(
                        "**/occlusion/suggestions/",
                        lambda route: route.fulfill(json=suggestion_state),
                    )
                    page.route(
                        "**/occlusion/suggestions/synthetic-job/",
                        lambda route: route.fulfill(json=suggestion_state),
                    )
                    page.route(
                        "**/occlusion/suggestions/synthetic-job/cancel/",
                        lambda route: route.fulfill(json={"status": "cancelled"}),
                    )
                    suggestion_form.get_by_role(
                        "button", name="Suggest regions", exact=True
                    ).click()
                    suggestion_results.get_by_role("button", name="Use suggestion 1").wait_for()
                    assert suggestion_results.locator("script").count() == 0
                    assert json.loads(builder.locator('[name="masks"]').input_value()) == masks
                    suggestion_results.get_by_role("button", name="Use suggestion 1").click()
                    assert builder.locator("[data-mask-list] button").count() == 3
                    suggestion_results.get_by_role("button", name="Use suggestion 1").click()
                    assert builder.locator("[data-mask-list] button").count() == 3
                    builder.get_by_label("Region right", exact=True).fill("210")
                    builder.get_by_label("Region top", exact=True).focus()
                    assert (
                        json.loads(builder.locator('[name="masks"]').input_value())[2]["right"]
                        == 210
                    )
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(
                        path=str(OUTPUT / "occlusion-suggestions-mobile.png"), full_page=True
                    )
                    page.set_viewport_size({"width": 1512, "height": 1100})
                    builder.get_by_role("button", name="Undo", exact=True).click()
                    builder.get_by_role("button", name="Undo", exact=True).click()
                    assert json.loads(builder.locator('[name="masks"]').input_value()) == masks
                    suggestion_state["status"] = "running"
                    suggestion_form.get_by_role(
                        "button", name="Suggest regions", exact=True
                    ).click()
                    suggestion_form.get_by_text(
                        "Analysing this slide with Codex", exact=False
                    ).wait_for()
                    suggestion_form.get_by_role(
                        "button", name="Stop suggestions", exact=True
                    ).click()
                    suggestion_form.get_by_text("Suggestions stopped.", exact=False).wait_for()
                    assert json.loads(builder.locator('[name="masks"]').input_value()) == masks
                    suggestion_state.update(status="completed", suggestions=[])
                    suggestion_form.get_by_role(
                        "button", name="Suggest regions", exact=True
                    ).click()
                    suggestion_form.get_by_text(
                        "No suitable regions were suggested.", exact=False
                    ).wait_for()
                    assert json.loads(builder.locator('[name="masks"]').input_value()) == masks
                    page.get_by_text("Suggest regions with AI", exact=True).click()
                    page.unroute("**/occlusion/suggestions/")
                    page.unroute("**/occlusion/suggestions/synthetic-job/")
                    page.unroute("**/occlusion/suggestions/synthetic-job/cancel/")
                    # Keyboard controls support adding/removing a region and precise adjustments.
                    builder.get_by_role("button", name="Add region", exact=True).click()
                    assert builder.locator("[data-mask-list] button").count() == 3
                    builder.get_by_role("button", name="Remove selected region", exact=True).click()
                    assert builder.locator("[data-mask-list] button").count() == 2
                    builder.get_by_label("Region left", exact=True).fill(str(masks[1]["left"] + 5))
                    builder.get_by_label("Region top", exact=True).focus()
                    builder.get_by_role(
                        "button", name="Preview selected region", exact=True
                    ).click()
                    builder.get_by_text(
                        "Region 2 of 2. Each region makes one card.", exact=False
                    ).wait_for()
                    assert builder.locator(".preview-card").count() == 1
                    hidden = builder.locator(".preview-question img")
                    hidden.evaluate("image => image.decode()")
                    builder.locator(".preview-card summary").click()
                    revealed = builder.locator(".preview-answer img")
                    revealed.evaluate("image => image.decode()")
                    assert hidden.get_attribute("src") != revealed.get_attribute("src")
                    page.screenshot(
                        path=str(OUTPUT / "occlusion-builder-desktop.png"), full_page=True
                    )
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    touch_canvas = builder.locator("[data-mask-stage]")
                    touch_canvas.scroll_into_view_if_needed()
                    touch_region = builder.locator('[data-mask-index="1"]')
                    touch_box = touch_region.bounding_box()
                    tx, ty = (
                        touch_box["x"] + touch_box["width"] / 2,
                        touch_box["y"] + touch_box["height"] / 2,
                    )
                    before_touch = json.loads(builder.locator('[name="masks"]').input_value())
                    cdp = page.context.new_cdp_session(page)
                    cdp.send(
                        "Input.dispatchTouchEvent",
                        {"type": "touchStart", "touchPoints": [{"x": tx, "y": ty}]},
                    )
                    cdp.send(
                        "Input.dispatchTouchEvent",
                        {"type": "touchMove", "touchPoints": [{"x": tx + 10, "y": ty + 8}]},
                    )
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                    after_touch = json.loads(builder.locator('[name="masks"]').input_value())
                    assert (
                        len(after_touch) == 2 and after_touch[1]["left"] > before_touch[1]["left"]
                    )
                    builder.get_by_role("button", name="Undo", exact=True).click()
                    assert (
                        json.loads(builder.locator('[name="masks"]').input_value()) == before_touch
                    )
                    cdp.detach()
                    page.screenshot(
                        path=str(OUTPUT / "occlusion-builder-mobile.png"), full_page=True
                    )
                    builder.get_by_role("button", name="Add drafts", exact=True).click()
                    page.get_by_text("2 image occlusion draft(s) added.", exact=False).wait_for()
                    page.set_viewport_size({"width": 1512, "height": 1100})
                    editor = edit_current(page, "[data-source-tool]:has([data-occlusion-editor])")
                    assert editor.locator('[data-single="yes"]').count() == 1
                    assert editor.locator('[name="crop_enabled"]').count() == 0
                    original_action = editor.get_attribute("action")
                    saved_region = editor.locator('[data-mask-index="0"]')
                    saved_region.scroll_into_view_if_needed()
                    region_box = saved_region.bounding_box()
                    sx, sy = (
                        region_box["x"] + region_box["width"] / 2,
                        region_box["y"] + region_box["height"] / 2,
                    )
                    saved_mask = json.loads(editor.locator('[name="masks"]').input_value())[0]
                    page.mouse.move(sx, sy)
                    page.mouse.down()
                    page.mouse.move(sx + 12, sy + 8, steps=5)
                    page.mouse.up()
                    assert editor.locator("[data-mask-list] button").count() == 1
                    assert (
                        json.loads(editor.locator('[name="masks"]').input_value())[0]["left"]
                        > saved_mask["left"]
                    )
                    editor.get_by_label("Extra explanation (optional)", exact=True).fill(
                        "Image answer explanation"
                    )
                    editor.get_by_label("Region right", exact=True).fill(
                        str(masks[0]["right"] + 10)
                    )
                    editor.get_by_label("After saving", exact=True).select_option("accepted")
                    preview_current(editor)
                    editor.get_by_text(
                        "Region 1 of 1. Each region makes one card.", exact=False
                    ).wait_for()
                    editor.get_by_role("button", name="Save changes", exact=True).click()
                    assert (
                        page.locator("[data-card-form]").get_attribute("action") == original_action
                    )
                    occlusion_notes = page.locator(".card-item").filter(
                        has_text="Image occlusion sample"
                    )
                    assert occlusion_notes.count() == 2
                    open_queue(page)
                    occlusion_notes.last.click()
                    editor = edit_current(page)
                    assert editor.get_attribute("action") != original_action
                    editor.get_by_role("button", name="Keep & next", exact=False).click()
                    lecture_action(page, "Preview export")
                    page.get_by_text("7 review cards from 5 accepted notes", exact=False).wait_for()
                    assert page.locator(".preview-card").count() == 7
                    occlusion_previews = page.locator(".export-preview-note").filter(
                        has_text="Image occlusion"
                    )
                    assert occlusion_previews.count() == 2
                    occlusion_previews.locator(".preview-question img").first.evaluate(
                        "image => image.decode()"
                    )
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(
                        path=str(OUTPUT / "occlusion-export-mobile.png"), full_page=True
                    )
                    with page.expect_download() as occlusion_export:
                        page.get_by_role("link", name="Export 7 to Anki", exact=False).click()
                    assert Path(occlusion_export.value.path()).stat().st_size > 1000
                    page.get_by_role("link", name="Back to lecture", exact=False).click()
                    with page.expect_download() as occlusion_backup:
                        lecture_action(page, "Save backup")
                    assert Path(occlusion_backup.value.path()).stat().st_size > 1000
                    # Saved generation proposals use the real review/save/export views.
                    # All inference below is synthetic, isolated from CLI credentials.
                    subprocess.run(
                        [
                            sys.executable,
                            "manage.py",
                            "shell",
                            "-c",
                            """
from unittest.mock import patch
from converter.models import GenerationRun, Lecture
from converter.services.generation import perform_run
lecture = Lecture.objects.first()
run = GenerationRun.objects.create(lecture=lecture, page_numbers=[1, 2, 3], card_limit=3,
    text_enabled=False, occlusion_enabled=True)
def images(pages, *args, **kwargs):
    return {'suggestions': [{'label': 'Saved label ' + str(pages[0].number),
        'reason': 'Recall this visible structure.', 'left': 20, 'top': 30, 'right': 180, 'bottom': 100}]}
with patch('converter.services.generation.codex_generate', side_effect=images):
    perform_run(run.pk)
run.refresh_from_db()
assert run.status == 'completed', run.error
assert run.suggestions.count() == 3
""",
                        ],
                        cwd=ROOT,
                        env=environment,
                        check=True,
                        capture_output=True,
                    )
                    page.reload()
                    page.get_by_role("link", name="Review image suggestions", exact=False).click()
                    page.get_by_role("heading", name="Image suggestions", exact=True).wait_for()
                    review = page.locator("[data-card-form]")
                    review.get_by_label("Prompt", exact=True).fill("Edited saved suggestion")
                    review.get_by_label("Region right", exact=True).fill("220")
                    review.get_by_label("Region top", exact=True).focus()
                    review.get_by_role("button", name="Preview changes", exact=True).click()
                    review.locator("[data-preview-output] img").first.wait_for()
                    review.get_by_role("button", name="Save edits", exact=True).click()
                    page.get_by_text("Suggestion changes saved.", exact=False).wait_for()
                    review = page.locator("[data-card-form]")
                    assert review.get_by_label("Region right", exact=True).input_value() == "220"
                    page.set_viewport_size({"width": 1512, "height": 1100})
                    page.screenshot(
                        path=str(OUTPUT / "saved-occlusions-desktop.png"), full_page=True
                    )
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(
                        path=str(OUTPUT / "saved-occlusions-mobile.png"), full_page=True
                    )
                    review.get_by_role("button", name="Keep & next", exact=True).click()
                    page.get_by_text("Region saved.", exact=False).wait_for()
                    page.locator("[data-card-form]").get_by_role(
                        "button", name="Discard", exact=True
                    ).click()
                    page.get_by_text("Suggestion discarded.", exact=False).wait_for()
                    page.get_by_role("navigation", name="Suggestion status").get_by_role(
                        "link", name="Discarded", exact=True
                    ).click()
                    page.get_by_role("button", name="Restore suggestion", exact=True).click()
                    page.get_by_text("Suggestion restored for review.", exact=False).wait_for()
                    page.get_by_role("navigation", name="Suggestion status").get_by_role(
                        "link", name="Accepted", exact=True
                    ).click()
                    page.get_by_role(
                        "link", name="Open the saved card to edit it", exact=True
                    ).click()
                    assert page.locator("#id_front").input_value() == "Edited saved suggestion"
                    assert page.get_by_label("Region right", exact=True).input_value() == "220"
                    check_visual_questions_and_rundown(page, environment)
                    # Return to export preview so the existing deletion workflow starts as before.
                    lecture_action(page, "Preview export")
                    # Delete only this isolated synthetic set, then import the same PDF afresh.
                    page.get_by_role("link", name="Back to lecture", exact=False).click()
                    old_lecture_url = page.url.split("?")[0]
                    lecture_action(page, "Delete set")
                    page.get_by_role("heading", name="Delete this set?", exact=True).wait_for()
                    assert page.get_by_role(
                        "link", name="Save backup first", exact=True
                    ).is_visible()
                    page.screenshot(path=str(OUTPUT / "delete-set-desktop.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.get_by_role(
                        "checkbox", name="I want to permanently delete this set from Recalloom."
                    ).check()
                    page.get_by_role("button", name="Delete set permanently", exact=True).click()
                    page.get_by_text("Set removed.", exact=False).wait_for()
                    assert page.locator(".lecture-tile").count() == 0
                    open_sample(page)
                    page.locator(".card-list").wait_for(state="attached")
                    assert page.url.split("?")[0] != old_lecture_url
                    assert page.locator(".card-item").count() == 5
                    assert page.request.get(old_lecture_url).status == 404
                    check_bulk_review(page)
                    page.get_by_role("link", name="AI connections", exact=True).click()
                    page.get_by_role("navigation", name="AI connections", exact=True).get_by_role(
                        "link", name="Claude Code", exact=True
                    ).click()
                    page.get_by_role("heading", name="Connect Claude Code.", exact=True).wait_for()
                    page.get_by_role(
                        "link", name="Open the Claude Code setup guide", exact=False
                    ).wait_for()
                    page.screenshot(
                        path=str(OUTPUT / "claude-connection-mobile.png"), full_page=True
                    )
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    for label, slug in (("Gemini CLI", "gemini"), ("Kimi Code", "kimi")):
                        page.get_by_role(
                            "navigation", name="AI connections", exact=True
                        ).get_by_role("link", name=label, exact=True).click()
                        page.get_by_role("heading", name=f"Connect {label}.", exact=True).wait_for()
                        page.get_by_role(
                            "link", name=f"Open the {label} setup guide", exact=False
                        ).wait_for()
                        assert (
                            "separate local CLI profile"
                            in page.locator(".connection-panel").inner_text()
                        )
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        page.screenshot(
                            path=str(OUTPUT / f"{slug}-connection-mobile.png"), full_page=True
                        )
                    assert not errors, errors
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=10)
    print(
        "Browser checks passed: sample import, edit/accept, Keep all drafts with confirmation and unsaved-edit protection, same-tab slide viewer with zoom/pan and touch pinch, preserved edits and image retry, export, backup, recovery, provider/model/effort dropdowns, cloze/reverse cards, crops, image occlusion drawing and unsaved previews, graph/formula questions with editable covers, source-linked lecture rundown and Markdown, mixed export, confirmed set deletion and fresh reimport, desktop/mobile layouts, no JavaScript errors."
    )
    print(f"Screenshots: {OUTPUT}")


if __name__ == "__main__":
    main()
