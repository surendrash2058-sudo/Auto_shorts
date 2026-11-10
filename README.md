# Auto Shorts - fully automatic "What if" YouTube Shorts

Every day: find trending "what if" videos -> Gemini writes an original script -> free stock video (Pexels)
-> free AI voice (edge-tts) -> word-synced captions -> upload to YouTube.

## Files
- `auto_shorts.py` - the whole program (`--list`, `--upload`, `--auto`)
- `topics.json` - queue of topics/scripts (done ones are marked)
- `.github/workflows/daily.yml` - runs it every day on GitHub (free)
- `requirements.txt`, `.gitignore`

## One-time setup
1. Google Cloud: new project, enable **YouTube Data API v3**.
2. Create an **OAuth client (Desktop app)** -> download as `client_secret.json` (never upload it to GitHub).
   Set the OAuth app to **In production** (Testing mode expires after 7 days).
3. Create an **API key** (same project) = `YOUTUBE_API_KEY`. Free Pexels key (pexels.com/api) = `PEXELS_API_KEY`.
4. On your computer: `pip install -r requirements.txt`, install ffmpeg, then run `python auto_shorts.py --upload`
   once and log in. This creates `token.json`.
5. GitHub repo > Settings > Secrets and variables > Actions, add 4 secrets:
   `YOUTUBE_TOKEN_JSON` (contents of token.json), `GEMINI_API_KEY`, `YOUTUBE_API_KEY`, `PEXELS_API_KEY`.
6. Actions tab > Daily What-If Short > Run workflow to test.

## Visuals: 3D renders made by code (default, free, no internet, original = good for monetizing)
Default `VISUALS=3d`. A small numpy 3D renderer (no GPU) draws lit, shaded spheres: a rotating Earth with
continents, clouds, atmosphere and night-side city lights; a boiling Sun with corona; a cratered Moon;
a ringed gas planet; a black hole with accretion disc and gravitational lensing. The script is split into scenes
and each scene's words pick the render and its behaviour (e.g. "vanish" fades the Sun, "stopped" freezes
Earth's spin, "freezes" turns Earth to ice over the scene, "dark/lights/power" shows the night side with city
lights that go out). Console shows `scene 1/4 -> 3d:sun`.
Needs `numpy` (in requirements.txt); without it the simple 2D cartoon animations are used.

Other modes (env VISUALS): `auto` (real photos: AI photo, Pixabay/Pexels with keys, NASA photo; 3D where none found),
`anim` (2D cartoon animations), `stock` (Pexels video), `plain` (stars).
To add a new 3D look: write draw_xxx + a branch in render3d + a rule in KIND3D / ANIM_RULES.

## Notes
- The GitHub Actions workflow sets `PRIVACY=public`, so it requests public YouTube uploads.
- Important: newly created or unaudited YouTube API projects may be restricted to private uploads by Google. If Google applies this restriction, videos may remain private until the API project passes Google's audit.
- Without GEMINI_API_KEY the system uses starter topics and cannot generate new scripts or Gemini scene plans. Add the key to enable automatic script generation.

## Automated schedule

The GitHub Actions workflow in `.github/workflows/daily.yml` runs on its configured daily schedule and uploads videos with **public** privacy. You can also run it manually from the Actions tab.

Add these GitHub Actions secrets:
- `YOUTUBE_API_KEY`
- `YOUTUBE_TOKEN_JSON`
- `GEMINI_API_KEY`
- Optional: `PEXELS_API_KEY`, `PIXABAY_API_KEY`

The workflow currently sets `PRIVACY=public`. To change it, edit the `PRIVACY` value in `.github/workflows/daily.yml`. GitHub-hosted runners are temporary: the local `topics.json` queue and generated files do not persist between runs unless saved as artifacts or committed to durable storage. A later milestone should move topic history and outputs to persistent storage.
