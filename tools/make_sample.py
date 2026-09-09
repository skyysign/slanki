"""Rebuild the entirely synthetic sample; requires the development dependencies."""

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests" / "fixtures" / "synthetic"
TARGET.mkdir(parents=True, exist_ok=True)
slides = [
    (
        "Retrieval practice",
        "01 / MEMORY & LEARNING",
        [
            "Retrieval practice means trying to recall information from memory.",
            "A retrieval attempt happens before looking at the answer.",
            "Checking the answer gives feedback after the attempt.",
        ],
    ),
    (
        "Space your practice",
        "02 / MEMORY & LEARNING",
        [
            "Spaced practice distributes study sessions over time.",
            "Massed practice groups study into one continuous session.",
            "A review schedule decides when a card should be studied again.",
        ],
    ),
    (
        "Make a useful card",
        "03 / MEMORY & LEARNING",
        [
            "An atomic card tests one clear idea.",
            "A source reference points back to the supporting lecture page.",
            "An ambiguous question can have more than one plausible answer.",
        ],
    ),
]
pdf = canvas.Canvas(str(TARGET / "lecture.pdf"), pagesize=(960, 540), invariant=1)
pdf.setTitle("Memory and learning — synthetic test lecture")
for title, eyebrow, lines in slides:
    pdf.setFillColor(HexColor("#F5F7EE"))
    pdf.rect(0, 0, 960, 540, fill=1, stroke=0)
    pdf.setFillColor(HexColor("#7A886F"))
    pdf.setFont("Helvetica", 12)
    pdf.drawString(65, 473, eyebrow)
    pdf.setFillColor(HexColor("#234C3A"))
    pdf.setFont("Helvetica-Bold", 36)
    pdf.drawString(65, 405, title)
    pdf.setFont("Helvetica", 19)
    for offset, line in enumerate(lines):
        pdf.drawString(65, 316 - offset * 62, line)
    pdf.setFillColor(HexColor("#9A7A4D"))
    pdf.setFont("Helvetica", 11)
    pdf.drawString(65, 45, "SYNTHETIC EXAMPLE / prepared for application testing")
    pdf.showPage()
# Deliberately image-only page: the importer must flag it rather than imply coverage.
pdf.setFillColor(HexColor("#E9EEDD"))
pdf.rect(0, 0, 960, 540, fill=1, stroke=0)
for x in (170, 410, 650):
    pdf.setFillColor(HexColor("#476E53"))
    pdf.roundRect(x, 190, 140, 140, 22, fill=1, stroke=0)
pdf.showPage()
pdf.save()
print(f"Created synthetic sample at {TARGET / 'lecture.pdf'}")
