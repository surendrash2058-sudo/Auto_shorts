# What If Unlocked — automated video pipeline

Cinematic, science-based What-If videos for the What If Unlocked YouTube channel.

## Video style
- Realistic, environment-led visuals matched to the narration.
- No recurring character, mascot, stick figure, or cartoon-human layer.
- Natural male English narration, captions, background music, and sound effects.
- Gemini writes the story and scene plan. A built-in fallback prevents temporary Gemini outages from crashing story generation.
- Scene images use the configured Cloudflare image endpoint when credentials are available, with existing visual fallbacks.

## Workflows
- `.github/workflows/daily.yml`: scheduled Short generation.
- `.github/workflows/long-form.yml`: scheduled long-form documentary generation.

Both workflows request YouTube visibility **public** for future uploads. This does not change visibility of videos already uploaded.

## Required GitHub Actions secrets
- `YOUTUBE_API_KEY`
- `YOUTUBE_TOKEN_JSON`
- `GEMINI_API_KEY`

Optional visual-provider secrets:
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `PIXABAY_API_KEY`

No OpenAI or Pexels API key is required.

## Local setup
1. Install Python 3.11+, FFmpeg, and dependencies: `pip install -r requirements.txt`.
2. Configure environment variables (see `.env.example`).
3. Authenticate YouTube locally using `youtube_auth.py`; keep OAuth files private.
4. Run `python auto_shorts.py --auto` for a Short or `python long_video.py` for a long video.

Direct local runs default to private unless an explicit visibility setting is supplied; GitHub Actions workflows request public for future uploads.
