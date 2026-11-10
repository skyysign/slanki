"""Freeze reference behaviour of the Recalloom Django edition for the Slanki port.

Run once from the repository root with the Django edition's environment:

    .venv\\Scripts\\python.exe tools/golden.py

It works in an isolated temporary data directory, mocks every model call, and
writes tests/fixtures/synthetic/golden/. The outputs are frozen fixtures: note
IDs and timestamps are random, so regenerate only deliberately and review the
diff. Real lectures are never read.
"""

import copy
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "synthetic"
OUT = FIXTURES / "golden"
TITLE = 'Golden "Memory" & <learning> :: sample'

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def write_json(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def outcome(function, *args, **kwargs):
    from converter.services.files import GenerationOutputError, WorkflowError

    try:
        return {"ok": function(*args, **kwargs)}
    except GenerationOutputError as exc:
        return {"output_error": str(exc)}
    except WorkflowError as exc:
        return {"error": str(exc)}


def page(number, text, warning="", width=1500, height=844):
    return SimpleNamespace(number=number, text=text, warning=warning, width=width, height=height)


# ---------------------------------------------------------------------------
# Unicode and text rules


SAMPLES = [
    "What is retrieval practice?",
    "  Leading and trailing  ",
    "Straße",
    "STRASSE",
    "ẞ capital sharp s",
    "ﬁnance ﬂow ﬀ",
    "ΣΊΣΥΦΟΣ and σίσυφος and ς",
    "İstanbul and ı",
    "ǅ ǈ ǋ",
    "Ⅻ ⅻ ① ²",
    "𝑥² + 𝑦² = 𝑟²",
    "x y z w",
    "a\x1cb\x1dc\x1ed\x1fe",
    "a\x85b",
    "a﻿b",
    "a​b",
    "tab\tnew\nline\r\nend\x0bv\x0cf",
    "é vs é",
    "Ｆｕｌｌｗｉｄｔｈ ＡＢＣ",
    "µ vs μ",
    "K Kelvin",
    "ſ long s",
    "ΐ ŉ ǰ",
    "Ꭰ Ꮿ ꭰ",
    "😀 emoji 👩‍🔬",
    " line para",
    "　ideographic　",
    "᠎mongolian",
    "Wie lange dauert die Prüfung?",
    "körperliche Untersuchung",
    "",
    "   ",
]

CLOZE_FRONTS = [
    "Retrieval practice means trying to {{c1::recall}} information from {{c2::memory::where?}}.",
    "{{c1::A}} and {{c1::B}} together, then {{c3::C}}.",
    "{{c20::twenty}} is the highest.",
    "{{c21::too high}}",
    "{{c0::zero}}",
    "No cloze here.",
    "{{c1::outer {{c2::inner}}}}",
    "{{c1::}}",
    "{{c1:: }}",
    "{{c1::answer::hint::extra}}",
    "Unclosed {{c1::answer",
    "Stray }} brace {{c1::ok}}",
    "{{c1::a::}} empty hint",
    "Escaped <b>&amp;</b> {{c1::x < y}} and\nnewline",
    "{{C1::capital}}",
    "{{c01::leading zero}}",
    "{{c1::𝑥²}} astral",
]

LOGISTICS = [
    ("How long is the exam?", ""),
    ("When is the final exam scheduled?", ""),
    ("What is the exam duration?", ""),
    ("Where does the midterm take place?", ""),
    ("Which materials are allowed in the exam?", ""),
    ("Are calculators permitted during the exam?", ""),
    ("What topics will the exam cover?", ""),
    ("How difficult is the exam?", ""),
    ("How is the course graded?", ""),
    ("When are the office hours?", ""),
    ("How do I email the lecturer?", ""),
    ("What does a clinical examination include?", ""),
    ("What is a physical examination?", ""),
    ("What is bond duration?", "Duration measures interest-rate sensitivity."),
    ("How long does a neurological exam take?", ""),
    ("Wie lange dauert die Klausur?", ""),
    ("Wann ist die Prüfung?", ""),
    ("Welche Hilfsmittel sind in der Prüfung erlaubt?", ""),
    ("Was ist die Prüfungsdauer?", ""),
    ("Wann ist die Sprechstunde?", ""),
    ("Wie wird das Modul benotet?", ""),
    ("Was umfasst eine körperliche Untersuchung?", "Prüfung des Patienten"),
    ("What is retrieval practice?", "Retrieval practice means trying to recall."),
    ("EXAM DATE for the course?", ""),
    ("Is the exam   format oral?", ""),
    ("When does the examination start?", ""),
    ("What is the expected exam difficulty?", ""),
    ("How many ECTS credits does the module give?", ""),
    ("Explain the Prüfungsordnung", ""),
    ("Stoff der Klausur?", ""),
]


def unicode_tables():
    space = [cp for cp in range(0x110000) if chr(cp).isspace()]
    casefold = [
        [cp, chr(cp).casefold()]
        for cp in range(0x110000)
        if not 0xD800 <= cp <= 0xDFFF and chr(cp).casefold() != chr(cp)
    ]
    word = re.compile(r"\w")
    ranges, start = [], None
    for cp in range(0x110001):
        inside = cp < 0x110000 and not 0xD800 <= cp <= 0xDFFF and word.match(chr(cp)) is not None
        if inside and start is None:
            start = cp
        elif not inside and start is not None:
            ranges.append([start, cp - 1])
            start = None
    return {
        "python": sys.version.split()[0],
        "unidata_version": unicodedata.unidata_version,
        "space": space,
        "casefold": casefold,
        "word_ranges": ranges,
    }


def text_vectors():
    import genanki

    from converter.services.cards import fingerprint, normalized, validate_content
    from converter.services.note_types import (
        cloze_matches,
        plain_front,
        plain_questions,
        study_card_count,
        study_previews,
        text_html,
    )
    from converter.services.selection import (
        checked_card_limit,
        default_card_limit,
        filter_generated_logistics,
        is_course_logistics,
    )

    ids = [
        "00000000-0000-0000-0000-000000000000",
        "12345678-1234-5678-1234-567812345678",
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
    ] + [str(uuid.uuid5(uuid.NAMESPACE_URL, f"slanki-golden-{i}")) for i in range(40)]
    identity = [
        {
            "uuid": value,
            "guid": genanki.guid_for(value),
            "deck_id": int.from_bytes(hashlib.sha256(value.encode()).digest()[:6], "big"),
            "hex": uuid.UUID(value).hex,
        }
        for value in ids
    ]
    strings = [
        {
            "text": text,
            "normalized": normalized(text),
            "casefold": normalized(text).casefold(),
            "fingerprint": fingerprint(text),
            "split": text.split(),
            "strip": text.strip(),
            "text_html": text_html(text),
            "length": len(text),
        }
        for text in SAMPLES + LOGISTICS_TEXTS()
    ]

    def cloze_row(front):
        row = {"front": front}
        try:
            matches = cloze_matches(front)
            row["matches"] = [
                {"number": int(m[1]), "body": m[2], "start": m.start(), "end": m.end()}
                for m in matches
            ]
        except Exception as exc:
            row["matches_error"] = str(exc)
        row["count"] = outcome(study_card_count, front, "cloze")
        row["plain_front"] = plain_front(front, "cloze")
        row["fingerprint"] = fingerprint(front, "cloze")
        row["previews"] = outcome(study_previews, front, "Extra & <b>back</b>\nline", "cloze")
        row["previews_no_back"] = outcome(study_previews, front, "", "cloze")
        return row

    note_type_rows = []
    for front, back, kind in [
        ("Question & <tag>?", "Answer\nline 2", "basic"),
        ("Term", "Definition", "reversed"),
        ("Name the hidden part.", "", "occlusion"),
        ("What does the figure show?", "It shows x.", "visual"),
        ("Q", "A", "unknown"),
    ]:
        note_type_rows.append(
            {
                "front": front,
                "back": back,
                "note_type": kind,
                "count": outcome(study_card_count, front, kind),
                "plain_questions": list(plain_questions(front, back, kind))
                if kind != "unknown"
                else None,
                "previews": outcome(study_previews, front, back, kind),
            }
        )

    page_text = (
        "02 / MEMORY & LEARNING\nSpace your practice\nSpaced practice distributes study sessions over time.\n"
        "Massed practice groups study into one continuous session.\nStraße und 𝑥² sind hier."
    )
    source = page(2, page_text)
    content_cases = [
        (
            "What is spaced practice?",
            "Distributing sessions.",
            "Spaced practice distributes study sessions over time.",
            "basic",
            False,
        ),
        ("  padded  ", "  answer  ", "  Spaced   practice\ndistributes  ", "basic", True),
        ("Q", "A", "not on the page", "basic", True),
        ("Q", "A", "", "basic", True),
        ("Q", "A", "", "basic", False),
        ("", "A", "", "basic", False),
        ("Q", "  ", "", "basic", False),
        ("{{c1::Spaced}} practice", "", "Spaced practice", "cloze", True),
        ("{{c1::Spaced}} practice", "", "", "cloze", False),
        ("No cloze", "", "", "cloze", False),
        ("Term", "term", "", "reversed", False),
        ("Term", "TERM ", "", "reversed", False),
        ("Straße", "STRASSE", "", "reversed", False),
        ("Term", "Definition", "Straße und 𝑥² sind hier.", "reversed", True),
        ("Name it", "", "", "occlusion", False),
        ("Q" * 1001, "A", "", "basic", False),
        ("Q" * 1000, "A", "", "basic", False),
        ("Q", "A" * 5001, "", "basic", False),
        ("Q", "A", "x" * 2501, "basic", False),
        ("Q\x00", "A", "", "basic", False),
        ("𝑥" * 1000, "A", "", "basic", False),
        ("𝑥" * 1001, "A", "", "basic", False),
        ("Q", "A", "ﬁ", "basic", False),
        ("Q", "A", "massed PRACTICE", "basic", False),
        ("Q", "A", "Massed practice groups study", "basic", False),
    ]
    content = [
        {
            "front": front,
            "back": back,
            "quote": quote,
            "note_type": kind,
            "require_quote": required,
            "page_text": page_text,
            "page_number": 2,
            "result": outcome(
                validate_content, front, back, quote, source, require_quote=required, note_type=kind
            ),
        }
        for front, back, quote, kind, required in content_cases
    ]
    limits = []
    for value in [
        None,
        "",
        "0",
        "1",
        "2",
        "500",
        "501",
        3,
        7,
        "abc",
        True,
        False,
        "1000",
        " 5",
        "5 ",
        "007",
        "1.5",
        -1,
    ]:
        for page_count in (1, 4, 9):
            for card_format in ("basic", "mixed", "reversed", "all"):
                limits.append(
                    {
                        "value": value,
                        "page_count": page_count,
                        "card_format": card_format,
                        "result": outcome(
                            checked_card_limit, value, page_count, card_format=card_format
                        ),
                    }
                )
    logistics = [
        {"front": front, "quote": quote, "result": is_course_logistics(front, quote)}
        for front, quote in LOGISTICS
    ]
    payloads = [
        {"cards": []},
        {
            "cards": [
                {"front": "When is the exam?", "back": "Monday", "page": 1, "source_quote": "x"},
                {"front": "What is recall?", "back": "Memory", "page": 1, "source_quote": "x"},
                {
                    "front": "Term",
                    "back": "Wann ist die Klausur?",
                    "page": 1,
                    "source_quote": "x",
                    "note_type": "reversed",
                },
                {"front": 5, "back": "x", "page": 1, "source_quote": "x"},
                "not a dict",
            ]
        },
    ]
    filtered = [
        {"payload": payload, "result": outcome(filter_generated_logistics, payload)}
        for payload in payloads + [{"cards": "no"}, {"other": []}, [], {"cards": [], "extra": 1}]
    ]
    return {
        "identity": identity,
        "strings": strings,
        "cloze": [cloze_row(front) for front in CLOZE_FRONTS],
        "note_types": note_type_rows,
        "validate_content": content,
        "card_limits": limits,
        "default_card_limit": {str(n): default_card_limit(n) for n in range(0, 12)}
        | {"85": default_card_limit(85), "100": default_card_limit(100)},
        "logistics": logistics,
        "filter_generated_logistics": filtered,
    }


def LOGISTICS_TEXTS():
    return [front for front, _ in LOGISTICS]


def batch_vectors():
    from converter.services.cards import validate_generated_batch

    pages = {
        1: page(1, "Retrieval practice means trying to recall information from memory."),
        2: page(2, "Spaced practice distributes study sessions over time. Straße 𝑥²."),
    }
    payloads = [
        {
            "cards": [
                {
                    "front": "What is retrieval practice?",
                    "back": "Recall.",
                    "page": 1,
                    "source_quote": "trying to recall information",
                    "note_type": "basic",
                },
                {
                    "front": "{{c1::Spaced}} practice",
                    "back": "",
                    "page": 2,
                    "source_quote": "Spaced practice",
                    "note_type": "cloze",
                },
                {
                    "front": "Term",
                    "back": "Definition",
                    "page": 2,
                    "source_quote": "Straße 𝑥²",
                    "note_type": "reversed",
                },
                {
                    "front": "Bad quote",
                    "back": "A",
                    "page": 1,
                    "source_quote": "invented",
                    "note_type": "basic",
                },
                {
                    "front": "Wrong page",
                    "back": "A",
                    "page": 9,
                    "source_quote": "x",
                    "note_type": "basic",
                },
                {
                    "front": "Bool page",
                    "back": "A",
                    "page": True,
                    "source_quote": "x",
                    "note_type": "basic",
                },
                {
                    "front": "Extra key",
                    "back": "A",
                    "page": 1,
                    "source_quote": "x",
                    "note_type": "basic",
                    "x": 1,
                },
                {"front": "No type", "back": "A", "page": 1, "source_quote": "Retrieval practice"},
                {
                    "front": "No quote",
                    "back": "A",
                    "page": 1,
                    "source_quote": "  ",
                    "note_type": "basic",
                },
                {
                    "front": "x" * 1200,
                    "back": "y" * 6000,
                    "page": 1,
                    "source_quote": "z\x00" * 1500,
                    "note_type": "basic",
                },
                "string item",
            ]
        },
        {
            "cards": [
                {
                    "front": "Q",
                    "back": "A",
                    "page": 1,
                    "source_quote": "Retrieval practice",
                    "note_type": "visual",
                }
            ]
        },
        {"cards": "not a list"},
        {"cards": [{}] * 501},
    ]
    rows = []
    for payload in payloads:
        for card_format in ("mixed", "all", "basic", "reversed"):

            def run():
                validated, issues = validate_generated_batch(payload, pages, card_format)
                return {
                    "validated": [
                        {
                            "page": item.page.number,
                            "front": item.front,
                            "back": item.back,
                            "source_quote": item.source_quote,
                            "note_type": item.note_type,
                        }
                        for item in validated
                    ],
                    "issues": issues,
                }

            rows.append(
                {
                    "payload": payload if len(json.dumps(payload)) < 20000 else "<501 empty items>",
                    "card_format": card_format,
                    "result": outcome(run),
                }
            )
    return {"pages": {n: p.text for n, p in pages.items()}, "cases": rows}


# ---------------------------------------------------------------------------
# Prompts, schemas and overview


def prompt_vectors():
    from converter.services.generation import (
        OVERVIEW_SCHEMA,
        SCHEMA,
        generation_request,
        prompt_for,
    )
    from converter.services.lecture_context import (
        context_download,
        context_instructions,
        context_sections,
        overview_prompt,
        overview_sources,
        resolve_overview,
        validate_topics,
    )

    long_text = " ".join(f"Wort{n} 𝑥{n}" for n in range(120)) + "\nTail line"
    pages = [
        page(
            1,
            "Retrieval practice means trying to recall information from memory.\nA retrieval attempt happens before looking at the answer.",
        ),
        page(
            2,
            "Spaced practice distributes study sessions over time. «Quotes» & <tags> \"double\" 'single'",
        ),
        page(3, long_text),
        page(4, "", warning="No usable text found on this page. Check the slide image."),
        page(5, "a" * 250 + " " + "b" * 10),
        page(6, ("Line one\n" * 40).strip()),
    ]
    topics = [
        {
            "title": "Retrieval",
            "summary": "Recall from memory.",
            "priority": "core",
            "page": 1,
            "source_quote": "Retrieval practice means trying to recall information from memory.",
        },
        {
            "title": "Spacing «x»",
            "summary": "Distribute sessions.",
            "priority": "supporting",
            "page": 2,
            "source_quote": "Spaced practice distributes study sessions over time.",
        },
    ]
    prompts = []
    for card_format in (
        "mixed",
        "all",
        "basic",
        "cloze",
        "reversed",
        "basic_reversed",
        "cloze_reversed",
    ):
        for limit, questions, context in [
            (None, [], None),
            (3, ["What is recall?", "Wie heißt ß?", 'emoji 😀 "q"'], None),
            (7, [], topics),
            (2, ["Term", "Definition"], topics),
        ]:
            prompts.append(
                {
                    "card_format": card_format,
                    "card_limit": limit,
                    "existing_questions": questions,
                    "lecture_context": context,
                    "pages": [1, 2, 3],
                    "result": outcome(
                        prompt_for,
                        pages[:3],
                        limit,
                        questions,
                        card_format=card_format,
                        lecture_context=context,
                    ),
                }
            )
    sections = [
        {"pages": [1, 2], "topics": topics},
        {
            "pages": [3],
            "topics": [
                {
                    "title": "Long",
                    "summary": "Long page.",
                    "priority": "core",
                    "page": 3,
                    "source_quote": "Wort0 𝑥0 Wort1 𝑥1",
                }
            ],
        },
    ]
    requests = []
    for task, args, kwargs, spec in [
        (
            "cards",
            [pages[:2], 4, ["Q?"]],
            {"card_format": "mixed", "lecture_context": topics},
            None,
        ),
        (
            "cards",
            [pages[:2], 4, []],
            {"card_format": "all", "validation_feedback": "Bad JSON «ß» " + "x" * 600},
            None,
        ),
        ("overview", [pages], {}, None),
        (
            "overview",
            [pages],
            {
                "validation_feedback": "An overview topic must select a source_id supplied in this request."
            },
            None,
        ),
        ("overview", [[]], {"sections": sections}, None),
        (
            "cards",
            [[page(1, "x" * 199000)], 2, []],
            {"card_format": "mixed"},
            {"page_text": ["x", 199000]},
        ),
        (
            "cards",
            [[page(1, "x" * 1000)], 2, []],
            {"card_format": "mixed", "sections": [{"t": "y" * 200001}]},
            {"page_text": ["x", 1000], "sections_text": ["y", 200001]},
        ),
    ]:
        stored = dict(kwargs)
        if spec and "sections" in stored:
            stored["sections"] = "<see spec>"
        requests.append(
            {
                "task": task,
                "pages": [p.number for p in args[0]] if spec is None else None,
                "spec": spec,
                "args": args[1:],
                "kwargs": stored,
                "result": outcome(lambda: list(generation_request(*args, task=task, **kwargs))),
            }
        )
    section_cases = []
    for lengths in [
        [10] * 30,
        [60000, 60000, 1],
        [119999, 2],
        [120000],
        [0, 50, "warn", 70],
        [130000],
        [5] * 12 + [5],
    ]:
        test_pages = []
        for index, size in enumerate(lengths, 1):
            if size == "warn":
                test_pages.append(page(index, "text", warning="No usable text"))
            else:
                test_pages.append(page(index, ("𝑥" if index % 2 else "a") * size))
        result = outcome(lambda: [[p.number for p in s] for s in context_sections(test_pages)])
        section_cases.append({"lengths": lengths, "astral_odd_pages": True, "result": result})
    sources = {
        "pages": outcome(lambda: list(overview_sources(pages))),
        "sections": outcome(lambda: list(overview_sources([], sections))),
    }
    page_map = {p.number: p for p in pages}
    resolve_cases = []
    for payload, use_sections in [
        (
            {"topics": [{"title": "T", "summary": "S", "priority": "core", "source_id": "p1:e1"}]},
            False,
        ),
        (
            {"topics": [{"title": "T", "summary": "S", "priority": "core", "source_id": "p9:e1"}]},
            False,
        ),
        (
            {
                "topics": [
                    {"title": "T", "summary": "S", "priority": "core", "source_id": "p1:e1", "x": 1}
                ]
            },
            False,
        ),
        (
            {
                "topics": [
                    {
                        "title": "T",
                        "summary": "S",
                        "priority": "core",
                        "page": 1,
                        "source_quote": "Retrieval practice",
                    }
                ]
            },
            False,
        ),
        (
            {
                "topics": [
                    {
                        "title": "T",
                        "summary": "S",
                        "priority": "core",
                        "page": 1,
                        "source_quote": "invented",
                    }
                ]
            },
            False,
        ),
        (
            {"topics": [{"title": "T", "summary": "S", "priority": "minor", "source_id": "p1:e1"}]},
            False,
        ),
        (
            {"topics": [{"title": " ", "summary": "S", "priority": "core", "source_id": "p1:e1"}]},
            False,
        ),
        (
            {
                "topics": [
                    {"title": "T" * 101, "summary": "S", "priority": "core", "source_id": "p1:e1"}
                ]
            },
            False,
        ),
        (
            {
                "topics": [{"title": "T", "summary": "S", "priority": "core", "source_id": "p1:e1"}]
                * 9
            },
            False,
        ),
        ({"topics": []}, False),
        ({"topics": "x"}, False),
        ({"other": []}, False),
        (
            {
                "topics": [
                    {"title": "Merged", "summary": "S", "priority": "core", "source_id": "s2:t1"}
                ]
            },
            True,
        ),
        (
            {
                "topics": [
                    {"title": "Merged", "summary": "S", "priority": "core", "source_id": "p1:e1"}
                ]
            },
            True,
        ),
        (
            {
                "topics": [
                    {
                        "title": "Merged",
                        "summary": "S",
                        "priority": "core",
                        "page": 1,
                        "source_quote": "Retrieval practice",
                    }
                ]
            },
            True,
        ),
        (
            {
                "topics": [{"title": "T", "summary": "S", "priority": "core", "source_id": "s1:t1"}]
                * 21
            },
            True,
        ),
    ]:
        resolve_cases.append(
            {
                "payload": payload,
                "sections": sections if use_sections else None,
                "result": outcome(
                    resolve_overview, payload, page_map, sections=sections if use_sections else None
                ),
            }
        )
    return {
        "schemas": {
            "cards": SCHEMA,
            "overview": OVERVIEW_SCHEMA,
            "cards_json": json.dumps(SCHEMA),
            "overview_json": json.dumps(OVERVIEW_SCHEMA),
        },
        "pages": [vars(p) for p in pages],
        "topics": topics,
        "sections": sections,
        "prompt_for": prompts,
        "generation_request": requests,
        "context_sections": section_cases,
        "overview_sources": sources,
        "overview_prompt": {
            "section": overview_prompt(pages),
            "merge": overview_prompt([], sections=sections),
        },
        "resolve_overview": resolve_cases,
        "validate_topics_long_quote": outcome(
            validate_topics,
            {"topics": [{**topics[0], "source_quote": "x" * 241}]},
            page_map,
        ),
        "context_instructions": {
            "none": context_instructions(None),
            "topics": context_instructions(topics),
        },
        "context_download": outcome(context_download, pages, {1, 2}, "CARD PROMPT"),
        "context_download_too_large": outcome(
            context_download, [page(1, "x" * 200001)], set(), "CARD PROMPT"
        ),
    }


# ---------------------------------------------------------------------------
# Provider command lines and model metadata


def provider_vectors(data_dir):
    from converter.services import generation, providers
    from converter.services.cli import claude_environment, claude_isolation_args

    os.environ.pop("SLIDES_CODEX_MODEL", None)
    catalog = {
        "models": [
            {
                "id": "",
                "label": "CLI default",
                "efforts": ["", "low", "medium", "high", "max"],
                "default_effort": "",
            },
            {
                "id": "claude-sonnet-5-5",
                "label": "Sonnet 5.5",
                "efforts": ["", "low", "medium", "high", "max"],
                "default_effort": "",
            },
        ],
        "updated_at": 1.0,
    }
    (Path(data_dir) / "models-claude.json").write_text(json.dumps(catalog), encoding="utf-8")
    pages = [page(1, "Retrieval practice means trying to recall information from memory.")]

    class FakeProcess:
        def __init__(self, command, stdin=None, stdout=None, stderr=None, cwd=None, env=None, **_):
            self.command, self.env, self.returncode = command, env, 0
            self.stdin_text = stdin.read().decode("utf-8") if stdin else ""
            self.cwd = cwd
            captured.append(self)
            if "--output-last-message" in command:
                Path(command[command.index("--output-last-message") + 1]).write_text(
                    '{"cards": []}', encoding="utf-8"
                )
            if stdout is not None and envelope_bytes[0] is not None:
                stdout.write(envelope_bytes[0])
                stdout.flush()

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            pass

        def kill(self):
            pass

    captured, envelope_bytes = [], [None]

    def placeholder(command, cwd):
        return [
            "<temp>" + value[len(str(cwd)) :].replace("\\", "/")
            if cwd and value.startswith(str(cwd))
            else value
            for value in command
        ]

    codex_rows = []
    for model, effort in [("", ""), ("gpt-5.5", "low"), ("", "xhigh"), ("o4-mini", "minimal")]:
        captured.clear()
        with (
            patch.object(generation.subprocess, "Popen", FakeProcess),
            patch.object(generation, "codex_executable", return_value="CODEX_EXE"),
        ):
            result = outcome(
                generation.codex_generate,
                pages,
                model=model,
                reasoning_effort=effort,
                card_format="mixed",
                card_limit=1,
            )
        process = captured[0] if captured else None
        codex_rows.append(
            {
                "model": model,
                "effort": effort,
                "result": result,
                "argv": placeholder(process.command, process.cwd) if process else None,
                "stdin_is_prompt": process.stdin_text
                == generation.generation_request(pages, 1, (), card_format="mixed")[0]
                if process
                else None,
            }
        )
    codex_rows.append(
        {
            "model": "",
            "effort": "on",
            "result": outcome(generation.codex_generate, pages, reasoning_effort="on"),
        }
    )
    claude_rows = []
    good = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "structured_output": {"cards": []},
    }
    for model, effort, envelope in [
        ("", "", good),
        ("claude-sonnet-5-5", "high", good),
        ("", "", {"type": "result", "subtype": "success", "result": '{"cards": [1]}'}),
        ("", "", {"type": "result", "subtype": "success", "result": "not json"}),
        ("", "", {"type": "result", "subtype": "success", "result": "[1, 2]"}),
        (
            "",
            "",
            {"type": "result", "subtype": "success", "is_error": True, "structured_output": {}},
        ),
        ("", "", {"type": "result", "subtype": "error_max_turns"}),
        ("", "", {"type": "assistant"}),
        ("", "", [1, 2]),
        ("", "", "{broken"),
        (
            "",
            "",
            {
                "type": "result",
                "subtype": "success",
                "structured_output": None,
                "result": '{"a": 1}',
            },
        ),
        ("", "", {"type": "result", "subtype": "success", "structured_output": [1]}),
        ("", "low", None),
        ("unknown-model", "", None),
    ]:
        captured.clear()
        envelope_bytes[0] = (
            None
            if envelope is None
            else (envelope if isinstance(envelope, str) else json.dumps(envelope)).encode()
        )
        with (
            patch.object(generation.subprocess, "Popen", FakeProcess),
            patch.object(generation, "claude_executable", return_value="CLAUDE_EXE"),
            patch(
                "converter.services.connection.claude_login_status",
                return_value={"state": "connected"},
            ),
        ):
            result = outcome(
                generation.claude_generate,
                pages,
                model=model,
                reasoning_effort=effort,
                card_format="mixed",
                card_limit=1,
            )
        process = captured[0] if captured else None
        claude_rows.append(
            {
                "model": model,
                "effort": effort,
                "envelope": envelope,
                "result": result,
                "argv": process.command if process else None,
            }
        )
    probe_env = {
        "PATH": "x",
        "ANTHROPIC_MODEL": "x",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "x",
        "CLAUDE_CODE_EFFORT_LEVEL": "x",
        "CLAUDE_CODE_SUBAGENT_MODEL": "x",
        "CLAUDE_CODE_EXPERIMENTAL_X": "x",
        "CLAUDE_CODE_SIMPLE": "1",
        "CLAUDE_CODE_BARE": "1",
        "CLAUDECODE": "1",
        "CLAUDE_CONFIG_DIR": "kept",
        "ANTHROPIC_API_KEY_HELPER": "kept",
    }
    with patch.dict(os.environ, probe_env, clear=True):
        environment = sorted(claude_environment())
    model_ids = [
        "",
        "gpt-5.5",
        "claude-sonnet-5-5[1m]",
        "kimi-code/k2",
        "models/gemini-3-pro",
        "-flag",
        "a b",
        'x"y',
        "a" * 100,
        "a" * 101,
        "ünï",
        "a\nb",
        ".dot",
        "a:b/c_d-e.f",
    ]
    codex_models = [
        {
            "model": "gpt-5.5",
            "displayName": "GPT-5.5",
            "supportedReasoningEfforts": [
                {"reasoningEffort": "low"},
                {"reasoningEffort": "high"},
                {"reasoningEffort": "ultra"},
            ],
            "defaultReasoningEffort": "low",
            "isDefault": True,
        },
        {
            "model": "gpt-5.5-mini",
            "displayName": "",
            "supportedReasoningEfforts": [{"reasoningEffort": "minimal"}, "bad"],
            "defaultReasoningEffort": "medium",
        },
        {"model": "hidden-model", "hidden": True},
        {"model": "gpt-5.5", "displayName": "Duplicate"},
    ]
    claude_models = [
        {
            "value": "default",
            "displayName": "Default (recommended)",
            "supportedEffortLevels": ["low", "medium", "high", "max"],
        },
        {
            "value": "claude-sonnet-5-5",
            "displayName": "Sonnet",
            "supportedEffortLevels": ["low", "high", "xhigh"],
        },
        {
            "value": "claude-haiku-5-5",
            "displayName": "Haiku",
            "supportsEffort": False,
            "supportedEffortLevels": ["low"],
        },
    ]
    return {
        "codex": codex_rows,
        "claude": claude_rows,
        "claude_isolation_args": claude_isolation_args(),
        "claude_environment": {"input": sorted(probe_env), "kept": environment},
        "efforts": providers.EFFORTS,
        "providers": providers.PROVIDER_DETAILS,
        "model_ids": [
            {"id": value, "result": outcome(providers.checked_model_id, value)}
            for value in model_ids
        ],
        "normalize_models": [
            {
                "provider": "codex",
                "rows": codex_models,
                "result": outcome(providers.normalize_models, codex_models, "codex"),
            },
            {
                "provider": "claude",
                "rows": claude_models,
                "result": outcome(providers.normalize_models, claude_models, "claude"),
            },
            {
                "provider": "codex",
                "rows": [],
                "result": outcome(providers.normalize_models, [], "codex"),
            },
            {
                "provider": "codex",
                "rows": [{"model": "x", "hidden": True}],
                "result": outcome(
                    providers.normalize_models, [{"model": "x", "hidden": True}], "codex"
                ),
            },
            {
                "provider": "codex",
                "rows": [{"model": "-bad"}],
                "result": outcome(providers.normalize_models, [{"model": "-bad"}], "codex"),
            },
        ],
    }


