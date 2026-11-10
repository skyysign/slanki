from pathlib import Path

from django.conf import settings


class WorkflowError(ValueError):
    """An error that can be shown to the user without exposing internals."""


class GenerationOutputError(WorkflowError):
    """A completed model response was unreadable; safe to retry within a fixed limit."""


def media_path(relative):
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise WorkflowError("Invalid media path.")
    return path
