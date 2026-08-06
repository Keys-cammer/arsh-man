"""
Gesture-controlled 3D model viewer
==================================
Open a 3D model in a window and manipulate it with your hands only.

    pip install opencv-python mediapipe open3d numpy
    python gesture_3d_viewer.py

GESTURES
    pinch thumb+index, then move hand ....... rotate the model
    both hands pinched, move apart/together . zoom in / out
    pinch thumb+middle, move hand up/down ... zoom with one hand
    open palm, move hand .................... rotate the model
    open palm, twist your wrist ............. roll the model
    ESC (in camera window) .................. quit

Drop a .obj / .stl / .ply file into models/ and it loads automatically - no
edit needed. With that folder empty, a built-in procedural engine is used.
"""

from pathlib import Path

import numpy as np
import cv2
import mediapipe as mp
import open3d as o3d

# ----------------------------------------------------------------------------
# CONFIG - tune these
# ----------------------------------------------------------------------------
MODEL_PATH   = None      # force one file, e.g. "models/engine.stl".
                         # None = load whatever is in MODEL_DIR automatically.
MODEL_DIR    = "models"  # drop a model in here and just run - no edits needed
MODEL_EXTS   = (".obj", ".stl", ".ply")

# The render loop rewrites the entire vertex array every frame, so triangle
# count is what stands between a responsive demo and a laggy one. CAD exports
# routinely land in the hundreds of thousands. None disables decimation.
MAX_TRIS     = 150_000

CAM_INDEX    = 0

PINCH_ON     = 0.34      # normalized pinch ratio to ENTER a grab
PINCH_OFF    = 0.50      # normalized pinch ratio to EXIT a grab (hysteresis)

# Thumb+middle (one-hand zoom) needs its own pair. It cannot share the index
# thresholds: the middle finger rides along with the index during a rotate, so
# a shared threshold lets the zoom steal a hand that is already rotating.
PINCH_MID_ON  = 0.26     # tighter than PINCH_ON - this gesture must be deliberate
PINCH_MID_OFF = 0.46

# Open palm is a hold gesture too, so it gets a threshold pair of its own.
# The measure is mean finger extension over palm size: roughly 0.6 for a
# spread hand, near 0 for a fist.
PALM_ON      = 0.45      # raise if a half-open hand grabs the model
PALM_OFF     = 0.30      # hold band - release only when clearly closing

SMOOTH       = 0.5       # 0 = no smoothing, 0.9 = very smooth but laggy
ROT_SPEED    = 11.0      # radians per unit of normalized hand travel.
                         # Hand travel is normalized by frame width now, not
                         # per-axis, so this is ~1.8x the old number for the
                         # same vertical feel - and horizontal finally matches.
ROLL_SPEED   = 1.0       # 1.0 = model rolls 1:1 with the wrist twist
ZOOM_SPEED   = 5.3       # also rescaled by width/height for the same reason
MIN_SCALE    = 0.15
MAX_SCALE    = 8.0

MODEL_COLOR  = (0.72, 0.74, 0.78)
BG_COLOR     = (0.05, 0.06, 0.08)

# MediaPipe landmark indices
WRIST, THUMB_TIP, INDEX_TIP, MIDDLE_MCP, MIDDLE_TIP = 0, 4, 8, 9, 12
FINGER_TIPS = [8, 12, 16, 20]
FINGER_PIPS = [6, 10, 14, 18]


# ----------------------------------------------------------------------------
# PROCEDURAL ROCKET ENGINE (used when MODEL_PATH is None)
# ----------------------------------------------------------------------------
def revolve(profile, segments=72):
    """Revolve a 2D (radius, height) profile around the Z axis."""
    profile = np.asarray(profile, dtype=float)
    n = len(profile)
    verts = []
    for i in range(segments):
        a = 2.0 * np.pi * i / segments
        ca, sa = np.cos(a), np.sin(a)
        for r, z in profile:
            verts.append((r * ca, r * sa, z))
    tris = []
    for i in range(segments):
        j = (i + 1) % segments
        for k in range(n - 1):
            a0, a1 = i * n + k, i * n + k + 1
            b0, b1 = j * n + k, j * n + k + 1
            tris.append((a0, b0, b1))
            tris.append((a0, b1, a1))
    return np.array(verts), np.array(tris)


