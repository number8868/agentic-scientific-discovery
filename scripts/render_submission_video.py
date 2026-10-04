#!/usr/bin/env python3
"""Render a narrated NOVA-MAT evidence-replay video from a storyboard JSON.

The renderer is deliberately offline: it only reads the supplied storyboard and
scene WAVs, draws slides with Pillow, and pipes frames to a local FFmpeg binary.
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


W, H = 1920, 1080
FPS = 30
NAVY = (7, 17, 31)
PANEL = (14, 31, 49)
PANEL_2 = (18, 39, 58)
TEAL = (70, 221, 207)
CORAL = (255, 132, 122)
WHITE = (239, 247, 250)
MUTED = (159, 182, 196)
LINE = (39, 67, 84)
TRANSITION_SEC = 0.42
TAIL_SEC = 0.55
MIN_SCENE_SEC = 3.2
MAX_VIDEO_SEC = 59.0
TARGET_VIDEO_SEC = 55.0


def fail(message: str) -> None:
    raise SystemExit(f"render_submission_video: {message}")


def choose_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    candidates: list[str]
    if mono:
        candidates = [
            r"C:\Windows\Fonts\CascadiaMono.ttf",
            r"C:\Windows\Fonts\consola.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
    elif bold:
        candidates = [
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


FONTS = {
    "display": choose_font(58, bold=True),
    "hero": choose_font(94, bold=True),
    "large": choose_font(52, bold=True),
    "medium": choose_font(34, bold=True),
    "body": choose_font(26),
    "small": choose_font(20),
    "tiny": choose_font(16),
    "mono": choose_font(22, mono=True),
    "caption": choose_font(31),
}


@lru_cache(maxsize=1024)
def fit_font(text: str, max_width: int, start_size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    size = start_size
    while size > 24:
        font = choose_font(size, bold=bold)
        if ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)[2] <= max_width:
            return font
        size -= 2
    return choose_font(max(24, size), bold=bold)


def make_background(width: int, height: int) -> Image.Image:
    # A restrained two-tone gradient with soft teal/coral light near the corners.
    yy, xx = np.mgrid[0:height, 0:width]
    t = (yy / max(1, height - 1))[..., None]
    top = np.array([7.0, 17.0, 31.0], dtype=np.float32)
    bottom = np.array([10.0, 27.0, 42.0], dtype=np.float32)
    pixels = top + (bottom - top) * t
    teal_glow = np.exp(-(((xx - width * 0.89) / (width * 0.37)) ** 2 + ((yy - height * 0.22) / (height * 0.54)) ** 2) * 2.1)
    coral_glow = np.exp(-(((xx - width * 0.08) / (width * 0.27)) ** 2 + ((yy - height * 0.87) / (height * 0.5)) ** 2) * 2.4)
    pixels[..., 1] += teal_glow * 5.0 + coral_glow * 1.1
    pixels[..., 2] += teal_glow * 7.0 + coral_glow * 3.0
    image = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    for x in range(58, width, 96):
        draw.line((x, 0, x, height), fill=(78, 143, 164, 11), width=1)
    for y in range(40, height, 96):
        draw.line((0, y, width, y), fill=(78, 143, 164, 11), width=1)
    draw.line((0, 868, width, 868), fill=(77, 119, 139, 70), width=1)
    return image


BACKGROUND = make_background(W, H)


def smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def wrap_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    words = str(text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    max_width: int,
    line_gap: int = 8,
    max_lines: int | None = None,
) -> int:
    lines = wrap_lines(draw, text, font, max_width)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            while lines[-1] and draw.textbbox((0, 0), lines[-1] + "…", font=font)[2] > max_width:
                lines[-1] = lines[-1][:-1]
            lines[-1] = lines[-1].rstrip() + "…"
    y = xy[1]
    for line in lines:
        draw.text((xy[0], y), line, font=font, fill=fill)
        box = draw.textbbox((xy[0], y), line, font=font)
        y += box[3] - box[1] + line_gap
    return y


def rounded_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int] = PANEL,
    outline: tuple[int, int, int] = LINE,
    radius: int = 22,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pick(mapping: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return default


def item_parts(item: Any) -> tuple[str, str, str, str]:
    if not isinstance(item, dict):
        return str(item), "", "", ""
    label = pick(item, "label", "title", "name", "metric", "step", "key", "id", default="Evidence")
    value = pick(item, "value", "count", "number", "actual", "result_value", "amount")
    detail = pick(item, "detail", "description", "note", "subtitle", "result", "method", "text")
    tag = pick(item, "tag", "type", "phase", "state", "status")
    return str(label), str(value), str(detail), str(tag)


def scene_items(scene: dict[str, Any]) -> list[Any]:
    layout = str(scene.get("layout", "")).lower().replace("-", "_")
    if layout in {"sensitivity", "table", "comparison", "gate_table"}:
        keys = ("rows", "metrics", "items")
    elif layout in {"decision", "choice", "options"}:
        keys = ("options", "items", "metrics")
    elif layout in {"primary", "metrics"}:
        keys = ("metrics", "items", "cards")
    else:
        keys = ("items", "cards", "steps", "options", "metrics", "rows")
    for key in keys:
        value = scene.get(key)
        if isinstance(value, list) and value:
            return value
    return []


def draw_info_cards(draw: ImageDraw.ImageDraw, items: list[Any], top: int, t: float, max_items: int = 3, height: int = 190) -> None:
    visible = items[:max_items]
    if not visible:
        return
    gap = 20
    left, right = 94, W - 94
    card_w = (right - left - gap * (len(visible) - 1)) // len(visible)
    for i, item in enumerate(visible):
        label, value, detail, tag = item_parts(item)
        x = left + i * (card_w + gap)
        lift = int((1.0 - smoothstep((t - 0.10 - 0.1 * i) / 0.52)) * 16)
        accent = CORAL if tag.lower() in {"warning", "risk", "blocked", "limit"} else TEAL
        rounded_panel(draw, (x, top + lift, x + card_w, top + height + lift), PANEL_2 if i == 0 else PANEL, outline=(accent[0] // 2, accent[1] // 2, accent[2] // 2))
        draw.rounded_rectangle((x + 23, top + 23 + lift, x + 29, top + 65 + lift), radius=3, fill=accent)
        draw_text_block(draw, label, (x + 47, top + 22 + lift), FONTS["small"], accent, card_w - 72, line_gap=3, max_lines=2)
        body = value or detail
        body_font = FONTS["body"] if len(body) < 95 else FONTS["small"]
        draw_text_block(draw, body, (x + 28, top + 80 + lift), body_font, WHITE, card_w - 56, line_gap=5, max_lines=3)
        if detail and value:
            draw_text_block(draw, detail, (x + 29, top + height - 42 + lift), FONTS["tiny"], MUTED, card_w - 58, line_gap=2, max_lines=1)


def item_numeric(item: Any) -> float | None:
    _, value, _, _ = item_parts(item)
    if not value:
        return None
    text = value.replace(",", "").replace("%", "").replace("pp", "").strip()
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    try:
        return float(match.group(0)) if match else None
    except ValueError:
        return None


def draw_header(draw: ImageDraw.ImageDraw, video_title: str, scene: dict[str, Any], index: int, count: int, evidence: dict[str, Any]) -> int:
    draw.rounded_rectangle((82, 52, 91, 100), radius=4, fill=TEAL)
    run_label = str(pick(evidence, "run_label", default="")).strip()
    replay_label = str(pick(evidence, "replay_label", default=run_label or "NOVA-MAT  ·  RECORDED EVIDENCE"))
    label_font = fit_font(replay_label, 1355, 19, bold=False)
    draw.text((113, 58), replay_label, font=label_font, fill=(186, 213, 220))
    draw.text((1552, 57), "NOVA-MAT", font=FONTS["small"], fill=TEAL)
    draw.text((1748, 60), f"{index:02d} / {count:02d}", font=FONTS["small"], fill=MUTED)

    kicker = str(pick(scene, "kicker", "eyebrow", default=video_title)).strip()
    if kicker:
        draw.text((96, 127), kicker.upper(), font=FONTS["tiny"], fill=TEAL)
    title = str(pick(scene, "title", default="Evidence replay"))
    hero_title = scene.get("layout") == "title" and title == "NOVA-MAT"
    title_font = FONTS["hero"] if hero_title else fit_font(title, 1690, 58)
    y = draw_text_block(draw, title, (94, 158), title_font, WHITE, 1690, line_gap=4, max_lines=2)
    subtitle = str(pick(scene, "subtitle", "subhead", default=""))
    if subtitle:
        subtitle_y = draw.textbbox((94, 158), title, font=title_font)[3] + 12 if hero_title else max(222, y + 5)
        y = draw_text_block(draw, subtitle, (98, subtitle_y), FONTS["body"], MUTED, 1660, line_gap=5, max_lines=2)
    return min(330 if hero_title else 310, max(260, y + 22))


def draw_metric_cards(draw: ImageDraw.ImageDraw, items: list[Any], top: int, duration: float, t: float) -> None:
    if not items:
        return
    n = min(4, len(items))
    gap = 22
    left, right = 94, W - 94
    card_w = (right - left - gap * (n - 1)) // n
    for i, item in enumerate(items[:n]):
        x = left + i * (card_w + gap)
        y = top + 5
        entrance = smoothstep((t - 0.12 - i * 0.10) / 0.48)
        lift = int((1.0 - entrance) * 22)
        box = (x, y + lift, x + card_w, y + 250 + lift)
        label, value, detail, tag = item_parts(item)
        accent = CORAL if (tag.lower() in {"warning", "risk", "holdout", "limit"} or "not executed" in label.lower()) else TEAL
        rounded_panel(draw, box, fill=PANEL_2 if i % 2 else PANEL, outline=(accent[0] // 2, accent[1] // 2, accent[2] // 2))
        draw.rounded_rectangle((x + 24, y + 29 + lift, x + 31, y + 77 + lift), radius=3, fill=accent)
        draw_text_block(draw, label.upper(), (x + 52, y + 28 + lift), FONTS["tiny"], MUTED, card_w - 80, max_lines=2)
        # Scientific observations must remain verbatim; animate only the card entrance.
        number = value
        if number:
            font = fit_font(number, card_w - 62, 54)
            draw.text((x + 29, y + 86 + lift), number, font=font, fill=WHITE)
        else:
            draw_text_block(draw, label, (x + 28, y + 91 + lift), FONTS["medium"], WHITE, card_w - 58, max_lines=2)
        if detail:
            draw_text_block(draw, detail, (x + 30, y + 166 + lift), FONTS["small"], MUTED, card_w - 58, line_gap=4, max_lines=3)


def draw_choice_cards(draw: ImageDraw.ImageDraw, items: list[Any], top: int, selected: Any, t: float) -> None:
    if not items:
        return
    n = min(4, len(items))
    gap = 22
    left, right = 94, W - 94
    card_w = (right - left - gap * (n - 1)) // n
    selected_text = str(selected).lower()
    for i, item in enumerate(items[:n]):
        label, value, detail, tag = item_parts(item)
        is_selected = bool(tag.lower() in {"selected", "chosen", "winner"} or str(item.get("selected", "")).lower() == "true") if isinstance(item, dict) else False
        is_selected = is_selected or (selected_text and (selected_text == label.lower() or selected_text == value.lower()))
        accent = TEAL if is_selected else (CORAL if tag.lower() in {"blocked", "stop", "limit"} else LINE)
        x = left + i * (card_w + gap)
        y = top + int((1.0 - smoothstep((t - i * 0.08) / 0.52)) * 18)
        rounded_panel(draw, (x, y, x + card_w, y + 286), PANEL_2 if is_selected else PANEL, outline=accent, width=3 if is_selected else 2)
        badge = "SELECTED" if is_selected else (tag.upper() if tag else f"OPTION {i + 1}")
        draw.text((x + 28, y + 27), badge[:26], font=FONTS["tiny"], fill=accent)
        draw_text_block(draw, label, (x + 28, y + 70), FONTS["medium"], WHITE, card_w - 56, line_gap=4, max_lines=2)
        if value and value != label:
            draw_text_block(draw, value, (x + 28, y + 145), FONTS["large"], accent, card_w - 56, max_lines=1)
        if detail:
            draw_text_block(draw, detail, (x + 30, y + 211), FONTS["small"], MUTED, card_w - 58, line_gap=4, max_lines=3)


def draw_bars(draw: ImageDraw.ImageDraw, items: list[Any], top: int, t: float) -> None:
    if not items:
        return
    left, right = 130, W - 130
    row_h = min(77, 400 // max(1, min(6, len(items))))
    visible = items[:6]
    nums = [item_numeric(item) for item in visible]
    maximum = max([v for v in nums if v is not None and v > 0] or [1.0])
    for i, item in enumerate(visible):
        label, value, detail, tag = item_parts(item)
        y = top + i * row_h
        draw.text((left, y), label[:40], font=FONTS["small"], fill=WHITE)
        if detail:
            draw.text((left + 390, y + 2), detail[:55], font=FONTS["tiny"], fill=MUTED)
        draw.text((right - 220, y), value or tag, font=FONTS["small"], fill=TEAL)
        bar_y = y + 38
        draw.rounded_rectangle((left, bar_y, right, bar_y + 13), radius=7, fill=(30, 52, 66))
        number = nums[i]
        fraction = max(0.035, min(1.0, (number / maximum) if number is not None and number > 0 else 0.12))
        fraction *= smoothstep((t - 0.35 - i * 0.07) / 0.8)
        draw.rounded_rectangle((left, bar_y, left + int((right - left) * fraction), bar_y + 13), radius=7, fill=TEAL if i == 0 else (76, 170, 171))


def draw_sensitivity(draw: ImageDraw.ImageDraw, scene: dict[str, Any], top: int, t: float) -> None:
    rows = scene.get("rows", [])
    if not isinstance(rows, list) or not rows:
        draw_table(draw, scene, rows, top, t)
        return
    def numeric(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            if key in row:
                match = re.search(r"[-+]?\d+(?:\.\d+)?", str(row[key]).replace(",", ""))
                if match:
                    return float(match.group(0))
        return None
    first = next((r for r in rows if isinstance(r, dict)), {})
    if not first:
        return
    threshold_key = next((k for k in first if any(token in k.lower() for token in ("ehull", "threshold", "cutoff"))), next(iter(first)))
    value_keys = [k for k in first if k != threshold_key and not any(token in k.lower() for token in ("delta", "pp", "interval", "ci"))]
    value_keys = value_keys[:2]
    delta_key = next((k for k in first if "delta" in k.lower() or "pp" in k.lower()), None)
    if not value_keys:
        draw_table(draw, scene, rows, top, t)
        return
    values = [numeric(r, tuple(value_keys)) or 0 for r in rows if isinstance(r, dict)]
    maximum = max(values or [1])
    maximum = max(1.0, maximum)
    left, bar_left, bar_right = 126, 505, 1460
    legend_y = top + 10
    draw.ellipse((bar_left, legend_y + 5, bar_left + 15, legend_y + 20), fill=TEAL)
    draw.text((bar_left + 26, legend_y), value_keys[0].replace("_", " ").title(), font=FONTS["tiny"], fill=WHITE)
    if len(value_keys) > 1:
        draw.ellipse((bar_left + 254, legend_y + 5, bar_left + 269, legend_y + 20), fill=(111, 187, 255))
        draw.text((bar_left + 280, legend_y), value_keys[1].replace("_", " ").title(), font=FONTS["tiny"], fill=WHITE)
    draw.text((bar_right + 40, legend_y), "Δ pass-rate", font=FONTS["tiny"], fill=MUTED)
    row_height = 104
    chart_top = top + 47
    for i, row in enumerate(rows[:4]):
        if not isinstance(row, dict):
            continue
        y = chart_top + i * row_height
        threshold = str(row.get(threshold_key, ""))
        draw.text((left, y + 17), f"eHull  {threshold}", font=FONTS["small"], fill=WHITE)
        for j, key in enumerate(value_keys):
            value = numeric(row, (key,)) or 0
            by = y + j * 31 + 12
            draw.rounded_rectangle((bar_left, by, bar_right, by + 19), radius=9, fill=(29, 50, 65))
            amount = int((bar_right - bar_left) * max(0.025, min(1.0, value / maximum)) * smoothstep((t - 0.28 - i * 0.12) / 0.75))
            color = TEAL if j == 0 else (111, 187, 255)
            draw.rounded_rectangle((bar_left, by, bar_left + amount, by + 19), radius=9, fill=color)
            draw.text((bar_right + 14, by - 4), str(row.get(key, "")), font=FONTS["tiny"], fill=color)
        if delta_key:
            draw.text((bar_right + 40, y + 32), f"{row.get(delta_key, '')} pp", font=FONTS["small"], fill=TEAL)
    insights = scene.get("items", [])
    if isinstance(insights, list) and insights:
        draw_info_cards(draw, insights[:2], top + 363, t, max_items=2, height=133)


def extract_holdout_numbers(scene: dict[str, Any]) -> tuple[float, float, float] | None:
    estimate: float | None = None
    interval: tuple[float, float] | None = None
    for item in scene.get("items", []) if isinstance(scene.get("items", []), list) else []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).lower()
        value = str(item.get("value", ""))
        if "interval" in label or "confidence" in label:
            match = re.search(r"\[\s*([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)\s*\]", value)
            if match:
                interval = (float(match.group(1)), float(match.group(2)))
        elif "difference" in label or "estimate" in label:
            match = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
            if match:
                estimate = float(match.group(0))
    structured = scene.get("holdout_ci", scene.get("confidence_interval", {}))
    if isinstance(structured, dict):
        try:
            estimate = float(structured.get("estimate_pp", structured.get("estimate", estimate)))
            interval = (
                float(structured.get("lower_pp", structured.get("lower", interval[0] if interval else None))),
                float(structured.get("upper_pp", structured.get("upper", interval[1] if interval else None))),
            )
        except (TypeError, ValueError):
            pass
    elif isinstance(structured, (list, tuple)) and len(structured) >= 2:
        try:
            interval = (float(structured[0]), float(structured[1]))
        except (TypeError, ValueError):
            pass
    direct_estimate = scene.get("point_estimate_pp", scene.get("delta_pp"))
    if direct_estimate is not None:
        try:
            estimate = float(direct_estimate)
        except (TypeError, ValueError):
            pass
    if estimate is None or interval is None:
        return None
    return estimate, interval[0], interval[1]


def draw_holdout(draw: ImageDraw.ImageDraw, scene: dict[str, Any], top: int, duration: float, t: float) -> None:
    metrics = scene.get("metrics", [])
    if isinstance(metrics, list) and metrics:
        draw_metric_cards(draw, metrics, top, duration, t)
    numbers = extract_holdout_numbers(scene)
    if numbers is None:
        draw_info_cards(draw, scene.get("items", []), top + 270, t, max_items=3, height=165)
        return
    estimate, low, high = numbers
    if low > high:
        low, high = high, low
    span = max(0.01, high - low)
    axis_low = min(low - span * 0.15, 0.0)
    axis_high = max(high + span * 0.15, 0.0)
    if axis_high <= axis_low:
        axis_high = axis_low + 1.0
    left, right = 288, 1632
    plot_y = top + 352
    draw.text((left, top + 278), "95% RESAMPLING INTERVAL  ·  PERCENTAGE POINTS", font=FONTS["tiny"], fill=MUTED)
    def x_at(value: float) -> int:
        return left + int((value - axis_low) / (axis_high - axis_low) * (right - left))
    draw.line((left, plot_y, right, plot_y), fill=(69, 96, 111), width=3)
    for value in (axis_low, 0.0, axis_high):
        x = x_at(value)
        color = CORAL if value == 0.0 else (104, 131, 147)
        draw.line((x, plot_y - (55 if value == 0.0 else 12), x, plot_y + 22), fill=color, width=4 if value == 0.0 else 2)
        label = "0.00" if value == 0.0 else f"{value:+.2f}"
        draw.text((x, plot_y + 29), label, font=FONTS["tiny"], fill=color, anchor="ma")
    draw.text((x_at(0.0), plot_y - 76), "ZERO", font=FONTS["tiny"], fill=CORAL, anchor="mm")
    x_low, x_high, x_est = x_at(low), x_at(high), x_at(estimate)
    draw.line((x_low, plot_y, x_high, plot_y), fill=TEAL, width=11)
    draw.line((x_low, plot_y - 18, x_low, plot_y + 18), fill=TEAL, width=4)
    draw.line((x_high, plot_y - 18, x_high, plot_y + 18), fill=TEAL, width=4)
    draw.ellipse((x_est - 15, plot_y - 15, x_est + 15, plot_y + 15), fill=WHITE, outline=TEAL, width=5)
    draw.text((x_low, plot_y - 43), f"{low:+.5f}", font=FONTS["tiny"], fill=WHITE, anchor="ms")
    draw.text((x_high, plot_y - 43), f"{high:+.5f}", font=FONTS["tiny"], fill=WHITE, anchor="ms")
    draw.text((x_est, plot_y + 38), f"point {estimate:+.5f} pp", font=FONTS["tiny"], fill=TEAL, anchor="mm")
    if low <= 0.0 <= high:
        draw.rounded_rectangle((right - 205, top + 252, right, top + 282), radius=12, fill=(55, 35, 40), outline=(155, 86, 78), width=1)
        draw.text((right - 102, top + 260), "INTERVAL CROSSES ZERO", font=FONTS["tiny"], fill=(255, 184, 166), anchor="ma")
    status = next((item for item in scene.get("items", []) if isinstance(item, dict) and "status" in str(item.get("label", "")).lower()), None)
    if status:
        label, value, _, _ = item_parts(status)
        y = top + 419
        rounded_panel(draw, (94, y, W - 94, y + 90), fill=(15, 37, 52), outline=(57, 117, 128), radius=16)
        draw.text((122, y + 20), label.upper(), font=FONTS["tiny"], fill=TEAL)
        draw_text_block(draw, value, (354, y + 18), FONTS["small"], WHITE, 1370, line_gap=2, max_lines=1)


def draw_path_band(draw: ImageDraw.ImageDraw, labels: list[str], top: int, t: float) -> None:
    visible = labels[:5]
    if len(visible) < 2:
        return
    left, right = 122, W - 122
    gap = 22
    box_w = (right - left - gap * (len(visible) - 1)) // len(visible)
    for i, label in enumerate(visible):
        x = left + i * (box_w + gap)
        accent = TEAL if i == 0 or i == len(visible) - 1 else (112, 174, 255)
        rounded_panel(draw, (x, top, x + box_w, top + 52), PANEL_2, outline=(accent[0] // 2, accent[1] // 2, accent[2] // 2), radius=15, width=2)
        draw.ellipse((x + 15, top + 20, x + 27, top + 32), fill=accent)
        font = fit_font(label, box_w - 48, 18, bold=False)
        draw.text((x + box_w // 2 + 8, top + 17), label.upper(), font=font, fill=WHITE, anchor="ma")
    rail_y = top + 68
    draw.line((left + 8, rail_y, right - 8, rail_y), fill=(46, 81, 101), width=2)
    phase = (t * 0.24) % 1.0
    pulse_x = left + 8 + int((right - left - 16) * phase)
    draw.ellipse((pulse_x - 7, rail_y - 7, pulse_x + 7, rail_y + 7), fill=TEAL, outline=(181, 255, 245), width=2)


def draw_abstract_lattice(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, t: float) -> None:
    """Draw a clearly labeled workflow schematic, not a material structure."""
    points = []
    for i in range(6):
        angle = -math.pi / 2 + i * math.tau / 6
        points.append((cx + int(math.cos(angle) * radius), cy + int(math.sin(angle) * radius)))
    edge = (46, 112, 142)
    draw.ellipse((cx - radius - 34, cy - radius - 34, cx + radius + 34, cy + radius + 34), outline=(31, 78, 104), width=2)
    draw.text((cx, cy - radius - 48), "ABSTRACT WORKFLOW SCHEMATIC", font=FONTS["tiny"], fill=(125, 166, 183), anchor="mm")
    for i, point in enumerate(points):
        nxt = points[(i + 1) % len(points)]
        draw.line((*point, *nxt), fill=edge, width=3)
        draw.line((cx, cy, *point), fill=(36, 82, 105), width=2)
    draw.line((*points[0], *points[3]), fill=(44, 96, 119), width=2)
    draw.line((*points[1], *points[4]), fill=(44, 96, 119), width=2)
    draw.line((*points[2], *points[5]), fill=(44, 96, 119), width=2)
    draw.ellipse((cx - 50, cy - 50, cx + 50, cy + 50), fill=(13, 38, 56), outline=TEAL, width=3)
    draw.text((cx, cy), "NOVA-MAT", font=FONTS["small"], fill=WHITE, anchor="mm")
    labels = ("QUESTION", "RESULT", "REVIEW", "PI CHOICE", "RUN", "EXPORT")
    for i, (x, y) in enumerate(points):
        accent = TEAL if i in {0, 3} else (112, 174, 255)
        draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=(11, 28, 43), outline=accent, width=4)
        angle = -math.pi / 2 + i * math.tau / 6
        tx = cx + int(math.cos(angle) * (radius + 25))
        ty = cy + int(math.sin(angle) * (radius + 25))
        draw.text((tx, ty), labels[i], font=FONTS["tiny"], fill=MUTED, anchor="mm")
    phase = (t * 0.22) % 1.0
    segment = min(5, int(phase * 6))
    within = phase * 6 - segment
    start, end = points[segment], points[(segment + 1) % 6]
    px = int(start[0] + (end[0] - start[0]) * within)
    py = int(start[1] + (end[1] - start[1]) * within)
    draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=WHITE, outline=TEAL, width=2)


def draw_timeline(draw: ImageDraw.ImageDraw, items: list[Any], top: int, t: float) -> None:
    if not items:
        return
    visible = items[:6]
    left, right = 150, W - 150
    baseline = top + 70
    if len(visible) > 1:
        draw.line((left + 35, baseline, right - 35, baseline), fill=LINE, width=5)
        phase = (t * 0.30) % 1.0
        pulse_x = left + 35 + int((right - left - 70) * phase)
        draw.ellipse((pulse_x - 8, baseline - 8, pulse_x + 8, baseline + 8), fill=WHITE, outline=TEAL, width=2)
    slot = (right - left) / max(1, len(visible))
    for i, item in enumerate(visible):
        label, value, detail, tag = item_parts(item)
        cx = int(left + slot * (i + 0.5))
        active = smoothstep((t - i * 0.12) / 0.42)
        accent = TEAL if tag.lower() not in {"blocked", "risk", "holdout"} else CORAL
        radius = 18 + int(active * 5)
        draw.ellipse((cx - radius, baseline - radius, cx + radius, baseline + radius), fill=accent if active > 0.75 else PANEL, outline=accent, width=4)
        if value:
            draw.text((cx, baseline - 58), value[:18], font=FONTS["tiny"], fill=accent, anchor="mm")
        width = min(int(slot - 20), 260)
        draw_text_block(draw, label, (cx - width // 2, baseline + 34), FONTS["small"], WHITE, width, max_lines=2)
        if detail:
            draw_text_block(draw, detail, (cx - width // 2, baseline + 87), FONTS["tiny"], MUTED, width, line_gap=3, max_lines=2)


def draw_table(draw: ImageDraw.ImageDraw, scene: dict[str, Any], items: list[Any], top: int, t: float) -> None:
    columns = scene.get("columns", [])
    rows = scene.get("rows", items)
    if not isinstance(columns, list) or not columns:
        keys: list[str] = []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                for key in row:
                    if key not in keys:
                        keys.append(key)
        columns = keys[:4]
    if not isinstance(rows, list) or not rows:
        return
    columns = [str(c) for c in columns[:4]]
    x0, x1 = 112, W - 112
    table_w = x1 - x0
    col_w = table_w // max(1, len(columns))
    y = top
    draw.rounded_rectangle((x0, y, x1, y + 57), radius=12, fill=(20, 51, 67))
    for j, col in enumerate(columns):
        draw.text((x0 + j * col_w + 20, y + 16), col.upper()[:26], font=FONTS["tiny"], fill=TEAL)
    y += 70
    for i, row in enumerate(rows[:6]):
        height = 65
        if i % 2 == 0:
            draw.rounded_rectangle((x0, y, x1, y + height - 4), radius=10, fill=PANEL)
        for j, col in enumerate(columns):
            if isinstance(row, dict):
                cell = row.get(col, row.get(col.lower(), ""))
                if cell == "":
                    cell = row.get(col.replace(" ", "_").lower(), "")
            elif isinstance(row, (list, tuple)):
                cell = row[j] if j < len(row) else ""
            else:
                cell = row if j == 0 else ""
            text = str(cell)
            if len(text) > 54:
                text = text[:51] + "…"
            draw.text((x0 + j * col_w + 20, y + 17), text, font=FONTS["small"], fill=WHITE if j == 0 else MUTED)
        y += height


def evidence_lines(scene: dict[str, Any]) -> list[str]:
    for key in ("evidence_excerpt", "terminal_excerpt", "excerpt", "command_output", "source_excerpt", "evidence_lines"):
        value = scene.get(key)
        if isinstance(value, str) and value.strip():
            return value.splitlines()
        if isinstance(value, list) and value:
            return [str(line) for line in value]
    return []


def draw_evidence(draw: ImageDraw.ImageDraw, scene: dict[str, Any], top: int, t: float) -> None:
    lines = evidence_lines(scene)
    if not lines:
        return
    left, right, bottom = 112, W - 112, 796
    rounded_panel(draw, (left, top, right, bottom), fill=(8, 21, 34), outline=(44, 91, 105), radius=18)
    draw.ellipse((left + 26, top + 23, left + 40, top + 37), fill=CORAL)
    draw.ellipse((left + 50, top + 23, left + 64, top + 37), fill=(244, 190, 91))
    draw.ellipse((left + 74, top + 23, left + 88, top + 37), fill=TEAL)
    title = str(pick(scene, "excerpt_label", "evidence_label", default="RECORDED PUBLIC EVIDENCE"))
    draw.text((left + 118, top + 18), title.upper(), font=FONTS["tiny"], fill=MUTED)
    line_y = top + 68
    shown = lines[:8]
    for i, line in enumerate(shown):
        alpha = smoothstep((t - 0.25 - i * 0.075) / 0.32)
        color = (110 + int(95 * alpha), 184 + int(35 * alpha), 189 + int(40 * alpha))
        text = line[:132]
        draw.text((left + 30, line_y + i * 46), text, font=FONTS["mono"], fill=color)


def draw_generic(draw: ImageDraw.ImageDraw, scene: dict[str, Any], items: list[Any], top: int, t: float, duration: float) -> None:
    layout = str(scene.get("layout", "cards")).lower().replace("-", "_")
    selected = pick(scene, "selected", "selected_option", "chosen")
    if layout in {"table", "comparison", "gate_table"}:
        draw_table(draw, scene, items, top, t)
    elif layout == "sensitivity":
        draw_sensitivity(draw, scene, top, t)
    elif layout == "holdout":
        draw_holdout(draw, scene, top, duration, t)
    elif layout in {"bars", "bar_chart", "grid"}:
        draw_bars(draw, items, top, t)
    elif layout in {"pipeline", "timeline", "provenance", "flow"}:
        nodes = scene.get("nodes", [])
        if isinstance(nodes, list) and nodes:
            draw_timeline(draw, nodes, top, t)
            if scene.get("items"):
                draw_info_cards(draw, scene["items"], top + 188, t, max_items=3, height=150)
        else:
            draw_timeline(draw, items, top, t)
    elif layout in {"decision", "choice", "options"}:
        options = scene.get("options", items)
        draw_choice_cards(draw, options if isinstance(options, list) else items, top, selected, t)
        details = scene.get("items", [])
        if isinstance(details, list) and details:
            draw_info_cards(draw, details[:2], top + 300, t, max_items=2, height=145)
        draw_path_band(draw, ["ACTUAL RESULT", "SKEPTIC REVIEW", "PI CHOICE", "REGISTERED RUN"], top + 452, t)
    elif layout == "gate":
        nodes = scene.get("nodes", [])
        if isinstance(nodes, list) and nodes:
            draw_timeline(draw, nodes, top, t)
        draw_info_cards(draw, scene.get("items", items), top + 205, t, max_items=3, height=150)
    elif layout in {"terminal", "evidence", "excerpt", "cli"}:
        draw_evidence(draw, scene, top, t)
        if items and not evidence_lines(scene):
            draw_info_cards(draw, items, top, t)
    elif layout == "primary":
        metrics = scene.get("metrics", items)
        draw_metric_cards(draw, metrics if isinstance(metrics, list) else items, top, duration, t)
        extra = scene.get("items", [])
        if isinstance(extra, list) and extra:
            draw_info_cards(draw, extra[:2], top + 275, t, max_items=2, height=145)
    elif layout == "title":
        draw_info_cards(draw, items, top, t, max_items=2, height=160)
        lattice_offset = 326 if scene.get("title") == "NOVA-MAT" else 357
        draw_abstract_lattice(draw, W // 2, top + lattice_offset, 104, t)
    elif layout == "ownership":
        draw_info_cards(draw, items, top, t, max_items=3, height=190)
        draw_path_band(draw, ["TEAM A · SCIENCE", "SHARED RESULT", "TEAM B · ORCHESTRATION"], top + 252, t)
    elif layout == "provenance":
        nodes = scene.get("nodes", [])
        draw_timeline(draw, nodes if isinstance(nodes, list) and nodes else items, top, t)
        if scene.get("items"):
            draw_info_cards(draw, scene["items"], top + 188, t, max_items=3, height=150)
        draw_path_band(draw, ["SPEC", "RESULT", "REVIEW", "FROZEN PROTOCOL"], top + 375, t)
    elif layout in {"closing", "limitations", "cards", "metrics", "ownership_gate"}:
        draw_info_cards(draw, items, top, t, max_items=3 if layout != "title" else 2, height=205 if layout in {"closing", "limitations"} else 190)
        if layout in {"closing", "limitations"}:
            draw_path_band(draw, ["SCREEN", "DECIDE", "VALIDATE", "EXPORT"], top + 290, t)
    else:
        draw_info_cards(draw, items, top, t)
    # Exact excerpts are only displayed when the storyboard supplies them.
    if evidence_lines(scene) and layout not in {"terminal", "evidence", "excerpt", "cli"}:
        draw_evidence(draw, scene, min(top + 24, 345), t)


def refs_for_scene(scene: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    refs = pick(scene, "source_refs", "refs", "sources", default=[])
    if isinstance(refs, str):
        refs = [refs]
    if not isinstance(refs, list):
        refs = []
    if not refs and isinstance(evidence, dict):
        refs = evidence.get("public_sources", evidence.get("refs", []))
        refs = refs if isinstance(refs, list) else []
    return [str(ref) for ref in refs if str(ref).strip()]


@dataclass
class Cue:
    start: float
    end: float
    text: str


def caption_chunks(narration: str) -> list[str]:
    narration = " ".join(str(narration or "").split())
    if not narration:
        return []
    # Split on sentence boundaries, then reflow into at most two subtitle lines.
    sentences = re.split(r"(?<=[.!?])\s+", narration)
    chunks: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) > 68 and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for i in range(0, len(lines), 2):
            chunks.append("\n".join(lines[i : i + 2]))
    return chunks


def cues_for(narration: str, speech_duration: float) -> list[Cue]:
    chunks = caption_chunks(narration)
    if not chunks:
        return []
    weights = [max(1, len(chunk.split())) for chunk in chunks]
    total_words = sum(weights)
    cues: list[Cue] = []
    cursor = 0.0
    for chunk, weight in zip(chunks, weights):
        span = speech_duration * weight / total_words
        end = min(speech_duration, cursor + span)
        cues.append(Cue(cursor, end, chunk))
        cursor = end
    return cues


def draw_caption(frame: Image.Image, caption: str) -> None:
    if not caption:
        return
    draw = ImageDraw.Draw(frame)
    draw.rounded_rectangle((102, 905, W - 102, 1055), radius=18, fill=(3, 12, 22), outline=(62, 107, 122), width=2)
    lines = caption.splitlines()[:2]
    line_height = 44
    total_h = len(lines) * line_height
    y = 905 + (150 - total_h) // 2 - 2
    font = FONTS["caption"]
    for line in lines:
        while draw.textbbox((0, 0), line, font=font)[2] > W - 230 and getattr(font, "size", 31) > 23:
            font = choose_font(getattr(font, "size", 31) - 2)
        draw.text((W // 2, y), line, font=font, fill=WHITE, anchor="ma")
        y += line_height


def render_scene(scene: dict[str, Any], video_title: str, index: int, count: int, local_t: float, duration: float, video_key: str, evidence: dict[str, Any]) -> Image.Image:
    frame = BACKGROUND.copy()
    draw = ImageDraw.Draw(frame)
    top = draw_header(draw, video_title, scene, index, count, evidence)
    items = scene_items(scene)
    draw_generic(draw, scene, items, top, local_t, duration)
    footer = str(pick(scene, "footer", default=pick(evidence, "scope", default="")))
    if footer:
        draw.rounded_rectangle((94, 818, W - 94, 858), radius=14, fill=(14, 34, 48), outline=(49, 91, 104), width=1)
        draw_text_block(draw, footer, (115, 828), FONTS["tiny"], (190, 215, 220), 1170, line_gap=0, max_lines=1)
    refs = refs_for_scene(scene, evidence)
    ref_text = "SOURCE  " + "  ·  ".join(Path(ref).name for ref in refs[:3])
    if refs:
        ref_text = ref_text[:60]
        draw.text((W - 115, 841), ref_text, font=FONTS["tiny"], fill=MUTED, anchor="ra")
    # A quiet progress rail communicates replay progression, not system state.
    progress = (index - 1 + min(1.0, local_t / max(0.1, duration))) / max(1, count)
    draw.rounded_rectangle((94, 879, W - 94, 886), radius=4, fill=(33, 55, 68))
    draw.rounded_rectangle((94, 879, 94 + int((W - 188) * progress), 886), radius=4, fill=TEAL)
    return frame


def audio_path(audio_dir: Path, video_key: str, scene: dict[str, Any]) -> Path:
    scene_id = str(scene.get("id", "scene")).strip()
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", scene_id)
    candidates = [
        audio_dir / f"{video_key}_{safe_id}.wav",
        audio_dir / video_key / f"{safe_id}.wav",
        audio_dir / f"{safe_id}.wav",
    ]
    for path in candidates:
        if path.is_file():
            return path
    fail(f"missing narrated scene WAV for '{scene_id}'. Expected {candidates[0]}")


def safe_scene_id(scene: dict[str, Any], fallback: int) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(scene.get("id", fallback)).strip())


@dataclass
class ScenePlan:
    scene: dict[str, Any]
    wav_path: Path
    audio_seconds: float
    frame_count: int
    start_frame: int
    cues: list[Cue]

    @property
    def duration(self) -> float:
        return self.frame_count / FPS


def read_wav_info(path: Path) -> tuple[wave._wave_params, bytes, float]:
    try:
        with wave.open(str(path), "rb") as wav:
            params = wav.getparams()
            frames = wav.readframes(params.nframes)
    except (wave.Error, OSError) as exc:
        fail(f"cannot read PCM WAV {path}: {exc}")
    if params.comptype != "NONE" or params.sampwidth != 2:
        fail(f"{path.name} must be uncompressed 16-bit PCM WAV, received {params.comptype}/{params.sampwidth * 8}-bit")
    duration = params.nframes / params.framerate
    return params, frames, duration


def create_audio_mix(plans: list[ScenePlan], target_frames: int, temp_path: Path) -> dict[str, Any]:
    info = [read_wav_info(plan.wav_path) for plan in plans]
    base = info[0][0]
    for plan, (params, _, _) in zip(plans, info):
        if (params.nchannels, params.sampwidth, params.framerate, params.comptype) != (base.nchannels, base.sampwidth, base.framerate, base.comptype):
            fail(f"scene WAV format mismatch at {plan.wav_path.name}; rerun local voice synthesis with one Windows voice setup")
    sample_frame = base.nchannels * base.sampwidth
    target_samples = round(target_frames / FPS * base.framerate)
    with wave.open(str(temp_path), "wb") as out:
        out.setnchannels(base.nchannels)
        out.setsampwidth(base.sampwidth)
        out.setframerate(base.framerate)
        written = 0
        for plan, (_, payload, _) in zip(plans, info):
            planned_samples = round(plan.frame_count / FPS * base.framerate)
            payload_samples = len(payload) // sample_frame
            if payload_samples > planned_samples:
                fail(f"audio in {plan.wav_path.name} exceeds its allocated scene by {payload_samples / base.framerate:.2f}s")
            out.writeframes(payload)
            padding = planned_samples - payload_samples
            if padding:
                out.writeframes(b"\x00" * (padding * sample_frame))
            written += planned_samples
        if written < target_samples:
            out.writeframes(b"\x00" * ((target_samples - written) * sample_frame))
    return {
        "sample_rate_hz": base.framerate,
        "channels": base.nchannels,
        "sample_width_bits": base.sampwidth * 8,
    }


def ms_time(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(path: Path, plans: list[ScenePlan]) -> None:
    cues: list[tuple[float, float, str]] = []
    for plan in plans:
        start = plan.start_frame / FPS
        for cue in plan.cues:
            cues.append((start + cue.start, start + cue.end, cue.text))
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for i, (start, end, text) in enumerate(cues, 1):
            out.write(f"{i}\n{ms_time(start)} --> {ms_time(end)}\n{text}\n\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_ffmpeg(value: str | None) -> str:
    if value:
        path = Path(value)
        if not path.is_file():
            fail(f"FFmpeg binary does not exist: {path}")
        return str(path)
    found = shutil.which("ffmpeg")
    if not found:
        fail("FFmpeg not found. Pass --ffmpeg with the extracted local FFmpeg executable.")
    return found


def load_storyboard(path: Path, video_key: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    try:
        storyboard = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read storyboard {path}: {exc}")
    videos = storyboard.get("videos", {})
    video = videos.get(video_key) if isinstance(videos, dict) else None
    if not isinstance(video, dict):
        fail(f"storyboard has no videos.{video_key} entry")
    scenes = video.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        fail(f"videos.{video_key}.scenes must be a non-empty list")
    if len(scenes) != 6:
        fail(f"expected six storyboard scenes for {video_key}; found {len(scenes)}")
    for i, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict) or not scene.get("narration"):
            fail(f"scene {i} must be an object with narration")
    return storyboard, video, scenes


def prepare_plans(scenes: list[dict[str, Any]], audio_dir: Path, video_key: str, target_seconds: float = TARGET_VIDEO_SEC) -> list[ScenePlan]:
    plans: list[ScenePlan] = []
    frame_cursor = 0
    for scene in scenes:
        wav_path = audio_path(audio_dir, video_key, scene)
        _, _, speech_sec = read_wav_info(wav_path)
        scene_frames = math.ceil(max(MIN_SCENE_SEC, speech_sec + TAIL_SEC) * FPS)
        plan = ScenePlan(
            scene=scene,
            wav_path=wav_path,
            audio_seconds=speech_sec,
            frame_count=scene_frames,
            start_frame=frame_cursor,
            cues=cues_for(str(scene.get("narration", "")), speech_sec),
        )
        plans.append(plan)
        frame_cursor += scene_frames
    total_sec = frame_cursor / FPS
    if total_sec <= target_seconds:
        target_frames = round(target_seconds * FPS)
        scale = target_frames / max(1, frame_cursor)
        cursor = 0
        for plan in plans:
            plan.frame_count = max(plan.frame_count, round(plan.frame_count * scale))
            plan.start_frame = cursor
            cursor += plan.frame_count
        # Frame rounding can differ from the target by a couple of frames.
        plans[-1].frame_count += target_frames - cursor
        cursor = 0
        for plan in plans:
            plan.start_frame = cursor
            cursor += plan.frame_count
        total_sec = cursor / FPS
    if total_sec > MAX_VIDEO_SEC:
        detail = ", ".join(f"{str(p.scene.get('id', 'scene'))} {p.audio_seconds:.1f}s" for p in plans)
        fail(f"voice track needs {total_sec:.2f}s including scene tails, above the {MAX_VIDEO_SEC:.0f}s limit ({detail}); shorten storyboard narration and resynthesize")
    return plans


def render(
    plans: list[ScenePlan],
    video: dict[str, Any],
    evidence: dict[str, Any],
    video_key: str,
    output_dir: Path,
    ffmpeg: str,
    audio_mix_path: Path,
    audio_info: dict[str, Any],
    width: int,
    height: int,
) -> dict[str, Any]:
    if (width, height) != (W, H):
        fail("this presentation renderer currently supports 1920x1080 only")
    output_dir.mkdir(parents=True, exist_ok=True)
    still_dir = output_dir / f"{video_key}_stills"
    still_dir.mkdir(parents=True, exist_ok=True)
    title = str(video.get("title", "NOVA-MAT evidence replay"))
    total_frames = sum(p.frame_count for p in plans)
    total_seconds = total_frames / FPS
    output_path = output_dir / f"{video_key}.mp4"
    srt_path = output_dir / f"{video_key}.srt"
    write_srt(srt_path, plans)

    previous_exit: Image.Image | None = None
    scene_exits: list[Image.Image] = []
    for i, plan in enumerate(plans, 1):
        scene_exits.append(render_scene(plan.scene, title, i, len(plans), max(0.0, plan.duration - 0.1), plan.duration, video_key, evidence))
    ffmpeg_args = [
        ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", str(FPS), "-i", "pipe:0",
        "-i", "AUDIO_MIX_PLACEHOLDER",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-threads", "4", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-t", f"{total_seconds:.3f}", "-movflags", "+faststart",
        str(output_path),
    ]
    ffmpeg_args[ffmpeg_args.index("AUDIO_MIX_PLACEHOLDER")] = str(audio_mix_path)

    with tempfile.TemporaryFile(mode="w+b") as errlog:
        proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stderr=errlog, stdout=subprocess.DEVNULL)
        assert proc.stdin is not None
        try:
            current_plan = 0
            for frame_no in range(total_frames):
                while current_plan + 1 < len(plans) and frame_no >= plans[current_plan + 1].start_frame:
                    previous_exit = scene_exits[current_plan]
                    current_plan += 1
                plan = plans[current_plan]
                local_frame = frame_no - plan.start_frame
                local_t = local_frame / FPS
                frame = render_scene(plan.scene, title, current_plan + 1, len(plans), local_t, plan.duration, video_key, evidence)
                if previous_exit is not None and local_t < TRANSITION_SEC:
                    alpha = smoothstep(local_t / TRANSITION_SEC)
                    frame = Image.blend(previous_exit, frame, alpha)
                active_caption = ""
                for cue in plan.cues:
                    if cue.start <= local_t <= cue.end:
                        active_caption = cue.text
                        break
                draw_caption(frame, active_caption)
                proc.stdin.write(frame.tobytes())
                # Retain one polished preview per scene, independent of video encoding.
                if local_frame == plan.frame_count // 2:
                    frame.save(still_dir / f"{safe_scene_id(plan.scene, current_plan + 1)}.png", optimize=True)
            proc.stdin.close()
            return_code = proc.wait()
        except BrokenPipeError:
            return_code = proc.wait()
        if return_code != 0:
            errlog.seek(0)
            details = errlog.read().decode("utf-8", errors="replace")
            fail(f"FFmpeg failed with exit code {return_code}: {details[-5000:]}")

    contact = make_contact_sheet(still_dir, plans, output_dir / f"{video_key}_contact_sheet.png")
    return {
        "file": output_path,
        "srt": srt_path,
        "still_dir": still_dir,
        "contact_sheet": contact,
        "frame_count": total_frames,
        "duration_seconds": total_seconds,
        "video_title": title,
        "audio_info": audio_info,
    }


def make_contact_sheet(still_dir: Path, plans: list[ScenePlan], output: Path) -> Path:
    files = [still_dir / f"{safe_scene_id(plan.scene, i + 1)}.png" for i, plan in enumerate(plans)]
    thumbs = []
    for path, plan in zip(files, plans):
        if path.is_file():
            image = Image.open(path).convert("RGB")
            image.thumbnail((640, 360), Image.Resampling.LANCZOS)
            thumbs.append((image.copy(), str(pick(plan.scene, "title", default=plan.scene.get("id", "")))))
    sheet = Image.new("RGB", (1320, 3 * 405 + 32), (5, 13, 23))
    draw = ImageDraw.Draw(sheet)
    for i, (thumb, title) in enumerate(thumbs):
        col, row = i % 2, i // 2
        x, y = 14 + col * 652, 12 + row * 405
        sheet.paste(thumb, (x, y))
        draw.text((x + 6, y + 365), title[:70], font=FONTS["small"], fill=WHITE)
    sheet.save(output, optimize=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a local narrated NOVA-MAT demo from a JSON storyboard.")
    parser.add_argument("--storyboard", required=True, type=Path)
    parser.add_argument("--video", required=True, choices=("product_demo", "technical_walkthrough"))
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ffmpeg", help="Path to the locally extracted FFmpeg executable.")
    parser.add_argument("--audio-dir", type=Path, help="Directory containing the locally synthesized scene WAV files.")
    parser.add_argument("--fps", type=int, default=FPS)
    parser.add_argument("--width", type=int, default=W)
    parser.add_argument("--height", type=int, default=H)
    parser.add_argument("--preview-only", action="store_true", help="Render PNG previews and contact sheet without audio or FFmpeg.")
    args = parser.parse_args()
    if args.fps != FPS:
        fail("the renderer uses 30 fps so audio timing and scene transitions stay deterministic")
    storyboard, video, scenes = load_storyboard(args.storyboard, args.video)
    evidence = storyboard.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    still_dir = output_dir / f"{args.video}_stills"
    still_dir.mkdir(parents=True, exist_ok=True)
    title = str(video.get("title", "NOVA-MAT evidence replay"))
    # Preview mode needs no voice files and shows one representative frame per scene.
    if args.preview_only:
        for i, scene in enumerate(scenes, 1):
            image = render_scene(scene, title, i, len(scenes), 2.0, 3.5, args.video, evidence)
            image.save(still_dir / f"{safe_scene_id(scene, i)}.png", optimize=True)
        contact = make_contact_sheet(still_dir, [ScenePlan(s, Path(), 3.5, 105, 0, []) for s in scenes], output_dir / f"{args.video}_contact_sheet.png")
        preview_manifest = {
            "schema_version": 1,
            "status": "preview_only",
            "video": args.video,
            "title": title,
            "target_duration_seconds": video.get("target_duration_seconds", TARGET_VIDEO_SEC),
            "duration_seconds": None,
            "width": args.width,
            "height": args.height,
            "fps": FPS,
            "planned_container": "mp4",
            "planned_video_codec": "H.264 (libx264)",
            "planned_pixel_format": "yuv420p",
            "planned_audio_codec": "AAC",
            "local_voice": storyboard.get("voice"),
            "voice_rate": storyboard.get("voice_rate"),
            "evidence": evidence,
            "storyboard": str(args.storyboard.resolve()),
            "storyboard_sha256": sha256_file(args.storyboard),
            "contact_sheet": contact.name,
            "scene_stills_dir": still_dir.name,
            "scenes": [
                {
                    "id": str(scene.get("id", i + 1)),
                    "title": str(scene.get("title", "")),
                    "layout": str(scene.get("layout", "")),
                    "narration_words": len(str(scene.get("narration", "")).split()),
                    "source_refs": refs_for_scene(scene, evidence),
                }
                for i, scene in enumerate(scenes)
            ],
        }
        preview_path = output_dir / f"{args.video}_preview_manifest.json"
        preview_path.write_text(json.dumps(preview_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Preview rendered: {contact}")
        print(f"Preview manifest: {preview_path}")
        return 0

    if args.audio_dir is None:
        fail("--audio-dir is required unless --preview-only is set")
    ffmpeg = resolve_ffmpeg(args.ffmpeg)
    target_seconds = float(video.get("target_duration_seconds", TARGET_VIDEO_SEC))
    if target_seconds <= 0 or target_seconds > MAX_VIDEO_SEC:
        fail(f"target_duration_seconds must be greater than zero and no more than {MAX_VIDEO_SEC:.0f}")
    plans = prepare_plans(scenes, args.audio_dir.resolve(), args.video, target_seconds)
    total_frames = sum(plan.frame_count for plan in plans)
    mix_path = output_dir / f".{args.video}_audio_mix.wav"
    audio_info = create_audio_mix(plans, total_frames, mix_path)
    try:
        result = render(plans, video, evidence, args.video, output_dir, ffmpeg, mix_path, audio_info, args.width, args.height)
    finally:
        try:
            mix_path.unlink()
        except OSError:
            pass
    manifest = {
        "schema_version": 1,
        "video": args.video,
        "title": result["video_title"],
        "output": result["file"].name,
        "sha256": sha256_file(result["file"]),
        "file_size_bytes": result["file"].stat().st_size,
        "container": "mp4",
        "video_codec": "H.264 (libx264)",
        "pixel_format": "yuv420p",
        "audio_codec": "AAC",
        "audio_bitrate_kbps": 160,
        "audio_sample_rate_hz": 48000,
        "audio_channels": result["audio_info"]["channels"],
        "source_wav_audio": result["audio_info"],
        "local_voice": storyboard.get("voice"),
        "voice_rate": storyboard.get("voice_rate"),
        "width": args.width,
        "height": args.height,
        "fps": FPS,
        "frame_count": result["frame_count"],
        "duration_seconds": result["duration_seconds"],
        "ffmpeg": ffmpeg,
        "storyboard": str(args.storyboard.resolve()),
        "storyboard_sha256": sha256_file(args.storyboard),
        "evidence": evidence,
        "captions": result["srt"].name,
        "contact_sheet": result["contact_sheet"].name,
        "scene_stills_dir": result["still_dir"].name,
        "scenes": [
            {
                "id": str(plan.scene.get("id", f"scene_{i + 1}")),
                "title": str(plan.scene.get("title", "")),
                "start_seconds": round(plan.start_frame / FPS, 3),
                "end_seconds": round((plan.start_frame + plan.frame_count) / FPS, 3),
                "duration_seconds": round(plan.duration, 3),
                "narration_seconds": round(plan.audio_seconds, 3),
                "wav": str(plan.wav_path),
                "source_refs": refs_for_scene(plan.scene, evidence),
            }
            for i, plan in enumerate(plans)
        ],
    }
    manifest_path = output_dir / f"{args.video}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Rendered {result['file']} ({result['duration_seconds']:.2f}s, {args.width}x{args.height}, H.264/AAC)")
    print(f"Captions: {result['srt']}")
    print(f"Contact sheet: {result['contact_sheet']}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("Interrupted.")
