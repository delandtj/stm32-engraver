#!/usr/bin/env python3
"""Close the last three open pad pairs by hand, on the COMMITTED board.

This is not part of the pipeline and it must not be: `place.py` regenerates
the board from the schematic and `autoroute.py` is not deterministic, so the
routing that is committed is the best one there has been and re-running either
of them throws it away. What is left on it is three pad pairs, and this script
draws those three by hand, on the board as it stands, and puts them in the
PCB group `manual` - the same group `manual.py` collects and restores, so the
copper drawn here survives a later regeneration like any other hand route.

    python3 tools/pcb/close_pairs.py            # draw, refill, save, DRC
    python3 tools/pcb/close_pairs.py --dry      # draw nothing, report only
    python3 tools/pcb/close_pairs.py --no-drc   # skip the kicad-cli grade

The three:

  1. /MCU/VDDA       U301 pad 9 -> C306, copper.py's VDDA_LAYERED replayed.
  2. Net-(U301-PB2)  pad 20's escape via -> R303 pad 1, SIGNAL_LAYERED
                     replayed.
  3. +5V             D105 pad 1 (the ORing diode in the power block) to
                     C201 pad 1 (the gate driver's supply cap), ~40 mm across
                     the board. Nothing is tabulated for this one: the path is
                     SEARCHED, on a 0.1 mm grid with the same clearance model
                     copper.py uses, and the one place it leaves F.Cu is a
                     1.56 mm hop under the USB pair - see CROSSINGS below.

The clearance model is copper.py's, with one difference that matters: copper.py
runs on a board with no copper on it yet and accumulates what it draws, so its
`Copper.segs` IS the board. Here the board is full, so every track and via on
it is loaded into the same lists before anything is checked. The keepouts are
rebuilt the same way (the M3 rings come with `Copper`, the crystal island is
`parts_bbox` over the same three parts as step 1).

Geometry is the placement convention throughout: mm from the board's top-left
corner, which is page (50, 50).

Needs plain python3 with the system KiCad 10 `pcbnew` bindings, plus numpy and
scipy for the +5V search (the grid is 1101 x 701 cells on two layers; a pure
Python Dijkstra over it is minutes, scipy's is under a second). Nothing else
in tools/pcb needs either.
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
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import copper as C          # noqa: E402  (after the sys.path fix)

PROJ = C.PROJ
PCB = C.PCB
PRO = C.PRO
DRU = C.DRU
OUT = C.OUT
MANUAL_GROUP = "manual"

NET5 = "+5V"
W5 = C.W_RAIL_MIN               # 0.30 mm, the .kicad_dru Power floor
G = 0.1                         # search grid, mm

# ADR 0003 decision 4: the flyback loop's return path is not something a
# 0.30 mm rail may run through. Its copper gets a 1.00 mm clearance on BOTH
# layers instead of the net-class 0.40 - a B.Cu track under the loop cuts the
# return as surely as an F.Cu one beside it does.
FLYBACK_NETS = ("/Driver/COIL_NEG", "/Driver/CLAMP", "VIN")
FLYBACK_BOX = (48.0, 4.0, 78.0, 28.0)     # x0, y0, x1, y1 - the clamp corner
FLYBACK_CLEAR = 1.0

# The USB pair's B.Cu shadow. copper.py lays a User.2 band 0.15 mm off the
# pair's centre line so the ROUTER cannot cross under it; the search here is
# told something stronger - B.Cu is simply not available within USB_SHADOW of
# the pair - so that the one crossing below is the only one there can be.
USB_SHADOW = 1.0
# A via beside the pair has to clear the pair's own F.Cu track: 0.30 (via
# radius) + 0.20 (+5V against Default) + 0.10 (the pair's half width).
USB_VIA_KEEP = 0.60

PEN_B = 6.0                     # B.Cu length costs six times F.Cu length
VIA_COST = 8.0                  # and a via costs 8 mm of F.Cu. Both are
                                # deliberately brutal: the brief asks for as
                                # few vias as possible on the +5V run, so the
                                # search only buys one where 8 mm of top-side
                                # detour is not available
LOOKAHEAD = 25                  # vertices the octilinear simplifier looks past
EPS = 0.001                     # 1 um of slack in the raster, so that a cell
                                # the grid calls free also passes the exact
                                # clearance check (0.550 < 0.550 is a coin toss
                                # in floating point, and it came up tails)

_KEEP = []                      # detached SWIG proxies, never collected

# ------------------------------------------------------------- the nudge --
# VDDA_LAYERED does NOT drop straight onto the committed board, and the reason
# is worth writing down because it is the one thing this script had to move.
#
# copper.py measured pad 9's via window on the REGENERATED board, where the
# only copper is its own: (47.250, 48.225), 0.048 mm tall in y, hemmed in by
# pads 8 and 10 (0.513 mm where 0.500 is needed), C309's pad (0.550) and
# NRST's own diagonal (0.646 where 0.625 is needed). The committed board also
# carries the SIXTH PASS'S ROUTER COPPER, and one piece of it - a 0.50 mm
# +3V3 B.Cu trunk running dead straight along y = 47.800 from x = 41.550 to
# the via at x = 49.400 - passes 0.425 mm under that window where a via needs
# 0.750 and a 0.30 mm track needs 0.600.
#
# There is no second window. East of C309's pad a via needs x >= 48.225 to
# clear the pad and x <= 47.600 to clear PEDAL_TIP's stub; south of the +3V3
# trunk it needs y >= 48.550 and C309's pad puts it at y <= 48.275. So either
# VDDA stays open or the trunk moves, and the trunk is the cheaper of the two:
# it is router copper, it is 0.50 mm on a 0.30 mm floor, and the 1.3 mm of it
# that is in the way has nothing under it but the QFN's own F.Cu pads.
#
# It is moved 0.40 mm north over that 1.3 mm and comes straight back, so BOTH
# VIAS STAY WHERE THEY ARE and the trunk is still one piece of copper between
# the same two ends - 0.33 mm longer. The new legs go into the `autorouted`
# group the old one is in, NOT into `manual`: this is a correction to the
# router's copper and the next route run should replace it, not inherit it.
#
# The second one is a millimetre of dead copper. `copper.py` gives QFN pad 12
# (PEDAL_RING) a plain 1.00 mm radial stub down x = 48.750; the router then
# left the pad EASTWARD, joining that stub 0.012 mm below the pad centre, so
# everything south of y = 47.450 carries no current and is one of the board's
# four `track_dangling` warnings. It is also the west wall of the only via
# window VDDA has left. It is shortened back into pad 12's own copper, which
# removes the dangling end as well.
NUDGES = [
    dict(net="+3V3", layer="B.Cu", a=(41.550, 47.800), b=(49.400, 47.800),
         new=[(41.550, 47.800), (46.200, 47.800), (46.600, 47.400),
              (49.000, 47.400), (49.400, 47.800)],
         why="it passes 0.425 mm under VDDA's only via window at "
             "(47.250, 48.225), where 0.750 mm is needed"),
    dict(net="PEDAL_RING", layer="F.Cu", a=(48.750, 47.438),
         b=(48.750, 48.438),
         new=[(48.750, 47.438), (48.750, 47.875)],
         why="0.99 mm of it hangs below the point the router leaves pad 12 "
             "(a track_dangling warning) and it is 0.15 mm from VDDA's "
             "second via, where 0.60 mm is needed"),
]

# PB2 is the same story one net further on, and worse: SIGNAL_LAYERED's B.Cu
# leg from pad 20's escape to R303 crosses the router's ENC_A run, which comes
# in from the encoder on B.Cu along y = 42.750 and turns south-west at
# (54.300, 42.750) down to the MCU. That is not a clearance to be dodged, it
# is a TOPOLOGY: PB2 has to get from y = 43.45 to y = 37.50 and ENC_A from
# x = 57.65 to x = 49.90, in a corridor whose F.Cu is solid pads, so the two
# nets cross and one of them has to be somewhere else. A search over the whole
# board confirms it - with ENC_A where it is there is no F.Cu/B.Cu path at all
# from the escape to R303, on either layer, anywhere.
#
# So ENC_A's 4 segments through that corridor are RIPPED, PB2 is drawn, and
# ENC_A is then re-routed between the same two ends with PB2's copper in the
# model. ENC_A is a quadrature encoder line - a few extra millimetres and a
# via cost it nothing measurable - and it is router copper, so it goes back
# into the `autorouted` group and the next route run replaces it.
RIPUPS = [
    dict(net="ENC_A", layer="B.Cu",
         segs=[((51.500, 39.900), (52.250, 40.650)),
               ((52.250, 40.650), (52.250, 40.700)),
               ((52.250, 40.700), (54.300, 42.750)),
               ((54.300, 42.750), (57.650, 42.750))],
         ends=((51.500, 39.900), (57.650, 42.750)), width=0.20,
         region=(45.0, 32.0, 63.0, 49.0), step=0.05,
         why="its run across the corridor is the wall between PB2's escape "
             "and R303, and no route of PB2 avoids it on either layer"),
]

# VDDA on the COMMITTED board. copper.py's VDDA_LAYERED is tried first and is
# the geometry this follows - out of pad 9 southward, across on B.Cu, back up
# into C306 pad 1 - but its second via at (48.250, 49.225) is where the
# router's PEDAL_TIP escape runs (x = 48.200, y 48.8..49.7), so on this board
# the crossing is made 0.75 mm further north, where the only gap is:
#
#   west   PEDAL_TIP's own scripted stub down x = 48.250, 0.650 mm away
#          where 0.600 is needed
#   east   the +3V3 F.Cu diagonal out of the via at (49.400, 47.800),
#          0.849 mm away where 0.750 is needed
#   north  the +3V3 B.Cu trunk, which is why it had to be nudged
#   south  C306 pad 1's own copper, 0.300 mm from the via's edge - the same
#          0.275 mm VDDA_LAYERED's own second via stands off that pad
#
# 2.55 mm of new copper and 2 vias; with pad 9's existing 0.85 mm escape that
# is 3.40 mm from the pad to the cap against a 2.50 mm straight line.
VDDA_COMMITTED = [
    ("F.Cu", ["U301.9", (47.250, 48.225)]),
    ("B.Cu", [(47.250, 48.225), (47.500, 48.475), (48.900, 48.475)]),
    ("F.Cu", [(48.900, 48.475), (49.000, 48.575), "C306.1"]),
]


# ----------------------------------------------------------------- model --
def build_model(board):
    """copper.py's clearance model, loaded with the copper already on the board."""
    cop = C.Copper(board)
    cop.xtal_rect = C.parts_bbox(cop, C.XTAL_PARTS, C.XTAL_MARGIN)
    cop.keepouts.append(("rect", cop.xtal_rect,
                         ("/MCU/OSC_IN", "/MCU/OSC_OUT", "GND")))
    ntrk = nvia = 0
    for t in board.GetTracks():
        net = t.GetNetname()
        if isinstance(t, pcbnew.PCB_VIA):
            top = t.TopLayer()
            cop.vias.append((C.loc(t.GetPosition()),
                             C.tomm(t.GetWidth(top)) / 2.0,
                             C.tomm(t.GetDrill()) / 2.0, net))
            nvia += 1
        else:
            cop.segs.append((C.loc(t.GetStart()), C.loc(t.GetEnd()),
                             C.tomm(t.GetWidth()) / 2.0,
                             t.GetLayerName(), net))
            ntrk += 1
    print("  model: %d pad(s), %d track(s), %d via(s), crystal keepout "
          "x[%.2f, %.2f] y[%.2f, %.2f]"
          % (len(cop.pads), ntrk, nvia, cop.xtal_rect[0], cop.xtal_rect[2],
             cop.xtal_rect[1], cop.xtal_rect[3]))
    return cop


