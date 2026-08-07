FROM nousresearch/hermes-agent:latest

# Install system deps: ffmpeg for audio processing, yt-dlp for SoundCloud, libsndfile for librosa
RUN apt-get update && apt-get install -y --no-install-recommends jq curl ffmpeg yt-dlp libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

# Phase 1: librosa for audio analysis (BPM/key detection, spectral analysis)
# Phase 2: demucs for AI stem separation (drums/bass/vocals/other)
RUN uv pip install --python /opt/hermes/.venv/bin/python3 --no-cache librosa numpy soundfile && \
    uv pip install --python /opt/hermes/.venv/bin/python3 --no-cache torch --extra-index-url https://download.pytorch.org/whl/cpu && \
    uv pip install --python /opt/hermes/.venv/bin/python3 --no-cache demucs

# Matchering: reference-based mastering (match RMS, FR, peak, stereo width to a pro track)
# Pedalboard: Spotify's studio-quality per-stem effects (reverb, compression, EQ, limiting)
RUN uv pip install --python /opt/hermes/.venv/bin/python3 --no-cache matchering pedalboard

COPY skills/ /opt/hermes/bundled-skills/
COPY skins/ /opt/hermes/bundled-skins/
COPY entrypoint.sh /opt/hermes/entrypoint.sh
RUN chmod +x /opt/hermes/entrypoint.sh && \
    chmod -R a+rw /opt/hermes/ui-tui/dist /opt/hermes/.venv /opt/hermes/node_modules /opt/hermes/bundled-skills /opt/hermes/bundled-skins && \
    rm -f /opt/hermes/docker/SOUL.md

ENV HERMES_HOME=/opt/data

ENTRYPOINT ["/opt/hermes/entrypoint.sh"]
