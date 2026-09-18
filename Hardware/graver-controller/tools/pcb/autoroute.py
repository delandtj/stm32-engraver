#!/usr/bin/env python3
"""Route what copper.py left open, on a copy, and import only a graded result.

Runs AFTER copper.py and silk.py (or as `place.py --copper --silk --route`).
This is the routing step; tools/pcb/routability.sh is the placement TEST and
imports nothing.

What it does, in order:

  1. Removes the group AUTOROUTED_GROUP from the repo board, refills the
     zones and saves, so the stage is idempotent: a re-run replaces the
     router's copper instead of stacking it.
  2. Asks kicad-cli which nets still have unconnected pad pairs on that
     stripped board. That set - minus NO_ROUTE - is the routing scope, and
     nothing outside it is ever imported.
  3. Copies the board and the PRISTINE .kicad_pro outside the repository and
     runs KiCadRoutingTools there. Never on a repo file, per ADR 0003 risk
     "Autorouter rewrites the rules". The nets in FIRST go in a pass of their
     own so the QFN escapes get first pick of the corridors, everything else
     follows on that pass's output, and whatever is still short gets up to
     two mop-up passes with permission to rip. The whole chain runs once per
     ORDERINGS entry and the best-scoring attempt wins. No --write-fill: the
     GND pour is copper.py's and the router's refill of it ignores the
     0.25 mm hole clearance at J301's NPTH pegs. The scripted copper is
     KiCad-locked, so the router will not rip it.
  4. Grades the board this run WOULD commit - the stripped repo board plus
     the copper about to be imported, filled by pcbnew, with the pristine
     .kicad_pro beside it - with `kicad-cli pcb drc`. Not the router's own
     output file, whose re-emitted pour is 400-odd violations of its own, and
     not the router's "no violations" messages, which mean nothing.
  5. Imports tracks and vias of the scope nets that are NEW in the copy.
     A net is dropped if any of its copper is under the board minimums, if it
     is not complete on the candidate, or if a kicad-cli error names it -
     cheapest first, by the pad pairs the drop gives back. Any error left
     refuses the whole import. Imported items are NOT locked - they are the
     router's and regenerable - but they are grouped as AUTOROUTED_GROUP so
     step 1 can find them again.
  6. Refills the zones with pcbnew's ZONE_FILLER so the pour respects the
     new copper, saves, restores the .kicad_pro, and grades the repo board:
     errors, parity, unconnected, warnings by type, vias per net, the longest
     nets, the keepout check, the USB reference check and the
     ADC-versus-switching parallel-run check.

Usage:
    python3 tools/pcb/autoroute.py [options]

    --strip            remove the imported copper, refill, and stop
    --no-import        route and grade the copy, import nothing
    --reuse            do not run the router, grade/import the last copy
    --ordering NAME    one ordering instead of all of ORDERINGS
    --first A,B,...    the nets that get the first pass, instead of FIRST
    --rip              let the router rip and re-route PRE-EXISTING
                       non-locked copper that blocks it (the scripted copper
                       is locked and is never touched by this)
    --nets N [N ...]   restrict the routing scope to these nets
    --label NAME       scratch sub-directory name (default: route)
    --no-drc           skip the final kicad-cli grade of the repo board
"""

import collections
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

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

AUTOROUTED_GROUP = "autorouted"
SCRIPTED_GROUP = "scripted-copper"

SCRATCH = os.environ.get(
    "PCB_SCRATCH",
    "/tmp/claude-1000/-home-delandtj-Electronics-stm32-engraver/"
    "c35434fb-71f8-4fe0-a190-ed9924ac831a/scratchpad")
KRT_DIR = os.environ.get("KRT_DIR",
                         os.path.join(SCRATCH, "routetest", "KiCadRoutingTools"))
KRT_PY = os.environ.get("KRT_PY",
                        os.path.join(SCRATCH, "routetest", "venv", "bin", "python"))

# ------------------------------------------------------------- router ------
# ADR 0003 decision 5, the amended numbers: 0.2 mm track, 0.15 mm clearance,
# 0.6/0.3 vias. Per-net widths come out of the committed .kicad_pro net
# classes (Power 0.5, HighCurrent 0.8); GND is a Default-class net but gets
# 0.4 because its job here is the return path between two pour islands, not
# a signal.
TRACK_W = 0.2
CLEARANCE = 0.15
VIA_SIZE = 0.6
VIA_DRILL = 0.3
GRID_STEP = 0.05
GND_WIDTH = 0.4

# Nets the router must not be handed, whatever DRC says about them.
#   USB      ADR 0003: scripted, via-free, length-matched. The two pad pairs
#            kicad-cli still counts are U302's own I/O pins, which the die
#            joins and copper does not - see the README.
#   MP / NC  auto-named "unconnected-*" nets: two pads that share an
#            invented net name and nothing to route between them.
NO_ROUTE = ("/MCU/USB_DP", "/MCU/USB_DM")
# The ESD device whose two duplicate-pin links copper.py draws. Its own
# pad-to-pad copper is on the pair's nets but is not part of the pair's run -
# see usb_reference_check.
USB_DIE_BRIDGE = "U302"

