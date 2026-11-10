"""Persisted image proposals. Only a review action creates an accepted Anki note."""

from django.db import transaction
from django.db.models import Q

from converter.models import OcclusionSuggestion

from .cards import update_card, validate_content
from .files import WorkflowError
from .occlusion import add_occlusions, checked_occlusion, mask_fingerprint, occlusion_png


def validate_saved_suggestion(suggestion):
    if (
        not suggestion.run.occlusion_enabled
        or suggestion.page.lecture_id != suggestion.run.lecture_id
        or suggestion.page.number not in suggestion.run.image_completed_pages
    ):
        raise WorkflowError("An image suggestion has an invalid source page or run.")
    for value, maximum in ((suggestion.label, 120), (suggestion.reason, 300)):
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > maximum
            or "\x00" in value
        ):
            raise WorkflowError("An image suggestion has an invalid description.")
    checked_occlusion(suggestion.original_mask, suggestion.page)
    checked_occlusion(suggestion.mask, suggestion.page)
    validate_content(suggestion.front, suggestion.back, "", suggestion.page, note_type="occlusion")
    if (
        suggestion.status not in dict(OcclusionSuggestion.STATUS)
        or type(suggestion.version) is not int
        or suggestion.version < 1
    ):
        raise WorkflowError("An image suggestion has an invalid review state.")
    if (suggestion.status == "accepted") != bool(suggestion.card_id):
        raise WorkflowError("An image suggestion has an invalid saved-card reference.")
    if suggestion.card_id and (
        suggestion.card.lecture_id != suggestion.run.lecture_id
        or suggestion.card.page_id != suggestion.page_id
        or suggestion.card.note_type != "occlusion"
    ):
        raise WorkflowError("An image suggestion references an unrelated card.")


def existing_region_keys(lecture):
    keys = set()
    for card in lecture.cards.filter(note_type="occlusion").select_related("page"):
        keys.update([card.fingerprint, mask_fingerprint(card.page, card.occlusion)])
    for suggestion in OcclusionSuggestion.objects.filter(run__lecture=lecture).select_related(
        "page"
    ):
        keys.update(
            mask_fingerprint(suggestion.page, mask)
            for mask in (suggestion.original_mask, suggestion.mask)
        )
    return keys


def save_suggestions(run, page, suggestions, limit):
    # Called under the generation worker's transaction/write lock. Include reviewed
    # and edited regions so retries or later runs never overwrite a user's choices.
    seen = existing_region_keys(run.lecture)
    added = excluded = 0
    for suggestion in suggestions:
        mask = suggestion["mask"]
        key = mask_fingerprint(page, mask)
        if key in seen:
            continue
        seen.add(key)
        if added >= limit:
            excluded += 1
            continue
        OcclusionSuggestion.objects.create(
            run=run,
            page=page,
            label=suggestion["label"],
            reason=suggestion["reason"],
            original_mask=mask,
            mask=mask,
        )
        added += 1
    return excluded


@transaction.atomic
def review_suggestion(suggestion_id, version, action, *, front=None, back=None, mask=None):
    suggestion = OcclusionSuggestion.objects.select_related("page", "run__lecture").get(
        pk=suggestion_id
    )
    if action not in ("save", "accept", "discard", "restore"):
        raise WorkflowError("Choose a valid suggestion action.")
    if suggestion.version != version:
        raise WorkflowError("This suggestion changed in another tab. Reload before saving.")
    if suggestion.status == "accepted":
        raise WorkflowError(
            "This suggestion has already been reviewed. Edit its saved card instead."
        )
    if (action == "restore") != (suggestion.status == "discarded"):
        raise WorkflowError("Restore a discarded suggestion before editing or accepting it.")
    values = {"version": version + 1}
    if action in ("save", "accept"):
        front, back, _ = validate_content(front, back, "", suggestion.page, note_type="occlusion")
        mask = checked_occlusion(mask, suggestion.page)
        occlusion_png(suggestion.page, mask)
        values.update(front=front, back=back, mask=mask)
    values["status"] = {
        "save": "pending",
        "accept": "accepted",
        "discard": "discarded",
        "restore": "pending",
    }[action]
    # Acquire the write lock with optimistic version checking before any card write.
    if not OcclusionSuggestion.objects.filter(pk=suggestion_id, version=version).update(**values):
        raise WorkflowError("This suggestion changed in another tab. Reload before saving.")
    if action == "accept":
        lecture = suggestion.run.lecture
        cards = add_occlusions(lecture, suggestion.page, front, back, [mask])
        if cards:
            card = cards[0]
            card.run = suggestion.run
            card.save(update_fields=["run"])
            card = update_card(card.pk, card.version, front, back, "", "accepted")
        else:
            # Exact duplicate submissions reuse a note without changing its edits or status.
            card = (
                lecture.cards.filter(page=suggestion.page, note_type="occlusion")
                .filter(Q(fingerprint=mask_fingerprint(suggestion.page, mask)) | Q(occlusion=mask))
                .first()
            )
            if card is None:
                raise WorkflowError(
                    "Could not find the existing region. Reload before trying again."
                )
        OcclusionSuggestion.objects.filter(pk=suggestion_id).update(card=card)
    return OcclusionSuggestion.objects.select_related("card").get(pk=suggestion_id)