def add_seg(cop, a, b, width, layer, net):
    """Like Copper.add_seg but UNLOCKED - this is a hand route, not script copper."""
    if C.dist(a, b) < 1e-9:
        return None
    t = pcbnew.PCB_TRACK(cop.board)
    t.SetStart(C.at(*a))
    t.SetEnd(C.at(*b))
    t.SetWidth(C.mm(width))
    t.SetLayer(pcbnew.F_Cu if layer == "F.Cu" else pcbnew.B_Cu)
    t.SetNet(cop.net(net))
    cop.board.Add(t)
    cop.made.append(t)
    cop.segs.append((a, b, width / 2.0, layer, net))
    return t


def add_path(cop, pts, width, layer, net):
    made = []
    for i in range(len(pts) - 1):
        t = add_seg(cop, pts[i], pts[i + 1], width, layer, net)
        if t is not None:
            made.append(t)
    return made


def add_via(cop, p, net):
    v = pcbnew.PCB_VIA(cop.board)
    v.SetPosition(C.at(*p))
    v.SetWidth(C.mm(C.VIA_D))
    v.SetDrill(C.mm(C.VIA_DRILL))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNet(cop.net(net))
    cop.board.Add(v)
    cop.made.append(v)
    cop.vias.append((p, C.VIA_D / 2.0, C.VIA_DRILL / 2.0, net))
    return v


def covered(cop, a, b, layer, net):
    """Is segment a-b already drawn, as part of one same-net segment?"""
    for (sa, sb, shw, slay, snet) in cop.segs:
        if slay != layer or snet != net:
            continue
        if (C.seg_point_dist(sa, sb, a) < 1e-6
                and C.seg_point_dist(sa, sb, b) < 1e-6):
            return True
    return False


def has_via(cop, p, net):
    for (q, r, d, vnet) in cop.vias:
        if vnet == net and C.dist(p, q) < 1e-6:
            return True
    return False


def group_index(board):
    idx = {}
    for g in board.Groups():
        for it in g.GetItems():
            idx[it.m_Uuid.AsString()] = g
    return idx


