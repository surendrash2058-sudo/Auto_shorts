# Auto Shorts - fully automatic "What if" YouTube Shorts

Every day: find trending "what if" videos -> Claude writes an original script -> free stock video (Pexels)
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
   `YOUTUBE_TOKEN_JSON` (contents of token.json), `ANTHROPIC_API_KEY`, `YOUTUBE_API_KEY`, `PEXELS_API_KEY`.
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
- New API projects can only upload as **private** until Google audits the project.
- Without ANTHROPIC_API_KEY the system uses the 20 starter topics in topics.json (about 20 days) and cannot write new ones or use trends. Add the key later to unlock trending-topic scripts.
- Not tested with real internet: trend search, Pexels download, voice, upload, GitHub Action.
