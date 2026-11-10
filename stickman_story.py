#!/usr/bin/env python3
"""
stickman_story.py
Create an original 40–60 second colorful-cartoon stickman Short script with
Gemini. This is the first stage of the stickman video pipeline.

Usage:
  python stickman_story.py
  python stickman_story.py --topic "What if the Moon disappeared?"
  python stickman_story.py --output output/story.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

DEFAULT_OUTPUT = Path("output/stickman_story.json")
MIN_WORDS = 85
MAX_WORDS = 135
MIN_SCENES = 6
MAX_SCENES = 10


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text, flags=re.I)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Gemini response did not contain a JSON object.")
    return json.loads(text[start:end + 1])


def fallback_story(topic: str | None = None) -> dict:
    title = topic or "What If Earth Suddenly Lost Gravity?"
    narration = (
        "Imagine letting go of your phone… and watching it float away. "
        "If Earth suddenly lost gravity, people, cars, and oceans would start drifting upward. "
        "Our colorful stickman, Pip, grabs a streetlamp as everything around him lifts off. "
        "But the danger gets worse. Earth's atmosphere would no longer stay in place, "
        "and breathing could become impossible. The planet would not feel like a giant playground for long. "
        "Without gravity holding things together, life as we know it would collapse. "
        "So would floating away be fun? Only for a moment."
    )
    parts = [
        ("Pip drops a phone and it floats upward", "surprised"),
        ("Pip jumps and keeps rising above the street", "funny"),
        ("Cars and objects drift into the sky", "shocked"),
        ("The ocean lifts into enormous floating blobs", "amazed"),
        ("Pip clings to a streetlamp while the air thins", "scared"),
        ("A simple Earth diagram shows gravity disappearing", "serious"),
        ("Pip looks at the viewer as the scene fades", "curious"),
    ]
    scenes = []
    for i, (visual, emotion) in enumerate(parts, 1):
        scenes.append({
            "scene": i,
            "narration": visual + ".",
            "visual": visual,
            "action": "clear readable full-body stickman movement",
            "emotion": emotion,
            "camera": "medium shot",
        })
    return {
        "title": title[:85],
        "hook": "Imagine letting go of your phone… and watching it float away.",
        "narration": narration,
        "characters": [
            {"id": "pip", "name": "Pip", "description": "small friendly white stickman, round white head, simple black outline, bright teal scarf, expressive black eyes; keep this design identical in every scene"},
        ],
        "scenes": scenes,
        "visual_style": "colorful 2D cartoon stickman animation, bold clean outlines, bright simple backgrounds, expressive poses, playful but cinematic lighting",
        "music_mood": "playful curiosity that builds into suspense",
        "sound_effects": ["soft pop", "cartoon whoosh", "rising wind", "dramatic impact"],
        "ending_question": "Would you enjoy floating for one minute?",
    }


def build_prompt(topic: str | None) -> str:
    topic_instruction = f'Use this topic: "{topic}".' if topic else (
        "Invent a fresh, surprising science-based What If topic that is easy to visualize."
    )
    return f"""
You are the head writer for an original YouTube Shorts channel about surprising
science-based What If scenarios, told with colorful cartoon stickman animation.

{topic_instruction}

Create ONE original short, designed for a 40–60 second video.
Narration must be 85–135 words, natural spoken English, energetic and easy to understand.
Start with a powerful curiosity gap in the first 1–2 seconds: show an impossible,
dangerous, or surprising result before explaining why it happens. Build escalating
consequences, include one memorable reveal, and finish with a thought-provoking question.
EMOTION + CURIOSITY RETENTION RULES:
- Give the viewer a reason to care: Pip must want, fear, lose, discover, or try something.
- Create a clear emotional arc across the story (for example curiosity -> surprise -> fear
  -> determination -> relief/shock). Do not keep Pip emotionally neutral.
- Every scene must change something: reveal a new clue, raise the stakes, cause a reaction,
  or show a consequence. No repeated filler shots.
