import json

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from .forms import CardForm, UploadForm
from .models import Card, GenerationRun, Lecture, Page
from .services.backups import export_backup, restore_backup
from .services.cards import add_drafts, update_card, validate_content, validate_payload
from .services.documents import import_pdf
from .services.exporting import export_deck
from .services.files import WorkflowError, media_path
from .services.generation import prompt_for, remaining_pages, resume_generation, start_generation


def error_page(request, message, lecture=None, status=400):
    return render(
        request, "converter/error.html", {"error": message, "lecture": lecture}, status=status
    )


@require_GET
def home(request):
    lectures = Lecture.objects.annotate(
        card_count=Count("cards"), accepted_count=Count("cards", filter=Q(cards__status="accepted"))
    )
    return render(request, "converter/home.html", {"lectures": lectures, "form": UploadForm()})


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
            initial={
                key: getattr(selected, key)
                for key in ("version", "front", "back", "source_quote", "status")
            }
        )
    pages = list(item.pages.all())
    page = selected.page if selected else (pages[0] if pages else None)
    counts = {status: item.cards.filter(status=status).count() for status, _ in Card.STATUS}
    last_run = item.runs.order_by("-updated_at").first()
    resume_count = (
        len(remaining_pages(last_run))
        if last_run and last_run.provider == "codex" and last_run.status in ("failed", "cancelled")
        else 0
    )
    # Keep earlier warnings visible when a later run or JSON import is created.
    issue_runs = [run for run in item.runs.all() if run.issues]
    return {
        "lecture": item,
        "cards": cards,
        "selected": selected,
        "form": form,
        "pages": pages,
        "page": page,
        "filter": state,
        "counts": counts,
        "active_run": item.runs.filter(status__in=["queued", "running"]).first(),
        "last_run": last_run,
        "resume_count": resume_count,
        "issue_runs": issue_runs,
        "issue_count": sum(len(run.issues) for run in issue_runs),
        "warning_pages": [p for p in pages if p.warning],
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
    form = CardForm(values)
    if form.is_valid():
        try:
            update_card(card.pk, **form.cleaned_data)
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


@require_POST
def generate(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    if request.POST.get("consent") != "yes":
        return error_page(
            request,
            "Confirm that the selected slide text can be sent through your Codex account.",
            item,
        )
    try:
        pages = selected_pages(request, item)
        start_generation(item, [p.number for p in pages])
        return redirect(item)
    except WorkflowError as exc:
        return error_page(request, str(exc), item)


@require_POST
def prompt(request, pk):
    item = get_object_or_404(Lecture, pk=pk)
    try:
        pages = selected_pages(request, item)
    except WorkflowError as exc:
        return error_page(request, str(exc), item)
    response = HttpResponse(prompt_for(pages), content_type="text/plain; charset=utf-8")
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
            run = GenerationRun.objects.create(
                lecture=item,
                status="completed",
                provider="json-import",
                page_numbers=sorted({p.number for p, *_ in validated}),
            )
            run.cards_added = add_drafts(item, validated, run)
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
        front, back, quote = validate_content(
            request.POST.get("front", ""), request.POST.get("back", ""), "", page
        )
        add_drafts(item, [(page, front, back, quote)])
        return redirect(item)
    except WorkflowError as exc:
        return error_page(request, str(exc), item)


@require_GET
def page_image(request, pk):
    page = get_object_or_404(Page, pk=pk)
    path = media_path(page.image)
    if not path.is_file():
        return HttpResponse("Source image missing. Restore your backup.", status=404)
    return FileResponse(path.open("rb"), content_type="image/png")


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
        return error_page(request, "Choose a Slides to Anki backup ZIP.")
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
            "error": run.error,
            "issues": len(run.issues),
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
