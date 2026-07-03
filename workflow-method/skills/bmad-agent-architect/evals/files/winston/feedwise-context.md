# FeedWise — Context for Architecture

## What it is
FeedWise is a small SaaS that lets podcast creators turn each published episode into
a set of short promo assets: an audiogram clip, a transcript, and three suggested
social captions. The creator pastes an episode's public RSS/audio URL, FeedWise
fetches the audio, transcribes it, and generates the assets.

## v1 scope (agreed)
- A creator signs in (email/password) and connects nothing else — they just paste an episode audio URL.
- The system downloads the audio (up to ~120 min), transcribes it, and stores the transcript.
- From the transcript it generates: one 30–60s audiogram (waveform + captions over the episode artwork), and three caption suggestions.
- The creator views the assets on an episode page and downloads the audiogram (mp4) and transcript (txt).
- Expected load at launch: a few hundred creators, each processing 1–8 episodes per week. Bursty — most uploads land Monday/Tuesday.

## Explicitly out of v1
- No direct podcast-host integrations (Spotify/Apple) — URL paste only.
- No team accounts, no billing/Stripe yet (manual invoicing for the pilot).
- No mobile app.
- No multi-language transcription — English only for v1.

## Constraints / preferences stated by the founder
- Solo founder + one part-time engineer. Wants to keep ops simple.
- Already pays for an OpenAI-compatible transcription+LLM API and wants to keep using a hosted model API rather than self-hosting GPUs.
- Comfortable on a single cloud provider; has AWS credits.
- Transcribing a 2-hour episode and rendering an audiogram is slow (minutes), so it must not block the web request.

## Undecided / open (founder hasn't chosen)
- Whether to store audio long-term or discard after processing.
- Exact audiogram rendering approach (ffmpeg in a worker vs a third-party render service).
- Database choice.
- Whether to add a CDN now or later.