# ---------------------------------------------------------------------------
# Full mocked generation runs


def make_text_lecture(name, texts, warnings=()):
    from converter.models import Lecture, Page

    lecture = Lecture.objects.create(
        title=name,
        sha256=hashlib.sha256(name.encode()).hexdigest(),
        original_name=f"{name}.pdf",
        original_file=f"documents/{name}/original.pdf",
    )
    for number, text in enumerate(texts, 1):
        Page.objects.create(
            lecture=lecture,
            number=number,
            text=text,
            image=f"documents/{name}/page-{number:03}.png",
            width=1500,
            height=844,
            warning="No usable text found on this page. Check the slide image."
            if number in warnings
            else "",
        )
    return lecture


def sentence(number, index):
    words = ["memory", "Gedächtnis", "spacing", "𝑥²", "retrieval", "Straße", "feedback", "schedule"]
    return f"Concept {number}.{index}: {words[(number + index) % len(words)]} links idea {number * 10 + index} to practice."


def page_texts(count):
    return [
        f"{number:02} / SYNTHETIC LECTURE\n" + "\n".join(sentence(number, i) for i in range(1, 4))
        for number in range(1, count + 1)
    ]


def cards_response(call, pages, *, formats, extras=()):
    cards = []
    for p in pages:
        quote = p.text.split("\n")[1]
        cards.append(
            {
                "note_type": "basic",
                "front": f"What does concept {p.number}.1 link?",
                "back": f"Idea {p.number * 10 + 1}.",
                "page": p.number,
                "source_quote": quote,
            }
        )
        if "cloze" in formats:
            cards.append(
                {
                    "note_type": "cloze",
                    "front": f"Concept {p.number}.2 links {{{{c1::idea {p.number * 10 + 2}}}}} to {{{{c2::practice::where?}}}}.",
                    "back": "",
                    "page": p.number,
                    "source_quote": p.text.split("\n")[2],
                }
            )
        if "reversed" in formats:
            cards.append(
                {
                    "note_type": "reversed",
                    "front": f"Concept {p.number}.3",
                    "back": f"Idea {p.number * 10 + 3}",
                    "page": p.number,
                    "source_quote": p.text.split("\n")[3],
                }
            )
    cards.extend(extras)
    return {"cards": cards}


