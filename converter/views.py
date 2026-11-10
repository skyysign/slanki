import base64
import json
import uuid

from django.conf import settings
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import CardForm, UploadForm
from .models import Card, GenerationRun, Lecture, OcclusionSuggestion, Page, PendingFileDeletion
from .services.backups import export_backup, restore_backup
from .services.cards import (
    Draft,
    add_drafts,
    keep_drafts,
    undo_card_edit,
    update_card,
    validate_content,
    validate_payload,
)
from .services.connection import claude_connection, connection, gemini_connection, kimi_connection
from .services.crops import crop_from_form, crop_png
from .services.deletion import cleanup_deleted_files, delete_lecture
from .services.documents import import_pdf
from .services.exporting import export_deck
from .services.files import WorkflowError, media_path
from .services.generation import (
    checked_generation_modes,
    checked_reasoning_effort,
    prompt_for,
    remaining_pages,
    resume_generation,
    start_generation,
)
from .services.lecture_context import checked_context, context_download, context_progress
from .services.note_types import (
    CARD_FORMATS,
    LEARNING_FOCUSES,
    MANUAL_NOTE_TYPES,
    NOTE_TYPES,
    TEXT_NOTE_TYPES,
    checked_choice,
    format_from_types,
    format_types,
    study_previews,
)
from .services.occlusion import add_occlusions, masks_from_form, occlusion_png
from .services.occlusion_review import review_suggestion
from .services.occlusion_suggestions import suggestion_jobs
from .services.providers import (
    EFFORTS,
    PROVIDER_DETAILS,
    PROVIDERS,
    checked_model_settings,
    model_catalog,
    refresh_models,
)
from .services.rundown import rundown_markdown
from .services.selection import (
    checked_card_limit,
    default_card_limit,
    logistics_drafts,
    recent_questions,
    select_drafts,
    set_aside_logistics,
)
from .services.visual_cards import visual_masks_from_form, visual_png


def error_page(request, message, lecture=None, status=400):
    return render(
        request, "converter/error.html", {"error": message, "lecture": lecture}, status=status
    )


def provider_ui_details():
    # HTTP adapter metadata: browser modules do not construct Django route paths.
    return {
        value: {
            **details,
            "connect_url": reverse("provider_connection", args=[value]),
            "refresh_url": reverse("refresh_provider_models", args=[value]),
        }
        for value, details in PROVIDER_DETAILS.items()
    }


def library_lectures():
    lectures = list(Lecture.objects.prefetch_related("cards"))
    for item in lectures:
        item.card_count = sum(card.study_card_count for card in item.cards.all())
        item.accepted_count = sum(
            card.study_card_count for card in item.cards.all() if card.status == "accepted"
        )
        item.draft_count = sum(card.status == "draft" for card in item.cards.all())
    return lectures


@require_GET
def home(request):
    return render(
        request,
        "converter/home.html",
        {
            "lectures": library_lectures(),
            "form": UploadForm(),
            "pending_deletions": PendingFileDeletion.objects.all(),
        },
    )


def provider_connection(provider):
    if provider not in dict(PROVIDERS):
        raise Http404
    return {
        "codex": connection,
        "claude": claude_connection,
        "gemini": gemini_connection,
        "kimi": kimi_connection,
    }[provider]


@require_GET
def codex_connection(request, provider="codex"):
    manager = provider_connection(provider)
    return render(
        request,
        "converter/connection.html",
        {
            "connection": manager.status(),
            "provider_id": provider,
            "provider_label": dict(PROVIDERS)[provider],
            "providers": PROVIDERS,
            "account_label": PROVIDER_DETAILS[provider]["account"],
            "company_label": PROVIDER_DETAILS[provider]["company"],
            "setup_url": PROVIDER_DETAILS[provider]["setup"],
            "separate_profile": provider in ("gemini", "kimi"),
        },
    )


@require_GET
def codex_connection_status(request, provider="codex"):
    return JsonResponse(provider_connection(provider).status())


@require_POST
def connect_codex(request, provider="codex"):
    manager = provider_connection(provider)
    if provider in ("gemini", "kimi"):
        try:
            manager.start(
                force=request.POST.get("reconnect") == "yes", region=request.POST.get("region", "")
            )
        except WorkflowError as exc:
            return error_page(request, str(exc))
    else:
        manager.start()
    return redirect("provider_connection", provider=provider)


@require_POST
def cancel_codex_login(request, provider="codex"):
    provider_connection(provider).cancel()
    return redirect("provider_connection", provider=provider)


@require_GET
def provider_models(request, provider):
    provider_connection(provider)
    return JsonResponse(model_catalog(provider))


@require_POST
def refresh_provider_models(request, provider):
    provider_connection(provider)
    try:
        return JsonResponse(refresh_models(provider))
    except WorkflowError as exc:
        return JsonResponse({**model_catalog(provider), "error": str(exc)}, status=400)