def apply_nudge(cop, board, spec):
    """Re-shape one existing track, in place, keeping its group and its ends."""
    want = {(round(spec["a"][0], 3), round(spec["a"][1], 3)),
            (round(spec["b"][0], 3), round(spec["b"][1], 3))}
    hit = None
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        if t.GetNetname() != spec["net"] or t.GetLayerName() != spec["layer"]:
            continue
        a, b = C.loc(t.GetStart()), C.loc(t.GetEnd())
        if {(round(a[0], 3), round(a[1], 3)),
                (round(b[0], 3), round(b[1], 3))} == want:
            hit = (t, a, b)
            break
    if hit is None:
        print("  the %s %s track %s-%s is not on the board any more; nothing "
              "to nudge" % (spec["net"], spec["layer"], spec["a"], spec["b"]))
        return []
    t, a, b = hit
    w = C.tomm(t.GetWidth())
    pts = list(spec["new"])
    if C.dist(pts[0], a) > 1e-6:
        pts.reverse()
    if not C.all_octilinear(pts):
        print("  FAIL: the nudged %s path is not octilinear" % spec["net"])
        return None
    cop.segs = [s for s in cop.segs
                if not (s[4] == spec["net"] and s[3] == spec["layer"]
                        and {(round(s[0][0], 3), round(s[0][1], 3)),
                             (round(s[1][0], 3), round(s[1][1], 3))} == want)]
    for i in range(len(pts) - 1):
        why = cop.seg_clear(pts[i], pts[i + 1], w / 2.0, spec["layer"],
                            spec["net"])
        if why:
            print("  FAIL: the nudged %s leg %d does not clear: %s"
                  % (spec["net"], i + 1, why))
            return None
    idx = group_index(board)
    grp = idx.get(t.m_Uuid.AsString())
    t.SetStart(C.at(*pts[0]))
    t.SetEnd(C.at(*pts[1]))
    cop.segs.append((pts[0], pts[1], w / 2.0, spec["layer"], spec["net"]))
    made = []
    for i in range(1, len(pts) - 1):
        nt = pcbnew.PCB_TRACK(board)
        nt.SetStart(C.at(*pts[i]))
        nt.SetEnd(C.at(*pts[i + 1]))
        nt.SetWidth(C.mm(w))
        nt.SetLayer(t.GetLayer())
        nt.SetNet(cop.net(spec["net"]))
        board.Add(nt)
        if grp is not None:
            grp.AddItem(nt)
        cop.segs.append((pts[i], pts[i + 1], w / 2.0, spec["layer"],
                         spec["net"]))
        made.append(nt)
    print("  nudged the %.2f mm %s %s track (%.3f, %.3f)-(%.3f, %.3f): %s"
          % (w, spec["net"], spec["layer"], a[0], a[1], b[0], b[1],
             spec["why"]))
    print("    %.2f mm -> %.2f mm over %d leg(s), both ends unmoved, group %r"
          % (C.dist(a, b), C.path_len(pts), len(pts) - 1,
             grp.GetName() if grp is not None else "-"))
    return made


def rip(cop, board, spec):
    """Take one chain of existing copper off the board, model included."""
    want = [{(round(a[0], 3), round(a[1], 3)),
             (round(b[0], 3), round(b[1], 3))} for (a, b) in spec["segs"]]
    grp = None
    gone = 0
    idx = group_index(board)
    for t in list(board.GetTracks()):
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        if t.GetNetname() != spec["net"] or t.GetLayerName() != spec["layer"]:
            continue
        a, b = C.loc(t.GetStart()), C.loc(t.GetEnd())
        key = {(round(a[0], 3), round(a[1], 3)),
               (round(b[0], 3), round(b[1], 3))}
        if key not in want:
            continue
        g = idx.get(t.m_Uuid.AsString())
        if g is not None:
            grp = g
            g.RemoveItem(t)
        board.Remove(t)
        _KEEP.append(t)
        gone += 1
        cop.segs = [s for s in cop.segs
                    if not (s[4] == spec["net"] and s[3] == spec["layer"]
                            and {(round(s[0][0], 3), round(s[0][1], 3)),
                                 (round(s[1][0], 3), round(s[1][1], 3))} == key)]
    print("  ripped %d %s %s segment(s): %s"
          % (gone, spec["net"], spec["layer"], spec["why"]))
    return gone, grp


# --------------------------------------------------- the two replayed ones -
def escape_end(cop, net):
    """The via a QFN fanned escape ends on, for a net that has exactly one."""
    pts = [v[0] for v in cop.vias if v[3] == net]
    if len(pts) != 1:
        raise RuntimeError("%s has %d via(s), expected the escape's one"
                           % (net, len(pts)))
    return pts[0]


def draw_layered(cop, label, net, width, runs, resolve, quiet=False):
    """copper.py's `layered`, on a board that already has copper on it.

    Same contract - check every run and every via in full BEFORE committing
    anything - with one addition: a run whose copper is already on the board
    (the committed board carries VDDA's 0.85 mm escape out of pad 9, which is
    VDDA_LAYERED's first run and then some) is reported and not drawn twice.
    """
    built, vias, skipped = [], [], []
    for i, (layer, pts) in enumerate(runs):
        out = [resolve(q) for q in pts]
        ign = tuple(q for q in pts if isinstance(q, str)
                    and not q.startswith("ESCAPE."))
        legs = []
        for k in range(len(out) - 1):
            if covered(cop, out[k], out[k + 1], layer, net):
                skipped.append((layer, out[k], out[k + 1]))
                continue
            legs.append((out[k], out[k + 1]))
        for (a, b) in legs:
            why = cop.seg_clear(a, b, width / 2.0, layer, net, ign)
            if why:
                if not quiet:
                    print("  FAIL %s (%s run %d): %s"
                          % (label, layer, i + 1, why))
                return None
        built.append((layer, legs))
        if i:
            vias.append(out[0])
    for p in list(vias):
        if has_via(cop, p, net):
            vias.remove(p)
            skipped.append(("via", p, p))
            continue
        why = cop.via_clear(p, net)
        if why:
            if not quiet:
                print("  FAIL %s: via at (%.3f, %.3f) blocked: %s"
                      % (label, p[0], p[1], why))
            return None
    made, total, per = [], 0.0, collections.Counter()
    for layer, legs in built:
        for (a, b) in legs:
            t = add_seg(cop, a, b, width, layer, net)
            if t is not None:
                made.append(t)
            total += C.dist(a, b)
            per[layer] += C.dist(a, b)
    for p in vias:
        made.append(add_via(cop, p, net))
    for (what, a, b) in skipped:
        if what == "via":
            print("  already on the board: a via at (%.3f, %.3f)" % a)
        else:
            print("  already on the board: %.2f mm of %s from (%.3f, %.3f)"
                  % (C.dist(a, b), what, a[0], a[1]))
    print("  %-34s %5.2f mm new copper (%s), %d new via(s)"
          % (label, total,
             ", ".join("%.2f mm %s" % (v, k) for k, v in sorted(per.items()))
             or "-", len(vias)))
    return made, total, len(vias), per


