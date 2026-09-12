"""Manual hide-one/reveal-one rectangles, rendered into bounded source PNGs."""

import hashlib
import io
import json

from PIL import Image, ImageDraw

from .crops import checked_crop
from .files import WorkflowError, media_path

MAX_MASKS = 20
MASK_COLOR = "#d9aa54"


def checked_occlusion(value, page, note_type="occlusion", source_crop=None):
    if note_type != "occlusion":
        if value != {}:
            raise WorkflowError("Only image occlusion notes can have a hidden region.")
        return {}
    if source_crop:
        raise WorkflowError("An image occlusion note uses its full source slide, without a crop.")
    if not isinstance(value, dict) or set(value) != {"page", "left", "top", "right", "bottom"}:
        raise WorkflowError("Draw a region to hide on this note's source slide.")
    rectangle = checked_crop({**value, "on_question": False}, page)
    rectangle.pop("on_question")
    return rectangle


def masks_from_form(values, page, *, single=False):
    raw = values.get("masks", "")
    if not isinstance(raw, str) or len(raw) > 8000:
        raise WorkflowError("Too many hidden regions. Add at most 20 at a time.")
    try:
        masks = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise WorkflowError("Draw at least one region to hide first.") from exc
    limit = 1 if single else MAX_MASKS
    if not isinstance(masks, list) or not 1 <= len(masks) <= limit:
        raise WorkflowError(f"Choose between 1 and {limit} hidden regions.")
    return [checked_occlusion(mask, page) for mask in masks]


def mask_fingerprint(page, mask):
    mask = checked_occlusion(mask, page)
    payload = json.dumps(["occlusion", str(page.lecture_id), mask], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def occlusion_png(page, mask, *, answer=False):
    mask = checked_occlusion(mask, page)
    try:
        with Image.open(media_path(page.image), formats=["PNG"]) as source:
            if source.size != (page.width, page.height) or not (
                0 < source.width <= 1500 and 0 < source.height <= 1500
            ):
                raise WorkflowError("The source image dimensions do not match the saved slide.")
            with source.convert("RGB") as image:
                # Coordinates use exclusive right/bottom edges, like source crops.
                box = (mask["left"], mask["top"], mask["right"] - 1, mask["bottom"] - 1)
                draw = ImageDraw.Draw(image)
                if answer:
                    # Outline outside the hidden region so even tiny answers remain visible.
                    left, top, right, bottom = box
                    draw.rectangle(
                        (left - 2, top - 2, right + 2, bottom + 2), outline="#247c57", width=2
                    )
                else:
                    draw.rectangle(box, fill=MASK_COLOR)
                output = io.BytesIO()
                image.save(output, format="PNG")
                return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, WorkflowError):
            raise
        raise WorkflowError(
            "Could not read this source image. Restore a backup before masking."
        ) from exc


def add_occlusions(lecture, page, front, back, masks):
    # Imports stay local to avoid a cycle with shared note validation.
    from django.db import transaction

    from converter.models import Card

    from .cards import validate_content

    if page.lecture_id != lecture.pk:
        raise WorkflowError("Choose a source page from this lecture.")
    if not isinstance(masks, list) or not 1 <= len(masks) <= MAX_MASKS:
        raise WorkflowError("Choose between 1 and 20 hidden regions.")
    front, back, _ = validate_content(front, back, "", page, note_type="occlusion")
    masks = [checked_occlusion(mask, page) for mask in masks]
    # Verify the source before saving; never leave half a submitted batch behind.
    occlusion_png(page, masks[0])
    saved = []
    with transaction.atomic():
        existing = {
            mask_fingerprint(page, card.occlusion)
            for card in lecture.cards.filter(page=page, note_type="occlusion")
        }
        for mask in masks:
            key = mask_fingerprint(page, mask)
            if key in existing:
                continue
            card, created = Card.objects.get_or_create(
                lecture=lecture,
                fingerprint=key,
                defaults={
                    "page": page,
                    "front": front,
                    "back": back,
                    "note_type": "occlusion",
                    "occlusion": mask,
                },
            )
            existing.add(key)
            if created:
                saved.append(card)
    return saved