def record_run(lecture, run_kwargs, respond, *, resume=0):
    from converter.models import GenerationRun
    from converter.services.files import GenerationOutputError, WorkflowError
    from converter.services.generation import generation_request, perform_run, resume_generation

    calls = []

    def fake(pages, cancelled, **kwargs):
        task = kwargs.get("task", "cards")
        prompt = outcome(
            lambda: generation_request(
                pages,
                kwargs.get("card_limit"),
                kwargs.get("existing_questions", ()),
                learning_focus=kwargs["learning_focus"],
                card_format=kwargs["card_format"],
                lecture_context=kwargs.get("lecture_context"),
                task=task,
                sections=kwargs.get("sections"),
                validation_feedback=kwargs.get("validation_feedback", ""),
            )[0]
        )
        call = {
            "task": task,
            "pages": [p.number for p in pages],
            "card_limit": kwargs.get("card_limit"),
            "existing_questions": list(kwargs.get("existing_questions", ())),
            "lecture_context": kwargs.get("lecture_context"),
            "sections": kwargs.get("sections"),
            "validation_feedback": kwargs.get("validation_feedback", ""),
            "model": kwargs["model"],
            "reasoning_effort": kwargs["reasoning_effort"],
            "prompt": prompt,
        }
        response = respond(len(calls), call, pages)
        calls.append(call)
        if isinstance(response, BaseException):
            call["raises"] = {"type": type(response).__name__, "message": str(response)}
            raise response
        call["response"] = response
        return response

    run = GenerationRun.objects.create(lecture=lecture, **run_kwargs)
    states = []
    for attempt in range(resume + 1):
        if attempt:
            with (
                patch("converter.services.generation.checked_model_settings"),
                patch("converter.services.generation.codex_executable"),
                patch("converter.services.generation.launch_worker"),
            ):
                resume_generation(run)
        with patch("converter.services.generation.codex_generate", side_effect=fake):
            perform_run(run.pk)
        run.refresh_from_db()
        states.append(
            {
                key: getattr(run, key)
                for key in (
                    "status",
                    "page_numbers",
                    "completed_pages",
                    "cards_added",
                    "study_cards_added",
                    "filtered_count",
                    "over_limit_count",
                    "issues",
                    "error",
                    "context_enabled",
                    "context_data",
                    "card_limit",
                    "card_format",
                )
            }
        )
    notes = [
        {
            "front": c.front,
            "back": c.back,
            "page": c.page.number,
            "note_type": c.note_type,
            "source_quote": c.source_quote,
            "fingerprint": c.fingerprint,
            "status": c.status,
            "from_run": c.run_id == run.pk,
        }
        for c in lecture.cards.order_by("created_at")
    ]
    _ = (GenerationOutputError, WorkflowError)
    return {"run": run_kwargs, "calls": calls, "states": states, "notes": notes}


