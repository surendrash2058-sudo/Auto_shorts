# Start your own automatic "What if" YouTube Shorts channel

This project makes one "What if" science Short every day (voice, 3D visuals, captions) and uploads it to YouTube
using free GitHub servers. Follow the steps one by one.

## IMPORTANT
- Make your OWN accounts and keys. NEVER send or upload `client_secret.json`, `token.json`, or any API key.
- Change the topics in `topics.json` to your own. If two channels post the same scripts, YouTube may treat it
  as repeated content and not show or pay for the videos.
- New YouTube API projects can only upload as PRIVATE until Google approves the project. Check the videos
  and set them public by hand at first.

## Easiest way (from a phone)
1. Log in to claude.ai (any account). Upload the file `START_HERE_shorts_project.txt`.
2. Send this message: "Read this file and do everything in the message at the top."
   (If your Claude has GitHub connected it can build the repo for you. If not, it will guide you one step at a time.)

## Manual way
1. Make a free account at github.com and create a new repository (name: auto-shorts).
2. Upload these files: `auto_shorts.py`, `topics.json`, `requirements.txt`, `README.md`, `.gitignore`
   (Add file > Upload files > Commit changes).
3. Make the daily schedule file: Add file > Create new file. In the name box type exactly
   `.github/workflows/daily.yml` (typing the slashes makes the folders). Paste the contents of `daily.yml`. Commit.
4. Do the setup in `README.md`: Google Cloud (YouTube Data API v3, OAuth Desktop app set to "In production",
   an API key), run the program once on a computer to log in and make `token.json`, then add the GitHub secrets
   `YOUTUBE_TOKEN_JSON` and `YOUTUBE_API_KEY` (Settings > Secrets and variables > Actions).
5. Actions tab > Daily What-If Short > Run workflow to test.

Optional later (paid): `ANTHROPIC_API_KEY` lets Claude write new topics from YouTube trends every day.
