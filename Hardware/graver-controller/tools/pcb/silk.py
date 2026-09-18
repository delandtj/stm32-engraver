#!/usr/bin/env python3
"""Draw the silkscreen on graver-controller.kicad_pcb.

Runs AFTER place.py and copper.py (or as `place.py --copper --silk`, which
calls both). It touches F.Silkscreen only - no copper item is created, moved
or deleted, and the F.Fab layer is left exactly as place.py made it.

Idempotent in two different ways, because there are two kinds of silk:

  * everything this script CREATES (the rear-edge connector labels, the pin
    legends, the pin-1 markers and the board title) goes into a PCB group
    named SILK_GROUP, and the first thing a run does is delete that group's
    members - so re-running replaces them instead of stacking them;
  * everything it MOVES (every footprint's reference field) is positioned
    absolutely from the part's own body box, never relative to where the
    field happens to sit, and the obstacle set is rebuilt from scratch. A
    second run therefore computes the same positions as the first.

What it does, in order:

  1. clips the F.Silkscreen graphics that cross the board outline - the four
     right-angle rear connectors overhang the rear edge and their library
     outlines with them, which is the whole silk_edge_clearance count
  2. resets every reference field to 1.0 mm / 0.15 mm on F.Silkscreen (ADR
     0003 decision 5 minimum) and hides the four mounting-hole references
  3. places the rear-edge connector labels, the J201 and J401 pin legends,
     the pin-1 markers and the board title, which claim their space first
  4. places every reference by searching outwards from its own body: above,
     below, left/right, then the corners, taking the first position that is
     clear of every mask opening, every other piece of silk and the board
     edge
  5. re-runs kicad-cli DRC and prints the silk warning counts by type

Usage:  python3 tools/pcb/silk.py [--no-drc] [--verbose]
"""

import collections
import json
import math
import os
import subprocess
import sys

import pcbnew

# KiCad 10 + Python 3.14: the SWIG iterator lost its .next shim.
if not hasattr(pcbnew.SwigPyIterator, "next"):
    pcbnew.SwigPyIterator.next = pcbnew.SwigPyIterator.__next__

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.normpath(os.path.join(HERE, "..", ".."))
NAME = "graver-controller"
PCB = os.path.join(PROJ, NAME + ".kicad_pcb")
PRO = os.path.join(PROJ, NAME + ".kicad_pro")
OUT = os.path.join(PROJ, "output", "pcb")

ORIGIN = (50.0, 50.0)          # must match place.py
BOARD_W, BOARD_H = 110.0, 70.0
CORNER_R = 2.0

SILK_GROUP = "scripted-silk"

# ------------------------------------------------------------- numbers -----
# ADR 0003 decision 5: silkscreen 0.15 mm lines, 1.0 mm text minimum.
REF_SIZE, REF_THICK = 1.0, 0.15        # reference designators
LABEL_SIZE, LABEL_THICK = 1.2, 0.18    # rear-edge connector names (1.2-1.5)
PIN_SIZE, PIN_THICK = 1.0, 0.15        # pin numbers and pin names
TITLE_SIZE, TITLE_THICK = 1.4, 0.20    # board title
MARK_SIZE = 1.1                        # pin-1 triangle, tip to base

EDGE_CLR = 0.5        # silk text to board outline (brief)
EDGE_LINE_CLR = 0.08  # silk GRAPHIC to board outline, used by the clipper
PAD_CLR = 0.03        # text box to a mask opening
SILK_CLR = 0.03       # text box to any other silk line or text
MASK_MARGIN = 0.05    # a mask opening is the pad grown by this much

# Ring ladder, in mm of air between the part's body box and the text box.
# Ring 1 is the brief's 1.5 mm and ring 2 its 3.0 mm fallback. Past that the
# search leaves the ladder and sweeps a grid out to FREE_R - the "reference
# row" case: a label that cannot stay with its part and ends up in a line
# above or below the row of parts.
RING1 = [0.15 + 0.15 * i for i in range(10)]           # 0.15 .. 1.50
RING2 = [1.65 + 0.15 * i for i in range(9)]            # 1.65 .. 3.00
FREE_R = 12.0

# A legal position is not automatically a readable one: a label that sits
# nearer someone else's body than its own reads as that part's label. A
# candidate is only taken if its own part is the nearest body, give or take
# OWN_SLACK - without that slack two 0603s 1.6 mm apart could never both be
# labelled. The whole search is repeated without the test for anything that
# cannot satisfy it, and the run prints what that cost.
OWN_SLACK = 0.25

DIRS = ("N", "S", "W", "E", "NW", "NE", "SW", "SE")
# Text runs along the part in the two side positions and across it above and
# below, which is what keeps a row of standing 0603s from fighting for the
# same lane.
ROT_PREF = {"N": (0, 90), "S": (0, 90), "W": (90, 0), "E": (90, 0),
            "NW": (0, 90), "NE": (0, 90), "SW": (0, 90), "SE": (0, 90)}

# Body area from which a part is "big" enough to carry its reference inside
# its own outline: connectors, the QFN, the DPAK, the SO-8s, the inductor,
# the switches and the encoder.
BIG_AREA = 20.0

# The four mounting holes do not need a silk label (brief item 4).
NO_SILK_REF = ("MH401", "MH402", "MH403", "MH404")

# ---------------------------------------------------------- nudge table ----
# ref -> (dx, dy, rot): put this reference at the footprint origin plus
# (dx, dy) at `rot` degrees and skip the search entirely. Same shape as the
# placement tables in place.py. The run prints "OVERRIDE" for each one and
# still reports whether the spot is legal, so a bad nudge is visible.
REF_OVERRIDE = {
}

