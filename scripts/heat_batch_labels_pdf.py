#!/usr/bin/env python
"""Print every Heat Batch label (QR + batch code) from the Rover database to one PDF.

Run from the repo root, inside the project's virtualenv (reportlab required:
``pip install reportlab``)::

    python scripts/heat_batch_labels_pdf.py --base http://192.168.1.20:8000 --out docs/heat-batch-labels.pdf

Options:
    --base     Address the phones use to reach the app (LAN IP or Render URL).
               Defaults to SITE_BASE_URL from settings/.env. A 127.0.0.1 or
               localhost base is refused - a phone cannot open it.
    --status   all | in_progress | completed   (default all)
    --out      Output path (default docs/heat-batch-labels-<date>.pdf)
    --sample   Build a layout sample with fake batches instead of reading the DB.

The QR payload is exactly what the app's own labels carry:
``<base>/scan/<qr_token>/`` - resolved by the ``scan`` URL - so a code
printed from this sheet lands on the same batch page as a code printed
from the app. Nothing here is hardcoded to a batch number format or host.
"""

import argparse
import datetime as dt
import math
import os
import sys
from decimal import Decimal

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# Sheet geometry: A4 portrait, 2 columns x 4 rows of 90 x 65 mm labels.
PAGE_W, PAGE_H = A4
LABEL_W, LABEL_H = 90 * mm, 65 * mm
COLS, ROWS = 2, 4
GUTTER = 6 * mm
MARGIN_X = (PAGE_W - COLS * LABEL_W - (COLS - 1) * GUTTER) / 2
MARGIN_Y = (PAGE_H - ROWS * LABEL_H - (ROWS - 1) * GUTTER) / 2
QR_SIZE = 36 * mm

LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0")


# ----------------------------------------------------------------------
# Data access (Django) - only imported when not running --sample
# ----------------------------------------------------------------------
def load_batches(status):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    sys.path.insert(0, os.getcwd())
    import django

    django.setup()
    from django.conf import settings
    from django.urls import reverse

    from apps.heat_treatment.models import HeatBatch

    qs = HeatBatch.objects.all().order_by("batch_no")
    if status != "all":
        qs = qs.filter(status=status)

    rows = []
    for batch in qs:
        rows.append(
            {
                "batch_no": batch.batch_no,
                "path": reverse("scan", kwargs={"token": batch.qr_token}),
                "status": batch.get_status_display() if hasattr(batch, "get_status_display") else batch.status,
                "created": getattr(batch, "created_at", None),
                "traveller_types": _safe_list(batch, "traveller_types"),
                "wire_serials": _safe_list(batch, "wire_serials"),
                "received_kg": _safe(batch, "received_weight_total"),
            }
        )
    return rows, (getattr(settings, "SITE_BASE_URL", "") or "")


def _safe(obj, name):
    try:
        value = getattr(obj, name)
        return value() if callable(value) else value
    except Exception:  # a property that needs data this batch lacks
        return None


def _safe_list(obj, name):
    value = _safe(obj, name)
    if value is None:
        return []
    try:
        return [str(v) for v in value]
    except TypeError:
        return [str(value)]


def sample_batches(n=8):
    today = dt.datetime.now()
    types = ["U1UM UDR", "EM1 FLAT", "RC1 HNO", "M2 UDR", "EL1 FLAT"]
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "batch_no": f"B{i:03d}",
                "path": f"/scan/SAMPLETOKEN{i:02d}xxxxxxxxxxxx/",
                "status": "Completed" if i % 3 else "In Progress",
                "created": today - dt.timedelta(days=n - i),
                "traveller_types": types[: 1 + i % 3],
                "wire_serials": [f"SB{300 + i * 2}", f"SB{301 + i * 2}"][: 1 + i % 2],
                "received_kg": Decimal("41.50") + i,
            }
        )
    return rows


