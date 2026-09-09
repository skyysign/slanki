import hashlib
import io
import json
import shutil
import uuid
import zipfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware

from converter.models import Card, CardRevision, GenerationRun, Lecture, Page

from .cards import validate_content
from .files import WorkflowError, media_path

MAX_BACKUP_BYTES = 200 * 1024 * 1024


@transaction.atomic
def export_backup(lecture):
    pages = list(lecture.pages.all())
    cards = list(lecture.cards.select_related("page"))
    assets = {"original.pdf": media_path(lecture.original_file)}
    assets.update({f"pages/{page.number}.png": media_path(page.image) for page in pages})
    if any(not path.is_file() for path in assets.values()):
        raise WorkflowError(
            "Some source files are missing. Restore them before making a new backup."
        )
    manifest = {
        "format": "slides-to-anki",
        "version": 4,
        "lecture": {
            "id": str(lecture.id),
            "title": lecture.title,
            "sha256": lecture.sha256,
            "original_name": lecture.original_name,
            "created_at": lecture.created_at.isoformat(),
        },
        "pages": [
            {
                "number": p.number,
                "text": p.text,
                "width": p.width,
                "height": p.height,
                "warning": p.warning,
            }
            for p in pages
        ],
        "cards": [
            {
                "id": str(c.id),
                "page": c.page.number,
                "front": c.front,
                "back": c.back,
                "source_quote": c.source_quote,
                "status": c.status,
                "fingerprint": c.fingerprint,
                "version": c.version,
                "anki_modified": c.anki_modified,
                "run": str(c.run_id) if c.run_id else None,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "revisions": [
                    {
                        "version": r.version,
                        "front": r.front,
                        "back": r.back,
                        "source_quote": r.source_quote,
                        "status": r.status,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in c.revisions.all()
                ],
            }
            for c in cards
        ],
        "runs": [
            {
                "id": str(r.id),
                "status": r.status,
                "provider": r.provider,
                "page_numbers": r.page_numbers,
                "completed_pages": r.completed_pages,
                "issues": r.issues,
                "cards_added": r.cards_added,
                "card_limit": r.card_limit,
                "reasoning_effort": r.reasoning_effort,
                "filtered_count": r.filtered_count,
                "over_limit_count": r.over_limit_count,
                "error": r.error,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in lecture.runs.all()
        ],
        "assets": {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in assets.items()
        },
    }
    output = io.BytesIO()
    encoded_manifest = json.dumps(manifest, ensure_ascii=False)
    if (
        len(encoded_manifest.encode("utf-8")) > 5 * 1024 * 1024
        or sum(path.stat().st_size for path in assets.values())
        + len(encoded_manifest.encode("utf-8"))
        > MAX_BACKUP_BYTES
        or len(manifest["cards"]) > 10000
        or len(manifest["runs"]) > 1000
        or any(len(card["revisions"]) > 1000 for card in manifest["cards"])
    ):
        raise WorkflowError(
            "This lecture exceeds the current backup limits. Keep a separate copy of the entire data folder while the app is stopped."
        )
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", encoded_manifest)
        for name, path in assets.items():
            archive.write(path, name)
    return output.getvalue()


def timestamp(value):
    result = parse_datetime(value)
    if result is None or not is_aware(result):
        raise WorkflowError("Backup contains an invalid timestamp.")
    return result


def require_keys(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise WorkflowError("Backup contains an invalid record structure.")


def validate_run_pages(numbers, allowed):
    if (
        not isinstance(numbers, list)
        or any(type(number) is not int or number not in allowed for number in numbers)
        or len(numbers) != len(set(numbers))
    ):
        raise WorkflowError("Backup contains invalid generation page references.")


def validate_run_issues(issues, page_numbers):
    if not isinstance(issues, list) or len(issues) > 500 * settings.MAX_PDF_PAGES:
        raise WorkflowError("Backup contains invalid generation issues.")
    for issue in issues:
        require_keys(issue, "page batch_pages reason front back source_quote")
        validate_run_pages(issue["batch_pages"], page_numbers)
        if issue["page"] is not None:
            validate_run_pages([issue["page"]], issue["batch_pages"])
        for key, limit in [
            ("reason", 1000),
            ("front", 1000),
            ("back", 5000),
            ("source_quote", 2500),
        ]:
            if not isinstance(issue[key], str) or len(issue[key]) > limit or "\x00" in issue[key]:
                raise WorkflowError("Backup contains an invalid generation issue.")


def restore_backup(upload):
    """Restore a new lecture only; never replace a current lecture or extract arbitrary paths."""
    if upload.size > MAX_BACKUP_BYTES:
        raise WorkflowError("Backup is too large (maximum 200 MB).")
    destination = None
    owns_destination = False
    try:
        with zipfile.ZipFile(upload) as archive:
            members = archive.infolist()
            if len(members) > 102 or sum(item.file_size for item in members) > MAX_BACKUP_BYTES:
                raise WorkflowError("Backup exceeds the supported size or page limit.")
            if len({item.filename for item in members}) != len(members):
                raise WorkflowError("Backup contains duplicate entries.")
            if archive.getinfo("manifest.json").file_size > 5 * 1024 * 1024:
                raise WorkflowError("Backup manifest is too large.")
            manifest = json.loads(archive.read("manifest.json"))
            require_keys(manifest, "format version lecture pages cards runs assets")
            if (
                manifest["format"] != "slides-to-anki"
                or type(manifest["version"]) is not int
                or manifest["version"] not in (1, 2, 3, 4)
            ):
                raise WorkflowError("This is not a supported Recalloom backup.")
            info = manifest["lecture"]
            require_keys(info, "id title sha256 original_name created_at")
            lecture_id = uuid.UUID(info["id"])
            if (
                Lecture.objects.filter(pk=lecture_id).exists()
                or Lecture.objects.filter(sha256=info["sha256"]).exists()
            ):
                raise WorkflowError(
                    "This lecture already exists. Restore into a separate data folder to inspect an older backup."
                )
            pages = manifest["pages"]
            if not 1 <= len(pages) <= settings.MAX_PDF_PAGES or [
                p["number"] for p in pages
            ] != list(range(1, len(pages) + 1)):
                raise WorkflowError("Backup page numbers are invalid.")
            expected = {"original.pdf", *(f"pages/{p['number']}.png" for p in pages)}
            if set(manifest["assets"]) != expected or {m.filename for m in members} != expected | {
                "manifest.json"
            }:
                raise WorkflowError("Backup contains unexpected or missing files.")
            contents = {}
            for name in expected:
                contents[name] = archive.read(name)
                if hashlib.sha256(contents[name]).hexdigest() != manifest["assets"][name]:
                    raise WorkflowError("Backup failed its integrity check.")
            if hashlib.sha256(contents["original.pdf"]).hexdigest() != info["sha256"]:
                raise WorkflowError(
                    "The original PDF does not match the backup's document identity."
                )
            if len(manifest["cards"]) > 10000 or len(manifest["runs"]) > 1000:
                raise WorkflowError("Backup contains too many records.")
            folder = f"documents/{lecture_id}"
            destination = media_path(folder)
            if destination.exists():
                destination = None
                raise WorkflowError(
                    "Source files with this identity already exist. Restore into a separate data folder."
                )
            with transaction.atomic():
                lecture = Lecture(
                    id=lecture_id,
                    title=info["title"],
                    sha256=info["sha256"],
                    original_name=info["original_name"],
                    original_file=f"{folder}/original.pdf",
                )
                lecture.full_clean()
                lecture.save()
                Lecture.objects.filter(pk=lecture.pk).update(
                    created_at=timestamp(info["created_at"])
                )
                page_map = {}
                for p in pages:
                    require_keys(p, "number text width height warning")
                    page = Page(lecture=lecture, **p, image=f"{folder}/page-{p['number']:03}.png")
                    page.full_clean()
                    if len(page.text) > 25000 or not (
                        0 < page.width <= 1500 and 0 < page.height <= 1500
                    ):
                        raise WorkflowError("Backup contains an invalid source page.")
                    page.save()
                    page_map[page.number] = page
                run_ids = set()
                for r in manifest["runs"]:
                    require_keys(
                        r,
                        "id status provider page_numbers completed_pages cards_added error created_at updated_at"
                        + (" issues" if manifest["version"] >= 2 else "")
                        + (
                            " card_limit filtered_count over_limit_count"
                            if manifest["version"] >= 3
                            else ""
                        )
                        + (" reasoning_effort" if manifest["version"] >= 4 else ""),
                    )
                    r = dict(r)
                    r.setdefault("issues", [])
                    if r.get("card_limit") is not None and (
                        type(r["card_limit"]) is not int or not 1 <= r["card_limit"] <= 500
                    ):
                        raise WorkflowError("Backup contains an invalid card limit.")
                    validate_run_pages(r["page_numbers"], page_map)
                    validate_run_pages(r["completed_pages"], r["page_numbers"])
                    validate_run_issues(r["issues"], r["completed_pages"])
                    created, updated = (
                        timestamp(r.pop("created_at")),
                        timestamp(r.pop("updated_at")),
                    )
                    if r["status"] in ("queued", "running"):
                        r["status"], r["error"] = (
                            "failed",
                            "Generation was interrupted by backup/restore. Saved drafts are intact.",
                        )
                    run = GenerationRun(lecture=lecture, **r)
                    run.full_clean()
                    run.save(force_insert=True)
                    run_ids.add(str(run.pk))
                    GenerationRun.objects.filter(pk=run.pk).update(
                        created_at=created, updated_at=updated
                    )
                for c in manifest["cards"]:
                    require_keys(
                        c,
                        "id page front back source_quote status fingerprint version anki_modified run created_at updated_at revisions",
                    )
                    c = dict(c)
                    page = page_map[c.pop("page")]
                    revisions = c.pop("revisions")
                    created, updated = (
                        timestamp(c.pop("created_at")),
                        timestamp(c.pop("updated_at")),
                    )
                    run_id = c.pop("run")
                    if run_id and run_id not in run_ids:
                        raise WorkflowError("Backup has an invalid generation reference.")
                    validate_content(c["front"], c["back"], c["source_quote"], page)
                    card = Card(lecture=lecture, page=page, run_id=run_id, **c)
                    card.full_clean()
                    card.save(force_insert=True)
                    Card.objects.filter(pk=card.pk).update(created_at=created, updated_at=updated)
                    if len(revisions) > 1000:
                        raise WorkflowError("Backup contains too many card revisions.")
                    for revision in revisions:
                        require_keys(revision, "version front back source_quote status created_at")
                        revision_time = timestamp(revision.pop("created_at"))
                        record = CardRevision(card=card, **revision)
                        record.full_clean()
                        record.save()
                        CardRevision.objects.filter(pk=record.pk).update(created_at=revision_time)
                destination.mkdir(parents=True)
                owns_destination = True
                (destination / "original.pdf").write_bytes(contents["original.pdf"])
                for page in pages:
                    (destination / f"page-{page['number']:03}.png").write_bytes(
                        contents[f"pages/{page['number']}.png"]
                    )
            return lecture
    except Exception as exc:
        if (
            owns_destination
            and destination
            and destination.exists()
            and destination.resolve().is_relative_to(Path(settings.MEDIA_ROOT).resolve())
        ):
            shutil.rmtree(destination)
        if isinstance(exc, WorkflowError):
            raise
        raise WorkflowError(
            "This backup is invalid or incomplete. Existing lectures have not been changed."
        ) from exc