# ------------------------------------------------- rear-edge connectors ----
# ADR 0003 "Polish": DC 24V, USB, PEDAL, HANDPIECE, plus SWD. Each is seeded
# just inside the rear edge next to its connector and then searched outwards
# from that seed, so the numbers below are intent, not hard coordinates.
REAR_LABELS = (
    # ref,    text,         seed (x, y),      size
    ("J101", "DC 24V",    (17.60, 1.58), LABEL_SIZE),
    ("J301", "USB",       (29.00, 4.20), LABEL_SIZE),
    ("J302", "SWD",       (43.60, 5.60), LABEL_SIZE),
    ("J201", "HANDPIECE", (61.90, 4.60), LABEL_SIZE),
    ("J402", "PEDAL",     (88.00, 1.75), LABEL_SIZE),
)

# Pin legends. The seed is an offset from the pad itself, so the legend
# follows the connector if place.py moves it.
#
# J201 is at rotation 180 (place.py: the four wire-entry funnels are drawn on
# its +y side and nothing else points them out of the rear edge), which
# reverses the pin order on the board. Seen from the front, left to right,
# it is 4 GND / 3 NTC / 2 COIL_NEG / 1 VIN - the legend has to follow that
# and not the schematic.
PIN_LEGEND = (
    # ref,   pad, text,     seed offset from the pad, rot, size
    ("J201", "4", "4 GND",  (0.0, -3.05), 0, PIN_SIZE),
    ("J201", "3", "3 NTC",  (0.0, -3.05), 0, PIN_SIZE),
    ("J201", "2", "2 COIL", (0.0, -3.05), 0, PIN_SIZE),
    ("J201", "1", "1 VIN",  (0.0, -3.05), 0, PIN_SIZE),
    # J401, the LCD's 1x7 XH: names along the pins, in front of the body.
    ("J401", "1", "G",      (0.0, 6.40), 90, PIN_SIZE),
    ("J401", "2", "3V3",    (0.0, 5.90), 90, PIN_SIZE),
    ("J401", "3", "SCK",    (0.0, 5.90), 90, PIN_SIZE),
    ("J401", "4", "SDA",    (0.0, 5.90), 90, PIN_SIZE),
    ("J401", "5", "RST",    (0.0, 5.90), 90, PIN_SIZE),
    ("J401", "6", "DC",     (0.0, 5.90), 90, PIN_SIZE),
    ("J401", "7", "BL",     (0.0, 5.90), 90, PIN_SIZE),
)

# Filled triangles pointing at pin 1. The seed is absolute; `point` is the
# direction the tip faces.
PIN1_MARKS = (
    # ref,   pad, seed (x, y),     point
    ("J201", "1", (71.85, 10.05), "W"),
    ("J302", "1", (37.00, 4.95),  "N"),
    ("J401", "1", (20.00, 57.30), "S"),
)

# Board title, in the empty front-centre strip (README "What is still rough"
# item 3: x 45..78 / y 45..70 is the empty fifth of the board).
TITLE = (
    ("GRAVER CTRL r0.1", (57.00, 67.30), TITLE_SIZE, TITLE_THICK),
    ("2026-09",          (74.00, 67.30), TITLE_SIZE, TITLE_THICK),
)


# ============================================================ helpers ======
def mm(v):
    return pcbnew.FromMM(v)


def tomm(v):
    return pcbnew.ToMM(v)


def at(x, y):
    return pcbnew.VECTOR2I(mm(ORIGIN[0] + x), mm(ORIGIN[1] + y))


def loc(pos):
    return (tomm(pos.x) - ORIGIN[0], tomm(pos.y) - ORIGIN[1])


def angle(deg):
    return pcbnew.EDA_ANGLE(float(deg), pcbnew.DEGREES_T)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def seg_point_dist(a, b, p):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def seg_seg_dist(a, b, c, d):
    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    d1, d2 = cross(c, d, a), cross(c, d, b)
    d3, d4 = cross(a, b, c), cross(a, b, d)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(seg_point_dist(a, b, c), seg_point_dist(a, b, d),
               seg_point_dist(c, d, a), seg_point_dist(c, d, b))


def seg_rect_dist(a, b, r):
    """Distance from segment a-b to axis-aligned rect (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = r
    for p in (a, b):
        if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
            return 0.0
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    best = 1e9
    for i in range(4):
        best = min(best, seg_seg_dist(a, b, corners[i], corners[(i + 1) % 4]))
        if best == 0.0:
            return 0.0
    return best


def rect_gap(a, b):
    """Air between two axis-aligned rects; 0.0 when they touch or overlap."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def grow(r, d):
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def rect_corners(r):
    return ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3]))


def point_in_board(p, clr):
    """Inside the 110 x 70 outline with 2 mm corner radii, by `clr` mm."""
    x, y = p
    if not (clr <= x <= BOARD_W - clr and clr <= y <= BOARD_H - clr):
        return False
    for cx, cy in ((CORNER_R, CORNER_R), (BOARD_W - CORNER_R, CORNER_R),
                   (BOARD_W - CORNER_R, BOARD_H - CORNER_R),
                   (CORNER_R, BOARD_H - CORNER_R)):
        if abs(x - cx) > CORNER_R or abs(y - cy) > CORNER_R:
            continue
        inx = (x < CORNER_R) == (cx < BOARD_W / 2)
        iny = (y < CORNER_R) == (cy < BOARD_H / 2)
        if inx and iny and math.hypot(x - cx, y - cy) > CORNER_R - clr:
            return False
    return True