# ----------------------------------------------------------------------
# Drawing
# ----------------------------------------------------------------------
def draw_qr(c, url, x, y, size):
    widget = QrCodeWidget(url, barLevel="Q", barBorder=4)
    b = widget.getBounds()
    w, h = b[2] - b[0], b[3] - b[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(widget)
    renderPDF.draw(d, c, x, y)


def draw_code128(c, text, x, y, width, height):
    bc = code128.Code128(text, barHeight=height, barWidth=0.33 * mm, humanReadable=False)
    scale = min(1.0, width / bc.width)
    c.saveState()
    c.translate(x + (width - bc.width * scale) / 2, y)
    c.scale(scale, 1)
    bc.drawOn(c, 0, 0)
    c.restoreState()


def fit(text, max_chars):
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def wrap(c, text, font, size, width, max_lines):
    """Break `text` on commas/spaces so every line fits `width`; the last
    allowed line is truncated with an ellipsis if there is still more."""
    words = text.replace(", ", ",\u200b ").split(" ")
    lines, current = [], ""
    for word in words:
        word = word.replace("\u200b", "")
        trial = (current + " " + word).strip()
        if c.stringWidth(trial, font, size) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and c.stringWidth(last + "…", font, size) > width:
            last = last[:-1]
        lines[-1] = last.rstrip(", ") + "…"
    return lines


def draw_label(c, row, base_url, x, y, code128_line=True):
    url = f"{base_url}{row['path']}"

    # Frame + cut marks
    c.setStrokeColorRGB(0.82, 0.83, 0.86)
    c.setLineWidth(0.4)
    c.roundRect(x, y, LABEL_W, LABEL_H, 3 * mm)

    # QR on the left
    qr_x, qr_y = x + 5 * mm, y + LABEL_H - QR_SIZE - 5 * mm
    draw_qr(c, url, qr_x, qr_y, QR_SIZE)

    # Batch code under the QR - the human-readable key
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(qr_x + QR_SIZE / 2, y + 12 * mm, row["batch_no"])

    # Details on the right - a fixed-width column, values wrapped to fit
    tx = x + QR_SIZE + 10 * mm
    col_w = LABEL_W - QR_SIZE - 15 * mm          # width available for text
    val_x = tx + 19 * mm
    val_w = col_w - 19 * mm
    top = y + LABEL_H - 8.5 * mm
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColorRGB(0.89, 0.12, 0.18)
    c.drawString(tx, top, "ROVER · HEAT BATCH")

    lines = [
        ("Batch", row["batch_no"], 1),
        ("Status", str(row["status"] or "-"), 1),
        ("Created", row["created"].strftime("%d %b %Y") if row["created"] else "-", 1),
        ("Traveller", ", ".join(row["traveller_types"]) or "-", 3),
        ("Wire serials", ", ".join(row["wire_serials"]) or "-", 2),
        ("Received", f"{row['received_kg']} kg" if row["received_kg"] is not None else "-", 1),
    ]
    yy = top - 6 * mm
    for label, value, max_lines in lines:
        c.setFont("Helvetica", 6.5)
        c.setFillColorRGB(0.42, 0.45, 0.52)
        c.drawString(tx, yy, label.upper())
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.12, 0.15, 0.2)
        for part in wrap(c, value, "Helvetica", 8, val_w, max_lines):
            c.drawString(val_x, yy, part)
            yy -= 4.2 * mm
        yy -= 0.8 * mm

    # Code128 of the batch number along the bottom (for laser scanners)
    if code128_line:
        draw_code128(c, row["batch_no"], tx, y + 6 * mm, col_w, 6 * mm)

    # Scan URL in tiny text - readable without a camera
    c.setFont("Helvetica", 5.5)
    c.setFillColorRGB(0.6, 0.62, 0.68)
    c.drawString(x + 5 * mm, y + 3 * mm, fit(url, 70))


def build_pdf(rows, base_url, out_path, sample=False):
    c = canvas.Canvas(out_path, pagesize=A4)
    c.setTitle("Rover Traveller - Heat batch labels")
    per_page = COLS * ROWS
    pages = max(1, math.ceil(len(rows) / per_page))
    stamp = dt.datetime.now().strftime("%d %b %Y %H:%M")

    for page in range(pages):
        chunk = rows[page * per_page : (page + 1) * per_page]
        for i, row in enumerate(chunk):
            col, r = i % COLS, i // COLS
            x = MARGIN_X + col * (LABEL_W + GUTTER)
            y = PAGE_H - MARGIN_Y - (r + 1) * LABEL_H - r * GUTTER
            draw_label(c, row, base_url, x, y)
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.5, 0.5, 0.55)
        c.drawString(MARGIN_X, 8 * mm, f"Rover Traveller · Heat batch labels · generated {stamp} · {base_url}")
        c.drawRightString(PAGE_W - MARGIN_X, 8 * mm, f"Page {page + 1} of {pages}")
        c.showPage()
    c.save()
    return pages


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="", help="Base URL phones use, e.g. http://192.168.1.20:8000")
    ap.add_argument("--status", default="all", choices=["all", "in_progress", "completed"])
    ap.add_argument("--out", default="")
    ap.add_argument("--sample", action="store_true", help="Layout sample with fake batches; no database")
    args = ap.parse_args()

    if args.sample:
        rows, settings_base = sample_batches(), ""
    else:
        rows, settings_base = load_batches(args.status)

    base = (args.base or settings_base).strip().rstrip("/")
    if not base:
        if args.sample:
            base = "http://SET-SITE-BASE-URL"
        else:
            sys.exit("No base URL. Pass --base http://<LAN-IP>:8000 or set SITE_BASE_URL in .env.")
    if any(h in base for h in LOCAL_HOSTS) and not args.sample:
        sys.exit(f"Refusing to print labels pointing at {base}: a phone cannot open a localhost address.")

    if not rows:
        sys.exit("No heat batches found for that filter - nothing to print.")

    out = args.out or f"docs/heat-batch-labels{'-SAMPLE' if args.sample else ''}-{dt.date.today():%Y%m%d}.pdf"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    pages = build_pdf(rows, base, out, sample=args.sample)
    print(f"Wrote {out}: {len(rows)} labels on {pages} page(s); QR base {base}")


if __name__ == "__main__":
    main()