# The router's net orderings, and how many attempts one stage makes.
#
# KiCadRoutingTools is NOT reproducible. Part positions are identical run to
# run but the .kicad_pcb serialisation order is not (KiCad regenerates item
# UUIDs and writes footprints in a UUID-dependent order), the net ordering
# ties break on it, and two runs of the same stage on the same placement have
# come out 13 and 20 open pad pairs apart. So the stage routes the same input
# ATTEMPTS times and imports the best of them; all of the attempts are
# printed, with their score, so the spread is visible rather than hidden.
#
# The attempts use different net orderings while the pool lasts, because a
# different ordering is a bigger perturbation than the serialisation noise,
# and repeat the pool after that. Three is the useful number here: mps and
# bus have both won, inside_out and original have never won by more than the
# noise, and a fourth attempt costs ~4 minutes for about one pad pair.
ORDERINGS = ("mps", "bus", "inside_out", "original")
ATTEMPTS = 3
ROUTE_SUMMARY = "route-summary.txt"

# Nets routed in a pass of their own, before everything else. These are the
# ones the QFN fan-out boxes in: they have one way out each and lose it to
# whatever the ordering happens to route first. Measured, not guessed - see
# "Routing the rest" in the README for the runs that produced this list.
FIRST = ("+3V3", "NTC", "OC_TRIP", "GATE_IN", "/MCU/VDDA", "PEDAL_TIP",
         "I_SENSE", "ENC_SW", "LCD_MOSI", "LCD_SCK", "LCD_DC", "LCD_RST",
         "NRST", "PEDAL_RING")

# ADC-versus-switching coupling check (ADR 0003 decision 4 / the expert Q).
ADC_NETS = ("I_SENSE", "VIN_SENSE", "NTC", "PEDAL_TIP", "PEDAL_RING")
SWITCHING_NETS = ("/Driver/COIL_NEG", "/Driver/CLAMP", "Net-(U101-SW)")
PARALLEL_GAP = 1.0        # mm, centre to centre
PARALLEL_RUN = 3.0        # mm of overlap that makes it worth reporting


def mm(v):
    return int(round(v * 1e6))


def tomm(v):
    return v / 1e6


def netname_of(item):
    return str(item.GetNetname())


def width_of(t):
    """PCB_TRACK.GetWidth(), and the layer-aware KiCad 10 form for a via."""
    if isinstance(t, pcbnew.PCB_VIA):
        try:
            return t.GetWidth(pcbnew.F_Cu)
        except TypeError:
            pass
    return t.GetWidth()


def set_width(t, w):
    if isinstance(t, pcbnew.PCB_VIA):
        try:
            t.SetWidth(pcbnew.F_Cu, w)
            return
        except TypeError:
            pass
    t.SetWidth(w)


# ------------------------------------------------------------ helpers ------
def drc_json(pcb, out, parity=True):
    cmd = ["kicad-cli", "pcb", "drc", "--severity-all", "--format", "json",
           "-o", out]
    if parity:
        cmd.append("--schematic-parity")
    cmd.append(pcb)
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(out) as fh:
        return json.load(fh)


def unconnected_nets(drc):
    """net -> number of unconnected pad pairs, from a kicad-cli DRC report."""
    c = collections.Counter()
    for u in drc.get("unconnected_items") or []:
        txt = " ".join(i.get("description", "") for i in (u.get("items") or []))
        m = re.findall(r"\[([^\]]+)\]", txt)
        if m:
            c[m[0]] += 1
    return c


def net_widths():
    """Per-net track widths, read out of the committed .kicad_pro."""
    with open(PRO) as fh:
        pro = json.load(fh)
    ns = pro["net_settings"]
    width = {c["name"]: c["track_width"] for c in ns["classes"]}
    out = [("GND", GND_WIDTH)]
    for p in ns.get("netclass_patterns") or []:
        w = width.get(p["netclass"])
        if w and abs(w - width.get("Default", TRACK_W)) > 1e-9:
            out.append((p["pattern"], w))
    return out


def strip_group(board, name):
    """Remove everything a previous run put in the group `name`.

    Same dance as copper.py: take the group off the board before its members,
    and keep the detached SWIG proxies alive for the rest of the process or
    KiCad 10 segfaults when they are collected.
    """
    grp = None
    for g in board.Groups():
        if g.GetName() == name:
            grp = g
            break
    if grp is None:
        return 0, []
    items = list(grp.GetItems())
    board.Remove(grp)
    for it in items:
        board.Remove(it)
    items.append(grp)
    return len(items) - 1, items


_DETACHED = []      # see strip_group()


def track_key(t):
    """A geometry signature that survives a save/load round trip."""
    if isinstance(t, pcbnew.PCB_VIA):
        p = t.GetPosition()
        return ("via", netname_of(t), p.x, p.y, width_of(t), t.GetDrill())
    a, b = t.GetStart(), t.GetEnd()
    ends = tuple(sorted([(a.x, a.y), (b.x, b.y)]))
    return ("seg", netname_of(t), t.GetLayer(), ends, t.GetWidth())


def copper_keys(board):
    return {track_key(t) for t in board.GetTracks()}


def seg_seg_overlap(a, b, c, d, gap):
    """Length over which segment cd runs within `gap` of segment ab.

    Sampled: the two are straight, so walking cd in small steps and asking
    for the point-to-segment distance is exact enough to decide "more than
    3 mm within 1 mm" and needs no case analysis.
    """
    cd = math.hypot(d[0] - c[0], d[1] - c[1])
    if cd < 1e-9:
        return 0.0
    n = max(2, int(cd / 0.1) + 1)
    hit = 0
    for i in range(n):
        t = i / (n - 1.0)
        p = (c[0] + (d[0] - c[0]) * t, c[1] + (d[1] - c[1]) * t)
        if point_seg_dist(p, a, b) <= gap:
            hit += 1
    return cd * hit / float(n)


