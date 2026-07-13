"""Optional stage 1: topic -> episode.json via a user-supplied agent command.

Standalone:  python generate_script.py --episode ../episodes/ep001-shortest-war \
                 --topic "The shortest war in history lasted 38 minutes"
Via run.py:  generate(episode_dir, topic, config)

Set SHORTS_AGENT_COMMAND to a command that accepts a prompt on stdin and prints
one JSON object on stdout. The main Agent Shorts Kit workflow can instead have
an AI agent write episode.json directly according to the public contract.
"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from common import EpisodePaths, extract_json_block, load_config, log, word_count, write_json

REQUIRED_KEYS = ("title", "narration", "scenes", "description", "tags", "hashtags")
# Optional keys (do NOT gate old episodes): animate reads hero_scene/hints,
# scenes.py reads visual_bible (continuity canon appended to every image
# prompt), mascot_poses.py reads mascot_poses. Validated softly below only
# when present.
OPTIONAL_KEYS = ("hero_scene", "hero_motion_hints", "visual_bible", "mascot_poses", "callouts")


def _build_prompt(topic: str, config: dict) -> str:
    target = config["script"]["target_words"]
    lo = config["script"]["min_words"]
    hi = config["script"]["max_words"]
    scene_count = config["video"]["scene_count"]
    language = config.get("language", "en")
    channel_brief = config.get("script", {}).get(
        "channel_brief",
        "an accurate, engaging vertical short for a general audience",
    )
    return (
        f"Write one {language}-language YouTube Short for {channel_brief}.\n\n"
        f"TOPIC: {topic}\n\n"
        "Requirements:\n"
        f"- narration: a single spoken paragraph, {lo}-{hi} words (aim {target}). "
        "Punchy hook in the first sentence, factually accurate, conversational, no stage directions, "
        "no markdown, plain sentences a TTS voice will read aloud.\n"
        f"- scenes: EXACTLY {scene_count} concrete visual descriptions with setting, action and mood. "
        "Do not put text, captions, logos or watermarks inside scene images.\n"
        "- title: <=90 chars, curiosity-driven, may use one emoji.\n"
        "- description: 2-3 sentences for the YouTube description box.\n"
        "- tags: 10-15 lowercase SEO keywords as a JSON array of strings.\n"
        "- hashtags: 3-5 strings starting with # (e.g. #history #shorts).\n"
        "- hero_scene: the 1-based index of the ONE scene best suited to subtle ambient "
        "animation (the most visually alive: a swaying crowd, waving flags, fire, smoke, "
        "waves, rain, drifting clouds). This scene will be turned into a short looping video.\n"
        "- hero_motion_hints: a short comma-separated phrase describing ONLY subtle ambient "
        "motion for that scene, e.g. 'crowd sways, flags wave, sunlight flickers'. NO new "
        "objects, events, or camera moves.\n"
        "- visual_bible: 1-2 sentences pinning the RECURRING visuals so every scene stays "
        "consistent: exact clothing/uniform colors for each side or character, the location "
        "and its palette (e.g. 'USA players wear plain white kits, England players wear red "
        "shirts with white shorts; 1950 Brazilian stadium with pale concrete stands'). This "
        "string is appended to every image prompt, so pin only what recurs across scenes.\n"
        "- callouts: a JSON array of 2-4 big on-screen text callouts that carry the STORY "
        "so a viewer who does NOT parse the fast narration still understands who-vs-who and "
        "what just happened. Each item is "
        '{"anchor": "<words>", "occurrence": 1, "text": "<SHORT UPPERCASE HEADLINE>", '
        '"style": "scoreboard" | "label" | "shock"}. '
        "CRITICAL: anchor MUST be words copied VERBATIM from your narration (the callout "
        "appears on screen exactly when that word is spoken); occurrence (1-based, default "
        "1) picks which repeat if the phrase recurs. Author an early matchup/setup "
        "(style scoreboard or label), the single KEY moment as style shock or scoreboard, "
        "and optionally a final verdict (shock). Keep every text to <=4 words. "
        "scoreboard = full-width event banner (a score / matchup), label = small corner "
        "tag (a place & year), shock = the big dramatic hit.\n\n"
        "Return ONLY a JSON object with keys: title, narration, scenes, description, tags, "
        "hashtags, hero_scene, hero_motion_hints, visual_bible, callouts. "
        "No markdown fences, no commentary."
    )


def _call_agent(prompt: str, timeout: int = 180) -> str:
    raw_command = os.environ.get("SHORTS_AGENT_COMMAND", "").strip()
    if not raw_command:
        raise RuntimeError("SHORTS_AGENT_COMMAND is not configured")
    command = shlex.split(raw_command)
    if not command or not shutil.which(command[0]):
        raise FileNotFoundError(f"agent command is unavailable: {raw_command}")
    result = subprocess.run(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"agent command exited {result.returncode}: {result.stderr[:300]}")
    return result.stdout


def _validate_episode(data: dict, config: dict) -> dict:
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"episode JSON missing keys: {missing}")
    scenes = data["scenes"]
    if not isinstance(scenes, list) or len(scenes) < 1:
        raise ValueError("scenes must be a non-empty list")
    wc = word_count(data["narration"])
    if wc < config["script"]["min_words"] - 30:
        raise ValueError(f"narration too short: {wc} words")
    # Soft-validate the optional animate keys: keep them only when well-formed so a
    # malformed value never reaches (or breaks) the animate stage. Never required.
    hero = data.get("hero_scene")
    if not (isinstance(hero, int) and not isinstance(hero, bool) and 1 <= hero <= len(scenes)):
        data.pop("hero_scene", None)
    hints = data.get("hero_motion_hints")
    if not (isinstance(hints, str) and hints.strip()):
        data.pop("hero_motion_hints", None)
    bible = data.get("visual_bible")
    if not (isinstance(bible, str) and bible.strip()):
        data.pop("visual_bible", None)
    poses = data.get("mascot_poses")
    if not _valid_mascot_poses(poses, len(scenes)):
        data.pop("mascot_poses", None)
    if not _valid_callouts(data.get("callouts")):
        data.pop("callouts", None)
    return data


def _valid_callouts(callouts: object) -> bool:
    """True when callouts is a non-empty list of {anchor: str, text: str,
    style: scoreboard|label|shock, occurrence?: int>=1}. Anchor-in-narration is NOT
    checked here (run.py resolves and skips misses); kept strict-but-soft so a
    malformed field is dropped, never fatal."""
    if not isinstance(callouts, list) or not callouts:
        return False
    styles = {"scoreboard", "label", "shock"}
    for item in callouts:
        if not isinstance(item, dict):
            return False
        anchor = item.get("anchor")
        text = item.get("text")
        style = item.get("style")
        if not (isinstance(anchor, str) and anchor.strip()):
            return False
        if not (isinstance(text, str) and text.strip()):
            return False
        if not (isinstance(style, str) and style.strip().lower() in styles):
            return False
        occurrence = item.get("occurrence", 1)
        if not (isinstance(occurrence, int) and not isinstance(occurrence, bool) and occurrence >= 1):
            return False
    return True


def _valid_mascot_poses(poses: object, scene_count: int) -> bool:
    """True when poses is a non-empty list of {scene: in-range int, pose: str}.
    Kept strict-but-soft: a malformed field is dropped, never fatal."""
    if not isinstance(poses, list) or not poses:
        return False
    for item in poses:
        if not isinstance(item, dict):
            return False
        scene = item.get("scene")
        pose = item.get("pose")
        if not (isinstance(scene, int) and not isinstance(scene, bool) and 1 <= scene <= scene_count):
            return False
        if not (isinstance(pose, str) and pose.strip()):
            return False
    return True


def _fallback_episode(topic: str) -> dict:
    """A visibly synthetic placeholder so the pipeline stays testable without AI."""
    narration = (
        f"This is a local placeholder for the topic: {topic}. "
        "Connect your own AI agent or replace episode dot json with a reviewed script. "
        "The production engine can validate assets, build a storyboard, require approval, "
        "and render the finished vertical video without bundling anyone else's credentials."
    )
    scenes = [
        "a clear opening image that introduces the topic",
        "a concrete visual showing the central context",
        "a close detail that explains the key mechanism",
        "a high-stakes turning point with a strong focal subject",
        "a clean final image that resolves the story",
    ]
    return {
        "title": topic[:90],
        "narration": narration,
        "scenes": scenes,
        "description": "Replace this placeholder with reviewed episode metadata.",
        "tags": ["shorts", "agent workflow"],
        "hashtags": ["#shorts"],
    }


def generate(episode_dir: Path, topic: str, config: dict, force: bool = False) -> Path:
    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()
    if paths.episode_json.exists() and not force:
        log("script", f"episode.json exists, skipping ({paths.episode_json})")
        return paths.episode_json

    data: dict
    source = "agent-command"
    try:
        raw = _call_agent(_build_prompt(topic, config))
        data = _validate_episode(extract_json_block(raw), config)
    except Exception as error:  # noqa: BLE001 - fallback is intentional
        log("script", f"agent command failed ({error}); using placeholder episode")
        source = "fallback"
        data = _fallback_episode(topic)

    scene_count = config["video"]["scene_count"]
    scenes = list(data["scenes"])[:scene_count]
    while len(scenes) < scene_count:
        scenes.append(scenes[-1] if scenes else "a pixel-art historical scene")

    episode = {
        "topic": topic,
        "generated_by": source,
        "word_count": word_count(data["narration"]),
        **data,
        "scenes": scenes,
    }
    write_json(paths.episode_json, episode)
    log("script", f"wrote {paths.episode_json} (source={source}, words={episode['word_count']})")
    return paths.episode_json


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate episode.json from a topic")
    parser.add_argument("--episode", required=True, help="episode working directory")
    parser.add_argument("--topic", required=True, help="episode topic / title idea")
    parser.add_argument("--force", action="store_true", help="regenerate even if episode.json exists")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = load_config()
    generate(Path(args.episode), args.topic, config, force=args.force)


if __name__ == "__main__":
    main()
