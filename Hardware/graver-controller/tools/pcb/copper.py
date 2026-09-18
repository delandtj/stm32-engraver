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
  3. decoupling: pin -> cap on top, cap GND -> via into the pour
  4. crystal: OSC_IN / OSC_OUT on F.Cu only, load caps, F.Cu ground guard
  5. VDDA / VSSA chain FB301 -> C306/C307 -> pin 9
  6. USB: J301 -> U302 -> MCU as a coupled pair on F.Cu, 0 vias anywhere
  7. power: VIN chain, flyback loop, shunt Kelvin, gate, buck, +5V, +3V3
  8. the RC filters at the MCU's analog pins

Geometry is computed from real pad positions and drawn as octilinear
segments. Every candidate path is clearance-checked against every pad, every
piece of copper already drawn, the board edge and the keepouts BEFORE it is
committed, at the pairwise net-class clearance; a path that cannot be made to
clear is reported, not drawn.

Usage:  python3 tools/pcb/copper.py [--no-drc] [--no-refill] [--verbose]
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
# Pads that also get a VIA at the end of a longer stub, so the net can leave
# on B.Cu. At 0.5 mm pitch a 0.6 mm via needs to sit at least 1.43 mm out of
# the pad centre to keep 0.15 mm from a neighbouring 1.15 mm stub's end cap,
# and two vias need 0.75 mm of copper and 0.80 mm of hole-to-hole between
# them - so at most every SECOND pad of a row, and the pads in between keep
# a top-only escape. These four are the nets a strict autoroute of the
# it7 + copper board left open on the east and west rows.
QFN_VIA_PADS = ("18", "20", "42", "44")
QFN_VIA_RADII = (1.55, 1.75, 1.95, 2.20, 2.50)