def run_vectors():
    from converter.services.cards import Draft, add_drafts, update_card
    from converter.services.files import GenerationOutputError, WorkflowError

    scenarios = {}

    # 1. Small lecture, mixed formats, invalid/logistics/duplicate drafts, over-limit.
    lecture = make_text_lecture("run-small", page_texts(7), warnings=(5,))
    pages = {p.number: p for p in lecture.pages.all()}
    existing = add_drafts(
        lecture, [Draft(pages[1], "What does concept 1.1 link?", "Old answer", "", "basic")]
    )
    edited = lecture.cards.get()
    update_card(edited.pk, edited.version, "Edited prior question", "Old answer", "", "accepted")
    add_drafts(lecture, [Draft(pages[2], "What does concept 2.1 link?", "Prior", "", "basic")])

    def small(index, call, pages):
        extras = [
            {
                "note_type": "basic",
                "front": "When is the exam?",
                "back": "Monday",
                "page": pages[0].number,
                "source_quote": pages[0].text.split("\n")[1],
            },
            {
                "note_type": "basic",
                "front": "Invented",
                "back": "A",
                "page": pages[0].number,
                "source_quote": "not in the page",
            },
            {
                "note_type": "reversed",
                "front": "Not allowed",
                "back": "In mixed",
                "page": pages[0].number,
                "source_quote": pages[0].text.split("\n")[1],
            },
            {
                "note_type": "basic",
                "front": "Edited prior question",
                "back": "dup",
                "page": pages[0].number,
                "source_quote": pages[0].text.split("\n")[1],
            },
        ]
        return cards_response(call, pages, formats=("basic", "cloze"), extras=extras)

    scenarios["small_mixed"] = record_run(
        lecture,
        {
            "page_numbers": [1, 2, 3, 4, 6, 7],
            "card_limit": 4,
            "card_format": "mixed",
            "reasoning_effort": "low",
            "model": "gpt-5.5",
        },
        small,
    ) | {"existing_created": existing, "texts": page_texts(7), "warnings": [5]}

    # 2. 24 pages, whole-lecture overview (two sections + merge with one correction), all formats.
    lecture = make_text_lecture("run-context", page_texts(24))

    def context(index, call, pages):
        if call["task"] == "overview" and call["sections"] is None:
            first = pages[0].number
            return {
                "topics": [
                    {
                        "title": f"Topic {first}",
                        "summary": f"Summary for pages from {first}.",
                        "priority": "core",
                        "source_id": f"p{first}:e1",
                    },
                    {
                        "title": f"Detail {first + 1}",
                        "summary": "Supporting detail.",
                        "priority": "supporting",
                        "source_id": f"p{first + 1}:e1",
                    },
                ]
            }
        if call["task"] == "overview":
            if not call["validation_feedback"]:
                return {
                    "topics": [
                        {
                            "title": "Bad",
                            "summary": "Bad id",
                            "priority": "core",
                            "source_id": "s9:t9",
                        }
                    ]
                }
            return {
                "topics": [
                    {
                        "title": "Whole lecture",
                        "summary": "Merged.",
                        "priority": "core",
                        "source_id": "s1:t1",
                    },
                    {
                        "title": "Second half",
                        "summary": "Merged too.",
                        "priority": "supporting",
                        "source_id": "s2:t2",
                    },
                ]
            }
        return cards_response(call, pages, formats=("basic", "cloze", "reversed"))

    scenarios["context_all"] = record_run(
        lecture,
        {
            "page_numbers": list(range(1, 25)),
            "card_limit": 9,
            "card_format": "all",
            "context_enabled": True,
            "reasoning_effort": "",
            "model": "",
        },
        context,
    ) | {"texts": page_texts(24), "warnings": []}

    # 3. Failure in batch 2, then resume continuing the remaining pages.
    lecture = make_text_lecture("run-resume", page_texts(9))

    def resume(index, call, pages):
        if index == 1:
            return WorkflowError(
                "Codex could not finish. Check `codex login status` and your usage limit in a terminal, then retry. Completed drafts are preserved."
            )
        return cards_response(call, pages, formats=("basic",))

    scenarios["resume"] = record_run(
        lecture,
        {
            "page_numbers": list(range(1, 10)),
            "card_limit": 6,
            "card_format": "basic",
            "reasoning_effort": "low",
        },
        resume,
        resume=1,
    ) | {"texts": page_texts(9), "warnings": []}

    # 4. Reverse-only with a small ceiling stops as limited.
    # 7 pages, ceiling 7: batches of 3/3/1 leave one slot for the last batch.
    lecture = make_text_lecture("run-limited", page_texts(7))

    def reversed_only(index, call, pages):
        response = cards_response(call, pages, formats=("reversed",))
        response["cards"] = [card for card in response["cards"] if card["note_type"] == "reversed"]
        return response

    scenarios["reversed_limited"] = record_run(
        lecture,
        {
            "page_numbers": list(range(1, 8)),
            "card_limit": 7,
            "card_format": "reversed",
            "reasoning_effort": "low",
        },
        reversed_only,
    ) | {"texts": page_texts(7), "warnings": []}

    # 5. Invalid JSON shape from a card batch fails the run (no retry for card batches).
    lecture = make_text_lecture("run-invalid", page_texts(4))

    def invalid(index, call, pages):
        if index == 0:
            return {"cards": "not a list"}
        return cards_response(call, pages, formats=("basic",))

    scenarios["invalid_batch"] = record_run(
        lecture,
        {
            "page_numbers": [1, 2, 3, 4],
            "card_limit": 2,
            "card_format": "mixed",
            "reasoning_effort": "low",
        },
        invalid,
    ) | {"texts": page_texts(4), "warnings": []}

    # 6. Overview exhausting all three attempts stops the run visibly.
    lecture = make_text_lecture("run-overview-fail", page_texts(3))

    def overview_fail(index, call, pages):
        if call["task"] == "overview":
            return {
                "topics": [
                    {"title": "Bad", "summary": "x", "priority": "core", "source_id": "nope"}
                ]
            }
        return cards_response(call, pages, formats=("basic",))

    scenarios["overview_exhausted"] = record_run(
        lecture,
        {
            "page_numbers": [1, 2, 3],
            "card_limit": 2,
            "card_format": "mixed",
            "context_enabled": True,
            "reasoning_effort": "low",
        },
        overview_fail,
    ) | {"texts": page_texts(3), "warnings": []}

    # 7. Allowance failure during the overview is not retried.
    lecture = make_text_lecture("run-allowance", page_texts(3))
    scenarios["overview_allowance"] = record_run(
        lecture,
        {
            "page_numbers": [1, 2, 3],
            "card_limit": 2,
            "card_format": "mixed",
            "context_enabled": True,
            "reasoning_effort": "low",
        },
        lambda index, call, pages: WorkflowError(
            "Codex could not finish. Check `codex login status` and your usage limit in a terminal, then retry. Completed drafts are preserved."
        ),
    ) | {"texts": page_texts(3), "warnings": []}

    # 8. Invalid overview JSON text (output error) is retried and then succeeds.
    lecture = make_text_lecture("run-overview-json", page_texts(2))

    def overview_json(index, call, pages):
        if call["task"] == "overview":
            if index == 0:
                return GenerationOutputError(
                    "Codex returned invalid JSON. No cards from this batch were imported."
                )
            return {
                "topics": [
                    {"title": "Fine", "summary": "Ok", "priority": "core", "source_id": "p1:e1"}
                ]
            }
        return cards_response(call, pages, formats=("basic", "cloze"))

    scenarios["overview_output_retry"] = record_run(
        lecture,
        {
            "page_numbers": [1, 2],
            "card_limit": 3,
            "card_format": "mixed",
            "context_enabled": True,
            "reasoning_effort": "low",
        },
        overview_json,
    ) | {"texts": page_texts(2), "warnings": []}
    return scenarios


