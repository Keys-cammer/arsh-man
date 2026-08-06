# Gesture-Controlled 3D Model Viewer

Manipulate a 3D model with your hands in front of a webcam — no keyboard, no
mouse. Pinch to rotate, spread two hands to zoom, twist your wrist to roll.

Built around MediaPipe hand tracking and Open3D rendering, in a single Python
file. Point it at any `.stl`, `.obj` or `.ply` and it loads automatically.

![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)

## Gestures

| Gesture | Action |
|---|---|
| Pinch thumb + index, move hand | Rotate |
| Open palm, move hand | Rotate |
| Open palm, twist your wrist | Roll |
| Pinch thumb + middle, move up / down | Zoom, one hand |
| Both hands pinched, move apart / together | Zoom |
| `ESC` in the camera window | Quit |

There is no reset gesture — restart to get the default view back.

## Setup

Use **Python 3.10 or 3.11**. MediaPipe wheels are unreliable on 3.12+, and a
version mismatch is by far the most common install failure.

```bash
git clone https://github.com/Keys-cammer/arsh-man.git
cd arsh-man
python -m venv venv
```

Activate it — Windows:

```bash
venv\Scripts\activate
```

macOS / Linux:

```bash
source venv/bin/activate
```

Then install and run:

```bash
pip install -r requirements.txt
python gesture_3d_viewer.py
```

Two windows open: the camera feed with a landmark overlay, and the 3D view.
A real webcam is required.

## Loading your own model

Drop a `.stl`, `.obj` or `.ply` into `models/` and run. That is the whole
procedure — no code edit. The model is auto-centered and auto-scaled to fit the
view, whatever units it was exported in.

With `models/` empty, a built-in procedural rocket engine is used instead.

If several models are present the first by filename wins, and the script prints
which one it picked. To force a specific file, set `MODEL_PATH` at the top of
`gesture_3d_viewer.py`.

Free sources: NASA 3D Resources (public domain), GrabCAD, Thingiverse.

### Large CAD files

`MAX_TRIS` (default 150,000) caps how heavy a mesh the render loop carries.
Above it, the model is decimated once at load.

STL also stores loose triangles with no shared vertices, so meshes arrive with
roughly three times the vertices they need — and per-frame cost tracks vertex
count, not triangle count. The script welds duplicates on load. On a
150k-triangle test mesh that took the per-frame transform from 27 ms to 5.4 ms.
Both steps print what they did, so watch the terminal if a model feels heavy.

## Tuning

Every adjustable value lives in the `CONFIG` block at the top of the file.

| Setting | Raise it when |
|---|---|
| `SMOOTH` | The model feels twitchy (try 0.7) |
| `PINCH_ON` | The pinch won't register for your hand |
| `PINCH_MID_ON` | Thumb+middle zoom won't trigger. Lower it if the zoom grabs a hand you meant to rotate with |
| `PALM_ON` | A half-open hand keeps grabbing the model. Lower it if an open palm won't take hold |
| `ROT_SPEED` | Rotation feels sluggish |
| `ROLL_SPEED` | Wrist twist barely moves the model |
| `ZOOM_SPEED` | Zoom feels sluggish |

`PINCH_OFF`, `PINCH_MID_OFF` and `PALM_OFF` are release thresholds — each hold
gesture enters on the tight value and holds until the loose one, so it doesn't
flicker at the boundary. Keep each `_OFF` on the loose side of its `_ON` (below
for the pinches, above for the palm, since that measure runs the other way).

## How it works

A few decisions are load-bearing and worth knowing before changing anything:

- **Pinch distance is normalized by palm size** (wrist → middle knuckle). Raw
  pixel distance breaks the moment your hand moves toward or away from the
  camera.
- **Every hold gesture has two thresholds.** A single one flickers at the
  boundary and the model jitters, so each enters tight and releases loose.
- **MediaPipe's `z` coordinate is unused.** It is too noisy for depth. Zoom
  comes from hand separation or hand travel instead, and roll from the in-plane
  hand angle.
- **The mesh is transformed, not the camera.** Rotation and scale are applied
  to the vertex array each frame, because Open3D's `ViewControl` has had
  regressions where changes don't persist.
- **Hand travel is normalized by frame width on both axes.** Dividing y by
  height instead makes vertical rotation 1.78× faster than horizontal on a
  960×540 frame, which is what makes rotation feel unruly.
- Landmarks are smoothed with an EMA, keyed by handedness rather than detection
  order — MediaPipe can swap the order between frames, and a positional key
  blends one hand's landmarks into the other's.

## Ideas to extend

- **Exploded view** — spread both open palms to separate injector, chamber and
  nozzle into labelled layers.
- **Point to annotate** — hold your index finger over a component to raise a
  callout naming it.
