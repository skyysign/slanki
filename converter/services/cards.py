import hashlib
import unicodedata
from typing import NamedTuple

from django.db import transaction
from django.utils import timezone

from converter.models import Card, CardRevision, Page

from .crops import checked_crop
from .files import WorkflowError
from .note_types import format_types, plain_front, study_card_count
from .occlusion import checked_occlusion, occlusion_png


class Draft(NamedTuple):
    page: Page
    front: str
    back: str
    source_quote: str
    note_type: str = "basic"


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def fingerprint(front, note_type="basic"):
    front = plain_front(front, note_type)
    return hashlib.sha256(normalized(front).casefold().encode()).hexdigest()


def validate_content(front, back, quote, page, require_quote=False, note_type="basic"):
    for label, value, limit in [
        ("Question", front, 1000),
        ("Answer", back, 5000),
        ("Source excerpt", quote, 2500),
    ]:
        if not isinstance(value, str) or len(value) > limit or "\x00" in value:
            raise WorkflowError(f"{label} is invalid or too long.")
    study_card_count(front, note_type)
    if not front.strip() or (note_type not in ("cloze", "occlusion") and not back.strip()):
        raise WorkflowError("Both a question and an answer are required.")
    if note_type == "reversed" and normalized(front).casefold() == normalized(back).casefold():
        raise WorkflowError("Use different text on the two sides of a reverse note.")
    if require_quote and not quote.strip():
        raise WorkflowError("Each generated card needs an exact supporting source excerpt.")
    if quote.strip() and normalized(quote) not in normalized(page.text):
        raise WorkflowError(
            f"The source excerpt is not present on page {page.number}. Check the page and excerpt."
        )
    return front.strip(), back.strip(), quote.strip()


def payload_items(payload):
    if (
        not isinstance(payload, dict)
        or set(payload) != {"cards"}
        or not isinstance(payload["cards"], list)
    ):
        raise WorkflowError('Expected a JSON object containing a "cards" array.')
    if len(payload["cards"]) > 500:
        raise WorkflowError("Import at most 500 draft cards at a time.")
    return payload["cards"]


def validate_item(item, pages, index, card_format="all"):
    required = {"front", "back", "page", "source_quote"}
    if not isinstance(item, dict) or set(item) not in (required, required | {"note_type"}):
        raise WorkflowError(f"Card {index} must contain front, back, page and source_quote.")
    if type(item["page"]) is not int or item["page"] not in pages:
        raise WorkflowError(f"Card {index} refers to a page outside the selected lecture pages.")
    page = pages[item["page"]]
    note_type = item.get("note_type", "basic")
    if note_type not in format_types(card_format):
        raise WorkflowError(f"Card {index} does not use the requested {card_format} format.")
    front, back, quote = validate_content(
        item["front"],
        item["back"],
        item["source_quote"],
        page,
        require_quote=True,
        note_type=note_type,
    )
    return Draft(page, front, back, quote, note_type)


def validate_payload(payload, pages):
    # Explicit file imports remain atomic: show an error so the file can be corrected.
    return [validate_item(item, pages, i) for i, item in enumerate(payload_items(payload), 1)]


def validate_generated_batch(payload, pages, card_format="mixed"):
    """Keep good drafts and report individual failures without trusting bad source links."""
    validated, issues = [], []
    for index, item in enumerate(payload_items(payload), 1):
        try:
            validated.append(validate_item(item, pages, index, card_format))
        except WorkflowError as exc:
            data = item if isinstance(item, dict) else {}
            number = data.get("page")
            issue = {
                "page": number if type(number) is int and number in pages else None,
                "batch_pages": list(pages),
                "reason": str(exc),
            }
            # Invalid output is retained for inspection only, with bounded display fields.
            for key, limit in [("front", 1000), ("back", 5000), ("source_quote", 2500)]:
                value = data.get(key)
                issue[key] = value[:limit].replace("\x00", "") if isinstance(value, str) else ""
            issues.append(issue)
    return validated, issues


def add_drafts(lecture, validated, run=None):
    count = 0
    with transaction.atomic():
        for item in validated:
            page, front, back, quote, note_type = Draft(*item)
            if note_type == "occlusion":
                raise WorkflowError("Use the image occlusion editor to add a hidden region.")
            validate_content(front, back, quote, page, note_type=note_type)
            _, created = Card.objects.get_or_create(
                lecture=lecture,
                fingerprint=fingerprint(front, note_type),
                defaults={
                    "page": page,
                    "front": front,
                    "back": back,
                    "source_quote": quote,
                    "note_type": note_type,
                    "run": run,
                },
            )
            count += created
    return count


def update_card(
    card_id, version, front, back, source_quote, status, *, source_crop=None, occlusion=None
):
    if status not in dict(Card.STATUS):
        raise WorkflowError("Choose a valid card status.")
    with transaction.atomic():
        card = Card.objects.select_related("page").get(pk=card_id)
        crop = checked_crop(card.source_crop if source_crop is None else source_crop, card.page)
        mask = checked_occlusion(
            card.occlusion if occlusion is None else occlusion, card.page, card.note_type, crop
        )
        if mask:
            occlusion_png(card.page, mask)
        front, back, quote = validate_content(
            front, back, source_quote, card.page, note_type=card.note_type
        )
        # Keep cloze ordinals stable: they identify separately scheduled Anki cards.
        # Changing a note's type or adding/removing cloze numbers needs a separate
        # explicit migration workflow; ordinary text edits must not reset reviews.
        if card.note_type == "cloze":
            from .note_types import cloze_matches

            if {m[1] for m in cloze_matches(front)} != {m[1] for m in cloze_matches(card.front)}:
                raise WorkflowError(
                    "Keep this note's existing cloze numbers when editing. Create a new note for a different set of blanks."
                )
        if card.version != version:
            raise WorkflowError(
                "This card changed in another tab. Reload before saving to avoid losing edits."
            )
        changed = Card.objects.filter(pk=card_id, version=version).update(
            front=front,
            back=back,
            source_quote=quote,
            source_crop=crop,
            occlusion=mask,
            status=status,
            version=version + 1,
            updated_at=timezone.now(),
            anki_modified=max(int(timezone.now().timestamp()), card.anki_modified + 1),
        )
        if not changed:
            raise WorkflowError("This card changed in another tab. Reload before saving.")
        CardRevision.objects.create(
            card=card,
            version=version,
            front=card.front,
            back=card.back,
            source_quote=card.source_quote,
            source_crop=card.source_crop,
            occlusion=card.occlusion,
            status=card.status,
            note_type=card.note_type,
        )
    return Card.objects.get(pk=card_id)