def procedural_engine():
    """A bell-nozzle liquid rocket engine silhouette: injector -> chamber ->
    throat -> expanding bell."""
    profile = [
        (0.00, 1.30),   # injector centre
        (0.30, 1.30),
        (0.32, 1.22),   # injector plate
        (0.32, 0.78),   # combustion chamber wall
        (0.28, 0.68),
        (0.15, 0.56),   # convergent section
        (0.115, 0.50),  # throat
        (0.19, 0.42),
        (0.31, 0.31),   # divergent bell
        (0.44, 0.20),
        (0.56, 0.10),
        (0.66, 0.02),
        (0.70, 0.00),   # nozzle exit
        (0.66, -0.01),  # thin lip so the exit reads as a rim
    ]
    v, t = revolve(profile)
    mesh = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(v), o3d.utility.Vector3iVector(t)
    )

    # A couple of stiffener rings on the chamber for visual interest.
    for z, rad in ((1.05, 0.335), (0.88, 0.335)):
        ring = o3d.geometry.TriangleMesh.create_torus(
            torus_radius=rad, tube_radius=0.022, radial_resolution=48, tubular_resolution=12
        )
        ring.translate((0, 0, z))
        mesh += ring

    mesh.compute_vertex_normals()
    return mesh


def find_model():
    """Pick the model file to load, without anyone editing this file.

    MODEL_PATH wins if it is set; otherwise the first model in MODEL_DIR.
    Everything resolves against the script's own folder, so the program works
    the same whichever directory it is launched from.
    """
    here = Path(__file__).resolve().parent

    if MODEL_PATH:
        given = Path(MODEL_PATH)
        for cand in (given, here / given):
            if cand.is_file():
                return cand
        raise SystemExit(f"MODEL_PATH is set to {MODEL_PATH!r} but that file does not exist.")

    folder = here / MODEL_DIR
    if not folder.is_dir():
        return None
    found = sorted(p for p in folder.iterdir() if p.suffix.lower() in MODEL_EXTS)
    if not found:
        return None
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        print(f"[model] {len(found)} models in {MODEL_DIR}/ ({names})")
        print(f"[model] loading the first by name; rename one to pick another")
    return found[0]


def load_model():
    path = find_model()
    if path is not None:
        mesh = o3d.io.read_triangle_mesh(str(path))
        if len(mesh.vertices) == 0:
            raise SystemExit(f"Could not read any geometry from {path}")
        print(f"[model] {path.name}: {len(mesh.triangles)} triangles, "
              f"{len(mesh.vertices)} vertices")

        # STL stores loose triangles with no shared vertices, so a mesh arrives
        # with ~3 vertices per triangle. Decimation cannot collapse those, and
        # the per-frame cost is driven by vertex count, not triangle count -
        # measured, welding first took a 150k-triangle STL from 27 ms/frame to
        # 5.4 ms. Costs a few hundred ms once, here at load.
        before = len(mesh.vertices)
        mesh.remove_duplicated_vertices()
        mesh.remove_duplicated_triangles()
        mesh.remove_degenerate_triangles()
        if len(mesh.vertices) < before:
            print(f"[model] welded {before} -> {len(mesh.vertices)} vertices")
    else:
        mesh = procedural_engine()
        print(f"[model] nothing in {MODEL_DIR}/ - using the built-in procedural engine")

    # Every frame rewrites the whole vertex array, so a heavy CAD export makes
    # the gestures feel broken rather than merely slow.
    if MAX_TRIS and len(mesh.triangles) > MAX_TRIS:
        mesh = mesh.simplify_quadric_decimation(int(MAX_TRIS))
        print(f"[model] decimated to {len(mesh.triangles)} triangles "
              f"/ {len(mesh.vertices)} vertices (MAX_TRIS={MAX_TRIS})")

    # Decimation drops normals, and STL files never carry usable ones.
    mesh.compute_vertex_normals()

    # Normalize: centre on origin, fit inside a unit cube.
    mesh.translate(-mesh.get_center())
    extent = float(np.max(mesh.get_max_bound() - mesh.get_min_bound()))
    mesh.scale(1.0 / max(extent, 1e-9), center=(0, 0, 0))
    mesh.paint_uniform_color(MODEL_COLOR)
    return mesh


