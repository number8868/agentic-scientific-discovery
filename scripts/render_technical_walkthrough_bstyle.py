#!/usr/bin/env python3
"""Render the NOVA-MAT technical walkthrough in the product-demo visual style.

This is an offline evidence replay. It validates pinned public exports, reuses
the already-recorded scene narration, paints six diagrams, and sends frames to
the local FFmpeg binary. It never imports or runs a science executor.
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_submission_video as media  # Reuse its PCM, timing, SRT and hash helpers.


W, H, FPS = 1920, 1080, 30
NAVY = (7, 21, 33)
PANEL = (10, 29, 45)
PANEL_ALT = (13, 36, 52)
TEAL = (89, 222, 210)
BLUE = (123, 177, 231)
WHITE = (242, 247, 248)
MUTED = (154, 179, 194)
DIM = (100, 129, 147)
RULE = (36, 67, 84)
GOLD = (224, 185, 112)
CONTENT_BOX = (770, 208, 1824, 875)
MARGIN_X = 96
TRANSITION_SEC = 0.38
RUN_EVIDENCE: dict[str, Any] = {}


def fail(message: str) -> None:
    raise SystemExit(f"render_technical_walkthrough_bstyle: {message}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read JSON {path}: {exc}")


def sha256(path: Path) -> str:
    return media.sha256_file(path)


def verify_file_pin(relative_path: str, expected_hash: str, role: str) -> Path:
    path = (ROOT / relative_path).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        fail(f"pinned source escapes the workspace: {relative_path}")
    if not path.is_file():
        fail(f"missing pinned {role}: {relative_path}")
    actual = sha256(path)
    if actual.lower() != str(expected_hash).lower():
        fail(f"pinned {role} hash mismatch for {relative_path}: expected {expected_hash}, found {actual}")
    return path


def index_sources(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = evidence.get("sources")
    if not isinstance(sources, list):
        fail("evidence index has no sources list")
    indexed: dict[str, dict[str, Any]] = {}
    for item in sources:
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            indexed[item["path"]] = item
    return indexed


def validate_inputs(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[Path]]:
    pins = config.get("input_pins")
    if not isinstance(pins, dict):
        fail("config requires input_pins")
    evidence_pin = pins.get("evidence_index", {})
    storyboard_pin = pins.get("narration_storyboard", {})
    evidence_path = verify_file_pin(evidence_pin.get("path", ""), evidence_pin.get("sha256", ""), "evidence index")
    storyboard_path = verify_file_pin(storyboard_pin.get("path", ""), storyboard_pin.get("sha256", ""), "narration storyboard")
    evidence = load_json(evidence_path)
    storyboard = load_json(storyboard_path)
    if evidence.get("run_id") != "native-adaptive-live-09":
        fail("evidence index identifies an unexpected run")

    entries = pins.get("public_aggregate_exports")
    if not isinstance(entries, list) or len(entries) < 8:
        fail("config must pin the published native09 aggregate exports")
    evidence_sources = index_sources(evidence)
    declared: set[str] = set()
    source_paths: list[Path] = []
    for entry in entries:
        if not isinstance(entry, dict):
            fail("public_aggregate_exports entries must be objects")
        relative = str(entry.get("path", ""))
        if not relative.startswith("docs/results/native09_completed/"):
            fail(f"non-public source is forbidden: {relative}")
        if any(word in relative.lower() for word in ("raw", "prepared", "runtime", "trace", "sqlite", "model-audit")):
            fail(f"private, prepared or raw source is forbidden: {relative}")
        if relative in declared:
            fail(f"duplicate source pin: {relative}")
        declared.add(relative)
        indexed = evidence_sources.get(relative)
        if not indexed or indexed.get("published_inventory_match") is not True:
            fail(f"source is not a published aggregate export in evidence.json: {relative}")
        expected = str(entry.get("sha256", ""))
        if indexed.get("sha256") != expected:
            fail(f"config and evidence index disagree on source hash: {relative}")
        source_paths.append(verify_file_pin(relative, expected, "public aggregate export"))

    public_dir = ROOT / "docs" / "results" / "native09_completed"
    fixed_required = {
        "README.md", "results.json", "specs.json", "reviews.json", "events.jsonl",
        "final_protocol.json", "science-artifacts.json", "native-holdout-result.json", "manifest.json",
    }
    if declared != {f"docs/results/native09_completed/{name}" for name in fixed_required}:
        fail("public source list changed; review the source allowlist before rendering")

    audio_config = config.get("audio", {})
    video_key = str(audio_config.get("video_key", ""))
    audio_story = storyboard.get("videos", {}).get(video_key, {})
    audio_scenes = audio_story.get("scenes", [])
    scenes = config.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 6:
        fail("config must contain exactly six scenes")
    if not isinstance(audio_scenes, list) or len(audio_scenes) != 6:
        fail("pinned narration storyboard must contain exactly six source scenes")
    for i, scene in enumerate(scenes):
        source_scene = audio_scenes[i]
        if scene.get("id") != source_scene.get("id") or scene.get("narration") != source_scene.get("narration"):
            fail(f"scene {i + 1} id or narration no longer matches the pinned storyboard")
        expected_wav = f"{audio_config.get('wav_prefix', '')}{scene['id']}.wav"
        if scene.get("audio_wav") != expected_wav:
            fail(f"scene {scene['id']} audio mapping is invalid")
    if [str(s.get("id", "")) for s in scenes] != [str(s.get("id", "")) for s in audio_scenes]:
        fail("new scene order must remain aligned with the recorded narration")
    return evidence, storyboard, audio_story, source_paths


def find_row(rows: list[Any], key: str, value: Any) -> dict[str, Any]:
    found = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(found) != 1:
        fail(f"expected one {key}={value!r} row, found {len(found)}")
    return found[0]


def validate_lineage(config: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    base = ROOT / "docs/results/native09_completed"
    results = load_json(base / "results.json")
    specs = load_json(base / "specs.json")
    reviews = load_json(base / "reviews.json")
    artifacts = load_json(base / "science-artifacts.json")
    protocol = load_json(base / "final_protocol.json")
    native_holdout = load_json(base / "native-holdout-result.json")
    expected_lineage = evidence.get("result_lineage", {})
    configured = config.get("lineage_bindings", {})
    record_bindings = configured.get("result_records", [])
    if len(record_bindings) != 3 or len(results) != 3 or len(specs) != 3:
        fail("native09 must have exactly three published Result and Spec records")

    payload_by_result: dict[str, str] = {}
    spec_by_result: dict[str, str] = {}
    validated: dict[str, Any] = {}
    artifact_results = artifacts.get("results", [])
    artifact_index = artifacts.get("artifacts", [])
    artifact_by_payload = {str(item.get("sha256")): item for item in artifact_index if isinstance(item, dict)}
    for record in record_bindings:
        role = str(record.get("lineage_key", ""))
        lineage = expected_lineage.get(role)
        if not isinstance(lineage, dict):
            fail(f"evidence index has no lineage for {role}")
        if record.get("experiment_id") != lineage.get("experiment_id"):
            fail(f"configured experiment id for {role} differs from evidence.json")
        result = find_row(results, "experiment_id", lineage["experiment_id"])
        spec = find_row(specs, "experiment_id", lineage["experiment_id"])
        artifact_result = find_row(artifact_results, "experiment_id", lineage["experiment_id"])
        if result.get("result_id") != lineage.get("result_id"):
            fail(f"Result id mismatch for {role}")
        spec_sha = str(lineage.get("registered_spec_sha256", ""))
        payload_sha = str(lineage.get("payload_sha256", ""))
        if result.get("spec_sha256") != spec_sha:
            fail(f"registered Spec digest mismatch for {role}")
        if artifact_result.get("result_id") != lineage.get("result_id") or artifact_result.get("registered_spec_sha256") != spec_sha:
            fail(f"artifact export does not bind to the registered Spec and Result for {role}")
        payload_artifact = f"nova-result-payload:{payload_sha}"
        if payload_artifact not in result.get("artifact_ids", []) or payload_artifact not in artifact_result.get("artifact_ids", []):
            fail(f"science payload digest is not linked from the Result for {role}")
        indexed_payload = artifact_by_payload.get(payload_sha)
        if not indexed_payload or indexed_payload.get("artifact_id") != payload_artifact:
            fail(f"science artifact index does not contain the payload for {role}")
        if spec.get("experiment_id") != lineage.get("experiment_id"):
            fail(f"Spec record mismatch for {role}")
        for field, evidence_field in (("parent_result_id", "parent_result_id"), ("review_id", "review_id"), ("frozen_protocol_id", "frozen_protocol_id")):
            if spec.get(field) != lineage.get(evidence_field):
                fail(f"{field} mismatch for {role}")
        if spec.get("split") != ("discovery" if role != "holdout" else "holdout"):
            fail(f"unexpected split in Spec for {role}")
        payload_by_result[lineage["result_id"]] = payload_sha
        spec_by_result[lineage["result_id"]] = spec_sha
        validated[role] = {
            "role": str(record.get("role", role)).upper(),
            "experiment_id": lineage["experiment_id"],
            "result_id": lineage["result_id"],
            "spec_sha256": spec_sha,
            "payload_sha256": payload_sha,
            "parent_result_id": lineage.get("parent_result_id"),
            "review_ref": lineage.get("review_id"),
            "frozen_protocol_id": lineage.get("frozen_protocol_id"),
            "source": "science-artifacts.json",
            "scientific_status": result.get("scientific_status"),
        }

    review_refs = [str(row.get("result_id", "")) for row in reviews if isinstance(row, dict)]
    expected_review_refs = [str(x) for x in configured.get("expected_review_result_refs", [])]
    if len(reviews) != int(configured.get("summary_counts", {}).get("reviews", -1)) or review_refs != expected_review_refs:
        fail("published reviews do not match the two configured Result references")
    frozen = expected_lineage.get("frozen_protocol", {})
    protocol_id = frozen.get("id")
    if protocol_id != configured.get("protocol_id"):
        fail("frozen protocol id mismatch")
    if protocol.get("main_result_id") != expected_lineage.get("primary_discovery", {}).get("result_id"):
        fail("frozen protocol does not reference the primary discovery Result")
    if protocol.get("followup_result_id") != expected_lineage.get("threshold_followup", {}).get("result_id"):
        fail("frozen protocol does not reference the threshold follow-up Result")
    native_result = native_holdout.get("result", {})
    holdout = expected_lineage.get("holdout", {})
    if native_result.get("result_id") != holdout.get("result_id") or native_result.get("spec_sha256") != holdout.get("registered_spec_sha256"):
        fail("published native holdout record differs from the indexed holdout Result")
    if native_result.get("scientific_status") != configured.get("holdout_status"):
        fail("holdout status binding differs from the published result")
    if holdout.get("frozen_protocol_id") != protocol_id:
        fail("holdout is not linked to the published frozen protocol")
    if len(results) != int(configured.get("summary_counts", {}).get("results", -1)):
        fail("configured Result total differs from the published records")
    if int(configured.get("summary_counts", {}).get("holdouts", -1)) != 1:
        fail("only one published holdout is expected")
    validated["counts"] = {"results": len(results), "reviews": len(reviews), "holdouts": 1}
    validated["protocol_id"] = protocol_id
    validated["review_result_refs"] = review_refs
    return validated


def validate_audio_and_plan(scenes: list[dict[str, Any]], audio_dir: Path, config: dict[str, Any]) -> list[media.ScenePlan]:
    plans: list[media.ScenePlan] = []
    cursor = 0
    audio_cfg = config["audio"]
    for scene in scenes:
        wav_path = (audio_dir / scene["audio_wav"]).resolve()
        if not wav_path.is_file():
            fail(f"missing recorded narration WAV for {scene['id']}: {wav_path}")
        params, frames, seconds = media.read_wav_info(wav_path)
        del frames
        if params.framerate <= 0 or seconds <= 0:
            fail(f"invalid WAV duration for {scene['id']}")
        frame_count = math.ceil(max(media.MIN_SCENE_SEC, seconds + float(audio_cfg.get("tail_seconds", 0.55))) * FPS)
        plans.append(media.ScenePlan(
            scene=scene,
            wav_path=wav_path,
            audio_seconds=seconds,
            frame_count=frame_count,
            start_frame=cursor,
            cues=media.cues_for(scene["narration"], seconds),
        ))
        cursor += frame_count
    target = float(config.get("target_duration_seconds", 55.0))
    if cursor / FPS <= target:
        target_frames = round(target * FPS)
        scale = target_frames / max(1, cursor)
        cursor = 0
        for plan in plans:
            plan.frame_count = max(plan.frame_count, round(plan.frame_count * scale))
            plan.start_frame = cursor
            cursor += plan.frame_count
        plans[-1].frame_count += target_frames - cursor
        cursor = 0
        for plan in plans:
            plan.start_frame = cursor
            cursor += plan.frame_count
    total = sum(plan.frame_count for plan in plans) / FPS
    maximum = float(config.get("maximum_duration_seconds", 59.5))
    if total > maximum:
        detail = ", ".join(f"{p.scene['id']} {p.audio_seconds:.2f}s" for p in plans)
        fail(f"narration plus scene tails requires {total:.2f}s, above {maximum:.1f}s ({detail})")
    return plans


def make_background() -> Image.Image:
    image = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(image)
    top, bottom = (7, 21, 33), (10, 33, 49)
    for y in range(H):
        f = y / max(1, H - 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * f) for i in range(3))
        draw.line((0, y, W, y), fill=color)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((1220, -140, 1990, 690), fill=(25, 116, 141, 29))
    gd.ellipse((-360, 620, 430, 1290), fill=(21, 94, 123, 19))
    glow = glow.filter(ImageFilter.GaussianBlur(100))
    image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")
    return image


BACKGROUND = make_background()


@lru_cache(maxsize=256)
def font(size: int, face: str = "body", italic: bool = False) -> ImageFont.FreeTypeFont:
    paths: list[str]
    if face == "display":
        paths = [r"C:\Windows\Fonts\georgia.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]
    elif face == "display_bold":
        paths = [r"C:\Windows\Fonts\georgiab.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"]
    elif face == "display_italic" or italic:
        paths = [r"C:\Windows\Fonts\georgiai.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"]
    elif face == "mono":
        paths = [r"C:\Windows\Fonts\consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
    elif face == "body_bold":
        paths = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    else:
        paths = [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path in paths:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def fit_font(draw: ImageDraw.ImageDraw, text: str, width: int, start: int, face: str, minimum: int = 17) -> ImageFont.FreeTypeFont:
    size = start
    while size > minimum:
        candidate = font(size, face)
        if draw.textbbox((0, 0), text, font=candidate)[2] <= width:
            return candidate
        size -= 2
    return font(max(minimum, size), face)


def wrap(draw: ImageDraw.ImageDraw, text: str, face: str, size: int, width: int, max_lines: int | None = None) -> list[str]:
    out: list[str] = []
    for paragraph in str(text or "").splitlines() or [""]:
        words = paragraph.split()
        if not words:
            out.append("")
            continue
        current = words[0]
        fnt = font(size, face)
        for word in words[1:]:
            trial = f"{current} {word}"
            if draw.textbbox((0, 0), trial, font=fnt)[2] <= width:
                current = trial
            else:
                out.append(current)
                current = word
        out.append(current)
    if max_lines is not None and len(out) > max_lines:
        out = out[:max_lines]
        tail = out[-1]
        while tail and draw.textbbox((0, 0), tail + "…", font=font(size, face))[2] > width:
            tail = tail[:-1]
        out[-1] = tail.rstrip() + "…"
    return out


def write_block(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], width: int, size: int, color: tuple[int, int, int], face: str = "body", line_gap: int = 8, max_lines: int | None = None) -> int:
    lines = wrap(draw, text, face, size, width, max_lines)
    y = xy[1]
    fnt = font(size, face)
    for line in lines:
        draw.text((xy[0], y), line, font=fnt, fill=color)
        box = draw.textbbox((xy[0], y), line, font=fnt)
        y += max(size, box[3] - box[1]) + line_gap
    return y


def panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: tuple[int, int, int] = PANEL, outline: tuple[int, int, int] = RULE, radius: int = 20, width: int = 2) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def centered(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int, color: tuple[int, int, int], face: str = "body", anchor: str = "mm") -> None:
    draw.text(xy, text, font=font(size, face), fill=color, anchor=anchor)


def label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, color: tuple[int, int, int] = TEAL, size: int = 18, anchor: str = "la") -> None:
    draw.text(xy, text.upper(), font=font(size, "body_bold"), fill=color, anchor=anchor)


def arrow(draw: ImageDraw.ImageDraw, a: tuple[int, int], b: tuple[int, int], color: tuple[int, int, int] = TEAL, width: int = 3) -> None:
    draw.line((*a, *b), fill=color, width=width)
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    length = 12
    p1 = (b[0] - length * math.cos(angle - math.pi / 6), b[1] - length * math.sin(angle - math.pi / 6))
    p2 = (b[0] - length * math.cos(angle + math.pi / 6), b[1] - length * math.sin(angle + math.pi / 6))
    draw.polygon([b, p1, p2], fill=color)


def short_hash(value: str) -> str:
    return f"{value[:8]}…{value[-8:]}" if len(value) > 22 else value


def short_result(result_id: str) -> str:
    prefix = "nova-result-"
    value = result_id[len(prefix):] if result_id.startswith(prefix) else result_id
    return f"result-{value[:8]}…{value[-8:]}"


def format_clock(seconds: float) -> str:
    n = max(0, int(seconds))
    return f"{n // 60:02d}:{n % 60:02d}"


def draw_header(draw: ImageDraw.ImageDraw, scene_index: int, total: int, global_seconds: float, duration: float) -> None:
    draw.ellipse((99, 45, 109, 55), fill=TEAL)
    draw.text((126, 39), "NOVA-MAT", font=font(19, "body_bold"), fill=WHITE)
    draw.text((250, 39), "/", font=font(19, "body"), fill=DIM)
    draw.text((273, 39), "TECHNICAL WALKTHROUGH", font=font(18, "body_bold"), fill=MUTED)
    draw.line((96, 81, W - 96, 81), fill=(31, 60, 76), width=2)
    badge = (1280, 35, 1635, 65)
    draw.rounded_rectangle(badge, radius=5, fill=(10, 32, 47), outline=(37, 95, 111), width=1)
    draw.text((1458, 50), "RECORDED RUN · EVIDENCE REPLAY", font=font(14, "body_bold"), fill=TEAL, anchor="mm")
    draw.text((1807, 49), f"{format_clock(global_seconds)} / {format_clock(duration)}", font=font(17, "mono"), fill=MUTED, anchor="ra")
    draw.text((1807, 68), f"{scene_index:02d} / {total:02d}", font=font(13, "mono"), fill=DIM, anchor="ra")


def draw_chrome(frame: Image.Image, scene: dict[str, Any], index: int, plans: list[media.ScenePlan], elapsed: float) -> None:
    draw = ImageDraw.Draw(frame)
    total_frames = sum(p.frame_count for p in plans)
    duration = total_frames / FPS
    draw_header(draw, index, len(plans), elapsed, duration)
    draw.line((738, 203, 738, 872), fill=(35, 68, 86), width=2)
    draw.line((730, 203, 746, 203), fill=TEAL, width=2)
    draw.line((730, 872, 746, 872), fill=(73, 107, 123), width=2)

    # Left editorial rail: a short technical idea and a compact explanation.
    label(draw, (99, 226), str(scene["kicker"]), TEAL, 17)
    title = str(scene["title"])
    title_lines = wrap(draw, title, "display", 67, 560, max_lines=3)
    title_size = 67
    while any(draw.textbbox((0, 0), line, font=font(title_size, "display"))[2] > 558 for line in title_lines) and title_size > 51:
        title_size -= 2
        title_lines = wrap(draw, title, "display", title_size, 560, max_lines=3)
    y = 292
    for line in title_lines:
        color = TEAL if line.lower().startswith(("to ", "one ", "choose", "checked", "end to end")) else WHITE
        draw.text((99, y), line, font=font(title_size, "display"), fill=color)
        y += title_size + 13
    write_block(draw, str(scene["dek"]), (101, y + 18), 530, 25, MUTED, "body", line_gap=9, max_lines=5)
    draw.text((101, 835), "NATIVE09 · RECORDED EVIDENCE", font=font(14, "body_bold"), fill=(112, 148, 165))

    # Stable right-hand canvas with a small top line, no full-screen subtitles.
    panel(draw, CONTENT_BOX, fill=(9, 26, 41), outline=(27, 57, 73), radius=14, width=2)
    draw.line((802, 232, 1792, 232), fill=(25, 54, 70), width=1)
    draw.text((817, 222), "NOVA-MAT  /  TECHNICAL SYSTEM MAP", font=font(13, "body_bold"), fill=(118, 154, 171))

    painter = {
        "opening": draw_opening,
        "ownership": draw_ownership,
        "agents": draw_agents,
        "contract": draw_contract,
        "holdout": draw_holdout,
        "closing": draw_closing,
    }.get(str(scene.get("visual")))
    if painter is None:
        fail(f"unknown visual type for scene {scene.get('id')}")
    painter(draw, scene, index, elapsed, duration)

    draw.text((99, 951), str(scene["chapter"]).upper(), font=font(15, "body_bold"), fill=TEAL)
    draw.text((310, 951), "3 RESULTS  ·  2 REVIEWS  ·  1 FROZEN HOLDOUT", font=font(14, "body_bold"), fill=(112, 147, 164))
    marks_x0, marks_y = 1510, 956
    for i in range(6):
        color = TEAL if i == index - 1 else (45, 74, 90)
        draw.rounded_rectangle((marks_x0 + i * 47, marks_y, marks_x0 + i * 47 + 32, marks_y + 5), radius=2, fill=color)
    rail_y = 1001
    draw.line((96, rail_y, W - 96, rail_y), fill=(35, 64, 79), width=2)
    progress = min(1.0, max(0.0, elapsed / max(0.01, duration)))
    draw.line((96, rail_y, 96 + int((W - 192) * progress), rail_y), fill=TEAL, width=3)
    for i in range(6):
        x = 96 + int((W - 192) * (i / 5))
        draw.line((x, rail_y - 6, x, rail_y + 6), fill=(89, 119, 134) if i != index - 1 else TEAL, width=2)


def draw_opening(draw: ImageDraw.ImageDraw, scene: dict[str, Any], index: int, t: float, duration: float) -> None:
    cx, cy = 1302, 507
    draw.text((cx, 281), "OPEN-SOURCE OMNIGENT · COORDINATION LAYER", font=font(15, "body_bold"), fill=(135, 171, 186), anchor="mm")
    draw.ellipse((cx - 178, cy - 162, cx + 178, cy + 162), outline=(25, 69, 88), width=2)
    draw.ellipse((cx - 139, cy - 124, cx + 139, cy + 124), outline=(39, 92, 108), width=2)
    draw.text((cx, cy - 3), "N·M", font=font(100, "display_italic"), fill=WHITE, anchor="mm")
    nodes = [((1016, 435), "PI"), ((1588, 435), "RUNNER"), ((1016, 601), "SKEPTIC"), ((1588, 601), "PLANNER")]
    for pos, name in nodes:
        panel(draw, (pos[0] - 87, pos[1] - 27, pos[0] + 87, pos[1] + 27), fill=(12, 38, 55), outline=(41, 91, 108), radius=12, width=1)
        centered(draw, pos, name, 16, WHITE, "body_bold")
    arrow(draw, (1103, 435), (1169, 435), (50, 131, 151), 2)
    arrow(draw, (1437, 435), (1501, 435), (50, 131, 151), 2)
    arrow(draw, (1169, 601), (1103, 601), (50, 131, 151), 2)
    arrow(draw, (1501, 601), (1437, 601), (50, 131, 151), 2)
    panel(draw, (853, 725, 1750, 815), fill=(12, 36, 52), outline=(44, 93, 109), radius=12, width=1)
    label(draw, (879, 745), "INITIAL SCIENCE QUESTION", TEAL, 14)
    draw.text((879, 776), str(scene["host_seed_note"]), font=font(21, "body"), fill=WHITE)
    centered(draw, (1301, 849), "SCREENING RESULT  →  AGENT REVIEW  →  REGISTERED RUN  →  CONTROLLED VALIDATION  →  EXPORT", 14, MUTED, "body")


def draw_ownership(draw: ImageDraw.ImageDraw, scene: dict[str, Any], index: int, t: float, duration: float) -> None:
    xs = [817, 1160, 1495]
    widths = [306, 294, 300]
    titles = ["TEAM A  ·  SCIENCE", "SHARED CONTRACT", "TEAM B  ·  OMNIGENT"]
    colors = [TEAL, BLUE, TEAL]
    for x, width, title, color in zip(xs, widths, titles, colors):
        panel(draw, (x, 288, x + width, 692), fill=(12, 34, 50), outline=(color[0] // 2, color[1] // 2, color[2] // 2), radius=16, width=2)
        label(draw, (x + 20, 311), title, color, 15)
    for i, item in enumerate(scene["team_a"]):
        y = 370 + i * 66
        draw.ellipse((840, y + 7, 852, y + 19), fill=TEAL if i < 3 else BLUE)
        draw.text((866, y), str(item), font=font(22, "body"), fill=WHITE)
    centered(draw, (1307, 381), "REGISTERED", 15, MUTED, "body_bold")
    centered(draw, (1307, 421), "SPEC", 31, WHITE, "mono")
    arrow(draw, (1307, 450), (1307, 492), TEAL, 3)
    centered(draw, (1307, 526), "EXECUTE", 18, TEAL, "body_bold")
    arrow(draw, (1307, 551), (1307, 592), TEAL, 3)
    centered(draw, (1307, 626), "RESULT", 28, WHITE, "mono")
    centered(draw, (1307, 659), "+ immutable payload", 16, MUTED, "body")
    agents = scene["team_b"]
    for i, agent in enumerate(agents):
        row, col = divmod(i, 2)
        x = 1518 + col * 130
        y = 376 + row * 108
        panel(draw, (x, y, x + 112, y + 62), fill=(15, 42, 58), outline=(47, 97, 113), radius=12, width=1)
        centered(draw, (x + 56, y + 31), str(agent), 16, WHITE, "body_bold")
    arrow(draw, (1126, 492), (1152, 492), BLUE, 3)
    arrow(draw, (1455, 492), (1488, 492), BLUE, 3)
    draw.text((817, 724), str(scene["adapter"]), font=font(15, "mono"), fill=(172, 201, 211))
    draw.text((817, 776), "A typed adapter sits behind the registered Spec → Result boundary.", font=font(18, "body"), fill=MUTED)
    centered(draw, (1307, 833), "SHARED RESULT CONTRACT", 14, TEAL, "body_bold")


def draw_agents(draw: ImageDraw.ImageDraw, scene: dict[str, Any], index: int, t: float, duration: float) -> None:
    panel(draw, (819, 263, 1774, 319), fill=(12, 38, 54), outline=(46, 98, 115), radius=12, width=1)
    centered(draw, (1297, 291), str(scene["initial_goal"]), 16, TEAL, "body_bold")
    # A subtle path from the host-seeded objective into the native role layer.
    draw.line((1297, 319, 1297, 338), fill=(48, 110, 128), width=2)
    role_names = ["SKEPTIC", "PLANNER", "PI", "RUNNER"]
    role_notes = ["reviews Result\nevidence", "offers registered\noptions", "chooses next\nexperiment", "runs selected\nregistered tool"]
    x0, gap, box_w = 819, 17, 224
    for i, (name, note) in enumerate(zip(role_names, role_notes)):
        x = x0 + i * (box_w + gap)
        accent = TEAL if name == "PI" else (BLUE if name == "SKEPTIC" else (53, 103, 122))
        panel(draw, (x, 347, x + box_w, 471), fill=(13, 38, 55), outline=accent, radius=13, width=2)
        label(draw, (x + 20, 369), name, accent, 15)
        for j, line in enumerate(note.splitlines()):
            draw.text((x + 20, 401 + j * 26), line, font=font(19, "body"), fill=WHITE)
        if i < 3:
            arrow(draw, (x + box_w + 2, 410), (x + box_w + gap - 2, 410), (49, 126, 144), 2)
    panel(draw, (819, 550, 1094, 699), fill=(12, 34, 50), outline=(46, 86, 103), radius=13, width=1)
    panel(draw, (1133, 550, 1420, 699), fill=(12, 34, 50), outline=(46, 86, 103), radius=13, width=1)
    panel(draw, (1458, 550, 1774, 699), fill=(12, 34, 50), outline=(46, 86, 103), radius=13, width=1)
    # Runner invokes the chosen registered Spec; the Result returns to Skeptic review.
    draw.line((1654, 471, 1654, 512, 956, 512), fill=(45, 104, 122), width=2)
    arrow(draw, (956, 512), (956, 544), (45, 104, 122), 2)
    draw.line((1774, 623, 1801, 623, 1801, 337, 931, 337), fill=(45, 104, 122), width=2)
    arrow(draw, (931, 337), (931, 346), (45, 104, 122), 2)
    label(draw, (841, 572), "REGISTERED SPEC", TEAL, 14)
    centered(draw, (956, 631), "threshold_sensitivity", 18, WHITE, "mono")
    label(draw, (1155, 572), "SCIENCE ADAPTER", BLUE, 14)
    centered(draw, (1277, 619), "science tools", 23, WHITE, "body_bold")
    centered(draw, (1277, 654), "execute(spec)", 17, MUTED, "mono")
    label(draw, (1480, 572), "SHARED RESULT", TEAL, 14)
    centered(draw, (1616, 619), "Result + payload", 22, WHITE, "body_bold")
    centered(draw, (1616, 654), "review evidence", 17, MUTED, "body")
    arrow(draw, (1096, 623), (1125, 623), TEAL, 3)
    arrow(draw, (1422, 623), (1450, 623), TEAL, 3)
    draw.text((819, 760), f"SELECTED  {scene['selected']}     ·     OFFERED  {', '.join(scene['offered'])}", font=font(15, "body_bold"), fill=TEAL)
    draw.text((819, 804), str(scene["not_executed_note"]), font=font(16, "body"), fill=MUTED)


def draw_contract(draw: ImageDraw.ImageDraw, scene: dict[str, Any], index: int, t: float, duration: float) -> None:
    lineage = RUN_EVIDENCE["result_lineage"]
    roles = scene["display_roles"]
    keys = ["primary_discovery", "threshold_followup", "holdout"]
    y0, row_h = 256, 193
    for i, (role, key) in enumerate(zip(roles, keys)):
        item = lineage[key]
        y = y0 + i * row_h
        edge = TEAL if i == 1 else (52, 104, 122)
        panel(draw, (810, y, 1784, y + 176), fill=(11, 34, 50), outline=edge, radius=14, width=2 if i == 1 else 1)
        label(draw, (834, y + 20), role, TEAL if i == 1 else BLUE, 14)
        exp_id = str(item["experiment_id"])
        draw.text((834, y + 51), exp_id, font=font(17, "mono"), fill=WHITE)
        draw.text((834, y + 83), short_result(str(item["result_id"])), font=font(15, "mono"), fill=MUTED)
        # Compact digest columns stay readable at 1080p and are shortened only visually.
        label(draw, (1190, y + 20), "REGISTERED SPEC SHA256", MUTED, 12)
        draw.text((1190, y + 51), short_hash(str(item["registered_spec_sha256"])), font=font(17, "mono"), fill=WHITE)
        parent = item.get("parent_result_id") or "host-seeded initial Spec"
        review = item.get("review_id") or "no parent review"
        draw.text((1190, y + 87), f"PARENT  {short_result(str(parent)) if str(parent).startswith('nova-result-') else str(parent)}", font=font(13, "mono"), fill=MUTED)
        draw.text((1190, y + 115), f"SPEC REVIEW REF  {short_result(str(review)) if str(review).startswith('nova-result-') else str(review)}", font=font(13, "mono"), fill=MUTED)
        label(draw, (1537, y + 20), "SCIENCE PAYLOAD SHA256", MUTED, 12)
        draw.text((1537, y + 51), short_hash(str(item["payload_sha256"])), font=font(16, "mono"), fill=WHITE)
        draw.text((1537, y + 88), "SOURCE  science-artifacts.json", font=font(13, "mono"), fill=(139, 172, 188))
        draw.text((1537, y + 119), "RESULT  immutable record", font=font(13, "mono"), fill=(139, 172, 188))
    centered(draw, (1297, 852), "REGISTERED SPEC  →  SCIENCE ADAPTER  →  RESULT  →  REVIEW  →  FROZEN PROTOCOL", 14, TEAL, "body_bold")


def draw_holdout(draw: ImageDraw.ImageDraw, scene: dict[str, Any], index: int, t: float, duration: float) -> None:
    lineage = RUN_EVIDENCE["result_lineage"]
    protocol = lineage["frozen_protocol"]
    holdout = lineage["holdout"]
    label(draw, (825, 266), "HOST CONTROLS", TEAL, 14)
    control_names = scene["host_controls"]
    x_start, y_mid, slot = 845, 386, 229
    centers = [x_start + i * slot for i in range(5)]
    labels = ["FREEZE", "LINEAGE", "TIME BUDGET", "ONE CLAIM", "PERSIST"]
    subtitles = ["registered\nprotocol", "parent + review\nrefs", "shared host\ndeadline", "single attempt\nclaim", "completed\nResult"]
    for i, (cx, name, sub) in enumerate(zip(centers, labels, subtitles)):
        color = TEAL if i in (0, 4) else BLUE
        draw.ellipse((cx - 23, y_mid - 23, cx + 23, y_mid + 23), fill=(12, 42, 58), outline=color, width=3)
        centered(draw, (cx, y_mid), f"{i + 1:02d}", 14, WHITE, "mono")
        centered(draw, (cx, y_mid + 52), name, 15, color, "body_bold")
        for j, line in enumerate(sub.splitlines()):
            centered(draw, (cx, y_mid + 82 + j * 22), line, 15, MUTED, "body")
        if i < 4:
            arrow(draw, (cx + 29, y_mid), (cx + slot - 30, y_mid), (42, 91, 108), 2)
    panel(draw, (815, 584, 1777, 652), fill=(13, 37, 52), outline=(41, 84, 102), radius=12, width=1)
    draw.text((836, 608), f"PROTOCOL  {protocol['id']}", font=font(16, "mono"), fill=WHITE)
    draw.text((1320, 608), f"HOLDOUT  {holdout['experiment_id']}", font=font(16, "mono"), fill=TEAL)
    for i, control in enumerate(control_names):
        x = 822 + i * 322
        panel(draw, (x, 690, x + 292, 733), fill=(11, 34, 49), outline=(40, 86, 103), radius=10, width=1)
        centered(draw, (x + 146, 711), control, 13, (182, 205, 213), "body_bold")
    draw.text((821, 773), f"RESULT  {short_result(str(holdout['result_id']))}", font=font(15, "mono"), fill=WHITE)
    draw.text((821, 808), f"PARENT / REVIEW REF  {short_result(str(holdout['parent_result_id']))}", font=font(14, "mono"), fill=MUTED)
    draw.text((1320, 773), f"PAYLOAD  {short_hash(str(holdout['payload_sha256']))}", font=font(15, "mono"), fill=WHITE)
    draw.text((1320, 808), "direction_consistent_inconclusive", font=font(14, "mono"), fill=(182, 205, 213))
    draw.text((821, 846), str(scene["closing_note"]), font=font(14, "body"), fill=(124, 156, 172))


def draw_closing(draw: ImageDraw.ImageDraw, scene: dict[str, Any], index: int, t: float, duration: float) -> None:
    counts = scene["summary_claims"]
    x0 = 841
    for i, (value, title) in enumerate(zip(counts, ("RESULTS", "REVIEWS", "FROZEN HOLDOUT"))):
        x = x0 + i * 310
        panel(draw, (x, 278, x + 277, 408), fill=(12, 38, 54), outline=(41, 91, 109), radius=14, width=1)
        draw.text((x + 24, 296), value.split()[0], font=font(58, "display"), fill=TEAL if i != 2 else GOLD)
        draw.text((x + 97, 327), title, font=font(15, "body_bold"), fill=WHITE)
        draw.line((x + 24, 378, x + 252, 378), fill=(47, 80, 96), width=1)
    # Three Results remain ordered and linked all the way to export.
    names = ["SCREENING RESULT", "REGISTERED FOLLOW-UP", "CONTROLLED HOLDOUT"]
    notes = ["Skeptic review", "PI choice", "frozen protocol"]
    xs = [828, 1151, 1474]
    for i, (x, name, note) in enumerate(zip(xs, names, notes)):
        panel(draw, (x, 513, x + 277, 653), fill=(11, 34, 50), outline=(44, 91, 107), radius=14, width=1)
        label(draw, (x + 18, 533), f"0{i + 1}  ·  {name}", TEAL if i == 2 else BLUE, 13)
        centered(draw, (x + 138, 586), note, 20, WHITE, "body_bold")
        if i < 2:
            arrow(draw, (x + 281, 583), (xs[i + 1] - 9, 583), TEAL, 3)
    panel(draw, (829, 711, 1750, 812), fill=(12, 38, 53), outline=(49, 103, 117), radius=14, width=1)
    centered(draw, (1289, 746), "EVIDENCE EXPORT", 16, TEAL, "body_bold")
    centered(draw, (1289, 780), "Each decision points back to its registered Spec, Result, review and payload.", 18, WHITE, "body")
    centered(draw, (1297, 851), "FROM INITIAL QUESTION TO A REVIEWABLE NEXT STEP", 14, MUTED, "body_bold")


def render_frame(scene: dict[str, Any], index: int, plans: list[media.ScenePlan], elapsed: float) -> Image.Image:
    frame = BACKGROUND.copy()
    draw_chrome(frame, scene, index, plans, elapsed)
    return frame


def contact_sheet(still_dir: Path, plans: list[media.ScenePlan], path: Path) -> Path:
    sheet = Image.new("RGB", (1944, 812), (5, 15, 25))
    draw = ImageDraw.Draw(sheet)
    for i, plan in enumerate(plans):
        still = still_dir / f"{plan.scene['id']}.png"
        if not still.is_file():
            continue
        im = Image.open(still).convert("RGB")
        im.thumbnail((620, 349), Image.Resampling.LANCZOS)
        col, row = i % 3, i // 3
        x, y = 18 + col * 646, 18 + row * 395
        sheet.paste(im, (x, y))
        draw.text((x + 2, y + 356), f"{i + 1:02d}  {plan.scene['id']}  ·  {plan.scene['title']}", font=font(15, "body"), fill=WHITE)
    sheet.save(path, optimize=True)
    return path


def write_previews(plans: list[media.ScenePlan], output_dir: Path, bound: dict[str, Any]) -> dict[str, Any]:
    still_dir = output_dir / "technical_walkthrough_bstyle_stills"
    still_dir.mkdir(parents=True, exist_ok=True)
    duration = sum(plan.frame_count for plan in plans) / FPS
    for i, plan in enumerate(plans, 1):
        local = min(2.0, plan.duration * 0.5)
        image = render_frame(plan.scene, i, plans, plan.start_frame / FPS + local)
        image.save(still_dir / f"{plan.scene['id']}.png", optimize=True)
    sheet = contact_sheet(still_dir, plans, output_dir / "technical_walkthrough_bstyle_contact_sheet.png")
    return {
        "status": "preview_only",
        "title": "NOVA-MAT | Technical walkthrough",
        "duration_seconds": round(duration, 3),
        "width": W,
        "height": H,
        "fps": FPS,
        "planned_video_codec": "H.264 (libx264)",
        "planned_pixel_format": "yuv420p",
        "planned_audio_codec": "AAC",
        "captions_burned_in": False,
        "contact_sheet": sheet.name,
        "scene_stills_dir": still_dir.name,
        "source_bindings": bound,
        "scenes": [
            {
                "id": plan.scene["id"],
                "title": plan.scene["title"],
                "start_seconds": round(plan.start_frame / FPS, 3),
                "end_seconds": round((plan.start_frame + plan.frame_count) / FPS, 3),
                "narration_seconds": round(plan.audio_seconds, 3),
                "wav": plan.wav_path.name,
                "wav_sha256": sha256(plan.wav_path),
                "narration_sha256": hashlib.sha256(plan.scene["narration"].encode("utf-8")).hexdigest(),
            }
            for plan in plans
        ],
    }


def encode(plans: list[media.ScenePlan], output_dir: Path, ffmpeg: str, width: int, height: int, bound: dict[str, Any]) -> dict[str, Any]:
    output_path = output_dir / "technical_walkthrough_bstyle.mp4"
    captions_path = output_dir / "captions.srt"
    manifest_path = output_dir / "manifest.json"
    for path in (output_path, captions_path, manifest_path):
        if path.exists():
            fail(f"refusing to overwrite existing output: {path}")
    total_frames = sum(p.frame_count for p in plans)
    total_seconds = total_frames / FPS
    mix_path = output_dir / ".technical_walkthrough_bstyle_audio.wav"
    audio_info = media.create_audio_mix(plans, total_frames, mix_path)
    media.write_srt(captions_path, plans)
    still_dir = output_dir / "technical_walkthrough_bstyle_stills"
    still_dir.mkdir(parents=True, exist_ok=True)
    previous_exit: Image.Image | None = None
    scene_exits = [render_frame(plan.scene, i, plans, (plan.start_frame + plan.frame_count - 1) / FPS) for i, plan in enumerate(plans, 1)]
    args = [
        ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", str(FPS), "-i", "pipe:0",
        "-i", str(mix_path), "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "4", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{total_seconds:.3f}",
        "-movflags", "+faststart", str(output_path),
    ]
    with tempfile.TemporaryFile(mode="w+b") as errlog:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=errlog, stdout=subprocess.DEVNULL)
        assert proc.stdin is not None
        try:
            current = 0
            for frame_no in range(total_frames):
                while current + 1 < len(plans) and frame_no >= plans[current + 1].start_frame:
                    previous_exit = scene_exits[current]
                    current += 1
                plan = plans[current]
                local_frame = frame_no - plan.start_frame
                local = local_frame / FPS
                elapsed = frame_no / FPS
                frame = render_frame(plan.scene, current + 1, plans, elapsed)
                if previous_exit is not None and local < TRANSITION_SEC:
                    alpha = local / TRANSITION_SEC
                    alpha = alpha * alpha * (3 - 2 * alpha)
                    frame = Image.blend(previous_exit, frame, alpha)
                proc.stdin.write(frame.tobytes())
                if local_frame == plan.frame_count // 2:
                    frame.save(still_dir / f"{plan.scene['id']}.png", optimize=True)
            proc.stdin.close()
            exit_code = proc.wait()
        except BrokenPipeError:
            exit_code = proc.wait()
        if exit_code != 0:
            errlog.seek(0)
            details = errlog.read().decode("utf-8", errors="replace")
            fail(f"FFmpeg encode failed ({exit_code}): {details[-5000:]}")
    try:
        mix_path.unlink()
    except OSError:
        pass
    # Decode the complete output once so a successful FFmpeg exit alone is not treated as validation.
    with tempfile.TemporaryFile(mode="w+b") as errlog:
        check = subprocess.run([ffmpeg, "-v", "error", "-i", str(output_path), "-f", "null", "NUL"], stderr=errlog, stdout=subprocess.DEVNULL)
        if check.returncode != 0:
            errlog.seek(0)
            details = errlog.read().decode("utf-8", errors="replace")
            fail(f"full media decode failed ({check.returncode}): {details[-5000:]}")
    sheet = contact_sheet(still_dir, plans, output_dir / "technical_walkthrough_bstyle_contact_sheet.png")
    manifest = {
        "schema_version": 1,
        "video": "technical_walkthrough_bstyle",
        "title": "NOVA-MAT | Technical walkthrough",
        "output": output_path.name,
        "sha256": sha256(output_path),
        "file_size_bytes": output_path.stat().st_size,
        "duration_seconds": round(total_seconds, 3),
        "width": width,
        "height": height,
        "fps": FPS,
        "frame_count": total_frames,
        "config_sha256": bound["config"]["sha256"],
        "evidence_sha256": bound["evidence_index"]["sha256"],
        "narration_storyboard_sha256": bound["narration_storyboard"]["sha256"],
        "video_codec": "H.264 (libx264)",
        "pixel_format": "yuv420p",
        "audio_codec": "AAC",
        "audio_sample_rate_hz": 48000,
        "audio_channels": audio_info["channels"],
        "audio_source": audio_info,
        "captions_burned_in": False,
        "captions": captions_path.name,
        "ffmpeg": ffmpeg,
        "source_bindings": bound,
        "contact_sheet": sheet.name,
        "scenes": [
            {
                "id": plan.scene["id"],
                "title": plan.scene["title"],
                "start_seconds": round(plan.start_frame / FPS, 3),
                "end_seconds": round((plan.start_frame + plan.frame_count) / FPS, 3),
                "narration_seconds": round(plan.audio_seconds, 3),
                "wav": str(plan.wav_path),
                "wav_sha256": sha256(plan.wav_path),
                "narration_sha256": hashlib.sha256(plan.scene["narration"].encode("utf-8")).hexdigest(),
                "source_refs": plan.scene.get("source_refs", []),
            }
            for plan in plans
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"video": output_path, "captions": captions_path, "manifest": manifest_path, "contact_sheet": sheet, "duration": total_seconds}


def main() -> int:
    parser = argparse.ArgumentParser(description="Render an offline NOVA-MAT technical walkthrough in the product-demo style.")
    parser.add_argument("--storyboard", type=Path, default=Path("docs/demo/technical_bstyle.json"), help="Pinned technical walkthrough configuration JSON.")
    parser.add_argument("--audio-dir", type=Path, default=Path(".verification-repro/demo-videos/audio"), help="Directory containing the previously recorded technical scene WAVs.")
    parser.add_argument("--output-dir", type=Path, default=Path(".verification-repro/demo-videos-bstyle"), help="New local output directory for this style revision.")
    parser.add_argument("--ffmpeg", type=str, help="Path to the local FFmpeg executable; not required in preview-only mode.")
    parser.add_argument("--preview-only", action="store_true", help="Render six stills and a contact sheet without encoding video.")
    args = parser.parse_args()
    if (W, H, FPS) != (1920, 1080, 30):
        fail("video geometry is fixed at 1920x1080 / 30 fps")
    config_path = args.storyboard.resolve()
    config = load_json(config_path)
    evidence, storyboard, audio_story, source_paths = validate_inputs(config)
    if len(source_paths) != len(config["input_pins"]["public_aggregate_exports"]):
        fail("source binding count mismatch")
    global RUN_EVIDENCE
    RUN_EVIDENCE = evidence
    reference_pin = config.get("style_reference", {})
    reference_path = str(reference_pin.get("path", ""))
    if not reference_path.startswith(".verification-repro/demo-videos-bstyle/reference/"):
        fail("style reference must use the safe repository-relative reference path")
    reference_resolved = (ROOT / reference_path).resolve()
    try:
        reference_resolved.relative_to(ROOT)
    except ValueError:
        fail("style reference escapes the workspace")
    if reference_resolved.is_file():
        verify_file_pin(reference_path, reference_pin.get("sha256", ""), "style reference video")
        style_reference = {"path": reference_path, "sha256": reference_pin["sha256"], "verified": True}
    elif reference_pin.get("required_for_render") is True:
        fail(f"required style reference is missing: {reference_path}")
    else:
        style_reference = {"path": reference_path, "sha256": reference_pin.get("sha256"), "verified": False, "available": False}
    bound = {
        "config": {"path": str(config_path.relative_to(ROOT)), "sha256": sha256(config_path)},
        "evidence_index": {"path": config["input_pins"]["evidence_index"]["path"], "sha256": config["input_pins"]["evidence_index"]["sha256"]},
        "narration_storyboard": {"path": config["input_pins"]["narration_storyboard"]["path"], "sha256": config["input_pins"]["narration_storyboard"]["sha256"]},
        "public_aggregate_exports": [
            {"path": entry["path"], "sha256": entry["sha256"]} for entry in config["input_pins"]["public_aggregate_exports"]
        ],
        "style_reference": style_reference,
        "validated_lineage": validate_lineage(config, evidence),
    }
    audio_dir = args.audio_dir.resolve()
    scenes = config["scenes"]
    plans = validate_audio_and_plan(scenes, audio_dir, config)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    still_dir = output_dir / "technical_walkthrough_bstyle_stills"
    if args.preview_only:
        preview = write_previews(plans, output_dir, bound)
        preview["config"] = str(config_path)
        preview["config_sha256"] = sha256(config_path)
        preview["evidence_sha256"] = sha256(ROOT / "docs/demo/evidence.json")
        preview["narration_source"] = str((ROOT / config["input_pins"]["narration_storyboard"]["path"]).resolve())
        preview["source_paths"] = [str(path.relative_to(ROOT)) for path in source_paths]
        preview["style_reference"] = style_reference
        preview_path = output_dir / "technical_walkthrough_bstyle_preview_manifest.json"
        preview_path.write_text(json.dumps(preview, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Preview contact sheet: {output_dir / preview['contact_sheet']}")
        print(f"Preview manifest: {preview_path}")
        print(f"Planned duration: {preview['duration_seconds']:.3f}s")
        return 0
    ffmpeg = media.resolve_ffmpeg(args.ffmpeg)
    result = encode(plans, output_dir, ffmpeg, W, H, bound)
    print(f"Rendered: {result['video']} ({result['duration']:.3f}s, 1920x1080, H.264/AAC)")
    print(f"Captions: {result['captions']}")
    print(f"Contact sheet: {result['contact_sheet']}")
    print(f"Manifest: {result['manifest']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("Interrupted.")