def point_seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    if L < 1e-18:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / L
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (ax + dx * t), p[1] - (ay + dy * t))


# -------------------------------------------------------------- router -----
def run_router(work, scope, ordering, rip, src, dst, tag):
    shutil.copy(PRO, os.path.splitext(src)[0] + ".kicad_pro")

    pats, widths = zip(*net_widths())
    cmd = [KRT_PY, os.path.join("py_router", "route.py"), src, dst,
           "--nets"] + list(scope) + [
        "--track-width", str(TRACK_W),
        "--clearance", str(CLEARANCE),
        "--via-size", str(VIA_SIZE),
        "--via-drill", str(VIA_DRILL),
        "--grid-step", str(GRID_STEP),
        "--escalation", "off", "--strict-sizes",
        "--keepout", "--keepout-layer", "User.2",
        "--keep-input-copper",
        "--ordering", ordering,
        "--power-nets"] + list(pats) + [
        "--power-nets-widths"] + [str(w) for w in widths] + [
        "--json-out", os.path.join(work, "route-%s.json" % tag)]
    if rip:
        cmd += ["--rip-existing-nets", "*"]
    log = os.path.join(work, "route-%s.log" % tag)
    print("  router pass %s: %d net(s), ordering %s%s"
          % (tag, len(scope), ordering,
             ", ripping non-locked copper" if rip else ""))
    with open(log, "w") as fh:
        fh.write(" ".join(cmd) + "\n\n")
        fh.flush()
        subprocess.run(cmd, cwd=KRT_DIR, stdout=fh, stderr=subprocess.STDOUT)
    # The router rewrites the sibling project with its own relaxed minimums.
    shutil.copy(PRO, os.path.splitext(dst)[0] + ".kicad_pro")
    st = route_stats(work, tag)
    if st:
        print("    failed %s: %s (the tool's own grade is ignored)"
              % (st.get("failed"), ", ".join(st.get("failed_single") or []) or "-"))
    return dst


def unlock_router_copper(path):
    """Unlock everything the ROUTER wrote into `path`, keep the scripted lock.

    KiCadRoutingTools marks the tracks it lays down as KiCad-locked, and then
    refuses to rip locked copper on the next call - so a second pass with
    --rip-existing-nets sees a board where every net is "locked" and can move
    nothing. The scripted copper (the SCRIPTED_GROUP members) must keep its
    lock; that is what ADR 0003 decision 8 relies on. Everything else this
    run made is the router's own and is fair game for the next pass.
    """
    board = pcbnew.LoadBoard(path)
    keep = set()
    for g in board.Groups():
        if g.GetName() == SCRIPTED_GROUP:
            keep = {it.m_Uuid.AsString() for it in g.GetItems()}
    n = 0
    for t in board.GetTracks():
        if t.m_Uuid.AsString() in keep or not t.IsLocked():
            continue
        t.SetLocked(False)
        n += 1
    if n:
        pcbnew.SaveBoard(path, board)
    return n


def route_stats(work, tag):
    try:
        with open(os.path.join(work, "route-%s.json" % tag)) as fh:
            d = json.load(fh)
    except Exception:
        return {}
    return d


# --------------------------------------------------------------- import ----
def new_copper(routed, scope, before_keys):
    """The router's NEW tracks and vias, per net."""
    by_net = collections.defaultdict(list)
    for t in routed.GetTracks():
        net = netname_of(t)
        if net not in scope:
            continue
        if track_key(t) in before_keys:
            continue
        by_net[net].append(t)
    return by_net


def undersized(items):
    """Copper the router made below the board minimums, despite --strict-sizes.

    The tool's "net rescue" pass narrows a track or a via when it cannot
    otherwise close a net, and then writes the relaxed floor into the sibling
    .kicad_pro so its own check passes. ADR 0003 decision 5 says no smaller
    via anywhere; this is the gate that enforces it on the way in.
    """
    bad = []
    for t in items:
        if isinstance(t, pcbnew.PCB_VIA):
            if width_of(t) < mm(VIA_SIZE) - 1 or t.GetDrill() < mm(VIA_DRILL) - 1:
                bad.append("via %.3f/%.3f mm at (%.2f, %.2f)"
                           % (tomm(width_of(t)), tomm(t.GetDrill()),
                              tomm(t.GetPosition().x), tomm(t.GetPosition().y)))
        elif t.GetWidth() < mm(TRACK_W) - 1:
            bad.append("track %.3f mm at (%.2f, %.2f)"
                       % (tomm(t.GetWidth()), tomm(t.GetStart().x),
                          tomm(t.GetStart().y)))
    return bad


