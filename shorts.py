#!/usr/bin/env python3
"""Agent-friendly CLI for creating and rendering vertical Shorts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PIPELINE = ROOT / "pipeline"
EPISODES = ROOT / "episodes"
CONFIG = PIPELINE / "config.json"
SCHEMA = ROOT / "contracts" / "episode.schema.json"
sys.path.insert(0, str(PIPELINE))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:64] or "short"


def episode_dir(slug: str) -> Path:
    return EPISODES / slug


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scene_count(ep_dir: Path) -> int:
    episode_path = ep_dir / "episode.json"
    if not episode_path.exists():
        return 0
    scenes = read_json(episode_path).get("scenes", [])
    return len(scenes) if isinstance(scenes, list) else 0


def _approval_valid(ep_dir: Path) -> bool:
    board = ep_dir / "storyboard" / "contact-sheet.png"
    marker = ep_dir / "storyboard" / "approved.json"
    if not board.exists() or not marker.exists():
        return False
    try:
        approval = read_json(marker)
        return (
            approval.get("contact_sheet_sha256") == sha256(board)
            and approval.get("scene_count") == _scene_count(ep_dir)
        )
    except (OSError, ValueError, TypeError):
        return False


def status_for(ep_dir: Path) -> dict:
    count = _scene_count(ep_dir)
    present = sum((ep_dir / "scenes" / f"scene_{i}.png").exists() for i in range(1, count + 1))
    board = ep_dir / "storyboard" / "contact-sheet.png"
    result = {
        "slug": ep_dir.name,
        "request": (ep_dir / "request.json").exists(),
        "episode": (ep_dir / "episode.json").exists(),
        "voice": (ep_dir / "voice.mp3").exists(),
        "captions": (ep_dir / "words.json").exists(),
        "scenes_expected": count,
        "scenes_present": present,
        "storyboard": board.exists(),
        "approved": _approval_valid(ep_dir),
        "final": (ep_dir / "out" / "final.mp4").exists(),
    }
    if result["final"]:
        result["next_action"] = "done"
    elif result["approved"]:
        result["next_action"] = "render"
    elif result["storyboard"]:
        result["next_action"] = "human_review_then_approve"
    elif count and present == count and result["voice"] and result["captions"]:
        result["next_action"] = "board"
    else:
        result["next_action"] = "agent_create_missing_assets"
    return result


def command_init(args: argparse.Namespace) -> None:
    slug = args.slug or slugify(args.topic)
    ep_dir = episode_dir(slug)
    ep_dir.mkdir(parents=True, exist_ok=True)
    request_path = ep_dir / "request.json"
    if request_path.exists() and not args.force:
        raise SystemExit(f"Request already exists: {request_path} (use --force to replace it)")
    config = read_json(CONFIG)
    request = {
        "protocol_version": "1.0",
        "topic": args.topic,
        "slug": slug,
        "language": args.language or config.get("language", "en"),
        "target": {
            "scene_count": args.scenes or config["video"]["scene_count"],
            "width": config["video"]["width"],
            "height": config["video"]["height"],
            "fps": config["video"]["fps"],
            "words": config["script"]["target_words"],
        },
        "contract": "../../contracts/episode.schema.json",
        "instructions": "Read AGENTS.md. Create assets, validate, build storyboard, then stop for human approval.",
    }
    write_json(request_path, request)
    print(request_path)


def validation_errors(ep_dir: Path) -> list[str]:
    errors: list[str] = []
    episode_path = ep_dir / "episode.json"
    if not episode_path.exists():
        return [f"missing {episode_path}"]
    try:
        episode = read_json(episode_path)
    except (OSError, json.JSONDecodeError) as error:
        return [f"invalid episode.json: {error}"]
    try:
        import jsonschema
        jsonschema.validate(episode, read_json(SCHEMA))
    except ImportError:
        for key in ("topic", "title", "narration", "scenes", "description", "tags", "hashtags"):
            if key not in episode:
                errors.append(f"episode.json missing required key: {key}")
    except Exception as error:  # jsonschema exposes several validation subclasses
        errors.append(f"episode.json schema error: {error}")

    scenes = episode.get("scenes", [])
    if isinstance(scenes, list):
        for index in range(1, len(scenes) + 1):
            if not (ep_dir / "scenes" / f"scene_{index}.png").exists():
                errors.append(f"missing scenes/scene_{index}.png")
    if not (ep_dir / "voice.mp3").exists():
        errors.append("missing voice.mp3")
    words_path = ep_dir / "words.json"
    if not words_path.exists():
        errors.append("missing words.json")
    else:
        try:
            words = read_json(words_path)
            if float(words.get("audio_duration", 0)) <= 0:
                errors.append("words.json audio_duration must be > 0")
            if not isinstance(words.get("words"), list) or not words["words"]:
                errors.append("words.json words must be a non-empty array")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            errors.append(f"invalid words.json: {error}")
    return errors


def command_validate(args: argparse.Namespace) -> None:
    ep_dir = episode_dir(args.slug)
    errors = validation_errors(ep_dir)
    if errors:
        print("\n".join(f"ERROR: {item}" for item in errors), file=sys.stderr)
        raise SystemExit(2)
    print(f"OK: {ep_dir}")


def command_captions(args: argparse.Namespace) -> None:
    ep_dir = episode_dir(args.slug)
    episode = read_json(ep_dir / "episode.json")
    voice = ep_dir / "voice.mp3"
    if not voice.exists():
        raise SystemExit(f"Missing {voice}")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(voice)],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise SystemExit(f"ffprobe failed: {probe.stderr.strip()}")
    duration = float(probe.stdout.strip())
    tokens = re.findall(r"[\w']+[^\w\s]*", episode["narration"], flags=re.UNICODE)
    if not tokens:
        raise SystemExit("Narration contains no words")
    step = duration / len(tokens)
    words = [
        {"word": token, "start": round(i * step, 3), "end": round((i + 1) * step, 3)}
        for i, token in enumerate(tokens)
    ]
    write_json(ep_dir / "words.json", {"audio_duration": round(duration, 3), "source": "uniform-known-text", "words": words})
    print(ep_dir / "words.json")


def command_board(args: argparse.Namespace) -> None:
    ep_dir = episode_dir(args.slug)
    errors = validation_errors(ep_dir)
    if errors:
        print("\n".join(f"ERROR: {item}" for item in errors), file=sys.stderr)
        raise SystemExit(2)
    from PIL import Image, ImageDraw, ImageOps

    count = _scene_count(ep_dir)
    cols = min(4, count)
    rows = (count + cols - 1) // cols
    cell_w, cell_h, label_h = 270, 480, 44
    sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + label_h)), "#111111")
    draw = ImageDraw.Draw(sheet)
    for index in range(1, count + 1):
        image = Image.open(ep_dir / "scenes" / f"scene_{index}.png").convert("RGB")
        image = ImageOps.fit(image, (cell_w, cell_h), method=Image.Resampling.LANCZOS)
        x = ((index - 1) % cols) * cell_w
        y = ((index - 1) // cols) * (cell_h + label_h)
        sheet.paste(image, (x, y))
        draw.rectangle((x, y + cell_h, x + cell_w, y + cell_h + label_h), fill="#111111")
        draw.text((x + 12, y + cell_h + 12), f"SCENE {index}", fill="white")
    storyboard = ep_dir / "storyboard"
    storyboard.mkdir(parents=True, exist_ok=True)
    board_path = storyboard / "contact-sheet.png"
    sheet.save(board_path, optimize=True)
    (storyboard / "approved.json").unlink(missing_ok=True)
    write_json(storyboard / "manifest.json", {"scene_count": count, "contact_sheet_sha256": sha256(board_path)})
    print(board_path)


def command_approve(args: argparse.Namespace) -> None:
    ep_dir = episode_dir(args.slug)
    board = ep_dir / "storyboard" / "contact-sheet.png"
    if not board.exists():
        raise SystemExit("No storyboard. Run board first and review the contact sheet.")
    marker = {
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "approved_by": args.by,
        "contact_sheet_sha256": sha256(board),
        "scene_count": _scene_count(ep_dir),
    }
    write_json(ep_dir / "storyboard" / "approved.json", marker)
    print(ep_dir / "storyboard" / "approved.json")


def command_render(args: argparse.Namespace) -> None:
    ep_dir = episode_dir(args.slug)
    errors = validation_errors(ep_dir)
    if errors:
        print("\n".join(f"ERROR: {item}" for item in errors), file=sys.stderr)
        raise SystemExit(2)
    if not _approval_valid(ep_dir):
        raise SystemExit("Render blocked: storyboard is missing, unapproved, or changed after approval.")
    import run as pipeline_run
    import sfx as sfx_stage

    config = read_json(CONFIG)
    if config.get("sfx", {}).get("enable", False):
        sfx_stage.synthesize(config)
    final = pipeline_run.assemble(ep_dir, config, force=args.force)
    print(final)


def command_status(args: argparse.Namespace) -> None:
    result = status_for(episode_dir(args.slug))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")


def command_doctor(_args: argparse.Namespace) -> None:
    checks = {
        "python>=3.11": sys.version_info >= (3, 11),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "node": shutil.which("node") is not None,
        "npm": shutil.which("npm") is not None,
        "remotion_dependencies": (PIPELINE / "remotion" / "node_modules" / ".bin" / "remotion").exists(),
    }
    for module in ("PIL", "numpy"):
        try:
            __import__(module)
            checks[f"python:{module}"] = True
        except ImportError:
            checks[f"python:{module}"] = False
    for name, passed in checks.items():
        print(f"{'OK' if passed else 'MISSING'}  {name}")
    if not all(checks.values()):
        raise SystemExit(2)


def command_demo(args: argparse.Namespace) -> None:
    from PIL import Image, ImageDraw

    topic = "A local demo built without API keys"
    init_args = argparse.Namespace(topic=topic, slug=args.slug, language="en", scenes=4, force=True)
    command_init(init_args)
    ep_dir = episode_dir(args.slug)
    narration = "This demo proves the workflow works without bundled keys. Four generated cards become a vertical short. The storyboard still needs your explicit approval before rendering."
    episode = {
        "topic": topic,
        "title": "A Keyless Shorts Workflow",
        "narration": narration,
        "scenes": ["Plan", "Create assets", "Review storyboard", "Render safely"],
        "description": "Synthetic local demo for Agent Shorts Kit.",
        "tags": ["shorts", "automation", "ai agent"],
        "hashtags": ["#shorts", "#automation"],
    }
    write_json(ep_dir / "episode.json", episode)
    scenes_dir = ep_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    colors = ("#183153", "#5b2c6f", "#0e6251", "#784212")
    for index, label in enumerate(episode["scenes"], start=1):
        image = Image.new("RGB", (1080, 1920), colors[index - 1])
        draw = ImageDraw.Draw(image)
        draw.text((90, 850), f"{index}. {label}", fill="white", stroke_width=2, stroke_fill="black")
        image.save(scenes_dir / f"scene_{index}.png")
    voice = ep_dir / "voice.mp3"
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=8", "-q:a", "4", str(voice)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg demo audio failed: {result.stderr.strip()}")
    command_captions(argparse.Namespace(slug=args.slug))
    command_board(argparse.Namespace(slug=args.slug))
    print("Demo assets are ready. Review the storyboard; approval was intentionally not created.")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="shorts", description="Provider-neutral Shorts production CLI")
    sub = cli.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create an agent request")
    init.add_argument("--topic", required=True)
    init.add_argument("--slug")
    init.add_argument("--language")
    init.add_argument("--scenes", type=int)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)
    for name, func in (("validate", command_validate), ("captions", command_captions), ("board", command_board)):
        command = sub.add_parser(name)
        command.add_argument("--slug", required=True)
        command.set_defaults(func=func)
    approve = sub.add_parser("approve")
    approve.add_argument("--slug", required=True)
    approve.add_argument("--by", default="human-owner")
    approve.set_defaults(func=command_approve)
    render = sub.add_parser("render")
    render.add_argument("--slug", required=True)
    render.add_argument("--force", action="store_true")
    render.set_defaults(func=command_render)
    status = sub.add_parser("status")
    status.add_argument("--slug", required=True)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)
    doctor = sub.add_parser("doctor")
    doctor.set_defaults(func=command_doctor)
    demo = sub.add_parser("demo")
    demo.add_argument("--slug", default="demo")
    demo.set_defaults(func=command_demo)
    return cli


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

