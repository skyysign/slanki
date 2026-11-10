"""Supported note formats and actual Anki card counts; no HTML from users."""

import html
import re

from .files import WorkflowError

TEXT_NOTE_TYPES = [("basic", "Basic Q/A"), ("cloze", "Cloze"), ("reversed", "Basic + reverse")]
MANUAL_NOTE_TYPES = TEXT_NOTE_TYPES + [("visual", "Graph / formula question")]
NOTE_TYPES = MANUAL_NOTE_TYPES + [("occlusion", "Image occlusion")]
# Keep the original mixed value limited to Q/A + cloze for saved runs/backups.
FORMAT_TYPES = {
    "basic": ("basic",),
    "cloze": ("cloze",),
    "reversed": ("reversed",),
    "mixed": ("basic", "cloze"),
    "basic_reversed": ("basic", "reversed"),
    "cloze_reversed": ("cloze", "reversed"),
    "all": ("basic", "cloze", "reversed"),
}
CARD_FORMATS = TEXT_NOTE_TYPES + [
    ("mixed", "Mixed Q/A and cloze"),
    ("basic_reversed", "Q/A and reverse"),
    ("cloze_reversed", "Cloze and reverse"),
    ("all", "Q/A, cloze and reverse"),
]
LEARNING_FOCUSES = [
    ("balanced", "Balanced"),
    ("core", "Core knowledge"),
    ("understanding", "Understanding"),
    ("application", "Application"),
]
FOCUS_INSTRUCTIONS = {
    "balanced": "Balance core knowledge, explanations, distinctions, and applications according to the supplied material.",
    "core": "Prioritize essential definitions, terminology, key facts, and formulas with their meaning and conditions.",
    "understanding": "Prioritize why and how, causal explanations, connections, and distinctions between similar concepts. For cloze, hide a meaningful part of an explanation rather than isolated trivia.",
    "application": "Prioritize when to choose a method, how to apply a procedure, and the reasoning in supplied worked examples. Do not invent exercises, numerical data, solutions, or prerequisites absent from the source.",
}
CLOZE = re.compile(r"{{c([1-9]|1[0-9]|20)::([^{}]+)}}")


def checked_choice(value, choices, label):
    if not isinstance(value, str) or value not in dict(choices):
        raise WorkflowError(f"Choose a supported {label}.")
    return value


def format_types(card_format):
    checked_choice(card_format, CARD_FORMATS, "card format")
    return FORMAT_TYPES[card_format]


def format_from_types(types):
    if not types or len(types) != len(set(types)):
        raise WorkflowError("Tick at least one card format, without duplicate choices.")
    for value, members in FORMAT_TYPES.items():
        if set(types) == set(members):
            return value
    raise WorkflowError("Tick only supported card formats.")


def cloze_matches(text):
    matches = list(CLOZE.finditer(text))
    remainder = CLOZE.sub("", text)
    if not matches or "{{" in remainder or "}}" in remainder:
        raise WorkflowError(
            "Use flat clozes such as {{c1::answer}} or {{c2::answer::hint}}, numbered 1–20. Nested or incomplete clozes are not supported."
        )
    for match in matches:
        answer, _, hint = match[2].partition("::")
        if not answer.strip() or "::" in hint:
            raise WorkflowError("Each cloze needs a nonempty answer and at most one hint.")
    return matches


def study_card_count(front, note_type="basic"):
    checked_choice(note_type, NOTE_TYPES, "note format")
    if note_type in ("basic", "occlusion", "visual"):
        return 1
    if note_type == "reversed":
        return 2
    return len({int(match[1]) for match in cloze_matches(front)})


def plain_front(front, note_type="basic"):
    if note_type == "cloze":
        return CLOZE.sub(lambda match: match[2].split("::", 1)[0], front)
    return front


def plain_questions(front, back, note_type="basic"):
    if note_type == "occlusion":
        return ()
    return (front, back) if note_type == "reversed" else (plain_front(front, note_type),)


def text_html(text):
    return html.escape(text).replace("\n", "<br>")


def study_previews(front, back, note_type="basic"):
    """Escaped question/answer HTML for exactly the ordinals exported to Anki."""
    study_card_count(front, note_type)
    if note_type in ("basic", "occlusion", "visual"):
        return [{"number": 1, "question": text_html(front), "answer": text_html(back)}]
    if note_type == "reversed":
        return [
            {
                "number": 1,
                "direction": "Front → back",
                "question": text_html(front),
                "answer": text_html(back),
            },
            {
                "number": 2,
                "direction": "Back → front",
                "question": text_html(back),
                "answer": text_html(front),
            },
        ]
    matches = cloze_matches(front)
    previews = []
    for number in sorted({int(match[1]) for match in matches}):

        def render(reveal):
            chunks, end = [], 0
            for match in matches:
                chunks.append(text_html(front[end : match.start()]))
                answer, _, hint = match[2].partition("::")
                if int(match[1]) == number:
                    value = answer if reveal else f"[{hint or '...'}]"
                    chunks.append(f'<span class="cloze">{text_html(value)}</span>')
                else:
                    chunks.append(text_html(answer))
                end = match.end()
            chunks.append(text_html(front[end:]))
            return "".join(chunks)

        previews.append(
            {
                "number": number,
                "question": render(False),
                "answer": render(True) + ("<hr>" + text_html(back) if back else ""),
            }
        )
    return previews
