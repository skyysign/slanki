"""One source-linked rectangular crop per note, rendered from its original PNG."""

import io

from PIL import Image

from .files import WorkflowError, media_path


def checked_crop(value, page):
    if value == {}:
        return {}
    keys = {"page", "left", "top", "right", "bottom", "on_question"}
    if not isinstance(value, dict) or set(value) != keys:
        raise WorkflowError("Choose a rectangular crop from this note's source page.")
    if (
        any(type(value[key]) is not int for key in keys - {"on_question"})
        or type(value["on_question"]) is not bool
    ):
        raise WorkflowError("Crop coordinates must be whole pixels.")
    if value["page"] != page.number or not (
        0 <= value["left"] < value["right"] <= page.width
        and 0 <= value["top"] < value["bottom"] <= page.height
        and value["right"] - value["left"] >= 2
        and value["bottom"] - value["top"] >= 2
    ):
        raise WorkflowError(
            "Keep the crop inside this note's source slide and at least 2 pixels wide and high."
        )
    return dict(value)


def crop_png(page, crop):
    crop = checked_crop(crop, page)
    if not crop:
        raise WorkflowError("This note has no source crop.")
    path = media_path(page.image)
    try:
        # Inspect dimensions before decoding. Only bounded PNGs rendered by the app
        # are supported, including after backup restore.
        with Image.open(path, formats=["PNG"]) as image:
            if image.size != (page.width, page.height) or not (
                0 < image.width <= 1500 and 0 < image.height <= 1500
            ):
                raise WorkflowError("The source image dimensions do not match the saved slide.")
            with image.crop(
                tuple(crop[key] for key in ("left", "top", "right", "bottom"))
            ) as selected:
                output = io.BytesIO()
                selected.save(output, format="PNG")
                return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, WorkflowError):
            raise
        raise WorkflowError(
            "Could not read this source image. Restore a backup before cropping."
        ) from exc


def crop_from_form(values, page):
    if values.get("crop_enabled") != "yes":
        return {}
    try:
        crop = {
            key: int(values.get("crop_" + key, "")) for key in ("left", "top", "right", "bottom")
        }
    except (ValueError, TypeError) as exc:
        raise WorkflowError("Select a crop or enter its four coordinates first.") from exc
    crop.update(page=page.number, on_question=values.get("crop_on_question") == "yes")
    return checked_crop(crop, page)
