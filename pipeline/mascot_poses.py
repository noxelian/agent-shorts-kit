"""Stage 5.5: per-episode mascot pose pack via the Grok EDIT endpoint.

episode.json optional field:
    "mascot_poses": [{"scene": 1, "pose": "smirking with arms crossed"}, ...]

For each entry this optional stage generates a pose sprite of the same character
(reference image = assets/mascot/mascot.png) and knocks out its solid
background, writing:

    <episode>/mascot/pose_scene_N_raw.png   raw grok output (kept for QA)
    <episode>/mascot/pose_scene_N.png       transparent sprite staged by run.py

The mascot then SWAPS pose at every scene boundary in Remotion instead of
standing in the corner as a static puppet.

Guarantees mirror animate.py: resumable (skips existing sprites), cost-capped
by scenes_adapter.max_usd_per_episode, and NEVER blocks the pipeline (any
failure logs loudly and that scene simply keeps the base narrator sprite).

Standalone:  python mascot_poses.py --episode ../episodes/ep021-usa-beat-england-1950
Via run.py:  generate_poses(episode_dir, config)
"""
from __future__ import annotations

import argparse
from pathlib import Path

from common import EpisodePaths, PROJECT_DIR, get_env, load_config, log, read_json
from mascot_util import knockout_background

POSE_PROMPT_TEMPLATE = (
    "Exactly the same character as the reference image: keep identity, colors, "
    "outfit, proportions and art style, but change the pose to: {pose}. "
    "Full body visible, single character centered, solid dark background. "
    "No text, logo or watermark."
)


def _mascot_reference() -> Path | None:
    mascot_dir = PROJECT_DIR / "assets" / "mascot"
    for name in ("mascot.png", "character.png", "raccoon-test.png", "raccoon.png"):
        candidate = mascot_dir / name
        if candidate.exists():
            return candidate
    return None


def _valid_pose_entries(episode: dict, scene_count: int) -> list[dict]:
    """Soft-validate episode.json 'mascot_poses' into [{scene, pose}] with a
    1-based in-range scene int and a non-empty pose string. Malformed entries
    are dropped (old episodes without the field simply return [])."""
    raw = episode.get("mascot_poses")
    if not isinstance(raw, list):
        return []
    entries: list[dict] = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        scene = item.get("scene")
        pose = item.get("pose")
        if not (isinstance(scene, int) and not isinstance(scene, bool) and 1 <= scene <= scene_count):
            continue
        if not (isinstance(pose, str) and pose.strip()) or scene in seen:
            continue
        entries.append({"scene": scene, "pose": pose.strip()})
        seen.add(scene)
    return entries


def pose_sprite_path(episode_dir: Path, scene: int) -> Path:
    return Path(episode_dir) / "mascot" / f"pose_scene_{scene}.png"


def generate_poses(episode_dir: Path, config: dict, force: bool = False) -> dict[int, str]:
    """Generate the pose pack. Returns {scene: status} for reporting."""
    import grok_image

    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()
    episode = read_json(paths.episode_json)
    entries = _valid_pose_entries(episode, len(episode.get("scenes", [])))
    if not entries:
        log("mascot", "no mascot_poses in episode.json -> base narrator sprite only")
        return {}

    if not get_env("FAL_KEY"):
        log("mascot", "!!! FAL_KEY not set (pipeline/.env) -> skipping pose pack")
        return {}

    adapter = config["scenes_adapter"]
    model = str(adapter.get("grok_edit_model", grok_image.GROK_EDIT_MODEL))
    usd_per_pose = float(adapter.get("grok_usd_per_edit", grok_image.USD_PER_EDIT))
    max_usd = float(adapter.get("max_usd_per_episode", 0.30))
    poll_timeout = int(adapter.get("grok_poll_timeout_seconds", 240))

    reference = _mascot_reference()
    if reference is None:
        log("mascot", "!!! no mascot sprite in assets/mascot -> skipping pose pack")
        return {}

    mascot_dir = paths.root / "mascot"
    mascot_dir.mkdir(parents=True, exist_ok=True)

    reference_url: str | None = None
    statuses: dict[int, str] = {}
    spent = 0.0
    for entry in entries:
        scene = entry["scene"]
        sprite = pose_sprite_path(paths.root, scene)
        if sprite.exists() and not force:
            statuses[scene] = "cached"
            log("mascot", f"pose_scene_{scene}.png exists, skipping (no cost)")
            continue
        if spent + usd_per_pose > max_usd + 1e-9:
            statuses[scene] = "skipped (budget)"
            log("mascot", f"!!! COST GUARD: ${spent:.3f} + ${usd_per_pose:.3f} would exceed "
                          f"${max_usd:.2f} -> pose for scene {scene} skipped")
            continue

        raw = mascot_dir / f"pose_scene_{scene}_raw.png"
        try:
            if reference_url is None:
                reference_url = grok_image.upload_image(reference)
            grok_image.edit_image(
                POSE_PROMPT_TEMPLATE.format(pose=entry["pose"]), [reference_url], raw,
                model=model, aspect_ratio="1:1", resolution="1k", poll_timeout=poll_timeout,
            )
            knockout_background(raw, sprite)
        except Exception as error:  # noqa: BLE001 - scene keeps the base sprite
            raw.unlink(missing_ok=True)
            sprite.unlink(missing_ok=True)
            statuses[scene] = f"error: {error}"
            log("mascot", f"!!! pose generation FAILED for scene {scene}: {error}")
            log("mascot", "!!! That scene keeps the base narrator sprite. Pipeline continues.")
            continue

        spent += usd_per_pose
        statuses[scene] = "generated"
        log("mascot", f"pose_scene_{scene}.png ready ('{entry['pose'][:60]}', "
                      f"~${usd_per_pose:.3f}, running total ${spent:.3f})")

    generated = sum(1 for value in statuses.values() if value == "generated")
    log("mascot", f"pose pack: {generated} generated, "
                  f"{sum(1 for v in statuses.values() if v == 'cached')} cached, ~${spent:.3f}")
    return statuses


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the per-episode mascot pose pack via Grok edit")
    parser.add_argument("--episode", required=True, help="episode working directory")
    parser.add_argument("--force", action="store_true", help="regenerate even if pose sprites exist")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    statuses = generate_poses(Path(args.episode), load_config(), force=args.force)
    for scene in sorted(statuses):
        print(f"scene_{scene}: {statuses[scene]}")


if __name__ == "__main__":
    main()