def rect_in_board(r, clr):
    # The rect and the inset outline are both convex, so its corners decide.
    return all(point_in_board(p, clr) for p in rect_corners(r))


def item_box(it):
    b = it.GetBoundingBox()
    return (tomm(b.GetLeft()) - ORIGIN[0], tomm(b.GetTop()) - ORIGIN[1],
            tomm(b.GetRight()) - ORIGIN[0], tomm(b.GetBottom()) - ORIGIN[1])


def fab_bbox(fp):
    """F.Fab bbox in board-local mm - the real BODY outline. Same rule as
    place.py: graphics only, text skipped (place.py grows the F.Fab
    ${REFERENCE} to fill the body, which would read as body)."""
    pts = []
    for it in fp.GraphicalItems():
        if it.GetClass() in ("PCB_TEXT", "PCB_TEXTBOX"):
            continue
        if it.GetLayer() == pcbnew.F_Fab:
            pts.append(item_box(it))
    if not pts:
        b = fp.GetBoundingBox(False, False)
        return (tomm(b.GetLeft()) - ORIGIN[0], tomm(b.GetTop()) - ORIGIN[1],
                tomm(b.GetRight()) - ORIGIN[0], tomm(b.GetBottom()) - ORIGIN[1])
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[2] for p in pts), max(p[3] for p in pts))


# ========================================================== the clipper ====
def clip_seg(a, b, lo, hi):
    """Liang-Barsky clip of a-b to the box (lo, hi); None when fully out."""
    x0, y0 = a
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - lo[0]), (dx, hi[0] - x0),
                 (-dy, y0 - lo[1]), (dy, hi[1] - y0)):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    if t1 - t0 < 1e-9:
        return None
    return ((x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy))


_DETACHED = []        # see strip_previous() / clip_footprint_silk()


def clip_footprint_silk(board, verbose=False):
    """Trim the F.Silkscreen graphics that cross the board outline.

    All four rear connectors are right-angle parts that overhang the rear
    edge on purpose (place.py EDGE_PARTS), and their library outlines
    overhang with them - that is every silk_edge_clearance warning that is
    not a reference field. A segment that still has a piece inside is
    shortened in place (clipping an already clipped segment is a no-op, so
    this stays idempotent); one that is wholly outside is removed.
    """
    n_clip = n_drop = n_left = 0
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        for it in list(fp.GraphicalItems()):
            if it.GetLayer() != pcbnew.F_SilkS:
                continue
            if it.GetClass() != "PCB_SHAPE":
                continue
            hw = tomm(it.GetWidth()) / 2.0 + EDGE_LINE_CLR
            lo, hi = (hw, hw), (BOARD_W - hw, BOARD_H - hw)
            sh = it.GetShape()
            if sh == pcbnew.SHAPE_T_SEGMENT:
                a, b = loc(it.GetStart()), loc(it.GetEnd())
                cl = clip_seg(a, b, lo, hi)
                if cl is None:
                    fp.Remove(it)
                    _DETACHED.append(it)
                    n_drop += 1
                    if verbose:
                        print("    dropped %s segment (%.2f, %.2f)-(%.2f, "
                              "%.2f)" % ((fp.GetReference(),) + a + b))
                elif dist(cl[0], a) > 1e-6 or dist(cl[1], b) > 1e-6:
                    it.SetStart(at(*cl[0]))
                    it.SetEnd(at(*cl[1]))
                    n_clip += 1
            elif sh == pcbnew.SHAPE_T_RECT:
                a, b = loc(it.GetStart()), loc(it.GetEnd())
                r = (min(a[0], b[0]), min(a[1], b[1]),
                     max(a[0], b[0]), max(a[1], b[1]))
                c = (max(r[0], lo[0]), max(r[1], lo[1]),
                     min(r[2], hi[0]), min(r[3], hi[1]))
                if c[2] - c[0] < 0.2 or c[3] - c[1] < 0.2:
                    fp.Remove(it)
                    _DETACHED.append(it)
                    n_drop += 1
                elif rect_gap(r, c) > 0 or r != c:
                    it.SetStart(at(c[0], c[1]))
                    it.SetEnd(at(c[2], c[3]))
                    n_clip += 1
            else:
                box = item_box(it)
                if not rect_in_board(box, 0.0):
                    n_left += 1
                    print("  WARNING %s: %s on F.Silkscreen crosses the "
                          "outline and is not clipped" % (fp.GetReference(),
                                                          sh))
    print("silk outline clip: %d graphic(s) shortened, %d dropped, %d left"
          % (n_clip, n_drop, n_left))
    return n_clip, n_drop


# =============================================================== model ====
CELL = 4.0            # spatial hash cell for the obstacle set, mm