@require_POST
def upload(request):
    form = UploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            "converter/home.html",
            {"lectures": library_lectures(), "form": form},
            status=400,
        )
    try:
        item, _ = import_pdf(form.cleaned_data["pdf"], form.cleaned_data["title"])
        return redirect(item)
    except WorkflowError as exc:
        form.add_error("pdf", str(exc))
        return render(
            request,
            "converter/home.html",
            {"lectures": library_lectures(), "form": form},
            status=400,
        )


def lecture_context(item, request, selected=None, form=None, *, purpose="cards"):
    state = request.GET.get("filter", "all")
    if state not in ("all", "draft", "accepted", "rejected"):
        state = "all"
    cards = item.cards.select_related("page")
    if state != "all":
        cards = cards.filter(status=state)
    cards = list(cards)
    if selected is None and request.GET.get("card"):
        selected = get_object_or_404(item.cards.select_related("page"), pk=request.GET["card"])
    selected = (
        selected
        or next((card for card in cards if card.status == "draft"), None)
        or (cards[0] if cards else None)
    )
    if form is None and selected:
        form = CardForm(
            note_type=selected.note_type,
            initial={
                key: getattr(selected, key)
                for key in ("version", "front", "back", "source_quote", "status")
            },
        )
    pages = list(item.pages.all())
    page = selected.page if selected else (pages[0] if pages else None)
    counts = {status: 0 for status, _ in Card.STATUS}
    study_counts = {status: 0 for status, _ in Card.STATUS}
    draft_versions = {}
    for card in item.cards.all():
        counts[card.status] += 1
        study_counts[card.status] += card.study_card_count
        if card.status == "draft":
            draft_versions[str(card.pk)] = card.version
    last_run = item.runs.filter(purpose=purpose).order_by("-updated_at").first()
    resume_count = (
        len(remaining_pages(last_run))
        if last_run
        and last_run.provider in dict(PROVIDERS)
        and last_run.status in ("failed", "cancelled")
        else 0
    )
    # Keep earlier warnings visible when a later run or JSON import is created.
    issue_runs = [run for run in item.runs.all() if run.issues]
    last_codex_run = (
        item.runs.filter(provider__in=dict(PROVIDERS), purpose=purpose, occlusion_enabled=False)
        .order_by("-updated_at")
        .first()
    )
    context_run = item.runs.filter(context_enabled=True).first()
    active_run = item.runs.filter(status__in=["queued", "running"]).first()
    crop = selected.source_crop if selected else {}
    crop_enabled = bool(crop)
    if selected and request.method == "POST" and request.POST.get("crop_present") == "yes":
        crop = {
            key: request.POST.get("crop_" + key, "") for key in ("left", "top", "right", "bottom")
        }
        crop["on_question"] = request.POST.get("crop_on_question") == "yes"
        crop_enabled = request.POST.get("crop_enabled") == "yes"
    selected_format = last_codex_run.card_format if last_codex_run else "mixed"
    selected_provider = last_codex_run.provider if last_codex_run else "codex"
    selected_model = last_codex_run.model if last_codex_run else ""
    selected_reasoning = last_codex_run.reasoning_effort if last_codex_run else "low"
    catalogs = {provider: model_catalog(provider) for provider, _ in PROVIDERS}
    models = list(catalogs[selected_provider]["models"])
    if selected_model and selected_model not in [row["id"] for row in models]:
        models.append(
            {"id": selected_model, "label": f"Saved model: {selected_model} (refresh to verify)"}
        )
    position = next((i for i, card in enumerate(cards) if selected and card.pk == selected.pk), 0)
    undo = None
    if request.GET.get("undo"):
        try:
            undo = item.cards.filter(
                pk=uuid.UUID(request.GET["undo"]), version=int(request.GET.get("undo_version", ""))
            ).first()
        except (ValueError, TypeError):
            pass
        if undo and not undo.revisions.filter(version=undo.version - 1).exists():
            undo = None
    return {
        "lecture": item,
        "cards": cards,
        "card_position": position + 1 if cards else 0,
        "previous_card": cards[position - 1] if position > 0 else None,
        "next_card": cards[position + 1] if position + 1 < len(cards) else None,
        "undo_card": undo,
        "edit_open": request.method == "POST" or request.GET.get("edit") == "1",
        "selected": selected,
        "form": form,
        "pages": pages,
        "page": page,
        "filter": state,
        "counts": counts,
        "study_counts": study_counts,
        "keep_drafts_token": signing.dumps(
            {"lecture": str(item.pk), "versions": draft_versions},
            salt="keep-drafts",
            compress=True,
        )
        if draft_versions
        else "",
        "study_previews": study_previews(selected.front, selected.back, selected.note_type)
        if selected
        else [],
        "note_types": TEXT_NOTE_TYPES,
        "manual_note_types": MANUAL_NOTE_TYPES,
        "masks_json": request.POST.get("masks", "[]")
        if request.method == "POST"
        else json.dumps(
            [selected.occlusion]
            if selected and selected.note_type == "occlusion"
            else selected.visual_masks
            if selected and selected.note_type == "visual"
            else []
        ),
        "card_formats": CARD_FORMATS,
        "learning_focuses": LEARNING_FOCUSES,
        "selected_focus": last_codex_run.learning_focus if last_codex_run else "balanced",
        "selected_formats": format_types(selected_format)
        if not last_codex_run or last_codex_run.text_enabled
        else (),
        "selected_occlusion": False,
        "selected_visual": bool(last_codex_run and last_codex_run.visual_enabled),
        "suggestion_count": OcclusionSuggestion.objects.filter(
            run__lecture=item, status="pending"
        ).count(),
        "has_suggestions": OcclusionSuggestion.objects.filter(run__lecture=item).exists(),
        "crop": crop,
        "crop_enabled": crop_enabled,
        "active_run": active_run,
        "active_context": context_progress(active_run) if active_run else None,
        "last_run": last_run,
        "last_context": context_progress(last_run) if last_run else None,
        "context_run": context_run,
        "context_progress": context_progress(context_run) if context_run else None,
        "resume_count": resume_count,
        "issue_runs": issue_runs,
        "issue_count": sum(len(run.issues) for run in issue_runs),
        "warning_pages": [p for p in pages if p.warning],
        "default_card_limit": default_card_limit(sum(not p.warning for p in pages)),
        "logistics_count": len(logistics_drafts(item)),
        "reasoning_levels": EFFORTS,
        "selected_reasoning": selected_reasoning,
        "providers": PROVIDERS,
        "provider_details": provider_ui_details(),
        "selected_provider_details": PROVIDER_DETAILS[selected_provider],
        "selected_provider": selected_provider,
        "selected_model": selected_model,
        "provider_models": models,
        "model_catalogs": catalogs,
        "effort_labels": dict(EFFORTS),
    }