- Every 5–8 seconds introduce a new visual discovery, unanswered question, escalation,
  or emotional turn. Keep each beat easy to understand at a glance.
- Delay the biggest explanation until after the viewer has seen a compelling consequence.
  Use a setup -> escalation -> twist/payoff structure, not a list of facts.
- Pip's emotion must be visible in face AND body language: widened eyes/open mouth for
  surprise, leaning back/raised arms for fear, forward-leaning pose for curiosity,
  energetic raised arms for excitement, relaxed smile for relief.
- Make the ending payoff answer the opening hook, then leave one natural question.
Keep science plausible; clearly qualify uncertain outcomes. No copied scripts, no fake facts,
no long intro, no subscribe request, and no "follow for more" filler.

VISUAL RULES:
- Use one recurring original character named Pip in every scene.
- Pip's fixed design: friendly white stickman, round white head, black outline,
  expressive black eyes, bright teal scarf. Never change body proportions or outfit.
- Supporting stickmen may appear, but give each a consistent simple color accessory.
- Colorful cartoon 2D style, clean thick outlines, readable silhouettes, vivid backgrounds.
- Every scene must communicate its meaning to a viewer who CANNOT hear the audio.
- Silent-viewing rule: a deaf viewer must understand the main event by watching alone.
  Never rely on narration, sound effects, music, or spoken explanation to explain the plot.
- Show a clear visual cause -> action -> result. Use large recognizable objects, unmistakable
  gestures, expressive reactions, and visible consequences. Show the important object moving,
  changing, breaking, rising, falling, disappearing, or affecting Pip.
- One main action per scene. Avoid abstract symbols unless paired with a literal physical example.
  Avoid tiny details, clutter, vague standing poses, and unrelated decorative shots.
- Keep Pip visible in every scene when practical; preserve his exact white body and teal scarf.
  Supporting characters must visibly react to the same event.
- Make 7–9 scenes. Scene narration chunks must appear in order and together match
  the full narration closely. Each scene should be about 4–8 seconds, with enough time
  to see the action and its consequence.
- Use visual continuity: the result of one scene should lead naturally into the next.
- Retention structure: scene 1 is the hook; scenes 2–3 raise a question; middle scenes
  escalate danger or wonder; second-last scene delivers the biggest reveal; final scene
  gives the payoff and a clear reaction from Pip.
- Each scene's emotion must match its actual event and visibly differ when the story turns.
- Vertical 9:16 composition; keep faces and important action near the center safe area.