class Silk:
    """The obstacle set every piece of silk is checked against.

    Everything goes into one flat list of obstacles plus a 4 mm spatial hash
    over their bounding boxes, because the reference search probes tens of
    thousands of candidate positions and a linear scan over 1000 obstacles
    per probe is minutes of nothing.
    """

    def __init__(self, board):
        self.board = board
        self.fps = collections.OrderedDict(
            (f.GetReference(), f)
            for f in sorted(board.GetFootprints(),
                            key=lambda f: f.GetReference()))
        self.made = []          # board-level items to lock + group
        self.obs = []           # (kind, geometry, owner)
        self.cells = collections.defaultdict(list)
        self.n_mask = self.n_line = 0
        self._index_masks()
        self._index_lines()

    # ------------------------------------------------------------ index --
    def _add(self, kind, geo, owner, box):
        i = len(self.obs)
        self.obs.append((kind, geo, owner))
        for cx in range(int(math.floor(box[0] / CELL)),
                        int(math.floor(box[2] / CELL)) + 1):
            for cy in range(int(math.floor(box[1] / CELL)),
                            int(math.floor(box[3] / CELL)) + 1):
                self.cells[(cx, cy)].append(i)

    def _near(self, rect):
        out = set()
        for cx in range(int(math.floor((rect[0] - 0.5) / CELL)),
                        int(math.floor((rect[2] + 0.5) / CELL)) + 1):
            for cy in range(int(math.floor((rect[1] - 0.5) / CELL)),
                            int(math.floor((rect[3] + 0.5) / CELL)) + 1):
                out.update(self.cells.get((cx, cy), ()))
        return out

    def _index_masks(self):
        for ref, fp in self.fps.items():
            for pad in fp.Pads():
                if not (pad.IsOnLayer(pcbnew.F_Mask) or
                        pad.IsOnLayer(pcbnew.F_Cu)):
                    continue
                b = pad.GetBoundingBox()
                r = (tomm(b.GetLeft()) - ORIGIN[0],
                     tomm(b.GetTop()) - ORIGIN[1],
                     tomm(b.GetRight()) - ORIGIN[0],
                     tomm(b.GetBottom()) - ORIGIN[1])
                self._add("mask", grow(r, MASK_MARGIN),
                          "%s.%s" % (ref, pad.GetNumber()),
                          grow(r, MASK_MARGIN))
                self.n_mask += 1

    def _line(self, a, b, hw, owner):
        self._add("line", (a, b, hw), owner,
                  (min(a[0], b[0]) - hw, min(a[1], b[1]) - hw,
                   max(a[0], b[0]) + hw, max(a[1], b[1]) + hw))
        self.n_line += 1

    def _add_shape(self, it, owner):
        hw = max(tomm(it.GetWidth()) / 2.0, 0.03)
        sh = it.GetShape()
        if sh == pcbnew.SHAPE_T_SEGMENT:
            self._line(loc(it.GetStart()), loc(it.GetEnd()), hw, owner)
        elif sh == pcbnew.SHAPE_T_RECT:
            a, b = loc(it.GetStart()), loc(it.GetEnd())
            c = ((a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1]))
            for i in range(4):
                self._line(c[i], c[(i + 1) % 4], hw, owner)
        elif sh == pcbnew.SHAPE_T_CIRCLE:
            ctr, rad = loc(it.GetCenter()), tomm(it.GetRadius())
            pts = [(ctr[0] + rad * math.cos(t * math.pi / 8),
                    ctr[1] + rad * math.sin(t * math.pi / 8))
                   for t in range(16)]
            for i in range(16):
                self._line(pts[i], pts[(i + 1) % 16], hw, owner)
        elif sh == pcbnew.SHAPE_T_ARC:
            a, m, b = loc(it.GetStart()), loc(it.GetArcMid()), loc(it.GetEnd())
            self._line(a, m, hw, owner)
            self._line(m, b, hw, owner)
        elif sh == pcbnew.SHAPE_T_POLY and it.IsPolyShapeValid():
            poly = it.GetPolyShape()
            for o in range(poly.OutlineCount()):
                out = poly.Outline(o)
                n = out.PointCount()
                pts = [(tomm(out.CPoint(i).x) - ORIGIN[0],
                        tomm(out.CPoint(i).y) - ORIGIN[1]) for i in range(n)]
                for i in range(n):
                    self._line(pts[i], pts[(i + 1) % n], hw, owner)
        else:
            # Bezier and anything new: fall back to its bounding box.
            c = rect_corners(item_box(it))
            for i in range(4):
                self._line(c[i], c[(i + 1) % 4], hw, owner)

    def _index_lines(self):
        for ref, fp in self.fps.items():
            for it in fp.GraphicalItems():
                if it.GetLayer() != pcbnew.F_SilkS:
                    continue
                if it.GetClass() == "PCB_SHAPE":
                    self._add_shape(it, ref)
        for d in self.board.GetDrawings():
            if d.GetLayer() == pcbnew.F_SilkS and d.GetClass() == "PCB_SHAPE":
                self._add_shape(d, "board")

    # ---------------------------------------------------------- the test --
    def free(self, rect, owner):
        """None when `rect` is a legal place for silk text, else the reason."""
        if not rect_in_board(rect, EDGE_CLR):
            return "board edge"
        for i in self._near(rect):
            kind, geo, who = self.obs[i]
            if kind == "mask":
                if rect_gap(rect, geo) <= PAD_CLR:
                    return "pad %s" % who
            elif kind == "line":
                a, b, hw = geo
                if seg_rect_dist(a, b, rect) <= hw + SILK_CLR:
                    return "silk line of %s" % who
            else:
                if rect_gap(rect, geo) <= SILK_CLR:
                    return "silk text %s" % who
        return None

    def claim_box(self, rect, owner):
        self._add("text", rect, owner, rect)

    # ------------------------------------------------------- ownership ----
    def index_bodies(self, boxes):
        """Body boxes, for the question DRC cannot ask: which part does this
        label look like it belongs to?"""
        self.bodies = boxes
        self.bcells = collections.defaultdict(list)
        for ref, b in boxes.items():
            for cx in range(int(math.floor(b[0] / CELL)),
                            int(math.floor(b[2] / CELL)) + 1):
                for cy in range(int(math.floor(b[1] / CELL)),
                                int(math.floor(b[3] / CELL)) + 1):
                    self.bcells[(cx, cy)].append(ref)

    def nearest_other(self, rect, ref, reach):
        """Gap to the nearest body box that is not `ref`, searching `reach`."""
        best, who = 1e9, None
        seen = set()
        r = grow(rect, reach)
        for cx in range(int(math.floor(r[0] / CELL)),
                        int(math.floor(r[2] / CELL)) + 1):
            for cy in range(int(math.floor(r[1] / CELL)),
                            int(math.floor(r[3] / CELL)) + 1):
                for other in self.bcells.get((cx, cy), ()):
                    if other == ref or other in seen:
                        continue
                    seen.add(other)
                    g = rect_gap(rect, self.bodies[other])
                    if g < best:
                        best, who = g, other
        return best, who

    def owns(self, rect, ref, slack=OWN_SLACK):
        """Is `rect` close enough to its own body to read as its label?"""
        own = rect_gap(rect, self.bodies[ref])
        if own <= slack:
            return True
        g, _ = self.nearest_other(rect, ref, own + 0.2)
        return g >= own - slack