@require_GET
def lecture(request, pk):
    return render(
        request,
        "converter/lecture.html",
        lecture_context(get_object_or_404(Lecture, pk=pk), request),
    )


@require_POST
def keep_all_drafts(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    try:
        snapshot = signing.loads(
            request.POST.get("drafts", ""), salt="keep-drafts", max_age=24 * 60 * 60
        )
        if not isinstance(snapshot, dict) or snapshot.get("lecture") != str(item.pk):
            raise WorkflowError("The draft selection is invalid. Reload the lecture.")
        kept = keep_drafts(item, snapshot.get("versions"))
    except signing.BadSignature:
        error = "The draft selection expired or is invalid. Reload the lecture and try again."
    except WorkflowError as exc:
        error = str(exc)
    else:
        total = sum(card.study_card_count for card in kept)
        return redirect(
            f"{item.get_absolute_url()}?filter=accepted&kept={len(kept)}&kept_cards={total}"
        )
    context = lecture_context(item, request)
    context["bulk_review_error"] = error
    return render(request, "converter/lecture.html", context, status=400)


@require_POST
def save_card(request, pk):
    card = get_object_or_404(Card.objects.select_related("lecture", "page"), pk=pk)
    values = request.POST.copy()
    if values.get("action") == "accept_next":
        values["status"] = "accepted"
    elif values.get("action") == "reject_next":
        values["status"] = "rejected"
    form = CardForm(values, note_type=card.note_type)
    if form.is_valid():
        try:
            crop = (
                crop_from_form(values, card.page) if values.get("crop_present") == "yes" else None
            )
            if crop:
                crop_png(card.page, crop)
            mask = (
                masks_from_form(values, card.page, single=True)[0]
                if card.note_type == "occlusion"
                else None
            )
            covers = (
                visual_masks_from_form(values, card.page) if card.note_type == "visual" else None
            )
            saved = update_card(
                card.pk, **form.cleaned_data, source_crop=crop, occlusion=mask, visual_masks=covers
            )
            undo = f"&undo={saved.pk}&undo_version={saved.version}"
            if values.get("action") in ("accept_next", "reject_next"):
                next_card = card.lecture.cards.filter(status="draft").first()
                if next_card:
                    return redirect(
                        f"{card.lecture.get_absolute_url()}?card={next_card.pk}&saved=1{undo}"
                    )
            return redirect(f"{card.lecture.get_absolute_url()}?card={card.pk}&saved=1{undo}")
        except WorkflowError as exc:
            form.add_error(None, str(exc))
    return render(
        request,
        "converter/lecture.html",
        lecture_context(card.lecture, request, card, form),
        status=400,
    )


@require_POST
def undo_card(request, pk):
    card = get_object_or_404(Card.objects.select_related("lecture"), pk=pk)
    try:
        try:
            version = int(request.POST.get("version", ""))
        except ValueError as exc:
            raise WorkflowError("Choose a saved edit to undo.") from exc
        undo_card_edit(card.pk, version)
        return redirect(f"{card.lecture.get_absolute_url()}?card={card.pk}&undone=1")
    except WorkflowError as exc:
        return error_page(request, str(exc), card.lecture)


def selected_pages(request, item, *, images=False):
    raw = request.POST.getlist("pages")
    if not raw:
        raise WorkflowError("Select the pages you want to process.")
    try:
        numbers = {int(number) for number in raw}
    except ValueError as exc:
        raise WorkflowError("Invalid page selection.") from exc
    query = item.pages.filter(number__in=numbers)
    pages = list(query if images else query.filter(warning=""))
    if len(pages) != len(numbers):
        raise WorkflowError(
            "Some selected pages have no usable text or do not belong to this lecture."
        )
    return pages


def selected_card_format(request):
    # Older scripts can still submit the original single card_format setting.
    if request.POST.get("formats_present") != "yes":
        return checked_choice(request.POST.get("card_format", "basic"), CARD_FORMATS, "card format")
    formats = request.POST.getlist("formats")
    if len(formats) != len(set(formats)):
        raise WorkflowError("Tick card formats without duplicate choices.")
    if "occlusion" in formats or "visual" in formats:
        formats = [value for value in formats if value not in ("occlusion", "visual")]
        if not formats:
            return "basic"  # Stored text preference; text_enabled is false for this run.
    return format_from_types(formats)


@require_POST
def generate(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    if request.POST.get("consent") != "yes":
        return error_page(
            request,
            "Confirm that the selected slide text can be sent through your chosen CLI account.",
            item,
        )
    try:
        chosen = (
            request.POST.getlist("formats") if request.POST.get("formats_present") == "yes" else []
        )
        occlusions, visual = "occlusion" in chosen, "visual" in chosen
        images = occlusions or visual
        text_enabled = not images or any(value not in ("occlusion", "visual") for value in chosen)
        pages = selected_pages(request, item, images=images)
        card_format = selected_card_format(request)
        limit = checked_card_limit(
            request.POST.get("card_limit"),
            len(pages),
            card_format=card_format,
            text_enabled=text_enabled,
            occlusion_enabled=images,
        )
        effort = checked_reasoning_effort(request.POST.get("reasoning_effort", "low"))
        provider = request.POST.get("provider", "codex")
        checked_generation_modes(provider, text_enabled, occlusions, visual)
        model = request.POST.get("model", "")
        if "provider" in request.POST and "reasoning_effort" not in request.POST:
            effort = ""
        checked_model_settings(provider, model, effort)
        focus = checked_choice(
            request.POST.get("learning_focus", "balanced"), LEARNING_FOCUSES, "learning focus"
        )
        start_generation(
            item,
            [p.number for p in pages],
            card_limit=limit,
            reasoning_effort=effort,
            learning_focus=focus,
            card_format=card_format,
            provider=provider,
            model=model,
            **({"context_enabled": True} if request.POST.get("lecture_context") == "yes" else {}),
            **(
                {
                    "text_enabled": text_enabled,
                    "occlusion_enabled": occlusions,
                    "visual_enabled": visual,
                }
                if visual
                else {"text_enabled": text_enabled, "occlusion_enabled": True}
                if occlusions
                else {}
            ),
        )
        return redirect(item)
    except WorkflowError as exc:
        return error_page(request, str(exc), item)


@require_POST
def prompt(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    try:
        if set(request.POST.getlist("formats")) & {"occlusion", "visual"}:
            raise WorkflowError(
                "Image suggestions need slide attachments. Use Generate drafts, or turn off visual formats to download a text prompt."
            )
        pages = selected_pages(request, item)
        card_format = selected_card_format(request)
        limit = checked_card_limit(
            request.POST.get("card_limit"), len(pages), card_format=card_format
        )
        focus = checked_choice(
            request.POST.get("learning_focus", "balanced"), LEARNING_FOCUSES, "learning focus"
        )
    except WorkflowError as exc:
        return error_page(request, str(exc), item)
    questions = recent_questions(item)
    text = prompt_for(pages, limit, questions, learning_focus=focus, card_format=card_format)
    if request.POST.get("lecture_context") == "yes":
        try:
            text = context_download(item.pages.all(), {p.number for p in pages}, text)
        except WorkflowError as exc:
            return error_page(request, str(exc), item)
    response = HttpResponse(text, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="card-generation-prompt.txt"'
    return response


@require_POST
def import_cards(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    upload = request.FILES.get("cards")
    try:
        if not upload or upload.size > 2 * 1024 * 1024:
            raise WorkflowError("Choose a JSON draft file smaller than 2 MB.")
        payload = json.loads(upload.read().decode("utf-8-sig"))
        validated = validate_payload(payload, {p.number: p for p in item.pages.all()})
        with transaction.atomic():
            validated, filtered, _ = select_drafts(item, validated)
            run = GenerationRun.objects.create(
                lecture=item,
                status="completed",
                provider="json-import",
                page_numbers=sorted({p.number for p, *_ in validated}),
                filtered_count=filtered,
            )
            run.cards_added = add_drafts(item, validated, run)
            run.study_cards_added = sum(card.study_card_count for card in run.card_set.all())
            run.card_format = (
                format_from_types([*dict.fromkeys(draft.note_type for draft in validated)])
                if validated
                else "basic"
            )
            run.completed_pages = run.page_numbers
            run.save()
        return redirect(item)
    except (ValueError, UnicodeError) as exc:
        return error_page(
            request,
            str(exc)
            if isinstance(exc, WorkflowError)
            else "Could not read this JSON file. Use the downloaded prompt's format.",
            item,
        )


@require_POST
def add_card(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    page = get_object_or_404(item.pages, number=request.POST.get("page"))
    try:
        note_type = checked_choice(
            request.POST.get("note_type", "basic"), MANUAL_NOTE_TYPES, "note format"
        )
        front, back, quote = validate_content(
            request.POST.get("front", ""),
            request.POST.get("back", ""),
            "",
            page,
            note_type=note_type,
        )
        add_drafts(item, [Draft(page, front, back, quote, note_type)])
        return redirect(item)
    except WorkflowError as exc:
        return error_page(request, str(exc), item)


@require_POST
def preview_note(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    try:
        note_type = checked_choice(
            request.POST.get("note_type", "basic"), NOTE_TYPES, "note format"
        )
        if note_type == "visual":
            if request.POST.get("card_id"):
                try:
                    card_id = uuid.UUID(request.POST["card_id"])
                except ValueError as exc:
                    raise WorkflowError("Choose a saved visual question.") from exc
                card = get_object_or_404(
                    item.cards.select_related("page"), pk=card_id, note_type="visual"
                )
                page = card.page
            else:
                try:
                    number = int(request.POST.get("page", ""))
                except ValueError as exc:
                    raise WorkflowError("Choose a source page.") from exc
                page = get_object_or_404(item.pages, number=number)
            front, back, _ = validate_content(
                request.POST.get("front", ""),
                request.POST.get("back", ""),
                "",
                page,
                note_type="visual",
            )
            crop = crop_from_form(request.POST, page)
            masks = visual_masks_from_form(request.POST, page)
            previews = study_previews(front, back, "visual")
            for key, answer in (("question_image", False), ("answer_image", True)):
                previews[0][key] = "data:image/png;base64," + base64.b64encode(
                    visual_png(page, crop, masks, answer=answer)
                ).decode("ascii")
            return JsonResponse(
                {
                    "previews": previews,
                    "study_cards": 1,
                    "caption": "One visual question. All text covers are hidden together; the answer reveals them.",
                }
            )
        if note_type == "occlusion":
            if request.POST.get("card_id"):
                try:
                    card_id = uuid.UUID(request.POST["card_id"])
                except ValueError as exc:
                    raise WorkflowError("Choose a saved image occlusion note.") from exc
                card = get_object_or_404(
                    item.cards.select_related("page"), pk=card_id, note_type="occlusion"
                )
                page = card.page
            else:
                try:
                    page_number = int(request.POST.get("page", ""))
                except ValueError as exc:
                    raise WorkflowError("Choose a source page.") from exc
                page = get_object_or_404(item.pages, number=page_number)
            masks = masks_from_form(request.POST, page, single=bool(request.POST.get("card_id")))
            front, back, _ = validate_content(
                request.POST.get("front", ""),
                request.POST.get("back", ""),
                "",
                page,
                note_type=note_type,
            )
            try:
                index = int(request.POST.get("preview_index", "0"))
            except ValueError as exc:
                raise WorkflowError("Select a region to preview.") from exc
            if not 0 <= index < len(masks):
                raise WorkflowError("Select a region to preview.")
            previews = study_previews(front, back, note_type)
            for key, answer in (("question_image", False), ("answer_image", True)):
                previews[0][key] = "data:image/png;base64," + base64.b64encode(
                    occlusion_png(page, masks[index], answer=answer)
                ).decode("ascii")
            return JsonResponse(
                {
                    "previews": previews,
                    "study_cards": 1,
                    "caption": f"Region {index + 1} of {len(masks)}. Each region makes one card. Preview only; changes have not been saved.",
                }
            )
        # Preview is content-only and never saves edits or calls a provider.
        front, back, _ = validate_content(
            request.POST.get("front", ""),
            request.POST.get("back", ""),
            "",
            item.pages.first(),
            note_type=note_type,
        )
        previews = study_previews(front, back, note_type)
        crop_image, on_question = "", False
        if request.POST.get("card_id"):
            try:
                card_id = uuid.UUID(request.POST["card_id"])
            except ValueError as exc:
                raise WorkflowError("Choose an existing note to preview its source crop.") from exc
            card = get_object_or_404(item.cards.select_related("page"), pk=card_id)
            crop = crop_from_form(request.POST, card.page)
            if crop:
                crop_image = "data:image/png;base64," + base64.b64encode(
                    crop_png(card.page, crop)
                ).decode("ascii")
                on_question = crop["on_question"]
        return JsonResponse(
            {
                "previews": previews,
                "study_cards": len(previews),
                "crop_image": crop_image,
                "crop_on_question": on_question,
            }
        )
    except WorkflowError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_GET
def preview_export(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    accepted = item.cards.filter(status="accepted").select_related("page")
    total = sum(card.study_card_count for card in accepted)
    page = Paginator(accepted, 20).get_page(request.GET.get("page"))
    entries = [
        {"note": card, "previews": study_previews(card.front, card.back, card.note_type)}
        for card in page
    ]
    return render(
        request,
        "converter/preview_export.html",
        {"lecture": item, "entries": entries, "pagination": page, "study_count": total},
    )


@require_POST
def filter_logistics(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    count = set_aside_logistics(item)
    return redirect(f"{item.get_absolute_url()}?filtered={count}&filter=draft")


@require_GET
def page_image(request, pk):
    page = get_object_or_404(Page, pk=pk)
    path = media_path(page.image)
    if not path.is_file():
        return HttpResponse("Source image missing. Restore your backup.", status=404)
    return FileResponse(path.open("rb"), content_type="image/png")


@require_GET
def card_crop(request, pk):
    card = get_object_or_404(Card.objects.select_related("page"), pk=pk)
    try:
        return HttpResponse(crop_png(card.page, card.source_crop), content_type="image/png")
    except WorkflowError as exc:
        return HttpResponse(str(exc), status=404, content_type="text/plain")


@require_GET
def confirm_delete(request, pk):
    lecture = get_object_or_404(Lecture, pk=pk)
    return render(request, "converter/delete_lecture.html", {"lecture": lecture})


@require_POST
def delete_set(request, pk):
    if request.POST.get("confirm") != "yes":
        return render(
            request,
            "converter/delete_lecture.html",
            {
                "lecture": get_object_or_404(Lecture, pk=pk),
                "error": "Tick the confirmation before deleting this set.",
            },
            status=400,
        )
    delete_lecture(pk)
    return redirect("/?deleted=1")


@require_POST
def retry_file_deletion(request, pk):
    get_object_or_404(PendingFileDeletion, pk=pk)
    complete = cleanup_deleted_files(pk)
    return redirect("/?cleanup=" + ("done" if complete else "pending"))


@require_GET
def export(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    try:
        data = export_deck(item)
    except WorkflowError as exc:
        return error_page(request, str(exc), item)
    response = HttpResponse(data, content_type="application/octet-stream")
    response["Content-Disposition"] = (
        f'attachment; filename="{slugify(item.title) or "lecture"}.apkg"'
    )
    return response


@require_GET
def backup(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    try:
        data = export_backup(item)
    except WorkflowError as exc:
        return error_page(request, str(exc), item)
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = (
        f'attachment; filename="{slugify(item.title) or "lecture"}-backup.zip"'
    )
    return response


@require_POST
def restore(request):
    upload = request.FILES.get("backup")
    if not upload:
        return error_page(request, "Choose a Recalloom backup ZIP.")
    try:
        return redirect(restore_backup(upload))
    except WorkflowError as exc:
        return error_page(request, str(exc))


@require_POST
def cancel_run(request, pk):
    run = get_object_or_404(GenerationRun, pk=pk)
    GenerationRun.objects.filter(pk=pk, status__in=["queued", "running"]).update(
        status="cancelled", updated_at=timezone.now()
    )
    return (
        redirect("lecture_rundown", pk=run.lecture_id)
        if run.purpose == "rundown"
        else redirect(run.lecture)
    )


@require_GET
def run_status(request, pk):
    run = get_object_or_404(GenerationRun, pk=pk)
    return JsonResponse(
        {
            "status": run.status,
            "completed": len(run.progress_pages),
            "total": len(run.page_numbers),
            "cards_added": run.cards_added,
            "study_cards_added": run.study_cards_added,
            "context": context_progress(run),
            "learning_focus": run.get_learning_focus_display(),
            "card_format": run.format_label,
            "image_phase": run.image_phase,
            "visual_enabled": run.visual_enabled,
            "purpose": run.purpose,
            "suggestions": run.suggestions.count(),
            "review_url": (reverse("lecture_rundown", args=[run.lecture_id]) + f"?run={run.pk}")
            if run.purpose == "rundown"
            else reverse("review_occlusions", args=[run.lecture_id]),
            "error": run.error,
            "issues": len(run.issues),
            "card_limit": run.card_limit,
            "reasoning_effort": run.get_reasoning_effort_display(),
            "provider": run.provider_label,
            "model": run.model_label,
            "filtered_count": run.filtered_count,
            "over_limit_count": run.over_limit_count,
        }
    )


@require_POST
def resume_run(request, pk):
    run = get_object_or_404(GenerationRun.objects.select_related("lecture"), pk=pk)
    try:
        resume_generation(run)
        return (
            redirect("lecture_rundown", pk=run.lecture_id)
            if run.purpose == "rundown"
            else redirect(run.lecture)
        )
    except WorkflowError as exc:
        return error_page(request, str(exc), run.lecture)


@require_POST
def demo(request):
    fixture = settings.BASE_DIR / "tests" / "fixtures" / "synthetic"
    item, _ = import_pdf(
        SimpleUploadedFile("memory-and-learning.pdf", (fixture / "lecture.pdf").read_bytes()),
        "Memory & learning · sample",
    )
    payload = json.loads((fixture / "cards.json").read_text(encoding="utf-8"))
    add_drafts(item, validate_payload(payload, {p.number: p for p in item.pages.all()}))
    return redirect(item)


@require_GET
def card_visual(request, pk, side):
    card = get_object_or_404(Card.objects.select_related("page"), pk=pk, note_type="visual")
    if side not in ("question", "answer"):
        raise Http404
    try:
        return HttpResponse(
            visual_png(card.page, card.source_crop, card.visual_masks, answer=side == "answer"),
            content_type="image/png",
        )
    except WorkflowError as exc:
        return error_page(request, str(exc), card.lecture)


@require_GET
def anatomy(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    context = lecture_context(item, request)
    context.update(
        providers=(("codex", "Codex"),),
        selected_provider="codex",
        selected_model="",
        selected_reasoning="low",
        selected_provider_details=PROVIDER_DETAILS["codex"],
        provider_models=model_catalog("codex")["models"],
    )
    return render(request, "converter/anatomy.html", context)


@require_GET
def lecture_rundown(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    context = lecture_context(item, request, purpose="rundown")
    runs = item.runs.filter(purpose="rundown")
    if request.GET.get("run"):
        try:
            run = get_object_or_404(runs, pk=uuid.UUID(request.GET["run"]))
        except ValueError:
            raise Http404 from None
    else:
        run = runs.first()
    sections = []
    source_pages = {p.number: p for p in context["pages"]}
    if run:
        for section in run.rundown_data.get("sections", []):
            for topic in section["content"]["topics"]:
                topic = dict(topic)
                topic["source_page"] = source_pages[topic["page"]]
                sections.append(topic)
    context.update(
        rundown_page=True,
        rundown_run=run,
        rundown_topics=sections,
        rundown_runs=runs[:20],
        rundown_active=run if run and run.status in ("queued", "running") else None,
        rundown_resume=run and run.status in ("failed", "cancelled") and remaining_pages(run),
    )
    return render(request, "converter/rundown.html", context)


@require_POST
def generate_rundown(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    try:
        if request.POST.get("consent") != "yes":
            raise WorkflowError("Confirm sharing the lecture text before generating its rundown.")
        start_generation(
            item,
            list(item.pages.filter(warning="").exclude(text="").values_list("number", flat=True)),
            provider=request.POST.get("provider", "codex"),
            model=request.POST.get("model", ""),
            reasoning_effort=request.POST.get("reasoning_effort", ""),
            purpose="rundown",
        )
        return redirect("lecture_rundown", pk=pk)
    except WorkflowError as exc:
        return error_page(request, str(exc), item)


@require_GET
def download_rundown(request, pk):
    run = get_object_or_404(
        GenerationRun.objects.select_related("lecture"), pk=pk, purpose="rundown"
    )
    response = HttpResponse(
        rundown_markdown(run.lecture, run), content_type="text/markdown; charset=utf-8"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{slugify(run.lecture.title) or "lecture"}-rundown.md"'
    )
    return response


@require_http_methods(["GET", "POST"])
def review_occlusions(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    suggestions = OcclusionSuggestion.objects.filter(run__lecture=item).select_related(
        "page", "card", "run"
    )
    state = request.GET.get("status", "pending")
    if state not in dict(OcclusionSuggestion.STATUS):
        state = "pending"
    selected_id = (
        request.POST.get("suggestion")
        if request.method == "POST"
        else request.GET.get("suggestion")
    )
    if request.method == "POST" and not selected_id:
        return error_page(request, "Choose a saved suggestion before reviewing it.", item)
    selected = None
    if selected_id:
        try:
            selected = get_object_or_404(suggestions, pk=uuid.UUID(selected_id))
        except ValueError:
            raise Http404 from None
    listing = Paginator(suggestions.filter(status=state), 20).get_page(request.GET.get("page"))
    selected = selected or next(iter(listing), None)
    error = ""
    if request.method == "POST":
        if selected is None:
            raise Http404
        try:
            try:
                version = int(request.POST.get("version", ""))
            except ValueError as exc:
                raise WorkflowError("Reload this suggestion before saving.") from exc
            action = request.POST.get("action")
            mask = (
                masks_from_form(request.POST, selected.page, single=True)[0]
                if action in ("save", "accept")
                else None
            )
            result = review_suggestion(
                selected.pk,
                version,
                action,
                front=request.POST.get("front", ""),
                back=request.POST.get("back", ""),
                mask=mask,
            )
            url = reverse("review_occlusions", args=[pk])
            if action == "save":
                return redirect(f"{url}?suggestion={selected.pk}&saved=1")
            if action == "accept":
                return redirect(f"{url}?accepted={result.card_id}")
            return redirect(f"{url}?{action}=1")
        except WorkflowError as exc:
            error = str(exc)
    return render(
        request,
        "converter/occlusion_review.html",
        {
            "lecture": item,
            "suggestions": listing,
            "selected": selected,
            "state": state,
            "states": OcclusionSuggestion.STATUS,
            "error": error,
            "pending_count": suggestions.filter(status="pending").count(),
            "active_run": item.runs.filter(
                status__in=["queued", "running"], occlusion_enabled=True
            ).first(),
            "front": request.POST.get("front", selected.front if selected else ""),
            "back": request.POST.get("back", selected.back if selected else ""),
            "masks_json": request.POST.get(
                "masks", json.dumps([selected.mask] if selected else [])
            ),
        },
        status=400 if error else 200,
    )


@require_GET
def suggestion_image(request, pk, side):
    suggestion = get_object_or_404(OcclusionSuggestion.objects.select_related("page"), pk=pk)
    if side not in ("question", "answer"):
        raise Http404
    try:
        return HttpResponse(
            occlusion_png(suggestion.page, suggestion.mask, answer=side == "answer"),
            content_type="image/png",
        )
    except WorkflowError as exc:
        return error_page(request, str(exc), status=400)


@require_http_methods(["GET", "POST"])
def occlusion_builder(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    values = request.POST if request.method == "POST" else request.GET
    try:
        page_number = int(values.get("page", "1"))
    except ValueError:
        return error_page(request, "Choose a valid source page.", item)
    page = get_object_or_404(item.pages, number=page_number)
    error = ""
    front = request.POST.get("front", "Name the hidden part.")
    back = request.POST.get("back", "")
    catalog = model_catalog("codex")
    last_codex = item.runs.filter(provider="codex").first()
    overview_run = next(
        (
            run
            for run in item.runs.filter(context_enabled=True)
            if run.context_data.get("outline") is not None
        ),
        None,
    )
    if request.method == "POST":
        try:
            masks = masks_from_form(request.POST, page)
            saved = add_occlusions(item, page, front, back, masks)
            if saved:
                return redirect(
                    f"{item.get_absolute_url()}?card={saved[0].pk}&occlusions_added={len(saved)}"
                )
            error = "These regions already have notes. Open the existing notes to edit them."
        except WorkflowError as exc:
            error = str(exc)
    return render(
        request,
        "converter/occlusion_builder.html",
        {
            "lecture": item,
            "page": page,
            "pages": item.pages.all(),
            "front": front,
            "back": back,
            "error": error,
            "masks_json": request.POST.get("masks", "[]"),
            "overview_run": overview_run,
            "providers": (("codex", "Codex"),),
            "provider_details": provider_ui_details(),
            "selected_provider": "codex",
            "selected_model": last_codex.model if last_codex else "",
            "selected_reasoning": last_codex.reasoning_effort if last_codex else "low",
            "provider_models": catalog["models"],
            "model_catalogs": {"codex": catalog},
            "reasoning_levels": EFFORTS,
            "effort_labels": dict(EFFORTS),
            "image_suggestions": True,
        },
        status=400 if error else 200,
    )


@require_POST
def start_occlusion_suggestions(request, pk):
    from .services.connection import login_status

    item = get_object_or_404(Lecture, pk=pk)
    try:
        if request.POST.get("consent") != "yes":
            raise WorkflowError(
                "Confirm sharing this slide image and text before requesting suggestions."
            )
        if request.POST.get("provider", "codex") != "codex":
            raise WorkflowError("Image suggestions currently require the Codex connection.")
        try:
            number = int(request.POST.get("page", ""))
        except ValueError as exc:
            raise WorkflowError("Choose a valid source page.") from exc
        page = get_object_or_404(item.pages, number=number)
        model, effort = request.POST.get("model", ""), request.POST.get("reasoning_effort", "")
        checked_model_settings("codex", model, effort)
        outline = None
        if selected := request.POST.get("overview"):
            try:
                overview_id = uuid.UUID(selected)
            except ValueError as exc:
                raise WorkflowError("Choose a saved overview from this lecture.") from exc
            run = get_object_or_404(item.runs, pk=overview_id, context_enabled=True)
            data = checked_context(run.context_data, True, item, list(item.pages.all()))
            outline = data.get("outline")
            if outline is None:
                raise WorkflowError(
                    "This overview is incomplete. Finish it or untick the overview option."
                )
        if login_status()["state"] != "connected":
            raise WorkflowError("Connect Codex with your ChatGPT account in AI connections first.")
        data = suggestion_jobs.start(page, model, effort, outline)
        return JsonResponse(data)
    except WorkflowError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_GET
def occlusion_suggestion_status(request, pk, job_id):
    get_object_or_404(Lecture, pk=pk)
    try:
        return JsonResponse(suggestion_jobs.get(job_id, pk))
    except WorkflowError as exc:
        return JsonResponse({"error": str(exc)}, status=404)


@require_POST
def cancel_occlusion_suggestions(request, pk, job_id):
    get_object_or_404(Lecture, pk=pk)
    suggestion_jobs.cancel(job_id, pk)
    return JsonResponse({"status": "cancelled"})


@require_GET
def card_occlusion(request, pk, side):
    card = get_object_or_404(Card.objects.select_related("page"), pk=pk, note_type="occlusion")
    if side not in ("question", "answer"):
        raise Http404
    try:
        return HttpResponse(
            occlusion_png(card.page, card.occlusion, answer=side == "answer"),
            content_type="image/png",
        )
    except WorkflowError as exc:
        return HttpResponse(str(exc), status=404, content_type="text/plain")
