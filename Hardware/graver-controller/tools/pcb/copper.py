#!/usr/bin/env python3
"""Draw the scripted, locked critical copper on graver-controller.kicad_pcb.

Runs AFTER place.py (or as `place.py --copper`, which calls it). Idempotent:
everything it creates goes into a PCB group named SCRIPTED_GROUP, and the
first thing a run does is delete that group's members, so re-running replaces
the copper instead of stacking it.

Everything it creates is LOCKED, which is what keeps the KiCadRoutingTools
autorouter off it (the tool refuses to rip KiCad-locked copper).

Order, per ADR 0003 decision 8:

  1. GND pour on B.Cu, M3 ground-free rule areas, crystal keepout, User.2
     copies of the keepouts for the router's --keepout
  2. QFN fanout for U301: radial stubs, GND pins into the EP, EP vias
  3. decoupling: pin -> cap on top
  4. crystal: OSC_IN / OSC_OUT on F.Cu only, load caps, F.Cu ground guard
  5. VDDA / VSSA chain FB301 -> C306/C307 -> pin 9
  6. USB: J301 -> U302 -> MCU as a coupled pair on F.Cu, 0 vias anywhere
  7. power: VIN chain, flyback loop, shunt Kelvin, gate, buck, +5V, +3V3
  8. the RC filters at the MCU's analog pins

and LAST, step 3b, the ground stitching - every top-side GND pad's own stub
and via, a via row with an F.Cu rib along the two long edges, and a spine
tying GND's F.Cu pieces to each other. It runs last because its stubs would
otherwise close escapes a signal needed, and the point of it is that GND
comes out CLOSED: kicad-cli reports 0 GND pad pairs afterwards, so GND is not
in the net list autoroute.py hands the router at all.

Geometry is computed from real pad positions and drawn as octilinear
segments. Every candidate path is clearance-checked against every pad, every
piece of copper already drawn, the board edge and the keepouts BEFORE it is
committed, at the pairwise net-class clearance; a path that cannot be made to
clear is reported, not drawn.

Widths come from the committed graver-controller.kicad_dru, not from a table
here: `net_floors()` reads the per-class `track_width (min ...)` rules and
`width_floor_table` checks every scripted segment against the floor for its
net, so a Power tap at 0.25 mm or a HighCurrent Kelvin tap at 0.20 mm fails
the run instead of turning up as a DRC error after the router has gone.

Usage:  python3 tools/pcb/copper.py [--no-drc] [--no-refill] [--verbose]
"""

import collections
import json
import math
import os
import re
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
DRU = os.path.join(PROJ, NAME + ".kicad_dru")
OUT = os.path.join(PROJ, "output", "pcb")

ORIGIN = (50.0, 50.0)          # must match place.py
BOARD_W, BOARD_H = 110.0, 70.0
EDGE_KEEP = 0.35               # copper to board edge (rule is 0.3)

SCRIPTED_GROUP = "scripted-copper"

# ------------------------------------------------------------- rules -------
# Net-class clearance, from the committed .kicad_pro. Pairwise max, as KiCad
# resolves it. Everything not named here is Default.
CLEARANCE_DEFAULT = 0.15
NET_CLEARANCE = {
    "+3V3": 0.2, "+5V": 0.2, "VBUS": 0.2, "/MCU/VDDA": 0.2,
    "VIN": 0.4, "/Driver/COIL_NEG": 0.4, "/Driver/CLAMP": 0.4,
    "/Driver/SHUNT_HI": 0.4,
}
MAX_CLEARANCE = max([CLEARANCE_DEFAULT] + list(NET_CLEARANCE.values()))
VIA_D, VIA_DRILL = 0.6, 0.3
HOLE_TO_HOLE = 0.5
HOLE_CLEARANCE = 0.25
ZONE_CLEARANCE = 0.25
ZONE_MIN_WIDTH = 0.2

W_SIG = 0.25          # general signal
W_FINE = 0.2          # at the 0.5 mm pitch parts
W_VDDA = 0.4
W_RAIL = 0.5          # +3V3 / +5V distribution
W_POWER = 1.0         # VIN and the flyback loop
W_GUARD = 0.3         # crystal ground guard


# ------------------------------------------------- the .kicad_dru floors ---
# ADR 0003 decision 5: a net class's track width is KiCad's DEFAULT for new
# copper, not a limit, so graver-controller.kicad_dru carries one
# `track_width (min ...)` rule per class and DRC fails a power net drawn at the
# signal width. The numbers are READ out of the two committed files rather than
# repeated here: a floor that has drifted from the rule it is meant to satisfy
# is worse than no floor at all, and this is the only reason a 0.25 mm rail tap
# or a 0.20 mm Kelvin tap is not a legal piece of copper on this board.
def class_floors():
    """net class -> minimum track width in mm, from the committed .kicad_dru."""
    try:
        with open(DRU) as fh:
            txt = fh.read()
    except OSError:
        return {}
    out = {}
    for blk in re.split(r"(?=\(rule\b)", txt):
        cls = re.search(r"A\.NetClass\s*==\s*'([^']+)'", blk)
        w = re.search(r"\(constraint\s+track_width\s+\(min\s+([0-9.]+)\s*mm\)",
                      blk)
        if cls and w:
            out[cls.group(1)] = max(out.get(cls.group(1), 0.0),
                                    float(w.group(1)))
    return out


def net_floors():
    """net name -> the minimum track width DRC enforces on it."""
    floors = class_floors()
    try:
        with open(PRO) as fh:
            pro = json.load(fh)
    except OSError:
        return {}
    out = {}
    for p in pro["net_settings"].get("netclass_patterns") or []:
        w = floors.get(p["netclass"])
        if w:
            out[p["pattern"]] = w
    return out


W_FLOOR = net_floors()
# The two ladder floors the tables below use, named so a change to the
# .kicad_dru shows up as a changed number here and not as a DRC error.
W_RAIL_MIN = W_FLOOR.get("+3V3", 0.3)         # Power class
W_HC_MIN = W_FLOOR.get("VIN", 0.5)            # HighCurrent class

# ------------------------------------------------------- GND stitching -----
# Every top-side GND pad that is not already tied gets a short fat stub of its
# own and a via into the pour, so that GND is CLOSED by this script and the
# router never sees it as a net at all. Widest first, shortest first: a 0.40 mm
# stub 0.85 mm long is the tie a decoupling cap wants, and the narrower and
# longer rungs only exist so that a pad in a corridor gets a tie rather than
# nothing. Everything past STITCH_MAX is reported as a long tie.
STITCH_W = (0.4, 0.3, 0.25)
STITCH_LEN = (0.85, 1.0, 1.2, 1.5, 1.8, 2.2, 2.6)
STITCH_MAX = 1.5              # the brief's length; longer ties are reported
# A via row along the two long edges, to tie the pour. VIA_EDGE_IN is the via
# centre's distance from the outline, which is EDGE_KEEP + the via radius plus
# a little; the ribs are what stop every one of them being a dangling via.
EDGE_STITCH_PITCH = 10.0
EDGE_STITCH_IN = 1.2
EDGE_STITCH_RIB = 0.3
# Every stitching stub is its own little piece of copper ON TOP, joined to its
# neighbours only through the pour - and the ROUTER's B.Cu copper dices the
# pour. 2.00 mm, measured: it is what the crystal corner needs (C304.2's stub
# to C301.2's is 1.40 mm and C301.2's to the ground guard is 1.48 mm) and it
# touches 23 of the 63 pieces, where 3.50 mm would touch 46. See
# "GND is closed by the script" in the README.
#
# Each sweep is (cap, lone stubs only, may enter the QFN annulus). The THIRD
# one is the sixth pass's targeted fix and it is deliberately the last resort:
# after the first two, two stubs were still pieces of their own - C309.2, whose
# hop to the crystal ground guard is 2.02 mm (0.02 mm over the first cap, and
# then inside the annulus the second one will not enter) and C205.2, whose
# nearest piece is 2.90 mm (0.40 mm over the second cap). Both came back as
# open GND pad pairs once the router had diced the pour under them. A stub that
# is STILL lone after both sweeps is the one case where a long hop through the
# annulus is worth more than the escape lane it costs: there is nothing else
# holding it to the rest of GND. It only ever fires on a piece the other two
# could not reach, so it cannot draw the 14 long hops a bigger cap on sweep 2
# would (see below).
GND_SPINE_MAX = ((2.0, False, False), (2.5, True, False), (3.0, True, True))
GND_SPINE_W = (0.3, 0.25, 0.2)
# The second sweep is for the pieces the first one could not reach at all: a
# LONE stub, under this much copper of its own, may take a slightly longer
# hop, because a lone stub is the whole population at risk - a big piece
# already holds several vias in several pour islands.
#
# 2.50 and not 4.50, measured. At 4.50 the sweep draws 14 long hops and
# 62.59 mm of extra GND copper, two of them diagonals across the USB corner
# at y 8..12 and two more through the clamp corner - that is a bigger
# perturbation of the router's corridors than the thing it buys, and it buys
# almost nothing: what actually closed the crystal corner is a SHORT
# L-shaped hop, C301.2's stub to the ground guard, 1.57 mm of copper for a
# 1.48 mm straight line. The straight line itself does not clear - C301's own
# +3V3 pad sits 0.24 mm off it where 0.30 is needed - which is why the hop
# candidates are octilinear and not just a chord.
#
# C304.2's stub stays a lone piece whatever the cap: everything south of it
# has to cross LED_STAT's channel lane and everything north is inside the
# QFN's escape annulus. It keeps its own via and is the one GND tie on this
# board whose connection still depends on the pour island under it.
GND_SPINE_LONE = 3.0
# No long hop inside the QFN's escape annulus. The second ring ends about
# 2.9 mm out of a 3.5 mm pad row, so 6.5 mm from the part centre is the first
# radius at which a GND link is not competing with an escape.
GND_SPINE_KEEP_R = 6.5
GND_SPINE_SLACK = 1.6        # copper to straight line, as in rail_tree

# --------------------------------------------------------- mechanical ------
M3 = 4.0
HOLES = {"MH401": (M3, M3), "MH402": (BOARD_W - M3, M3),
         "MH403": (BOARD_W - M3, BOARD_H - M3), "MH404": (M3, BOARD_H - M3)}
M3_COPPER_FREE_D = 6.0        # ADR: 6 mm diameter ground-free keepout
M3_COPPER_FREE_R = M3_COPPER_FREE_D / 2.0

# ------------------------------------------------------------ crystal ------
XTAL_PARTS = ("Y301", "C310", "C311")
XTAL_MARGIN = 0.3             # keepout margin around the island's pads
GUARD_MARGIN = 0.75           # ground guard, outside the keepout so its
                              # stitching vias are legal
# THIRD PASS. place.py now puts the island in the CORNER at the low pin
# numbers, so the geometry here is derived from the real pads instead of the
# hand-measured constants the second-pass island needed:
#
#   - the channel between the QFN's pin-row copper and the island's keepout is
#     about 1.0 mm, which is two 0.20 mm lanes at 0.15 mm instead of the old
#     one. The inner lane carries the pad that the island shadows (LED_STAT on
#     pad 2), the outer one carries OSC_IN across to the crystal's XIN pad.
#   - OSC_OUT does not use the channel at all: the crystal at rotation 270 has
#     XOUT on its south-east pad, so OSC_OUT leaves pad 6 straight out and
#     turns once, 0.20 mm clear of the crystal's north-east GND pad.
#   - VDDA no longer needs the channel either (step 5): pad 9 is now east of
#     the island and its 1 uF sits right at it.
# 0.21 mm, not the Default class's 0.15: pads 1 and 9 on this row are +3V3 and
# VDDA, both 0.20 mm classes, so a lane that clears the row by 0.15 clears
# nothing. 0.21 still leaves 0.25 mm of slack to the keepout.
LANE_GAP = 0.21               # air between the two channel lanes and to the
                              # pin-row copper
GUARD_BACK = 1.0              # how far the guard bracket's open ends reach
                              # back towards the MCU past the island's pads

# ---------------------------------------------------------- QFN fanout -----
QFN = "U301"
QFN_EP = "49"
QFN_STUB = 1.15               # stub end, mm from the pad centre (pad is 0.44)
QFN_EP_VIAS = ((-1.4, -1.4), (1.4, -1.4), (-1.4, 1.4), (1.4, 1.4))
# GND perimeter pins tie into the EP copper instead of taking a via of their
# own: at 0.5 mm pitch no 0.6 mm via fits in the first ring, and the EP is
# 0.2 mm away from the pin row.
QFN_GND_PINS = ("8", "23", "35", "47")
# Which pads get no radial stub is no longer a constant: step 2b works out
# which pin-row pads the crystal island stands in front of and draws their
# escapes, and step 2 skips exactly those. In the second pass this was the
# hand-written list ("11", "12") plus pad 7 failing silently.
# --- the escape fan ---------------------------------------------------------
# A via that sits in the FIRST ring is zero-sum and worse than that: at 0.5 mm
# pitch a 0.6 mm via 1.55 mm out of its pad denies BOTH its neighbours any
# radial escape past about 1.15 mm, because a 0.20 mm track 0.5 mm to the side
# clears it by 0.50 mm where it needs 0.55. That is exactly what boxed NTC in
# (pad 19, between the fanout vias of 18 and 20) and ENC_SW (pad 43, between
# 42 and 44), and the router reported both `boxed_in_static` against copper
# this script had already locked.
#
# So the rows that carry more signals than the first ring has lanes are FANNED
# instead: each escape leaves its pad radially, turns 45 degrees at QFN_FAN_R
# and lands on a lane of its own in a second, WIDER ring, where the pitch is
# 0.70 mm (east) or 0.90 mm (west) instead of 0.50. A 0.6 mm via then clears a
# neighbouring lane's 0.20 mm track by 0.15 mm at 0.70 mm pitch, two vias on
# lanes 1.4 mm apart clear each other's holes by 0.6 mm, and every used pad
# keeps a straight top-layer lane of its own out to the second ring.
#
# `fan` is the lateral step in mm, signed +y for a row whose pads face east or
# west and +x for one facing north or south. The entries of one row must be
# MONOTONIC in the lane they start from, or two escapes cross. `reach` is
# where the escape ends, from the pad centre; `via` drops a via there.
#
# Where the free lanes come from: pads 3, 4, 10, 13, 14, 26, 30, 38, 39, 45
# and 46 are unconnected on this design and get no copper at all, so their
# lanes are the room the fan expands into. The east row fans towards pads 13
# and 14, the west row towards 38/39 one way and 45/46 the other. The west
# row stops at y = 45.75 and not 46.25: C304, pad 48's own 100 nF, sits on
# that lane.
QFN_FAN_R = 1.35              # radius at which the 45-degree turn starts
QFN_ESCAPE = {
    # east row, faces +x, 0.70 mm lane pitch
    "21": (0.00, 2.60, False),    # LCD_DC
    "20": (0.20, 2.90, True),     # Net-(U301-PB2)
    "19": (0.40, 2.60, False),    # NTC        - the pad the old vias boxed in
    "18": (0.60, 2.90, True),     # VIN_SENSE
    "17": (0.80, 2.60, False),    # LCD_MOSI
    "16": (1.00, 2.60, False),    # I_SENSE
    "15": (1.20, 2.90, False),    # LCD_SCK
    # west row, faces -x, 0.90 mm lane pitch
    "40": (-0.60, 2.60, False),   # ENC_A
    "41": (-0.20, 2.60, False),   # ENC_B      - jammed behind 42's old via
    "42": (0.20, 2.90, True),     # LCD_BL
    "43": (0.60, 2.60, False),    # ENC_SW     - the pad 42 and 44 boxed in
    "44": (1.00, 2.90, True),     # Net-(U301-BOOT0)
}
QFN_VIA_PADS = tuple(n for n, (_f, _r, v) in QFN_ESCAPE.items() if v)
# Fallback reaches, tried shortest-first when the tabulated one does not clear.
QFN_REACH_BACK = (0.30, 0.60, 0.90, 1.20)

# Pads whose destination is a first-ring part ON TOP: no via, a real trace.
# (mcu pad, target pad, width) - the router never sees these nets near the QFN.
FIRST_RING = [
    # Pad 1 is VBAT and its 100 nF sits round the corner with pad 48's, so
    # there is no first-ring trace for it: step 2's shadow escape jumpers pad
    # 1 to pad 48 instead, and +3V3 carries on from there.
    # The three VDD pads are W_RAIL_MIN and not W_SIG: they are +3V3, which is
    # in the Power class, and the .kicad_dru holds it to 0.30 mm at a 0.5 mm
    # pitch pad as much as anywhere else. 0.30 mm leaves 0.375 - 0.35 =
    # 0.025 mm to the GND pad next door, so it is drawable but only just; a pad
    # whose trace does not clear keeps its plain radial stub and its cap goes
    # back to the router.
    ("24", "C302.1", W_RAIL_MIN),
    ("36", "C303.1", W_RAIL_MIN),
    ("48", "C304.1", W_RAIL_MIN),
    # ("22", "C308.1") was here and never came out: C308 is 7.79 mm away in
    # the SECOND ring and the two-segment search has to thread the C302 / C104
    # row on the way. It is an explicit path now, see SIGNAL_EXPLICIT.
    ("7", "C309.1", W_SIG),          # NRST
]

# Pads whose escape is an explicit path in SIGNAL_EXPLICIT (step 6c), so step 2
# must not also give them a radial stub the path would then run along. Step 6c
# falls back to the plain stub if its path cannot be drawn, so a pad here is
# never left bare.
QFN_EXPLICIT_PADS = ("22", "29")

# Pads that get a fanout stub only; the router picks them up at the stub end.
# Everything connected and not in FIRST_RING / QFN_GND_PINS / the crystal /
# USB lands here automatically.

# ------------------------------------------------------------- USB ---------
# HRO TYPE-C-31-M-12, reversible: A6 and B6 are both D+, A7 and B7 both D-.
# Pad x at y=7.245:  B6 28.25 | A7 28.75 | A6 29.25 | B7 29.75
# The run leaves from B6 (D+) and A7 (D-): adjacent, and D+ on the low-x side,
# which is the order U302 (rotated 180 by place.py) and the MCU both want, so
# the pair never swaps sides. Both duplicates then sit EAST of the run, and
# that is what makes bridging them via-free possible: the D+ bridge (B6 <-> A6)
# crosses the run in FRONT of the pad row, where A7 has no copper, and the D-
# bridge (B7 <-> A7) crosses it BEHIND, where A6 has none. Take the run from
# A7/A6 instead - the other adjacent pair - and both bridges have to cross
# behind, which four interleaved contacts on one row cannot do in one plane;
# that costs 2 vias and ~4 mm of B.Cu under the connector.
USB_DP, USB_DM = "/MCU/USB_DP", "/MCU/USB_DM"
USB_W, USB_GAP = 0.2, 0.15
USB_PITCH = USB_W + USB_GAP     # 0.35 centre to centre
USB_KEEP = 0.15                 # User.2 band off the pair's centre line

# ---------------------------------------------------------- explicit paths -
# (label, net, layer, width, [waypoints]) - a waypoint is "REF.PAD" or (x, y).
# Consecutive points must be H, V or exactly 45 degrees apart; the builder
# checks and says so if they are not.
def _P(label, net, width, pts, layer="F.Cu"):
    return dict(label=label, net=net, width=width, pts=pts, layer=layer)


# ============================================================ helpers ======
def mm(v):
    return pcbnew.FromMM(v)


def tomm(v):
    return pcbnew.ToMM(v)


def at(x, y):
    return pcbnew.VECTOR2I(mm(ORIGIN[0] + x), mm(ORIGIN[1] + y))


def loc(pos):
    return (tomm(pos.x) - ORIGIN[0], tomm(pos.y) - ORIGIN[1])


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
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    # inside?
    for p in (a, b):
        if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
            return 0.0
    best = 1e9
    for i in range(4):
        best = min(best, seg_seg_dist(a, b, corners[i], corners[(i + 1) % 4]))
        if best == 0.0:
            return 0.0
    return best


def point_rect_dist(p, r):
    x0, y0, x1, y1 = r
    dx = max(x0 - p[0], 0.0, p[0] - x1)
    dy = max(y0 - p[1], 0.0, p[1] - y1)
    return math.hypot(dx, dy)


def clearance(na, nb):
    if na == nb:
        return 0.0
    return max(NET_CLEARANCE.get(na, CLEARANCE_DEFAULT),
               NET_CLEARANCE.get(nb, CLEARANCE_DEFAULT))


def octilinear(a, b):
    """Is a-b horizontal, vertical or exactly 45 degrees?"""
    dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
    return dx < 1e-6 or dy < 1e-6 or abs(dx - dy) < 1e-6


