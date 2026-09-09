import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.db import IntegrityError, transaction

from converter.models import Lecture, Page

from .files import WorkflowError, media_path


def import_pdf(upload, title=""):
    if upload.size > settings.MAX_PDF_BYTES:
        raise WorkflowError("Choose a PDF smaller than 25 MB.")
    with TemporaryDirectory(dir=settings.WORK_DIR) as temporary:
        temporary = Path(temporary)
        source = temporary / "original.pdf"
        digest = hashlib.sha256()
        size = 0
        with source.open("wb") as handle:
            for chunk in upload.chunks():
                size += len(chunk)
                if size > settings.MAX_PDF_BYTES:
                    raise WorkflowError("Choose a PDF smaller than 25 MB.")
                digest.update(chunk)
                handle.write(chunk)
        with source.open("rb") as handle:
            if b"%PDF-" not in handle.read(1024):
                raise WorkflowError("This file is not a PDF. Export your slides as a PDF first.")
        sha256 = digest.hexdigest()
        existing = Lecture.objects.filter(sha256=sha256).first()
        if existing:
            return existing, False
        command = [
            sys.executable,
            str(Path(__file__).with_name("pdf_worker.py")),
            str(source),
            str(temporary),
            str(settings.MAX_PDF_PAGES),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=settings.PDF_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(
                "Processing took too long. Split the PDF into smaller lectures and try again."
            ) from exc
        if result.returncode:
            raise WorkflowError(
                "Could not process this PDF. Use an unencrypted PDF with at most 100 normal-sized pages."
            )
        pages = json.loads((temporary / "pages.json").read_text(encoding="utf-8"))
        lecture_id = uuid.uuid4()
        folder = f"documents/{lecture_id}"
        destination = media_path(folder)
        destination.parent.mkdir(parents=True, exist_ok=True)
        owns_destination = False
        try:
            with transaction.atomic():
                lecture = Lecture.objects.create(
                    id=lecture_id,
                    title=(title.strip() or Path(upload.name).stem)[:180],
                    sha256=sha256,
                    original_name=Path(upload.name).name[:255],
                    original_file=f"{folder}/original.pdf",
                )
                destination.mkdir()
                owns_destination = True
                shutil.copytree(temporary, destination, dirs_exist_ok=True)
                Page.objects.bulk_create(
                    [
                        Page(lecture=lecture, **{**page, "image": f"{folder}/{page['image']}"})
                        for page in pages
                    ]
                )
        except Exception as exc:
            if (
                owns_destination
                and destination.exists()
                and destination.resolve().is_relative_to(Path(settings.MEDIA_ROOT).resolve())
            ):
                shutil.rmtree(destination)
            if isinstance(exc, IntegrityError):
                existing = Lecture.objects.filter(sha256=sha256).first()
                if existing:
                    return existing, False
            raise
        return lecture, True
