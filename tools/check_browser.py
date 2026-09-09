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
        environment = {**os.environ, "SLIDES_DATA_DIR": directory}
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
                    page.get_by_label("Title", exact=True).fill("Memory & learning · sample")
                    page.locator("#id_pdf").set_input_files(
                        str(ROOT / "tests/fixtures/synthetic/lecture.pdf")
                    )
                    page.get_by_role("button", name="Open lecture").click()
                    page.get_by_role("heading", name="Memory & learning · sample").wait_for()
                    with page.expect_download() as downloaded_prompt:
                        page.get_by_role("button", name="Download prompt").click()
                    assert "LECTURE PAGE DATA" in Path(downloaded_prompt.value.path()).read_text(
                        encoding="utf-8"
                    )
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
                    assert not errors, errors
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=10)
    print(
        "Browser checks passed: sample import, source image, edit/accept, export, backup, page switch, desktop/mobile layouts, no JavaScript errors."
    )
    print(f"Screenshots: {OUTPUT}")


if __name__ == "__main__":
    main()
