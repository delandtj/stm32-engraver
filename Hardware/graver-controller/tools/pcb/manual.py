#!/usr/bin/env python3
"""Keep hand-drawn copper across a regeneration of the board.

`place.py` rebuilds `graver-controller.kicad_pcb` from the schematic on every
run, so anything Jan draws by hand in pcbnew is gone the next time the
pipeline runs. Every other piece of copper on this board belongs to a script
and to a PCB group that its own script strips and remakes:

    scripted-copper   copper.py
    scripted-silk     silk.py
    autorouted        autoroute.py

A track that is in NONE of those is by definition a hand route, and that is
the whole rule this file implements - there is no marker to set and nothing to
remember to do in the GUI.

    python3 tools/pcb/place.py --export-manual   # board -> tools/pcb/manual.json
    python3 tools/pcb/manual.py --export         # the same, standalone
    python3 tools/pcb/manual.py --restore        # manual.json -> board

`place.py` runs the restore itself as the LAST step of a pipeline run, after
copper.py, silk.py and autoroute.py, and refills the zones so the pour closes
round whatever came back. The restored items go into a group named `manual`,
which is what makes the next export find them again.

Order matters and only one way round works: export BEFORE regenerating,
because the regeneration is what destroys them.

The items are written as geometry and net NAMES, not UUIDs - a UUID does not
survive `place.py` rebuilding the footprint it hangs off. A net that no longer
exists on the board is reported and skipped rather than silently dropped.
"""

import json
import os
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
STORE = os.path.join(HERE, "manual.json")

ORIGIN = (50.0, 50.0)          # must match place.py / copper.py
MANUAL_GROUP = "manual"
# The groups every GENERATED item on this board belongs to. Anything outside
# them is a hand route.
#
# MANUAL_GROUP is deliberately NOT in this tuple, and that is the fix for a
# bug the README already described the right behaviour for: a restore puts the
# hand copper into `manual`, so if the export skipped that group as well then
# the very next `--export-manual` would collect nothing, delete the store and
# take every hand route off the board on the following restore. The group name
# is what makes the next export find the same items again - it has to be
# collected, not skipped.
SCRIPTED_GROUPS = ("scripted-copper", "scripted-silk", "autorouted")

LAYERS = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}


def mm(v):
    return pcbnew.FromMM(v)


def tomm(v):
    return pcbnew.ToMM(v)


def at(p):
    return pcbnew.VECTOR2I(mm(ORIGIN[0] + p[0]), mm(ORIGIN[1] + p[1]))


def loc(pos):
    return [round(tomm(pos.x) - ORIGIN[0], 4), round(tomm(pos.y) - ORIGIN[1], 4)]


def layer_name(item):
    for name, lid in LAYERS.items():
        if item.GetLayer() == lid:
            return name
    return item.GetBoard().GetLayerName(item.GetLayer())


def group_of(item, board):
    """The name of the group this item is in, or None."""
    for g in board.Groups():
        for it in g.GetItems():
            if it.m_Uuid.AsString() == item.m_Uuid.AsString():
                return g.GetName()
    return None


def _group_index(board):
    """uuid -> group name, built once; group_of is O(groups x items)."""
    idx = {}
    for g in board.Groups():
        for it in g.GetItems():
            idx[it.m_Uuid.AsString()] = g.GetName()
    return idx


def collect(board):
    """Every track, via and arc that is in no scripted group."""
    idx = _group_index(board)
    out = []
    for t in board.Tracks():
        if idx.get(t.m_Uuid.AsString()) in SCRIPTED_GROUPS:
            continue
        net = t.GetNetname()
        if isinstance(t, pcbnew.PCB_VIA):
            top, bot = t.TopLayer(), t.BottomLayer()
            out.append(dict(kind="via", net=net, pos=loc(t.GetPosition()),
                            size=round(tomm(t.GetWidth(top)), 4),
                            drill=round(tomm(t.GetDrill()), 4),
                            layers=[board.GetLayerName(top),
                                    board.GetLayerName(bot)]))
        elif isinstance(t, pcbnew.PCB_ARC):
            out.append(dict(kind="arc", net=net, layer=layer_name(t),
                            start=loc(t.GetStart()), mid=loc(t.GetMid()),
                            end=loc(t.GetEnd()),
                            width=round(tomm(t.GetWidth()), 4)))
        else:
            out.append(dict(kind="track", net=net, layer=layer_name(t),
                            start=loc(t.GetStart()), end=loc(t.GetEnd()),
                            width=round(tomm(t.GetWidth()), 4)))
    return out


