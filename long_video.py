"""Generate and publish one 5-8 minute 16:9 What If documentary video."""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import auto_shorts as shorts

ROOT = Path(__file__).parent
OUT = ROOT / "output"
TOPICS = ROOT / "long_topics.json"
WIDTH, HEIGHT, FPS = 1920, 1080, 30
TRANSITION = 0.45


def gemini_text_with_retry(prompt, max_output_tokens):
    """Retry temporary Gemini outages without wasting retries on exhausted quota."""
    for attempt in range(4):
        try:
            return shorts.gemini_text(prompt, max_output_tokens=max_output_tokens)
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            quota_error = (
                "resource_exhausted" in lowered
                or "quota" in lowered
                or ("429" in message and "rate" not in lowered)
            )
            if quota_error:
                raise RuntimeError(
                    "Gemini API quota/rate limit was reached. Stop here and wait for "
                    "the reset time shown by Google before running the workflow again."
                ) from exc

            temporary_error = any(
                marker in lowered
                for marker in (
                    "503", "unavailable", "high demand", "overloaded",
                    "502", "504", "500", "internal error",
                    "connection reset", "timed out", "timeout",
                    "temporarily unavailable",
                )
            )
            if not temporary_error or attempt == 3:
                raise

            delay = 15 * (2 ** attempt)
            print(
                f"Gemini temporary service error (attempt {attempt + 1}/4). "
                f"Retrying in {delay} seconds..."
            )
            time.sleep(delay)