Return ONLY valid JSON in this exact structure:
{{
  "title": "short accurate title",
  "hook": "opening hook",
  "narration": "complete voiceover, 85-135 words",
  "characters": [
    {{"id":"pip","name":"Pip","description":"exact recurring visual design"}}
  ],
  "scenes": [
    {{
      "scene": 1,
      "narration": "the exact voiceover lines for this scene",
      "visual": "what the viewer sees, including setting and props",
      "action": "specific movement/gesture of Pip or other characters",
      "emotion": "one word",
      "camera": "wide shot, medium shot, close-up, or tracking shot"
    }}
  ],
  "visual_style": "consistent visual style description",
  "music_mood": "music direction",
  "sound_effects": ["short effect cue", "short effect cue"],
  "ending_question": "final engaging question"
}}
"""


def validate(data: dict) -> dict:
    required = ("title", "hook", "narration", "characters", "scenes", "visual_style")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(missing))
    count = word_count(data["narration"])
    if not MIN_WORDS <= count <= MAX_WORDS:
        raise ValueError(f"Narration has {count} words; expected {MIN_WORDS}–{MAX_WORDS}.")
    if not MIN_SCENES <= len(data["scenes"]) <= MAX_SCENES:
        raise ValueError(f"Expected {MIN_SCENES}–{MAX_SCENES} scenes; got {len(data['scenes'])}.")
    for i, scene in enumerate(data["scenes"], 1):
        for key in ("narration", "visual", "action", "emotion", "camera"):
            if not scene.get(key):
                raise ValueError(f"Scene {i} is missing '{key}'.")
        scene["scene"] = i
    return data


def is_retryable_error(exc: Exception) -> bool:
    """Return True for temporary Gemini capacity, rate-limit, or server errors."""
    message = str(exc).upper()
    retry_markers = (
        "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
        "500", "INTERNAL", "502", "BAD GATEWAY", "504", "DEADLINE_EXCEEDED",
        "TIMEOUT", "TIMED OUT", "SERVICE UNAVAILABLE",
    )
    return any(marker in message for marker in retry_markers)


def is_fatal_auth_error(exc: Exception) -> bool:
    message = str(exc).upper()
    return any(marker in message for marker in (
        "API_KEY_INVALID", "INVALID API KEY", "PERMISSION_DENIED",
        "UNAUTHENTICATED", "401", "403",
    ))


def generate(topic: str | None) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set; using built-in sample story.", file=sys.stderr)
        return validate(fallback_story(topic))

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
    except Exception as exc:
        print(f"Could not initialize Gemini client: {exc}", file=sys.stderr)
        print("Using built-in sample story.", file=sys.stderr)
        return validate(fallback_story(topic))

    primary = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    configured_fallbacks = os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.7-flash,gemini-3.5-flash-lite"
    )
    models = list(dict.fromkeys(
        [m.strip() for m in [primary, *configured_fallbacks.split(",")] if m.strip()]
    ))
    prompt = build_prompt(topic)
    last_error = None

    for model_index, model in enumerate(models):
        # Retry temporary service/capacity errors with exponential backoff.
        max_attempts = 3 if model_index == 0 else 2
        for attempt in range(1, max_attempts + 1):
            try:
                print(
                    f"Gemini story request: model {model} "
                    f"(model {model_index + 1}/{len(models)}, attempt {attempt}/{max_attempts})",
                    file=sys.stderr,
                )
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "temperature": 0.85,
                        "max_output_tokens": 5000,
                    },
                )
                if not response.text:
                    raise RuntimeError(f"{model} returned an empty response.")
                story = validate(extract_json(response.text))
                print(f"Story generated successfully with {model}.", file=sys.stderr)
                return story
            except Exception as exc:
                last_error = exc
                print(f"Gemini {model} attempt {attempt} failed: {exc}", file=sys.stderr)

                if is_fatal_auth_error(exc):
                    print("Gemini authentication/permission error; stopping model retries.", file=sys.stderr)
                    break

                if is_retryable_error(exc) and attempt < max_attempts:
                    delay = 2 ** attempt + (attempt - 1) * 2
                    print(f"Temporary Gemini error; retrying in {delay}s.", file=sys.stderr)
                    time.sleep(delay)
                    continue

                # For overload, quota, unavailable models, or malformed output,
                # move to the next configured model rather than immediately using a sample.
                break

        if last_error is not None and is_fatal_auth_error(last_error):
            break
        if model_index < len(models) - 1:
            print(f"Switching to backup Gemini model after {model} failed.", file=sys.stderr)

    print(f"All Gemini models failed. Last error: {last_error}", file=sys.stderr)
    print("Using built-in sample story as final fallback.", file=sys.stderr)
    return validate(fallback_story(topic))

def main():
    parser = argparse.ArgumentParser(description="Generate a colorful stickman Shorts script.")
    parser.add_argument("--topic", help="Optional What If topic. Gemini invents one if omitted.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON output path.")
    args = parser.parse_args()

    story = generate(args.topic)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Story created: {output}")
    print(f"Title: {story['title']}")
    print(f"Narration words: {word_count(story['narration'])}")
    print(f"Scenes: {len(story['scenes'])}")
    print("Characters: " + ", ".join(c["name"] for c in story["characters"]))


if __name__ == "__main__":
    main()
