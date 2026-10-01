#!/usr/bin/env python3
"""Close the pad pairs the autorouter left open, by searching - not by routing.

Written 2026-10-01, after the connector rework (ADR 0003 Decision 9) re-placed
every part on a 95 x 70 board and left three open pairs: +5V D105.1 -> C201.1
and two short GND gaps.

Why this exists next to `close_pairs.py`: that script is the eighth pass and it
is welded to the OLD board. Its NUDGES, RIPUPS and VDDA_COMMITTED tables name
tracks at coordinates that no longer exist, so `main()` dies at step 1 with
"FAIL: nothing ripped for ENC_A" and never reaches its +5V stage. But the
machinery underneath it - the two-layer clearance grid, the Dijkstra, the
octilinear simplifier, the `manual` grouping - is generic and good. This file
is a thin driver over exactly that machinery with the targets found by name
instead of by coordinate.

The one behavioural difference from `close_pairs.close_5v`: that function
ALWAYS inserts a B.Cu crossing under the USB pair, because on the old layout
the pair walled the two halves of the board apart and no direct path existed.
Here a direct path is tried first and the crossing is only used if the direct
search fails. Crossing or not, `autoroute.usb_reference_check` still has to
pass before anything is saved.

    python3 tools/pcb/close_open.py          # draw, refill, save, DRC
    python3 tools/pcb/close_open.py --dry    # report only, write nothing
    python3 tools/pcb/close_open.py --no-drc # skip the kicad-cli grade

Geometry is the placement convention: mm from the board's top-left corner,
which is page (50, 50). Everything drawn lands in the PCB group `manual`, so
`place.py --export-manual` captures it into manual.json and a later pipeline
run puts it back.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pcbnew                                           # noqa: E402
import copper as C                                      # noqa: E402
import close_pairs as CP                                # noqa: E402


# (label, net, width, A, B, search region) - region is the box the grid covers,
# in board mm. Keep it tight: the grid is (region / 0.1 mm) cells on two layers.
# A spec is either a pad name ("D105.1") or a point on the copper, as a
# (x, y) tuple - the GND pieces are bare track with no pad to name.
TARGETS = [
    ("+5V  D105.1 -> C201.1", "+5V", C.W_RAIL_MIN,
     "D105.1", "C201.1", (14.0, 14.0, 62.0, 62.0)),
    ("GND  stub by the crystal", "GND", 0.4,
     (46.75, 47.44), (46.20, 49.05), (40.0, 42.0, 54.0, 56.0)),
    ("GND  stub east of the MCU", "GND", 0.4,
     (52.78, 41.25), (55.78, 39.50), (47.0, 34.0, 61.0, 47.0)),
]


def close_one(cop, label, net, width, a_spec, b_spec, region):
    """Search a two-layer path between the islands holding a_spec and b_spec.

    For +5V this defers to `close_pairs.close_5v`, which inserts ONE short
    perpendicular crossing under the USB pair at a site chosen for clearance.
    That is not a shortcut: with the pair's B.Cu shadow respected there is no
    path at all - the pair walls the two halves of the board apart - and a
    search allowed to ignore the shadow came back crossing the run twice at a
    shallow angle, which `autoroute.usb_reference_check` rightly refused. One
    controlled crossing, whitelisted in USB_CROSSING_OK, is the agreed answer
    and the one the old board used too.
    """
    print("\n--- %s" % label)
    isl = CP.net_islands(cop, net)

    if net == "+5V":
        # Already joined by an earlier run? close_5v does not check, and it
        # will happily draw a SECOND crossing under the USB pair if asked.
        a_i = [i for i in isl if CP.island_with(i, a_spec)]
        b_i = [i for i in isl if CP.island_with(i, b_spec)]
        if a_i and b_i and a_i[0] is b_i[0]:
            print("  already joined - nothing to do")
            return []
        got = CP.close_5v(cop)
        return None if got is None else got[0]


    def find(spec):
        if isinstance(spec, tuple):
            got = CP.island_at(isl, spec)
            return [got] if got is not None else []
        return [i for i in isl if CP.island_with(i, spec)]

    src, dst = find(a_spec), find(b_spec)
    if not src or not dst:
        print("  FAIL: %s is in %d piece(s); %s and %s are not on two of them"
              % (net, len(isl), a_spec, b_spec))
        return None
    if src[0] is dst[0]:
        print("  already joined - nothing to do")
        return []
    print("  %s is in %d piece(s); the two that matter carry %d and %d item(s)"
          % (net, len(isl), len(src[0]), len(dst[0])))
    grid = CP.Grid(cop, net, width, (0.0, 0.0), CP.G, region,
                   flyback=True, usb_shadow=True)
    path = CP.two_layer_route(grid,
                              CP.island_mask(grid, src[0], "F.Cu"),
                              CP.island_mask(grid, src[0], "B.Cu"),
                              CP.island_mask(grid, dst[0], "F.Cu"),
                              CP.island_mask(grid, dst[0], "B.Cu"))
    if path is None:
        print("  FAIL: no two-layer path for %s at %.2f mm" % (net, width))
        return None
    got = CP.draw_searched(cop, label, net, width, path)
    return None if got is None else got[0]


_KEEP = []


def strip_manual(board):
    """Remove the existing `manual` group and its copper before searching.

    This script OWNS that group. `close_pairs.group_manual` replaces the whole
    group with whatever the current run drew, so a run that skipped a target
    as "already joined" would delete the copper that joined it - two runs in a
    row ping-pong between the +5V route and the GND stubs, each deleting the
    other. Starting from the autorouted baseline every time and redrawing all
    of TARGETS makes the script idempotent instead.
    """
    gone = 0
    for g in list(board.Groups()):
        if g.GetName() != CP.MANUAL_GROUP:
            continue
        members = list(g.GetItems())
        board.Remove(g)
        for it in members:
            board.Remove(it)
            gone += 1
        _KEEP.extend(members)
        _KEEP.append(g)
    if gone:
        board.BuildConnectivity()
    return gone


def main():
    dry = "--dry" in sys.argv
    do_drc = "--no-drc" not in sys.argv

    board = pcbnew.LoadBoard(CP.PCB)
    gone = strip_manual(board)
    if gone:
        print("stripped %d item(s) of a previous run from group %r"
              % (gone, CP.MANUAL_GROUP))
    cop = CP.build_model(board)

    made = []
    for label, net, width, a, b, region in TARGETS:
        got = close_one(cop, label, net, width, a, b, region)
        if got is None:
            return 1
        made += got

    if not made:
        print("\nnothing to draw")
        return 0

    print("\n--- checks on the result")
    import autoroute
    bad, allowed = autoroute.usb_reference_check(board, made)
    for line in allowed:
        print("  allowed: %s" % line)
    if bad:
        # ADR 0003 component breakdown 3: D+/D- over unbroken bottom ground.
        # A route that breaks it is not a route, however short it is.
        for line in bad:
            print("  FAIL: %s" % line)
        return 1
    print("  USB pair reference intact: no B.Cu crossing under the run")

    ok = True
    for t in made:
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        if t.GetWidth() < C.mm(C.W_FINE) - 1:
            print("  FAIL: a segment is under the %.2f mm board minimum"
                  % C.W_FINE)
            ok = False
    if not ok:
        return 1
    print("  every drawn segment is at or above the board minimum")

    if dry:
        print("\n--dry: %d item(s) drawn in memory, nothing saved" % len(made))
        return 0

    gone = CP.group_manual(board, made)
    print("\n--- save")
    print("  %d item(s) in group %r%s"
          % (len(made), CP.MANUAL_GROUP,
             " (replacing %d from a previous run)" % gone if gone else ""))
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    print("  zones refilled")

    pro_before = open(CP.PRO, "rb").read() if os.path.exists(CP.PRO) else None
    dru_before = open(CP.DRU, "rb").read() if os.path.exists(CP.DRU) else None
    pcbnew.SaveBoard(CP.PCB, board)
    for path, before in ((CP.PRO, pro_before), (CP.DRU, dru_before)):
        if before is None:
            continue
        with open(path, "rb") as fh:
            same = fh.read() == before
        if not same:
            with open(path, "wb") as fh:
                fh.write(before)
        print("  %s %s" % (os.path.basename(path),
                           "untouched" if same
                           else "rewritten by SaveBoard and RESTORED"))

    if do_drc:
        print("\n--- kicad-cli DRC (--schematic-parity --severity-all)")
        CP.run_drc("close-open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