def import_copper(board, by_net, nets):
    """Copy the router's new copper for `nets` into `board`, unlocked+grouped."""
    made = []
    for net in sorted(nets):
        ni = board.FindNet(net)
        if ni is None:
            print("  net %r is not on the repo board - skipped" % net)
            continue
        code = ni.GetNetCode()
        for t in by_net.get(net, []):
            if isinstance(t, pcbnew.PCB_VIA):
                it = pcbnew.PCB_VIA(board)
                it.SetPosition(t.GetPosition())
                it.SetViaType(pcbnew.VIATYPE_THROUGH)
                it.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                set_width(it, width_of(t))
                it.SetDrill(t.GetDrill())
            else:
                it = pcbnew.PCB_TRACK(board)
                it.SetStart(t.GetStart())
                it.SetEnd(t.GetEnd())
                it.SetWidth(t.GetWidth())
                it.SetLayer(t.GetLayer())
            it.SetNetCode(code)
            it.SetLocked(False)
            board.Add(it)
            made.append(it)
    if made:
        g = pcbnew.PCB_GROUP(board)
        g.SetName(AUTOROUTED_GROUP)
        board.Add(g)
        for it in made:
            g.AddItem(it)
    return made


def build_candidate(by_net, nets, path):
    """The board this run WOULD commit: stripped repo board + those nets.

    Graded instead of the router's own output file, because the router's
    writer re-emits the GND pour and its refill ignores the 0.25 mm hole
    clearance at J301's NPTH pegs - 400-odd violations that say nothing
    about the tracks. This candidate is filled by pcbnew, exactly as the
    committed board is.
    """
    board = pcbnew.LoadBoard(PCB)
    made = import_copper(board, by_net, nets)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(path, board)
    shutil.copy(PRO, os.path.splitext(path)[0] + ".kicad_pro")
    return board, made


def attributable(drc, scope):
    """Split the copy's errors into "the router's tracks did this" and not.

    The known non-attributable one is the router's refill of the scripted GND
    pour, which does not apply the 0.25 mm hole clearance to J301's two NPTH
    pegs: its items are a Zone and a hole, never a track of ours. An error is
    ours if any of its items IS a track or via on a net we intend to import.
    """
    mine, theirs = [], []
    for v in drc.get("violations", []):
        if v["severity"] != "error":
            continue
        own = False
        for it in v.get("items") or []:
            d = it.get("description", "")
            m = re.match(r"(Track|Via)\s*\[([^\]]+)\]", d)
            if m and m.group(2) in scope:
                own = True
        (mine if own else theirs).append(v)
    return mine, theirs


# ---------------------------------------------------------------- report ---
def net_metrics(board, nets=None):
    """length (mm) and via count per net, over the whole board."""
    length = collections.Counter()
    vias = collections.Counter()
    for t in board.GetTracks():
        n = netname_of(t)
        if nets is not None and n not in nets:
            continue
        if isinstance(t, pcbnew.PCB_VIA):
            vias[n] += 1
        else:
            length[n] += tomm(t.GetLength())
    return length, vias


def user2_polys(board):
    """The keepout outlines copper.py drew on User.2, as point lists."""
    out = []
    for d in board.GetDrawings():
        if d.GetLayerName() != "User.2":
            continue
        if not isinstance(d, pcbnew.PCB_SHAPE):
            continue
        try:
            sp = d.GetPolyShape()
        except Exception:
            continue
        if sp.OutlineCount() == 0:
            continue
        o = sp.Outline(0)
        pts = [(tomm(o.CPoint(i).x), tomm(o.CPoint(i).y))
               for i in range(o.PointCount())]
        if len(pts) >= 3:
            out.append(pts)
    return out


def point_in_poly(p, poly):
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def keepout_check(board, items):
    """Autorouted copper inside a User.2 keepout (crystal island, M3 rings).

    copper.py draws the M3 rings as 24-point circles and the crystal island as
    a 4-point rectangle, which is enough to tell them apart. The verdict is
    not the same for the two: nothing at all may sit in an M3 ring, and the
    crystal island is a no-VIAS rule area that copper.py's own clearance model
    lets GND into (the ground guard is GND and the pour is under it by
    design), so a GND track there is a note and anything else is a failure.
    """
    polys = user2_polys(board)
    bad, notes = [], []
    for it in items:
        if isinstance(it, pcbnew.PCB_VIA):
            samples = [(tomm(it.GetPosition().x), tomm(it.GetPosition().y))]
            what = "via"
        else:
            a = (tomm(it.GetStart().x), tomm(it.GetStart().y))
            b = (tomm(it.GetEnd().x), tomm(it.GetEnd().y))
            n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.1) + 1)
            samples = [(a[0] + (b[0] - a[0]) * i / (n - 1.0),
                        a[1] + (b[1] - a[1]) * i / (n - 1.0))
                       for i in range(n)]
            what = it.GetLayerName()
        net = netname_of(it)
        for poly in polys:
            if not any(point_in_poly(s, poly) for s in samples):
                continue
            where = "crystal island" if len(poly) == 4 else "M3 ring"
            line = "%s %s [%s] at (%.2f, %.2f)" % (where, what, net,
                                                   samples[0][0], samples[0][1])
            if where == "crystal island" and net == "GND" and what != "via":
                notes.append(line)
            else:
                bad.append(line)
            break
    return bad, notes


