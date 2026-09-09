"""Explicit live smoke check. Uses the user's Codex allowance on synthetic text only."""

import argparse
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Consent to using the local Codex account for a small synthetic generation test",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error(
            "Pass --live to explicitly run the provider check. Routine tests do not call a provider."
        )
    folder = ROOT / "data" / "live-checks" / str(uuid.uuid4())
    os.environ["SLIDES_DATA_DIR"] = str(folder)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.core.management import call_command

    from converter.models import GenerationRun
    from converter.services.documents import import_pdf
    from converter.services.generation import perform_run

    call_command("migrate", verbosity=0)
    lecture, _ = import_pdf(
        SimpleUploadedFile(
            "synthetic.pdf", (ROOT / "tests/fixtures/synthetic/lecture.pdf").read_bytes()
        )
    )
    run = GenerationRun.objects.create(lecture=lecture, page_numbers=[1, 2, 3])
    print("Generating from three synthetic pages with the local Codex CLI…", flush=True)
    perform_run(run.pk)
    run.refresh_from_db()
    print(
        f"Status: {run.status}; drafts: {run.cards_added}; completed pages: {run.completed_pages}"
    )
    print(f"Isolated check data: {folder}")
    if run.status != "completed" or not run.cards_added:
        print(run.error)
        sys.exit(1)
    for card in lecture.cards.all()[:3]:
        print(f"Page {card.page.number}: {card.front}")


if __name__ == "__main__":
    main()
