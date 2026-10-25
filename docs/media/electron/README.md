# README media

Captured from the Electron renderer on Linux, September 16, 2026. These images show the development branch, not a claim about a published release. The browser capture runs the same renderer as Electron; native window decorations are excluded.

Only the bundled demo voice appears. Personal profiles, history, and projects are filtered from the capture context, and API mutations are blocked. The normal app and its local storage are left alone.

With the Electron development server running:

```bash
CHROMIUM_PATH=/usr/bin/chromium node scripts/capture-readme-electron.mjs
```

The script writes PNG screenshots here and prints the temporary WebM path. Convert that recording to the main GIF (replace `recording.webm` with that path):

```bash
ffmpeg -y -ss 1 -i recording.webm -vf 'fps=8,scale=1120:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3' -loop 0 docs/media/electron/voicestudio.gif
```

The README uses the GIF plus the cloning and dubbing screenshots. Design and model screenshots are captured as companion stills. The official logo and repository badges retain their existing assets.