def usb_reference_check(board, items):
    """Imported B.Cu copper crossing under the USB pair.

    ADR 0003 component breakdown 3 wants D+/D- "over unbroken bottom ground".
    The pair's own locked F.Cu copper keeps other F.Cu off it and nothing
    keeps the router off the B.Cu underneath, so this is checked rather than
    assumed; copper.py's User.2 bands along the pair are what prevents it.

    What counts is a track that actually CROSSES the run, not one that passes
    near it: at the MCU's 0.5 mm pitch the pair's last millimetre has pads 32
    and 34's escapes either side of it by construction, and no proximity rule
    can tell those apart from a broken reference.

    `USB_DIE_BRIDGE` is excluded, and only that. copper.py draws a 1.35 mm
    link across U302 between each of the ESD device's two duplicate I/O pins
    (see the README) so that kicad-cli stops counting them as unconnected.
    Those links are on the pair's nets but they are not the pair's RUN - the
    37.88 mm ADR 0003 asks to keep over unbroken ground is the copper between
    J301, U302 and the MCU, and the band copper.py lays along it covers all
    of that. A B.Cu track passing under the ESD device's own pad-to-pad link
    is 0.35 mm of reference under a 2.3 mm hop between two pads of one part;
    banding it as well only pushes the router off SWDIO and VBUS for nothing.
    """
    keep = board.FindFootprintByReference(USB_DIE_BRIDGE)
    box = keep.GetBoundingBox() if keep else None
    pair = []
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        if netname_of(t) in NO_ROUTE and t.GetLayerName() == "F.Cu":
            if box is not None and (box.Contains(t.GetStart())
                                    and box.Contains(t.GetEnd())):
                continue
            pair.append(((tomm(t.GetStart().x), tomm(t.GetStart().y)),
                         (tomm(t.GetEnd().x), tomm(t.GetEnd().y))))
    bad = []
    for it in items:
        if isinstance(it, pcbnew.PCB_VIA) or it.GetLayerName() != "B.Cu":
            continue
        a = (tomm(it.GetStart().x), tomm(it.GetStart().y))
        b = (tomm(it.GetEnd().x), tomm(it.GetEnd().y))
        for (p, q) in pair:
            x = seg_cross(p, q, a, b)
            if x:
                bad.append("%s crosses the pair at (%.2f, %.2f)"
                           % (netname_of(it), x[0], x[1]))
                break
    return sorted(set(bad))


def seg_cross(p1, p2, p3, p4):
    """Where segments p1-p2 and p3-p4 cross, or None."""
    d = ((p2[0] - p1[0]) * (p4[1] - p3[1])
         - (p2[1] - p1[1]) * (p4[0] - p3[0]))
    if abs(d) < 1e-12:
        return None
    t = ((p3[0] - p1[0]) * (p4[1] - p3[1])
         - (p3[1] - p1[1]) * (p4[0] - p3[0])) / d
    u = ((p3[0] - p1[0]) * (p2[1] - p1[1])
         - (p3[1] - p1[1]) * (p2[0] - p1[0])) / d
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))
    return None


def parallel_check(board):
    """ADC nets running beside the switching nets: length within PARALLEL_GAP."""
    segs = collections.defaultdict(list)
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        n = netname_of(t)
        if n in ADC_NETS or n in SWITCHING_NETS:
            segs[n].append((t.GetLayer(),
                            (tomm(t.GetStart().x), tomm(t.GetStart().y)),
                            (tomm(t.GetEnd().x), tomm(t.GetEnd().y))))
    hits = []
    for a in ADC_NETS:
        for s in SWITCHING_NETS:
            run = 0.0
            where = None
            for (la, p1, p2) in segs.get(a, []):
                for (ls, q1, q2) in segs.get(s, []):
                    if la != ls:
                        continue
                    ov = seg_seg_overlap(q1, q2, p1, p2, PARALLEL_GAP)
                    if ov > 0.01:
                        run += ov
                        if where is None:
                            where = p1
            if run >= PARALLEL_RUN:
                hits.append((a, s, run, where))
    return hits


def report_board(board, imported_nets, items, do_drc):
    print("\n=== repo board after import ===")
    if do_drc:
        os.makedirs(OUT, exist_ok=True)
        d = drc_json(PCB, os.path.join(OUT, "drc-route.json"))
        v = d.get("violations", [])
        errs = [x for x in v if x["severity"] == "error"]
        warns = [x for x in v if x["severity"] != "error"]
        unc = d.get("unconnected_items") or []
        par = d.get("schematic_parity") or []
        print("  errors %d   parity %d   unconnected %d   warnings %d"
              % (len(errs), len(par), len(unc), len(warns)))
        print("  errors by type:   %s"
              % dict(collections.Counter(x["type"] for x in errs)))
        print("  warnings by type: %s"
              % dict(collections.Counter(x["type"] for x in warns)))
        for x in errs[:20]:
            print("    ERROR %-26s %s"
                  % (x["type"], x.get("description", "")[:110]))
        left = unconnected_nets(d)
        if left:
            print("  still unconnected (%d pad pair(s) over %d net(s)):"
                  % (sum(left.values()), len(left)))
            for n, k in left.most_common():
                print("    %-34s %d" % (n, k))

    length, vias = net_metrics(board)
    print("\n  total vias on the board: %d  (autorouted: %d)"
          % (sum(vias.values()),
             len([i for i in items if isinstance(i, pcbnew.PCB_VIA)])))
    if imported_nets:
        print("  imported nets, length and vias:")
        for n in sorted(imported_nets,
                        key=lambda n: -length.get(n, 0.0)):
            print("    %-34s %7.2f mm  %2d via(s)"
                  % (n, length.get(n, 0.0), vias.get(n, 0)))
    print("\n  longest 10 nets on the board:")
    for n, L in sorted(length.items(), key=lambda kv: -kv[1])[:10]:
        print("    %-34s %7.2f mm  %2d via(s)" % (n, L, vias.get(n, 0)))

    bad, notes = keepout_check(board, items)
    print("\n  autorouted copper in an M3 ring, or a via or a foreign net in "
          "the crystal island: %s"
          % ("none" if not bad else "%d - %s" % (len(bad), "; ".join(bad[:8]))))
    if notes:
        print("  GND track(s) the router laid across the crystal island (%d, "
              "allowed - the guard is GND and the pour is under it): %s"
              % (len(notes), "; ".join(notes[:4])))

    usb = usb_reference_check(board, items)
    print("  imported B.Cu copper crossing under the USB pair (ADR: unbroken "
          "bottom ground): %s"
          % ("none" if not usb else "%d - %s" % (len(usb), "; ".join(usb[:6]))))
    bad += usb

    hits = parallel_check(board)
    if not hits:
        print("  ADC net running within %.1f mm of a switching net for more "
              "than %.1f mm: none" % (PARALLEL_GAP, PARALLEL_RUN))
    else:
        print("  ADC/switching parallel runs (%d):" % len(hits))
        for (a, s, run, where) in hits:
            print("    %-14s beside %-20s %.2f mm near (%.1f, %.1f)"
                  % (a, s, run, where[0], where[1]))
    return bad, hits


