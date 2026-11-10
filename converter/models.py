import time
import uuid

from django.db import models
from django.urls import reverse

from .services.note_types import CARD_FORMATS, LEARNING_FOCUSES, NOTE_TYPES, study_card_count
from .services.providers import EFFORTS, PROVIDERS


def unix_seconds():
    return int(time.time())


class Lecture(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=180)
    sha256 = models.CharField(max_length=64, unique=True)
    original_name = models.CharField(max_length=255)
    original_file = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def get_absolute_url(self):
        return reverse("lecture", args=[self.pk])


class Page(models.Model):
    lecture = models.ForeignKey(Lecture, on_delete=models.CASCADE, related_name="pages")
    number = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    image = models.CharField(max_length=255)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    warning = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["lecture", "number"], name="unique_lecture_page")
        ]


class PendingFileDeletion(models.Model):
    """Committed set deletions whose private source directory still needs removal."""

    id = models.UUIDField(primary_key=True, editable=False)
    title = models.CharField(max_length=180)


class GenerationRun(models.Model):
    REASONING_LEVELS = EFFORTS
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lecture = models.ForeignKey(Lecture, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=16, default="queued")
    provider = models.CharField(max_length=30, default="codex")
    model = models.CharField(max_length=100, default="", blank=True)
    page_numbers = models.JSONField(default=list, blank=True)
    completed_pages = models.JSONField(default=list, blank=True)
    context_enabled = models.BooleanField(default=False)
    context_data = models.JSONField(default=dict, blank=True)
    text_enabled = models.BooleanField(default=True)
    occlusion_enabled = models.BooleanField(default=False)
    image_completed_pages = models.JSONField(default=list, blank=True)
    visual_enabled = models.BooleanField(default=False)
    purpose = models.CharField(
        max_length=12, default="cards", choices=[("cards", "Cards"), ("rundown", "Lecture rundown")]
    )
    rundown_data = models.JSONField(default=dict, blank=True)
    issues = models.JSONField(default=list, blank=True)
    worker_token = models.UUIDField(default=uuid.uuid4, editable=False)
    cards_added = models.PositiveIntegerField(default=0)
    study_cards_added = models.PositiveIntegerField(default=0)
    learning_focus = models.CharField(max_length=20, choices=LEARNING_FOCUSES, default="balanced")
    card_format = models.CharField(max_length=20, choices=CARD_FORMATS, default="basic")
    card_limit = models.PositiveIntegerField(null=True, blank=True)
    reasoning_effort = models.CharField(
        max_length=12, choices=REASONING_LEVELS, default="", blank=True
    )
    filtered_count = models.PositiveIntegerField(default=0)
    over_limit_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def provider_label(self):
        return dict(PROVIDERS).get(self.provider, self.provider)

    @property
    def model_label(self):
        return self.model or "CLI default"

    @property
    def format_label(self):
        if self.purpose == "rundown":
            return "Lecture rundown"
        text = self.get_card_format_display() if self.text_enabled else ""
        return " + ".join(
            filter(
                None,
                [
                    text,
                    "Image occlusion" if self.occlusion_enabled else "",
                    "Graphs & formulas" if self.visual_enabled else "",
                ],
            )
        )

    @property
    def image_phase(self):
        return (self.occlusion_enabled or self.visual_enabled) and len(
            self.image_completed_pages
        ) < len(self.page_numbers)

    @property
    def progress_pages(self):
        if self.image_phase or not self.text_enabled:
            return self.image_completed_pages
        return self.completed_pages

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["lecture"],
                condition=models.Q(status__in=["queued", "running"]),
                name="one_active_generation",
            )
        ]


class Card(models.Model):
    STATUS = [("draft", "Draft"), ("accepted", "Accepted"), ("rejected", "Rejected")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lecture = models.ForeignKey(Lecture, on_delete=models.CASCADE, related_name="cards")
    page = models.ForeignKey(Page, on_delete=models.PROTECT, related_name="cards")
    run = models.ForeignKey(GenerationRun, null=True, blank=True, on_delete=models.SET_NULL)
    front = models.TextField()
    back = models.TextField(blank=True)
    note_type = models.CharField(max_length=12, choices=NOTE_TYPES, default="basic")
    source_quote = models.TextField(blank=True)
    source_crop = models.JSONField(default=dict, blank=True)
    occlusion = models.JSONField(default=dict, blank=True)
    visual_masks = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="draft")
    fingerprint = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    anki_modified = models.PositiveBigIntegerField(default=unix_seconds)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def study_card_count(self):
        return study_card_count(self.front, self.note_type)

    class Meta:
        ordering = ["page__number", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["lecture", "fingerprint"], name="unique_generated_question"
            )
        ]


class CardRevision(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="revisions")
    version = models.PositiveIntegerField()
    front = models.TextField()
    back = models.TextField(blank=True)
    note_type = models.CharField(max_length=12, choices=NOTE_TYPES, default="basic")
    source_quote = models.TextField(blank=True)
    source_crop = models.JSONField(default=dict, blank=True)
    occlusion = models.JSONField(default=dict, blank=True)
    visual_masks = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=12)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["version"]
        constraints = [
            models.UniqueConstraint(fields=["card", "version"], name="unique_card_revision")
        ]


class OcclusionSuggestion(models.Model):
    STATUS = [("pending", "To review"), ("accepted", "Accepted"), ("discarded", "Discarded")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(GenerationRun, on_delete=models.CASCADE, related_name="suggestions")
    page = models.ForeignKey(Page, on_delete=models.PROTECT)
    label = models.CharField(max_length=120)
    reason = models.CharField(max_length=300)
    original_mask = models.JSONField()
    mask = models.JSONField()
    front = models.TextField(default="Name the hidden part.")
    back = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="pending")
    version = models.PositiveIntegerField(default=1)
    card = models.ForeignKey(Card, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["page__number", "created_at", "id"]