def export(pcb=PCB, store=STORE, quiet=False):
    """Board -> manual.json. Writes nothing when there is nothing to keep."""
    board = pcbnew.LoadBoard(pcb)
    items = collect(board)
    if not items:
        if os.path.exists(store):
            os.remove(store)
            if not quiet:
                print("manual copper: none on the board; removed %s"
                      % os.path.relpath(store, PROJ))
        elif not quiet:
            print("manual copper: none on the board, nothing to write")
        return 0
    with open(store, "w") as fh:
        json.dump({"note": "Hand-drawn copper, re-added by place.py as the "
                           "last step of a pipeline run. Coordinates are mm "
                           "from the board's top-left corner, which is page "
                           "(%.0f, %.0f)." % ORIGIN,
                   "items": items}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    kinds = {}
    for it in items:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    if not quiet:
        print("manual copper: %d item(s) (%s) -> %s"
              % (len(items), ", ".join("%d %s" % (v, k)
                                       for k, v in sorted(kinds.items())),
                 os.path.relpath(store, PROJ)))
        for it in items:
            print("  %-6s %-22s %s" % (it["kind"], it["net"] or "-",
                                       it.get("layer", "/".join(
                                           it.get("layers", ())))))
    return len(items)


def _net(board, name):
    n = board.FindNet(name) if name else None
    return n


def restore(pcb=PCB, store=STORE, refill=True, quiet=False):
    """manual.json -> board, in a group named `manual`, then refill."""
    items = []
    if os.path.exists(store):
        items = json.load(open(store)).get("items") or []
    # manual.json is the source of truth, so an absent or empty one means the
    # board must not carry a `manual` group either - that is how a hand route
    # is taken OUT again. The fast path is the common one: nothing stored and
    # nothing on the board, so the board is not rewritten at all.
    if not items and not any(g.GetName() == MANUAL_GROUP
                             for g in pcbnew.LoadBoard(pcb).Groups()):
        if not quiet:
            print("manual copper: nothing in %s and nothing on the board"
                  % os.path.relpath(store, PROJ))
        return 0
    pro_before = None
    if os.path.exists(PRO):
        with open(PRO, "rb") as fh:
            pro_before = fh.read()
    board = pcbnew.LoadBoard(pcb)
    # Idempotent the same way every other stage is: drop the previous group's
    # members first, so a restore never stacks copper.
    gone = 0
    for g in list(board.Groups()):
        if g.GetName() != MANUAL_GROUP:
            continue
        members = list(g.GetItems())
        board.Remove(g)
        for it in members:
            board.Remove(it)
            gone += 1
        _KEEP.extend(members)          # see place.py: KiCad 10 segfaults if
        _KEEP.append(g)                # a detached SWIG proxy is collected
    made, bad = [], []
    for it in items:
        net = _net(board, it.get("net"))
        if it.get("net") and net is None:
            bad.append("%s on net %r - that net is not on the board any more"
                       % (it["kind"], it["net"]))
            continue
        if it["kind"] == "via":
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(at(it["pos"]))
            v.SetWidth(mm(it.get("size", 0.6)))
            v.SetDrill(mm(it.get("drill", 0.3)))
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            if net:
                v.SetNet(net)
            board.Add(v)
            made.append(v)
            continue
        lid = LAYERS.get(it.get("layer"))
        if lid is None:
            bad.append("%s on layer %r - only F.Cu and B.Cu are copper here"
                       % (it["kind"], it.get("layer")))
            continue
        if it["kind"] == "arc":
            t = pcbnew.PCB_ARC(board)
            t.SetStart(at(it["start"]))
            t.SetMid(at(it["mid"]))
            t.SetEnd(at(it["end"]))
        else:
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(at(it["start"]))
            t.SetEnd(at(it["end"]))
        t.SetWidth(mm(it.get("width", 0.25)))
        t.SetLayer(lid)
        if net:
            t.SetNet(net)
        board.Add(t)
        made.append(t)
    if made:
        g = pcbnew.PCB_GROUP(board)
        g.SetName(MANUAL_GROUP)
        board.Add(g)
        for it in made:
            g.AddItem(it)
    board.BuildConnectivity()
    if refill:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(pcb, board)
    if pro_before is not None:
        with open(PRO, "rb") as fh:
            if fh.read() != pro_before:
                with open(PRO, "wb") as w:
                    w.write(pro_before)
    if not quiet:
        if made:
            print("manual copper: %d item(s) re-added as group %r%s%s"
                  % (len(made), MANUAL_GROUP,
                     " (replacing %d from a previous restore)" % gone if gone
                     else "", ", zones refilled" if refill else ""))
        else:
            print("manual copper: nothing stored; removed the %d item(s) the "
                  "board's %r group still carried%s"
                  % (gone, MANUAL_GROUP,
                     ", zones refilled" if refill else ""))
        for line in bad:
            print("  SKIPPED %s" % line)
    return len(made)


_KEEP = []


def main():
    argv = sys.argv[1:]
    if "--restore" in argv:
        restore(refill="--no-refill" not in argv)
        return 0
    export()
    return 0


if __name__ == "__main__":
    sys.exit(main())