# ----------------------------------------------- the two-layer grid router -
# Used where a dictated path does not fit the committed board. Same clearance
# model, on a grid anchored ON the point the path has to start from, so the
# copper it produces lands exactly on the copper it has to join.
class Grid(object):
    def __init__(self, cop, net, width, origin, step, region,
                 flyback=False, usb_shadow=False):
        import numpy as np
        self.cop, self.net, self.w, self.g = cop, net, width, step
        self.ox, self.oy = origin
        x0, y0, x1, y1 = region
        self.i0 = int(math.ceil((x0 - self.ox) / step))
        self.j0 = int(math.ceil((y0 - self.oy) / step))
        ni = int(math.floor((x1 - self.ox) / step)) - self.i0 + 1
        nj = int(math.floor((y1 - self.oy) / step)) - self.j0 + 1
        self.ni, self.nj = ni, nj
        self.xs = self.ox + (self.i0 + np.arange(ni)) * step
        self.ys = self.oy + (self.j0 + np.arange(nj)) * step
        hw = width / 2.0
        self.F = np.zeros((ni, nj), bool)
        self.B = np.zeros((ni, nj), bool)
        self.V = np.zeros((ni, nj), bool)       # via NOT allowed
        r = C.VIA_D / 2.0
        dr = C.VIA_DRILL / 2.0
        self._edge(self.F, C.EDGE_KEEP + hw)
        self._edge(self.B, C.EDGE_KEEP + hw)
        self._edge(self.V, C.EDGE_KEEP + r)
        for kind, g, allow in cop.keepouts:
            skip = net in allow
            if kind == "circle":
                cx, cy, rr = g
                if not skip:
                    self._seg(self.F, (cx, cy), (cx, cy), rr + hw)
                    self._seg(self.B, (cx, cy), (cx, cy), rr + hw)
                self._seg(self.V, (cx, cy), (cx, cy), rr + r)
            else:
                if not skip:
                    self._rect(self.F, g, hw)
                    self._rect(self.B, g, hw)
                self._rect(self.V, g, r)        # no vias in there at all
        for rr, pnet, lay, hole, hr, ctr, ref, num in cop.pads:
            need = C.clearance(net, pnet)
            if need > 0.0:
                if hole or "F.Cu" in lay:
                    self._rect(self.F, rr, hw + need)
                if hole or "B.Cu" in lay:
                    self._rect(self.B, rr, hw + need)
                self._rect(self.V, rr, r + need)
            if hole:
                self._seg(self.V, ctr, ctr, dr + hr + C.HOLE_TO_HOLE)
        for (a, bb, shw, lay, snet) in cop.segs:
            need = C.clearance(net, snet)
            if (flyback and snet in FLYBACK_NETS
                    and C.seg_rect_dist(a, bb, FLYBACK_BOX) <= 0.0):
                d = hw + shw + FLYBACK_CLEAR
                self._seg(self.F, a, bb, d)
                self._seg(self.B, a, bb, d)
                self._seg(self.V, a, bb, r + shw + FLYBACK_CLEAR)
                continue
            if usb_shadow and lay == "F.Cu" and snet in (C.USB_DP, C.USB_DM):
                # nothing of ours under the pair except the one crossing,
                # which is drawn explicitly and not searched for
                self._seg(self.B, a, bb, USB_SHADOW + hw)
            if need <= 0.0:
                continue
            self._seg(self.F if lay == "F.Cu" else self.B, a, bb,
                      hw + shw + need)
            self._seg(self.V, a, bb, r + shw + need)
        for (p, vr, vdr, vnet) in cop.vias:
            need = C.clearance(net, vnet)
            if need > 0.0:
                self._seg(self.F, p, p, hw + vr + need)
                self._seg(self.B, p, p, hw + vr + need)
                self._seg(self.V, p, p, r + vr + need)
            self._seg(self.V, p, p, dr + vdr + C.HOLE_TO_HOLE)

    def _win(self, x0, y0, x1, y1, d):
        i0 = max(0, int(math.floor((x0 - d - self.xs[0]) / self.g)))
        i1 = min(self.ni - 1, int(math.ceil((x1 + d - self.xs[0]) / self.g)))
        j0 = max(0, int(math.floor((y0 - d - self.ys[0]) / self.g)))
        j1 = min(self.nj - 1, int(math.ceil((y1 + d - self.ys[0]) / self.g)))
        return i0, i1, j0, j1

    def _edge(self, M, d):
        import numpy as np
        ok = (((self.xs >= d) & (self.xs <= C.BOARD_W - d))[:, None]
              & ((self.ys >= d) & (self.ys <= C.BOARD_H - d))[None, :])
        M |= ~ok

    def _rect(self, M, rr, d):
        import numpy as np
        d = d + EPS
        i0, i1, j0, j1 = self._win(rr[0], rr[1], rr[2], rr[3], d)
        if i1 < i0 or j1 < j0:
            return
        X = self.xs[i0:i1 + 1][:, None]
        Y = self.ys[j0:j1 + 1][None, :]
        dx = np.maximum(np.maximum(rr[0] - X, 0.0), X - rr[2])
        dy = np.maximum(np.maximum(rr[1] - Y, 0.0), Y - rr[3])
        M[i0:i1 + 1, j0:j1 + 1] |= (dx * dx + dy * dy) < d * d

    def _seg(self, M, a, b, d):
        import numpy as np
        d = d + EPS
        i0, i1, j0, j1 = self._win(min(a[0], b[0]), min(a[1], b[1]),
                                   max(a[0], b[0]), max(a[1], b[1]), d)
        if i1 < i0 or j1 < j0:
            return
        X = self.xs[i0:i1 + 1][:, None]
        Y = self.ys[j0:j1 + 1][None, :]
        vx, vy = b[0] - a[0], b[1] - a[1]
        L2 = vx * vx + vy * vy
        t = 0.0 if L2 < 1e-12 else np.clip(
            ((X - a[0]) * vx + (Y - a[1]) * vy) / L2, 0.0, 1.0)
        px, py = a[0] + t * vx, a[1] + t * vy
        M[i0:i1 + 1, j0:j1 + 1] |= ((X - px) ** 2 + (Y - py) ** 2) < d * d

    def pt(self, i, j):
        return (round(float(self.xs[i]), 4), round(float(self.ys[j]), 4))

    def near(self, p):
        i = int(round((p[0] - self.xs[0]) / self.g))
        j = int(round((p[1] - self.ys[0]) / self.g))
        if 0 <= i < self.ni and 0 <= j < self.nj:
            return i, j
        return None


def island_mask(grid, island, layer):
    """Grid cells that sit on one island's copper on `layer`."""
    import numpy as np
    M = np.zeros((grid.ni, grid.nj), bool)
    for kind, g in island:
        if kind == "seg":
            a, b, shw, lay = g
            if lay != layer:
                continue
            grid._seg(M, a, b, max(1e-3, shw - 0.01))
        elif kind == "via":
            grid._seg(M, g[0], g[0], max(1e-3, g[1] - 0.01))
        else:
            rr, spec, lay = g
            if layer not in lay:
                continue
            grid._rect(M, (rr[0] + 0.10, rr[1] + 0.10,
                           rr[2] - 0.10, rr[3] - 0.10), 1e-3)
    return M


def island_at(islands, p):
    """The island whose copper contains point p."""
    for isl in islands:
        for kind, g in isl:
            if kind == "seg" and C.seg_point_dist(g[0], g[1], p) <= g[2] + 1e-6:
                return isl
            if kind == "via" and C.dist(g[0], p) <= g[1] + 1e-6:
                return isl
            if kind == "pad" and C.point_rect_dist(p, g[0]) <= 1e-6:
                return isl
    return None


