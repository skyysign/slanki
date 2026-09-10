from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("codex/", views.codex_connection, name="codex_connection"),
    path("codex/status/", views.codex_connection_status, name="codex_connection_status"),
    path("codex/connect/", views.connect_codex, name="connect_codex"),
    path("codex/cancel/", views.cancel_codex_login, name="cancel_codex_login"),
    path("upload/", views.upload, name="upload"),
    path("demo/", views.demo, name="demo"),
    path("restore/", views.restore, name="restore"),
    path("lectures/<uuid:pk>/", views.lecture, name="lecture"),
    path("lectures/<uuid:pk>/generate/", views.generate, name="generate"),
    path("lectures/<uuid:pk>/filter-logistics/", views.filter_logistics, name="filter_logistics"),
    path("lectures/<uuid:pk>/import/", views.import_cards, name="import_cards"),
    path("lectures/<uuid:pk>/prompt/", views.prompt, name="prompt"),
    path("lectures/<uuid:pk>/export/", views.export, name="export"),
    path("lectures/<uuid:pk>/preview/", views.preview_export, name="preview_export"),
    path("lectures/<uuid:pk>/preview-note/", views.preview_note, name="preview_note"),
    path("lectures/<uuid:pk>/backup/", views.backup, name="backup"),
    path("lectures/<uuid:pk>/add/", views.add_card, name="add_card"),
    path("cards/<uuid:pk>/save/", views.save_card, name="save_card"),
    path("pages/<int:pk>/image/", views.page_image, name="page_image"),
    path("runs/<uuid:pk>/cancel/", views.cancel_run, name="cancel_run"),
    path("runs/<uuid:pk>/resume/", views.resume_run, name="resume_run"),
    path("runs/<uuid:pk>/status/", views.run_status, name="run_status"),
]