# Pads whose destination is a first-ring part ON TOP: no via, a real trace.
# (mcu pad, target pad, width) - the router never sees these nets near the QFN.
FIRST_RING = [
    # Pad 1 is VBAT and its 100 nF sits round the corner with pad 48's, so
    # there is no first-ring trace for it: step 2's shadow escape jumpers pad
    # 1 to pad 48 instead, and +3V3 carries on from there.
    ("24", "C302.1", W_SIG),
    ("36", "C303.1", W_SIG),
    ("48", "C304.1", W_SIG),
    ("22", "C308.1", W_SIG),         # VCAP1
    ("7", "C309.1", W_SIG),          # NRST
]

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

    def pad(self, spec):
        ref, num = spec.split(".", 1)
        p = self.fps[ref].FindPadByNumber(num)
        if p is None:
            raise KeyError(spec)
        return loc(p.GetPosition())

    def padnet(self, spec):
        ref, num = spec.split(".", 1)
        return self.fps[ref].FindPadByNumber(num).GetNetname()

    def padbox(self, spec):
        ref, num = spec.split(".", 1)
        bb = self.fps[ref].FindPadByNumber(num).GetBoundingBox()
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
        for r, pnet, lay, hole, hr, ctr, ref, num in self.pads:
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
            need = clearance(net, snet)
            if need == 0.0:
                continue
            d = seg_seg_dist(a, b, sa, sb)
            if d < hw + shw + need:
                return "track of %s %.3f < %.3f" % (snet, d, hw + shw + need)
        for (p, rad, dr, vnet) in self.vias:
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
        for r, pnet, lay, hole, hr, ctr, ref, num in self.pads:
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
              stub=None, stubs=(0.0,), modes=OCT_MODES, quiet=False):
        """Route pad a to pad b octilinearly, trying stub lengths and modes.

        `stub` forces one radial stub length out of a; `stubs` is the list to
        try. The first combination that clears everything wins. Returns the
        path, or None (and records a failure).
        """
        a = self.resolve(a_spec)
        b = self.resolve(b_spec)
        net = (self.padnet(a_spec) if isinstance(a_spec, str)
               else self.padnet(b_spec))
        ign = tuple(s for s in (a_spec, b_spec) if isinstance(s, str))
        d = self.outward(a_spec) if isinstance(a_spec, str) else (0.0, 0.0)
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
                cand.append((path_len(out), len(out), out))
        # Three-segment detours: step sideways off the stub, then go across.
        # Enough obstacle avoidance for a board where the hard cases are
        # "a pad is in the way", without pretending to be a router.
        if d != (0.0, 0.0):
            perp = (-d[1], d[0])
            for s in ((stub,) if stub is not None else stubs):
                p0 = (a[0] + d[0] * s, a[1] + d[1] * s)
                for o in (0.4, -0.4, 0.7, -0.7, 1.0, -1.0, 1.4, -1.4,
                          1.8, -1.8, 2.2, -2.2, 2.8, -2.8, 3.5, -3.5,
                          4.5, -4.5, 6.0, -6.0, 8.0, -8.0):
                    p1 = (p0[0] + perp[0] * o, p0[1] + perp[1] * o)
                    for m in modes:
                        pts = [a, p0] + oct_route(p1, b, m)[0:]
                        out = [pts[0]]
                        for p in pts[1:]:
                            if dist(p, out[-1]) > 1e-9:
                                out.append(p)
                        cand.append((path_len(out) + 2.0, len(out), out))
        cand.sort(key=lambda c: (round(c[0], 2), c[1]))
        why = None
        for _l, _n, pts in cand:
            why = self.path_clear(pts, width, layer, net, ign)
            if why is None:
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

    def gnd_via_quiet(self, pad_spec):
        """Stub off a GND pad into the pour; silent when there is no room.

        Tries the pad's own outward normal first, then the other three axes,
        then the diagonals, at growing distance.
        """
        a = self.pad(pad_spec)
        d0 = self.outward(pad_spec)
        s2 = math.sqrt(0.5)
        dirs = [d0, (-d0[0], -d0[1]), (-d0[1], d0[0]), (d0[1], -d0[0]),
                (s2, s2), (-s2, s2), (s2, -s2), (-s2, -s2)]
        for s in (0.85, 1.05, 1.3, 1.6, 2.0, 2.5):
            for d in dirs:
                p = (round(a[0] + d[0] * s, 3), round(a[1] + d[1] * s, 3))
                if self.path_clear([a, p], W_FINE, "F.Cu", "GND",
                                   (pad_spec,)) is not None:
                    continue
                if self.via_clear(p, "GND", (pad_spec,)) is not None:
                    continue
                self.add_path([a, p], W_FINE, "F.Cu", "GND")
                self.add_via(p, "GND")
                return p
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
    done |= {"5", "6"}          # crystal, drawn in step 4
    done |= {"9"}               # VDDA, drawn in step 5
    done |= {"32", "33"}        # USB pair, drawn in step 6
    stubbed, vias, shadow = [], [], []
    for pad in fp.Pads():
        num = pad.GetNumber()
        if not num or num in done:
            continue
        net = pad.GetNetname()
        if not net or net.startswith("unconnected-"):
            continue
        spec = "%s.%s" % (QFN, num)
        a = cop.pad(spec)
        d = cop.outward(spec)
        placed = None
        if num in QFN_VIA_PADS:
            for r in QFN_VIA_RADII:
                b = (round(a[0] + d[0] * r, 3), round(a[1] + d[1] * r, 3))
                if cop.path_clear([a, b], W_FINE, "F.Cu", net, (spec,)):
                    continue
                if cop.via_clear(b, net, (spec,)):
                    continue
                cop.add_path([a, b], W_FINE, "F.Cu", net)
                cop.add_via(b, net)
                placed = r
                vias.append((num, net, r))
                break
            if placed is not None:
                stubbed.append((num, net, placed))
                continue
            cop.notes.append("no room for a fanout via on %s (%s), stub only"
                             % (spec, net))
        for s in (QFN_STUB, QFN_STUB - 0.15, QFN_STUB + 0.2, QFN_STUB + 0.45):
            b = (round(a[0] + d[0] * s, 3), round(a[1] + d[1] * s, 3))
            if cop.path_clear([a, b], W_FINE, "F.Cu", net, (spec,)) is None:
                cop.add_path([a, b], W_FINE, "F.Cu", net)
                placed = s
                break
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
    print("  radial stubs %.2f mm wide on %d pads (%.2f-%.2f mm out of the pad "
          "centre, %.2f-%.2f mm of new copper past the pad edge)"
          % (W_FINE, len(stubbed), min(s for _n, _t, s in stubbed),
             max(s for _n, _t, s in stubbed),
             min(s for _n, _t, s in stubbed) - 0.44,
             max(s for _n, _t, s in stubbed) - 0.44))
    print("  no via in the first ring: a %.1f mm via needs %.2f mm to a "
          "neighbouring %.2f mm stub and the pitch is 0.50 mm, so every "
          "escape leaves the pad radially on F.Cu and the bottom layer stays "
          "a whole ground plane under the part."
          % (VIA_D, VIA_D / 2 + CLEARANCE_DEFAULT + W_FINE / 2, W_FINE))
    if vias:
        print("  fanout vias %.1f/%.1f on pads %s (%.2f-%.2f mm out of the pad "
              "centre), so these nets can leave on B.Cu without fighting for "
              "the top-side second ring"
              % (VIA_D, VIA_DRILL,
                 ", ".join("%s=%s" % (n, t.rsplit("/", 1)[-1])
                           for n, t, _r in vias),
                 min(r for _n, _t, r in vias), max(r for _n, _t, r in vias)))
    if shadow:
        print("  pads the crystal island shadows, given real copper instead "
              "of a radial stub:")
        for line in shadow:
            print("    " + line)
    # First-ring traces (no via, destination is a part on top).
    ring_ok = 0
    for num, tgt, w in FIRST_RING:
        if cop.trace("QFN first ring %s->%s" % (num, tgt),
                     "%s.%s" % (QFN, num), tgt, w,
                     stubs=(0.7, 0.9, 1.1, 1.4, 1.7, 2.0)):
            ring_ok += 1
    print("  first-ring traces (no via): %d of %d" % (ring_ok, len(FIRST_RING)))
    return stubbed