# ============================================================== main =======
def main():
    argv = sys.argv[1:]

    def opt(name, default=None):
        if name in argv:
            i = argv.index(name)
            return argv[i + 1] if i + 1 < len(argv) else default
        return default

    do_strip_only = "--strip" in argv
    do_import = "--no-import" not in argv
    do_drc = "--no-drc" not in argv
    reuse = "--reuse" in argv
    rip = "--rip" in argv
    ordering = opt("--ordering")
    label = opt("--label", "route")
    only = []
    if "--nets" in argv:
        i = argv.index("--nets") + 1
        while i < len(argv) and not argv[i].startswith("--"):
            only.append(argv[i])
            i += 1
    first = [n for n in (opt("--first", "") or "").split(",") if n] or list(FIRST)

    for path, what in ((KRT_DIR, "KRT_DIR"), (KRT_PY, "KRT_PY")):
        if not reuse and not do_strip_only and not os.path.exists(path):
            print("%s not found: %s" % (what, path))
            return 2

    work = os.path.join(SCRATCH, "autoroute", label)
    real = os.path.realpath(work)
    repo = subprocess.run(["git", "-C", PROJ, "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True).stdout.strip()
    if repo and (real == os.path.realpath(repo)
                 or real.startswith(os.path.realpath(repo) + os.sep)):
        print("REFUSING: work dir %s is inside the git repo %s" % (real, repo))
        return 3
    os.makedirs(work, exist_ok=True)

    pro_before = open(PRO, "rb").read()

    # --- 1. strip whatever a previous run imported ----------------------
    board = pcbnew.LoadBoard(PCB)
    gone, detached = strip_group(board, AUTOROUTED_GROUP)
    _DETACHED.extend(detached)
    print("autorouted copper: removed %d item(s) from a previous run" % gone)
    if gone:
        board.BuildConnectivity()
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(PCB, board)
        print("  wrote the stripped board and refilled the zones")
    if do_strip_only:
        restore_pro(pro_before)
        return 0

    before_keys = copper_keys(board)
    board_nets = {netname_of(t) for t in board.GetTracks()}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            board_nets.add(str(p.GetNetname()))

    # --- 2. what is still open -----------------------------------------
    # kicad-cli prints the net name unescaped; the .kicad_pcb (and so the
    # router) spells '/' in a net name as '{slash}'. Map back, or the router
    # reports "net does not exist" and silently skips it.
    unescape = {n.replace("{slash}", "/"): n for n in board_nets}
    os.makedirs(OUT, exist_ok=True)
    d0 = drc_json(PCB, os.path.join(OUT, "drc-preroute.json"))
    open0 = unconnected_nets(d0)
    scope = sorted(unescape.get(n, n) for n in open0
                   if n not in NO_ROUTE and not n.startswith("unconnected-"))
    skipped = sorted(n for n in open0 if unescape.get(n, n) not in scope)
    if only:
        scope = [n for n in scope if n in only or n.replace("{slash}", "/") in only]
    print("\nopen before: %d pad pair(s) over %d net(s); routing %d, "
          "skipping %d (%s)"
          % (sum(open0.values()), len(open0), len(scope), len(skipped),
             ", ".join(skipped) or "-"))

    # --- 3/4/5. route a copy, grade it, keep the best attempt -----------
    # The board is handed to the router in passes: nets named with --first go
    # in a pass of their own and so get first pick of the corridors, which is
    # the one lever that moves the nets the QFN fan-out boxes in. Everything
    # else follows on that pass's output, and the nets that are still short
    # get a mop-up pass with permission to rip.
    #
    # The tool's result is NOT reproducible from one board file to the next -
    # part positions are identical run to run but the serialisation order is
    # not, and the net ordering ties break on it. Several orderings are tried
    # and the best-scoring attempt is the one that gets imported; an ordering
    # that leaves five pad pairs open and one that leaves twelve are both
    # things it does with the same input.
    head = [n for n in first if n in scope]
    tail = [n for n in scope if n not in head]

    def gate_and_grade(wd, path, tag, quiet=False):
        """Build the board this run WOULD commit from `path`, and grade it.

        Graded instead of the router's own output file, because the router's
        writer re-emits the GND pour and its refill ignores the 0.25 mm hole
        clearance at J301's NPTH pegs - 400-odd violations that say nothing
        about the tracks.
        """
        cand = os.path.join(wd, "candidate.kicad_pcb")
        routed = pcbnew.LoadBoard(path)
        by_net = new_copper(routed, set(scope), before_keys)
        take = set(by_net)
        for net in sorted(by_net):
            bad = undersized(by_net[net])
            if bad:
                take.discard(net)
                if not quiet:
                    print("  DROPPED %s: below the board minimums - %s"
                          % (net, "; ".join(bad[:3])))
        _, made = build_candidate(by_net, take, cand)
        dc = drc_json(cand, os.path.join(wd, "drc-%s.json" % tag), parity=False)
        openc = unconnected_nets(dc)
        short = sorted(n for n in take
                       if openc.get(n.replace("{slash}", "/")) or openc.get(n))
        return dict(wd=wd, path=path, routed=routed, by_net=by_net, take=take,
                    made=made, drc=dc, short=short, cand=cand)

    def finalize(a):
        """Drop what is incomplete, then whatever still causes an error."""
        if a["short"]:
            print("  incomplete in the copy, NOT imported (%d): %s"
                  % (len(a["short"]), ", ".join(a["short"])))
            a["take"] -= set(a["short"])
            _, a["made"] = build_candidate(a["by_net"], a["take"], a["cand"])
            a["drc"] = drc_json(a["cand"], os.path.join(a["wd"], "drc.json"),
                                parity=False)
        # One net at a time, cheapest first: a violation names two nets and
        # dropping the wrong one of them can cost twenty pad pairs to save
        # two. "Cheapest" is how many pad pairs the net had open before the
        # router touched it, which is exactly what dropping it gives back.
        for _ in range(8):
            mine, _th = attributable(a["drc"], a["take"])
            if not mine:
                break
            guilty = set()
            for x in mine:
                for it in x.get("items") or []:
                    m = re.match(r"(Track|Via)\s*\[([^\]]+)\]",
                                 it.get("description", ""))
                    if m and m.group(2) in a["take"]:
                        guilty.add(m.group(2))
                print("  ATTRIBUTABLE %-20s %s"
                      % (x["type"], x.get("description", "")[:90]))
            if not guilty:
                print("  the error is not on a net this run would import")
                break
            net = min(guilty, key=lambda n: (open0.get(
                n.replace("{slash}", "/"), 0), n))
            print("  dropping %s (%d pad pair(s)) and rebuilding the candidate"
                  % (net, open0.get(net.replace("{slash}", "/"), 0)))
            a["take"].discard(net)
            _, a["made"] = build_candidate(a["by_net"], a["take"], a["cand"])
            a["drc"] = drc_json(a["cand"], os.path.join(a["wd"], "drc.json"),
                                parity=False)
        a["errs"] = [x for x in a["drc"].get("violations", [])
                     if x["severity"] == "error"]
        a["open"] = sum(unconnected_nets(a["drc"]).values())
        return a

    def attempt(tag, name):
        wd = os.path.join(work, tag)
        os.makedirs(wd, exist_ok=True)
        out = os.path.join(wd, "routed.kicad_pcb")
        if not reuse:
            src = os.path.join(wd, "in.kicad_pcb")
            shutil.copy(PCB, src)
            if head:
                src = run_router(wd, head, name, rip, src,
                                 os.path.join(wd, "stage1.kicad_pcb"), "1")
            run_router(wd, tail, name, rip, src, out, "2")
        if not os.path.exists(out):
            return None
        a = gate_and_grade(wd, out, "2")
        mop = 0
        while a["short"] and not reuse and mop < 2:
            mop += 1
            print("  still short after pass %d: %s - mopping up with a rip"
                  % (mop + 1, ", ".join(a["short"])))
            nxt = os.path.join(wd, "mop%d.kicad_pcb" % mop)
            n = unlock_router_copper(a["path"])
            if n:
                print("    unlocked %d of the router's own track(s)" % n)
            run_router(wd, a["short"], name, True, a["path"], nxt, "m%d" % mop)
            if not os.path.exists(nxt):
                break
            b = gate_and_grade(wd, nxt, "m%d" % mop)
            if set(b["short"]) >= set(a["short"]):
                a = b
                break
            a = b
        return finalize(a)

    # The same input, routed ATTEMPTS times, and the best of them imported.
    # The tool is not deterministic (see ORDERINGS above), so one run is a
    # sample and not a result: the scoring order is errors, then open pad
    # pairs, then VIAS, then how many nets were taken.
    plan = ([ordering] if ordering else
            [ORDERINGS[i % len(ORDERINGS)] for i in range(ATTEMPTS)])
    print("\n--- routing a copy in %s, %d attempt(s): %s"
          % (work, len(plan), ", ".join(plan)))
    best, table = None, []
    for i, name in enumerate(plan):
        tag = name if plan.count(name) == 1 else "%s-%d" % (name, i + 1)
        print("\n  == attempt %d of %d, ordering %s =="
              % (i + 1, len(plan), name))
        a = attempt(tag, name)
        if a is None:
            print("  the router produced no output")
            table.append((tag, None, None, None, None))
            continue
        nvias = len([x for x in a["made"] if isinstance(x, pcbnew.PCB_VIA)])
        a["vias"] = nvias
        print("  attempt %-13s -> %d error(s), %d unconnected pad pair(s), "
              "%d via(s), %d net(s) imported"
              % (tag, len(a["errs"]), a["open"], nvias, len(a["take"])))
        table.append((tag, len(a["errs"]), a["open"], nvias, len(a["take"])))
        key = (len(a["errs"]), a["open"], nvias, -len(a["take"]))
        if best is None or key < best[0]:
            best = (key, a)
    print("\n  attempt        errors  open  vias  nets")
    for tag, e, o, v, n in table:
        if e is None:
            print("  %-14s %s" % (tag, "no output"))
        else:
            print("  %-14s %6d %5d %5d %5d%s"
                  % (tag, e, o, v, n,
                     "   <- imported" if best and best[1]["wd"].endswith(tag)
                     else ""))
    if best is None:
        restore_pro(pro_before)
        return 1
    a = best[1]
    routed, by_net, take, made, dc = (a["routed"], a["by_net"], a["take"],
                                      a["made"], a["drc"])
    errs = a["errs"]
    mine, theirs = attributable(dc, take)
    print("\n  best attempt: %s - %d error(s), %d unconnected pad pair(s)"
          % (os.path.basename(a["wd"]), len(errs), a["open"]))
    nothing = sorted(n for n in scope if n not in by_net)
    if nothing:
        print("  the router produced no copper at all for (%d): %s"
              % (len(nothing), ", ".join(nothing)))
    for x in theirs:
        print("  not attributable to imported copper: %-20s %s"
              % (x["type"], x.get("description", "")[:90]))
    if errs:
        print("\nREFUSING TO IMPORT: the candidate board has %d kicad-cli "
              "error(s) (%d attributable to imported copper)."
              % (len(errs), len(mine)))
        restore_pro(pro_before)
        return 1

    rl, rv = net_metrics(routed, take)
    ntr = len([i for i in made if not isinstance(i, pcbnew.PCB_VIA)])
    nvi = len([i for i in made if isinstance(i, pcbnew.PCB_VIA)])
    print("\n  routed and complete: %d net(s), %d track(s), %d via(s)"
          % (len(take), ntr, nvi))
    for n in sorted(take, key=lambda n: -rl.get(n, 0.0))[:10]:
        print("    %-34s %7.2f mm  %2d via(s)"
              % (n, rl.get(n, 0.0), rv.get(n, 0)))

    # The chosen scratch copy's summary, so a run can be compared with the
    # last one without re-reading the whole log. Nothing in $PCB_SCRATCH is
    # ever committed; this file is the only thing that survives it.
    os.makedirs(OUT, exist_ok=True)
    summary = os.path.join(OUT, ROUTE_SUMMARY)
    with open(summary, "w") as fh:
        fh.write("route stage %s\n" % time.strftime("%Y-%m-%d %H:%M"))
        fh.write("open before: %d pad pair(s) over %d net(s)\n"
                 % (sum(open0.values()), len(open0)))
        if reuse:
            fh.write("mode: --reuse - the copies were re-graded and NOT "
                     "re-routed, so the mop-up passes did not run and these "
                     "attempt scores are not comparable with a full run\n")
        fh.write("attempts (the router is not deterministic; the best is "
                 "imported, scored on errors, then open, then vias)\n")
        fh.write("  %-14s %6s %5s %5s %5s\n"
                 % ("attempt", "errors", "open", "vias", "nets"))
        for tag, e, o, v, n in table:
            if e is None:
                fh.write("  %-14s no output\n" % tag)
            else:
                fh.write("  %-14s %6d %5d %5d %5d%s\n"
                         % (tag, e, o, v, n,
                            "   <- imported" if a["wd"].endswith(tag) else ""))
        fh.write("chosen copy: %s\n" % a["wd"])
        fh.write("  errors      %d\n" % len(errs))
        fh.write("  open        %d pad pair(s)\n" % a["open"])
        fh.write("  vias        %d imported\n" % nvi)
        fh.write("  tracks      %d imported\n" % ntr)
        fh.write("  nets        %d of %d in scope\n" % (len(take), len(scope)))
        if nothing:
            fh.write("  no copper at all for: %s\n" % ", ".join(nothing))
        fh.write("longest nets in the imported copper\n")
        for n in sorted(take, key=lambda n: -rl.get(n, 0.0))[:10]:
            fh.write("  %-34s %7.2f mm  %2d via(s)\n"
                     % (n, rl.get(n, 0.0), rv.get(n, 0)))
    print("\nwrote %s" % summary)

    if not do_import:
        print("\n--no-import: stopping before the repo board is touched")
        restore_pro(pro_before)
        return 0

    # --- 6. import into the repo board, refill, save --------------------
    items = import_copper(board, by_net, take)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    print("\nimported into %r: %d track(s), %d via(s) over %d net(s); "
          "unlocked, grouped, zones refilled"
          % (AUTOROUTED_GROUP, ntr, nvi, len(take)))
    print("wrote %s" % PCB)
    restore_pro(pro_before)

    bad, hits = report_board(board, take, items, do_drc)
    return 1 if bad else 0


def restore_pro(pro_before):
    with open(PRO, "rb") as fh:
        same = fh.read() == pro_before
    if not same:
        with open(PRO, "wb") as w:
            w.write(pro_before)
        print("restored %s (SaveBoard had rewritten it)"
              % os.path.basename(PRO))
    else:
        print("%s unchanged" % os.path.basename(PRO))


if __name__ == "__main__":
    sys.exit(main())