# ----------------------------------------------------------------------------
# MATH HELPERS
# ----------------------------------------------------------------------------
def rot_x(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_z(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


# ----------------------------------------------------------------------------
# HAND ANALYSIS
# ----------------------------------------------------------------------------
class Hand:
    """One hand's landmarks in image space, plus derived gesture features."""

    def __init__(self, lm, w, h):
        self.pts = np.array([[p.x * w, p.y * h] for p in lm.landmark])
        self.w, self.h = w, h
        # Palm size makes every measurement independent of distance to camera.
        self.palm = np.linalg.norm(self.pts[WRIST] - self.pts[MIDDLE_MCP]) + 1e-6

    def pinch_ratio(self, tip=INDEX_TIP):
        return np.linalg.norm(self.pts[THUMB_TIP] - self.pts[tip]) / self.palm

    def pinch_point(self, tip=INDEX_TIP):
        """Midpoint of the pinch, normalized by frame WIDTH on both axes.

        Dividing x by width and y by height would make the same hand movement
        travel further vertically than horizontally - 1.78x on a 960x540 frame
        - so the model tumbled faster than it spun. One divisor keeps the
        rotation mapping isotropic.
        """
        mid = (self.pts[THUMB_TIP] + self.pts[tip]) * 0.5
        return mid / self.w

    def openness(self):
        """How far the four fingers are extended, normalized by palm size.

        A boolean "all tips past their PIPs" test flickers on the frame where
        one finger dips, so this returns a continuous value instead and the
        caller applies PALM_ON / PALM_OFF hysteresis to it.
        """
        wrist = self.pts[WRIST]
        spread = [np.linalg.norm(self.pts[tip] - wrist) - np.linalg.norm(self.pts[pip] - wrist)
                  for tip, pip in zip(FINGER_TIPS, FINGER_PIPS)]
        return float(np.mean(spread)) / self.palm

    def palm_center(self):
        """Midpoint of wrist and middle knuckle, normalized to 0..1 of frame.

        Steadier than a landmark centroid, which drifts as fingers move.
        """
        mid = (self.pts[WRIST] + self.pts[MIDDLE_MCP]) * 0.5
        return mid / self.w      # width on both axes - see pinch_point()

    def palm_angle(self):
        """In-plane angle of the wrist -> middle-knuckle vector, in radians.

        Tilting the hand within the camera plane changes this. True
        forearm-axis roll would need depth, and MediaPipe's z is too noisy to
        use (see CLAUDE.md), so this is the twist measure that survives a real
        webcam.
        """
        v = self.pts[MIDDLE_MCP] - self.pts[WRIST]
        return float(np.arctan2(v[1], v[0]))


class Smoother:
    """Exponential moving average, keyed by hand slot. Kills landmark jitter."""

    def __init__(self, alpha):
        self.alpha = alpha
        self.state = {}

    def __call__(self, key, pts):
        prev = self.state.get(key)
        out = pts if prev is None or prev.shape != pts.shape \
            else self.alpha * prev + (1 - self.alpha) * pts
        self.state[key] = out
        return out

    def forget(self, key):
        self.state.pop(key, None)


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    mesh = load_model()
    base_v = np.asarray(mesh.vertices).copy()
    base_n = np.asarray(mesh.vertex_normals).copy()

    vis = o3d.visualization.Visualizer()
    vis.create_window("3D Model - Gesture Controlled", width=1100, height=800)
    vis.add_geometry(mesh)
    opt = vis.get_render_option()
    opt.background_color = np.asarray(BG_COLOR)
    opt.mesh_show_back_face = True
    vis.reset_view_point(True)

    cap = cv2.VideoCapture(CAM_INDEX)
    if not cap.isOpened():
        raise SystemExit("Could not open the webcam.")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)

    mp_hands = mp.solutions.hands
    mp_draw = mp.solutions.drawing_utils
    hands = mp_hands.Hands(
        max_num_hands=2,
        model_complexity=0,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.6,
    )

    smoother = Smoother(SMOOTH)

    # ---- interaction state ----
    rot = np.eye(3)
    scale = 1.0
    grab_prev = None        # last pinch point while rotating
    zoom_prev = None        # last y while one-hand zooming
    span_ref = None         # (initial two-hand distance, scale at that moment)
    palm_prev = None        # (palm centre, palm angle) while open-palm rotating
    mode = "idle"

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)               # mirror: feels natural
        h, w = frame.shape[:2]

        result = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        hands_list = []
        seen_keys = set()
        if result.multi_hand_landmarks:
            handed = result.multi_handedness or []
            for i, lm in enumerate(result.multi_hand_landmarks):
                mp_draw.draw_landmarks(frame, lm, mp_hands.HAND_CONNECTIONS)
                # Key the EMA on handedness, not list position. MediaPipe's
                # ordering can swap between frames, and a positional key would
                # then smooth one hand's landmarks into the other's - the model
                # visibly jumps when that happens.
                key = handed[i].classification[0].label if i < len(handed) else f"slot{i}"
                if key in seen_keys:      # both hands classified the same - rare
                    key = f"{key}{i}"
                seen_keys.add(key)
                hand = Hand(lm, w, h)
                hand.pts = smoother(key, hand.pts)
                hands_list.append(hand)
        for k in list(smoother.state):
            if k not in seen_keys:
                smoother.forget(k)

        # ---------------- gesture state machine ----------------
        pinched = [hd for hd in hands_list if hd.pinch_ratio() < PINCH_ON]
        held    = [hd for hd in hands_list if hd.pinch_ratio() < PINCH_OFF]
        # Measured on thumb+middle only, so a rotating hand no longer qualifies
        # for the zoom just because its index is closed.
        mid_on  = [hd for hd in hands_list if hd.pinch_ratio(MIDDLE_TIP) < PINCH_MID_ON]
        mid_off = [hd for hd in hands_list if hd.pinch_ratio(MIDDLE_TIP) < PINCH_MID_OFF]
        palm_on  = [hd for hd in hands_list if hd.openness() > PALM_ON]
        palm_off = [hd for hd in hands_list if hd.openness() > PALM_OFF]

        if len(hands_list) == 2 and len(held) == 2:
            # ---- two-hand zoom: separation between the two pinch points ----
            a, b = held[0].pinch_point(), held[1].pinch_point()
            span = float(np.linalg.norm(a - b))
            if span_ref is None:
                span_ref = (span, scale)
            ref_span, ref_scale = span_ref
            scale = float(np.clip(ref_scale * (span / max(ref_span, 1e-3)),
                                  MIN_SCALE, MAX_SCALE))
            grab_prev = zoom_prev = palm_prev = None
            mode = "zoom (2 hands)"

        elif mid_on or (zoom_prev is not None and mid_off):
            # ---- one-hand zoom: thumb + middle, move up/down ----
            # zoom_prev doubles as the "already zooming" flag, so once entered
            # the gesture holds down to PINCH_MID_OFF instead of dropping out.
            hand = (mid_on or mid_off)[0]
            y = float(hand.pinch_point(MIDDLE_TIP)[1])
            if zoom_prev is not None:
                scale = float(np.clip(scale * np.exp((zoom_prev - y) * ZOOM_SPEED),
                                      MIN_SCALE, MAX_SCALE))
            zoom_prev = y
            grab_prev = span_ref = palm_prev = None
            mode = "zoom (1 hand)"

        elif pinched or (grab_prev is not None and held):
            # ---- rotate: thumb + index, drag ----
            hand = (pinched or held)[0]
            p = hand.pinch_point()
            if grab_prev is not None:
                d = p - grab_prev
                rot = rot_y(d[0] * ROT_SPEED) @ rot_x(d[1] * ROT_SPEED) @ rot
            grab_prev = p
            zoom_prev = span_ref = palm_prev = None
            mode = "rotate"

        elif palm_on or (palm_prev is not None and palm_off):
            # ---- open palm: move to rotate, twist to roll ----
            # Last in the chain on purpose: a pinching hand is still fairly
            # open, so the pinch gestures get first claim on it.
            hand = (palm_on or palm_off)[0]
            c, ang = hand.palm_center(), hand.palm_angle()
            if palm_prev is not None:
                prev_c, prev_ang = palm_prev
                d = c - prev_c
                # Wrap the angle delta into [-pi, pi]. Without this, a twist
                # across the +/-180 boundary reads as a near-full turn and the
                # model snaps round.
                da = np.arctan2(np.sin(ang - prev_ang), np.cos(ang - prev_ang))
                rot = (rot_z(da * ROLL_SPEED)
                       @ rot_y(d[0] * ROT_SPEED)
                       @ rot_x(d[1] * ROT_SPEED) @ rot)
            palm_prev = (c, ang)
            grab_prev = zoom_prev = span_ref = None
            mode = "rotate (palm)"

        else:
            grab_prev = zoom_prev = span_ref = palm_prev = None
            mode = "idle"

        # ---------------- apply transform to the mesh ----------------
        mesh.vertices = o3d.utility.Vector3dVector((base_v @ rot.T) * scale)
        mesh.vertex_normals = o3d.utility.Vector3dVector(base_n @ rot.T)
        vis.update_geometry(mesh)
        if not vis.poll_events():
            break
        vis.update_renderer()

        # ---------------- on-screen feedback ----------------
        cv2.rectangle(frame, (0, 0), (w, 64), (25, 25, 30), -1)
        cv2.putText(frame, f"MODE: {mode.upper()}", (14, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (90, 220, 255), 2)
        cv2.putText(frame, f"scale {scale:4.2f}   hands {len(hands_list)}", (14, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 200, 200), 1)
        for hd in hands_list:
            r = hd.pinch_ratio()
            colour = (80, 255, 120) if r < PINCH_ON else (120, 120, 120)
            a = hd.pts[THUMB_TIP].astype(int)
            b = hd.pts[INDEX_TIP].astype(int)
            cv2.line(frame, tuple(a), tuple(b), colour, 2)
            cv2.circle(frame, tuple(a), 7, colour, -1)
            cv2.circle(frame, tuple(b), 7, colour, -1)

            # Palm vector: shows both what openness() reads and which way the
            # roll is being measured, which is otherwise invisible.
            o = hd.openness()
            pcol = (255, 180, 60) if o > PALM_ON else (110, 110, 110)
            wr = hd.pts[WRIST].astype(int)
            mc = hd.pts[MIDDLE_MCP].astype(int)
            cv2.line(frame, tuple(wr), tuple(mc), pcol, 2)
            cv2.putText(frame, f"{o:3.2f}", tuple(wr + np.array([8, 20])),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, pcol, 1)

        cv2.imshow("Hand Control  (ESC to quit)", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()
    vis.destroy_window()


if __name__ == "__main__":
    main()
