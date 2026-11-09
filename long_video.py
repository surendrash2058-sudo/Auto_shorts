"""Generate and publish one 5-8 minute 16:9 What If documentary video."""
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import auto_shorts as shorts

ROOT = Path(__file__).parent
OUT = ROOT / "output"
TOPICS = ROOT / "long_topics.json"
WIDTH, HEIGHT, FPS = 1920, 1080, 30
TRANSITION = 0.35


def make_topic():
    history = json.loads(TOPICS.read_text(encoding="utf-8")) if TOPICS.exists() else []
    previous = "; ".join(x.get("title", "") for x in history[-35:])
    prompt = (
        "Create ONE original 5-8 minute YouTube science documentary for the channel What If Unlocked. "
        "Target US viewers, but keep the science globally understandable. Choose a fascinating, visual, "
        "science-grounded hypothetical scenario with a strong curiosity gap. Do not copy any existing video. "
        "Avoid topics in this recent history: " + previous + ". "
        "Return ONLY a JSON array containing one object with title, script, description, tags. "
        "The script must be 900-1000 spoken words, natural American English for a warm, expressive male narrator. "
        "Structure: immediate 10-second hook; explain the premise; consequences in a clear timeline; "
        "real scientific reasoning and uncertainty; escalating stakes; satisfying conclusion. "
        "Every 20-30 seconds introduce a fresh question, surprising consequence, concrete reveal, "
        "or change in scale to renew curiosity. Use open loops and resolve them later. "
        "Write vivid visual details that can be shown on screen. Avoid long abstract explanations. "
        "Use short speakable sentences, contractions naturally, no stage directions, no fake statistics, "
        "no unsupported claims, and no repeated filler. End with a brief natural subscribe invitation. "
        "Title should be compelling, accurate, under 90 characters. Description 2-3 sentences. "
        "Tags should be 8-12 relevant plain strings."
    )
    raw = shorts.gemini_text(prompt, max_output_tokens=5000)
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise RuntimeError("Gemini did not return a long-video topic.")
    item = data[0]
    title, script = str(item.get("title", "")).strip(), str(item.get("script", "")).strip()
    count = len(script.split())
    if not title or not 850 <= count <= 1100:
        raise RuntimeError(f"Long script length validation failed ({count} words); expected 850-1100.")
    item["title"] = title[:95]
    item["script"] = script
    item["description"] = str(item.get("description", "")).strip()
    item["tags"] = [str(x)[:30] for x in item.get("tags", []) if str(x).strip()][:15]
    item["done"] = False
    history.append(item)
    TOPICS.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    return item, history


def validate_long_video(path):
    if not path.exists() or path.stat().st_size < 500_000:
        raise RuntimeError("Rendered long video is missing or unexpectedly small.")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=45
    )
    if result.returncode:
        raise RuntimeError("ffprobe could not read long video: " + (result.stderr or "")[-1000:])
    info = json.loads(result.stdout or "{}")
    video = next((x for x in info.get("streams", []) if x.get("codec_type") == "video"), None)
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    if not video or video.get("width") != WIDTH or video.get("height") != HEIGHT:
        raise RuntimeError("Long video must be 1920x1080 landscape.")
    if not 270 <= duration <= 510:
        raise RuntimeError(f"Long video duration {duration:.1f}s is outside the 4.5-8.5 minute safety range.")
    print(f"Long video validation passed: 1920x1080, {duration/60:.1f} minutes, {path.stat().st_size:,} bytes.")


