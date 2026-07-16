"""Product-level validation, provenance, QA and release gates.

This module deliberately uses files as the workflow state. Every approval is
content-addressed, so changing an input or final asset invalidates downstream
state instead of silently reusing stale output.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PIPELINE = Path(__file__).resolve().parent
ROOT = PIPELINE.parent
PRODUCTION = PIPELINE / "production.json"
CONFIG = PIPELINE / "config.json"
CONTRACTS = ROOT / "contracts"

PLACEHOLDER_RE = re.compile(
    r"\b(?:replace(?:\s+with)?|placeholder|narration beat|describe visual beat|"
    r"your verified story|define recurring characters)\b",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_json(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def file_record(path: Path) -> dict:
    record = {"path": _relative(path), "exists": path.exists()}
    if path.exists() and path.is_file():
        record.update({"bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return record


def configured_references() -> list[Path]:
    if not PRODUCTION.exists():
        return []
    production = read_json(PRODUCTION)
    return [(ROOT / item).resolve() for item in production.get("reference_images", [])]


def input_manifest(episode_dir: Path) -> dict:
    episode_dir = episode_dir.resolve()
    records = {
        "bits": file_record(episode_dir / "bits.json"),
        "episode": file_record(episode_dir / "episode.json"),
        "production": file_record(PRODUCTION),
        "render_config": file_record(CONFIG),
        "references": [file_record(path) for path in configured_references()],
    }
    return {"version": 2, "files": records, "sha256": sha256_json(records)}


def _matches_type(value: Any, expected: str) -> bool:
    mapping = {
        "object": dict, "array": list, "string": str, "integer": int,
        "number": (int, float), "boolean": bool,
    }
    kind = mapping.get(expected)
    return True if kind is None else isinstance(value, kind) and not (
        expected in {"integer", "number"} and isinstance(value, bool)
    )


def _basic_schema_errors(value: Any, schema: dict, where: str = "$") -> list[str]:
    """Validate the small JSON-Schema subset used by this repository.

    Keeping this dependency-free avoids architecture-specific wheels in the
    mandatory setup while the schemas remain the source of truth.
    """
    errors: list[str] = []
    expected = schema.get("type")
    if expected and not _matches_type(value, expected):
        return [f"{where}: expected {expected}"]
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{where}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(_basic_schema_errors(item, properties[key], f"{where}.{key}"))
    elif isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            errors.append(f"{where}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{where}: allows at most {schema['maxItems']} item(s)")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(_basic_schema_errors(item, item_schema, f"{where}[{index}]"))
    elif isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(f"{where}: is shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{where}: is longer than {schema['maxLength']} characters")
        if schema.get("pattern") and not re.search(schema["pattern"], value):
            errors.append(f"{where}: does not match {schema['pattern']!r}")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{where}: is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{where}: exceeds maximum {schema['maximum']}")
    return errors


def _schema_errors(path: Path, schema_name: str) -> list[str]:
    if not path.exists():
        return [f"missing {path.name}"]
    try:
        data = read_json(path)
        schema = read_json(CONTRACTS / schema_name)
    except (OSError, json.JSONDecodeError) as error:
        return [f"{path.name}: {error}"]
    return [f"{path.name}:{item}" for item in _basic_schema_errors(data, schema)]


def _placeholder_paths(value: Any, prefix: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, str) and PLACEHOLDER_RE.search(value):
        found.append(prefix)
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(_placeholder_paths(item, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_placeholder_paths(item, f"{prefix}[{index}]"))
    return found


def _normal_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def validate_episode(episode_dir: Path) -> dict:
    episode_dir = episode_dir.resolve()
    errors = _schema_errors(episode_dir / "bits.json", "bits.schema.json")
    errors += _schema_errors(episode_dir / "episode.json", "episode.schema.json")
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    bits: dict = {}
    episode: dict = {}
    try:
        bits = read_json(episode_dir / "bits.json")
        episode = read_json(episode_dir / "episode.json")
    except (OSError, json.JSONDecodeError):
        pass

    if bits:
        placeholders = _placeholder_paths(bits)
        if placeholders:
            errors.append("bits.json contains placeholders at " + ", ".join(placeholders[:8]))
        scenes = bits.get("bits") if isinstance(bits.get("bits"), list) else []
        actual_numbers = [item.get("n") for item in scenes if isinstance(item, dict)]
        if actual_numbers != list(range(1, len(scenes) + 1)):
            errors.append("bits.json scene numbers must be sequential from 1")
        declared = (bits.get("meta") or {}).get("scene_count")
        if declared != len(scenes):
            errors.append(f"bits.json meta.scene_count={declared!r} but contains {len(scenes)} bits")

    if episode:
        placeholders = _placeholder_paths(episode)
        if placeholders:
            errors.append("episode.json contains placeholders at " + ", ".join(placeholders[:8]))

    if bits and episode:
        scenes = bits.get("bits", [])
        narration = _normal_text(str(episode.get("narration", "")))
        voiced = _normal_text(" ".join(str(item.get("vo", "")) for item in scenes))
        if narration and voiced != narration:
            errors.append("bits[].vo must cover episode narration verbatim, contiguously and in order")
        episode_scenes = episode.get("scenes") or []
        if len(episode_scenes) != len(scenes):
            errors.append(
                f"episode.json has {len(episode_scenes)} scenes but bits.json has {len(scenes)}"
            )
        word_count = len(re.findall(r"[A-Za-z0-9']+", narration))
        estimate = round(word_count / 2.5, 1) if word_count else 0.0
        target = float((bits.get("meta") or {}).get("target_duration_seconds") or 0)
        metrics.update({"word_count": word_count, "estimated_seconds": estimate, "target_seconds": target})
        if target and estimate and abs(estimate - target) / target > 0.25:
            warnings.append(
                f"estimated narration duration {estimate}s differs from target {target:g}s by more than 25%"
            )

    refs = configured_references()
    missing_refs = [path for path in refs if not path.exists()]
    if not refs:
        warnings.append("no identity/style reference images configured")
    if missing_refs:
        errors.append("missing reference images: " + ", ".join(_relative(path) for path in missing_refs))
    if not (episode_dir / "sources.md").exists() and not episode.get("sources"):
        warnings.append("no sources.md or episode.sources found; factual Shorts should retain sources")

    return {
        "version": 2,
        "episode": episode_dir.name,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "input": input_manifest(episode_dir),
    }


def approval_payload(episode_dir: Path, board_raw: Path, scene_count: int) -> dict:
    manifest = input_manifest(episode_dir)
    return {
        "version": 2,
        "approved_at": utc_now(),
        "board_raw_sha256": sha256_file(board_raw),
        "scene_count": scene_count,
        "input_sha256": manifest["sha256"],
        "input": manifest["files"],
    }


def approval_valid(episode_dir: Path) -> tuple[bool, list[str]]:
    episode_dir = episode_dir.resolve()
    board = episode_dir / "storyboard" / "board_raw.png"
    marker = episode_dir / "storyboard" / "approved.json"
    reasons: list[str] = []
    if not board.exists():
        reasons.append("storyboard board is missing")
    if not marker.exists():
        reasons.append("storyboard approval is missing")
    if reasons:
        return False, reasons
    try:
        approval = read_json(marker)
        bits = read_json(episode_dir / "bits.json").get("bits", [])
    except (OSError, json.JSONDecodeError, TypeError) as error:
        return False, [str(error)]
    if approval.get("version") != 2:
        reasons.append("approval predates the full input-hash gate; approve again")
    if approval.get("board_raw_sha256") != sha256_file(board):
        reasons.append("storyboard changed after approval")
    if approval.get("scene_count") != len(bits):
        reasons.append("scene count changed after approval")
    if approval.get("input_sha256") != input_manifest(episode_dir)["sha256"]:
        reasons.append("episode, beat plan, render config or references changed after approval")
    return not reasons, reasons


def _artifact_paths(episode_dir: Path) -> list[Path]:
    bits = read_json(episode_dir / "bits.json")
    count = len(bits.get("bits", []))
    generated_name = (bits.get("meta") or {}).get("bits_dirname") or "generated"
    paths: list[Path] = []
    for index in range(1, count + 1):
        paths.extend((
            episode_dir / generated_name / f"bit_{index:02d}.png",
            episode_dir / "scenes" / f"scene_{index}.png",
        ))
    paths.extend((
        episode_dir / "voice.mp3",
        episode_dir / "words.json",
        episode_dir / "out" / "props.json",
        episode_dir / "out" / "final.mp4",
    ))
    return paths


def write_build_manifest(episode_dir: Path) -> dict:
    episode_dir = episode_dir.resolve()
    approval_ok, approval_reasons = approval_valid(episode_dir)
    if not approval_ok:
        raise ValueError("cannot seal build: " + "; ".join(approval_reasons))
    records = [file_record(path) for path in _artifact_paths(episode_dir)]
    missing = [record["path"] for record in records if not record["exists"]]
    if missing:
        raise ValueError("cannot seal build; missing artifacts: " + ", ".join(missing))
    body = {
        "version": 2,
        "created_at": utc_now(),
        "episode": episode_dir.name,
        "input_sha256": input_manifest(episode_dir)["sha256"],
        "approval_sha256": sha256_file(episode_dir / "storyboard" / "approved.json"),
        "artifacts": records,
    }
    body["build_sha256"] = sha256_json({key: value for key, value in body.items() if key != "created_at"})
    write_json(episode_dir / "out" / "build-manifest.json", body)
    return body


def build_manifest_valid(episode_dir: Path) -> tuple[bool, list[str]]:
    episode_dir = episode_dir.resolve()
    path = episode_dir / "out" / "build-manifest.json"
    if not path.exists():
        return False, ["build manifest is missing; render again"]
    try:
        manifest = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        return False, [str(error)]
    reasons: list[str] = []
    expected_manifest_sha = sha256_json({
        key: value for key, value in manifest.items()
        if key not in {"created_at", "build_sha256"}
    })
    if manifest.get("build_sha256") != expected_manifest_sha:
        reasons.append("build manifest checksum is invalid")
    if manifest.get("input_sha256") != input_manifest(episode_dir)["sha256"]:
        reasons.append("build inputs changed after render")
    approval = episode_dir / "storyboard" / "approved.json"
    if not approval.exists() or manifest.get("approval_sha256") != sha256_file(approval):
        reasons.append("storyboard approval changed after render")
    for record in manifest.get("artifacts", []):
        path_value = ROOT / record.get("path", "")
        if not path_value.exists():
            reasons.append(f"artifact missing: {record.get('path')}")
        elif record.get("sha256") != sha256_file(path_value):
            reasons.append(f"artifact changed: {record.get('path')}")
    return not reasons, reasons


def _run(command: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def _midpoint_contact_sheet(episode_dir: Path, duration: float, count: int) -> Path:
    from PIL import Image, ImageDraw

    qa_dir = episode_dir / "qa"
    frames_dir = qa_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    for index in range(count):
        timestamp = duration * (index + 0.5) / count
        frame_path = frames_dir / f"scene-{index + 1:02d}.jpg"
        result = _run([
            "ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i",
            str(episode_dir / "out" / "final.mp4"), "-frames:v", "1", "-q:v", "2", str(frame_path),
        ], timeout=120)
        if result.returncode != 0 or not frame_path.exists():
            raise RuntimeError(f"failed to extract QA frame {index + 1}: {result.stderr[-300:]}")
        frames.append(Image.open(frame_path).convert("RGB"))
    columns = min(4, count)
    rows = math.ceil(count / columns)
    cell_w, cell_h = 270, 480
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#07101d")
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        frame.thumbnail((cell_w, cell_h))
        x = (index % columns) * cell_w + (cell_w - frame.width) // 2
        y = (index // columns) * cell_h + (cell_h - frame.height) // 2
        sheet.paste(frame, (x, y))
        draw.rectangle((x + 6, y + 6, x + 48, y + 38), fill="#07101d")
        draw.text((x + 14, y + 11), f"{index + 1:02d}", fill="#ffdf55")
    output = qa_dir / "midpoints-contact-sheet.jpg"
    sheet.save(output, quality=90)
    return output


def qa_episode(episode_dir: Path) -> dict:
    episode_dir = episode_dir.resolve()
    final = episode_dir / "out" / "final.mp4"
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    validation = validate_episode(episode_dir)
    if not validation["valid"]:
        errors.extend("validation: " + item for item in validation["errors"])
    build_ok, build_reasons = build_manifest_valid(episode_dir)
    if not build_ok:
        errors.extend("provenance: " + item for item in build_reasons)
    if not final.exists():
        errors.append("final.mp4 is missing")
    if errors:
        report = {
            "version": 2, "created_at": utc_now(), "episode": episode_dir.name,
            "passed": False, "errors": errors, "warnings": warnings, "metrics": metrics,
        }
        write_json(episode_dir / "qa" / "qa-report.json", report)
        return report

    probe = _run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(final)])
    if probe.returncode != 0:
        errors.append("ffprobe failed: " + probe.stderr[-300:])
        probe_data: dict = {}
    else:
        probe_data = json.loads(probe.stdout)
    duration = float((probe_data.get("format") or {}).get("duration") or 0)
    video_stream = next((item for item in probe_data.get("streams", []) if item.get("codec_type") == "video"), {})
    audio_stream = next((item for item in probe_data.get("streams", []) if item.get("codec_type") == "audio"), {})
    metrics.update({
        "duration_seconds": round(duration, 3),
        "width": video_stream.get("width"), "height": video_stream.get("height"),
        "video_codec": video_stream.get("codec_name"), "audio_codec": audio_stream.get("codec_name"),
        "final_sha256": sha256_file(final),
    })
    config = read_json(CONFIG)
    expected_w = int(config["video"]["width"])
    expected_h = int(config["video"]["height"])
    if (video_stream.get("width"), video_stream.get("height")) != (expected_w, expected_h):
        errors.append(f"expected {expected_w}x{expected_h}, got {video_stream.get('width')}x{video_stream.get('height')}")
    if not audio_stream:
        errors.append("audio stream is missing")

    decode = _run(["ffmpeg", "-v", "error", "-i", str(final), "-f", "null", "-"], timeout=900)
    if decode.returncode != 0 or decode.stderr.strip():
        errors.append("full decode failed: " + decode.stderr[-500:])

    video_scan = _run([
        "ffmpeg", "-hide_banner", "-i", str(final), "-vf",
        "blackdetect=d=0.30:pix_th=0.10,freezedetect=n=-50dB:d=1.50", "-an", "-f", "null", "-",
    ], timeout=900)
    black_ranges = re.findall(r"black_start:([0-9.]+).*?black_end:([0-9.]+)", video_scan.stderr)
    freeze_starts = re.findall(r"freeze_start: ([0-9.]+)", video_scan.stderr)
    if video_scan.returncode != 0:
        errors.append("video QA filters failed: " + video_scan.stderr[-500:])
    metrics.update({"black_ranges": black_ranges, "freeze_starts": freeze_starts})
    if black_ranges:
        errors.append(f"detected {len(black_ranges)} black segment(s)")
    if freeze_starts:
        errors.append(f"detected {len(freeze_starts)} frozen segment(s)")

    audio_scan = _run([
        "ffmpeg", "-hide_banner", "-i", str(final), "-af",
        "silencedetect=noise=-45dB:d=2.0,volumedetect", "-vn", "-f", "null", "-",
    ], timeout=900)
    silence_starts = re.findall(r"silence_start: ([0-9.]+)", audio_scan.stderr)
    if audio_scan.returncode != 0:
        errors.append("audio QA filters failed: " + audio_scan.stderr[-500:])
    mean_match = re.search(r"mean_volume: (-?[0-9.]+) dB", audio_scan.stderr)
    max_match = re.search(r"max_volume: (-?[0-9.]+) dB", audio_scan.stderr)
    metrics.update({
        "silence_starts": silence_starts,
        "mean_volume_db": float(mean_match.group(1)) if mean_match else None,
        "max_volume_db": float(max_match.group(1)) if max_match else None,
    })
    if silence_starts:
        warnings.append(f"detected {len(silence_starts)} silence segment(s) longer than 2s")
    if mean_match and float(mean_match.group(1)) < -35:
        errors.append("audio mean volume is below -35 dB")

    words_path = episode_dir / "words.json"
    if words_path.exists():
        words_data = read_json(words_path)
        words = words_data.get("words") or []
        times = [float(item.get("start", 0)) for item in words if isinstance(item, dict)]
        if not words:
            errors.append("words.json has no caption words")
        elif times != sorted(times):
            errors.append("caption timestamps are not monotonic")
        if words and float(words[-1].get("end", words[-1].get("start", 0))) > duration + 0.25:
            errors.append("caption timestamps extend beyond final video")
        metrics["caption_words"] = len(words)
    else:
        errors.append("words.json is missing")

    scene_count = len(read_json(episode_dir / "bits.json").get("bits", []))
    try:
        contact_sheet = _midpoint_contact_sheet(episode_dir, duration, scene_count)
        metrics["midpoints_contact_sheet"] = _relative(contact_sheet)
    except Exception as error:  # noqa: BLE001 - report the failure as QA failure
        errors.append(f"midpoint contact sheet failed: {error}")

    report = {
        "version": 2, "created_at": utc_now(), "episode": episode_dir.name,
        "passed": not errors, "errors": errors, "warnings": warnings, "metrics": metrics,
        "build_manifest_sha256": sha256_file(episode_dir / "out" / "build-manifest.json"),
    }
    write_json(episode_dir / "qa" / "qa-report.json", report)
    lines = [f"# QA — {episode_dir.name}", "", f"Status: {'PASS' if report['passed'] else 'FAIL'}", ""]
    lines += [f"- {key}: {value}" for key, value in metrics.items()]
    if errors:
        lines += ["", "## Errors", ""] + [f"- {item}" for item in errors]
    if warnings:
        lines += ["", "## Warnings", ""] + [f"- {item}" for item in warnings]
    (episode_dir / "qa" / "qa-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def write_release_package(
    episode_dir: Path, target_slot: str, timezone_name: str, language: str,
    category: str, audience: str,
) -> dict:
    episode_dir = episode_dir.resolve()
    qa_path = episode_dir / "qa" / "qa-report.json"
    if not qa_path.exists() or not read_json(qa_path).get("passed"):
        raise ValueError("release package requires a passing current QA report")
    build_ok, reasons = build_manifest_valid(episode_dir)
    if not build_ok:
        raise ValueError("release package blocked: " + "; ".join(reasons))
    episode = read_json(episode_dir / "episode.json")
    final = episode_dir / "out" / "final.mp4"
    qa_report = read_json(qa_path)
    if (qa_report.get("metrics") or {}).get("final_sha256") != sha256_file(final):
        raise ValueError("QA report does not match the current final video; run qa again")
    title = str(episode.get("title", "")).strip()
    description = str(episode.get("description", "")).strip()
    tags = episode.get("tags") or []
    hashtags = episode.get("hashtags") or []
    metadata_errors = []
    if title.lower() in {"", "final", "untitled", "untitled short"}:
        metadata_errors.append("title is empty or looks like a filename")
    if not description:
        metadata_errors.append("description is empty")
    if not tags:
        metadata_errors.append("tags are empty")
    if not hashtags:
        metadata_errors.append("hashtags are empty")
    if not target_slot.strip():
        metadata_errors.append("target slot is empty")
    if metadata_errors:
        raise ValueError("release metadata blocked: " + "; ".join(metadata_errors))
    build_manifest_path = episode_dir / "out" / "build-manifest.json"
    package = {
        "version": 2,
        "created_at": utc_now(),
        "episode": episode_dir.name,
        "file": "out/final.mp4",
        "final_sha256": sha256_file(final),
        "qa_sha256": sha256_file(qa_path),
        "build_manifest_sha256": sha256_file(build_manifest_path),
        "title": title,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "cta": episode.get("cta", ""),
        "pinned_comment": episode.get("pinned_comment", ""),
        "settings": {
            "target_slot": target_slot, "timezone": timezone_name, "language": language,
            "category": category, "audience": audience, "privacy": "private",
        },
        "status": "qa_passed_awaiting_release_approval",
    }
    path = episode_dir / "publish-package.json"
    write_json(path, package)
    lines = [
        f"# {package['title']} — Publish Package", "", "## File", "", "`out/final.mp4`", "",
        f"SHA-256: `{package['final_sha256']}`", "", "## Title", "", package["title"], "",
        "## Description", "", package["description"], "", "## Tags", "",
        ", ".join(package["tags"]), "", "## Hashtags", "",
        " ".join(package["hashtags"]), "", "## CTA", "", package["cta"] or "(not set)", "",
        "## Pinned comment", "", package["pinned_comment"] or "(not set)", "",
        "## Planned settings", "",
    ]
    lines += [f"- {key}: {value}" for key, value in package["settings"].items()]
    lines += ["", "## Status", "", "QA passed. Upload remains blocked pending explicit release approval."]
    (episode_dir / "publish-package.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (episode_dir / "release-approved.json").unlink(missing_ok=True)
    return package


def approve_release(episode_dir: Path, privacy: str) -> dict:
    episode_dir = episode_dir.resolve()
    package_path = episode_dir / "publish-package.json"
    qa_path = episode_dir / "qa" / "qa-report.json"
    final = episode_dir / "out" / "final.mp4"
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("privacy must be private, unlisted or public")
    if not package_path.exists():
        raise ValueError("create and review publish-package.json first")
    package = read_json(package_path)
    if not qa_path.exists() or not read_json(qa_path).get("passed"):
        raise ValueError("release approval requires passing QA")
    build_ok, build_reasons = build_manifest_valid(episode_dir)
    build_manifest_path = episode_dir / "out" / "build-manifest.json"
    if not build_ok:
        raise ValueError("build is stale: " + "; ".join(build_reasons))
    if (package.get("final_sha256") != sha256_file(final)
            or package.get("qa_sha256") != sha256_file(qa_path)
            or package.get("build_manifest_sha256") != sha256_file(build_manifest_path)):
        raise ValueError("build, final video or QA changed after release package; package again")
    approval = {
        "version": 2, "approved_at": utc_now(), "episode": episode_dir.name,
        "privacy": privacy, "publish_package_sha256": sha256_file(package_path),
        "qa_sha256": sha256_file(qa_path), "final_sha256": sha256_file(final),
        "build_manifest_sha256": sha256_file(build_manifest_path),
    }
    write_json(episode_dir / "release-approved.json", approval)
    return approval


def release_approval_valid(episode_dir: Path, privacy: str) -> tuple[bool, list[str]]:
    episode_dir = episode_dir.resolve()
    paths = {
        "approval": episode_dir / "release-approved.json",
        "package": episode_dir / "publish-package.json",
        "qa": episode_dir / "qa" / "qa-report.json",
        "final": episode_dir / "out" / "final.mp4",
        "build": episode_dir / "out" / "build-manifest.json",
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        return False, ["missing " + ", ".join(missing)]
    approval = read_json(paths["approval"])
    reasons: list[str] = []
    if approval.get("privacy") != privacy:
        reasons.append(f"release approval allows {approval.get('privacy')}, not {privacy}")
    expected = {
        "publish_package_sha256": sha256_file(paths["package"]),
        "qa_sha256": sha256_file(paths["qa"]),
        "final_sha256": sha256_file(paths["final"]),
        "build_manifest_sha256": sha256_file(paths["build"]),
    }
    for key, value in expected.items():
        if approval.get(key) != value:
            reasons.append(f"{key.removesuffix('_sha256')} changed after release approval")
    if not read_json(paths["qa"]).get("passed"):
        reasons.append("QA report is not passing")
    build_ok, build_reasons = build_manifest_valid(episode_dir)
    if not build_ok:
        reasons.extend("build: " + item for item in build_reasons)
    return not reasons, reasons


def write_batch_manifest(episodes: list[Path], output: Path, slots: list[str]) -> dict:
    rows = []
    for index, episode_dir in enumerate(episodes):
        final = episode_dir / "out" / "final.mp4"
        qa = episode_dir / "qa" / "qa-report.json"
        package = episode_dir / "publish-package.json"
        approval = episode_dir / "release-approved.json"
        approval_current = False
        if approval.exists():
            approval_current = release_approval_valid(
                episode_dir, str(read_json(approval).get("privacy", ""))
            )[0]
        release_status = episode_dir / "release-status.json"
        rows.append({
            "position": index + 1, "episode": episode_dir.name,
            "target_slot": slots[index] if index < len(slots) else "",
            "final_sha256": sha256_file(final) if final.exists() else None,
            "qa_passed": bool(qa.exists() and read_json(qa).get("passed")),
            "release_package": package.exists(), "release_approved": approval_current,
            "youtube": read_json(release_status) if release_status.exists() else None,
        })
    manifest = {"version": 2, "created_at": utc_now(), "episodes": rows}
    write_json(output, manifest)
    return manifest
