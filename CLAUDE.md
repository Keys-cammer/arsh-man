# CLAUDE.md

Project context for Claude Code. Read this before making changes.

## What this project is

A computer vision demo: a window opens showing a 3D model of a rocket engine,
and the user manipulates it with hand gestures only — no keyboard, no mouse.
Built to be demonstrated live to classmates, so **reliability under a real
webcam matters more than feature count**.

## Stack

- **Python 3.10 or 3.11** — required. MediaPipe wheels are unreliable on 3.12+.
  If an install fails, check the Python version before anything else.
- `mediapipe` — hand tracking (21 landmarks per hand, `mp.solutions.hands`)
- `opencv-python` — webcam capture and the debug overlay window
- `open3d` — 3D rendering window
- `numpy`

## Layout

```
gesture_3d_viewer.py    single-file program; CONFIG block at the top
requirements.txt
README.md               user-facing setup and gesture docs
models/                 .obj / .stl / .ply files
```

Keep it a single file unless it genuinely outgrows one. If it must split,
suggest the split first rather than doing it unprompted.

## Gesture map (the contract — don't change without asking)

| Gesture | Action |
|---|---|
| Pinch thumb + index, move hand | Rotate |
| Both hands pinched, move apart / together | Zoom |
| Pinch thumb + middle, move up / down | Zoom, one hand |
| Open palm, all 5 fingers | Reset |
| ESC in camera window | Quit |

## Design decisions already made — don't undo these

1. **Pinch distance is normalized by palm size** (wrist → middle MCP). Raw
   pixel distance breaks the moment the hand moves toward or away from the
   camera. Any new gesture threshold must be normalized the same way.
2. **Hysteresis on pinch:** `PINCH_ON` to enter a grab, looser `PINCH_OFF` to
   exit. Without it the grab flickers at the boundary and the model jitters.
   Any new hold-style gesture needs its own two thresholds.
3. **MediaPipe's `z` landmark coordinate is not used and should stay unused.**
   It is too noisy for depth. Zoom comes from hand separation or hand travel.
4. **The mesh is transformed, not the camera.** Open3D's `ViewControl` has had
   regressions where changes don't persist. Rotation and scale are applied to
   the vertex array each frame instead. Don't refactor to `get_view_control()`.
5. Camera frame is mirrored (`cv2.flip`) so movement feels natural.
6. Landmarks are smoothed with an EMA (`SMOOTH`) before use.

## Critical limitation on your side

**You cannot see the webcam feed or the 3D window.** Whether a gesture "feels
right" is something only the user can judge.

So: do not guess at tuning values and declare them fixed. When the issue is
about feel — twitchy, too fast, won't trigger — change one constant, say which
one and in which direction, and ask the user to run it and report back. When
the issue is a crash or a traceback, that you can fix outright.

Tuning constants live in the CONFIG block: `SMOOTH`, `PINCH_ON`, `PINCH_OFF`,
`ROT_SPEED`, `ZOOM_SPEED`.

## Running it

```bash
source venv/bin/activate        # venv\Scripts\activate on Windows
python gesture_3d_viewer.py
```

Needs a real webcam. It cannot be tested headlessly — don't report a change as
verified when you have only confirmed that it imports.

## Style

- Standard library and the four deps above only. Ask before adding a dependency.
- Every tunable value goes in the CONFIG block at the top, never inline.
- Comment the *why*, not the *what*, especially for gesture thresholds.
- Keep the on-screen overlay (mode name, scale, pinch line) working — it is the
  main debugging tool and it is part of the demo.

## Planned next

- **Exploded view** — spreading both open palms separates injector, chamber and
  nozzle into labelled layers.
- **Point to annotate** — holding an index finger over a component raises a
  callout naming it.

Neither is started. Ask before beginning one.
