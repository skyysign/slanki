import base64
import json
import uuid

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from .forms import CardForm, UploadForm
from .models import Card, GenerationRun, Lecture, Page, PendingFileDeletion
from .services.backups import export_backup, restore_backup
from .services.cards import Draft, add_drafts, update_card, validate_content, validate_payload
from .services.connection import claude_connection, connection, gemini_connection, kimi_connection
from .services.crops import crop_from_form, crop_png
from .services.deletion import cleanup_deleted_files, delete_lecture
from .services.documents import import_pdf
from .services.exporting import export_deck
from .services.files import WorkflowError, media_path
from .services.generation import (
    checked_reasoning_effort,
    prompt_for,
    remaining_pages,
    resume_generation,
    start_generation,
)
from .services.note_types import (
    CARD_FORMATS,
    LEARNING_FOCUSES,
    NOTE_TYPES,
    checked_choice,
    format_from_types,
    format_types,
    study_previews,
)
from .services.providers import (
    EFFORTS,
    PROVIDER_DETAILS,
    PROVIDERS,
    checked_model_settings,
    model_catalog,
    refresh_models,
)
from .services.selection import (
    checked_card_limit,
    default_card_limit,
    logistics_drafts,
    recent_questions,
    select_drafts,
    set_aside_logistics,
)


def error_page(request, message, lecture=None, status=400):
    return render(
        request, "converter/error.html", {"error": message, "lecture": lecture}, status=status
    )


