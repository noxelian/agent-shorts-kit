#!/usr/bin/env python3
"""Thin CLI over the production Shorts pipeline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PIPELINE = ROOT / "pipeline"
EPISODES = ROOT / "episodes"
CONFIG = PIPELINE / "config.json"
PRODUCTION = PIPELINE / "production.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:64] or "short"


def episode_dir(slug: str) -> Path:
    return EPISODES / slug


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approval_valid(ep_dir: Path) -> bool:
    board = ep_dir / "storyboard" / "board_raw.png"
    marker = ep_dir / "storyboard" / "approved.json"
    bits_path = ep_dir / "bits.json"
    if not all(path.exists() for path in (board, marker, bits_path)):
        return False
    try:
        approval = read_json(marker)
        bits = read_json(bits_path).get("bits", [])
        return approval.get("board_raw_sha256") == sha256(board) and approval.get("scene_count") == len(bits)
    except (OSError, ValueError, TypeError):
        return False


def status_for(ep_dir: Path) -> dict:
    bits_path = ep_dir / "bits.json"
    bits = read_json(bits_path).get("bits", []) if bits_path.exists() else []
    meta = read_json(bits_path).get("meta", {}) if bits_path.exists() else {}
    generated_name = meta.get("bits_dirname") or "generated"
    generated = ep_dir / generated_name
    count = len(bits)
    images = sum((generated / f"bit_{index:02d}.png").exists() for index in range(1, count + 1))
    installed = sum((ep_dir / "scenes" / f"scene_{index}.png").exists() for index in range(1, count + 1))
    result = {
        "slug": ep_dir.name,
        "plan": bits_path.exists(),
        "scene_count": count,
        "storyboard": (ep_dir / "storyboard" / "contact-sheet.png").exists(),
        "approved": approval_valid(ep_dir),
        "generated_images": images,
        "installed_scenes": installed,
        "voice": (ep_dir / "voice.mp3").exists(),
        "word_timestamps": (ep_dir / "words.json").exists(),
        "final": (ep_dir / "out" / "final.mp4").exists(),
    }
    if result["final"]:
        result["next_action"] = "done"
    elif installed == count and count:
        result["next_action"] = "render"
    elif images == count and count:
        result["next_action"] = "install"
    elif result["approved"]:
        result["next_action"] = "gen"
    elif result["storyboard"]:
        result["next_action"] = "human_review_then_approve"
    elif result["plan"]:
        result["next_action"] = "board"
    else:
        result["next_action"] = "init"
    return result


def command_init(args: argparse.Namespace) -> None:
    slug = args.slug or slugify(args.topic)
    ep_dir = episode_dir(slug)
    ep_dir.mkdir(parents=True, exist_ok=True)
    if (ep_dir / "bits.json").exists() and not args.force:
        raise SystemExit(f"Episode exists: {ep_dir} (use --force to replace templates)")
    bits = [
        {"n": index, "vo": f"Narration beat {index}", "desc": f"Describe visual beat {index}"}
        for index in range(1, args.scenes + 1)
    ]
    write_json(ep_dir / "bits.json", {
        "meta": {"slug": slug, "title": args.topic, "scene_count": args.scenes,
                 "target_duration_seconds": args.duration, "bits_dirname": "generated"},
        "world": "Define recurring characters, location, palette, period and visual prohibitions.",
        "bits": bits,
    })
    write_json(ep_dir / "episode.json", {
        "title": args.topic,
        "topic": args.topic,
        "narration": "Replace with the reviewed final narration.",
        "description": "",
        "tags": [],
        "hashtags": ["#Shorts"],
        "scenes": [item["desc"] for item in bits],
    })
    write_json(ep_dir / "request.json", {
        "workflow": "production-shorts-v1",
        "topic": args.topic,
        "instructions": "Read AGENTS.md. Research and replace every placeholder in bits.json and episode.json before board.",
    })
    print(ep_dir)


def run_builder(slug: str, command: str, extra: list[str] | None = None) -> None:
    cmd = [sys.executable, str(PIPELINE / "build_bits2.py"), slug, command]
    if extra:
        cmd.extend(extra)
    raise SystemExit(subprocess.run(cmd, cwd=PIPELINE).returncode)


def command_builder(args: argparse.Namespace) -> None:
    extra: list[str] = []
    if getattr(args, "provider", None):
        extra += ["--provider", args.provider]
    if getattr(args, "only", None):
        extra += ["--only", args.only]
    if getattr(args, "force", False):
        extra.append("--force")
    run_builder(args.slug, args.builder_command, extra)


def command_render(args: argparse.Namespace) -> None:
    ep_dir = episode_dir(args.slug)
    if not approval_valid(ep_dir):
        raise SystemExit("Render blocked: storyboard is not approved or changed after approval.")
    status = status_for(ep_dir)
    if status["installed_scenes"] != status["scene_count"]:
        raise SystemExit("Render blocked: run gen and install first.")
    episode = read_json(ep_dir / "episode.json")
    cmd = [sys.executable, str(PIPELINE / "run.py"), "--episode", str(ep_dir),
           "--topic", str(episode.get("topic") or episode.get("title") or args.slug)]
    if args.force:
        (ep_dir / "out" / "final.mp4").unlink(missing_ok=True)
    raise SystemExit(subprocess.run(cmd, cwd=PIPELINE).returncode)


def command_status(args: argparse.Namespace) -> None:
    data = status_for(episode_dir(args.slug))
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else "\n".join(f"{k}: {v}" for k, v in data.items()))


def command_doctor(_args: argparse.Namespace) -> None:
    production = read_json(PRODUCTION)
    refs = [(ROOT / item).resolve() for item in production.get("reference_images", [])]
    env_path = PIPELINE / ".env"
    env_values: dict[str, str] = dict(os.environ)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env_values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    provider = production.get("image_provider", "gemini")
    checks = {
        "python>=3.11": sys.version_info >= (3, 11),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "node": shutil.which("node") is not None,
        "npm": shutil.which("npm") is not None,
        "remotion": (PIPELINE / "remotion/node_modules/.bin/remotion").exists(),
        f"provider:{provider}": (
            bool(env_values.get("GEMINI_API_KEY") or env_values.get("GOOGLE_API_KEY")) if provider == "gemini" else
            bool((production.get("vertex") or {}).get("project") or env_values.get("GOOGLE_CLOUD_PROJECT"))
            if provider == "vertex" else bool(env_values.get("FAL_KEY"))
        ),
        "reference_images": bool(refs) and all(path.exists() for path in refs),
    }
    for name, ok in checks.items():
        print(f"{'OK' if ok else 'MISSING'}  {name}")
    optional_assets = {
        "music": ROOT / "assets/music/track.mp3",
        "endcard_image": ROOT / "assets/channel/avatar.png",
        "endcard_voice": ROOT / "assets/channel/endcard_voice.mp3",
    }
    for name, path in optional_assets.items():
        print(f"{'OK' if path.exists() else 'OPTIONAL'}  {name}")
    if not all(checks.values()):
        raise SystemExit(2)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Production Shorts pipeline")
    sub = cli.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--topic", required=True)
    init.add_argument("--slug")
    init.add_argument("--scenes", type=int, default=16)
    init.add_argument("--duration", type=int, default=43)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)
    for name in ("board", "approve", "gen", "install"):
        command = sub.add_parser(name)
        command.add_argument("--slug", required=True)
        if name in {"board", "gen"}:
            command.add_argument("--provider", choices=["gemini", "vertex", "fal"])
        if name == "gen":
            command.add_argument("--only")
        if name == "board":
            command.add_argument("--force", action="store_true")
        command.set_defaults(func=command_builder, builder_command=name)
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
    return cli


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