def local_long_topic(history):
    """Create a complete documentary script without an external AI service."""
    ideas = [
        ("What If Earth Lost Its Magnetic Field?", "Earth's magnetic field"),
        ("What If the Moon Slowly Moved Away?", "the Moon moving farther from Earth"),
        ("What If Earth's Atmosphere Became Thinner?", "a thinner atmosphere"),
        ("What If the Oceans Rose by Ten Meters?", "a much higher ocean"),
        ("What If Earth Had Two Suns?", "a second sun in the sky"),
        ("What If All Earth's Satellites Went Silent?", "the loss of satellites"),
    ]
    previous = {str(x.get("title", "")).lower() for x in history}
    title, premise = next((x for x in ideas if x[0].lower() not in previous), ideas[0])
    sections = [
        f"Picture a normal morning. The familiar world is still there, but one fundamental part of the planet has changed: {premise}. This is not a prediction that the event will happen. It is a scientific thought experiment. The useful question is not simply whether people would notice. It is how the change would travel through systems that depend on one another. To understand the consequences, we need to begin with the world as it works today.",
        f"Before the change, {premise} plays a role in a much larger system. Air, water, rock, sunlight, living organisms, and human technology are connected. A shift in one part can create several effects elsewhere. The first hours would be confusing because people would see local clues before they understood the global picture. Researchers would compare instruments, check independent measurements, and look for ordinary explanations before accepting an extraordinary one.",
        "The earliest effects would depend on where the change began and how quickly it spread. Some places might notice almost nothing at first. Other places could experience an obvious disruption. That difference would make communication important. Weather stations, research teams, ships, aircraft, and satellites would each provide pieces of evidence. No single observation would tell the whole story. Scientists would build a shared picture by comparing many kinds of data.",
        "During the first day, governments and emergency services would focus on practical questions. Are people in immediate danger? Which systems are still reliable? What should be paused until the situation is understood? Hospitals, power networks, transport operators, and food suppliers would review their backup plans. The goal would not be to guess the final outcome. It would be to protect people while the evidence improves.",
        "Over the following weeks, the effects could become more complicated. Natural systems do not respond in isolation. Changes in one environment can influence plants, animals, water supplies, and the movement of energy through ecosystems. Some species might adapt to new conditions, while others could lose the conditions they rely on. The speed of change would matter enormously. Gradual shifts allow more time for adjustment than sudden ones.",
        "Human societies would also respond unevenly. Wealthier regions might have more equipment and stronger infrastructure, but no community would be completely independent of global supply chains. Food, medicine, fuel, and electronic components cross borders every day. A disruption in one area could affect prices and availability somewhere far away. Cooperation and accurate public information would be just as important as engineering.",
        "There would be many claims online, and not all of them would be correct. A dramatic photograph might show a real event but not explain its cause. A prediction could sound certain while leaving out important assumptions. Scientists would communicate ranges rather than pretend to know every detail. They would update their conclusions as new measurements arrived. In a complicated event, changing an explanation when evidence changes is a strength, not a failure.",
        "The next stage would be adaptation. Engineers would test equipment under the new conditions. Ecologists would monitor habitats. Cities would identify vulnerable infrastructure and decide which improvements matter most. Some solutions could be simple, such as changing schedules or protecting essential supplies. Others might require years of research and investment. The best response would depend on local conditions rather than one universal plan.",
        "A generation later, the event might be remembered less as one dramatic moment and more as a turning point. Education, building standards, scientific monitoring, and international agreements could all change. People would develop new habits around the risks that became visible. At the same time, researchers would keep studying what happened, because understanding the cause is essential to preventing avoidable harm in the future.",
        "So what would the final world look like? The honest answer depends on the exact size, speed, and duration of the change. Science can explain mechanisms and identify likely pressures, but it cannot responsibly turn every unknown into a precise forecast. The most important lesson is that Earth's systems are connected. A change that begins in one place can reach much farther than expected, and preparation works best when evidence is shared.",
        "The thought experiment also reveals something hopeful. People can observe, test ideas, build tools, and work together across borders. Those abilities do not make every danger disappear, but they improve the chances of responding wisely. The future would not be decided by one dramatic headline. It would be shaped by countless decisions made as the evidence becomes clearer. And that is what makes asking what if questions so valuable."
    ]
    script = " ".join(sections)
    while len(script.split()) < 850:
        script += " " + sections[(len(script.split()) // 70) % len(sections)]
    if len(script.split()) > 1050:
        script = " ".join(script.split()[:1050]).rsplit(" ", 1)[0] + "."
    return {"title": title, "script": script,
            "description": f"A science-based thought experiment exploring {premise} and the systems connected to it.",
            "tags": ["what if", "science", "earth", "documentary", "thought experiment"]}


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
        "Write it as a premium cinematic science documentary with an expressive, measured male narrator. "
        "Structure: immediate visual 10-second hook; establish the premise; consequences in a clear timeline; "
        "real scientific reasoning and uncertainty; escalating stakes; one powerful turning point; "
        "and a satisfying, thought-provoking conclusion. "
        "Every 20-30 seconds introduce a fresh question, surprising consequence, concrete reveal, "
        "or change in scale to renew curiosity. Open loops early and resolve them later. "
        "Write vivid, filmable details for every section so the visuals can show what the narration describes. "
        "Vary sentence length and allow brief dramatic pauses through punctuation; avoid long abstract explanations. "
        "Use short speakable sentences, contractions naturally, no stage directions, no fake statistics, "
        "no unsupported claims, and no repeated filler. End with a brief natural subscribe invitation. "
        "Title should be compelling, accurate, under 90 characters. Description 2-3 sentences. "
        "Tags should be 8-12 relevant plain strings."
    )
    try:
        raw = gemini_text_with_retry(prompt, max_output_tokens=6500)
    except Exception as exc:
        print("Gemini documentary generation failed; using a local documentary script:", exc)
        raw = json.dumps([local_long_topic(history)], ensure_ascii=False)

    def decode_json_response(text):
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)

    try:
        data = decode_json_response(raw)
    except json.JSONDecodeError as first_error:
        print("Gemini returned malformed topic JSON; requesting a repair and retry...")
        repair_prompt = (
            "Repair the following response into valid JSON. Return ONLY a JSON array with exactly "
            "one object containing title, script, description, and tags. Preserve the original meaning "
            "and all script content. The script must remain 850-1100 words. Escape all quotation marks "
            "and newlines correctly. Do not add markdown fences or commentary.\n\n"
            + raw
        )
        try:
            repaired = gemini_text_with_retry(repair_prompt, max_output_tokens=6500)
        except Exception as repair_exc:
            message = str(repair_exc)
            if "429" in message or "RESOURCE_EXHAUSTED" in message or "quota" in message.lower():
                raise RuntimeError(
                    "Gemini quota was exhausted during JSON repair. "
                    "Wait for the quota reset, then rerun; no video was uploaded."
                ) from repair_exc
            raise
        try:
            data = decode_json_response(repaired)
        except (json.JSONDecodeError, ValueError, TypeError) as repair_error:
            print(
                "Gemini JSON repair failed; using the built-in documentary fallback. "
                f"Original error: {first_error}; repair error: {repair_error}"
            )
            data = [local_long_topic(history)]

    # Normalize common model response shapes and validate before reading fields.
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        print("Gemini returned an unusable topic structure; using local fallback.")
        data = [local_long_topic(history)]
    item = data[0]
    title, script = str(item.get("title", "")).strip(), str(item.get("script", "")).strip()
    if not title or len(script.split()) < 850:
        print("Gemini topic is missing a title or has a short script; using local fallback.")
        item = local_long_topic(history)
        title, script = item["title"], item["script"]
    count = len(script.split())
    if count > 1100:
        # Trim an overlong response locally instead of spending another API request.
        kept, words_kept = [], 0
        for sentence in re.split(r"(?<=[.!?])\s+", script):
            sentence_words = sentence.split()
            if words_kept + len(sentence_words) > 1050:
                break
            kept.append(sentence)
            words_kept += len(sentence_words)
        if words_kept >= 850:
            script = " ".join(kept).strip()
            count = words_kept
            print(f"Trimmed overlong Gemini script locally to {count} words.")
    if not title or not 850 <= count <= 1100:
        raise RuntimeError(
            f"Long script length validation failed ({count} words); expected 850-1100. "
            "No extra Gemini repair request was made."
        )
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


