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
    nv = 0
    for v in [t for t in seq(b.Tracks()) if t.Type() == pcbnew.PCB_VIA_T]:
        p = v.GetPosition(); n = v.GetNetCode()
        touch = any(s.GetNetCode() == n and s.GetLayer() in outer and s.HitTest(p) for s in segs) or \
                any(q.GetNetCode() == n and q.HitTest(p) for q in pads)
        if not touch and v.GetNetname() not in ('GND', '+3V3'):
            b.Delete(v); nv += 1
    print('orphan vias deleted:', nv)
    os.makedirs(S, exist_ok=True)
    out = os.path.join(S, os.path.basename(path))
    b.Save(out); shutil.copy(out, path)

if __name__ == '__main__':
    main()
