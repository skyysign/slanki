"""Bounded PDF work in a disposable subprocess, independent of Django."""

import json
import sys
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium


def extract(source, destination, max_pages):
    result = []
    with pdfplumber.open(source) as text_doc, pdfium.PdfDocument(source) as render_doc:
        if not 1 <= len(text_doc.pages) <= max_pages or len(render_doc) != len(text_doc.pages):
            raise ValueError(f"Use a PDF containing between 1 and {max_pages} pages.")
        for index, text_page in enumerate(text_doc.pages):
            text = text_page.extract_text() or ""
            if len(text) > 25000:
                raise ValueError(
                    f"Page {index + 1} contains too much text. Split this PDF into smaller pages."
                )
            page = render_doc[index]
            try:
                width, height = page.get_size()
                if not (0 < width <= 15000 and 0 < height <= 15000):
                    raise ValueError(f"Page {index + 1} has unsupported dimensions.")
                scale = min(1.7, 1500 / max(width, height))
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    filename = f"page-{index + 1:03}.png"
                    image.save(destination / filename)
                    result.append(
                        {
                            "number": index + 1,
                            "text": text,
                            "image": filename,
                            "width": image.width,
                            "height": image.height,
                            "warning": "No usable text found. This page needs manual cards; scans and diagrams are not interpreted."
                            if len(text.strip()) < 15
                            else "",
                        }
                    )
                finally:
                    bitmap.close()
            finally:
                page.close()
            text_page.close()
    (destination / "pages.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    try:
        extract(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
    except Exception:
        # Malformed PDF errors may contain document text. Return a fixed message.
        print(
            "The PDF could not be processed. Check that it is unencrypted and has supported page dimensions and length.",
            file=sys.stderr,
        )
        sys.exit(1)
