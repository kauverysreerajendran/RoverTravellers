"""The label a heat batch carries: a QR code holding a URL.

A URL rather than a bare batch number, because a phone's own camera app
opens a URL natively - no scanner app, no keyboard entry. The payload is
`<SITE_BASE_URL>/scan/<qr_token>/`, and the base comes from settings (or
the request that is asking), never from a hostname written down here: a
QR pointing at 127.0.0.1 is unreadable from the shop floor.

The SVG is drawn here from the QR matrix rather than by an image library,
so the batch number can sit under the code in the same file, it stays
crisp at any print size, and it needs no Pillow.
"""

import qrcode
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils.html import escape

# Quiet zone, in modules, required either side of a QR code for a reader
# to find it.
QUIET_ZONE = 4
# Height reserved under the code for the batch number, in modules.
CAPTION_HEIGHT = 5


def site_base_url(request=None) -> str:
    """Where a phone should come back to. `SITE_BASE_URL` wins, so a LAN
    IP or the Render hostname can be set without touching code; failing
    that, whatever host this request arrived on."""
    base = (getattr(settings, "SITE_BASE_URL", "") or "").strip().rstrip("/")
    if base:
        return base
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    return ""


def scan_url(batch, request=None) -> str:
    """The URL the batch's QR carries."""
    return f"{site_base_url(request)}{reverse('scan', kwargs={'token': batch.qr_token})}"


def render_qr_svg(batch, request=None, *, caption=True) -> str:
    """The batch's QR as an SVG document, cached per batch and URL."""
    url = scan_url(batch, request)
    key = f"heat-batch-qr:{batch.pk}:{url}:{int(caption)}"
    svg = cache.get(key)
    if svg is None:
        svg = _qr_svg(url, batch.batch_no if caption else "")
        cache.set(key, svg, 60 * 60 * 24)
    return svg


def render_code128_svg(batch) -> str:
    """The batch number as a Code128 barcode, for hand-held laser scanners.
    Off unless `BATCH_LABEL_CODE128` is on, and silently absent if the
    optional dependency is not installed."""
    if not getattr(settings, "BATCH_LABEL_CODE128", False):
        return ""
    try:
        from barcode import Code128
        from barcode.writer import SVGWriter
    except ImportError:
        return ""
    import io

    buffer = io.BytesIO()
    Code128(batch.batch_no, writer=SVGWriter()).write(buffer, {"module_height": 8.0, "font_size": 8})
    return buffer.getvalue().decode("utf-8")


# ----------------------------------------------------------------------
def _qr_svg(payload: str, caption: str) -> str:
    """One <svg> per QR: the matrix as a path of module squares, with the
    batch number under it so a printed label is readable by eye as well as
    by camera."""
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=0,
    )
    code.add_data(payload)
    code.make(fit=True)
    matrix = code.get_matrix()

    size = len(matrix)
    width = size + QUIET_ZONE * 2
    height = width + (CAPTION_HEIGHT if caption else 0)

    squares = "".join(
        f"M{x + QUIET_ZONE} {y + QUIET_ZONE}h1v1h-1z"
        for y, row in enumerate(matrix)
        for x, filled in enumerate(row)
        if filled
    )
    text = ""
    if caption:
        text = (
            f'<text x="{width / 2}" y="{width + CAPTION_HEIGHT - 1.4}" text-anchor="middle" '
            f'font-family="monospace" font-size="3.2" fill="#000">{escape(caption)}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" height="100%" shape-rendering="crispEdges" role="img" '
        f'aria-label="Batch {escape(caption or payload)}">'
        # The payload in plain text as well as in the matrix: it is the
        # image's description, and it makes what a label points at
        # readable without a camera.
        f'<desc>{escape(payload)}</desc>'
        f'<rect width="{width}" height="{height}" fill="#fff"/>'
        f'<path d="{squares}" fill="#000"/>{text}</svg>'
    )
