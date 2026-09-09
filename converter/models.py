import time
import uuid

from django.db import models
from django.urls import reverse


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


class GenerationRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lecture = models.ForeignKey(Lecture, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=16, default="queued")
    provider = models.CharField(max_length=30, default="codex")
    page_numbers = models.JSONField(default=list, blank=True)
    completed_pages = models.JSONField(default=list, blank=True)
    cards_added = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    back = models.TextField()
    source_quote = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="draft")
    fingerprint = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    anki_modified = models.PositiveBigIntegerField(default=unix_seconds)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    back = models.TextField()
    source_quote = models.TextField(blank=True)
    status = models.CharField(max_length=12)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["version"]
        constraints = [
            models.UniqueConstraint(fields=["card", "version"], name="unique_card_revision")
        ]