def oct_route(a, b, mode):
    """Two-segment octilinear path from a to b. Modes:
       'dh'  diagonal then horizontal    'dv'  diagonal then vertical
       'hd'  horizontal then diagonal    'vd'  vertical then diagonal
       'hv'  horizontal then vertical    'vh'  vertical then horizontal
    Returns [a, mid, b] or [a, b] when one segment is enough.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    if octilinear(a, b):
        return [a, b]
    sx = 1.0 if dx > 0 else -1.0
    sy = 1.0 if dy > 0 else -1.0
    m = min(abs(dx), abs(dy))
    if mode == "dh":
        mid = (a[0] + sx * m, a[1] + sy * m)
    elif mode == "dv":
        mid = (a[0] + sx * m, a[1] + sy * m)
    elif mode == "hd":
        mid = (b[0] - sx * m, a[1])
    elif mode == "vd":
        mid = (a[0], b[1] - sy * m)
    elif mode == "hv":
        mid = (b[0], a[1])
    elif mode == "vh":
        mid = (a[0], b[1])
    else:
        raise ValueError(mode)
    return [a, mid, b]


OCT_MODES = ("dh", "hd", "vd", "hv", "vh")


def all_octilinear(pts):
    """Is every leg of this path H, V or exactly 45 degrees?

    `oct_route`'s 'hd' and 'vd' modes only come out at 45 degrees when the
    axis they run along is the LONGER one - 'hd' from (49.0, 34.2) to
    (42.0, 12.4) ends on a 7 x 21.8 slant. Those candidates are kept, because
    on a crowded board a slant that clears beats nothing at all, but they sort
    behind every octilinear candidate so they are only ever a last resort.
    `add_path` still says so in the notes when one is drawn.
    """
    return all(octilinear(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def path_len(pts):
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


# =============================================================== model ====
class Copper:
    """Everything the script draws, with the clearance model behind it."""

    def __init__(self, board):
        self.board = board
        self.fps = {f.GetReference(): f for f in board.GetFootprints()}
        self.made = []            # BOARD_ITEMs to lock + group
        self.segs = []            # (a, b, halfwidth, layer, net)
        self.vias = []            # (p, radius, drill_r, net)
        self.pads = []            # (rect, net, layers, is_hole, hole_r, centre)
        self.fails = []
        self.notes = []
        self.lengths = {}         # trace label -> mm of copper drawn
        self.qfn_end = {}         # QFN pad number -> (escape end, direction)
        self.qfn_all_end = {}     # same, but including the pads with a via -
                                  # what step 6c's "ESCAPE.<pad>" resolves to
        self._index_pads()
        self.keepouts = []        # (kind, geometry, allowed nets)
        for hx, hy in HOLES.values():
            self.keepouts.append(("circle", (hx, hy, M3_COPPER_FREE_R), ()))

    # ---------------------------------------------------------- geometry --
    def _index_pads(self):
        for ref, fp in self.fps.items():
            for pad in fp.Pads():
                bb = pad.GetBoundingBox()
                r = (tomm(bb.GetLeft()) - ORIGIN[0], tomm(bb.GetTop()) - ORIGIN[1],
                     tomm(bb.GetRight()) - ORIGIN[0], tomm(bb.GetBottom()) - ORIGIN[1])
                lay = set()
                if pad.IsOnLayer(pcbnew.F_Cu):
                    lay.add("F.Cu")
                if pad.IsOnLayer(pcbnew.B_Cu):
                    lay.add("B.Cu")
                if not lay:
                    continue                     # paste-only aperture
                hole = pad.GetDrillSize().x > 0
                self.pads.append((r, pad.GetNetname(), lay, hole,
                                  tomm(pad.GetDrillSize().x) / 2.0 if hole else 0.0,
                                  loc(pad.GetPosition()), ref, pad.GetNumber()))

    def findpad(self, spec):
        """"REF.NUM", or "REF.NUM#i" for a footprint with duplicate numbers.

        SW401's two mounting lugs are both pad MP and SW301's two switch
        halves are both pad 2, so a pad number is not a key on this board.
        """
        ref, num = spec.split(".", 1)
        idx = 0
        if "#" in num:
            num, i = num.split("#", 1)
            idx = int(i)
        pads = [p for p in self.fps[ref].Pads() if p.GetNumber() == num]
        if len(pads) <= idx:
            raise KeyError(spec)
        return pads[idx]

    def pad(self, spec):
        return loc(self.findpad(spec).GetPosition())

    def padnet(self, spec):
        return self.findpad(spec).GetNetname()

    def padbox(self, spec):
        bb = self.findpad(spec).GetBoundingBox()
        return (tomm(bb.GetLeft()) - ORIGIN[0], tomm(bb.GetTop()) - ORIGIN[1],
                tomm(bb.GetRight()) - ORIGIN[0], tomm(bb.GetBottom()) - ORIGIN[1])

    def outward(self, spec):
        """Unit axis vector from the footprint centre towards the pad."""
        ref = spec.split(".")[0]
        c = loc(self.fps[ref].GetPosition())
        p = self.pad(spec)
        vx, vy = p[0] - c[0], p[1] - c[1]
        if abs(vx) >= abs(vy):
            return (1.0 if vx > 0 else -1.0, 0.0)
        return (0.0, 1.0 if vy > 0 else -1.0)

    def resolve(self, wp):
        return self.pad(wp) if isinstance(wp, str) else tuple(wp)

    # -------------------------------------------------------- clearance ---
    def seg_clear(self, a, b, hw, layer, net, ignore_pads=()):
        """Worst violation of segment a-b, or None when it clears."""
        if dist(a, b) < 1e-9:
            return None
        ignore_pads = tuple(s.split("#", 1)[0] for s in ignore_pads)
        # board edge
        for p in (a, b):
            if not (EDGE_KEEP + hw <= p[0] <= BOARD_W - EDGE_KEEP - hw and
                    EDGE_KEEP + hw <= p[1] <= BOARD_H - EDGE_KEEP - hw):
                return "board edge at (%.2f, %.2f)" % p
        # track keepouts: the M3 rings and the crystal island
        for kind, g, allow in self.keepouts:
            if net in allow:
                continue
            if kind == "circle":
                cx, cy, r = g
                if seg_point_dist(a, b, (cx, cy)) < r + hw:
                    return "M3 keepout at (%.1f, %.1f)" % (cx, cy)
            else:
                if seg_rect_dist(a, b, g) < hw:
                    return "crystal keepout"
        # Everything below is a distance from this segment, so nothing whose
        # own box is further than the widest clearance can matter. The reject
        # is two comparisons against a box and it is what makes the rail
        # trees affordable - they run tens of thousands of candidates each
        # against ~1100 pieces of geometry.
        mg = hw + MAX_CLEARANCE + 0.55
        lox, hix = min(a[0], b[0]) - mg, max(a[0], b[0]) + mg
        loy, hiy = min(a[1], b[1]) - mg, max(a[1], b[1]) + mg
        for r, pnet, lay, hole, hr, ctr, ref, num in self.pads:
            if r[2] < lox or r[0] > hix or r[3] < loy or r[1] > hiy:
                continue
            need = clearance(net, pnet)
            if need == 0.0:
                continue
            if "%s.%s" % (ref, num) in ignore_pads:
                continue
            if layer not in lay and not hole:
                continue
            d = seg_rect_dist(a, b, r)
            if d < hw + need:
                return "%s.%s (%s) %.3f < %.3f" % (ref, num, pnet or "-", d,
                                                   hw + need)
        for (sa, sb, shw, slay, snet) in self.segs:
            if slay != layer:
                continue
            if (max(sa[0], sb[0]) < lox or min(sa[0], sb[0]) > hix or
                    max(sa[1], sb[1]) < loy or min(sa[1], sb[1]) > hiy):
                continue
            need = clearance(net, snet)
            if need == 0.0:
                continue
            d = seg_seg_dist(a, b, sa, sb)
            if d < hw + shw + need:
                return "track of %s %.3f < %.3f" % (snet, d, hw + shw + need)
        for (p, rad, dr, vnet) in self.vias:
            if not (lox <= p[0] <= hix and loy <= p[1] <= hiy):
                continue
            need = clearance(net, vnet)
            if need == 0.0:
                continue
            d = seg_point_dist(a, b, p)
            if d < hw + rad + need:
                return "via of %s %.3f < %.3f" % (vnet, d, hw + rad + need)
        return None

    def path_clear(self, pts, width, layer, net, ignore_pads=()):
        hw = width / 2.0
        for i in range(len(pts) - 1):
            bad = self.seg_clear(pts[i], pts[i + 1], hw, layer, net,
                                 ignore_pads)
            if bad:
                return bad
        return None

    def via_clear(self, p, net, ignore_pads=()):
        rad, dr = VIA_D / 2.0, VIA_DRILL / 2.0
        ignore_pads = tuple(s.split("#", 1)[0] for s in ignore_pads)
        if not (EDGE_KEEP + rad <= p[0] <= BOARD_W - EDGE_KEEP - rad and
                EDGE_KEEP + rad <= p[1] <= BOARD_H - EDGE_KEEP - rad):
            return "board edge"
        for kind, g, allow in self.keepouts:
            if kind == "circle":
                cx, cy, r = g
                if dist(p, (cx, cy)) < r + rad:
                    return "M3 keepout"
            elif point_rect_dist(p, g) < rad:
                return "crystal keepout (no vias)"
        mg = rad + MAX_CLEARANCE + HOLE_TO_HOLE + 1.6
        for r, pnet, lay, hole, hr, ctr, ref, num in self.pads:
            if (r[2] < p[0] - mg or r[0] > p[0] + mg or
                    r[3] < p[1] - mg or r[1] > p[1] + mg):
                continue
            if "%s.%s" % (ref, num) in ignore_pads:
                continue
            need = clearance(net, pnet)
            d = point_rect_dist(p, r)
            if need > 0.0 and d < rad + need:
                return "%s.%s (%s) %.3f" % (ref, num, pnet or "-", d)
            if hole and dist(p, ctr) < dr + hr + HOLE_TO_HOLE:
                return "hole-to-hole %s.%s" % (ref, num)
            if hole and need > 0.0 and dist(p, ctr) < dr + hr + HOLE_CLEARANCE:
                return "hole clearance %s.%s" % (ref, num)
        for (sa, sb, shw, slay, snet) in self.segs:
            if (max(sa[0], sb[0]) < p[0] - mg or min(sa[0], sb[0]) > p[0] + mg
                    or max(sa[1], sb[1]) < p[1] - mg
                    or min(sa[1], sb[1]) > p[1] + mg):
                continue
            need = clearance(net, snet)
            if need == 0.0:
                continue
            if seg_point_dist(sa, sb, p) < rad + shw + need:
                return "track of %s" % snet
        for (q, vrad, vdr, vnet) in self.vias:
            need = clearance(net, vnet)
            d = dist(p, q)
            if need > 0.0 and d < rad + vrad + need:
                return "via of %s" % vnet
            if d < dr + vdr + HOLE_TO_HOLE:
                return "via hole-to-hole"
        return None

    # ------------------------------------------------------------ build ---
    def net(self, name):
        n = self.board.FindNet(name)
        if n is None:
            raise KeyError("no net %r on the board" % name)
        return n

    def add_seg(self, a, b, width, layer, netname):
        if dist(a, b) < 1e-9:
            return
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(at(*a))
        t.SetEnd(at(*b))
        t.SetWidth(mm(width))
        t.SetLayer(pcbnew.F_Cu if layer == "F.Cu" else pcbnew.B_Cu)
        t.SetNet(self.net(netname))
        t.SetLocked(True)
        self.board.Add(t)
        self.made.append(t)
        self.segs.append((a, b, width / 2.0, layer, netname))

    def add_path(self, pts, width, layer, netname):
        for i in range(len(pts) - 1):
            dx = abs(pts[i + 1][0] - pts[i][0])
            dy = abs(pts[i + 1][1] - pts[i][1])
            if min(dx, dy) > 0.35 and abs(dx - dy) > 0.35:
                self.notes.append("non-octilinear segment on %s: %s -> %s"
                                  % (netname, pts[i], pts[i + 1]))
            self.add_seg(pts[i], pts[i + 1], width, layer, netname)

    def add_via(self, p, netname):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(at(*p))
        v.SetWidth(mm(VIA_D))
        v.SetDrill(mm(VIA_DRILL))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.net(netname))
        v.SetLocked(True)
        self.board.Add(v)
        self.made.append(v)
        self.vias.append((p, VIA_D / 2.0, VIA_DRILL / 2.0, netname))
        return v

    # ------------------------------------------------- routing primitives -
    def trace(self, label, a_spec, b_spec, width, layer="F.Cu",
              stub=None, stubs=(0.0,), modes=OCT_MODES, quiet=False,
              ign_extra=(), adir=None, detours=None, dry=False):
        """Route pad a to pad b octilinearly, trying stub lengths and modes.

        `stub` forces one radial stub length out of a; `stubs` is the list to
        try. The first combination that clears everything wins. Returns the
        path, or None (and records a failure).
        """
        a = self.resolve(a_spec)
        b = self.resolve(b_spec)
        net = (self.padnet(a_spec) if isinstance(a_spec, str)
               else self.padnet(b_spec))
        ign = tuple(s for s in (a_spec, b_spec)
                    if isinstance(s, str)) + tuple(ign_extra)
        d = (adir if adir is not None else
             (self.outward(a_spec) if isinstance(a_spec, str) else (0.0, 0.0)))
        cand = []
        for s in ((stub,) if stub is not None else stubs):
            p0 = (a[0] + d[0] * s, a[1] + d[1] * s)
            for m in modes:
                pts = [a] + oct_route(p0, b, m) if s > 0 else oct_route(a, b, m)
                # collapse duplicates
                out = [pts[0]]
                for p in pts[1:]:
                    if dist(p, out[-1]) > 1e-9:
                        out.append(p)
                cand.append((0 if all_octilinear(out) else 1,
                             path_len(out), len(out), out))
        # Three-segment detours: step sideways off the stub, then go across.
        # Enough obstacle avoidance for a board where the hard cases are
        # "a pad is in the way", without pretending to be a router.
        if d != (0.0, 0.0):
            perp = (-d[1], d[0])
            for s in ((stub,) if stub is not None else stubs):
                p0 = (a[0] + d[0] * s, a[1] + d[1] * s)
                for o in (detours if detours is not None else
                          (0.4, -0.4, 0.7, -0.7, 1.0, -1.0, 1.4, -1.4,
                           1.8, -1.8, 2.2, -2.2, 2.8, -2.8, 3.5, -3.5,
                           4.5, -4.5, 6.0, -6.0, 8.0, -8.0)):
                    p1 = (p0[0] + perp[0] * o, p0[1] + perp[1] * o)
                    for m in modes:
                        pts = [a, p0] + oct_route(p1, b, m)[0:]
                        out = [pts[0]]
                        for p in pts[1:]:
                            if dist(p, out[-1]) > 1e-9:
                                out.append(p)
                        cand.append((0 if all_octilinear(out) else 1,
                                     path_len(out) + 2.0, len(out), out))
        cand.sort(key=lambda c: (c[0], round(c[1], 2), c[2]))
        why = None
        for _o, _l, _n, pts in cand:
            why = self.path_clear(pts, width, layer, net, ign)
            if why is None:
                if dry:
                    return pts
                self.add_path(pts, width, layer, net)
                self.lengths[label] = path_len(pts)
                return pts
        if not quiet:
            self.fails.append("%s: no clear path %s -> %s (%s)"
                              % (label, a_spec, b_spec, why))
        return None

    def gnd_via(self, label, pad_spec, out=None, tries=(0.85, 1.05, 1.3, 1.6,
                                                        1.9, 2.3)):
        """Stub off a GND pad and drop a via into the pour."""
        a = self.pad(pad_spec)
        d = out or self.outward(pad_spec)
        for s in tries:
            p = (round(a[0] + d[0] * s, 3), round(a[1] + d[1] * s, 3))
            if self.path_clear([a, p], W_SIG, "F.Cu", "GND", (pad_spec,)):
                continue
            if self.via_clear(p, "GND", (pad_spec,)):
                continue
            self.add_path([a, p], W_SIG, "F.Cu", "GND")
            self.add_via(p, "GND")
            return p
        self.fails.append("%s: no room for a GND via off %s" % (label, pad_spec))
        return None

    def gnd_via_quiet(self, pad_spec, widths=None, lengths=None):
        """Stub off a GND pad into the pour; silent when there is no room.

        Placed by SEARCH, not tabulated: sixteen directions - the pad's own
        outward normal first, then the other three axes, then the diagonals,
        then the eight half-diagonals - at growing distance, and at each
        (distance, direction) the WIDEST stub that clears. A short fat stub is
        a better via tie than a long thin one, and a 0.40 mm one still fits
        between two 0603s at 0.15 mm; the narrow widths are there so that a
        pad in a corridor gets a tie at all rather than nothing.

        Returns (via point, width, length) or None.
        """
        a = self.pad(pad_spec)
        d0 = self.outward(pad_spec)
        s2 = math.sqrt(0.5)
        c, s = math.cos(math.pi / 8.0), math.sin(math.pi / 8.0)
        dirs = [d0, (-d0[0], -d0[1]), (-d0[1], d0[0]), (d0[1], -d0[0]),
                (s2, s2), (-s2, s2), (s2, -s2), (-s2, -s2),
                (c, s), (c, -s), (-c, s), (-c, -s),
                (s, c), (-s, c), (s, -c), (-s, -c)]
        for ln in (lengths if lengths is not None else STITCH_LEN):
            for d in dirs:
                p = (round(a[0] + d[0] * ln, 3), round(a[1] + d[1] * ln, 3))
                if self.via_clear(p, "GND", (pad_spec,)) is not None:
                    continue
                for w in (widths if widths is not None else STITCH_W):
                    if self.path_clear([a, p], w, "F.Cu", "GND",
                                       (pad_spec,)) is not None:
                        continue
                    self.add_path([a, p], w, "F.Cu", "GND")
                    self.add_via(p, "GND")
                    return p, w, ln
        return None

    def has_gnd_via(self, pad_spec):
        """Is there already a GND via sitting in this pad's own copper?"""
        r = self.padbox(pad_spec)
        return any(vnet == "GND" and point_rect_dist(v, r) < rad + 0.05
                   for (v, rad, _dr, vnet) in self.vias)

    def in_keepout(self, p, no_via=True):
        """Which keepout, if any, this point is inside."""
        for kind, g, _allow in self.keepouts:
            if kind == "circle":
                cx, cy, r = g
                if dist(p, (cx, cy)) <= r:
                    return "M3 ring at (%.1f, %.1f)" % (cx, cy)
            elif point_rect_dist(p, g) <= 0.0 and no_via:
                return "crystal keepout (no vias)"
        return None


# ============================================================== zones =====
def board_polygon(inset=0.0):
    """The 110 x 70 outline with 2 mm corner radii, as a point list."""
    w, h, r = BOARD_W - inset, BOARD_H - inset, 2.0
    x0, y0 = inset, inset
    pts = []
    n = 6
    for cx, cy, a0 in ((x0 + r, y0 + r, 180.0), (w - r, y0 + r, 270.0),
                       (w - r, h - r, 0.0), (x0 + r, h - r, 90.0)):
        for k in range(n + 1):
            a = math.radians(a0 + 90.0 * k / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def add_zone(cop, pts, layers, netname=None, rule_area=False, name="",
             no_fill=False, no_tracks=False, no_vias=False):
    z = pcbnew.ZONE(cop.board)
    ls = pcbnew.LSET()
    for l in layers:
        ls.addLayer(l)
    z.SetLayerSet(ls)
    outline = z.Outline()
    outline.NewOutline()
    for x, y in pts:
        outline.Append(mm(ORIGIN[0] + x), mm(ORIGIN[1] + y))
    z.SetZoneName(name)
    if rule_area:
        z.SetIsRuleArea(True)
        z.SetDoNotAllowZoneFills(no_fill)
        z.SetDoNotAllowTracks(no_tracks)
        z.SetDoNotAllowVias(no_vias)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
    else:
        z.SetNet(cop.net(netname))
        z.SetLocalClearance(mm(ZONE_CLEARANCE))
        z.SetMinThickness(mm(ZONE_MIN_WIDTH))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)
        z.SetThermalReliefGap(mm(0.3))
        z.SetThermalReliefSpokeWidth(mm(0.5))
        z.SetAssignedPriority(0)
    z.SetLocked(True)
    cop.board.Add(z)
    cop.made.append(z)
    return z


def add_user_poly(cop, pts, layer, width=0.1):
    """A closed polygon on a User layer - what the router reads as a keepout."""
    s = pcbnew.PCB_SHAPE(cop.board)
    s.SetShape(pcbnew.SHAPE_T_POLY)
    s.SetLayer(layer)
    v = pcbnew.VECTOR_VECTOR2I()
    for x, y in pts:
        v.append(at(x, y))
    s.SetPolyPoints(v)
    s.SetFilled(False)
    s.SetWidth(mm(width))
    s.SetLocked(True)
    cop.board.Add(s)
    cop.made.append(s)
    return s


