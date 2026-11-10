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

from converter.models import (
    Card,
    CardRevision,
    GenerationRun,
    Lecture,
    OcclusionSuggestion,
    Page,
    PendingFileDeletion,
)

from .cards import validate_content
from .crops import checked_crop
from .files import WorkflowError, media_path
from .lecture_context import checked_context
from .occlusion import checked_occlusion
from .occlusion_review import validate_saved_suggestion
from .providers import checked_model_id
from .rundown import checked_rundown
from .visual_cards import checked_visual_masks

MAX_BACKUP_BYTES = 200 * 1024 * 1024


def suggestion_records(run):
    records = []
    for suggestion in run.suggestions.select_related("page", "card", "run"):
        validate_saved_suggestion(suggestion)
        records.append(
            {
                "id": str(suggestion.pk),
                "page": suggestion.page.number,
                "label": suggestion.label,
                "reason": suggestion.reason,
                "original_mask": suggestion.original_mask,
                "mask": suggestion.mask,
                "front": suggestion.front,
                "back": suggestion.back,
                "status": suggestion.status,
                "version": suggestion.version,
                "card": str(suggestion.card_id) if suggestion.card_id else None,
                "created_at": suggestion.created_at.isoformat(),
            }
        )
    return records


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
        "version": 12,
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
                "note_type": c.note_type,
                "back": c.back,
                "source_quote": c.source_quote,
                "source_crop": checked_crop(c.source_crop, c.page),
                "occlusion": checked_occlusion(c.occlusion, c.page, c.note_type, c.source_crop),
                "visual_masks": checked_visual_masks(c.visual_masks, c.page, c.note_type),
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
                        "note_type": r.note_type,
                        "visual_masks": checked_visual_masks(r.visual_masks, c.page, r.note_type),
                        "back": r.back,
                        "source_quote": r.source_quote,
                        "source_crop": checked_crop(r.source_crop, c.page),
                        "occlusion": checked_occlusion(
                            r.occlusion, c.page, r.note_type, r.source_crop
                        ),
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
                "model": r.model,
                "page_numbers": r.page_numbers,
                "completed_pages": r.completed_pages,
                "context_enabled": r.context_enabled,
                "context_data": checked_context(r.context_data, r.context_enabled, lecture, pages),
                "text_enabled": r.text_enabled,
                "occlusion_enabled": r.occlusion_enabled,
                "visual_enabled": r.visual_enabled,
                "purpose": r.purpose,
                "rundown_data": checked_rundown(
                    r.rundown_data,
                    r.purpose,
                    lecture,
                    [p for p in pages if p.number in r.page_numbers],
                    r.completed_pages,
                )
                if r.purpose == "rundown"
                else {},
                "image_completed_pages": r.image_completed_pages,
                "suggestions": suggestion_records(r),
                "issues": r.issues,
                "cards_added": r.cards_added,
                "study_cards_added": r.study_cards_added,
                "learning_focus": r.learning_focus,
                "card_format": r.card_format,
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
                or manifest["version"] not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
            ):
                raise WorkflowError("This is not a supported Recalloom backup.")
            info = manifest["lecture"]
            require_keys(info, "id title sha256 original_name created_at")
            lecture_id = uuid.UUID(info["id"])
            if PendingFileDeletion.objects.filter(pk=lecture_id).exists():
                raise WorkflowError(
                    "Finish this set's pending file cleanup in the library before restoring it."
                )
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
                saved_suggestions = []
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
                        + (" reasoning_effort" if manifest["version"] >= 4 else "")
                        + (
                            " study_cards_added learning_focus card_format"
                            if manifest["version"] >= 5
                            else ""
                        )
                        + (" model" if manifest["version"] >= 7 else "")
                        + (" context_enabled context_data" if manifest["version"] >= 10 else "")
                        + (
                            " text_enabled occlusion_enabled image_completed_pages suggestions"
                            if manifest["version"] >= 11
                            else ""
                        )
                        + (
                            " visual_enabled purpose rundown_data"
                            if manifest["version"] >= 12
                            else ""
                        ),
                    )
                    r = dict(r)
                    r.setdefault("model", "")
                    r.setdefault("context_enabled", False)
                    r.setdefault("context_data", {})
                    r.setdefault("visual_enabled", False)
                    r.setdefault("purpose", "cards")
                    r.setdefault("rundown_data", {})
                    r.setdefault("text_enabled", True)
                    r.setdefault("occlusion_enabled", False)
                    r.setdefault("image_completed_pages", [])
                    proposals = r.pop("suggestions", [])
                    if not isinstance(proposals, list) or len(proposals) > 600:
                        raise WorkflowError("Backup contains too many image suggestions.")
                    if (
                        type(r["text_enabled"]) is not bool
                        or type(r["occlusion_enabled"]) is not bool
                        or type(r["visual_enabled"]) is not bool
                        or not (r["text_enabled"] or r["occlusion_enabled"] or r["visual_enabled"])
                        or (r["occlusion_enabled"] and r["visual_enabled"])
                        or (
                            (r["occlusion_enabled"] or r["visual_enabled"])
                            and r["provider"] != "codex"
                        )
                        or (
                            (not r["occlusion_enabled"] and proposals)
                            or (
                                not (r["occlusion_enabled"] or r["visual_enabled"])
                                and r["image_completed_pages"]
                            )
                        )
                    ):
                        raise WorkflowError("Backup has invalid image generation settings.")
                    checked_context(
                        r["context_data"], r["context_enabled"], lecture, list(page_map.values())
                    )
                    checked_model_id(r["model"])
                    r.setdefault("issues", [])
                    if manifest["version"] < 5:
                        r["study_cards_added"] = r["cards_added"]
                    if r.get("card_limit") is not None and (
                        type(r["card_limit"]) is not int or not 1 <= r["card_limit"] <= 500
                    ):
                        raise WorkflowError("Backup contains an invalid card limit.")
                    validate_run_pages(r["page_numbers"], page_map)
                    validate_run_pages(r["completed_pages"], r["page_numbers"])
                    validate_run_pages(r["image_completed_pages"], r["page_numbers"])
                    if (r["occlusion_enabled"] or r["visual_enabled"]) and (
                        r.get("card_limit") is None
                        or len(proposals) + r.get("study_cards_added", 0) > r["card_limit"]
                    ):
                        raise WorkflowError("Backup image proposals exceed their run's card limit.")
                    if r["purpose"] not in ("cards", "rundown") or (
                        r["purpose"] == "rundown"
                        and (
                            r["occlusion_enabled"]
                            or r["visual_enabled"]
                            or r["context_enabled"]
                            or r["cards_added"]
                            or r["study_cards_added"]
                        )
                    ):
                        raise WorkflowError("Invalid lecture rundown settings in backup.")
                    checked_rundown(
                        r["rundown_data"],
                        r["purpose"],
                        lecture,
                        [p for p in page_map.values() if p.number in r["page_numbers"]],
                        r["completed_pages"] if r["purpose"] == "rundown" else [],
                    )
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
                    saved_suggestions.append((run, proposals))
                    run_ids.add(str(run.pk))
                    GenerationRun.objects.filter(pk=run.pk).update(
                        created_at=created, updated_at=updated
                    )
                for c in manifest["cards"]:
                    require_keys(
                        c,
                        "id page front back source_quote status fingerprint version anki_modified run created_at updated_at revisions"
                        + (" note_type" if manifest["version"] >= 5 else "")
                        + (" source_crop" if manifest["version"] >= 6 else "")
                        + (" occlusion" if manifest["version"] >= 9 else "")
                        + (" visual_masks" if manifest["version"] >= 12 else ""),
                    )
                    c = dict(c)
                    c.setdefault("note_type", "basic")
                    page = page_map[c.pop("page")]
                    c["visual_masks"] = checked_visual_masks(
                        c.get("visual_masks", []), page, c["note_type"]
                    )
                    c["source_crop"] = checked_crop(c.get("source_crop", {}), page)
                    c["occlusion"] = checked_occlusion(
                        c.get("occlusion", {}), page, c["note_type"], c["source_crop"]
                    )
                    revisions = c.pop("revisions")
                    created, updated = (
                        timestamp(c.pop("created_at")),
                        timestamp(c.pop("updated_at")),
                    )
                    run_id = c.pop("run")
                    if run_id and run_id not in run_ids:
                        raise WorkflowError("Backup has an invalid generation reference.")
                    validate_content(
                        c["front"], c["back"], c["source_quote"], page, note_type=c["note_type"]
                    )
                    card = Card(lecture=lecture, page=page, run_id=run_id, **c)
                    card.full_clean()
                    card.save(force_insert=True)
                    Card.objects.filter(pk=card.pk).update(created_at=created, updated_at=updated)
                    if len(revisions) > 1000:
                        raise WorkflowError("Backup contains too many card revisions.")
                    for revision in revisions:
                        require_keys(
                            revision,
                            "version front back source_quote status created_at"
                            + (" note_type" if manifest["version"] >= 5 else "")
                            + (" source_crop" if manifest["version"] >= 6 else "")
                            + (" occlusion" if manifest["version"] >= 9 else "")
                            + (" visual_masks" if manifest["version"] >= 12 else ""),
                        )
                        revision = dict(revision)
                        revision["source_crop"] = checked_crop(
                            revision.get("source_crop", {}), page
                        )
                        revision.setdefault("note_type", "basic")
                        revision["visual_masks"] = checked_visual_masks(
                            revision.get("visual_masks", []), page, revision["note_type"]
                        )
                        revision["occlusion"] = checked_occlusion(
                            revision.get("occlusion", {}),
                            page,
                            revision["note_type"],
                            revision["source_crop"],
                        )
                        validate_content(
                            revision["front"],
                            revision["back"],
                            revision["source_quote"],
                            page,
                            note_type=revision["note_type"],
                        )
                        revision_time = timestamp(revision.pop("created_at"))
                        record = CardRevision(card=card, **revision)
                        record.full_clean()
                        record.save()
                        CardRevision.objects.filter(pk=record.pk).update(created_at=revision_time)
                for run, proposals in saved_suggestions:
                    for record in proposals:
                        require_keys(
                            record,
                            "id page label reason original_mask mask front back status version card created_at",
                        )
                        values = dict(record)
                        page = page_map[values.pop("page")]
                        created = timestamp(values.pop("created_at"))
                        card_id = values.pop("card")
                        card = lecture.cards.get(pk=card_id) if card_id else None
                        suggestion = OcclusionSuggestion(run=run, page=page, card=card, **values)
                        validate_saved_suggestion(suggestion)
                        suggestion.full_clean()
                        suggestion.save(force_insert=True)
                        OcclusionSuggestion.objects.filter(pk=suggestion.pk).update(
                            created_at=created
                        )
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
