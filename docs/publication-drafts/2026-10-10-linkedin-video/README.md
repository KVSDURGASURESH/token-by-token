# LinkedIn launch video

Status: rendered locally; not published.

This 35-second, 1080×1350 launch video uses only repository-owned visual
material and sanitized public evidence. It intentionally excludes Grafana,
provider identifiers, private infrastructure, the unresolved website domain,
and any Substack URL until a public post exists.

## Render

Prerequisites: Node.js, the dashboard's locked Playwright dependency, Google
Chrome at its standard macOS application path, FFmpeg/FFprobe, and the macOS
`say` command with the built-in Samantha voice.

```bash
npm --prefix dashboard ci
./docs/publication-drafts/2026-10-10-linkedin-video/render-video.sh
```

The render script produces the MP4, a JSON technical probe, a contact sheet,
seven source frames, and narration audio. Generated files are working
publication assets; they do not modify benchmark evidence.

## Evidence boundaries

- The 27.5% comparison is SGLang relative to vLLM at the recorded 16-user load.
- The recorded output rates are 480.44 and 376.73 output tokens/s.
- Both recorded p10 decode rates are below the declared 20 tokens/s floor.
- Episode 00 and Episode 01 are separate experiments and not an H100/H200
  comparison.
- Tested closed-loop loads do not establish maximum sustainable request rate or
  production capacity.
- The GitHub repository is public. The website and Substack URL are omitted
  until independently available.

Before publishing, visually review the MP4, replace or remove the pending
Substack line in `linkedin-caption.md`, confirm the LinkedIn account and
audience, and obtain final publish approval.
