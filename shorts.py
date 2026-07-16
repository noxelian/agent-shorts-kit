#!/usr/bin/env python3
"""Thin CLI over the production Shorts pipeline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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

sys.path.insert(0, str(PIPELINE))
from product import (  # noqa: E402
    approval_valid as product_approval_valid,
    approve_release,
    build_manifest_valid,
    qa_episode,
    release_approval_valid,
    validate_episode,
    write_batch_manifest,
    write_build_manifest,
    write_release_package,
)


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
    return product_approval_valid(ep_dir)[0]


def status_for(ep_dir: Path) -> dict:
    bits_path = ep_dir / "bits.json"
    bits = read_json(bits_path).get("bits", []) if bits_path.exists() else []
    meta = read_json(bits_path).get("meta", {}) if bits_path.exists() else {}
    generated_name = meta.get("bits_dirname") or "generated"
    generated = ep_dir / generated_name
    count = len(bits)
    images = sum((generated / f"bit_{index:02d}.png").exists() for index in range(1, count + 1))
    installed = sum((ep_dir / "scenes" / f"scene_{index}.png").exists() for index in range(1, count + 1))
    validation = validate_episode(ep_dir) if bits_path.exists() else {"valid": False, "errors": ["not initialized"]}
    build_current, build_reasons = build_manifest_valid(ep_dir)
    qa_path = ep_dir / "qa" / "qa-report.json"
    qa = read_json(qa_path) if qa_path.exists() else {}
    release_marker = ep_dir / "release-approved.json"
    release_current = False
    if release_marker.exists():
        release_current = release_approval_valid(
            ep_dir, str(read_json(release_marker).get("privacy", ""))
        )[0]
    release_status_path = ep_dir / "release-status.json"
    release_status = read_json(release_status_path) if release_status_path.exists() else {}
    result = {
        "slug": ep_dir.name,
        "plan": bits_path.exists(),
        "validated": validation["valid"],
        "validation_errors": validation.get("errors", []),
        "scene_count": count,
        "storyboard": (ep_dir / "storyboard" / "contact-sheet.png").exists(),
        "approved": approval_valid(ep_dir),
        "generated_images": images,
        "installed_scenes": installed,
        "voice": (ep_dir / "voice.mp3").exists(),
        "word_timestamps": (ep_dir / "words.json").exists(),
        "final_exists": (ep_dir / "out" / "final.mp4").exists(),
        "final_current": build_current,
        "build_errors": build_reasons,
        "qa_passed": bool(qa.get("passed") and build_current),
        "release_packaged": (ep_dir / "publish-package.json").exists(),
        "release_approved": release_current,
        "youtube_verified": bool(release_status.get("verified") and release_current),
    }
    if result["youtube_verified"]:
        result["next_action"] = "done"
    elif result["release_approved"]:
        result["next_action"] = "upload_or_schedule"
    elif result["release_packaged"] and result["qa_passed"]:
        result["next_action"] = "human_review_then_approve_release"
    elif result["qa_passed"]:
        result["next_action"] = "release"
    elif result["final_current"]:
        result["next_action"] = "qa"
    elif result["final_exists"]:
        result["next_action"] = "render_stale_final"
    elif result["plan"] and not result["validated"]:
        result["next_action"] = "fix_validation"
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
    report = validate_episode(episode_dir(args.slug))
    if not report["valid"]:
        for error in report["errors"]:
            print(f"ERROR  {error}", file=sys.stderr)
        raise SystemExit("Paid/production action blocked: run validate and fix the episode first.")
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
    report = validate_episode(ep_dir)
    if not report["valid"]:
        raise SystemExit("Render blocked: run validate and fix the episode first.")
    if not approval_valid(ep_dir):
        raise SystemExit("Render blocked: storyboard is not approved or changed after approval.")
    status = status_for(ep_dir)
    if status["installed_scenes"] != status["scene_count"]:
        raise SystemExit("Render blocked: run gen and install first.")
    episode = read_json(ep_dir / "episode.json")
    cmd = [sys.executable, str(PIPELINE / "run.py"), "--episode", str(ep_dir),
           "--topic", str(episode.get("topic") or episode.get("title") or args.slug)]
    final_path = ep_dir / "out" / "final.mp4"
    if final_path.exists() and not args.force:
        current, reasons = build_manifest_valid(ep_dir)
        if not current:
            raise SystemExit(
                "Render blocked: final.mp4 is stale (" + "; ".join(reasons)
                + "). Re-run render with --force."
            )
    if args.force:
        final_path.unlink(missing_ok=True)
    result = subprocess.run(cmd, cwd=PIPELINE)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    manifest = write_build_manifest(ep_dir)
    print(f"BUILD SEALED: {manifest['build_sha256']}")


def command_status(args: argparse.Namespace) -> None:
    data = status_for(episode_dir(args.slug))
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else "\n".join(f"{k}: {v}" for k, v in data.items()))


def command_validate(args: argparse.Namespace) -> None:
    report = validate_episode(episode_dir(args.slug))
    for error in report["errors"]:
        print(f"ERROR    {error}")
    for warning in report["warnings"]:
        print(f"WARNING  {warning}")
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else (
        f"{'VALID' if report['valid'] else 'INVALID'}  {args.slug}"
    ))
    if not report["valid"]:
        raise SystemExit(2)


def command_qa(args: argparse.Namespace) -> None:
    report = qa_episode(episode_dir(args.slug))
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else (
        f"QA {'PASS' if report['passed'] else 'FAIL'}: {episode_dir(args.slug) / 'qa/qa-report.md'}"
    ))
    if not report["passed"]:
        raise SystemExit(2)


def command_release(args: argparse.Namespace) -> None:
    package = write_release_package(
        episode_dir(args.slug), args.slot, args.timezone, args.language, args.category, args.audience,
    )
    print(f"RELEASE PACKAGE READY: {episode_dir(args.slug) / 'publish-package.md'}")
    print(f"Final SHA-256: {package['final_sha256']}")
    print("Upload remains blocked until approve-release is explicitly run.")


def command_approve_release(args: argparse.Namespace) -> None:
    approval = approve_release(episode_dir(args.slug), args.privacy)
    print(f"RELEASE APPROVED for privacy={approval['privacy']}: {episode_dir(args.slug) / 'release-approved.json'}")


def command_batch(args: argparse.Namespace) -> None:
    slugs = [item.strip() for item in args.slugs.split(",") if item.strip()]
    slots = [item.strip() for item in (args.slots or "").split(",") if item.strip()]
    output = Path(args.output).resolve()
    manifest = write_batch_manifest([episode_dir(slug) for slug in slugs], output, slots)
    print(f"BATCH MANIFEST: {output} ({len(manifest['episodes'])} episodes)")


def command_doctor(args: argparse.Namespace) -> None:
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
    try:
        from PIL import Image as _PillowImage  # noqa: F401
        pillow_ok = True
        pillow_error = ""
    except Exception as error:  # noqa: BLE001 - doctor must report broken native wheels
        pillow_ok = False
        pillow_error = str(error)
    checks = {
        "python>=3.11": (sys.version_info >= (3, 11), "Install Python 3.11 or newer."),
        "pillow": (pillow_ok, "Recreate .venv with scripts/setup.sh. " + pillow_error),
        "ffmpeg": (shutil.which("ffmpeg") is not None, "Install FFmpeg (macOS: brew install ffmpeg)."),
        "ffprobe": (shutil.which("ffprobe") is not None, "Install FFmpeg, which includes ffprobe."),
        "node": (shutil.which("node") is not None, "Install Node.js 20 or newer."),
        "npm": (shutil.which("npm") is not None, "Install npm with Node.js."),
        "remotion": ((PIPELINE / "remotion/node_modules/.bin/remotion").exists(),
                     "Run npm --prefix pipeline/remotion ci."),
        f"provider:{provider}": ((
            bool(env_values.get("GEMINI_API_KEY") or env_values.get("GOOGLE_API_KEY")) if provider == "gemini" else
            bool((production.get("vertex") or {}).get("project") or env_values.get("GOOGLE_CLOUD_PROJECT"))
            if provider == "vertex" else bool(env_values.get("FAL_KEY"))
        ), "Add the selected provider credential to pipeline/.env."),
        "reference_images": (bool(refs) and all(path.exists() for path in refs),
                             "Add owned reference images and list them in pipeline/production.json."),
    }
    rows = [
        {"name": name, "ok": ok, "fix": "" if ok else fix}
        for name, (ok, fix) in checks.items()
    ]
    optional_assets = {
        "music": ROOT / "assets/music/track.mp3",
        "endcard_image": ROOT / "assets/channel/avatar.png",
        "endcard_voice": ROOT / "assets/channel/endcard_voice.mp3",
    }
    if args.json:
        print(json.dumps({"ok": all(row["ok"] for row in rows), "architecture": platform.machine(),
                          "checks": rows, "optional_assets": {
                              name: path.exists() for name, path in optional_assets.items()
                          }}, ensure_ascii=False, indent=2))
    else:
        print(f"ARCH      {platform.machine()}")
        for row in rows:
            print(f"{'OK' if row['ok'] else 'MISSING'}  {row['name']}")
            if row["fix"]:
                print(f"         fix: {row['fix']}")
        for name, path in optional_assets.items():
            print(f"{'OK' if path.exists() else 'OPTIONAL'}  {name}")
    if not all(row["ok"] for row in rows):
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
    validate = sub.add_parser("validate")
    validate.add_argument("--slug", required=True)
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=command_validate)
    qa = sub.add_parser("qa")
    qa.add_argument("--slug", required=True)
    qa.add_argument("--json", action="store_true")
    qa.set_defaults(func=command_qa)
    release = sub.add_parser("release")
    release.add_argument("--slug", required=True)
    release.add_argument("--slot", required=True)
    release.add_argument("--timezone", default="UTC")
    release.add_argument("--language", default="English (United States)")
    release.add_argument("--category", default="Education")
    release.add_argument("--audience", default="not made for kids")
    release.set_defaults(func=command_release)
    approve_upload = sub.add_parser("approve-release")
    approve_upload.add_argument("--slug", required=True)
    approve_upload.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    approve_upload.set_defaults(func=command_approve_release)
    batch = sub.add_parser("batch")
    batch.add_argument("--slugs", required=True, help="comma-separated episode slugs")
    batch.add_argument("--slots", help="comma-separated target slots in the same order")
    batch.add_argument("--output", required=True)
    batch.set_defaults(func=command_batch)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=command_doctor)
    return cli


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
