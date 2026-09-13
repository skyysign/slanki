"""Delete set records atomically; finish only that set's files after commit."""

import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from converter.models import GenerationRun, Lecture, PendingFileDeletion


def cleanup_deleted_files(lecture_id):
    pending = PendingFileDeletion.objects.filter(pk=lecture_id).first()
    if pending is None:
        return True
    if Lecture.objects.filter(pk=lecture_id).exists():
        return False
    # Never follow a redirected directory or delete another set's source files.
    root = Path(settings.MEDIA_ROOT).resolve()
    folder = root / "documents" / str(pending.pk)
    try:
        if folder.resolve() != folder or not folder.is_relative_to(root):
            return False
        if folder.exists():
            shutil.rmtree(folder)
    except OSError:
        return False
    PendingFileDeletion.objects.filter(pk=pending.pk).delete()
    return True


def delete_lecture(lecture_id):
    from .occlusion_suggestions import suggestion_jobs

    with transaction.atomic():
        # Serialize deletion against generation saves/resume using a database write.
        GenerationRun.objects.filter(
            lecture_id=lecture_id, status__in=["queued", "running"]
        ).update(status="cancelled", worker_token=uuid.uuid4(), updated_at=timezone.now())
        lecture = Lecture.objects.filter(pk=lecture_id).first()
        if lecture is not None:
            PendingFileDeletion.objects.get_or_create(
                pk=lecture.pk, defaults={"title": lecture.title}
            )
            # Page references are protected, so remove the owned notes first.
            lecture.cards.all().delete()
            lecture.delete()
        # A failed cleanup keeps its marker, including across process restarts.
        # The library exposes a retry; the deleted PDF can already be imported anew.
        transaction.on_commit(lambda: cleanup_deleted_files(lecture_id))
        transaction.on_commit(lambda: suggestion_jobs.cancel_lecture(lecture_id))