@require_GET
def home(request):
    lectures = list(Lecture.objects.prefetch_related("cards"))
    for item in lectures:
        item.card_count = sum(card.study_card_count for card in item.cards.all())
        item.accepted_count = sum(
            card.study_card_count for card in item.cards.all() if card.status == "accepted"
        )
    return render(
        request,
        "converter/home.html",
        {
            "lectures": lectures,
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
            {"lectures": Lecture.objects.all(), "form": form},
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
            {"lectures": Lecture.objects.all(), "form": form},
            status=400,
        )


def lecture_context(item, request, selected=None, form=None):
    state = request.GET.get("filter", "all")
    if state not in ("all", "draft", "accepted", "rejected"):
        state = "all"
    cards = item.cards.select_related("page")
    if state != "all":
        cards = cards.filter(status=state)
    cards = list(cards)
    if selected is None and request.GET.get("card"):
        selected = get_object_or_404(item.cards.select_related("page"), pk=request.GET["card"])
    selected = selected or (cards[0] if cards else None)
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
    counts = {status: item.cards.filter(status=status).count() for status, _ in Card.STATUS}
    study_counts = {status: 0 for status, _ in Card.STATUS}
    for card in item.cards.all():
        study_counts[card.status] += card.study_card_count
    last_run = item.runs.order_by("-updated_at").first()
    resume_count = (
        len(remaining_pages(last_run))
        if last_run
        and last_run.provider in dict(PROVIDERS)
        and last_run.status in ("failed", "cancelled")
        else 0
    )
    # Keep earlier warnings visible when a later run or JSON import is created.
    issue_runs = [run for run in item.runs.all() if run.issues]
    last_codex_run = item.runs.filter(provider__in=dict(PROVIDERS)).order_by("-updated_at").first()
    crop = selected.source_crop if selected else {}
    crop_enabled = bool(crop)
    if selected and request.method == "POST" and request.POST.get("crop_present") == "yes":
        crop = {
            key: request.POST.get("crop_" + key, "") for key in ("left", "top", "right", "bottom")
        }
        crop["on_question"] = request.POST.get("crop_on_question") == "yes"
        crop_enabled = request.POST.get("crop_enabled") == "yes"
    selected_format = last_codex_run.card_format if last_codex_run else "basic"
    selected_provider = last_codex_run.provider if last_codex_run else "codex"
    selected_model = last_codex_run.model if last_codex_run else ""
    selected_reasoning = last_codex_run.reasoning_effort if last_codex_run else "low"
    catalogs = {provider: model_catalog(provider) for provider, _ in PROVIDERS}
    models = list(catalogs[selected_provider]["models"])
    if selected_model and selected_model not in [row["id"] for row in models]:
        models.append(
            {"id": selected_model, "label": f"Saved model: {selected_model} (refresh to verify)"}
        )
    return {
        "lecture": item,
        "cards": cards,
        "selected": selected,
        "form": form,
        "pages": pages,
        "page": page,
        "filter": state,
        "counts": counts,
        "study_counts": study_counts,
        "study_previews": study_previews(selected.front, selected.back, selected.note_type)
        if selected
        else [],
        "note_types": NOTE_TYPES,
        "card_formats": CARD_FORMATS,
        "learning_focuses": LEARNING_FOCUSES,
        "selected_focus": last_codex_run.learning_focus if last_codex_run else "balanced",
        "selected_formats": format_types(selected_format),
        "crop": crop,
        "crop_enabled": crop_enabled,
        "active_run": item.runs.filter(status__in=["queued", "running"]).first(),
        "last_run": last_run,
        "resume_count": resume_count,
        "issue_runs": issue_runs,
        "issue_count": sum(len(run.issues) for run in issue_runs),
        "warning_pages": [p for p in pages if p.warning],
        "default_card_limit": default_card_limit(sum(not p.warning for p in pages)),
        "logistics_count": len(logistics_drafts(item)),
        "reasoning_levels": EFFORTS,
        "selected_reasoning": selected_reasoning,
        "providers": PROVIDERS,
        "provider_details": PROVIDER_DETAILS,
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
def save_card(request, pk):
    card = get_object_or_404(Card.objects.select_related("lecture", "page"), pk=pk)
    values = request.POST.copy()
    if values.get("action") == "accept_next":
        values["status"] = "accepted"
    form = CardForm(values, note_type=card.note_type)
    if form.is_valid():
        try:
            crop = (
                crop_from_form(values, card.page) if values.get("crop_present") == "yes" else None
            )
            if crop:
                crop_png(card.page, crop)
            update_card(card.pk, **form.cleaned_data, source_crop=crop)
            if values.get("action") == "accept_next":
                next_card = card.lecture.cards.filter(status="draft").first()
                if next_card:
                    return redirect(
                        f"{card.lecture.get_absolute_url()}?card={next_card.pk}&saved=1"
                    )
            return redirect(f"{card.lecture.get_absolute_url()}?card={card.pk}&saved=1")
        except WorkflowError as exc:
            form.add_error(None, str(exc))
    return render(
        request,
        "converter/lecture.html",
        lecture_context(card.lecture, request, card, form),
        status=400,
    )


def selected_pages(request, item):
    raw = request.POST.getlist("pages")
    if not raw:
        raise WorkflowError("Select the pages you want to process.")
    try:
        numbers = {int(number) for number in raw}
    except ValueError as exc:
        raise WorkflowError("Invalid page selection.") from exc
    pages = list(item.pages.filter(number__in=numbers, warning=""))
    if len(pages) != len(numbers):
        raise WorkflowError(
            "Some selected pages have no usable text or do not belong to this lecture."
        )
    return pages


def selected_card_format(request):
    # Older scripts can still submit the original single card_format setting.
    if request.POST.get("formats_present") != "yes":
        return checked_choice(request.POST.get("card_format", "basic"), CARD_FORMATS, "card format")
    return format_from_types(request.POST.getlist("formats"))


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
        pages = selected_pages(request, item)
        card_format = selected_card_format(request)
        limit = checked_card_limit(
            request.POST.get("card_limit"), len(pages), card_format=card_format
        )
        effort = checked_reasoning_effort(request.POST.get("reasoning_effort", "low"))
        provider = request.POST.get("provider", "codex")
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
        )
        return redirect(item)
    except WorkflowError as exc:
        return error_page(request, str(exc), item)


@require_POST
def prompt(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    try:
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
    response = HttpResponse(
        prompt_for(pages, limit, questions, learning_focus=focus, card_format=card_format),
        content_type="text/plain; charset=utf-8",
    )
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
            request.POST.get("note_type", "basic"), NOTE_TYPES, "note format"
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
    return redirect(run.lecture)


@require_GET
def run_status(request, pk):
    run = get_object_or_404(GenerationRun, pk=pk)
    return JsonResponse(
        {
            "status": run.status,
            "completed": len(run.completed_pages),
            "total": len(run.page_numbers),
            "cards_added": run.cards_added,
            "study_cards_added": run.study_cards_added,
            "learning_focus": run.get_learning_focus_display(),
            "card_format": run.get_card_format_display(),
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
        return redirect(run.lecture)
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