# ====================================================== text and markers ==
def style_text(it, size, thick, rot):
    it.SetLayer(pcbnew.F_SilkS)
    it.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
    it.SetTextThickness(mm(thick))
    it.SetKeepUpright(False)
    it.SetMirrored(False)
    it.SetTextAngle(angle(rot))


def probe(it, pos, rot):
    """Put the text at (pos, rot) and hand back its real bounding box."""
    it.SetTextAngle(angle(rot))
    it.SetPosition(at(*pos))
    return item_box(it)


def new_text(board, txt, size, thick):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(txt)
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    style_text(t, size, thick, 0)
    return t


def triangle(p, point, s):
    """Filled pin-1 marker: an isoceles triangle with its tip at the pin."""
    h, w = s, s * 0.8
    if point == "N":
        return [(p[0], p[1] - h / 2), (p[0] - w / 2, p[1] + h / 2),
                (p[0] + w / 2, p[1] + h / 2)]
    if point == "S":
        return [(p[0], p[1] + h / 2), (p[0] - w / 2, p[1] - h / 2),
                (p[0] + w / 2, p[1] - h / 2)]
    if point == "W":
        return [(p[0] - h / 2, p[1]), (p[0] + h / 2, p[1] - w / 2),
                (p[0] + h / 2, p[1] + w / 2)]
    return [(p[0] + h / 2, p[1]), (p[0] - h / 2, p[1] - w / 2),
            (p[0] - h / 2, p[1] + w / 2)]


def add_poly(board, pts):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_POLY)
    s.SetLayer(pcbnew.F_SilkS)
    v = pcbnew.VECTOR_VECTOR2I()
    for p in pts:
        v.append(at(*p))
    s.SetPolyPoints(v)
    s.SetFilled(True)
    s.SetWidth(mm(0.05))
    board.Add(s)
    return s


# ======================================================== the ref search ==
def ring_pos(box, w, h, r, d):
    """Text-box centre `r` mm of air from body box `box`, in direction `d`."""
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    n, s = box[1] - r - h / 2.0, box[3] + r + h / 2.0
    e, wst = box[2] + r + w / 2.0, box[0] - r - w / 2.0
    return {"N": (cx, n), "S": (cx, s), "W": (wst, cy), "E": (e, cy),
            "NW": (wst, n), "NE": (e, n), "SW": (wst, s), "SE": (e, s)}[d]


def inside_pos(box, w, h):
    """Grid of centres that keep the text box inside the body box, nearest
    to the body centre first. The part's own outline is still an obstacle,
    so this only succeeds where the body really is empty."""
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    x0, y0 = box[0] + w / 2.0 + 0.1, box[1] + h / 2.0 + 0.1
    x1, y1 = box[2] - w / 2.0 - 0.1, box[3] - h / 2.0 - 0.1
    if x1 < x0 or y1 < y0:
        return []
    out = []
    nx = max(1, int((x1 - x0) / 0.25) + 1)
    ny = max(1, int((y1 - y0) / 0.25) + 1)
    for i in range(nx):
        for j in range(ny):
            p = (x0 + i * 0.25 if nx > 1 else (x0 + x1) / 2.0,
                 y0 + j * 0.25 if ny > 1 else (y0 + y1) / 2.0)
            out.append(p)
    out.sort(key=lambda p: (round(dist(p, (cx, cy)), 3), p[0], p[1]))
    return out


def grid_offsets(maxr, step):
    """Offsets on a `step` grid within `maxr`, nearest first, deterministic."""
    offs = []
    n = int(maxr / step)
    for j in range(-n, n + 1):
        for k in range(-n, n + 1):
            d = math.hypot(j * step, k * step)
            if d <= maxr:
                offs.append((round(d, 4), abs(k * step), k * step,
                             abs(j * step), j * step))
    offs.sort()
    return [(o[4], o[2]) for o in offs]


_FREE_OFFS = None


def free_offsets():
    global _FREE_OFFS
    if _FREE_OFFS is None:
        _FREE_OFFS = grid_offsets(FREE_R, 0.25)
    return _FREE_OFFS