def render_long_video(title, words, narration, output, clips, scenes, images):
    total = words[-1][1] + words[-1][2] + 1.0
    weights = [max(1, len(x.split())) for x in scenes]
    timeline_total = total + TRANSITION * max(0, len(scenes) - 1)
    durations = [timeline_total * x / sum(weights) for x in weights]
    inputs, filters, labels = [], [], []
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for i, scene in enumerate(scenes):
        clip = clips[i] if clips and i < len(clips) else None
        if clip:
            cmd += ["-stream_loop", "-1", "-i", str(clip)]
        elif images and i < len(images) and images[i] is not None:
            image_path = OUT / f"long_fallback_{i}.jpg"
            images[i].save(image_path, quality=92)
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{durations[i]:.3f}", "-i", str(image_path)]
        else:
            # A restrained topic-neutral background is preferable to unrelated stock footage.
            image_path = OUT / f"long_blank_{i}.jpg"
            from PIL import Image
            Image.new("RGB", (WIDTH, HEIGHT), (8, 14, 28)).save(image_path, quality=90)
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{durations[i]:.3f}", "-i", str(image_path)]
        filters.append(
            f"[{i}:v]trim=duration={durations[i]:.3f},setpts=PTS-STARTPTS,"
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS},format=yuv420p[v{i}]"
        )
        labels.append(f"[v{i}]")

    if len(labels) == 1:
        final_label = labels[0]
    else:
        previous = labels[0]
        for i in range(1, len(labels)):
            nxt = f"[xf{i}]"
            offset = sum(durations[:i]) - TRANSITION * i
            filters.append(
                f"{previous}{labels[i]}xfade=transition=fade:duration={TRANSITION}:"
                f"offset={offset:.3f}{nxt}"
            )
            previous = nxt
        final_label = previous
    filters.append(f"{final_label}null[outv]")

    narration_index = len(scenes)
    cmd += ["-i", str(narration)]
    music = ROOT / "assets" / "background_music.mp3"
    if music.exists():
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        music_index = narration_index + 1
        filters.append(f"[{narration_index}:a]loudnorm=I=-16:TP=-1.5:LRA=11[voice];"
                       f"[{music_index}:a]volume=0.10[music];"
                       f"[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]")
        audio_map = "[aout]"
    else:
        filters.append(f"[{narration_index}:a]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
        audio_map = "[aout]"

    cmd += ["-filter_complex", ";".join(filters), "-map", "[outv]", "-map", audio_map,
            "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(output)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=2400)
    if result.returncode:
        raise RuntimeError("FFmpeg long-video render failed: " + (result.stderr or result.stdout or "")[-3000:])


def main():
    OUT.mkdir(exist_ok=True)
    item, history = make_topic()
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", item["title"]).strip("_")[:55]
    audio = OUT / f"{slug}_narration.mp3"
    video = OUT / f"{slug}_long.mp4"

    print("1/4 Generating natural male narration...")
    words = asyncio.run(shorts.make_voice(item["script"], audio))
    # Short visual beats prevent one stock clip from sitting on screen for 20-30 seconds.
    # Each beat stays in narration order and is roughly 20-30 spoken words.
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\\s+", item["script"]) if x.strip()]
    scenes, current = [], ""
    for sentence in sentences:
        current = (current + " " + sentence).strip()
        if len(current.split()) >= 22:
            scenes.append(current)
            current = ""
    if current:
        if scenes and len(current.split()) < 12:
            scenes[-1] += " " + current
        else:
            scenes.append(current)
    if len(scenes) < 24:
        scenes = shorts.split_scenes(item["script"], min_words=18, max_scenes=36)
    scenes = scenes[:42]
    print(f"2/4 Building a detailed storyboard with {len(scenes)} visual beats...")
    plan = shorts.plan_scenes(scenes, item["title"])
    clips = shorts.fetch_scene_videos(scenes, plan, slug)
    print("Downloading matching still-image fallbacks...")
    images = shorts.fetch_scene_visuals(scenes, plan, slug)

    print("3/4 Rendering 16:9 long-form video with scene transitions...")
    render_long_video(item["title"], words, audio, video, clips, scenes, images)
    validate_long_video(video)

    print("4/4 Uploading as PRIVATE for your review...")
    description = (item.get("description", "") + "\n\n" +
                   "Explore more science-based What If stories on What If Unlocked.\n" +
                   "\n".join(shorts.CREDITS) + "\n#WhatIf #Science #WhatIfUnlocked")
    tags = item.get("tags") or ["what if", "science", "space", "documentary", "what if unlocked"]
    privacy = os.environ.get("PRIVACY", "private").strip().lower()
    if privacy != "private":
        raise RuntimeError("Safety lock: long-form videos must be uploaded as PRIVATE.")
    video_id = shorts.upload(video, item["title"], description, tags, "private")
    item["done"] = True
    item["video_id"] = video_id
    item["published_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    TOPICS.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Uploaded long video: https://youtube.com/watch?v=" + video_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nLONG VIDEO ERROR:", exc)
        sys.exit(1)