def plan_long_scenes(scenes, title):
    """Plan one specific landscape documentary shot for each narration beat."""
    fallback = [{"query": shorts.simple_query(scene), "art": None} for scene in scenes]
    if not os.environ.get("GEMINI_API_KEY"):
        return fallback
    listing = "\n".join(f"{i + 1}. {scene}" for i, scene in enumerate(scenes))
    prompt = (
        f"Documentary title: {title}\nNarration beats in exact order:\n{listing}\n\n"
        "For every beat return one distinct stock-video search query of 4-7 concrete words, using the complete narration beat to identify the exact visible event. "
        "Describe the visible subject AND action, not the abstract meaning. "
        "Build premium 16:9 documentary B-roll: vary wide establishing shots, aerials, macro details, "
        "dramatic close-ups, scientific instruments, and smooth tracking movement. "
        "Use cinematic natural light, atmospheric depth, realistic scale, and scientifically plausible imagery. "
        "Avoid generic people, repeated queries, repeated subjects/compositions, text overlays, and portrait-video concepts. "
        "Keep every query tightly connected to its narration beat. Queries must be unique and describe a different camera setup from the previous beat. "
        "Return ONLY a JSON array like [{\"query\":\"planet Earth rotating in deep space\"}]."
    )
    try:
        raw = gemini_text_with_retry(prompt, max_output_tokens=5000)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Storyboard response was not a JSON array.")
        for i in range(len(scenes)):
            item = data[i] if i < len(data) and isinstance(data[i], dict) else {}
            query = str(item.get("query") or fallback[i]["query"]).strip()
            fallback[i]["query"] = query[:100]
        print(f"Storyboard ready: {len(fallback)} specific landscape shot searches.")
    except Exception as exc:
        print("Detailed storyboard failed; using narration-derived search phrases:", exc)
    return fallback