def place_ref(silk, ref, fp, verbose=False):
    """Find a home for one reference designator.

    Returns (stage, gap, why): the stage that won, the air between the text
    box and the part's body box, and a complaint when the winner is not
    actually legal (only possible through REF_OVERRIDE).
    """
    it = fp.Reference()
    style_text(it, REF_SIZE, REF_THICK, 0)
    it.SetVisible(True)
    box = fab_bbox(fp)
    area = (box[2] - box[0]) * (box[3] - box[1])
    big = area >= BIG_AREA

    if ref in REF_OVERRIDE:
        dx, dy, rot = REF_OVERRIDE[ref]
        o = loc(fp.GetPosition())
        rect = probe(it, (o[0] + dx, o[1] + dy), rot)
        why = silk.free(rect, ref)
        silk.claim_box(rect, ref)
        return ("override", rect_gap(rect, box), why)

    wh = {}
    for rot in (0, 90):
        b = probe(it, (BOARD_W / 2.0, BOARD_H / 2.0), rot)
        wh[rot] = (b[2] - b[0], b[3] - b[1])

    tries = []
    if big:
        wide = (box[2] - box[0]) >= (box[3] - box[1])
        for rot in ((0, 90) if wide else (90, 0)):
            for p in inside_pos(box, wh[rot][0], wh[rot][1]):
                tries.append(("inside", p, rot))
    # Ring by ring outwards, and inside a ring above, below, the two sides
    # and then the corners - the brief's order.
    for ladder in (RING1, RING2):
        for r in ladder:
            for d in DIRS:
                for rot in ROT_PREF[d]:
                    w, h = wh[rot]
                    tries.append(("ring", ring_pos(box, w, h, r, d), rot))
    # Overflow: the eight ring directions are a ladder and a ladder misses
    # pockets that are not on an axis. Sweep a grid round the body centre
    # instead and take the nearest legal spot there. Where a whole row of
    # 0603s is this tight, what comes out is a line of references above or
    # below the row - the brief's "reference row".
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    for dx, dy in free_offsets():
        for rot in (0, 90):
            tries.append(("row", (cx + dx, cy + dy), rot))

    # First pass insists the label read as this part's: first legal wins.
    for stage, p, rot in tries:
        rect = probe(it, p, rot)
        if silk.free(rect, ref) is None and silk.owns(rect, ref):
            silk.claim_box(rect, ref)
            return (stage, rect_gap(rect, box), None)

    # Second pass drops that test, which only happens where the part is
    # boxed in on all sides. First legal is then the wrong answer: a label
    # 7 mm from its own 0603 and 0.2 mm from an op-amp reads as the op-amp's.
    # So collect the legal candidates at roughly the best distance available
    # and take the one with the most air round it instead.
    pool, own0 = [], None
    for i, (stage, p, rot) in enumerate(tries):
        rect = probe(it, p, rot)
        if silk.free(rect, ref) is not None:
            continue
        own = rect_gap(rect, box)
        if own0 is None:
            own0 = own
        if own > own0 + 1.5 or len(pool) >= 300:
            break
        other, _ = silk.nearest_other(rect, ref, own + 2.0)
        pool.append((-min(other, 2.0), round(own, 3), i, stage, p, rot))
    if pool:
        pool.sort()
        _, own, _, stage, p, rot = pool[0]
        rect = probe(it, p, rot)
        silk.claim_box(rect, ref)
        return (stage + "-loose", rect_gap(rect, box), None)
    # Nothing legal anywhere: leave it where the last probe put it and say so.
    rect = probe(it, ring_pos(box, wh[0][0], wh[0][1], 0.5, "N"), 0)
    silk.claim_box(rect, ref)
    return ("stuck", rect_gap(rect, box), "no legal position within %.1f mm"
            % FREE_R)


def place_free_text(silk, board, txt, size, thick, seed, rot, owner,
                    maxr=4.0, step=0.10):
    """Put a board-level text as near `seed` as a legal spot allows."""
    t = new_text(board, txt, size, thick)
    board.Add(t)
    for dx, dy in grid_offsets(maxr, step):
        rect = probe(t, (seed[0] + dx, seed[1] + dy), rot)
        if silk.free(rect, owner) is None:
            silk.claim_box(rect, owner)
            silk.made.append(t)
            return t, (seed[0] + dx, seed[1] + dy), math.hypot(dx, dy)
    rect = probe(t, seed, rot)
    why = silk.free(rect, owner)
    board.Remove(t)
    _DETACHED.append(t)
    return None, None, why


def place_marker(silk, board, seed, point, owner, maxr=3.0, step=0.10):
    for dx, dy in grid_offsets(maxr, step):
        p = (seed[0] + dx, seed[1] + dy)
        pts = triangle(p, point, MARK_SIZE)
        rect = (min(q[0] for q in pts), min(q[1] for q in pts),
                max(q[0] for q in pts), max(q[1] for q in pts))
        if silk.free(grow(rect, 0.02), owner) is None:
            s = add_poly(board, pts)
            silk.claim_box(rect, owner)
            silk.made.append(s)
            return p, math.hypot(dx, dy)
    return None, None


# ============================================================ bookkeeping ==
def strip_previous(board):
    """Remove everything a previous run of this script created."""
    grp = None
    for g in board.Groups():
        if g.GetName() == SILK_GROUP:
            grp = g
            break
    if grp is None:
        return 0
    # Take the group off the board FIRST; RemoveAll() hands its members back
    # to C++ ownership and the subsequent board.Remove() then crashes.
    items = list(grp.GetItems())
    board.Remove(grp)
    for it in items:
        board.Remove(it)
    # board.Remove() detaches without deleting, and letting the SWIG proxies
    # of the detached items be garbage collected segfaults KiCad 10 - keep
    # them alive for the rest of the process instead.
    _DETACHED.extend(items)
    _DETACHED.append(grp)
    return len(items)


def make_group(board, items):
    g = pcbnew.PCB_GROUP(board)
    g.SetName(SILK_GROUP)
    board.Add(g)
    for it in items:
        g.AddItem(it)
    return g


def copper_census(board):
    trk = via = 0
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            via += 1
        else:
            trk += 1
    return trk, via, len(list(board.Zones()))


