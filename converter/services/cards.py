import hashlib
import unicodedata

from django.db import transaction
from django.utils import timezone

from converter.models import Card, CardRevision

from .files import WorkflowError


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def fingerprint(front):
    return hashlib.sha256(normalized(front).casefold().encode()).hexdigest()


def validate_content(front, back, quote, page, require_quote=False):
    for label, value, limit in [
        ("Question", front, 1000),
        ("Answer", back, 5000),
        ("Source excerpt", quote, 2500),
    ]:
        if not isinstance(value, str) or len(value) > limit or "\x00" in value:
            raise WorkflowError(f"{label} is invalid or too long.")
    if not front.strip() or not back.strip():
        raise WorkflowError("Both a question and an answer are required.")
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


def validate_item(item, pages, index):
    if not isinstance(item, dict) or set(item) != {"front", "back", "page", "source_quote"}:
        raise WorkflowError(f"Card {index} must contain front, back, page and source_quote.")
    if type(item["page"]) is not int or item["page"] not in pages:
        raise WorkflowError(f"Card {index} refers to a page outside the selected lecture pages.")
    page = pages[item["page"]]
    front, back, quote = validate_content(
        item["front"], item["back"], item["source_quote"], page, require_quote=True
    )
    return page, front, back, quote


def validate_payload(payload, pages):
    # Explicit file imports remain atomic: show an error so the file can be corrected.
    return [validate_item(item, pages, i) for i, item in enumerate(payload_items(payload), 1)]


def validate_generated_batch(payload, pages):
    """Keep good drafts and report individual failures without trusting bad source links."""
    validated, issues = [], []
    for index, item in enumerate(payload_items(payload), 1):
        try:
            validated.append(validate_item(item, pages, index))
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
        for page, front, back, quote in validated:
            _, created = Card.objects.get_or_create(
                lecture=lecture,
                fingerprint=fingerprint(front),
                defaults={
                    "page": page,
                    "front": front,
                    "back": back,
                    "source_quote": quote,
                    "run": run,
                },
            )
            count += created
    return count


def update_card(card_id, version, front, back, source_quote, status):
    if status not in dict(Card.STATUS):
        raise WorkflowError("Choose a valid card status.")
    with transaction.atomic():
        card = Card.objects.select_related("page").get(pk=card_id)
        front, back, quote = validate_content(front, back, source_quote, card.page)
        if card.version != version:
            raise WorkflowError(
                "This card changed in another tab. Reload before saving to avoid losing edits."
            )
        changed = Card.objects.filter(pk=card_id, version=version).update(
            front=front,
            back=back,
            source_quote=quote,
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
            status=card.status,
        )
    return Card.objects.get(pk=card_id)
