"""Generates the tray icon images in memory (no icon asset files to ship).

The base mark is the app's brand -- two interlocking arrows forming a sync
symbol, on a navy circle -- kept constant regardless of health. A small
colored dot is composited in the bottom-right corner on top of it (the same
pattern Dropbox/OneDrive use for their tray icons) to carry the live
green/yellow/red/gray status signal from the design spec's icon-state table,
without the brand mark itself changing color or shape.

The tray glyph is a single-ring two-arrow sync/refresh mark rather than
logo.svg's two interlocking rings -- PIL's arc() can only sweep clockwise,
and an earlier two-ring version relied on a wraparound trick to fake a
mirrored ring that actually produced an arrowhead pointing the wrong way.
This version was rendered at 16/24/64px and visually inspected before being
adopted; run `python -c "from print_agent.icons import make_icon;
make_icon('green').save('test.png')"` if you change the geometry again.
"""
import math
from PIL import Image, ImageDraw

STATUS_COLORS = {
    "green": (18, 183, 106),
    "yellow": (247, 144, 9),
    "red": (240, 68, 56),
    "gray": (152, 162, 179),
}
NAVY = (11, 18, 32)
WHITE = (255, 255, 255)

# Back-compat alias -- earlier version of this module exposed COLORS.
COLORS = STATUS_COLORS


def _point_on_circle(cx, cy, r, angle_deg):
    a = math.radians(angle_deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def _tangent_dir(angle_deg, clockwise=True):
    a = math.radians(angle_deg)
    d = (-math.sin(a), math.cos(a))
    if not clockwise:
        d = (-d[0], -d[1])
    return d


def _arrowhead_polygon(base_point, direction, length, width):
    dx, dy = direction
    px, py = -dy, dx
    bx, by = base_point
    tip = (bx + dx * length, by + dy * length)
    b1 = (bx + px * width / 2, by + py * width / 2)
    b2 = (bx - px * width / 2, by - py * width / 2)
    return [tip, b1, b2]


def _draw_sync_mark(draw, cx, cy, r, color):
    """Draws a two-arrow sync/refresh mark on a single ring of radius r,
    centered at (cx, cy). Both arrows sweep clockwise -- PIL's arc() only
    supports clockwise sweeps, so (unlike logo.svg's true mirrored loops)
    this uses one ring with two arcs on opposite sides rather than two
    offset rings, which avoids needing a counter-clockwise sweep at all.
    Verified by rendering and visually inspecting the output (see the
    module docstring) after an earlier two-ring version produced an
    arrowhead pointing the wrong way."""
    lw = max(2, round(r * 0.22))
    arrow_len = lw * 1.4
    arrow_w = lw * 1.2

    bbox = [cx - r, cy - r, cx + r, cy + r]

    draw.arc(bbox, 200, 320, fill=color, width=lw)
    end1 = _point_on_circle(cx, cy, r, 320)
    d1 = _tangent_dir(320, clockwise=True)
    draw.polygon(_arrowhead_polygon(end1, d1, arrow_len, arrow_w), fill=color)

    draw.arc(bbox, 20, 140, fill=color, width=lw)
    end2 = _point_on_circle(cx, cy, r, 140)
    d2 = _tangent_dir(140, clockwise=True)
    draw.polygon(_arrowhead_polygon(end2, d2, arrow_len, arrow_w), fill=color)


def make_icon(status_color_name, size=64):
    """Navy circle brand mark with the white sync glyph, plus a small
    status-colored badge in the bottom-right corner. Signature unchanged
    from the previous plain-dot version, so tray.py needs no changes."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = round(size * 0.04)
    draw.ellipse([margin, margin, size - margin, size - margin], fill=NAVY)

    mark_r = size * 0.30
    _draw_sync_mark(draw, size / 2, size / 2, mark_r, WHITE)

    badge_r = size * 0.16
    badge_cx = size - margin - badge_r * 0.7
    badge_cy = size - margin - badge_r * 0.7
    badge_color = STATUS_COLORS.get(status_color_name, STATUS_COLORS["gray"])
    ring = badge_r * 1.25
    draw.ellipse(
        [badge_cx - ring, badge_cy - ring, badge_cx + ring, badge_cy + ring],
        fill=NAVY,
    )
    draw.ellipse(
        [badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r],
        fill=badge_color,
    )

    return img


def overall_color(snapshot):
    if snapshot.get("server_ok") is False:
        return "red"
    printer_status = snapshot.get("printer_status", {})
    if printer_status and not all(p.get("ok") for p in printer_status.values()):
        return "yellow"
    if snapshot.get("server_ok") is None:
        return "gray"
    return "green"