# ====================================================== decoupling etc ====
# Signal-side traces, pin to cap. Everything here is short and on F.Cu.
DECOUPLE = [
    ("U201 1 uF bypass at its pins", "C201.1", "U201.1", W_SIG),
    ("U201 second bypass", "C202.1", "C201.1", W_SIG),
    ("U202 100 nF bypass", "C203.1", "U202.8", W_SIG),
    ("buck CIN 1 (1206)", "C105.1", "U101.2", 0.6),
    ("buck CIN 2 (1206)", "C106.1", "U101.2", 0.6),
    # C107 sits on the far side of the RON resistor from the 1206 pair, so
    # it joins VIN at the EN/UVLO divider's top instead.
    ("buck CIN 3 (100 nF)", "C107.1", "R105.1", 0.4),
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
    """Ground stitching. Runs LAST so its stubs cannot take the space a
    signal trace needed - in the first pass it closed four of them."""
    print("\n--- 3b. ground stitching (runs last)")
    # Every SMD GND pad gets a via into the pour. On a 2-layer board with a
    # solid bottom plane that is both the right answer electrically and the
    # cheapest thing that can happen to the router: GND stops being a net it
    # has to solve. THT GND pads reach the pour through the zone's own
    # thermal reliefs and are skipped.
    todo = []
    skip = set(SENSE_GND) | {SENSE_TIE}
    for ref in sorted(cop.fps):
        for pad in cop.fps[ref].Pads():
            if pad.GetNetname() != "GND" or not pad.GetNumber():
                continue
            if pad.GetDrillSize().x > 0:
                continue
            if ref == QFN:
                continue                      # handled by the EP
            spec = "%s.%s" % (ref, pad.GetNumber())
            if spec in skip:
                continue              # sense side: single point at the shunt
            todo.append(spec)
    done, miss = 0, []
    for spec in todo:
        if cop.gnd_via_quiet(spec):
            done += 1
        else:
            miss.append(spec)
    print("  GND stitching: %d of %d SMD ground pads carry their own via "
          "into the pour" % (done, len(todo)))
    print("  excluded on purpose (the sense side ties into the pour only at "
          "the shunt): %s" % ", ".join(sorted(skip)))
    if miss:
        print("  no room for a via at: %s" % ", ".join(miss))
        print("  (those pads reach GND through the router or a neighbour)")
    return miss


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
    tie = [("Y301.4", "Y301.2"), ("C310.2", None), ("C311.2", None)]
    nt = 0
    for a, b in tie:
        if b is None:
            p = cop.pad(a)
            u, v = _uv(d, t, p)
            b = _xy(d, t, u, v_lo if abs(v - v_lo) < abs(v - v_hi) else v_hi)
        if cop.trace("crystal ground tie %s" % (a,), a, b, W_FINE,
                     stubs=(0.0, 0.4, 0.6, 0.9, 1.2)):
            nt += 1
    print("  %d of %d island ground ties onto the guard" % (nt, len(tie)))
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
        why = cop.path_clear(pts, W_FINE, "F.Cu", net, (spec, tgt))
        if why is None:
            cop.add_path(pts, W_FINE, "F.Cu", net)
            return ("pad %s (%s): %.2f mm jumper to pad %s on the same net, "
                    "no channel lane and no via needed"
                    % (num, short, mate[0][0], mate[0][1]))
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
    run = cop.trace("VDDA pin 9 to C306", "%s.9" % QFN, "C306.1", W_FINE,
                    stubs=(0.55, 0.7, 0.9, QFN_STUB, QFN_STUB + 0.3, 0.0))
    if run is None:
        return 0.0
    total = path_len(run)
    print("  pin 9 -> C306 %.2f mm on F.Cu, 0 vias, %.2f mm wide - a plain "
          "radial escape now that the island is off this side" % (total, W_FINE))
    return total


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
    for a, b in (("J301.A5", "R305.1"), ("J301.B5", "R306.1")):
        cop.trace("CC pull-down %s" % a, a, b, W_SIG,
                  stubs=(0.0, 0.5, 0.9, 1.3))
    print("  CC1/CC2 pull-downs at the connector, one on each side of the "
          "pair (place.py moved them there); VBUS and GND are separate and "
          "not part of the pair")
    return res


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
    ("CLAMP to bypass FET", "D202.1", "Q202.2", 0.5),
    ("VIN SMBJ24A to C102", "D202.2", "C102.1", 1.0),
    ("VIN C102 to C103", "C102.1", "C103.1", 1.0),
    ("VIN terminal pin 1 to C102", "J201.1", "C102.1", 1.0),
    ("VIN C103 to bypass FET source", "C103.1", "Q202.3", 0.5),
    # gate drive
    ("GATE driver out to R201", "U201.5", "R201.1", 0.4),
    ("GATE R201 to FET gate", "R201.2", "Q201.1", 0.4),
    ("GATE pulldown at the FET", "R203.1", "Q201.1", 0.25),
    ("GATE_IN pulldown at the driver", "R202.1", "U201.3", 0.25),
    # shunt and its Kelvin taps
    ("SHUNT FET source to R204", "Q201.3", "R204.1", 1.0),
    ("Kelvin tap to R209", "R204.1", "R209.1", 0.2),
    ("Kelvin tap to R213", "R204.1", "R213.1", 0.2),
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
    ("EN/UVLO top to VIN", "R105.1", "C105.1", 0.4),
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
    for label, a, b, w in POWER:
        if cop.trace(label, a, b, w, stubs=(0.0, 0.6, 0.9, 1.3, 1.8, 2.4)):
            ok += 1
    print("  %d of %d power/driver traces drawn"
          % (ok, len(POWER) + len(POWER_EXPLICIT)))
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


# =========================================================== RC filters ===
RC = [
    ("16", "R212.2", W_SIG), ("16", "C205.1", W_SIG),      # I_SENSE
    ("18", "C104.1", W_SIG), ("18", "R103.1", W_SIG),      # VIN_SENSE
    ("19", "C207.1", W_SIG), ("19", "R217.2", W_SIG),      # NTC
    ("11", "C405.1", W_SIG), ("12", "C404.1", W_SIG),      # pedal
    ("40", "C401.1", W_SIG), ("41", "C402.1", W_SIG),
    ("43", "C403.1", W_SIG),                               # encoder debounce
    ("44", "R301.1", W_SIG), ("20", "R303.1", W_SIG),
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
        a, b = cop.pad("%s.%s" % (QFN, num)), cop.pad(tgt)
        if dist(a, b) > RC_MAX:
            skip.append("%s->%s %.1f mm" % (num, tgt, dist(a, b)))
            continue
        if cop.trace("filter %s->%s" % (num, tgt), "%s.%s" % (QFN, num), tgt, w,
                     stubs=(QFN_STUB, QFN_STUB + 0.3, QFN_STUB + 0.7,
                            QFN_STUB + 1.2)):
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


# ============================================================ metrics =====
FLYBACK_LOOP = ("COIL_NEG terminal to SS110", "CLAMP SS110 to SMBJ24A",
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
    import re
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
    step3_decoupling(cop)
    step7_power(cop)
    step8_filters(cop)
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

    rc = 0
    if sense_ground_table(cop):
        rc = 1
    if t_drc:
        errs, warns, unc, par, raw = run_drc()
        by = unconnected_by_net(raw)
        print("\n  nets left for the router (%d unconnected pad pairs over %d "
              "nets):" % (unc, len(by)))
        for net, n in by.most_common():
            print("    %-34s %d" % (net, n))
        if errs or par:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