def build_graph(grid, via_cost=VIA_COST, pen_b=PEN_B):
    """The two-layer octilinear grid as a sparse graph.

    Node (layer, i, j) is layer * ni * nj + i * nj + j, F.Cu first. A
    diagonal step also needs the two cells beside it, so a path can never cut
    the corner of an obstacle; the exact clearance check on the finished
    polyline is what has the last word either way.
    """
    import numpy as np
    from scipy.sparse import csr_matrix
    ni, nj = grid.ni, grid.nj
    n = ni * nj
    freeF = ~grid.F
    freeB = ~grid.B
    rows, cols, data = [], [], []

    def layer_edges(free, base, mult):
        for di, dj, w in ((1, 0, grid.g), (0, 1, grid.g),
                          (1, 1, grid.g * math.sqrt(2)),
                          (1, -1, grid.g * math.sqrt(2))):
            i0 = max(0, -di)
            i1 = ni - max(0, di)
            j0 = max(0, -dj)
            j1 = nj - max(0, dj)
            if i1 <= i0 or j1 <= j0:
                continue
            m = free[i0:i1, j0:j1] & free[i0 + di:i1 + di, j0 + dj:j1 + dj]
            if di and dj:
                m = (m & free[i0 + di:i1 + di, j0:j1]
                     & free[i0:i1, j0 + dj:j1 + dj])
            ii, jj = np.nonzero(m)
            si, sj = ii + i0, jj + j0
            rows.append(base + si * nj + sj)
            cols.append(base + (si + di) * nj + (sj + dj))
            data.append(np.full(si.size, w * mult))

    layer_edges(freeF, 0, 1.0)
    layer_edges(freeB, n, pen_b)
    vm = (~grid.V) & freeF & freeB
    ii, jj = np.nonzero(vm)
    rows.append(ii * nj + jj)
    cols.append(n + ii * nj + jj)
    data.append(np.full(ii.size, via_cost))
    g = csr_matrix((np.concatenate(data),
                    (np.concatenate(rows), np.concatenate(cols))),
                   shape=(2 * n, 2 * n))
    return g, freeF, freeB


def nodes_of(grid, mask_f, mask_b, freeF, freeB):
    import numpy as np
    n = grid.ni * grid.nj
    return np.concatenate([np.flatnonzero((mask_f & freeF).ravel()),
                           n + np.flatnonzero((mask_b & freeB).ravel())])


def node_of(grid, p, layer):
    ij = grid.near(p)
    if ij is None:
        return None
    k = ij[0] * grid.nj + ij[1]
    return k if layer == "F.Cu" else k + grid.ni * grid.nj


def sweep(g, sources):
    from scipy.sparse.csgraph import dijkstra as sp_dijkstra
    return sp_dijkstra(g, directed=False, indices=sources, min_only=True,
                       return_predecessors=True)[:2]


