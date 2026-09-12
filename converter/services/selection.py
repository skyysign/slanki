"""Small, conservative content rules; no provider calls or semantic deletion."""

import re

from .cards import Draft, fingerprint, normalized, payload_items, update_card
from .files import WorkflowError
from .note_types import plain_questions, study_card_count


def default_card_limit(page_count):
    return max(1, (page_count + 1) // 2)


def checked_card_limit(value, page_count, *, card_format="basic"):
    minimum = 2 if card_format == "reversed" else 1
    if value in (None, ""):
        return max(minimum, default_card_limit(page_count))
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,3}", str(value)):
        raise WorkflowError("Choose a card limit from 1 to 500.")
    value = int(value)
    if not 1 <= value <= 500:
        raise WorkflowError("Choose a card limit from 1 to 500.")
    if value < minimum:
        raise WorkflowError(
            "Basic + reverse needs room for two cards. Set Maximum new cards to at least 2."
        )
    return value


def is_course_logistics(front, source_quote=""):
    question = normalized(front).casefold()
    context = question + " " + normalized(source_quote).casefold()
    # An examination can itself be course content (e.g. a clinical examination).
    if re.search(
        r"\b(?:clinical|physical|medical|neurological|patient|klinisch\w*|körperlich\w*|medizinisch\w*)\b",
        context,
    ):
        return False
    patterns = (
        r"\b(?:exam|examination|midterm)\s+(?:duration|date|location|format)\b",
        r"\b(?:prüfungs|pruefungs|klausur)(?:dauer|termin|ort|format)\b",
        r"^(?:how long|when|where|what (?:date|time|duration|format))\b.{0,55}\b(?:the|this|our|final|midterm|written|oral)\s+(?:exam|examination)\b",
        r"\b(?:exam|examination|midterm)\b.{0,35}\b(?:take place|scheduled|lasts?|start|end)\b",
        r"\b(?:materials|tools|aids|calculators|books|notes)\b.{0,55}\b(?:allowed|permitted)\b.{0,35}\bexam\b",
        r"\bwhat (?:material|topics|content|chapters)\b.{0,35}\bexam\b.{0,20}\bcover",
        r"\bexpected exam difficulty\b|\bhow difficult\b.{0,35}\b(?:the|this) exam\b",
        r"\b(?:course|exam|module)\b.{0,25}\b(?:graded|weighted|grading)\b",
        r"^(?:wie lange|wann|wo)\b.{0,45}\b(?:prüfung|pruefung|klausur)\w*\b",
        r"\b(?:hilfsmittel|materialien|themen|stoff)\b.{0,55}\b(?:prüfung|pruefung|klausur)\w*\b",
    )
    if any(re.search(pattern, question) for pattern in patterns):
        return True
    return bool(
        re.search(
            r"\b(?:office hours|sprechstunde\w*|course registration|course timetable|lecture schedule)\b"
            r"|\b(?:course|module|kurs|modul)\b.{0,40}\b(?:graded|grading|credits|ects|benotet|anmeldung)\b"
            r"|\b(?:email|e-mail|contact)\b.{0,35}\b(?:lecturer|instructor|professor|teaching assistant)\b",
            question,
        )
    )


def select_drafts(lecture, validated, limit=None):
    """Filter clear logistics, then keep unique drafts in the model's priority order."""
    seen = set(lecture.cards.values_list("fingerprint", flat=True))
    # An edited question may differ from its immutable generation fingerprint.
    seen.update(
        fingerprint(question)
        for front, back, kind in lecture.cards.values_list("front", "back", "note_type")
        for question in plain_questions(front, back, kind)
    )
    selected, filtered, over_limit = [], 0, 0
    selected_cards = 0
    for item in validated:
        page, front, back, quote, note_type = Draft(*item)
        questions = plain_questions(front, back, note_type)
        if any(is_course_logistics(question, quote) for question in questions):
            filtered += 1
            continue
        keys = {fingerprint(question) for question in questions}
        if keys & seen:
            continue
        count = study_card_count(front, note_type)
        if limit is not None and selected_cards + count > limit:
            over_limit += 1
        else:
            seen.update(keys)
            selected.append(item)
            selected_cards += count
    return selected, filtered, over_limit


def recent_questions(lecture):
    questions = []
    for front, back, kind in lecture.cards.order_by("-created_at").values_list(
        "front", "back", "note_type"
    )[:200]:
        questions.extend(plain_questions(front, back, kind))
    return questions[:200]


def logistics_drafts(lecture):
    return [
        card
        for card in lecture.cards.filter(status="draft", version=1)
        if any(
            is_course_logistics(question, card.source_quote)
            for question in plain_questions(card.front, card.back, card.note_type)
        )
    ]


def set_aside_logistics(lecture):
    count = 0
    for card in logistics_drafts(lecture):
        try:
            update_card(card.pk, card.version, card.front, card.back, card.source_quote, "rejected")
            count += 1
        except WorkflowError:
            # A concurrent edit takes precedence over automatic cleanup.
            continue
    return count


def filter_generated_logistics(payload):
    cards, filtered = [], 0
    for item in payload_items(payload):
        if (
            isinstance(item, dict)
            and isinstance(item.get("front"), str)
            and isinstance(item.get("back"), str)
            and isinstance(item.get("source_quote"), str)
            and any(
                is_course_logistics(question, item["source_quote"])
                for question in plain_questions(
                    item["front"], item["back"], item.get("note_type", "basic")
                )
            )
        ):
            filtered += 1
        else:
            cards.append(item)
    return {"cards": cards}, filtered
