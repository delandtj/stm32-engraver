#!/usr/bin/env python3
"""After krt-route: keep In1/In2 as solid planes (ADR 0005 Decision 1).

    python3 tools/pcb5/postroute.py [board.kicad_pcb]

Deletes every track segment on In1.Cu / In2.Cu that KRT laid (the planes
carry those nets), deletes vias that connect nothing on the outer layers
afterwards, and prints what went. Saves to scratch, copies only the
.kicad_pcb back (pcbnew Save rewrites the neighbouring .kicad_pro).
"""
import os, shutil, sys
import pcbnew

S = os.path.join(os.environ.get('SCRATCH', os.path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'graver-pcb5')), 'post')

def seq(c):
    return [c[i] for i in range(len(c))]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'graver-controller.kicad_pcb'
    b = pcbnew.LoadBoard(path)
    inner = {b.GetLayerID('In1.Cu'), b.GetLayerID('In2.Cu')}
    gone = {}
    for t in seq(b.Tracks()):
        if t.Type() == pcbnew.PCB_TRACE_T and t.GetLayer() in inner:
            gone[t.GetNetname()] = gone.get(t.GetNetname(), 0) + 1
            b.Delete(t)
    print('inner tracks deleted:', gone or 0)
    # vias whose only purpose was an inner track: nothing of the net touches them on F/B.Cu
    outer = {b.GetLayerID('F.Cu'), b.GetLayerID('B.Cu')}
    segs = [t for t in seq(b.Tracks()) if t.Type() == pcbnew.PCB_TRACE_T]
    pads = seq(b.GetPads())
    # (orphan-via deletion removed: it ate vias that KRT's tracks reach within
    # clearance but not at their centre; `pcbkit prune` on a 0-unconnected
    # board is the right tool for dangling vias)
    nv = 0
    # vias the router dropped into SMD pads (viaout could not move): delete, the
    # net is then re-routed with krt-reroute --keep
    bad = []
    for v in [t for t in seq(b.Tracks()) if t.Type() == pcbnew.PCB_VIA_T]:
        pos = v.GetPosition(); hit = None
        for f in seq(b.Footprints()):
            for q in seq(f.Pads()):
                if q.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and q.HitTest(pos) and not (f.GetReference() == 'U301' and q.GetNumber() == '49'):
                    hit = (f.GetReference(), q.GetNumber(), v.GetNetname())
        if hit:
            bad.append(hit); b.Delete(v)
    print('vias in SMD pads deleted:', bad or 0)
    os.makedirs(S, exist_ok=True)
    out = os.path.join(S, os.path.basename(path))
    b.Save(out); shutil.copy(out, path)

if __name__ == '__main__':
    main()