# ---------------------------------------------------------------------------
# Golden lecture with every note type, backups and the genanki deck


def pixel_hash(png):
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        image.load()
        return {
            "mode": image.mode,
            "size": list(image.size),
            "sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        }


def build_golden_lecture(data_dir):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from converter.models import GenerationRun
    from converter.services.cards import Draft, add_drafts, undo_card_edit, update_card
    from converter.services.documents import import_pdf
    from converter.services.generation import perform_run
    from converter.services.occlusion import add_occlusions
    from converter.services.occlusion_review import review_suggestion
    from converter.services.visual_cards import add_visual_drafts, validate_visual_payload

    lecture, _ = import_pdf(
        SimpleUploadedFile("lecture.pdf", (FIXTURES / "lecture.pdf").read_bytes()), TITLE
    )
    pages = {p.number: p for p in lecture.pages.all()}

    def respond_cards(pages_, cancelled, **kwargs):
        if kwargs.get("task") == "overview":
            return {
                "topics": [
                    {
                        "title": "Retrieval",
                        "summary": "Recall before checking.",
                        "priority": "core",
                        "source_id": "p1:e1",
                    }
                ]
            }
        cards = []
        for p in pages_:
            lines = p.text.split("\n")
            cards.append(
                {
                    "note_type": "basic",
                    "front": f"Generated question for page {p.number}?",
                    "back": "Generated answer.",
                    "page": p.number,
                    "source_quote": lines[2],
                }
            )
        cards.append(
            {
                "note_type": "cloze",
                "front": "A {{c1::retrieval attempt}} happens before looking at the {{c2::answer::what?}}.",
                "back": "",
                "page": 1,
                "source_quote": "A retrieval attempt happens before looking at the answer.",
            }
        )
        cards.append(
            {
                "note_type": "reversed",
                "front": "Massed practice",
                "back": "Study grouped into one continuous session",
                "page": 2,
                "source_quote": "Massed practice groups study into one continuous session.",
            }
        )
        cards.append(
            {
                "note_type": "basic",
                "front": "Invalid source",
                "back": "x",
                "page": 3,
                "source_quote": "This sentence is not on the slide.",
            }
        )
        cards.append(
            {
                "note_type": "basic",
                "front": "When is the exam?",
                "back": "Friday",
                "page": 3,
                "source_quote": lines[1],
            }
        )
        return {"cards": cards}

    text_run = GenerationRun.objects.create(
        lecture=lecture,
        page_numbers=[1, 2, 3],
        card_limit=6,
        card_format="all",
        context_enabled=True,
        reasoning_effort="low",
        model="gpt-5.5",
    )
    with patch("converter.services.generation.codex_generate", side_effect=respond_cards):
        perform_run(text_run.pk)

    basic_run = GenerationRun.objects.create(
        lecture=lecture,
        page_numbers=[3],
        card_limit=2,
        card_format="basic",
        reasoning_effort="medium",
    )

    def respond_basic(pages_, cancelled, **kwargs):
        return {
            "cards": [
                {
                    "note_type": "basic",
                    "front": "What does an atomic card test?",
                    "back": "One clear idea.",
                    "page": 3,
                    "source_quote": "An atomic card tests one clear idea.",
                },
                {
                    "note_type": "basic",
                    "front": "Unsupported?",
                    "back": "x",
                    "page": 3,
                    "source_quote": "Missing from the page.",
                },
            ]
        }

    with patch("converter.services.generation.codex_generate", side_effect=respond_basic):
        perform_run(basic_run.pk)

    from tests.test_visual_rundown import rundown_output, visual_output

    rundown_run = GenerationRun.objects.create(
        lecture=lecture, purpose="rundown", page_numbers=[1, 2, 3]
    )
    with patch(
        "converter.services.generation.codex_generate",
        side_effect=lambda p, *a, **k: rundown_output(p),
    ):
        perform_run(rundown_run.pk)

    add_drafts(
        lecture,
        [
            Draft(
                pages[1],
                "What is retrieval practice?",
                "Trying to recall information from memory.",
                "Retrieval practice means trying to recall information from memory.",
                "basic",
            ),
            Draft(
                pages[1],
                "Why \"escape\" <tags> & 'quotes'?\nSecond line",
                "Because & < > matter.\nLine 2 «ß» 𝑥²",
                "Checking the answer gives feedback after the attempt.",
                "basic",
            ),
            Draft(
                pages[2],
                "Spaced practice {{c1::distributes}} study sessions over {{c2::time::when?}}.",
                "Extra explanation.",
                "Spaced practice distributes study sessions over time.",
                "cloze",
            ),
            Draft(
                pages[2],
                "{{c1::Massed}} and {{c1::spaced}} practice differ; {{c3::schedules}} decide reviews.",
                "",
                "",
                "cloze",
            ),
            Draft(
                pages[3],
                "Atomic card",
                "A card that tests one clear idea.",
                "An atomic card tests one clear idea.",
                "reversed",
            ),
            Draft(
                pages[3],
                "Source reference",
                "Points back to the supporting lecture page.",
                "",
                "reversed",
            ),
            Draft(pages[3], "Rejected question?", "Rejected answer.", "", "basic"),
            Draft(pages[3], "Was ist eine Straße? 𝑥² ✓", "Ein Weg.", "", "basic"),
        ],
    )
    note = lambda front: lecture.cards.get(front=front)  # noqa: E731
    w, h = pages[1].width, pages[1].height
    card = note("What is retrieval practice?")
    card = update_card(
        card.pk,
        card.version,
        card.front,
        "Recalling information from memory.",
        card.source_quote,
        "draft",
    )
    card = update_card(
        card.pk,
        card.version,
        card.front,
        card.back,
        card.source_quote,
        "accepted",
        source_crop={
            "page": 1,
            "left": 40,
            "top": 60,
            "right": 700,
            "bottom": 400,
            "on_question": False,
        },
    )
    card = note("Why \"escape\" <tags> & 'quotes'?\nSecond line")
    update_card(
        card.pk,
        card.version,
        card.front,
        card.back,
        card.source_quote,
        "accepted",
        source_crop={
            "page": 1,
            "left": 0,
            "top": 0,
            "right": w,
            "bottom": h // 2,
            "on_question": True,
        },
    )
    card = note("Spaced practice {{c1::distributes}} study sessions over {{c2::time::when?}}.")
    update_card(card.pk, card.version, card.front, card.back, card.source_quote, "accepted")
    card = note(
        "{{c1::Massed}} and {{c1::spaced}} practice differ; {{c3::schedules}} decide reviews."
    )
    update_card(
        card.pk,
        card.version,
        card.front,
        card.back,
        card.source_quote,
        "accepted",
        source_crop={
            "page": 2,
            "left": 100,
            "top": 100,
            "right": 102,
            "bottom": 102,
            "on_question": True,
        },
    )
    card = note("Atomic card")
    update_card(
        card.pk,
        card.version,
        card.front,
        card.back,
        card.source_quote,
        "accepted",
        source_crop={
            "page": 3,
            "left": 10,
            "top": 20,
            "right": 900,
            "bottom": 500,
            "on_question": True,
        },
    )
    card = note("Rejected question?")
    update_card(card.pk, card.version, card.front, card.back, card.source_quote, "rejected")
    card = note("Was ist eine Straße? 𝑥² ✓")
    card = update_card(
        card.pk, card.version, "Was ist eine Straße? 𝑥² ✓ (edited)", card.back, "", "accepted"
    )
    undo_card_edit(card.pk, card.version)
    card = note("Was ist eine Straße? 𝑥² ✓")
    update_card(card.pk, card.version, card.front, card.back, card.source_quote, "accepted")
    for generated in lecture.cards.filter(run=text_run):
        if generated.note_type == "cloze":
            update_card(
                generated.pk,
                generated.version,
                generated.front,
                "Edited extra",
                generated.source_quote,
                "accepted",
            )
        elif generated.page.number == 2:
            update_card(
                generated.pk,
                generated.version,
                generated.front,
                generated.back,
                generated.source_quote,
                "accepted",
            )

    image_page = pages[4]
    occlusions = add_occlusions(
        lecture,
        image_page,
        "Name the hidden part.",
        "Hidden explanation & <b>",
        [
            {"page": 4, "left": 50, "top": 60, "right": 300, "bottom": 140},
            {"page": 4, "left": 0, "top": 0, "right": 2, "bottom": 2},
            {
                "page": 4,
                "left": image_page.width - 30,
                "top": image_page.height - 20,
                "right": image_page.width,
                "bottom": image_page.height,
            },
        ],
    )
    update_card(
        occlusions[0].pk,
        occlusions[0].version,
        occlusions[0].front,
        occlusions[0].back,
        "",
        "accepted",
        occlusion={"page": 4, "left": 55, "top": 65, "right": 305, "bottom": 145},
    )
    update_card(
        occlusions[1].pk,
        occlusions[1].version,
        occlusions[1].front,
        occlusions[1].back,
        "",
        "accepted",
    )
    update_card(
        occlusions[2].pk,
        occlusions[2].version,
        occlusions[2].front,
        occlusions[2].back,
        "",
        "accepted",
    )

    visual_run = GenerationRun.objects.create(
        lecture=lecture,
        page_numbers=[4],
        visual_enabled=True,
        text_enabled=False,
        card_limit=2,
        image_completed_pages=[4],
        status="completed",
        cards_added=1,
        study_cards_added=1,
    )
    add_visual_drafts(
        visual_run, image_page, validate_visual_payload(visual_output(image_page), image_page), 1
    )
    visual = lecture.cards.get(note_type="visual")
    update_card(visual.pk, visual.version, visual.front, "Answer-only explanation", "", "accepted")
    full_frame = add_drafts  # keep linters quiet about unused names in older Python
    del full_frame

    suggestion_run = GenerationRun.objects.create(
        lecture=lecture, page_numbers=[4], occlusion_enabled=True, text_enabled=False, card_limit=4
    )
    suggestion_payload = {
        "suggestions": [
            {
                "label": "Label A",
                "reason": "Recall the labelled structure.",
                "left": 400,
                "top": 300,
                "right": 600,
                "bottom": 380,
            },
            {
                "label": "Label B",
                "reason": "Second structure.",
                "left": 700,
                "top": 300,
                "right": 900,
                "bottom": 380,
            },
            {
                "label": "Label C",
                "reason": "Third structure.",
                "left": 1000,
                "top": 300,
                "right": 1200,
                "bottom": 380,
            },
        ]
    }
    with patch(
        "converter.services.generation.codex_generate",
        side_effect=lambda *a, **k: suggestion_payload,
    ):
        perform_run(suggestion_run.pk)
    proposals = list(suggestion_run.suggestions.order_by("label"))
    first = proposals[0]
    review_suggestion(
        first.pk,
        first.version,
        "accept",
        front=first.front,
        back="Accepted label explanation",
        mask=first.mask,
    )
    review_suggestion(proposals[1].pk, proposals[1].version, "discard")
    for run in (text_run, basic_run, rundown_run, suggestion_run):
        run.refresh_from_db()
        assert run.status == "completed", (run.purpose, run.error)
    return lecture


def manifest_of(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return json.loads(archive.read("manifest.json"))


def zip_with_manifest(manifest, assets):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for name, content in assets.items():
            archive.writestr(name, content)
    return output.getvalue()


def downgrade(manifest, version):
    result = copy.deepcopy(manifest)
    result["version"] = version

    def drop_runs(predicate):
        removed = {run["id"] for run in result["runs"] if predicate(run)}
        result["runs"] = [run for run in result["runs"] if run["id"] not in removed]
        for card in result["cards"]:
            if card["run"] in removed:
                card["run"] = None

    def drop_cards(note_type):
        result["cards"] = [card for card in result["cards"] if card["note_type"] != note_type]

    def pop(records, *keys):
        for record in records:
            for key in keys:
                record.pop(key)

    revisions = lambda: [r for c in result["cards"] for r in c["revisions"]]  # noqa: E731
    if version < 12:
        drop_runs(lambda run: run["purpose"] == "rundown" or run["visual_enabled"])
        drop_cards("visual")
        pop(result["runs"], "visual_enabled", "purpose", "rundown_data")
        pop(result["cards"], "visual_masks")
        pop(revisions(), "visual_masks")
    if version < 11:
        drop_runs(lambda run: run["occlusion_enabled"] or not run["text_enabled"])
        pop(
            result["runs"],
            "text_enabled",
            "occlusion_enabled",
            "image_completed_pages",
            "suggestions",
        )
    if version < 10:
        pop(result["runs"], "context_enabled", "context_data")
    if version < 9:
        drop_cards("occlusion")
        pop(result["cards"], "occlusion")
        pop(revisions(), "occlusion")
    if version < 8:
        drop_cards("reversed")
        drop_runs(lambda run: "reversed" in run["card_format"] or run["card_format"] == "all")
    if version < 7:
        pop(result["runs"], "model")
    if version < 6:
        pop(result["cards"], "source_crop")
        pop(revisions(), "source_crop")
    if version < 5:
        drop_cards("cloze")
        pop(result["runs"], "study_cards_added", "learning_focus", "card_format")
        pop(result["cards"], "note_type")
        pop(revisions(), "note_type")
    if version < 4:
        pop(result["runs"], "reasoning_effort")
    if version < 3:
        pop(result["runs"], "card_limit", "filtered_count", "over_limit_count")
    if version < 2:
        pop(result["runs"], "issues")
    return result


def golden_outputs(data_dir):
    import genanki_ref
    from django.core.files.uploadedfile import SimpleUploadedFile

    from converter.services.backups import export_backup, restore_backup
    from converter.services.deletion import cleanup_deleted_files, delete_lecture
    from converter.services.exporting import export_deck

    lecture = build_golden_lecture(data_dir)
    backup = export_backup(lecture)
    deck = export_deck(lecture)
    (OUT / "backup-v12.zip").write_bytes(backup)
    (OUT / "apkg").mkdir(parents=True, exist_ok=True)
    (OUT / "apkg" / "golden.apkg").write_bytes(deck)
    django_dump = genanki_ref.dump_apkg(deck)
    write_json("apkg/tables.json", django_dump)
    reference = genanki_ref.export_backup_deck(backup)
    reference_dump = genanki_ref.dump_apkg(reference)
    left = genanki_ref.comparable(django_dump, derived_media_names=False)
    right = genanki_ref.comparable(reference_dump, derived_media_names=False)
    if left != right:
        write_json("apkg/reference-mismatch.json", {"django": left, "reference": right})
        raise SystemExit(
            "genanki_ref.py does not reproduce export_deck; see apkg/reference-mismatch.json"
        )
    import genanki.apkg_col
    import genanki.apkg_schema

    (OUT / "apkg" / "genanki-schema.sql").write_text(
        genanki.apkg_schema.APKG_SCHEMA, encoding="utf-8"
    )
    (OUT / "apkg" / "genanki-col.sql").write_text(genanki.apkg_col.APKG_COL, encoding="utf-8")

    manifest = manifest_of(backup)
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        assets = {
            name: archive.read(name) for name in archive.namelist() if name != "manifest.json"
        }
    for number in range(1, len(manifest["pages"]) + 1):
        target = OUT / "pages" / f"{number}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(assets[f"pages/{number}.png"])
    assert (
        hashlib.sha256(assets["original.pdf"]).hexdigest()
        == hashlib.sha256((FIXTURES / "lecture.pdf").read_bytes()).hexdigest()
    )

    media_names = {item["name"]: item for item in django_dump["media"]}
    with zipfile.ZipFile(io.BytesIO(deck)) as archive:
        media_bytes = {
            media_names[name]["name"]: archive.read(item["index"])
            for name, item in media_names.items()
        }
    pixels = {"pages": {}, "derived": []}
    for number in range(1, len(manifest["pages"]) + 1):
        pixels["pages"][str(number)] = pixel_hash(assets[f"pages/{number}.png"])
    for card in manifest["cards"]:
        if card["status"] != "accepted":
            continue
        hex_id = card["id"].replace("-", "")
        for name, content in media_bytes.items():
            if hex_id in name:
                kind = name.split("_", 1)[0]
                answer = None
                if kind in ("occlusion", "visual"):
                    note_row = next(
                        n
                        for n in django_dump["notes"]
                        if n["guid"] == genanki_ref.genanki.guid_for(card["id"])
                    )
                    fields = note_row["flds"].split("\x1f")
                    hidden_index = 1 if kind == "occlusion" else 2
                    answer = name not in fields[hidden_index]
                pixels["derived"].append(
                    {
                        "name": name,
                        "kind": kind,
                        "answer": answer,
                        "note_id": card["id"],
                        "page": card["page"],
                        "source_crop": card["source_crop"],
                        "occlusion": card["occlusion"],
                        "visual_masks": card["visual_masks"],
                        **pixel_hash(content),
                    }
                )
    write_json("pixels.json", pixels)

    lecture_id = lecture.pk
    delete_lecture(lecture_id)
    cleanup_deleted_files(lecture_id)
    legacy = {}
    for version in range(1, 13):
        variant = manifest if version == 12 else downgrade(manifest, version)
        write_json(f"manifests/v{version}.json", variant)
        restored = restore_backup(
            SimpleUploadedFile(f"backup-v{version}.zip", zip_with_manifest(variant, assets))
        )
        # restore_backup returns the unsaved-timestamp instance; reload the stored record.
        restored = type(restored).objects.get(pk=restored.pk)
        restored_manifest = manifest_of(export_backup(restored))
        write_json(f"manifests/v{version}.restored.json", restored_manifest)
        legacy[version] = {
            "cards": len(restored_manifest["cards"]),
            "runs": len(restored_manifest["runs"]),
            "accepted": sum(c["status"] == "accepted" for c in restored_manifest["cards"]),
        }
        if version == 4:
            reference_v4 = genanki_ref.export_backup_deck(zip_with_manifest(variant, assets))
            django_v4 = export_deck(restored)
            assert genanki_ref.comparable(
                genanki_ref.dump_apkg(reference_v4), derived_media_names=False
            ) == genanki_ref.comparable(genanki_ref.dump_apkg(django_v4), derived_media_names=False)
        delete_lecture(restored.pk)
        cleanup_deleted_files(restored.pk)
    return {
        "lecture_id": str(lecture_id),
        "title": TITLE,
        "cards": len(manifest["cards"]),
        "accepted": sum(c["status"] == "accepted" for c in manifest["cards"]),
        "runs": len(manifest["runs"]),
        "media": len(django_dump["media"]),
        "legacy": legacy,
    }


def main():
    temporary = tempfile.mkdtemp(prefix="slanki-golden-")
    os.environ["SLIDES_DATA_DIR"] = temporary
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", verbosity=0)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    try:
        write_json("unicode.json", unicode_tables())
        write_json("text.json", text_vectors())
        write_json("batches.json", batch_vectors())
        write_json("prompts.json", prompt_vectors())
        write_json("providers.json", provider_vectors(temporary))
        write_json("runs.json", run_vectors())
        summary = golden_outputs(temporary)
        write_json("summary.json", summary)
        print(
            "golden fixtures written:",
            json.dumps({k: v for k, v in summary.items() if k != "title"}),
        )
    finally:
        from django.db import connections

        connections.close_all()
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    main()