def circle_pts(cx, cy, r, n=24):
    return [(cx + r * math.cos(2 * math.pi * k / n),
             cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def parts_bbox(cop, refs, margin):
    xs, ys = [], []
    for ref in refs:
        for pad in cop.fps[ref].Pads():
            bb = pad.GetBoundingBox()
            xs += [tomm(bb.GetLeft()) - ORIGIN[0], tomm(bb.GetRight()) - ORIGIN[0]]
            ys += [tomm(bb.GetTop()) - ORIGIN[1], tomm(bb.GetBottom()) - ORIGIN[1]]
    return (min(xs) - margin, min(ys) - margin,
            max(xs) + margin, max(ys) + margin)


def seg_band(a, b, hw):
    """The segment a-b swollen by hw, as a four-point polygon."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return [(a[0] - hw, a[1] - hw), (a[0] + hw, a[1] - hw),
                (a[0] + hw, a[1] + hw), (a[0] - hw, a[1] + hw)]
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    return [(a[0] - ux * hw + nx * hw, a[1] - uy * hw + ny * hw),
            (b[0] + ux * hw + nx * hw, b[1] + uy * hw + ny * hw),
            (b[0] + ux * hw - nx * hw, b[1] + uy * hw - ny * hw),
            (a[0] - ux * hw - nx * hw, a[1] - uy * hw - ny * hw)]


def rect_pts(r):
    x0, y0, x1, y1 = r
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def step1_zones(cop):
    print("\n--- 1. zones and keepouts")
    both = (pcbnew.F_Cu, pcbnew.B_Cu)
    # GND pour over the whole outline on B.Cu.
    add_zone(cop, board_polygon(), (pcbnew.B_Cu,), netname="GND",
             name="GND pour B.Cu")
    print("  GND pour on B.Cu over the outline, clearance %.2f mm, "
          "min width %.2f, thermal reliefs on THT, solid on SMD"
          % (ZONE_CLEARANCE, ZONE_MIN_WIDTH))
    # M3: no copper pour, both layers; and a router keepout on User.2.
    for ref, (hx, hy) in sorted(HOLES.items()):
        pts = circle_pts(hx, hy, M3_COPPER_FREE_R)
        add_zone(cop, pts, both, rule_area=True, no_fill=True,
                 name="M3 ground-free %s" % ref)
        add_user_poly(cop, pts, pcbnew.User_2)
    print("  4 x %.0f mm diameter ground-free rule areas at the M3 holes "
          "(both layers, no pour) + User.2 copies" % M3_COPPER_FREE_D)
    # Crystal island: no vias either layer (a rule area that also forbade
    # tracks would forbid the oscillator's own copper); the track exclusion
    # is the User.2 polygon the router is given with --keepout.
    xr = parts_bbox(cop, XTAL_PARTS, XTAL_MARGIN)
    cop.xtal_rect = xr
    add_zone(cop, rect_pts(xr), both, rule_area=True, no_vias=True,
             name="crystal keepout")
    add_user_poly(cop, rect_pts(xr), pcbnew.User_2)
    cop.keepouts.append(("rect", xr,
                         ("/MCU/OSC_IN", "/MCU/OSC_OUT", "GND")))
    print("  crystal keepout x[%.2f, %.2f] y[%.2f, %.2f]: rule area = no "
          "vias both layers, User.2 copy = no router tracks, and this "
          "script's own clearance model refuses every net in there but "
          "OSC_IN, OSC_OUT and the ground guard. The B.Cu pour stays "
          "(ADR: ground guard, no signal under it)."
          % (xr[0], xr[2], xr[1], xr[3]))
    return xr


# ========================================================== QFN fanout ====
def escape_path(cop, spec, fan, reach):
    """Radial stub, a 45-degree step of `fan` sideways, then radial to `reach`.

    Returns the point list, or None when `reach` is too short to hold the fan.
    """
    a = cop.pad(spec)
    d = cop.outward(spec)
    t = (0.0, 1.0) if abs(d[1]) < 0.5 else (1.0, 0.0)   # the lane axis
    pts, end = [a], 0.0
    if abs(fan) > 1e-6:
        if reach < QFN_FAN_R + abs(fan) + 0.1:
            return None
        p0 = (a[0] + d[0] * QFN_FAN_R, a[1] + d[1] * QFN_FAN_R)
        p1 = (p0[0] + d[0] * abs(fan) + t[0] * fan,
              p0[1] + d[1] * abs(fan) + t[1] * fan)
        pts += [p0, p1]
        end = QFN_FAN_R + abs(fan)
    if reach > end + 1e-6:
        pts.append((pts[-1][0] + d[0] * (reach - end),
                    pts[-1][1] + d[1] * (reach - end)))
    return [(round(p[0], 3), round(p[1], 3)) for p in pts]


def qfn_escape(cop, spec, net, fan, reach, want_via):
    """Draw one fanned escape, backing off the reach and then the fan.

    Every candidate is clearance-checked in full before anything is drawn, and
    the run says which variant it settled for. Returns (fan, reach, via) as
    built, or None when even a plain radial stub is impossible.
    """
    tries = []
    for back in (0.0,) + QFN_REACH_BACK:
        r = round(reach - back, 3)
        if r < QFN_FAN_R + abs(fan) + 0.1:
            continue
        tries.append((fan, r, want_via))
        if want_via:
            tries.append((fan, r, False))
    for f, r, v in tries:
        pts = escape_path(cop, spec, f, r)
        if pts is None:
            continue
        if cop.path_clear(pts, W_FINE, "F.Cu", net, (spec,)) is not None:
            continue
        if v and cop.via_clear(pts[-1], net, (spec,)) is not None:
            continue
        cop.add_path(pts, W_FINE, "F.Cu", net)
        if v:
            cop.add_via(pts[-1], net)
        return (f, r, v)
    return None


def plain_stub(cop, spec, net):
    """The old escape: a radial stub, longest of the ladder that clears."""
    a, d = cop.pad(spec), cop.outward(spec)
    for s in (QFN_STUB, QFN_STUB - 0.15, QFN_STUB + 0.2, QFN_STUB + 0.45):
        b = (round(a[0] + d[0] * s, 3), round(a[1] + d[1] * s, 3))
        if cop.path_clear([a, b], W_FINE, "F.Cu", net, (spec,)) is None:
            cop.add_path([a, b], W_FINE, "F.Cu", net)
            return s
    return None


def step2_fanout(cop):
    print("\n--- 2. QFN fanout for %s" % QFN)
    fp = cop.fps[QFN]
    ep = cop.pad("%s.%s" % (QFN, QFN_EP))
    # EP vias to GND, inside the pad copper.
    nv = 0
    for dx, dy in QFN_EP_VIAS:
        p = (ep[0] + dx, ep[1] + dy)
        why = cop.via_clear(p, "GND", ("%s.%s" % (QFN, QFN_EP),))
        if why:
            cop.fails.append("EP via at %s blocked: %s" % (p, why))
            continue
        cop.add_via(p, "GND")
        nv += 1
    print("  EP: %d vias %.1f/%.1f to GND inside the pad copper" % (nv, VIA_D, VIA_DRILL))

    # GND perimeter pins into the EP copper.
    for num in QFN_GND_PINS:
        spec = "%s.%s" % (QFN, num)
        a = cop.pad(spec)
        o = cop.outward(spec)                     # the pad faces this way
        half = 2.8                                # EP is 5.6 mm square
        if o[0]:
            b = (ep[0] + o[0] * half, a[1])       # near EP edge, same row
        else:
            b = (a[0], ep[1] + o[1] * half)
        why = cop.path_clear([a, b], W_FINE, "F.Cu", "GND",
                             (spec, "%s.%s" % (QFN, QFN_EP)))
        if why:
            cop.fails.append("GND pin %s to EP blocked: %s" % (num, why))
        else:
            cop.add_path([a, b], W_FINE, "F.Cu", "GND")
    print("  GND pins %s tied into the EP copper (%.2f mm, %.2f mm long): at "
          "0.5 mm pitch no %.1f mm via fits in the first ring, and the EP is "
          "0.20 mm from the pin row"
          % (", ".join(QFN_GND_PINS), W_FINE, 0.638, VIA_D))

    # Radial stubs first, so that a first-ring trace leaving one pad cannot
    # take the escape space of its neighbour (it did in the first pass: the
    # VCAP1 trace closed pad 21's only way out).
    done = set(QFN_GND_PINS) | {QFN_EP} | {n for n, _t, _w in FIRST_RING}
    done |= set(QFN_EXPLICIT_PADS)   # explicit paths, drawn in step 6c
    done |= {"5", "6"}          # crystal, drawn in step 4
    done |= {"9"}               # VDDA, drawn in step 5
    done |= {"32", "33"}        # USB pair, drawn in step 6
    # The fanned escapes go first, in order of |fan|, biggest first: the pad
    # that has to travel furthest sideways is the one with the least choice
    # about where its diagonal runs, and a plain 1.15 mm stub cannot get in
    # its way because the fan only starts at QFN_FAN_R = 1.35.
    order = [p.GetNumber() for p in fp.Pads()]
    fanned = sorted((n for n in QFN_ESCAPE if n in order and n not in done),
                    key=lambda n: -abs(QFN_ESCAPE[n][0]))
    stubbed, vias, shadow, escapes, backed = [], [], [], [], []
    for num in fanned:
        spec = "%s.%s" % (QFN, num)
        net = fp.FindPadByNumber(num).GetNetname()
        if not net or net.startswith("unconnected-"):
            continue
        fan, reach, want_via = QFN_ESCAPE[num]
        got = qfn_escape(cop, spec, net, fan, reach, want_via)
        if got is None:
            s = plain_stub(cop, spec, net)
            if s is None:
                cop.fails.append("no room for any escape on %s (%s)"
                                 % (spec, net))
                continue
            backed.append("%s fell back to a %.2f mm radial stub" % (num, s))
            stubbed.append((num, net, s))
            continue
        f, r, v = got
        if (f, r, v) != (fan, reach, want_via):
            backed.append("%s asked for fan %+.2f reach %.2f via %s, got "
                          "%+.2f / %.2f / %s" % (num, fan, reach, want_via,
                                                 f, r, v))
        escapes.append((num, net, f, r, v))
        stubbed.append((num, net, r))
        cop.qfn_all_end[num] = (escape_path(cop, spec, f, r)[-1],
                                cop.outward(spec))
        if v:
            vias.append((num, net, r))
        else:
            # Where step 8's filter link has to carry on from, so it does not
            # re-leave the pad radially into the lane it was fanned away from.
            cop.qfn_end[num] = (escape_path(cop, spec, f, r)[-1],
                                cop.outward(spec))
    # Everything else keeps the plain radial stub.
    for pad in fp.Pads():
        num = pad.GetNumber()
        if not num or num in done or num in QFN_ESCAPE:
            continue
        net = pad.GetNetname()
        if not net or net.startswith("unconnected-"):
            continue
        spec = "%s.%s" % (QFN, num)
        placed = plain_stub(cop, spec, net)
        if placed is None:
            # No radial escape at all. That happens only on the island's side
            # of the part, so try the channel lane / same-net jumper there.
            what = shadow_escape(cop, num, net, cop.xtal_rect)
            if what:
                shadow.append(what)
            else:
                cop.fails.append("no room for the fanout stub on %s (%s)"
                                 % (spec, net))
        else:
            stubbed.append((num, net, placed))
    plain = [s for n, _t, s in stubbed if n not in QFN_ESCAPE]
    print("  radial stubs %.2f mm wide on %d pads (%.2f-%.2f mm out of the pad "
          "centre, %.2f-%.2f mm of new copper past the pad edge)"
          % (W_FINE, len(plain), min(plain), max(plain),
             min(plain) - 0.44, max(plain) - 0.44))
    print("  no via in the first ring: a %.1f mm via needs %.2f mm to a "
          "neighbouring %.2f mm stub and the pitch is 0.50 mm, so every "
          "escape leaves the pad radially on F.Cu and the bottom layer stays "
          "a whole ground plane under the part."
          % (VIA_D, VIA_D / 2 + CLEARANCE_DEFAULT + W_FINE / 2, W_FINE))
    if escapes:
        print("  escape fan on %d pads - radial to %.2f mm, 45 degrees "
              "sideways, then a lane of its own in the second ring:"
              % (len(escapes), QFN_FAN_R))
        for num, net, f, r, v in sorted(escapes, key=lambda e: int(e[0])):
            end = escape_path(cop, "%s.%s" % (QFN, num), f, r)[-1]
            print("    pad %-3s %-18s fan %+5.2f  reach %.2f  ends (%.2f, "
                  "%.2f)%s" % (num, net.rsplit("/", 1)[-1], f, r, end[0],
                               end[1], "  + via" if v else ""))
    if vias:
        print("  fanout vias %.1f/%.1f on pads %s, all of them in the second "
              "ring %.2f-%.2f mm out of the pad centre, where the lane pitch "
              "is 0.70-0.90 mm instead of 0.50 and a via blocks no neighbour"
              % (VIA_D, VIA_DRILL,
                 ", ".join("%s=%s" % (n, t.rsplit("/", 1)[-1])
                           for n, t, _r in vias),
                 min(r for _n, _t, r in vias), max(r for _n, _t, r in vias)))
    if backed:
        for line in backed:
            cop.notes.append("QFN escape: " + line)
    if shadow:
        print("  pads the crystal island shadows, given real copper instead "
              "of a radial stub:")
        for line in shadow:
            print("    " + line)
    # First-ring traces (no via, destination is a part on top). A pad whose
    # first-ring trace cannot be drawn gets the plain radial stub it would
    # have had otherwise - without it the pad is left bare and the router has
    # nothing at all to pick up (pad 22, VCAP1, was in exactly that state).
    ring_ok = 0
    for num, tgt, w in FIRST_RING:
        if cop.trace("QFN first ring %s->%s" % (num, tgt),
                     "%s.%s" % (QFN, num), tgt, w,
                     stubs=(0.7, 0.9, 1.1, 1.4, 1.7, 2.0)):
            ring_ok += 1
        else:
            spec = "%s.%s" % (QFN, num)
            s = plain_stub(cop, spec, fp.FindPadByNumber(num).GetNetname())
            if s is not None:
                stubbed.append((num, "", s))
                cop.notes.append("first ring %s->%s failed; pad %s kept a "
                                 "%.2f mm radial stub" % (num, tgt, num, s))
    print("  first-ring traces (no via): %d of %d" % (ring_ok, len(FIRST_RING)))
    return stubbed


# ====================================================== decoupling etc ====
# Signal-side traces, pin to cap. Everything here is short and on F.Cu.
DECOUPLE = [
    # The three bypasses on a rail are W_RAIL_MIN, not W_SIG: +5V and +3V3 are
    # Power-class nets and the .kicad_dru's floor for the class is 0.30 mm.
    ("U201 1 uF bypass at its pins", "C201.1", "U201.1", W_RAIL_MIN),
    ("U201 second bypass", "C202.1", "C201.1", W_RAIL_MIN),
    ("U202 100 nF bypass", "C203.1", "U202.8", W_RAIL_MIN),
    ("buck CIN 1 (1206)", "C105.1", "U101.2", 0.6),
    ("buck CIN 2 (1206)", "C106.1", "U101.2", 0.6),
    # C107 sits on the far side of the RON resistor from the 1206 pair, so
    # it joins VIN at the EN/UVLO divider's top instead. W_HC_MIN: VIN is
    # HighCurrent and the floor for it is 0.50 mm.
    ("buck CIN 3 (100 nF)", "C107.1", "R105.1", W_HC_MIN),
    ("buck BST cap at the pins", "C108.1", "U101.7", W_SIG),
    ("buck SW at the BST cap", "C108.2", "U101.8", 0.5),
    ("LDO input cap", "C113.1", "U102.1", W_RAIL),
    ("LDO input pin 3", "U102.3", "C113.1", W_RAIL),
    ("LDO output cap", "C114.1", "U102.5", W_RAIL),
    ("+3V3 bulk at the MCU", "C115.1", "C305.1", W_RAIL),
    ("SOT-223 tab to pin 2", "Q101.2", ("PAD2", "Q101"), W_POWER),
]

# The LM5164's PowerPAD, per the README TODO: 4 thermal vias of its own now
# that the footprint no longer carries the library's 0.2 mm ones.
EP_VIA_PARTS = {
    "U101.9": ((-0.55, -0.9), (0.55, -0.9), (-0.55, 0.9), (0.55, 0.9)),
}


def step3_decoupling(cop):
    print("\n--- 3. decoupling and the IC bypasses")
    ok = 0
    for label, a, b, w in DECOUPLE:
        if isinstance(b, tuple) and b[0] == "PAD2":
            # SOT-223: pin 2 appears twice (lead + tab), join them
            ref = b[1]
            pads = [p for p in cop.fps[ref].Pads() if p.GetNumber() == "2"]
            if len(pads) == 2:
                p0, p1 = (loc(p.GetPosition()) for p in pads)
                if cop.path_clear([p0, p1], w, "F.Cu",
                                  pads[0].GetNetname()) is None:
                    cop.add_path([p0, p1], w, "F.Cu", pads[0].GetNetname())
                    ok += 1
                else:
                    cop.fails.append("%s: lead-to-tab blocked" % label)
            continue
        if cop.trace(label, a, b, w, stubs=(0.0, 0.6, 0.9, 1.2)):
            ok += 1
    print("  %d of %d bypass traces drawn" % (ok, len(DECOUPLE)))

    # Exposed-pad thermal vias.
    for spec, offs in sorted(EP_VIA_PARTS.items()):
        c = cop.pad(spec)
        n = 0
        for dx, dy in offs:
            p = (c[0] + dx, c[1] + dy)
            if cop.via_clear(p, cop.padnet(spec), (spec,)) is None:
                cop.add_via(p, cop.padnet(spec))
                n += 1
        print("  %s: %d thermal vias %.1f/%.1f" % (spec, n, VIA_D, VIA_DRILL))

    return None


def step3b_stitch(cop):
    """Ground stitching: GND becomes a net the ROUTER NEVER SEES.

    Every top-side GND pad that is not already tied gets its own short stub
    and its own 0.6/0.3 via into the B.Cu pour, placed by search. THT GND pads
    need nothing - they reach the pour through the zone's own thermal reliefs.
    Four sets are excluded on purpose and each one is named in the output:

      - the sense-side reference pads (SENSE_GND + SENSE_TIE), which must keep
        their SINGLE tie at the shunt, ADR 0003 decision 4;
      - the QFN, whose perimeter GND pins run into the EP copper and whose EP
        carries four vias of its own;
      - pads inside the crystal keepout, where the rule area forbids vias;
        they are tied to the F.Cu ground guard, which is stitched;
      - pads that already have a via in their own copper from an earlier step
        (the shunt's cluster, the guard's).

    It also lays a via row along the two long board edges to tie the pour,
    with an F.Cu rib between consecutive vias so none of them is a dangling
    via.
    """
    print("\n--- 3b. ground stitching (GND is closed here, not by the router)")
    todo, excl = [], collections.defaultdict(list)
    for ref in sorted(cop.fps):
        # A pad NUMBER is not a key on this board: SW301 and SW302 each carry
        # two pads numbered 2 and SW401 two numbered MP, so the spec has to be
        # "REF.NUM#i" wherever the number repeats or only the first of them is
        # ever stitched. SW302's second pad 2 was the one GND pad pair
        # kicad-cli reported on every run of the fourth pass.
        seen = collections.Counter()
        for pad in cop.fps[ref].Pads():
            num = pad.GetNumber()
            if not num:
                continue
            seen[num] += 1
            if pad.GetNetname() != "GND":
                continue
            total = len([q for q in cop.fps[ref].Pads()
                         if q.GetNumber() == num])
            spec = ("%s.%s" % (ref, num) if total == 1
                    else "%s.%s#%d" % (ref, num, seen[num] - 1))
            if pad.GetDrillSize().x > 0:
                excl["THT - reaches the pour through the thermal relief"]\
                    .append(spec)
                continue
            if ref == QFN:
                excl["QFN - the perimeter pins run into the EP, which has "
                     "4 vias"].append(spec)
                continue
            if spec in set(SENSE_GND) | {SENSE_TIE}:
                excl["sense side - one tie at the shunt (ADR decision 4)"]\
                    .append(spec)
                continue
            where = cop.in_keepout(cop.pad(spec))
            if where:
                excl["inside the %s - tied to the F.Cu ground guard" % where]\
                    .append(spec)
                continue
            if cop.has_gnd_via(spec):
                excl["already has a via in its own copper"].append(spec)
                continue
            todo.append(spec)
    done, long_ties, miss = 0, [], []
    for spec in todo:
        got = cop.gnd_via_quiet(spec)
        if got is None:
            miss.append(spec)
            continue
        done += 1
        _p, w, ln = got
        if ln > STITCH_MAX + 1e-6:
            long_ties.append("%s %.2f mm at %.2f" % (spec, ln, w))
    print("  %d of %d top-side GND pads got a stub and a via of their own "
          "(%.2f-%.2f mm wide, <= %.2f mm long, searched over 16 directions)"
          % (done, len(todo), min(STITCH_W), max(STITCH_W), STITCH_MAX))
    for why in sorted(excl):
        print("  not stitched, %s: %s" % (why, ", ".join(sorted(excl[why]))))
    if long_ties:
        print("  over the %.2f mm length: %s"
              % (STITCH_MAX, ", ".join(long_ties)))
    if miss:
        print("  NO ROOM for a via at: %s" % ", ".join(miss))
        for spec in miss:
            cop.fails.append("GND stitching: no room for a via off %s - that "
                             "pad is left to the router" % spec)
    edge_stitch(cop)
    gnd_spine(cop)
    return miss


def _gnd_fcu_pieces(cop):
    """The GND pieces on F.Cu, IGNORING the pour. root -> [terminal points].

    Ignoring the pour is the whole point: what the pour joins is exactly what
    the router can take away again, so the question this answers is "which
    stubs would survive the pour being cut to ribbons".
    """
    segs = [s for s in cop.segs if s[4] == "GND" and s[3] == "F.Cu"]
    parent = list(range(len(segs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, (a, b, hw, _l, _n) in enumerate(segs):
        for j in range(i + 1, len(segs)):
            c, d, hw2, _l2, _n2 = segs[j]
            if seg_seg_dist(a, b, c, d) <= hw + hw2:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[ra] = rb
    out = collections.defaultdict(set)
    for i, (a, b, _hw, _l, _n) in enumerate(segs):
        out[find(i)].add((round(a[0], 3), round(a[1], 3)))
        out[find(i)].add((round(b[0], 3), round(b[1], 3)))
    return {r: sorted(p) for r, p in out.items()}


def gnd_spine(cop):
    """Join GND's separate F.Cu pieces to each other where the hop is short.

    A stitching stub with a via of its own is connected - as long as the pour
    island it lands in is connected. It is not always: the router lays B.Cu
    tracks in parallel at 0.5 mm pitch, the pour's 0.25 mm clearance leaves no
    neck between them, and a pour island holding one stub and nothing else is
    a GND pad pair again. That is measured, not feared: the fourth pass's
    first route run came out with two of them, both in the crystal corner,
    where the island's own User.2 keepout plus the M3 ring plus the QFN
    squeeze the pour into slivers and the router's tracks cut each sliver.

    So the pieces are tied together ON F.CU, where a short hop clears:
    a cluster that is one piece on top cannot be orphaned one stub at a time,
    whatever the router does underneath. Kruskal again - shortest hop first
    between two pieces that are not yet one - with a hard GND_SPINE_MAX,
    because a long GND link is a corridor taken from a signal, and it runs
    after every other thing this script draws.
    """
    qfn = loc(cop.fps[QFN].GetPosition())
    hops, tried = [], set()
    before = len(_gnd_fcu_pieces(cop))
    for sweep, (cap, lone_only, in_annulus) in enumerate(GND_SPINE_MAX):
        while True:
            pieces = _gnd_fcu_pieces(cop)
            if len(pieces) < 2:
                break
            own = {r: _piece_len(cop, pts) for r, pts in pieces.items()}
            cands = []
            roots = sorted(pieces)
            for i, ra in enumerate(roots):
                for rb in roots[i + 1:]:
                    if lone_only and min(own[ra], own[rb]) > GND_SPINE_LONE:
                        continue
                    for p in pieces[ra]:
                        for q in pieces[rb]:
                            d = dist(p, q)
                            if d <= cap and (p, q) not in tried:
                                cands.append((round(d, 4), p, q))
            if not cands:
                break
            cands.sort()
            drew = False
            for d, p, q in cands:
                tried.add((p, q))
                # A straight hop first, then the two L shapes and the two
                # 45-degree ones: the crystal corner needs the L, because the
                # straight line to the guard grazes C301's +3V3 pad.
                forms = [[p, q]]
                for m in OCT_MODES:
                    pts = oct_route(p, q, m)
                    out = [pts[0]]
                    for r in pts[1:]:
                        if dist(r, out[-1]) > 1e-9:
                            out.append(r)
                    if all_octilinear(out):
                        forms.append(out)
                forms = [f for f in forms
                         if path_len(f) <= d * GND_SPINE_SLACK + 0.5]
                forms.sort(key=lambda f: (round(path_len(f), 3), len(f)))
                for pts in forms:
                    if lone_only and not in_annulus and any(
                            seg_point_dist(pts[i], pts[i + 1], qfn)
                            < GND_SPINE_KEEP_R
                            for i in range(len(pts) - 1)):
                        continue        # inside the QFN's escape annulus
                    for w in GND_SPINE_W:
                        if cop.path_clear(pts, w, "F.Cu", "GND") is None:
                            cop.add_path(pts, w, "F.Cu", "GND")
                            hops.append((p, q, path_len(pts), w, sweep))
                            drew = True
                            break
                    if drew:
                        break
                if drew:
                    break
            if not drew:
                break
    left = len(_gnd_fcu_pieces(cop))
    print("  GND spine: %d hop(s) in %d sweep(s) (%s), %.2f mm of copper; "
          "%d piece(s) of F.Cu GND copper left of %d, so a diced pour cannot "
          "orphan them one at a time"
          % (len(hops), len(GND_SPINE_MAX),
             ", ".join("%d at <= %.2f mm" % (len([h for h in hops
                                                  if h[4] == i]), c)
                       for i, (c, _l, _a) in enumerate(GND_SPINE_MAX)),
             sum(h[2] for h in hops), left, before))
    # What is STILL a lone piece, and why the hop to its nearest neighbour was
    # refused. Those are the pieces whose connection depends on the pour island
    # under their one via, which is exactly what the router can cut away - so
    # the run names them rather than leaving them to turn up as an open GND pad
    # pair after a 45-minute route.
    pieces = _gnd_fcu_pieces(cop)
    own = {r: _piece_len(cop, pts) for r, pts in pieces.items()}
    for ra in sorted(pieces):
        if own[ra] > GND_SPINE_LONE:
            continue
        near = sorted((dist(p, q), p, q) for p in pieces[ra]
                      for rb in pieces if rb != ra for q in pieces[rb])
        if not near:
            continue
        d, p, q = near[0]
        why = "over the %.2f mm cap" % GND_SPINE_MAX[-1][0]
        if d <= GND_SPINE_MAX[-1][0]:
            for w in GND_SPINE_W:
                why = cop.path_clear([p, q], w, "F.Cu", "GND")
                if why is None:
                    why = "drawable at %.2f mm - not reached by the sweeps" % w
                    break
        cop.notes.append("GND lone piece at (%.2f, %.2f), %.2f mm of copper: "
                         "nearest piece %.2f mm away at (%.2f, %.2f), %s"
                         % (p[0], p[1], own[ra], d, q[0], q[1], why))
    names = ("short", "long", "last-resort")
    for p, q, ln, w, sweep in hops:
        cop.notes.append("GND spine %-12s (%.2f, %.2f) -> (%.2f, %.2f)  "
                         "%.2f mm at %.2f mm"
                         % (names[sweep] if sweep < len(names) else sweep,
                            p[0], p[1], q[0], q[1], ln, w))
    return len(hops)


def _piece_len(cop, pts):
    """How much F.Cu GND copper a piece holds, by its terminal set."""
    keys = set(pts)
    return sum(dist(a, b) for (a, b, _hw, lay, net) in cop.segs
               if net == "GND" and lay == "F.Cu"
               and ((round(a[0], 3), round(a[1], 3)) in keys
                    or (round(b[0], 3), round(b[1], 3)) in keys))


def edge_stitch(cop):
    """A via row along the two long board edges, with an F.Cu rib.

    The rear (y = 0) and front (y = 70) edges are the two long ones. A bare
    via in the pour is connected on ONE layer, which kicad-cli calls a
    dangling via, so consecutive vias are joined by a 0.30 mm F.Cu rib where
    the rib clears: that makes each of them a real two-layer tie and gives the
    edge a ground rib rather than a row of holes. The M3 rings are keepouts
    and the clearance model refuses them by itself; the USB pair's User.2
    bands are checked explicitly, because they are a rule for the router and
    not part of this script's own model.
    """
    usb = [(a, b) for (a, b, _hw, lay, net) in cop.segs
           if net in (USB_DP, USB_DM) and lay == "F.Cu"]
    usb_keep = USB_KEEP + VIA_D / 2.0 + CLEARANCE_DEFAULT
    rows, total, ribs = [], 0, 0
    for label, y in (("rear", EDGE_STITCH_IN),
                     ("front", BOARD_H - EDGE_STITCH_IN)):
        placed, skipped = [], 0
        x = EDGE_STITCH_PITCH / 2.0
        while x <= BOARD_W - EDGE_STITCH_PITCH / 2.0 + 1e-6:
            p = (round(x, 3), round(y, 3))
            x += EDGE_STITCH_PITCH
            if any(seg_point_dist(a, b, p) < usb_keep for a, b in usb):
                skipped += 1
                continue
            if cop.via_clear(p, "GND") is not None:
                skipped += 1
                continue
            cop.add_via(p, "GND")
            placed.append(p)
        n = 0
        for i in range(len(placed) - 1):
            pts = [placed[i], placed[i + 1]]
            if cop.path_clear(pts, EDGE_STITCH_RIB, "F.Cu", "GND") is None:
                cop.add_path(pts, EDGE_STITCH_RIB, "F.Cu", "GND")
                n += 1
        rows.append((label, y, len(placed), skipped, n))
        total += len(placed)
        ribs += n
    print("  edge stitching, %.0f mm pitch, %.2f mm in from the outline:"
          % (EDGE_STITCH_PITCH, EDGE_STITCH_IN))
    for label, y, n, skipped, nr in rows:
        print("    %-5s edge y = %5.2f   %2d via(s), %d position(s) skipped "
              "(M3 ring, USB band or occupied), %d F.Cu rib(s)"
              % (label, y, n, skipped, nr))
    print("    %d edge via(s) and %d rib(s) in all; the rib is what keeps "
          "them off the via_dangling list" % (total, ribs))
    return total


def gnd_islands(cop):
    """Pieces of scripted GND copper that do NOT reach the pour.

    Union-find over real GEOMETRY, not over shared endpoints: two pieces of
    copper of the same net on the same layer are one piece when they overlap
    anywhere, which is how KiCad sees it and is the difference between a
    report that matches kicad-cli and one that does not. A tie that lands in
    the MIDDLE of the crystal guard's leg is connected; keyed on endpoints it
    is not, and that is how the Y301 island hid behind a run that said "3 of 3
    island ground ties onto the guard".

    A piece reaches the pour when it carries a via, a B.Cu segment or a THT
    pad. Anything else is named here, so the remainder is a list of parts
    rather than "Track [GND], length 2.40 mm" out of kicad-cli.
    """
    segs = [s for s in cop.segs if s[4] == "GND"]
    vias = [v for v in cop.vias if v[3] == "GND"]
    pads = [p for p in cop.pads if p[1] == "GND"]
    n = len(segs) + len(vias) + len(pads) + 1
    pour = n - 1
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def uni(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[a] = b
    for i, (a, b, hw, lay, _net) in enumerate(segs):
        if lay == "B.Cu":
            uni(i, pour)
        for j in range(i + 1, len(segs)):
            c, d, hw2, lay2, _n2 = segs[j]
            if lay2 == lay and seg_seg_dist(a, b, c, d) <= hw + hw2:
                uni(i, j)
    for k, (p, rad, _dr, _net) in enumerate(vias):
        vi = len(segs) + k
        uni(vi, pour)                     # a via always reaches the B.Cu pour
        for i, (a, b, hw, _lay, _net2) in enumerate(segs):
            if seg_point_dist(a, b, p) <= hw + rad:
                uni(vi, i)
    for m, (r, _pnet, lay, hole, _hr, _ctr, ref, num) in enumerate(pads):
        pi = len(segs) + len(vias) + m
        if hole:
            uni(pi, pour)                 # through the zone's thermal relief
        for i, (a, b, hw, slay, _net) in enumerate(segs):
            if slay in lay and seg_rect_dist(a, b, r) <= hw:
                uni(pi, i)
        for k, (p, rad, _dr, _net) in enumerate(vias):
            if point_rect_dist(p, r) <= rad:
                uni(pi, len(segs) + k)
    groups = collections.defaultdict(list)
    for i in range(n - 1):
        groups[find(i)].append(i)
    out = []
    for root, members in groups.items():
        if root == find(pour):
            continue
        owns, length = [], 0.0
        for i in members:
            if i < len(segs):
                length += dist(segs[i][0], segs[i][1])
            elif i >= len(segs) + len(vias):
                p = pads[i - len(segs) - len(vias)]
                owns.append("%s.%s" % (p[6], p[7]))
        out.append((sorted(owns), length))
    return sorted(out, key=lambda o: -o[1])


# ============================================================ crystal =====
def _uv(d, t, p):
    """Board mm -> (out of the part, along its pin row)."""
    return (p[0] * d[0] + p[1] * d[1], p[0] * t[0] + p[1] * t[1])


def _xy(d, t, u, v):
    return (u * d[0] + v * t[0], u * d[1] + v * t[1])


def _far_edge(d, t, box):
    """How far the copper of `box` reaches out along d."""
    return max(_uv(d, t, p)[0] for p in
               ((box[0], box[1]), (box[2], box[1]),
                (box[2], box[3]), (box[0], box[3])))


def _near_edge(d, t, box):
    return min(_uv(d, t, p)[0] for p in
               ((box[0], box[1]), (box[2], box[1]),
                (box[2], box[3]), (box[0], box[3])))


def osc_channel(cop, xr):
    """The two lanes between the QFN's pin row and the crystal island.

    Returns (d, t, inner lane, outer lane, keepout near edge, channel width).
    Everything downstream of this - the OSC_IN leg, the lane that carries the
    pad the island shadows, and the ground guard's open ends - is placed off
    these numbers rather than off constants measured by hand.
    """
    d = cop.outward("%s.5" % QFN)
    t = (-d[1], d[0])
    row = max(_far_edge(d, t, cop.padbox("%s.%s" % (QFN, n)))
              for n in ("1", "6", "12"))
    near = _near_edge(d, t, xr)
    lane_in = row + LANE_GAP + W_FINE / 2.0
    lane_out = lane_in + W_FINE + LANE_GAP
    return d, t, lane_in, lane_out, near, near - row


def step4_crystal(cop, xr):
    print("\n--- 4. crystal")
    res = {}
    d, t, lane_in, lane_out, near, chan = osc_channel(cop, xr)
    cop.channel = (d, t, lane_in, lane_out, near)
    print("  channel between the pin-row copper and the island keepout: "
          "%.2f mm, two %.2f mm lanes at %.2f mm (second pass: %.2f mm, one)"
          % (chan, W_FINE, LANE_GAP, 0.51))
    if lane_out + W_FINE / 2.0 > near:
        cop.fails.append("crystal channel too narrow for two lanes: %.2f mm"
                         % chan)
    p5, p6 = cop.pad("%s.5" % QFN), cop.pad("%s.6" % QFN)
    y1, y3 = cop.pad("Y301.1"), cop.pad("Y301.3")
    ign = ("%s.5" % QFN, "%s.6" % QFN, "C310.1", "C311.1", "Y301.1", "Y301.3")

    # OSC_IN: pad 5 goes out to the OUTER channel lane, runs along the pin row
    # to the crystal's XIN pad - which rotation 270 puts on the island's
    # near-west corner - and drops straight into it. The inner lane is left
    # for the one connected pad the island shadows (see step 2b).
    u5, v5 = _uv(d, t, p5)
    u1, v1 = _uv(d, t, y1)
    osc_in = [p5, _xy(d, t, lane_out, v5), _xy(d, t, lane_out, v1), y1]
    # OSC_OUT does not touch the channel: XOUT is the island's FAR pad on pad
    # 6's own side of the crystal, so the leg leaves pad 6 straight out, clears
    # the crystal's near GND pad by 0.20 mm, and turns once into XOUT.
    u6, v6 = _uv(d, t, p6)
    u3, v3 = _uv(d, t, y3)
    osc_out = [p6, _xy(d, t, u3, v6), y3]
    for name, net, pts in (("OSC_IN", "/MCU/OSC_IN", osc_in),
                           ("OSC_OUT", "/MCU/OSC_OUT", osc_out)):
        out = [pts[0]]
        for q in pts[1:]:
            if dist(q, out[-1]) > 1e-9:
                out.append(q)
        why = cop.path_clear(out, W_FINE, "F.Cu", net, ign)
        if why:
            cop.fails.append("crystal %s blocked: %s" % (name, why))
            continue
        cop.add_path(out, W_FINE, "F.Cu", net)
        res[net] = res.get(net, 0.0) + path_len(out)
    # each load cap hangs off its own crystal pad, one turn away
    for a, b in (("Y301.1", "C310.1"), ("Y301.3", "C311.1")):
        pts = cop.trace("crystal load cap %s->%s" % (a, b), a, b, W_FINE,
                        stubs=(0.0, 0.4, 0.6, 0.9, 1.2))
        if pts:
            net = cop.padnet(a)
            res[net] = res.get(net, 0.0) + path_len(pts)
    for net in ("/MCU/OSC_IN", "/MCU/OSC_OUT"):
        print("  %-8s %.2f mm of F.Cu, 0 vias"
              % (net.rsplit("/", 1)[-1], res.get(net, 0.0)))

    # Ground guard: a bracket on F.Cu just outside the keepout, open towards
    # the MCU, stitched into the pour with vias at its corners. Its open ends
    # now stop at the keepout's near edge rather than reaching back into the
    # channel: the second pass's west leg cut across the channel and was
    # always skipped, and with two lanes in there it would cut both.
    gb = parts_bbox(cop, XTAL_PARTS, GUARD_MARGIN)
    u_open = near + W_GUARD / 2.0
    u_far = _far_edge(d, t, gb)
    v_lo = min(_uv(d, t, p)[1] for p in
               ((gb[0], gb[1]), (gb[2], gb[1]), (gb[2], gb[3]), (gb[0], gb[3])))
    v_hi = max(_uv(d, t, p)[1] for p in
               ((gb[0], gb[1]), (gb[2], gb[1]), (gb[2], gb[3]), (gb[0], gb[3])))
    # Each leg's open end is pulled back until it clears: whatever sits in the
    # first ring on the island's flank - here VBAT's cap, which the island
    # pushed out along the pin row - ends up right at the open end, and the
    # second pass simply dropped the leg it fouled.
    def leg(u0, u1, v):
        return [_xy(d, t, u0, v), _xy(d, t, u1, v)]
    corners = [_xy(d, t, u_open, v_lo), _xy(d, t, u_far, v_lo),
               _xy(d, t, u_far, v_hi), _xy(d, t, u_open, v_hi)]
    legs = [(u_open, u_far, v_lo), (u_far, u_far, None), (u_far, u_open, v_hi)]
    drawn = 0
    for i, (ua, ub, v) in enumerate(legs):
        if v is None:
            pts = [_xy(d, t, u_far, v_lo), _xy(d, t, u_far, v_hi)]
            cands = [pts]
        else:
            cands = [leg(ua + k * (0.2 if ua < ub else -0.2), ub, v)
                     if ua < ub else
                     leg(ua, ub + k * 0.2, v) for k in range(7)]
        why = None
        for pts in cands:
            why = cop.path_clear(pts, W_GUARD, "F.Cu", "GND")
            if why is None:
                cop.add_path(pts, W_GUARD, "F.Cu", "GND")
                drawn += 1
                break
        if why is not None:
            cop.notes.append("crystal guard leg %d skipped (%s)" % (i, why))
    nv = 0
    for p in corners + [_xy(d, t, u_far, (v_lo + v_hi) / 2.0)]:
        if cop.via_clear(p, "GND") is None:
            cop.add_via(p, "GND")
            nv += 1
    x0 = min(c[0] for c in corners)
    x1 = max(c[0] for c in corners)
    print("  F.Cu ground guard x[%.2f, %.2f], open towards the MCU at the "
          "keepout's near edge: %d of 3 legs, %d stitching vias into the pour"
          % (x0, x1, drawn, nv))
    # Each island GND pad onto the nearest guard leg, and the crystal's own
    # two GND pads to each other.
    #
    # Y301.2 AND Y301.4 both get a leg of their own, not just the link between
    # them. Tying the two to each other and to nothing else is what left them
    # as the one real GND island on the board for three passes: they are inside
    # the keepout so neither can have a via, and the run reported "3 of 3
    # island ground ties" while the piece it had made reached the pour nowhere.
    # GND-to-GND clearance is zero, so a leg that crosses the other load cap's
    # ground pad is free; the check still refuses one that crosses OSC_IN or
    # OSC_OUT.
    # One requirement per PIECE of copper, with the candidates that would
    # satisfy it: the crystal's two GND pads are one piece as soon as the link
    # between them is drawn, so either of them reaching the guard does the
    # job, and Y301.4's own leg runs into OSC_IN on this rotation. Reported as
    # a failure only when every candidate fails.
    tie = [("Y301.4 to Y301.2", [("Y301.4", "Y301.2")]),
           ("the crystal's own GND pads to the guard",
            [("Y301.2", None), ("Y301.4", None)]),
           ("C310.2 to the guard", [("C310.2", None)]),
           ("C311.2 to the guard", [("C311.2", None)])]
    nt = 0
    for what, cands in tie:
        got = None
        for a, b in cands:
            if b is None:
                p = cop.pad(a)
                u, v = _uv(d, t, p)
                b = _xy(d, t, u,
                        v_lo if abs(v - v_lo) < abs(v - v_hi) else v_hi)
            got = cop.trace("crystal ground tie %s" % a, a, b, W_FINE,
                            stubs=(0.0, 0.4, 0.6, 0.9, 1.2),
                            quiet=len(cands) > 1)
            if got:
                break
        if got:
            nt += 1
        elif len(cands) > 1:
            cop.fails.append("crystal ground: %s - none of %s could be drawn"
                             % (what, ", ".join(a for a, _b in cands)))
    print("  %d of %d island ground ties onto the guard (the pads inside the "
          "keepout cannot have a via of their own)" % (nt, len(tie)))
    return dict(OSC_IN=res.get("/MCU/OSC_IN", 0.0),
                OSC_OUT=res.get("/MCU/OSC_OUT", 0.0))


# ================================================= pads under the island ==
def shadow_escape(cop, num, net, xr):
    """Last-resort escape for a pin-row pad the crystal island shadows.

    Wherever the island goes it takes some pads' radial escape with it - that
    is what "in the corner" buys: the corner at the low pin numbers holds
    VBAT, PC13 (LED_STAT) and two pins this design does not use, instead of
    NRST and the two pedal inputs. What is left gets real copper rather than
    a stub that dies against the island:

      - a pad with another pad of its OWN net on the part gets a jumper to it
        (VBAT's pad 1 to the VDD pad round the corner, 0.97 mm), which costs
        nothing at all;
      - anything else gets the INNER channel lane out past the island's flank
        and a via into the pour at the end of it, which is a genuine escape
        on B.Cu clear of the keepout - not a dangling stub.

    Returns a one-line description, or None when neither works.
    """
    d, t, lane_in, lane_out, near = cop.channel
    fp = cop.fps[QFN]
    spec = "%s.%s" % (QFN, num)
    a = cop.pad(spec)
    short = net.rsplit("/", 1)[-1]
    bynet = collections.defaultdict(list)
    for pad in fp.Pads():
        if pad.GetNumber() and pad.GetNetname():
            bynet[pad.GetNetname()].append(pad.GetNumber())
    mate = sorted((dist(a, cop.pad("%s.%s" % (QFN, m))), m)
                  for m in bynet[net] if m != num and m != QFN_EP)
    if mate and mate[0][0] <= 1.6:
        tgt = "%s.%s" % (QFN, mate[0][1])
        pts = [a, cop.pad(tgt)]
        # Widest first, because the jumper is on a rail: pad 1 is VBAT and the
        # mate is a VDD pad, so this is Power copper and the .kicad_dru's
        # 0.30 mm floor applies to it. At 0.5 mm pad pitch that is not always
        # drawable, and a jumper that necks is still better than a bare pad -
        # the run says which width it took.
        why = None
        for w in sorted({W_FLOOR.get(net, W_FINE), W_FINE}, reverse=True):
            why = cop.path_clear(pts, w, "F.Cu", net, (spec, tgt))
            if why is None:
                cop.add_path(pts, w, "F.Cu", net)
                return ("pad %s (%s): %.2f mm jumper to pad %s on the same "
                        "net at %.2f mm, no channel lane and no via needed"
                        % (num, short, mate[0][0], mate[0][1], w))
        cop.notes.append("pad %s jumper to %s blocked: %s" % (num, tgt, why))
    u0, v0 = _uv(d, t, a)
    vs = [_uv(d, t, p)[1] for p in
          ((xr[0], xr[1]), (xr[2], xr[1]), (xr[2], xr[3]), (xr[0], xr[3]))]
    why = None
    for sign in (1.0, -1.0):
        edge = (max(vs) if sign > 0 else min(vs)) + sign * 0.35
        for extra in (0.0, 0.3, 0.6, 1.0, 1.5, 2.0, 2.6):
            v1 = edge + sign * extra
            pts = [a, _xy(d, t, lane_in, v0), _xy(d, t, lane_in, v1)]
            bad = cop.path_clear(pts, W_FINE, "F.Cu", net, (spec,))
            if bad:
                why = why or "lane: " + bad
                continue
            bad = cop.via_clear(pts[-1], net, (spec,))
            if bad:
                why = why or ("via at (%.2f, %.2f): %s"
                              % (pts[-1][0], pts[-1][1], bad))
                continue
            cop.add_path(pts, W_FINE, "F.Cu", net)
            cop.add_via(pts[-1], net)
            return ("pad %s (%s): %.2f mm along the inner channel lane to "
                    "(%.2f, %.2f) and a via into the pour"
                    % (num, short, path_len(pts), pts[-1][0], pts[-1][1]))
    cop.notes.append("pad %s (%s) channel escape: %s" % (num, short, why))
    return None


# ============================================================== VDDA ======
def power_escape(cop, spec, net, width, lengths=(0.85, 1.0, 1.2, 1.5, 1.8,
                                                 2.2, 2.6)):
    """A stub of at least `width` off a pad, with a via, placed by search.

    The same idea as gnd_via_quiet, for a pad on a net the .kicad_dru holds to
    a floor: sixteen directions at growing distance, and the first one where
    both the stub and the via clear wins. The point is not the via - it is that
    the piece of copper the router picks up is wide enough to be legal, because
    at a 0.25 mm pad the router's own bridge never is.
    """
    a = cop.pad(spec)
    d0 = cop.outward(spec)
    s2 = math.sqrt(0.5)
    c, s = math.cos(math.pi / 8.0), math.sin(math.pi / 8.0)
    dirs = [d0, (-d0[1], d0[0]), (d0[1], -d0[0]), (-d0[0], -d0[1]),
            (s2, s2), (-s2, s2), (s2, -s2), (-s2, -s2),
            (c, s), (c, -s), (-c, s), (-c, -s),
            (s, c), (-s, c), (s, -c), (-s, -c)]
    # With a via first, because a via is a real escape; then without one, which
    # is still what matters here - the router continues from a TRACK END with
    # no pad-width cap on it, so a bare stub of the floor width is enough.
    for want_via in (True, False):
        for ln in (lengths if want_via else sorted(lengths, reverse=True)):
            for d in dirs:
                p = (round(a[0] + d[0] * ln, 3), round(a[1] + d[1] * ln, 3))
                if cop.path_clear([a, p], width, "F.Cu", net,
                                  (spec,)) is not None:
                    continue
                if want_via and cop.via_clear(p, net, (spec,)) is not None:
                    continue
                cop.add_path([a, p], width, "F.Cu", net)
                if want_via:
                    cop.add_via(p, net)
                return p, want_via
    return None


# SEVENTH PASS. Pad 9 to C306 is 2.50 mm pad to pad and it cannot be drawn on
# F.Cu at any width, because pad 9 is BOXED IN by four things this script drew
# first and by the placement:
#
#   - C309, NRST's cap, sits directly south of it (pad box x 46.775..47.725,
#     top edge y = 48.775), so a southward stub stops at y = 48.425;
#   - pads 8 (GND) and 10 (unconnected) are 0.5 mm either side, so the corridor
#     out of the pad is 0.75 mm wide between their copper;
#   - PEDAL_TIP's radial stub runs south down x = 48.250 to y = 48.587 and
#     PEDAL_RING's down x = 48.750 to y = 48.438, so the slot between C309's
#     pad and the first of them is 0.525 mm - a 0.30 mm VDDA track needs
#     0.35 mm to the pad plus 0.45 mm to the stub, i.e. 0.80 mm, and even a
#     0.20 mm one needs 0.70 mm;
#   - going round the SOUTH of the pedal stubs means crossing x = 48.250 at
#     y >= 49.037, and every route to there from pad 9 runs into C309's pad.
#
# So the room is in the third dimension, which is also what the router found in
# the sixth pass's p8 run (6.74 mm, 2 vias). The two ways to do it on one layer
# were both measured and both cost more than they buy: shortening the two pedal
# stubs to clear a 0.30 mm lane at y = 48.425 leaves them 0.10 mm of copper
# past their own pad edge, which is no escape at all for two real signals; and
# moving C309 south far enough (0.80 mm, not "a few tenths") puts C309 pad 2
# 0.19 mm from C405's pad and takes NRST's own first-ring trace into the
# crystal ground guard at x = 46.200.
#
# 2.95 mm over two layers, every segment at W_RAIL_MIN, and the vias are placed
# in the one window that exists: (47.250, 48.225) clears pads 8 and 10 by
# 0.513 mm where 0.50 is needed, C309's pad by 0.550 and NRST's own diagonal by
# 0.646 where 0.625 is needed. That window is 0.048 mm tall in y, which is why
# power_escape's 0.85 mm ladder rung missed it by 0.06 mm.
VDDA_LAYERED = [
    ("F.Cu", ["U301.9", (47.250, 48.225)]),
    ("B.Cu", [(47.250, 48.225), (48.250, 49.225)]),
    ("F.Cu", [(48.250, 49.225), "C306.1"]),
]


def step5_vdda(cop, xr):
    print("\n--- 5. VDDA / VSSA")
    for a, b in (("FB301.2", "C307.1"), ("FB301.2", "C306.1")):
        cop.trace("VDDA %s->%s" % (a, b), a, b, W_VDDA,
                  stubs=(0.0, 0.5, 0.8, 1.2))
    # THIRD PASS: pin 9 is now EAST of the island, not behind it, so VDDA is
    # an ordinary short radial escape into its own 1 uF - no channel, no
    # 0.20 mm squeeze, and the channel it used to occupy is free for the pad
    # the island shadows. C306 is 2.50 mm from pin 9 instead of 8.21 mm.
    # 0.20 mm, not W_VDDA: pin 9's neighbours are 0.25 mm away and a 0.40 mm
    # track cannot leave the pad at all. It widens to W_VDDA past C306.
    # Short stubs first: the NRST cap ends up 1.0 mm west of pin 9's own
    # first-ring slot (the island's courtyard pushes it there), so a full
    # 1.15 mm radial stub runs into its pad and the leg has to turn early.
    # SIXTH PASS: at the floor first. VDDA is a Power-class net and the
    # .kicad_dru holds it to W_RAIL_MIN, so a 0.20 mm escape here is a DRC
    # error wherever it goes - and leaving the pad to the ROUTER is not an
    # escape either: pad 9 is 0.25 mm wide, and the router's via-to-pad bridge
    # is capped at the pad's own width (pcb_modification: w = min(track,
    # pad.size_x, pad.size_y)), so whatever the router does at this pad it
    # does at 0.25 mm. Something >= the floor has to leave the pad here or the
    # net cannot be legal at all.
    run = None
    for w in (W_RAIL_MIN, W_FINE):
        # Both attempts are quiet: VDDA_LAYERED below is the answer when they
        # fail, so a "no clear path" line here would be a report of something
        # that is not left undrawn.
        run = cop.trace("VDDA pin 9 to C306", "%s.9" % QFN, "C306.1", w,
                        stubs=(0.55, 0.7, 0.9, QFN_STUB, QFN_STUB + 0.3, 0.0),
                        quiet=True)
        if run is not None:
            break
    if run is not None:
        total = path_len(run)
        print("  pin 9 -> C306 %.2f mm on F.Cu, 0 vias, %.2f mm wide - a plain "
              "radial escape now that the island is off this side" % (total, w))
        return total
    # No lane to C306 at any width on this pose (C309, NRST's cap, sits on the
    # only one). SEVENTH PASS: change layer rather than hand the 2 mm gap to
    # the router, which closed it in one run of six and left it open in five.
    # See VDDA_LAYERED above for why one layer cannot do it and what the two
    # single-layer alternatives cost.
    got = layered(cop, "VDDA pin 9 to C306", "/MCU/VDDA", W_RAIL_MIN,
                  VDDA_LAYERED)
    if got:
        total, nv = got
        print("  pin 9 -> C306 has no F.Cu lane at %.2f mm or %.2f mm - pad 9 "
              "is boxed in by C309's pad, pads 8/10 and the two pedal stubs. "
              "%.2f mm over two layers with %d via(s) instead, every segment "
              "at the %.2f mm floor (straight line %.2f mm)"
              % (W_RAIL_MIN, W_FINE, total, nv, W_RAIL_MIN,
                 dist(cop.pad("%s.9" % QFN), cop.pad("C306.1"))))
        return total
    got = power_escape(cop, "%s.9" % QFN, "/MCU/VDDA", W_RAIL_MIN)
    if got:
        p, v = got
        print("  pin 9 -> C306 could not be drawn at %.2f mm or %.2f mm; pad 9 "
              "has a %.2f mm escape to (%.2f, %.2f)%s instead, and the router "
              "carries on from there"
              % (W_RAIL_MIN, W_FINE, W_RAIL_MIN, p[0], p[1],
                 " and a via" if v else " (no room for a via)"))
        return dist(cop.pad("%s.9" % QFN), p)
    cop.fails.append("VDDA pad 9: no escape at %.2f mm in any direction, so "
                     "the router will reach the pad with a bridge capped at "
                     "the pad's own 0.25 mm width - one unavoidable "
                     "track_width error" % W_RAIL_MIN)
    return 0.0


# =============================================================== USB ======
# Everything here is derived from the HRO footprint's own pad x positions.
USB_TURN_Y = 13.4          # where the two legs leave the vertical for 45 deg
                           # (13.4 is the minimum that keeps the diagonals
                           # clear of R305's pads and SW302's)
USB_BRIDGE_Y = 6.05        # D+ duplicate bridge, in front of the pad row
USB_TEE_Y = 9.3            # the D- duplicate bridge, behind the pad row
# U302 -> MCU: one lane per leg, D- the inner one. Both clear U302's own pad
# row (y 27.94) and the R307 pull-up's pads (y 29.20 at x 44.6..45.4).
USB_MCU_LANE = {"D-": 28.4, "D+": 28.9}


def step6_usb(cop):
    print("\n--- 6. USB")
    res = {}
    px = {}
    for pad in cop.fps["J301"].Pads():
        px[pad.GetNumber()] = loc(pad.GetPosition())
    pady = px["A6"][1]
    # The run leaves from the two WESTMOST of the four data contacts, B6 (D+)
    # and A7 (D-): they are adjacent, and D+ on the low-x side is the order
    # U302 (rotated 180 by place.py) and the MCU both want, so the pair never
    # swaps sides. Both duplicates then sit east of the run, which is what
    # makes a via-free bridging possible: the D+ bridge crosses the run in
    # FRONT of the pad row, where A7 has no copper, and the D- bridge crosses
    # BEHIND it, where A6 has none. With the run leaving from A7/A6 instead,
    # both bridges would have to cross behind and one would need two vias.
    run = {USB_DP: px["B6"][0], USB_DM: px["A7"][0]}
    ok = True
    brg = [(px["B6"][0], pady), (px["B6"][0], USB_BRIDGE_Y),
           (px["A6"][0], USB_BRIDGE_Y), (px["A6"][0], pady)]
    why = cop.path_clear(brg, USB_W, "F.Cu", USB_DP, ("J301.B6", "J301.A6"))
    if why:
        cop.fails.append("USB D+ duplicate bridge blocked: %s" % why)
        ok = False
    brh = [(px["B7"][0], pady), (px["B7"][0], USB_TEE_Y),
           (px["A7"][0], USB_TEE_Y)]
    why = cop.path_clear(brh, USB_W, "F.Cu", USB_DM, ("J301.B7", "J301.A7"))
    if why:
        cop.fails.append("USB D- duplicate bridge blocked: %s" % why)
        ok = False
    if ok:
        cop.add_path(brg, USB_W, "F.Cu", USB_DP)
        cop.add_path(brh, USB_W, "F.Cu", USB_DM)
        print("  duplicate contacts bridged with 0 vias: D+ A6<->B6 %.2f mm "
              "in front of the pad row, D- A7<->B7 %.2f mm behind it"
              % (path_len(brg), path_len(brh)))

    legs = []
    for name, net, u302_in, u302_out, mcu in (
            ("D+", USB_DP, "U302.3", "U302.4", "%s.33" % QFN),
            ("D-", USB_DM, "U302.1", "U302.6", "%s.32" % QFN)):
        src = "J301.%s" % ("B6" if net == USB_DP else "A7")
        # connector -> U302: vertical clear of the CC resistors, then 45 deg,
        # then into the pad. The two legs turn at the same y, so their
        # diagonals are automatically USB_PITCH apart.
        t = cop.pad(u302_in)
        x0 = run[net]
        p1 = [(x0, pady), (x0, USB_TURN_Y),
              (t[0], USB_TURN_Y + abs(t[0] - x0)), (t[0], t[1])]
        why = cop.path_clear(p1, USB_W, "F.Cu", net, (src, u302_in, u302_out))
        l1 = 0.0
        if why:
            cop.fails.append("USB %s connector leg blocked: %s" % (name, why))
        else:
            cop.add_path(p1, USB_W, "F.Cu", net)
            l1 = path_len(p1)
        # U302 -> MCU: one lane each, D- inside. The lane has to clear the
        # R307 pull-up's pads (y 29.20) and U302's own row (y 27.94), and the
        # two verticals come up between MCU pad 34's stub and pad 31's, which
        # is why each leg turns north at its own pad's x.
        a, b = cop.pad(u302_out), cop.pad(mcu)
        lane = USB_MCU_LANE[name]
        # Octilinear, not Manhattan. Both legs leave the lane on a 45 degree
        # diagonal and come into the pad vertically, so the pair keeps its
        # spacing while the corner is cut: on this placement that is 4.7 mm
        # off each leg, which is what keeps the 40 mm budget of ADR 0003
        # component breakdown 3 after the MCU had to move 4 mm back from the
        # receptacle to make room for the Kelvin taps. The L shape is kept as
        # a fallback for a pose where the diagonal does not fit.
        dx = abs(b[0] - a[0])
        forms = []
        if lane + dx <= b[1] - 0.05:
            forms.append([(a[0], a[1]), (a[0], lane),
                          (b[0], lane + dx), (b[0], b[1])])
        forms.append([(a[0], a[1]), (a[0], lane), (b[0], lane), (b[0], b[1])])
        l2, why = 0.0, None
        for p2 in forms:
            why = cop.path_clear(p2, USB_W, "F.Cu", net, (u302_out, mcu))
            if why is None:
                cop.add_path(p2, USB_W, "F.Cu", net)
                l2 = path_len(p2)
                break
        if l2 == 0.0:
            cop.fails.append("USB %s MCU leg blocked: %s" % (name, why))
        legs.append((name, l1, l2, l1 + l2))
    for name, l1, l2, tot in legs:
        print("  %-3s connector->U302 %6.2f mm   U302->MCU %6.2f mm   "
              "total %6.2f mm" % (name, l1, l2, tot))
    if all(l[3] > 0 for l in legs):
        skew = abs(legs[0][3] - legs[1][3])
        print("  pair: D+ %.2f mm, D- %.2f mm, skew %.2f mm (budget 1.00), "
              "0 vias anywhere on either net, %.2f mm track / %.2f mm gap "
              "coupled on the long connector segment, 0.30 mm gap on the "
              "U302->MCU lanes (U302's own 1.9 mm pin pitch forces the "
              "widening). Budget 40 mm: %s"
              % (legs[0][3], legs[1][3], skew, USB_W, USB_GAP,
                 "PASS" if max(l[3] for l in legs) <= 40.0 else "OVER"))
        res["dp"], res["dm"], res["skew"] = legs[0][3], legs[1][3], skew
    # ADR 0003 component breakdown 3 asks for the pair "over unbroken bottom
    # ground". The pair's own F.Cu copper keeps other F.Cu off it, but
    # nothing keeps the router from crossing UNDER it on B.Cu and cutting the
    # reference - it did, with +3V3. A User.2 band along every segment of the
    # pair is what the router reads with --keepout, and it costs almost
    # nothing on F.Cu because the locked pair is already there: 0.15 mm off
    # the centre line is the pair's own half width plus 0.05.
    nb = 0
    for (a, b, hw, lay, net) in list(cop.segs):
        if net in (USB_DP, USB_DM) and lay == "F.Cu":
            add_user_poly(cop, seg_band(a, b, USB_KEEP), pcbnew.User_2)
            nb += 1
    print("  %d User.2 band(s) along the pair, %.2f mm off the centre line: "
          "the router may not cross under it on B.Cu" % (nb, USB_KEEP))

    for a, b in (("J301.A5", "R305.1"), ("J301.B5", "R306.1")):
        cop.trace("CC pull-down %s" % a, a, b, W_SIG,
                  stubs=(0.0, 0.5, 0.9, 1.3))
    print("  CC1/CC2 pull-downs at the connector, one on each side of the "
          "pair (place.py moved them there); VBUS and GND are separate and "
          "not part of the pair")
    return res


# ================================================= same-net pad bridges ===
# Two footprints carry pad pairs that are ONE node on the schematic and two
# separate pieces of copper on the board. kicad-cli counts each as an
# unconnected pad pair and no router can close them, because there is no
# ratsnest route to find - the parts join them internally.
#
#   U302 (USBLC6-2SC6) brings D+ out on pins 3 AND 4 and D- on pins 1 AND 6;
#   the die joins each pair. The bridge is a stub off the signal, not a
#   detour in it - the run still goes J301 -> pin 3 -> die -> pin 4 -> MCU -
#   so it costs the pair no length. It is drawn straight across the package,
#   which is where the two pads face each other, and it clears pins 2 and 5
#   (GND and VBUS, 0.95 mm away in x) by 0.55 mm.
#
#   SW401's two mounting lugs both carry the pad number MP, so KiCad invents
#   the net unconnected-(SW401-PadMP) for them. Nothing else is on it and the
#   schematic has no node for it, so a short link between the two lugs is the
#   only thing that can close it. It runs straight down x = 88, under the
#   encoder's body, 7.5 mm clear of every other pad of the part.
#
# (label, ref, pad a, pad b, width, inset) - `inset` is how far inside each
# pad's own copper the link starts, None to start at the pad centre (which is
# what a THT lug with a 0.2 mm annular ring needs).
BRIDGES = [
    ("U302 D+ across the die", "U302", "3", "4", USB_W, 0.2),
    ("U302 D- across the die", "U302", "1", "6", USB_W, 0.2),
    ("SW401 mounting lugs", "SW401", "MP", "MP", W_SIG, None),
]


def _pads_numbered(cop, ref, num):
    return [p for p in cop.fps[ref].Pads() if p.GetNumber() == num]


def _step_in(box, ctr, u, inset):
    """Walk from a pad's centre towards `u` until just inside its own copper."""
    if inset is None:
        return ctr
    t = 1e9
    for lo, hi, c, d in ((box[0], box[2], ctr[0], u[0]),
                         (box[1], box[3], ctr[1], u[1])):
        if abs(d) < 1e-9:
            continue
        t = min(t, (hi - c) / d if d > 0 else (lo - c) / d)
    t = max(0.0, t - inset)
    return (round(ctr[0] + u[0] * t, 3), round(ctr[1] + u[1] * t, 3))


def step6b_bridges(cop):
    print("\n--- 6b. same-net pad bridges (the netlist asks, no router can)")
    n = 0
    for label, ref, na, nb, w, inset in BRIDGES:
        if ref not in cop.fps:
            cop.fails.append("%s: no %s on the board" % (label, ref))
            continue
        pa = _pads_numbered(cop, ref, na)
        pb = _pads_numbered(cop, ref, nb) if nb != na else pa[1:]
        if not pa or not pb:
            cop.fails.append("%s: %s has no pad %s/%s" % (label, ref, na, nb))
            continue
        a, b = loc(pa[0].GetPosition()), loc(pb[0].GetPosition())
        net = pa[0].GetNetname()
        d = dist(a, b)
        u = ((b[0] - a[0]) / d, (b[1] - a[1]) / d)
        boxa = (tomm(pa[0].GetBoundingBox().GetLeft()) - ORIGIN[0],
                tomm(pa[0].GetBoundingBox().GetTop()) - ORIGIN[1],
                tomm(pa[0].GetBoundingBox().GetRight()) - ORIGIN[0],
                tomm(pa[0].GetBoundingBox().GetBottom()) - ORIGIN[1])
        boxb = (tomm(pb[0].GetBoundingBox().GetLeft()) - ORIGIN[0],
                tomm(pb[0].GetBoundingBox().GetTop()) - ORIGIN[1],
                tomm(pb[0].GetBoundingBox().GetRight()) - ORIGIN[0],
                tomm(pb[0].GetBoundingBox().GetBottom()) - ORIGIN[1])
        p0 = _step_in(boxa, a, u, inset)
        p1 = _step_in(boxb, b, (-u[0], -u[1]), inset)
        ign = tuple("%s.%s" % (ref, x) for x in {na, nb})
        why = cop.path_clear([p0, p1], w, "F.Cu", net, ign)
        if why:
            cop.fails.append("%s: %s" % (label, why))
            continue
        cop.add_path([p0, p1], w, "F.Cu", net)
        cop.lengths[label] = path_len([p0, p1])
        n += 1
        print("  %-26s %s pads %s-%s, %.2f mm of %.2f mm F.Cu on %s"
              % (label, ref, na, nb, path_len([p0, p1]), w, net))
    return n


# ================================================== explicit signals =====
# Four nets the two-segment search cannot do and the router did not finish.
# Same shape as POWER_EXPLICIT: a waypoint is "REF.PAD", "ESCAPE.<QFN pad>"
# (the far end of that pad's fanned escape, so the path follows the placement
# rather than a hard-coded number) or a literal (x, y); consecutive points are
# H, V or exactly 45 degrees apart and the whole polyline is clearance-checked
# as one before anything is drawn. A path that fails falls back to the plain
# radial stub for its QFN pad, so a pad is never left bare.
#
# They are drawn HERE - after the fanout, the crystal, VDDA, the USB pair and
# the pad bridges, and BEFORE the decoupling, the power block, the filters and
# the rails - because every lane below is one a later step would otherwise
# take. The +3V3 tree in particular ran a 0.5 mm trunk straight across two of
# them (x = 51.2 / y = 38.45), which is why VCAP1 and VIN_SENSE came out of
# the third pass undrawable and then unroutable.
SIGNAL_EXPLICIT = [
    # --- GATE_IN: MCU pad 29 to the gate driver's input pulldown ------------
    # The strike signal. It has to cross the 14 mm of board between the QFN's
    # north row and the driver, and there are only two lanes:
    #   x = 46.75, straight north out of the pad - which walls PA10's pull-up
    #     (pad 31 -> R307, a 45-degree run to x = 49.0) off from its resistor
    #     and blocks LCD_RST's way west to the LCD header;
    #   x = 49.90, east of R307 - which only costs +3V3 the EAST approach to
    #     R307 pad 2, and the rail tree can reach that pad from C303 in the
    #     west instead.
    # The second one is taken. The diagonal's line is pinned within 0.11 mm:
    # x + y = 86.11 clears R307 pad 1's corner by 0.29 mm (needs 0.25) and
    # pad 28's radial stub by 0.39 mm (needs 0.35), and PA10's own 45-degree
    # run is parallel to it 0.67 mm away.
    ("GATE_IN pad 29 to the driver", "GATE_IN", W_FINE, [
        "U301.29", (46.750, 39.360), (49.900, 36.210), (49.900, 26.225),
        "R202.1"]),
    # --- VCAP1: MCU pad 22 to its 2.2 uF -----------------------------------
    # C308 is in the second ring, 7.79 mm away, and the only way there is the
    # 0.55 mm slot between C302 pad 2 and C104 pad 1 at x = 53.5, which takes
    # a 0.20 mm track with 0.025 mm to spare on each side. 10.79 mm of copper
    # for a 7.79 mm straight line; the lever if that is too much for the
    # internal regulator is placement, not copper - C308 is a second-ring part
    # behind a first-ring cap.
    ("VCAP1 pad 22 to C308", "Net-(U301-VCAP1)", W_FINE, [
        "U301.22", (53.500, 42.250), (53.500, 35.750), "C308.1"]),
    # --- VIN_SENSE: the divider, its filter cap and the ADC pin -------------
    # R102/R103 divide VIN down, C104 filters it and pad 18 reads it. All
    # three pads sit in the x 54..56 column, so this is not a board crossing -
    # it is three short hops that RC_MAX (6.5 mm) put just out of reach of the
    # filter step (6.74, 6.86 and 7.93 mm) and that the router then routed
    # only partly, so the "complete" gate dropped the whole net.
    # The trunk runs east out of pad 18's escape to a lane at x = 55.25, which
    # is the 0.65 mm slot between C207's two pads, and branches there: north
    # over C104 and south to R103. NTC's own filter link (pad 19 -> C207) runs
    # diagonally across this corner 1.26 mm away - the two nets come off
    # adjacent QFN pads and their caps are the other way round, so on one
    # layer they would have to cross.
    ("VIN_SENSE pad 18 escape to the lane", "VIN_SENSE", W_SIG, [
        "ESCAPE.18", (55.250, 44.850)]),
    ("VIN_SENSE lane to C104", "VIN_SENSE", W_SIG, [
        (55.250, 44.850), (55.250, 40.300), (54.450, 39.500), "C104.1"]),
    ("VIN_SENSE lane to R103", "VIN_SENSE", W_SIG, [
        (55.250, 44.850), (55.250, 46.175), "R103.1"]),
    # R102 pad 2 to R103 pad 1: the divider's own mid-point, 7.93 mm down the
    # east side of R217 and R212, which both stand in the straight line.
    # x = 57.25 and not 56.60, which is the shortest lane that clears: at
    # 56.60 this trace sits 0.375 mm off R217 pad 1 and walls the +3V3 tree
    # out of its EAST approach to that pad, which cost the rail an island.
    # 57.25 leaves a 0.65 mm slot there, enough for the tree's 0.50 mm trunk,
    # and costs this leg 0.54 mm.
    ("VIN_SENSE R103 to R102", "VIN_SENSE", W_SIG, [
        "R103.1", (57.250, 48.175), (57.250, 52.925), "R102.2"]),
    # --- I_SENSE: the op-amp's output filter at the ADC pin ------------------
    # FOURTH PASS, in again. These two paths were tried in the fourth pass,
    # measured well (5.80 and 1.94 mm, both clear) and made the board WORSE:
    # they take the 0.80 mm slot between FB301 pad 1 and R217 pad 2, which is
    # the only way through that corner, and with them in it BOTH winning net
    # orderings stopped being able to finish GND - the completeness gate then
    # dropped GND whole and the board came out at 7 open pad pairs instead of
    # 4. So the cost was never I_SENSE's own lane, it was GND's stitching
    # needing the same corner.
    #
    # That is exactly what step 3b took away. GND is now closed by this
    # script, pad by pad and along the two long edges, and is not in the
    # router's scope at all, so the corner is I_SENSE's to take. Last, after
    # every VIN_SENSE leg, because VIN_SENSE has three pads in the same column
    # and only one lane each.
    ("I_SENSE pad 16 escape to R212", "I_SENSE", W_SIG, [
        "ESCAPE.16", (52.500, 46.250), (53.375, 47.125),
        (53.375, 50.450), "R212.2"]),
    ("I_SENSE R212 to its filter cap", "I_SENSE", W_SIG, [
        "R212.2", (53.925, 52.300), "C205.1"]),
]


# Explicit signal paths that have to change layer, same shape as POWER_LAYERED:
# a list of (layer, waypoints) runs, and the point two consecutive runs share
# gets a via.
#
# SEVENTH PASS, and PB2 is the only entry. Pad 20's fanned escape ends at
# (52.338, 43.450) with a via of its own already there, and R303 pad 1 - PB2's
# series resistor on the way to the LCD - is 6.22 mm away at (54.175, 37.500).
# Every F.Cu way north out of that escape is closed, and by this script's own
# copper rather than by congestion:
#
#   - VCAP1's explicit path runs east along y = 42.250 from pad 22 to
#     x = 53.500 and then north, so the escape is SOUTH of a wall that spans
#     the whole x 49.4..53.5 band. Crossing it means going round its corner,
#     i.e. east of x = 53.850 (0.35 mm of air for a 0.20 mm track against a
#     0.20 mm one);
#   - the only slot north of there is the 0.80 mm gap between C302 pad 2
#     (right edge 53.225) and C207 pad 1 (left edge 54.025), and VCAP1's own
#     lane at x = 53.500 already has it: what is left on its east side reaches
#     x = 53.775, and PB2 would need x >= 53.850. Short by 0.075 mm;
#   - the next slot east, between C207's two pads, is VIN_SENSE's x = 55.250
#     lane, and east of C207 again means crossing VIN_SENSE's y = 44.850
#     trunk or NTC's diagonal from pad 19's escape to C207 pad 1.
#
# So PB2 drops to B.Cu at the via its escape already carries - no new via at
# that end - crosses under the C207 / C104 column on the bottom layer and comes
# back up in the 1.05 mm gap between R303 pad 1 (bottom edge 37.975) and C104
# pad 1 (top edge 39.025), where a 0.6/0.3 via clears both by 0.525 mm and
# VCAP1's x = 53.500 lane by 0.675 mm. 5.71 mm of B.Cu, one new via, and a
# 1.00 mm F.Cu stub straight north into the pad.
#
# The B.Cu leg is drawn diagonal-then-vertical on purpose: the mirror image
# (vertical at x = 52.338 first) would put its slot in the pour directly under
# C302 pad 2, the MCU's own VDD decoupling ground, where this one runs under
# C207 pad 1 and C104 pad 1 - two signal pads whose return path nothing needs.
SIGNAL_LAYERED = [
    ("PB2 pad 20 escape to R303", "Net-(U301-PB2)", W_FINE, [
        ("B.Cu", ["ESCAPE.20", (54.175, 41.613), (54.175, 38.500)]),
        ("F.Cu", [(54.175, 38.500), "R303.1"]),
    ]),
]


def _way(cop, q):
    """One SIGNAL_EXPLICIT waypoint -> (x, y)."""
    if isinstance(q, str) and q.startswith("ESCAPE."):
        num = q.split(".", 1)[1]
        if num not in cop.qfn_all_end:
            raise KeyError("QFN pad %s has no fanned escape to start from"
                           % num)
        return cop.qfn_all_end[num][0]
    return cop.resolve(q)


def step6c_signals(cop):
    print("\n--- 6c. explicit signal paths")
    ok = 0
    for label, net, w, pts in SIGNAL_EXPLICIT:
        out = [_way(cop, q) for q in pts]
        ign = tuple(q for q in pts
                    if isinstance(q, str) and not q.startswith("ESCAPE."))
        why = cop.path_clear(out, w, "F.Cu", net, ign)
        if why:
            cop.fails.append("%s (explicit): %s" % (label, why))
            continue
        cop.add_path(out, w, "F.Cu", net)
        cop.lengths[label] = path_len(out)
        ok += 1
        print("  %-38s %6.2f mm at %.2f mm on F.Cu (straight line %.2f mm)"
              % (label, path_len(out), w, dist(out[0], out[-1])))
    # The layered ones last: they cross under copper the F.Cu paths above have
    # just claimed, so they have to know where it ended up.
    for label, net, w, runs in SIGNAL_LAYERED:
        got = layered(cop, label, net, w, runs)
        if got is None:
            continue
        ok += 1
        a = _way(cop, runs[0][1][0])
        b = _way(cop, runs[-1][1][-1])
        print("  %-38s %6.2f mm at %.2f mm over %d layer(s), %d via(s) "
              "(straight line %.2f mm)"
              % (label, got[0], w, len({r[0] for r in runs}), got[1],
                 dist(a, b)))
    # A QFN pad whose explicit path did not come out keeps the plain radial
    # stub step 2 skipped for it, or the router has nothing to pick up.
    for num in QFN_EXPLICIT_PADS:
        spec = "%s.%s" % (QFN, num)
        if any(s[4] == cop.padnet(spec) for s in cop.segs
               if dist(s[0], cop.pad(spec)) < 1e-6):
            continue
        net = cop.padnet(spec)
        s = plain_stub(cop, spec, net)
        cop.notes.append("explicit path off pad %s failed; %s" % (
            num, "kept a %.2f mm radial stub" % s if s is not None
            else "NO copper on the pad at all"))
    print("  %d of %d explicit signal paths drawn"
          % (ok, len(SIGNAL_EXPLICIT) + len(SIGNAL_LAYERED)))
    return ok


# ============================================================= power =====
POWER = [
    # VIN chain, in the power block
    ("VIN jack to fuse", "J101.1", "F101.1", 0.8),
    ("VIN fuse to P-FET drain", "F101.2", "Q101.2", 0.8),
    ("VIN P-FET source to TVS", "Q101.3", "D102.1", 0.8),
    ("VIN TVS to bulk cap", "D102.1", "C101.1", 0.8),
    ("VIN bulk cap to buck CIN", "C101.1", "C106.1", 0.8),
    # flyback loop, 1.0 mm, under the terminal
    ("COIL_NEG terminal to SS110", "J201.2", "D201.2", 1.0),
    ("CLAMP SS110 to SMBJ24A", "D201.1", "D202.1", 1.0),
    ("VIN SMBJ24A to C102", "D202.2", "C102.1", 1.0),
    ("VIN C102 to C103", "C102.1", "C103.1", 1.0),
    ("VIN terminal pin 1 to C102", "J201.1", "C102.1", 1.0),
    ("VIN C103 to bypass FET source", "C103.1", "Q202.3", 0.5),
    # gate drive
    # D202.1 -> Q202.2 is NOT here: it is POWER_LAYERED below, because the
    # only way east out of the clamp diode crosses the COIL_NEG trunk.
    ("GATE driver out to R201", "U201.5", "R201.1", 0.4),
    ("GATE R201 to FET gate", "R201.2", "Q201.1", 0.4),
    ("GATE pulldown at the FET", "R203.1", "Q201.1", 0.25),
    ("GATE_IN pulldown at the driver", "R202.1", "U201.3", 0.25),
    # shunt and its Kelvin taps
    ("SHUNT FET source to R204", "Q201.3", "R204.1", 1.0),
    # W_HC_MIN and not 0.2: the taps carry no current at all, so their width is
    # free electrically - what matters is that they leave the shunt pad's own
    # copper EDGE - but they are on SHUNT_HI, and the .kicad_dru holds every
    # HighCurrent track to 0.5 mm. Widening them is the cheapest of the three
    # ways to satisfy that rule; the geometry still has to clear, and the run
    # says so if it does not.
    ("Kelvin tap to R209", "R204.1", "R209.1", W_HC_MIN),
    ("Kelvin tap to R213", "R204.1", "R213.1", W_HC_MIN),
    ("R209 to op-amp A+", "R209.2", "U202.3", 0.2),
    ("op-amp A+ filter cap", "C204.1", "U202.3", 0.2),
    ("R213 to op-amp B+", "R213.2", "U202.5", 0.2),
    ("op-amp A- feedback", "R210.2", "U202.2", 0.2),
    ("op-amp A- to R211", "R211.1", "U202.2", 0.2),
    ("op-amp A out to R210", "R210.1", "U202.1", 0.2),
    ("OC_REF divider top", "R215.2", "U202.6", 0.2),
    ("OC_REF divider bottom", "R216.1", "U202.6", 0.2),
    ("OC_REF cap", "C206.1", "U202.6", 0.2),
    ("OC_TRIP op-amp out to R214", "U202.7", "R214.1", 0.25),
    ("OC_REF to op-amp B-", "R214.2", "U202.5", 0.2),
    # buck
    ("SW node to the inductor", "U101.8", "L101.1", 0.8),
    ("buck output to ORing diode", "L101.2", "D105.2", 0.5),
    ("FB divider top at the output", "R109.1", "L101.2", 0.25),
    ("FB divider to the FB pin", "R110.1", "U101.5", 0.25),
    ("FB divider mid", "R109.2", "R110.1", 0.25),
    ("FB feed-forward", "C109.1", "R109.2", 0.25),
    ("FB feed-forward 2", "C110.1", "C109.1", 0.25),
    ("EN/UVLO divider", "R105.2", "U101.3", 0.25),
    ("EN/UVLO divider mid", "R106.1", "R105.2", 0.25),
    # W_HC_MIN, not 0.4: this leg is on VIN, which the .kicad_dru holds to
    # 0.5 mm however little current an enable divider draws.
    ("EN/UVLO top to VIN", "R105.1", "C105.1", W_HC_MIN),
    ("RON to the buck", "R107.1", "U101.4", 0.25),
    # +5 V ORing and the LDO
    ("+5V ORing to VBUS diode", "D105.1", "D103.1", 0.5),
    ("+5V to the LDO input", "D103.1", "C113.1", 0.5),
    ("VBUS to the receptacle", "D103.2", "J301.A4", 0.5),
    ("buck output caps", "C111.1", "C112.1", 0.5),
    ("buck output cap to the diode", "C111.1", "D105.2", 0.5),
]

# The sense side joins the pour ONLY at the shunt's ground pad. These pads
# are therefore left OUT of the GND stitching and wired to U202 pin 4, which
# runs to R204 pad 2.
# The SENSE REFERENCE pads: the ground ends of the shunt sense network and the
# op-amp's own ground pin. These reach the pour through R204's ground pad and
# nowhere else, so they are kept out of the ground stitching and wired here.
#
# C203.2 is deliberately NOT one of them, and neither is C205.2. C203 is the
# op-amp's +3V3 bypass: its ground carries the supply's return current, not a
# measurement, and tying it to the single point instead of to the plane under
# it turns 15 mm of 0.20 mm trace around the op-amp into the bypass's return
# path, which is worse for the op-amp than the thing the rule is protecting
# against. C205 is the I_SENSE RC cap at the MCU pin, 20 mm away at the other
# end of the board. Both take an ordinary stitching via.
SENSE_GND = ("C204.2", "R211.2", "R216.2", "C206.2")
SENSE_TIE = "U202.4"
SHUNT_GND = "R204.2"
SHUNT_VIAS = ((-0.95, -0.95), (-0.95, 0.95), (-1.55, 0.0))


# Paths whose geometry is dictated rather than searched: waypoints are pad
# specs or (x, y), and the whole polyline is clearance-checked as one.
POWER_EXPLICIT = [
    # The SS110 -> FET drain leg has to pass east of the SMBJ24A: at 1.0 mm
    # and the 0.40 mm HighCurrent clearance the 2.0 mm slot west of it does
    # not take the track, and the slot between D202 and C102 does.
    ("COIL_NEG SS110 to FET drain", "/Driver/COIL_NEG", 1.0,
     ["D201.2", (67.0, 15.0), (67.0, 24.0)]),
]


# Paths that have to change layer, as a list of (layer, waypoints) runs; the
# point two consecutive runs share gets a via. Everything is still checked in
# full before anything is drawn.
#
# CLAMP's tap to the bypass FET is the one path on this board that cannot stay
# on top. D202 (the SMBJ24A) sits with VIN on its east pad, and the only two
# ways east out of D202's west pad are blocked by copper this script drew
# first and by ADR geometry:
#   - the band between D202 and Q201's DPAK tab (y 20.65..22.60) runs into the
#     1.0 mm COIL_NEG trunk at x = 67, which drops from the SS110 into the
#     FET tab and is a wall from y = 15 to y = 22.6. The slot east of it is
#     0.40 mm wide and HighCurrent needs 0.40 mm of air on each side alone;
#   - the corridor north of the terminal (y ~ 13) is crossed by the 1.0 mm
#     VIN leg from J201 pin 1 to C102.
# Left to the router, this tap came out 50 mm, down the right-hand edge of the
# board and back west. It is 3.75 mm of B.Cu between two vias instead: the
# slot that costs the pour sits SOUTH of the flyback loop (y 14..20), not
# under it, so the loop's return path is untouched and the scripted loop
# itself is still 20.26 mm.
POWER_LAYERED = [
    ("CLAMP D202 to the bypass FET", "/Driver/CLAMP", 0.5, [
        ("F.Cu", ["D202.1", (64.85, 21.6)]),
        ("B.Cu", [(64.85, 21.6), (68.60, 21.6)]),
        # 71.65 and no further east: Q202's gate pad is at x = 72.325 and
        # CLAMP is a HighCurrent net, so a 0.5 mm track needs 0.65 mm of air
        # from its centre line.
        ("F.Cu", [(68.60, 21.6), (71.65, 21.6), (71.65, 23.95), "Q202.2"]),
    ]),
]


def layered(cop, label, net, width, runs):
    """Draw one multi-layer explicit path, or report it and draw nothing."""
    built, vias = [], []
    for i, (layer, pts) in enumerate(runs):
        out = [_way(cop, q) for q in pts]
        ign = tuple(q for q in pts
                    if isinstance(q, str) and not q.startswith("ESCAPE."))
        why = cop.path_clear(out, width, layer, net, ign)
        if why:
            cop.fails.append("%s (%s run %d): %s" % (label, layer, i + 1, why))
            return None
        built.append((layer, out, ign))
        if i:
            vias.append(out[0])
    for p in vias:
        why = cop.via_clear(p, net)
        if why:
            cop.fails.append("%s: via at (%.2f, %.2f) blocked: %s"
                             % (label, p[0], p[1], why))
            return None
    total = 0.0
    for layer, out, _ign in built:
        cop.add_path(out, width, layer, net)
        total += path_len(out)
    for p in vias:
        cop.add_via(p, net)
    cop.lengths[label] = total
    return total, len(vias)


def zroute(cop, a, b, width, net, ign, axis="h", step=0.05, reach=7.0):
    """One-turn or two-turn path from a to b with the middle line SCANNED.

    `trace` tries a fixed ladder of perpendicular offsets, which is enough
    when there is a clear lane somewhere near the straight line. The sense
    side's ground trunk has to thread the 1.1 mm gaps between the op-amp's
    feedback resistors and between the two Kelvin taps, and the lane that
    works is 0.05 mm wide in the choice of offset. So scan it: every candidate
    is still clearance-checked in full before anything is drawn, and the
    shortest one that clears wins.
    """
    lo, hi = (sorted((a[1], b[1])) if axis == "h" else sorted((a[0], b[0])))
    lo, hi = lo - reach, hi + reach
    cands = []
    n = int((hi - lo) / step) + 1
    for i in range(n):
        m = lo + i * step
        pts = ([a, (a[0], m), (b[0], m), b] if axis == "h"
               else [a, (m, a[1]), (m, b[1]), b])
        out = [pts[0]]
        for q in pts[1:]:
            if dist(q, out[-1]) > 1e-9:
                out.append(q)
        cands.append((round(path_len(out), 2), out))
    cands.sort(key=lambda c: c[0])
    for _l, pts in cands:
        if cop.path_clear(pts, width, "F.Cu", net, ign) is None:
            return pts
    return None


def sense_tie(cop, label, a_spec, b_spec, width):
    """Draw one leg of the sense-side ground, trying hard before giving up."""
    pts = cop.trace(label, a_spec, b_spec, width,
                    stubs=(0.0, 0.5, 0.8, 1.1, 1.5, 2.0, 2.6), quiet=True)
    if pts:
        return pts
    a, b = cop.pad(a_spec), cop.pad(b_spec)
    ign = (a_spec, b_spec)
    for axis in ("h", "v"):
        pts = zroute(cop, a, b, width, "GND", ign, axis=axis)
        if pts:
            cop.add_path(pts, width, "F.Cu", "GND")
            cop.lengths[label] = path_len(pts)
            return pts
    return None


def step7_power(cop):
    print("\n--- 7. power paths")
    ok = 0
    for label, net, w, pts in POWER_EXPLICIT:
        out = [cop.resolve(q) for q in pts]
        ign = tuple(q for q in pts if isinstance(q, str))
        why = cop.path_clear(out, w, "F.Cu", net, ign)
        if why:
            cop.fails.append("%s (explicit): %s" % (label, why))
        else:
            cop.add_path(out, w, "F.Cu", net)
            cop.lengths[label] = path_len(out)
            ok += 1
    for label, net, w, runs in POWER_LAYERED:
        got = layered(cop, label, net, w, runs)
        if got:
            ok += 1
            print("  %s: %.2f mm over %d run(s) on %d layer(s), %d via(s)"
                  % (label, got[0], len(runs),
                     len({r[0] for r in runs}), got[1]))
    for label, a, b, w in POWER:
        if cop.trace(label, a, b, w, stubs=(0.0, 0.6, 0.9, 1.3, 1.8, 2.4)):
            ok += 1
    print("  %d of %d power/driver traces drawn"
          % (ok, len(POWER) + len(POWER_EXPLICIT) + len(POWER_LAYERED)))
    # single-point ground at the shunt
    # The trunk first, then a TREE: each remaining sense pad is wired to
    # whichever pad is already on the trunk and nearest to it, not all of them
    # back to pin 4. The OC_REF pads sit on the op-amp's east face and pin 4 is
    # on its west, so a star at pin 4 asks three of them to go right round the
    # part; chained, each hop is a couple of millimetres.
    #
    # 0.25 mm, not 0.50: this run carries no current at all - it is the sense
    # side's only reference - and 0.50 mm cannot get past the op-amp's own
    # feedback trio, which stands between pin 4 and the shunt.
    n = 0
    joined = [SHUNT_GND]
    if sense_tie(cop, "sense ground trunk to the shunt", SENSE_TIE, SHUNT_GND,
                 0.25):
        n += 1
        joined.append(SENSE_TIE)
    else:
        cop.fails.append("sense ground trunk %s -> %s: no clear F.Cu path, "
                         "even scanned" % (SENSE_TIE, SHUNT_GND))
    todo = list(SENSE_GND)
    while todo:
        cand = sorted((dist(cop.pad(a), cop.pad(b)), a, b)
                      for a in todo for b in joined)
        a = cand[0][1]
        got = None
        for _d, aa, b in cand:
            if aa != a:
                continue
            got = sense_tie(cop, "sense ground %s" % a, a, b, 0.2)
            if got:
                break
        todo.remove(a)
        if got:
            n += 1
            joined.append(a)
        else:
            cop.fails.append("sense ground %s: no clear F.Cu path to any pad "
                             "already on the trunk, even scanned" % a)
    c = cop.pad(SHUNT_GND)
    nv = 0
    for dx, dy in SHUNT_VIAS:
        p = (round(c[0] + dx, 3), round(c[1] + dy, 3))
        if cop.via_clear(p, "GND", (SHUNT_GND,)) is None:
            cop.add_via(p, "GND")
            nv += 1
    print("  sense-side ground: %d of %d ties into %s, then one run to %s "
          "with a %d-via cluster there - the only tie of the sense side into "
          "the pour" % (n, len(SENSE_GND) + 1, SENSE_TIE, SHUNT_GND, nv))
    return ok


# =========================================================== escapes =====
# Dictated escapes: a short piece of copper off a pad that is BOXED IN, with a
# via at its far end, so that what the router picks up is a track end in open
# copper instead of a pad it cannot reach. Same idea as power_escape and as
# every QFN escape, but with the direction chosen rather than searched, because
# in both cases here the one corridor out is known and a search would take the
# wrong one first.
#
# --- NRST off C309 ----------------------------------------------------------
# SEVENTH PASS, and it is VDDA_LAYERED's bill. NRST's four pads are U301 pad 7
# and C309 pad 1 (one piece of copper, joined by the first-ring trace), SW302's
# two halves at y = 19.125 and J302 pad 4 at the rear edge, so the cluster at
# the MCU's south-west corner has to reach y = 19 somehow. In the sixth pass
# the router did it by dropping to B.Cu at (46.800, 49.850), south-west of
# C309 - the one direction that is neither the crystal island nor the pin row -
# and running down to (46.800, 52.300).
#
# Adding VDDA's two vias at (47.250, 48.225) and (48.250, 49.225) put
# /MCU/VDDA into the ring of LOCKED copper round that cluster, and the p10 run
# is what that costs: NRST failed on all three orderings AND on the mop-up
# (`ROUTE FAILED - no rippable blockers found ... the box also includes
# PROTECTED net(s) ... '/MCU/VDDA' (locked) ... within 3mm of the failing
# endpoint`), and because the mop-up ran at --track-width 0.20 it also ripped
# VBUS and re-laid it at 0.20 mm, which the size gate then dropped whole. One
# boxed-in cluster, six pad pairs.
#
# So the corridor is scripted instead of hoped for: 0.74 mm of 0.25 mm F.Cu
# south-west out of C309 pad 1 and a 0.6/0.3 via at (46.850, 49.800), which
# clears the crystal ground guard at x = 46.200 by 0.650 mm where 0.600 is
# needed and C309 pad 2 by 0.525 where 0.450 is. It is drawn in step 7c, before
# the ground stitching, so C309 pad 2's own stub has to find another direction
# rather than this one.
#
# --- +5V off C202 -----------------------------------------------------------
# The one +5V pad pair the router has never closed is
# C201.1 <-> D105.1, 39.93 mm across the board, and the reason it gives is not
# congestion: "the failing endpoint is boxed in by copper copper.py LOCKED".
# That is exactly right, and it is measurable. C201 is the gate driver's supply
# cap and its only two ways out of the block are
#
#   - NORTH, up the empty column at x = 51.275 between J302 pad 5 (right edge
#     48.010) and the driver, and
#   - WEST, along the 1.05 mm lane at y = 24.500 between C201's own pads and
#     R202's,
#
# because south of it GATE_IN's pulldown leg runs east along y = 26.500 from
# x = 49.175 to 51.812, GATE_IN's main lane is a wall at x = 49.900 from
# y = 26.225 to 36.210, and the two ground stitching vias at (50.487, 28.000)
# and (51.087, 28.950) close the 2.1 mm slot east of that lane.
#
# The trunk itself is NOT scripted, and the corridor search says why. On F.Cu
# the shortest route that clears at 0.50 mm is 111.6 mm - up the rear, along
# y = 4.5 past the USB receptacle and all the way down the LEFT edge at x = 7 -
# because the x = 23.5 lane between the receptacle and the buck only takes
# 0.30 mm, at which the shortest route is still 94.96 mm and goes diagonally
# across the rear right, walling J302's four signal pads and SW301's +3V3 from
# the south. Either one is 2.4-2.8x the straight line and costs more corridors
# than the pad pair it closes. On B.Cu the direct 40 mm diagonal crosses UNDER
# the USB pair at (41.89, 33.74), which ADR 0003 component breakdown 3 forbids
# and the User.2 bands enforce; the pair's F.Cu run from J301 to the MCU is one
# unbroken wall from (28.250, 7.245) to (45.250, 40.562), so the only legal
# crossings are north of J301 (y < 6) or south of the MCU, and both of those
# are the long way round again.
#
# So what this step draws is the ESCAPE and not the trunk: 2.50 mm of 0.50 mm
# F.Cu north out of C202 - the northernmost +5V pad, tied to C201 by the
# scripted bypass leg - and a 0.6/0.3 via at the end of it, in open copper
# 2.0 mm clear of anything. The endpoint the router reports as boxed in is then
# a track END with a via on it, in the same position as every QFN escape, and
# the 40 mm crossing is the router's to make the way it makes VIN's 194 mm and
# VBUS's 68 mm. It stops at y = 19.000 on purpose: the reserved VIN corridor is
# y 14..17 and +3V3's own rear branch comes up x = 48.000.
ESCAPES = [
    ("NRST escape off C309, south-west", "NRST", W_SIG,
     ["C309.1", (47.250, 49.400), (46.850, 49.800)], True),
    ("+5V escape out of the driver's supply block", "+5V", W_RAIL,
     ["C202.1", (51.275, 19.000)], True),
]


def step7c_escapes(cop):
    print("\n--- 7c. escapes out of the boxed-in pads")
    for label, net, w, pts, want_via in ESCAPES:
        out = [cop.resolve(q) for q in pts]
        ign = tuple(q for q in pts if isinstance(q, str))
        why = cop.path_clear(out, w, "F.Cu", net, ign)
        if why:
            cop.fails.append("%s: %s" % (label, why))
            continue
        vwhy = cop.via_clear(out[-1], net, ign) if want_via else None
        cop.add_path(out, w, "F.Cu", net)
        cop.lengths[label] = path_len(out)
        if want_via and vwhy is None:
            cop.add_via(out[-1], net)
        print("  %-42s %5.2f mm at %.2f mm, ends (%.3f, %.3f)%s"
              % (label, path_len(out), w, out[-1][0], out[-1][1],
                 " + via" if want_via and vwhy is None else
                 " (no room for a via: %s)" % vwhy if want_via else ""))


# =========================================================== RC filters ===
RC = [
    ("16", "R212.2", W_SIG), ("16", "C205.1", W_SIG),      # I_SENSE
    ("18", "C104.1", W_SIG), ("18", "R103.1", W_SIG),      # VIN_SENSE
    ("19", "C207.1", W_SIG), ("19", "R217.2", W_SIG),      # NTC
    ("11", "C405.1", W_SIG), ("12", "C404.1", W_SIG),      # pedal
    ("40", "C401.1", W_SIG), ("41", "C402.1", W_SIG),
    ("43", "C403.1", W_SIG),                               # encoder debounce
    ("44", "R301.1", W_SIG),
    # ("20", "R303.1") was here and RC_MAX skipped it on every run: pad 20 to
    # R303 pad 1 is 7.45 mm and there is no F.Cu lane at any length. It is
    # SIGNAL_LAYERED's PB2 entry now, drawn in step 6c.
    ("31", "R307.1", W_SIG),
]
RC_CHAIN = [("R402.2", "C401.1"), ("R403.2", "C402.1"), ("R404.2", "C403.1"),
            ("R408.2", "C405.1"), ("R406.2", "C404.1"),
            # R212.1 -> R210.1 is NOT here: that is the whole I_SENSE run from
            # the op-amp's output to the filter at the MCU pin, ~11 mm across
            # the analog corner, not a local filter link. Drawn as one straight
            # 0.25 mm trace it cut six QFN escapes on the east and south rows.
            # It belongs to the router.
            ("R102.2", "R103.1")]
# 6.5 mm, down from 12.0. A "filter at the MCU pin" that is 8 mm away is not
# a filter link any more, and drawn as one straight 0.25 mm trace across the
# corner of the part it cut five QFN escapes on the east and south rows -
# I_SENSE from pad 16 to R212 did exactly that. Over this, the router gets it.
RC_MAX = 6.5


def step8_filters(cop):
    print("\n--- 8. the RC filters at the MCU pins")
    ok, skip = 0, []
    for num, tgt, w in RC:
        spec = "%s.%s" % (QFN, num)
        a, b = cop.pad(spec), cop.pad(tgt)
        if dist(a, b) > RC_MAX:
            skip.append("%s->%s %.1f mm" % (num, tgt, dist(a, b)))
            continue
        # A pad with a fanned escape is already 2.6-2.9 mm out of the part in
        # a lane of its own; the filter link carries on from THERE, not from
        # the pad, or it re-leaves the pad radially and runs into the
        # neighbouring lane it was fanned away from.
        if num in cop.qfn_end:
            end, d = cop.qfn_end[num]
            got = cop.trace("filter %s->%s" % (num, tgt), end, tgt, w,
                            stubs=(0.0, 0.4, 0.8, 1.2), adir=d,
                            ign_extra=(spec,))
        else:
            got = cop.trace("filter %s->%s" % (num, tgt), spec, tgt, w,
                            stubs=(QFN_STUB, QFN_STUB + 0.3, QFN_STUB + 0.7,
                                   QFN_STUB + 1.2))
        if got:
            ok += 1
    for a, b in RC_CHAIN:
        if dist(cop.pad(a), cop.pad(b)) > RC_MAX:
            skip.append("%s->%s" % (a, b))
            continue
        if cop.trace("filter chain %s->%s" % (a, b), a, b, W_SIG,
                     stubs=(0.0, 0.6, 0.9, 1.4)):
            ok += 1
    print("  %d of %d filter links drawn; left for the router (over %.0f mm): "
          "%s" % (ok, len(RC) + len(RC_CHAIN), RC_MAX,
                  ", ".join(skip) if skip else "none"))
    return ok


# ========================================================== rail trees ====
# The router has no notion of a power rail: it takes the pad pairs of +3V3 in
# whatever order its net ordering hands them and joins each to the nearest
# copper it has already laid, which came out as 229 mm of wandering and a ring
# round the MCU. This draws the rail as a TREE instead - repeatedly the
# SHORTEST hop between two pieces of copper of that net that are not yet one
# piece - which is a Kruskal minimum spanning tree over the pads, with the
# pads a hop has already joined collapsed into one node after every hop. That
# is the same shape the sense-side ground uses and for the same reason.
#
# Every hop is clearance-checked like any other scripted trace and tried at
# each width in turn, widest first; a hop that cannot be drawn at any width is
# left to the router rather than forced. The QFN's own pads are excluded as
# endpoints - at 0.5 mm pitch no rail width fits, and all four of them are
# already on their first-ring cap - and so is anything already joined.
RAILS = [
    # (net, widths to try, pads never used as an endpoint)
    # The narrow rung is W_RAIL_MIN (0.30) and not W_SIG (0.25): both rails are
    # in the Power class and the .kicad_dru's floor for it is 0.30 mm, so a
    # 0.25 mm tap is a DRC error rather than a thin tap. It costs the tree the
    # hops that only fitted at 0.25 - the run prints the islands that leaves.
    ("+3V3", (W_RAIL, 0.35, W_RAIL_MIN), (QFN,)),
    ("+5V", (W_RAIL, 0.35, W_RAIL_MIN), ()),
]
RAIL_VIA_BUDGET = {"+3V3": 8, "+5V": 0}
RAIL_LEN_BUDGET = {"+3V3": 120.0}
# No scripted rail hop longer than this. Past it the hop is a board-crossing
# run with a dozen ways round, which is a routing decision and not a trunk -
# J302's +3V3 pin is 60 mm from the LDO and the SWD header is the last thing
# that should dictate where the rail goes.
RAIL_MAX_HOP = 26.0
# Copper-to-straight-line ratios the two sweeps accept, in order.
RAIL_SLACK = (1.35, 2.5)


def _net_pads(cop, net, skip_refs):
    """Every pad of `net`, as specs, with #i where a number repeats."""
    out = []
    for ref, fp in sorted(cop.fps.items()):
        if ref in skip_refs:
            continue
        seen = collections.Counter()
        for p in fp.Pads():
            num = p.GetNumber()
            if not num:
                continue
            seen[num] += 1
            if p.GetNetname() != net:
                continue
            total = len([q for q in fp.Pads() if q.GetNumber() == num])
            out.append("%s.%s" % (ref, num) if total == 1
                       else "%s.%s#%d" % (ref, num, seen[num] - 1))
    return out


def _joined(cop, net, specs):
    """Union-find over the scripted copper: which of `specs` are one piece.

    The graph is every scripted segment of that net, keyed by its rounded
    endpoints; a segment endpoint that lands inside a pad's copper puts the
    pad on that piece. Layer is not part of the key, which is right here
    because every rail hop this script draws is on F.Cu and the one path that
    changes layer (CLAMP) puts a via at exactly the shared point.
    """
    def key(p):
        return (round(p[0], 3), round(p[1], 3))
    adj = collections.defaultdict(set)
    for (a, b, hw, lay, snet) in cop.segs:
        if snet != net:
            continue
        adj[key(a)].add(key(b))
        adj[key(b)].add(key(a))
    comp = {n: n for n in adj}

    def cfind(x):
        while comp[x] != x:
            comp[x] = comp[comp[x]]
            x = comp[x]
        return x
    for n in list(adj):
        for m in adj[n]:
            a, b = cfind(n), cfind(m)
            if a != b:
                comp[a] = b
    own = {s: {n for n in adj
               if point_rect_dist(n, cop.padbox(s)) <= 0.05} for s in specs}
    parent = {s: s for s in specs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    roots = collections.defaultdict(list)
    for s in specs:
        for n in own[s]:
            roots[cfind(n)].append(s)
    for members in roots.values():
        for s in members[1:]:
            ra, rb = find(members[0]), find(s)
            if ra != rb:
                parent[ra] = rb
    # every corner of this net's scripted copper that is on a piece a pad
    # owns, as a tap point: island representative -> list of (x, y)
    taps = collections.defaultdict(list)
    for n in adj:
        r = cfind(n)
        if r in roots:
            taps[find(roots[r][0])].append(n)
    return find, taps


def rail_tree(cop, net, widths, skip_refs):
    """Kruskal with a clearance check in place of the usual cycle test."""
    specs = _net_pads(cop, net, skip_refs)
    if len(specs) < 2:
        return 0, [], 0.0
    pairs = sorted((dist(cop.pad(a), cop.pad(b)), a, b)
                   for i, a in enumerate(specs) for b in specs[i + 1:])
    drawn, length, hops = 0, 0.0, []

    def hop(a, b, dry):
        for w in widths:
            got = cop.trace("%s tree %s->%s" % (net, a, b), a, b, w,
                            stubs=(0.0, 0.7, 1.4, 2.2), quiet=True, dry=dry,
                            detours=(0.5, -0.5, 1.0, -1.0, 1.8, -1.8,
                                     2.8, -2.8, 4.5, -4.5))
            if got:
                return got, w
        return None, None

    # Two sweeps. The first only takes a hop whose real copper is close to
    # the straight line between the two pads, so a pair that happens to be
    # nearest but has to go round the MCU does not become the trunk; the
    # second takes whatever is left. Plain Kruskal picks the shortest
    # RATSNEST and then pays whatever the copper costs, which is the router's
    # mistake with a tidier name.
    for slack in RAIL_SLACK:
        tried = set()
        while True:
            find, taps = _joined(cop, net, specs)
            # Pad to pad, and pad to any CORNER of a piece of this net's
            # copper that already reaches a pad. The second kind is what the
            # router does naturally and what a trunk with branches is: R404's
            # 3V3 does not have to walk to another pad, it taps the run going
            # past it. Pad to pad alone the same tree stopped at 16 hops and
            # 6 islands; with the taps it is 18 hops and 4, which is two more
            # pad pairs closed for 22.5 mm of copper.
            cands = []
            for d, a, b in pairs:
                if d <= RAIL_MAX_HOP and find(a) != find(b):
                    cands.append((d, a, b))
            for a in specs:
                pa, ia = cop.pad(a), find(a)
                for isl, pts in taps.items():
                    if isl == ia:
                        continue
                    for q in pts:
                        d = dist(pa, q)
                        if d <= RAIL_MAX_HOP:
                            cands.append((d, a, q))
            cands.sort(key=lambda c: (round(c[0], 3), str(c[1]), str(c[2])))
            nxt = None
            for d, a, b in cands:
                if (a, b) in tried:
                    continue
                nxt = (d, a, b)
                break
            if nxt is None:
                break
            d, a, b = nxt
            tried.add((a, b))
            got, _w = hop(a, b, True)
            if got is None or path_len(got) > d * slack + 2.0:
                continue
            got, w = hop(a, b, False)
            if got is None:
                continue
            drawn += 1
            length += path_len(got)
            hops.append((a, "(%.2f, %.2f)" % b if not isinstance(b, str)
                         else b, d, path_len(got), w))
    # what is left is a set of islands, not a list of pad pairs
    allpads = _net_pads(cop, net, ())
    find, _taps = _joined(cop, net, allpads)
    islands = collections.defaultdict(list)
    for s in allpads:
        islands[find(s)].append(s)
    return drawn, sorted(islands.values(), key=len, reverse=True), length, hops


def step7b_rails(cop):
    print("\n--- 7b. power rails as trees, not rings")
    for net, widths, skip in RAILS:
        n, islands, hopped, hops = rail_tree(cop, net, widths, skip)
        segs = [s for s in cop.segs if s[4] == net]
        total = sum(dist(s[0], s[1]) for s in segs)
        vias = len([v for v in cop.vias if v[3] == net])
        pads = _net_pads(cop, net, ())
        mst = _mst_len(cop, pads)
        lb = RAIL_LEN_BUDGET.get(net)
        vb = RAIL_VIA_BUDGET.get(net)
        print("  %-5s %2d tree hop(s) drawn (%.2f mm); %d island(s) left for "
              "the router" % (net, n, hopped, len(islands)))
        for a, b, d, made, w in hops:
            print("        %-11s -> %-11s %5.2f mm straight, %5.2f mm of "
                  "%.2f mm copper" % (a, b, d, made, w))
        for isl in islands:
            print("        island: %s" % ", ".join(sorted(isl)))
        print("        %6.2f mm of scripted copper on this net in all, %d "
              "via(s); the straight-line tree over its %d pads is %.2f mm"
              % (total, vias, len(pads), mst))
        if lb is not None:
            print("        length budget %.0f mm: %s" %
                  (lb, "PASS, %.2f mm" % total if total <= lb else
                   "OVER at %.2f mm" % total))
            if mst > lb:
                print("        (the minimum spanning tree over the %d pads is "
                      "%.2f mm of straight lines, so no routing of this net "
                      "can come in under %.0f mm - read the %.2f against %.2f, "
                      "not against %.0f)"
                      % (len(pads), mst, lb, total, mst, lb))
        if vb is not None:
            print("        via budget %d: %d - %s"
                  % (vb, vias, "PASS" if vias <= vb else "OVER"))


def _mst_len(cop, specs):
    """Straight-line minimum spanning tree over a set of pads, mm."""
    if len(specs) < 2:
        return 0.0
    pts = [cop.pad(s) for s in specs]
    inside, out = {0}, set(range(1, len(pts)))
    total = 0.0
    while out:
        d, j = min((min(dist(pts[i], pts[k]) for i in inside), k) for k in out)
        total += d
        inside.add(j)
        out.discard(j)
    return total


# ============================================================ metrics =====
FLYBACK_LOOP =("COIL_NEG terminal to SS110", "CLAMP SS110 to SMBJ24A",
                "VIN SMBJ24A to C102", "VIN terminal pin 1 to C102")
BUCK_CIN_LOOP = ("buck CIN 1 (1206)", "buck CIN 2 (1206)")


_DETACHED = []      # see strip_previous()


def strip_previous(board):
    """Remove everything a previous run of this script made."""
    grp = None
    for g in board.Groups():
        if g.GetName() == SCRIPTED_GROUP:
            grp = g
            break
    if grp is None:
        return 0
    # Take the group off the board FIRST; RemoveAll() hands its members back
    # to C++ ownership and the subsequent board.Remove() then crashes.
    items = list(grp.GetItems())
    board.Remove(grp)
    n = 0
    for it in items:
        board.Remove(it)
        n += 1
    # board.Remove() detaches without deleting, and letting the SWIG proxies
    # of the detached items be garbage collected segfaults KiCad 10 - keep
    # them alive for the rest of the process instead.
    _DETACHED.extend(items)
    _DETACHED.append(grp)
    return n


def make_group(board, items):
    g = pcbnew.PCB_GROUP(board)
    g.SetName(SCRIPTED_GROUP)
    board.Add(g)
    for it in items:
        g.AddItem(it)
    return g


def keepout_clean(cop, xr):
    """Copper of a foreign net inside the crystal keepout."""
    own = {"/MCU/OSC_IN", "/MCU/OSC_OUT", "GND", "/MCU/VDDA"}
    bad = []
    for (a, b, hw, lay, net) in cop.segs:
        if net in own:
            continue
        if seg_rect_dist(a, b, xr) <= hw:
            bad.append(net)
    for (p, r, d, net) in cop.vias:
        if point_rect_dist(p, xr) <= r:
            bad.append("via " + net)
    return sorted(set(bad))


def width_floor_table(cop):
    """Every scripted net against the .kicad_dru's track_width floor for it.

    ADR 0003 decision 5 through the rules file: a Power net may not be drawn
    under 0.30 mm and a HighCurrent one not under 0.50 mm, at a pad escape or
    anywhere else - the rule has no necking exception and there is no way to
    give it one without editing a committed file. So the floors are checked
    here, on the copper this run drew, and the run exits non-zero on a FAIL
    rather than leaving it for kicad-cli to find after the router has gone.
    """
    print("\n--- scripted track widths against the .kicad_dru floors")
    if not W_FLOOR:
        print("  no track_width rule found in %s" % os.path.basename(DRU))
        return 0
    bad = 0
    for net in sorted(W_FLOOR):
        w = [s[2] * 2.0 for s in cop.segs if s[4] == net]
        if not w:
            print("  %-18s floor %.2f mm   no scripted copper" % (net, W_FLOOR[net]))
            continue
        under = [x for x in w if x < W_FLOOR[net] - 1e-6]
        bad += len(under)
        print("  %-18s floor %.2f mm   %2d segment(s), min %.2f mm   %s"
              % (net, W_FLOOR[net], len(w), min(w),
                 "PASS" if not under else
                 "FAIL: %d under the floor" % len(under)))
    if bad:
        print("  %d scripted segment(s) below the .kicad_dru floor - each one "
              "is a track_width error kicad-cli will report" % bad)
    return bad


def sense_ground_table(cop):
    """ADR 0003 decision 4, checked pad by pad.

    "The sense side of R204 joins the pour only at the shunt." Two things have
    to hold for every pad on that side: it reaches the tie at R204's ground
    pad through scripted F.Cu copper only, and it has no via of its own
    anywhere. This walks the copper this run actually drew - it is not a
    restatement of the intent - and the run exits non-zero if a row fails.
    """
    print("\n--- sense-side ground (ADR 0003 decision 4)")
    pads = list(SENSE_GND) + [SENSE_TIE, SHUNT_GND]
    # graph over the F.Cu GND segments this run drew
    def key(p):
        return (round(p[0], 3), round(p[1], 3))
    adj = collections.defaultdict(set)
    for (a, b, hw, lay, net) in cop.segs:
        if net != "GND" or lay != "F.Cu":
            continue
        adj[key(a)].add(key(b))
        adj[key(b)].add(key(a))
    boxes = {spec: cop.padbox(spec) for spec in pads}
    # a pad owns every segment endpoint that lands on its copper
    nodes = {}
    for spec, r in boxes.items():
        nodes[spec] = [n for n in adj
                       if point_rect_dist(n, r) <= 0.05]
    seen = set()
    stack = [n for n in nodes[SHUNT_GND]]
    seen.update(stack)
    while stack:
        n = stack.pop()
        for m in adj[n]:
            if m not in seen:
                seen.add(m)
                stack.append(m)
    bad = []
    print("  %-10s %-38s %-10s %s"
          % ("pad", "reaches the tie at " + SHUNT_GND + " on F.Cu",
             "own via", ""))
    for spec in pads:
        if spec == SHUNT_GND:
            continue
        on_fcu = bool(nodes[spec]) and any(n in seen for n in nodes[spec])
        r = boxes[spec]
        own = [v for (v, rad, dr, vnet) in cop.vias
               if vnet == "GND" and point_rect_dist(v, r) < rad + 0.05]
        ok = on_fcu and not own
        print("  %-10s %-38s %-10s %s"
              % (spec, "yes" if on_fcu else "NO - not connected by this run",
                 "none" if not own else "%d - FAIL" % len(own),
                 "PASS" if ok else "FAIL"))
        if not ok:
            bad.append(spec)
    nv = len([1 for (v, rad, dr, vnet) in cop.vias
              if vnet == "GND" and point_rect_dist(v, boxes[SHUNT_GND])
              < rad + 0.6])
    print("  the one tie into the pour: %s, %d via(s) in its own copper"
          % (SHUNT_GND, nv))
    if nv == 0:
        bad.append(SHUNT_GND)
        print("  %s has NO via into the pour - FAIL" % SHUNT_GND)
    if bad:
        print("  SENSE GROUND FAILED (%d): %s" % (len(bad), ", ".join(bad)))
    return bad


def run_drc():
    out = os.path.join(OUT, "drc-copper.json")
    os.makedirs(OUT, exist_ok=True)
    subprocess.run(["kicad-cli", "pcb", "drc", "--schematic-parity",
                    "--severity-all", "--format", "json", "-o", out, PCB],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    d = json.load(open(out))
    v = d.get("violations", [])
    errs = [x for x in v if x["severity"] == "error"]
    warns = [x for x in v if x["severity"] != "error"]
    unc = d.get("unconnected_items") or []
    par = d.get("schematic_parity") or []
    print("\n--- 9. kicad-cli DRC (--schematic-parity --severity-all)")
    print("  errors %d   warnings %d   unconnected %d   parity %d"
          % (len(errs), len(warns), len(unc), len(par)))
    print("  errors by type:   %s"
          % dict(collections.Counter(x["type"] for x in errs)))
    print("  warnings by type: %s"
          % dict(collections.Counter(x["type"] for x in warns)))
    for x in errs[:20]:
        print("    ERROR %-28s %s" % (x["type"],
                                      x.get("description", "")[:100]))
    nets = collections.Counter()
    for u in unc:
        d0 = (u.get("items") or [{}])[0]
        nets[d0.get("description", "?")[:60]] += 1
    return len(errs), len(warns), len(unc), len(par), unc


def unconnected_by_net(unc):
    """Which nets the router still has to finish, with pad counts."""
    c = collections.Counter()
    for u in unc:
        txt = " ".join(i.get("description", "") for i in (u.get("items") or []))
        m = re.findall(r"\[([^\]]+)\]", txt)
        if m:
            c[m[0]] += 1
    return c


# =============================================================== main =====
def main():
    t_drc = "--no-drc" not in sys.argv
    refill = "--no-refill" not in sys.argv

    pro_before = None
    if os.path.exists(PRO):
        with open(PRO, "rb") as fh:
            pro_before = fh.read()

    board = pcbnew.LoadBoard(PCB)
    gone = strip_previous(board)
    print("scripted copper: removed %d item(s) from a previous run" % gone)

    cop = Copper(board)
    # Order is deliberate. The crystal island and the VDDA lane inside it
    # have exactly one way out each, so they claim their space before
    # anything else can; the ground stitching runs LAST because its stubs
    # would otherwise close escape routes a signal needed.
    xr = step1_zones(cop)
    osc = step4_crystal(cop, xr)
    # VDDA used to go before the fanout because it needed the crystal
    # channel. It does not any more (step 5), so the pin-row stubs claim
    # their space first: pin 9's neighbours 10, 11 and 12 are pedal inputs
    # with nowhere else to go, and a 0.20 mm VDDA leg can bend round them.
    step2_fanout(cop)
    step5_vdda(cop, xr)
    usb = step6_usb(cop)
    step6b_bridges(cop)
    # Before the decoupling, the power block, the filters and the rails: each
    # of the three nets here needs a lane one of those steps would take.
    step6c_signals(cop)          # GATE_IN, VCAP1, VIN_SENSE
    step3_decoupling(cop)
    step7_power(cop)
    # After the power block, so the flyback loop, the VIN chain and the
    # sense-side ground all keep the lanes they need, and before the filters
    # and the rails, which have alternatives where a rail escape has none.
    step7c_escapes(cop)
    step8_filters(cop)
    # The rails go after every local trace and before the ground stitching:
    # a 0.5 mm trunk laid early would close escapes the signals need, and a
    # stitching via laid early would close the trunk's own corridors.
    step7b_rails(cop)
    step3b_stitch(cop)

    make_group(board, cop.made)
    ntr = len([i for i in cop.made if isinstance(i, pcbnew.PCB_TRACK)
               and not isinstance(i, pcbnew.PCB_VIA)])
    nvi = len([i for i in cop.made if isinstance(i, pcbnew.PCB_VIA)])
    nzo = len([i for i in cop.made if isinstance(i, pcbnew.ZONE)])
    print("\nscripted, locked and grouped as %r: %d tracks, %d vias, %d zones, "
          "%d items total" % (SCRIPTED_GROUP, ntr, nvi, nzo, len(cop.made)))

    board.BuildConnectivity()
    if refill:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        print("zones filled")
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

    # ---- metrics -------------------------------------------------------
    print("\n--- loop and length metrics")
    fly = sum(cop.lengths.get(k, 0.0) for k in FLYBACK_LOOP)
    have = [k for k in FLYBACK_LOOP if k in cop.lengths]
    print("  flyback loop through the real copper: %.2f mm over %d of %d legs "
          "(%s)" % (fly, len(have), len(FLYBACK_LOOP),
                    ", ".join("%s %.1f" % (k.split()[0], cop.lengths[k])
                              for k in have)))
    cin = sum(cop.lengths.get(k, 0.0) for k in BUCK_CIN_LOOP)
    print("  buck CIN loop (both 1206 caps to the VIN pin): %.2f mm of "
          "copper; pad-to-pad %.2f / %.2f mm" % (
              cin, dist(cop.pad("C105.1"), cop.pad("U101.2")),
              dist(cop.pad("C106.1"), cop.pad("U101.2"))))
    for k, v in sorted(osc.items()):
        print("  %-8s %.2f mm on F.Cu, 0 vias" % (k, v))
    if usb:
        print("  USB D+ %.2f mm  D- %.2f mm  skew %.2f mm (budget 1.00 mm)"
              % (usb.get("dp", 0), usb.get("dm", 0), usb.get("skew", 0)))
    ko = keepout_clean(cop, xr)
    print("  crystal keepout: %s"
          % ("clean - only the oscillator's own nets, its ground guard and "
             "the VDDA lane" if not ko else "FOREIGN COPPER: %s" % ko))

    if cop.notes:
        print("\nnotes (%d):" % len(cop.notes))
        for n in cop.notes:
            print("  " + n)
    if cop.fails:
        print("\nCOULD NOT DRAW (%d) - left for the router:" % len(cop.fails))
        for f in cop.fails:
            print("  " + f)

    print("\n--- GND: is it closed, or is the router still asked for it?")
    isl = gnd_islands(cop)
    nv = len([1 for v in cop.vias if v[3] == "GND"])
    print("  %d GND via(s) scripted in all" % nv)
    if not isl:
        print("  every piece of scripted GND copper reaches the pour - the "
              "router should see no GND pad pair at all")
    else:
        print("  %d piece(s) of scripted GND copper with no via and no THT "
              "pad on them:" % len(isl))
        for owns, ln in isl:
            print("    %-46s %.2f mm of F.Cu"
                  % (", ".join(owns) if owns else "(no pad on it)", ln))

    rc = 0
    if sense_ground_table(cop):
        rc = 1
    if width_floor_table(cop):
        rc = 1
    if t_drc:
        errs, warns, unc, par, raw = run_drc()
        by = unconnected_by_net(raw)
        print("\n  nets left for the router (%d unconnected pad pairs over %d "
              "nets):" % (unc, len(by)))
        for net, n in by.most_common():
            print("    %-34s %d" % (net, n))
        gnd = [u for u in raw
               if "[GND]" in " ".join(i.get("description", "")
                                      for i in (u.get("items") or []))]
        print("\n  GND pad pairs left for the router: %d%s"
              % (len(gnd), " - the router does not see GND at all"
                 if not gnd else ""))
        for u in gnd:
            print("    %s" % " <-> ".join(i.get("description", "?")
                                          for i in (u.get("items") or [])))
        if errs or par:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