def run_drc(tag):
    out = os.path.join(OUT, "drc-silk-%s.json" % tag)
    os.makedirs(OUT, exist_ok=True)
    subprocess.run(["kicad-cli", "pcb", "drc", "--schematic-parity",
                    "--severity-all", "--format", "json", "-o", out, PCB],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    d = json.load(open(out))
    v = d.get("violations", [])
    return dict(
        errors=len([x for x in v if x["severity"] == "error"]),
        warnings=len([x for x in v if x["severity"] != "error"]),
        unconnected=len(d.get("unconnected_items") or []),
        parity=len(d.get("schematic_parity") or []),
        by_type=collections.Counter(x["type"] for x in v),
        violations=v)


def drc_line(tag, d):
    print("  %-7s errors %d  parity %d  unconnected %d  warnings %d  %s"
          % (tag, d["errors"], d["parity"], d["unconnected"], d["warnings"],
             dict(sorted(d["by_type"].items()))))


# =============================================================== main =====
def main():
    t_drc = "--no-drc" not in sys.argv
    verbose = "--verbose" in sys.argv

    pro_before = None
    if os.path.exists(PRO):
        with open(PRO, "rb") as fh:
            pro_before = fh.read()

    before = run_drc("before") if t_drc else None

    board = pcbnew.LoadBoard(PCB)
    cu_before = copper_census(board)
    gone = strip_previous(board)
    print("scripted silk: removed %d item(s) from a previous run" % gone)

    # ---- 1. the board outline ------------------------------------------
    clip_footprint_silk(board, verbose)

    # ---- 2. every reference to the ADR minimum, mounting holes off -----
    fps = collections.OrderedDict(
        (f.GetReference(), f)
        for f in sorted(board.GetFootprints(), key=lambda f: f.GetReference()))
    for ref in NO_SILK_REF:
        if ref in fps:
            fps[ref].Reference().SetVisible(False)
    print("references: %d on F.Silkscreen at %.1f / %.2f mm, %d hidden (%s)"
          % (len(fps) - len(NO_SILK_REF), REF_SIZE, REF_THICK,
             len(NO_SILK_REF), ", ".join(NO_SILK_REF)))

    silk = Silk(board)
    print("obstacles: %d mask openings, %d silk graphic segments"
          % (silk.n_mask, silk.n_line))

    # ---- 3. the labels claim their space first -------------------------
    print("\n--- rear-edge connector labels")
    for ref, txt, seed, size in REAR_LABELS:
        t, p, moved = place_free_text(silk, board, txt, size, LABEL_THICK,
                                      seed, 0, ref, maxr=5.0)
        if t is None:
            print("  %-6s %-11r COULD NOT PLACE near (%.2f, %.2f) - the seed "
                  "itself hits %s" % (ref, txt, seed[0], seed[1], moved))
        else:
            print("  %-6s %-11r at (%.2f, %.2f)  %.1f mm text, moved %.2f mm "
                  "off the seed" % (ref, txt, p[0], p[1], size, moved))

    print("\n--- pin-1 markers")
    for ref, pad, seed, point in PIN1_MARKS:
        p, moved = place_marker(silk, board, seed, point, ref)
        if p is None:
            print("  %-6s pin %-2s COULD NOT PLACE near (%.2f, %.2f)"
                  % (ref, pad, seed[0], seed[1]))
        else:
            print("  %-6s pin %-2s triangle at (%.2f, %.2f) pointing %s, "
                  "moved %.2f mm" % (ref, pad, p[0], p[1], point, moved))

    print("\n--- pin legends")
    for ref, pad, txt, off, rot, size in PIN_LEGEND:
        fp = fps.get(ref)
        if fp is None:
            continue
        pd = fp.FindPadByNumber(pad)
        c = loc(pd.GetPosition())
        seed = (c[0] + off[0], c[1] + off[1])
        t, p, moved = place_free_text(silk, board, txt, size, PIN_THICK,
                                      seed, rot, "%s.%s" % (ref, pad),
                                      maxr=3.0)
        if t is None:
            print("  %-6s pin %-2s %-7r NO ROOM near (%.2f, %.2f) - the seed "
                  "hits %s" % (ref, pad, txt, seed[0], seed[1], moved))
        else:
            print("  %-6s pin %-2s %-7r at (%.2f, %.2f) rot %d, moved %.2f mm"
                  % (ref, pad, txt, p[0], p[1], rot, moved))

    print("\n--- board title")
    for txt, seed, size, thick in TITLE:
        t, p, moved = place_free_text(silk, board, txt, size, thick, seed, 0,
                                      "title", maxr=6.0)
        if t is None:
            print("  %-18r COULD NOT PLACE near (%.2f, %.2f) - the seed hits "
                  "%s" % (txt, seed[0], seed[1], moved))
        else:
            print("  %-18r at (%.2f, %.2f), moved %.2f mm"
                  % (txt, p[0], p[1], moved))

    # ---- 4. the references ---------------------------------------------
    # Big bodies first: they are the ones that can carry their reference
    # inside their own outline, and a 0603 label can always be nudged round
    # a connector's while the reverse is not true. Then the small parts in
    # order of how crowded their own neighbourhood is - the tightest gets
    # first pick, because a part with room to spare still has room after
    # its neighbour has taken the one lane that was left.
    def rank(kv):
        box = fab_bbox(kv[1])
        area = (box[2] - box[0]) * (box[3] - box[1])
        if area >= BIG_AREA:
            return (0, -area, 0, kv[0])
        return (1, 0, -len(silk._near(grow(box, 2.0))), kv[0])
    order = sorted(fps.items(), key=rank)
    silk.index_bodies(dict((r, fab_bbox(f)) for r, f in fps.items()
                           if r not in NO_SILK_REF))
    stats = collections.Counter()
    rows, stuck, illegal, far = [], [], [], []
    for ref, fp in order:
        if ref in NO_SILK_REF:
            stats["hidden"] += 1
            continue
        stage, gap, why = place_ref(silk, ref, fp, verbose)
        if stage.endswith("-loose"):
            stats["loose"] += 1
            stage = stage[:-6]
        if stage == "inside":
            stats["inside"] += 1
        elif stage == "stuck":
            stats["stuck"] += 1
            stuck.append(ref)
        elif stage == "override":
            stats["override"] += 1
        elif gap <= 1.5 + 1e-6:
            stats["ring1"] += 1
        elif gap <= 3.0 + 1e-6:
            stats["ring2"] += 1
            far.append((ref, gap))
        else:
            stats["row"] += 1
            rows.append((ref, gap))
        if why is not None and stage == "override":
            illegal.append((ref, why))
        if verbose:
            b = item_box(fp.Reference())
            print("  %-6s %-7s gap=%.2f  box (%.2f, %.2f)-(%.2f, %.2f)"
                  % (ref, stage, gap, b[0], b[1], b[2], b[3]))

    print("\n--- reference designators (%d placed, %d hidden)"
          % (sum(stats[k] for k in ("inside", "ring1", "ring2", "row",
                                    "override", "stuck")), stats["hidden"]))
    print("  inside own body outline : %d" % stats["inside"])
    print("  ring 1  (<= 1.5 mm air) : %d" % stats["ring1"])
    print("  ring 2  (<= 3.0 mm air) : %d%s"
          % (stats["ring2"], ("  " + ", ".join("%s %.2f" % t for t in far))
             if far else ""))
    print("  reference row (> 3 mm)  : %d%s"
          % (stats["row"], ("  " + ", ".join("%s %.2f" % t for t in rows))
             if rows else ""))
    print("  boxed in, own-part test relaxed : %d" % stats["loose"])
    print("  nudged by REF_OVERRIDE  : %d" % stats["override"])
    print("  no legal position       : %d%s"
          % (stats["stuck"], ("  " + ", ".join(stuck)) if stuck else ""))
    print("  silk label dropped      : %d (%s)"
          % (stats["hidden"], ", ".join(NO_SILK_REF)))
    for ref, why in illegal:
        print("  OVERRIDE %s is not legal: %s" % (ref, why))

    # DRC says nothing about which part a legal label belongs to. A label
    # that sits nearer someone else's body than its own reads as that other
    # part's, which is worse than a label 4 mm out in clear space, so it is
    # checked and printed.
    bodies = [(r, fab_bbox(f)) for r, f in fps.items() if r not in NO_SILK_REF]
    wrong = []
    for ref, fp in fps.items():
        if ref in NO_SILK_REF:
            continue
        tb = item_box(fp.Reference())
        own = rect_gap(tb, dict(bodies)[ref])
        near = [(rect_gap(tb, b), r) for r, b in bodies if r != ref]
        near.sort()
        if near and near[0][0] < own - 1e-6:
            wrong.append((ref, own, near[0][1], near[0][0]))
    print("  labels nearer another body than their own: %d" % len(wrong))
    for ref, own, other, d in sorted(wrong, key=lambda t: -(t[1] - t[3])):
        print("    %-6s %.2f mm from itself, %.2f mm from %s"
              % (ref, own, d, other))

    # ---- 5. group, lock, save ------------------------------------------
    make_group(board, silk.made)
    for it in silk.made:
        it.SetLocked(True)
    ntxt = len([i for i in silk.made if isinstance(i, pcbnew.PCB_TEXT)])
    nshp = len(silk.made) - ntxt
    print("\nscripted, locked and grouped as %r: %d texts, %d markers"
          % (SILK_GROUP, ntxt, nshp))

    cu_after = copper_census(board)
    pcbnew.SaveBoard(PCB, board)
    print("wrote %s" % PCB)

    if pro_before is not None:
        with open(PRO, "rb") as fh:
            same = fh.read() == pro_before
        if not same:
            with open(PRO, "wb") as w:
                w.write(pro_before)
            print("restored %s (SaveBoard had rewritten it)"
                  % os.path.basename(PRO))
        else:
            print("%s unchanged" % os.path.basename(PRO))

    print("\n--- copper census (must not move)")
    print("  before  %d tracks, %d vias, %d zones" % cu_before)
    print("  after   %d tracks, %d vias, %d zones" % cu_after)
    cu_ok = cu_before == cu_after
    print("  %s" % ("unchanged" if cu_ok else "COPPER CHANGED - BUG"))

    rc = 0 if cu_ok else 1
    if t_drc:
        after = run_drc("after")
        print("\n--- kicad-cli DRC (--schematic-parity --severity-all)")
        drc_line("before", before)
        drc_line("after", after)
        print("\n  %-22s %8s %8s" % ("type", "before", "after"))
        keys = sorted(set(before["by_type"]) | set(after["by_type"]))
        for k in keys:
            print("  %-22s %8d %8d"
                  % (k, before["by_type"].get(k, 0), after["by_type"].get(k, 0)))
        for k in ("silk_overlap", "silk_over_copper", "silk_edge_clearance"):
            if after["by_type"].get(k, 0):
                rc = 1
                print("\n  %s is not zero - remaining:" % k)
                for x in after["violations"]:
                    if x["type"] != k:
                        continue
                    print("    " + " | ".join(
                        i.get("description", "") for i in (x.get("items") or [])))
        if after["errors"] or after["parity"]:
            rc = 1
        if after["unconnected"] != before["unconnected"]:
            rc = 1
            print("\n  unconnected count moved %d -> %d - BUG"
                  % (before["unconnected"], after["unconnected"]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