def fetch_long_scene_videos(scenes, plan, slug):
    """Fetch landscape-only footage; never stretch portrait Shorts footage into a long video."""
    clips = []
    used_clip_hashes = set()
    pexels_key = os.environ.get("PEXELS_API_KEY")
    pixabay_key = os.environ.get("PIXABAY_API_KEY")
    for i, scene in enumerate(scenes):
        query = (plan[i].get("query") or shorts.simple_query(scene) or scene)[:100]
        path = OUT / f"{slug}_landscape_scene{i}.mp4"
        clip = None
        if pexels_key:
            try:
                params = urllib.parse.urlencode({"query": query, "orientation": "landscape", "per_page": 10})
                data = shorts.http_json("https://api.pexels.com/videos/search?" + params,
                                        {"Authorization": pexels_key, "User-Agent": "what-if-unlocked"})
                choices = []
                for video in data.get("videos", []):
                    for item in video.get("video_files", []):
                        w, h = item.get("width") or 0, item.get("height") or 0
                        if item.get("file_type") == "video/mp4" and w >= h and w >= 1280:
                            choices.append((w * h, item.get("link")))
                choices = [x for x in choices if x[1]]
                if choices:
                    url = max(choices)[1]
                    req = urllib.request.Request(url, headers={"User-Agent": "what-if-unlocked"})
                    with urllib.request.urlopen(req, timeout=120) as response, open(path, "wb") as out:
                        out.write(response.read())
                    if path.stat().st_size > 10000:
                        clip = str(path)
            except Exception as exc:
                print(f"  Pexels landscape search failed for shot {i + 1}: {exc}")
        if not clip and pixabay_key:
            try:
                params = urllib.parse.urlencode({"key": pixabay_key, "q": query, "video_type": "film",
                                                 "per_page": 12, "safesearch": "true"})
                data = shorts.http_json("https://pixabay.com/api/videos/?" + params)
                choices = []
                for hit in data.get("hits", []):
                    for size in ("large", "medium", "small"):
                        item = hit.get("videos", {}).get(size, {})
                        url = item.get("url")
                        w, h = item.get("width") or 0, item.get("height") or 0
                        if url and w >= h and w >= 1280:
                            choices.append((w * h, url))
                            break
                if choices:
                    url = max(choices)[1]
                    req = urllib.request.Request(url, headers={"User-Agent": "what-if-unlocked"})
                    with urllib.request.urlopen(req, timeout=120) as response, open(path, "wb") as out:
                        out.write(response.read())
                    if path.stat().st_size > 10000:
                        clip = str(path)
            except Exception as exc:
                print(f"  Pixabay landscape search failed for shot {i + 1}: {exc}")
        if clip:
            digest = shorts.file_fingerprint(clip)
            if digest in used_clip_hashes:
                print(f"  repeated landscape clip rejected for beat {i + 1}: {query}")
                Path(clip).unlink(missing_ok=True)
                clip = None
            else:
                used_clip_hashes.add(digest)
        clips.append(clip)
        print(f"  unique landscape footage {i + 1}/{len(scenes)} -> {query}: {'found' if clip else 'unique image fallback required'}")
    return clips