def walk_nodes(grid, pred, end):
    """Predecessor array -> [(layer, (x, y))], source first."""
    n = grid.ni * grid.nj
    out = []
    k = int(end)
    seen = set()
    while k >= 0 and k not in seen:
        seen.add(k)
        lay = "B.Cu" if k >= n else "F.Cu"
        kk = k - n if k >= n else k
        out.append((lay, grid.pt(kk // grid.nj, kk % grid.nj)))
        nxt = int(pred[k])
        if nxt < 0:
            break
        k = nxt
    out.reverse()
    return out


def two_layer_route(grid, src_f, src_b, dst_f, dst_b, via_cost=VIA_COST,
                    pen_b=PEN_B):
    """Cheapest F/B path from the source cells to the target cells."""
    import numpy as np
    g, freeF, freeB = build_graph(grid, via_cost, pen_b)
    srcs = nodes_of(grid, src_f, src_b, freeF, freeB)
    dsts = nodes_of(grid, dst_f, dst_b, freeF, freeB)
    if not srcs.size or not dsts.size:
        return None
    d, pred = sweep(g, srcs)
    best = dsts[int(np.argmin(d[dsts]))]
    if not np.isfinite(d[best]):
        return None
    return walk_nodes(grid, pred, best)


def split_runs(path):
    """[(layer, pt)] -> [(layer, [pts])] plus the via points between them."""
    runs = []
    vias = []
    cur_layer = path[0][0]
    cur = [path[0][1]]
    for lay, p in path[1:]:
        if lay != cur_layer:
            vias.append(p)
            runs.append((cur_layer, cur))
            cur_layer, cur = lay, [p]
        else:
            cur.append(p)
    runs.append((cur_layer, cur))
    return [r for r in runs if len(r[1]) > 1], vias


def draw_searched(cop, label, net, width, path, skip_vias=()):
    """Simplify, check and draw a path the grid router found."""
    runs, vias = split_runs(path)
    clean = []
    for layer, pts in runs:
        pts = simplify(cop, pts, width, layer, net)
        if not C.all_octilinear(pts):
            print("  FAIL %s: a %s run is not octilinear" % (label, layer))
            return None
        why = cop.path_clear(pts, width, layer, net)
        if why:
            print("  FAIL %s: a %s run does not clear: %s"
                  % (label, layer, why))
            return None
        clean.append((layer, pts))
    new_vias = []
    for p in vias:
        if any(C.dist(p, q) < 1e-6 for q in skip_vias) or has_via(cop, p, net):
            continue
        why = cop.via_clear(p, net)
        if why:
            print("  FAIL %s: via at (%.3f, %.3f) blocked: %s"
                  % (label, p[0], p[1], why))
            return None
        new_vias.append(p)
    made, per = [], collections.Counter()
    for layer, pts in clean:
        made += add_path(cop, pts, width, layer, net)
        per[layer] += C.path_len(pts)
    for p in new_vias:
        made.append(add_via(cop, p, net))
    total = sum(per.values())
    print("  %-34s %5.2f mm (%s), %d new via(s) at %s"
          % (label, total,
             ", ".join("%.2f mm %s" % (v, k) for k, v in sorted(per.items())),
             len(new_vias),
             ", ".join("(%.3f, %.3f)" % p for p in new_vias) or "-"))
    for layer, pts in clean:
        print("    %-5s %s" % (layer, " -> ".join("(%.3f, %.3f)" % q
                                                  for q in pts)))
    return made, total, len(new_vias), dict(per)


def net_islands(cop, net):
    """The pieces of `net`'s existing copper, as lists of (kind, geometry)."""
    items = []
    for (a, b, shw, lay, snet) in cop.segs:
        if snet == net:
            items.append(("seg", (a, b, shw, lay)))
    for r, pnet, lay, hole, hr, ctr, ref, num in cop.pads:
        if pnet == net:
            items.append(("pad", (r, "%s.%s" % (ref, num),
                                  set(lay) | ({"F.Cu", "B.Cu"} if hole
                                              else set()))))
    for (p, vr, vdr, vnet) in cop.vias:
        if vnet == net:
            items.append(("via", (p, vr)))
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def hit(ka, ga, kb, gb):
        if ka == "seg" and kb == "seg":
            return C.seg_seg_dist(ga[0], ga[1], gb[0], gb[1]) <= ga[2] + gb[2]
        if ka == "seg" and kb == "pad":
            return C.seg_rect_dist(ga[0], ga[1], gb[0]) <= ga[2]
        if ka == "seg" and kb == "via":
            return C.seg_point_dist(ga[0], ga[1], gb[0]) <= ga[2] + gb[1]
        if ka == "via" and kb == "pad":
            return C.point_rect_dist(ga[0], gb[0]) <= ga[1]
        if ka == "via" and kb == "via":
            return C.dist(ga[0], gb[0]) <= ga[1] + gb[1]
        if ka == "pad" and kb == "pad":
            return C.point_rect_dist(((ga[0][0] + ga[0][2]) / 2.0,
                                      (ga[0][1] + ga[0][3]) / 2.0), gb[0]) <= 0
        return None

    def touch(i, j):
        ka, ga = items[i]
        kb, gb = items[j]
        r = hit(ka, ga, kb, gb)
        if r is None:
            r = hit(kb, gb, ka, ga)
        return bool(r)

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if find(i) != find(j) and touch(i, j):
                parent[find(i)] = find(j)
    groups = collections.defaultdict(list)
    for i, it in enumerate(items):
        groups[find(i)].append(it)
    return list(groups.values())


def island_with(island, spec):
    for kind, g in island:
        if kind == "pad" and g[1] == spec:
            return True
    return False


def merge_collinear(pts):
    out = [pts[0]]
    for p in pts[1:]:
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            if (abs((b[0] - a[0]) * (p[1] - a[1])
                    - (b[1] - a[1]) * (p[0] - a[0])) < 1e-9
                    and (p[0] - b[0]) * (b[0] - a[0])
                    + (p[1] - b[1]) * (b[1] - a[1]) > 0):
                out[-1] = p
                continue
        out.append(p)
    return out


def simplify(cop, pts, width, layer, net, ign=()):
    """Replace runs of grid steps with the longest octilinear leg that clears.

    A grid path is a staircase; a hand route is not. This is the usual
    line-of-sight simplification with `oct_route`'s shapes in place of a
    straight line, so the result is still H, V or exactly 45 degrees.
    """
    pts = merge_collinear(pts)
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        best = None
        for j in range(min(len(pts) - 1, i + LOOKAHEAD), i, -1):
            for m in C.OCT_MODES:
                cand = C.oct_route(pts[i], pts[j], m)
                if not C.all_octilinear(cand):
                    continue
                if cop.path_clear(cand, width, layer, net, ign) is None:
                    best = (j, cand)
                    break
            if best:
                break
        if best is None:
            out.append(pts[i + 1])
            i += 1
        else:
            j, cand = best
            out.extend(cand[1:])
            i = j
    return merge_collinear(out)


# ------------------------------------------------------ the USB crossing --
# The one place the +5V run leaves F.Cu, and the only B.Cu this script draws
# under the pair. ADR 0003 component breakdown 3 wants D+/D- over unbroken
# bottom ground, and `usb_reference_check` enforces it; this crossing is the
# single agreed exception and it is shaped so that it costs the reference as
# little as a crossing can:
#
#   - it is PERPENDICULAR to the pair, so the slot it opens in the pour is the
#     pair's own 0.35 mm width plus two clearances and not a millimetre more;
#   - it is 0.30 mm wide, the Power floor, and nothing wider;
#   - it happens exactly once, because the search is given a B.Cu map with the
#     whole pair blanked out to USB_SHADOW either side, so no second crossing
#     can appear anywhere.
#
# The candidates are generated per straight run of the pair. Both data lines
# run parallel, so one perpendicular hop crosses both; A is the via on the
# near side, B the one on the far side, and both have to stand USB_VIA_KEEP
# off every pair segment.
def pair_runs(cop):
    dp = [(a, b) for (a, b, hw, lay, n) in cop.segs
          if lay == "F.Cu" and n == C.USB_DP]
    dm = [(a, b) for (a, b, hw, lay, n) in cop.segs
          if lay == "F.Cu" and n == C.USB_DM]
    return dp, dm


def crossing_candidates(cop, grid, hw):
    """Every (A, B) pair of via sites whose hop crosses the run once."""
    dp, dm = pair_runs(cop)
    allsegs = dp + dm
    out = []
    dirs = [(1, -1), (1, 1), (1, 0), (0, 1)]
    seen = set()
    for (pa, pb) in dp:
        vx, vy = pb[0] - pa[0], pb[1] - pa[1]
        L = math.hypot(vx, vy)
        if L < 0.5:
            continue
        ux, uy = vx / L, vy / L
        for (dx, dy) in dirs:
            # perpendicular only
            if abs(ux * dx + uy * dy) > 1e-6:
                continue
            for k in range(0, int(L / G) + 1):
                p = (pa[0] + ux * k * G, pa[1] + uy * k * G)
                for sgn in (-1, 1):
                    nxv, nyv = dx * sgn, dy * sgn
                    a = snap_out(p, (-nxv, -nyv), allsegs)
                    b = snap_out(p, (nxv, nyv), allsegs)
                    if a is None or b is None:
                        continue
                    key = (round(a[0], 3), round(a[1], 3),
                           round(b[0], 3), round(b[1], 3))
                    if key in seen:
                        continue
                    seen.add(key)
                    if crossings(a, b, dp) != 1 or crossings(a, b, dm) != 1:
                        continue
                    if grid.near(a) is None or grid.near(b) is None:
                        continue
                    if cop.seg_clear(a, b, hw, "B.Cu", NET5) is not None:
                        continue
                    if cop.via_clear(a, NET5) is not None:
                        continue
                    if cop.via_clear(b, NET5) is not None:
                        continue
                    out.append((a, b))
    return out


def snap_out(p, d, segs):
    """Walk from p along d, on the grid, to the first cell USB_VIA_KEEP clear."""
    for k in range(1, 61):
        q = (round((p[0] + d[0] * k * G) / G) * G,
             round((p[1] + d[1] * k * G) / G) * G)
        if min(C.seg_point_dist(a, b, q) for (a, b) in segs) >= USB_VIA_KEEP:
            return (round(q[0], 4), round(q[1], 4))
    return None


def crossings(a, b, segs):
    n = 0
    for (p, q) in segs:
        if _cross(a, b, p, q):
            n += 1
    return n


def _cross(p1, p2, p3, p4):
    d = ((p2[0] - p1[0]) * (p4[1] - p3[1])
         - (p2[1] - p1[1]) * (p4[0] - p3[0]))
    if abs(d) < 1e-12:
        return False
    t = ((p3[0] - p1[0]) * (p4[1] - p3[1])
         - (p3[1] - p1[1]) * (p4[0] - p3[0])) / d
    u = ((p3[0] - p1[0]) * (p2[1] - p1[1])
         - (p3[1] - p1[1]) * (p2[0] - p1[0])) / d
    return 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0


def cell(p):
    return int(round(p[0] / G)), int(round(p[1] / G))


# ---------------------------------------------------------------- the +5V -
def close_5v(cop):
    import numpy as np
    print("\n--- 3. +5V  D105 pad 1 <-> C201 pad 1")
    islands = net_islands(cop, NET5)
    src = [i for i in islands if island_with(i, "D105.1")]
    dst = [i for i in islands if island_with(i, "C201.1")]
    if not src or not dst:
        print("  FAIL: +5V has %d island(s) and D105.1/C201.1 are not on two "
              "of them" % len(islands))
        return None
    print("  +5V is in %d piece(s); the two that matter carry %d and %d item(s)"
          % (len(islands), len(src[0]), len(dst[0])))
    # The grid is anchored on (0, 0) with the same 0.1 mm step `snap_out`
    # rounds to, so the crossing's two via sites are grid points by
    # construction and the F.Cu halves end exactly on them.
    grid = Grid(cop, NET5, W5, (0.0, 0.0), G, (4.0, 3.0, 61.0, 66.0),
                flyback=True, usb_shadow=True)
    print("  grid %d x %d at %.2f mm: F.Cu %.1f%% free, B.Cu %.1f%% free "
          "(the pair's B.Cu shadow is %.2f mm), via sites %.1f%%"
          % (grid.ni, grid.nj, G, 100.0 * (~grid.F).mean(),
             100.0 * (~grid.B).mean(), USB_SHADOW, 100.0 * (~grid.V).mean()))
    g, freeF, freeB = build_graph(grid)
    sm_f = island_mask(grid, src[0], "F.Cu")
    sm_b = island_mask(grid, src[0], "B.Cu")
    tm_f = island_mask(grid, dst[0], "F.Cu")
    tm_b = island_mask(grid, dst[0], "B.Cu")
    srcs = nodes_of(grid, sm_f, sm_b, freeF, freeB)
    dsts = nodes_of(grid, tm_f, tm_b, freeF, freeB)
    if not srcs.size or not dsts.size:
        print("  FAIL: no free grid cell on the source (%d) or target (%d) "
              "copper" % (srcs.size, dsts.size))
        return None
    ds, ps = sweep(g, srcs)
    dt, pt = sweep(g, dsts)
    direct = float(np.min(dt[srcs]))
    print("  without a crossing: %s"
          % ("%.2f mm of cost" % direct if np.isfinite(direct)
             else "NO PATH on either layer - the pair walls the two halves "
                  "of the board apart, which is what the crossing is for"))
    cands = crossing_candidates(cop, grid, W5 / 2.0)
    print("  %d perpendicular crossing site(s) clear enough for two vias"
          % len(cands))
    best = None
    for (a, b) in cands:
        for swap in (False, True):
            ua, ub = (b, a) if swap else (a, b)
            ka = node_of(grid, ua, "F.Cu")
            kb = node_of(grid, ub, "F.Cu")
            if ka is None or kb is None:
                continue
            if not (np.isfinite(ds[ka]) and np.isfinite(dt[kb])):
                continue
            cost = ds[ka] + PEN_B * C.dist(ua, ub) + dt[kb] + 2 * VIA_COST
            if best is None or cost < best[0]:
                best = (cost, ua, ub, ka, kb)
    if best is None:
        print("  FAIL: no crossing site is reachable from both halves")
        return None
    cost, a, b, ka, kb = best
    print("  crossing at (%.3f, %.3f) -> (%.3f, %.3f): %.2f mm of B.Cu at 90 "
          "degrees to the pair, 2 vias, %.3f mm off the nearest pair track"
          % (a[0], a[1], b[0], b[1], C.dist(a, b),
             min(min(C.seg_point_dist(p, q, a), C.seg_point_dist(p, q, b))
                 for pair in pair_runs(cop) for (p, q) in pair)))
    head = walk_nodes(grid, ps, ka)
    tail = walk_nodes(grid, pt, kb)
    tail.reverse()          # this sweep ran from the target
    runs = []
    vias = []
    for part in (head, tail):
        rr, vv = split_runs(part)
        runs += rr
        vias += vv
    clean = []
    for layer, pts in runs:
        pts = simplify(cop, pts, W5, layer, NET5)
        why = cop.path_clear(pts, W5, layer, NET5)
        if why or not C.all_octilinear(pts):
            print("  FAIL: a %s run does not clear: %s" % (layer, why))
            return None
        clean.append((layer, pts))
    for p in vias:
        why = cop.via_clear(p, NET5)
        if why:
            print("  FAIL: an intermediate via at (%.3f, %.3f) is blocked: %s"
                  % (p[0], p[1], why))
            return None
    why = cop.seg_clear(a, b, W5 / 2.0, "B.Cu", NET5)
    if why:
        print("  FAIL: the crossing does not clear: %s" % why)
        return None
    made, per = [], collections.Counter()
    for layer, pts in clean:
        made += add_path(cop, pts, W5, layer, NET5)
        per[layer] += C.path_len(pts)
    for p in vias:
        made.append(add_via(cop, p, NET5))
    made.append(add_via(cop, a, NET5))
    made += add_path(cop, [a, b], W5, "B.Cu", NET5)
    made.append(add_via(cop, b, NET5))
    per["B.Cu"] += C.dist(a, b)
    total = sum(per.values())
    nv = len(vias) + 2
    print("  %-34s %5.2f mm (%s), %d via(s), %.2f mm wide"
          % ("D105.1 -> C201.1", total,
             ", ".join("%.2f mm %s" % (v, k) for k, v in sorted(per.items())),
             nv, W5))
    for layer, pts in clean:
        print("    %-5s %s" % (layer, " -> ".join("(%.2f, %.2f)" % q
                                                  for q in pts)))
    print("    B.Cu  (%.3f, %.3f) -> (%.3f, %.3f)   the USB crossing"
          % (a[0], a[1], b[0], b[1]))
    return made, total, nv, dict(per), (a, b)


# ------------------------------------------------------------------ main --
def group_manual(board, items):
    """Put everything drawn into the `manual` group, replacing what was there."""
    gone = 0
    for g in list(board.Groups()):
        if g.GetName() != MANUAL_GROUP:
            continue
        members = list(g.GetItems())
        board.Remove(g)
        for it in members:
            board.Remove(it)
            gone += 1
        _KEEP.extend(members)
        _KEEP.append(g)
    g = pcbnew.PCB_GROUP(board)
    g.SetName(MANUAL_GROUP)
    board.Add(g)
    for it in items:
        g.AddItem(it)
    return gone


def run_drc(tag):
    out = os.path.join(OUT, "drc-%s.json" % tag)
    os.makedirs(OUT, exist_ok=True)
    subprocess.run(["kicad-cli", "pcb", "drc", "--schematic-parity",
                    "--severity-all", "--format", "json", "-o", out, PCB],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   cwd=PROJ)
    d = json.load(open(out))
    v = d.get("violations", [])
    errs = [x for x in v if x["severity"] == "error"]
    warns = [x for x in v if x["severity"] != "error"]
    unc = d.get("unconnected_items") or []
    par = d.get("schematic_parity") or []
    print("  errors %d   warnings %d   unconnected %d   parity %d"
          % (len(errs), len(warns), len(unc), len(par)))
    print("  warnings by type: %s"
          % dict(collections.Counter(x["type"] for x in warns)))
    for x in errs[:20]:
        print("    ERROR %-26s %s" % (x["type"], x.get("description", "")[:90]))
    for u in unc[:10]:
        print("    OPEN  %s"
              % " <-> ".join(i.get("description", "?")
                             for i in (u.get("items") or [])))
    return len(errs), len(warns), len(unc), len(par)


def run_checks():
    """Re-run the pipeline's own checks on the board as it now stands.

    All four are functions of a LOADED BOARD and need no regeneration:
    `copper.keepout_clean`, `copper.width_floor_table` and
    `copper.sense_ground_table` take the clearance model, which `build_model`
    fills from the board's own copper instead of from a run that drew it, and
    `autoroute.usb_reference_check` / `autoroute.parallel_check` take the
    board. `copper.gnd_islands` is the fifth and is reported too.
    """
    import autoroute as A
    print("=== the pipeline's own checks, on the committed board ===")
    board = pcbnew.LoadBoard(PCB)
    cop = build_model(board)
    print("\n--- copper.keepout_clean (M3 rings + the crystal island)")
    bad = C.keepout_clean(cop, cop.xtal_rect)
    print("  foreign copper in the crystal keepout: %s"
          % ("none" if not bad else ", ".join(bad)))
    C.width_floor_table(cop)
    C.sense_ground_table(cop)
    print("\n--- copper.gnd_islands (GND copper that does not reach the pour)")
    isl = C.gnd_islands(cop)
    print("  %d piece(s) of GND copper off the pour" % len(isl))
    for owns, length in isl[:6]:
        print("    %6.2f mm  %s" % (length, ", ".join(owns) or "no pad"))
    manual = []
    idx = group_index(board)
    for t in board.GetTracks():
        g = idx.get(t.m_Uuid.AsString())
        if g is not None and g.GetName() == MANUAL_GROUP:
            manual.append(t)
    print("\n--- autoroute.usb_reference_check, over the %d item(s) of the "
          "%r group" % (len(manual), MANUAL_GROUP))
    ubad, uok = A.usb_reference_check(board, manual)
    print("  crossings that are NOT allowed: %s"
          % ("none" if not ubad else "%d - %s" % (len(ubad), "; ".join(ubad))))
    for line in uok:
        print("  allowed: %s" % line)
    print("\n--- autoroute.parallel_check (ADC beside switching)")
    hits = A.parallel_check(board)
    if not hits:
        print("  ADC net within %.1f mm of a switching net for more than "
              "%.1f mm: none" % (A.PARALLEL_GAP, A.PARALLEL_RUN))
    for (a, s, run, where) in hits:
        print("    %-14s beside %-20s %.2f mm near (%.1f, %.1f)"
              % (a, s, run, where[0], where[1]))
    return 0 if not ubad else 1


def main():
    if "--checks" in sys.argv:
        return run_checks()
    dry = "--dry" in sys.argv
    do_drc = "--no-drc" not in sys.argv
    refill = "--no-refill" not in sys.argv

    print("=== close_pairs.py - the last three pad pairs, drawn by hand ===")
    board = pcbnew.LoadBoard(PCB)
    cop = build_model(board)
    made = []

    print("\n--- 0. the router copper that had to move")
    for spec in NUDGES:
        got = apply_nudge(cop, board, spec)
        if got is None:
            return 1
    ripped = []
    for spec in RIPUPS:
        gone, grp = rip(cop, board, spec)
        if not gone:
            print("  FAIL: nothing ripped for %s" % spec["net"])
            return 1
        ripped.append((spec, grp))

    print("\n--- 1. /MCU/VDDA  U301 pad 9 -> C306 (copper.py's VDDA_LAYERED)")
    got = draw_layered(cop, "VDDA pin 9 to C306", "/MCU/VDDA", C.W_RAIL_MIN,
                       C.VDDA_LAYERED, cop.resolve, quiet=True)
    if got is None:
        print("  VDDA_LAYERED as copper.py has it does not fit on the "
              "committed board - its second via at (48.250, 49.225) is where "
              "the router took PEDAL_TIP. Same shape, crossing 0.75 mm "
              "further north:")
        got = draw_layered(cop, "VDDA pin 9 to C306", "/MCU/VDDA",
                           C.W_RAIL_MIN, VDDA_COMMITTED, cop.resolve)
    else:
        print("  VDDA_LAYERED fits as it stands")
    if got is None:
        return 1
    made += got[0]
    vdda = got

    print("\n--- 2. Net-(U301-PB2)  pad 20's escape -> R303 "
          "(copper.py's SIGNAL_LAYERED)")
    esc = escape_end(cop, "Net-(U301-PB2)")
    print("  the escape's via is at (%.3f, %.3f)" % esc)

    def resolve_pb2(q):
        if isinstance(q, str) and q.startswith("ESCAPE."):
            return esc
        return cop.resolve(q)

    label, net, w, runs = C.SIGNAL_LAYERED[0]
    got = draw_layered(cop, label, net, w, runs, resolve_pb2, quiet=True)
    if got is None:
        print("  SIGNAL_LAYERED as copper.py has it does not fit on the "
              "committed board: the router's ENC_A B.Cu run crosses its "
              "diagonal. Searched instead, same two ends:")
        import numpy as np
        isl = net_islands(cop, net)
        src = [i for i in isl if island_with(i, "U301.20")]
        dst = [i for i in isl if island_with(i, "R303.1")]
        if not src or not dst:
            print("  FAIL: %s is in %d piece(s) and the two ends are not on "
                  "two of them" % (net, len(isl)))
            return 1
        grid = Grid(cop, net, w, esc, 0.05, (46.0, 30.0, 60.0, 47.0))
        sf = island_mask(grid, src[0], "F.Cu")
        # the escape's own via, and only that: the B.Cu leg then starts at the
        # via's centre instead of somewhere inside its annulus
        sb = np.zeros((grid.ni, grid.nj), bool)
        sb[grid.near(esc)] = True
        df = island_mask(grid, dst[0], "F.Cu")
        db = island_mask(grid, dst[0], "B.Cu")
        path = two_layer_route(grid, sf, sb, df, db)
        if path is None:
            print("  FAIL: no F.Cu/B.Cu path from pad 20's escape to R303")
            return 1
        got = draw_searched(cop, label, net, w, path, skip_vias=(esc,))
        if got is None:
            return 1
    else:
        print("  SIGNAL_LAYERED fits as it stands")
    made += got[0]
    pb2 = got

    print("\n--- 2b. the ripped-up victim, re-routed round what is now there")
    for spec, grp in ripped:
        vnet, vw = spec["net"], spec["width"]
        isl = net_islands(cop, vnet)
        a_isl = island_at(isl, spec["ends"][0])
        b_isl = island_at(isl, spec["ends"][1])
        if a_isl is None or b_isl is None or a_isl is b_isl:
            print("  FAIL: %s is in %d piece(s) and its two ends are not on "
                  "two of them" % (vnet, len(isl)))
            return 1
        grid = Grid(cop, vnet, vw, spec["ends"][0], spec["step"],
                    spec["region"])
        path = two_layer_route(grid,
                               island_mask(grid, a_isl, "F.Cu"),
                               island_mask(grid, a_isl, "B.Cu"),
                               island_mask(grid, b_isl, "F.Cu"),
                               island_mask(grid, b_isl, "B.Cu"))
        if path is None:
            print("  FAIL: no way to put %s back" % vnet)
            return 1
        got = draw_searched(cop, "%s back between its own ends" % vnet,
                            vnet, vw, path)
        if got is None:
            return 1
        if grp is not None:
            for it in got[0]:
                grp.AddItem(it)
            print("    back into group %r, not %r" % (grp.GetName(),
                                                      MANUAL_GROUP))

    got = close_5v(cop)
    if got is None:
        return 1
    made += got[0]
    v5 = got

    print("\n--- 4. the `manual` group")
    if dry:
        print("  --dry: %d item(s) drawn in memory, nothing saved" % len(made))
        return 0
    gone = group_manual(board, made)
    print("  %d item(s) in group %r%s"
          % (len(made), MANUAL_GROUP,
             " (replacing %d from a previous run)" % gone if gone else ""))

    board.BuildConnectivity()
    if refill:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        print("  zones refilled")
    pro_before = open(PRO, "rb").read() if os.path.exists(PRO) else None
    dru_before = open(DRU, "rb").read() if os.path.exists(DRU) else None
    pcbnew.SaveBoard(PCB, board)
    for path, before in ((PRO, pro_before), (DRU, dru_before)):
        if before is None:
            continue
        with open(path, "rb") as fh:
            same = fh.read() == before
        if not same:
            with open(path, "wb") as fh:
                fh.write(before)
        print("  %s %s" % (os.path.basename(path),
                           "untouched" if same else "rewritten by SaveBoard "
                           "and RESTORED"))

    if do_drc:
        print("\n--- 5. kicad-cli DRC (--schematic-parity --severity-all)")
        run_drc("close-pairs")

    print("\n--- summary")
    for name, g in (("VDDA", vdda), ("PB2", pb2), ("+5V", v5)):
        print("  %-5s %6.2f mm, %d via(s), %s"
              % (name, g[1], g[2],
                 ", ".join("%.2f mm %s" % (v, k) for k, v in sorted(g[3].items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