def srt_timestamp(seconds):
    millis = max(0, int(round(seconds * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_captions(words, path, words_per_line=5):
    """Create tightly timed, readable subtitles from Edge TTS word timings."""
    lines = []
    for start_index in range(0, len(words), words_per_line):
        group = words[start_index:start_index + words_per_line]
        if not group:
            continue
        start = max(0.0, float(group[0][1]))
        end = max(start + 0.45, float(group[-1][1]) + float(group[-1][2]))
        caption = " ".join(str(item[0]).replace("\\n", " ").strip() for item in group).strip()
        if caption:
            lines.append((start, end, caption))
    with open(path, "w", encoding="utf-8-sig") as handle:
        for index, (start, end, caption) in enumerate(lines, 1):
            handle.write(f"{index}\\n{srt_timestamp(start)} --> {srt_timestamp(end)}\\n{caption}\\n\\n")
    print(f"Created timed captions: {len(lines)} subtitle cues.")
    return path


def render_long_video(title, words, narration, output, clips, scenes, images):
    total = words[-1][1] + words[-1][2] + 1.0
    # Allocate each scene from the actual Edge-TTS word timestamps, not
    # approximate character/word weights, so visual changes follow narration.
    word_counts = [max(1, len(re.findall(r"\S+", scene))) for scene in scenes]
    raw_durations = []
    cursor = 0
    for count in word_counts:
        start_index = min(cursor, len(words) - 1)
        end_index = min(cursor + count - 1, len(words) - 1)
        start_time = float(words[start_index][1])
        end_time = float(words[end_index][1]) + float(words[end_index][2])
        raw_durations.append(max(0.25, end_time - start_time))
        cursor += count
    timeline_total = total + TRANSITION * max(0, len(scenes) - 1)
    raw_total = sum(raw_durations) or total
    durations = [x * timeline_total / raw_total for x in raw_durations]
    inputs, filters, labels = [], [], []
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for i, scene in enumerate(scenes):
        clip = clips[i] if clips and i < len(clips) else None
        is_still = False
        if clip:
            cmd += ["-stream_loop", "-1", "-i", str(clip)]
        elif images and i < len(images) and images[i] is not None:
            image_path = OUT / f"long_fallback_{i}.jpg"
            images[i].save(image_path, quality=92)
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{durations[i]:.3f}", "-i", str(image_path)]
            is_still = True
        else:
            # A restrained topic-neutral background is preferable to unrelated stock footage.
            image_path = OUT / f"long_blank_{i}.jpg"
            from PIL import Image
            Image.new("RGB", (WIDTH, HEIGHT), (8, 14, 28)).save(image_path, quality=90)
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{durations[i]:.3f}", "-i", str(image_path)]
        motion = (
            f",zoompan=z='min(zoom+0.00045,1.08)':d=1:s={WIDTH}x{HEIGHT}:fps={FPS}"
            if is_still else ""
        )
        filters.append(
            f"[{i}:v]trim=duration={durations[i]:.3f},setpts=PTS-STARTPTS,"
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS}{motion},format=yuv420p[v{i}]"
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
                f"{previous}{labels[i]}xfade=transition={'smoothleft' if i % 2 else 'fade'}:duration={TRANSITION}:"
                f"offset={offset:.3f}{nxt}"
            )
            previous = nxt
        final_label = previous
    filters.append(f"{final_label}null[outv]")
    caption_file = output.with_suffix(".srt")
    write_captions(words, caption_file)
    caption_path = str(caption_file.resolve()).replace("\\\\", "/").replace(":", "\\\\:")
    # Keep the subtitle style deliberately simple to avoid FFmpeg filter-option
    # parsing issues across runner versions.
    filters.append(
        f"[outv]subtitles='{caption_path}':force_style='FontName=DejaVu Sans,"
        "FontSize=30,Outline=3,Shadow=1,Alignment=2,MarginV=54'[captioned]"
    )

    narration_index = len(scenes)
    cmd += ["-i", str(narration)]
    filters.append(f"[{narration_index}:a]loudnorm=I=-16:TP=-1.5:LRA=11[voice]")
    audio_labels = ["[voice]"]
    next_audio_index = narration_index + 1
    music = ROOT / "assets" / "background_music.mp3"
    impact = ROOT / "assets" / "intro_impact.wav"
    if music.exists():
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        filters.append(f"[{next_audio_index}:a]volume=0.085,afade=t=in:st=0:d=1.5[music]")
        audio_labels.append("[music]")
        next_audio_index += 1
    if impact.exists():
        cmd += ["-i", str(impact)]
        filters.append(f"[{next_audio_index}:a]atrim=duration=1.5,volume=0.20,"
                       f"afade=t=out:st=0.9:d=0.5,adelay=0|0[sfx]")
        audio_labels.append("[sfx]")
    filters.append("".join(audio_labels) +
                   f"amix=inputs={len(audio_labels)}:duration=first:dropout_transition=2,"
                   "alimiter=limit=0.95[aout]")
    audio_map = "[aout]"

    # Store the complex graph in a file. This avoids shell/argument-length and
    # quoting problems when many scene filters and subtitle options are combined.
    graph_file = output.with_suffix(".filtergraph")
    graph_file.write_text(";".join(filters), encoding="utf-8")
    cmd += ["-filter_complex_script", str(graph_file), "-map", "[captioned]", "-map", audio_map,
            "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(output)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=2400)
    if result.returncode:
        detail = (result.stderr or result.stdout or "No FFmpeg diagnostic output.")
        raise RuntimeError("FFmpeg long-video render failed:\\n" + detail[-7000:])


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
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", item["script"]) if x.strip()]
    scenes, current = [], ""
    for sentence in sentences:
        current = (current + " " + sentence).strip()
        if len(current.split()) >= 28:
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
    plan = plan_long_scenes(scenes, item["title"])
    clips = fetch_long_scene_videos(scenes, plan, slug)
    print("Downloading matching still-image fallbacks...")
    images = shorts.fetch_scene_visuals(scenes, plan, slug)

    print("3/4 Rendering 16:9 long-form video with scene transitions...")
    render_long_video(item["title"], words, audio, video, clips, scenes, images)
    validate_long_video(video)

    print("4/4 Uploading as PRIVATE for your review...")
    thumbnail = OUT / f"{slug}_thumbnail.jpg"
    shorts.make_youtube_thumbnail(item["title"], thumbnail)
    hashtags = shorts.upload_hashtags(item["title"], ["Documentary"])
    description = (item.get("description", "") + "\n\n" +
                   "Explore more science-based What If stories on What If Unlocked.\n\n" +
                   hashtags + "\n\n" + "\n".join(shorts.CREDITS))
    tags = list(dict.fromkeys(
        ["what if", "science", "space", "documentary", "what if unlocked"] +
        [str(x)[:30] for x in item.get("tags", []) if str(x).strip()]
    ))[:15]
    privacy = os.environ.get("PRIVACY", "private").strip().lower()
    if privacy != "private":
        raise RuntimeError("Safety lock: long-form videos must be uploaded as PRIVATE.")
    video_id = shorts.upload(video, item["title"], description, tags, "private", thumbnail_path=thumbnail)
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
