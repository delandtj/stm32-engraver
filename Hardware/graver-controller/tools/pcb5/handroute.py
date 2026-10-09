#!/usr/bin/env python3
"""Scripted hand routes (ADR 0005 Decision 5, the granite pattern), group "hand".

    python3 tools/pcb5/handroute.py [board.kicad_pcb]

Draws, on F.Cu, straight 45-degree segments only:
- the USB 2.0 pair J301 -> U302 (USBLC6 in line) -> U301 pins 32/33 at
  0.25 mm, 0.15 mm gap, no vias, with a small jog on the shorter leg so the
  skew is <= 0.15 mm (ADR 0005 Decision 4); the A6/B6 and A7/B7 pads are
  joined by stubs just past the pad ends;
- the crystal: OSC_IN / OSC_OUT from U301 pins 5/6 through the load caps
  C310/C311 to Y301.
Existing copper of these nets is deleted first; krt-route keeps the group
([krt] keep_groups). Saves to scratch, copies only the .kicad_pcb back.
"""
import os, shutil, sys
sys.path.insert(0, os.path.expanduser('~/Electronics/pcbkit'))
import pcbnew
from pcbkit import pcbtool as T

GROUP = 'hand'
S = os.path.join(os.environ.get('SCRATCH', os.path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'graver-pcb5')), 'hand')

def seq(c):
    return [c[i] for i in range(len(c))]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'graver-controller.kicad_pcb'
    b = pcbnew.LoadBoard(path)
    T.drop_group(b, GROUP)
    nets = {'DP': '/MCU/USB_DP', 'DM': '/MCU/USB_DM', 'XI': '/MCU/OSC_IN', 'XO': '/MCU/OSC_OUT'}
    T.delete_net_copper(b, list(nets.values()))
    P = lambda r, n: T.pad_xy(b, r, n)
    items = []
    def tr(net, pts, w):
        T.add_track(b, nets[net], 'F.Cu', pts, w)

    # --- USB pair, 0.25 wide. J301 pads at y 58.045 (0.3 x 1.45), pitch 0.5:
    # B6 DP 92.25, A7 DM 92.75, A6 DP 93.25, B7 DM 93.75. The DP pads are
    # joined by a stub above the pad row (under the connector body), the DM
    # pads below it, so neither stub crosses the other leg's exit.
    yj = P('J301', 'A6')[1]
    b6, a6, a7, b7 = P('J301', 'B6')[0], P('J301', 'A6')[0], P('J301', 'A7')[0], P('J301', 'B7')[0]
    u3, u1, u4, u6 = P('U302', '3'), P('U302', '1'), P('U302', '4'), P('U302', '6')
    m33, m32 = P('U301', '33'), P('U301', '32')
    def length(pts):
        return sum(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 for (x0, y0), (x1, y1) in zip(pts, pts[1:]))
    def dp_paths(md):
        # md: depth of an orthogonal detour (to the left) on the J301 -> U302
        # leg; it adds exactly 2 * md and trims the skew
        a = [(b6, yj), (b6, yj - 1.1), (a6, yj - 1.1), (a6, yj)]             # stub above
        y0 = yj + 1.55
        c = [(b6, yj), (b6, y0)]
        if md > 0.02:
            c += [(b6 - md, y0), (b6 - md, y0 + 1.0), (b6, y0 + 1.0)]
        c += [(b6, u3[1] - 1.4), (u3[0], u3[1] - 1.4 + (u3[0] - b6)), (u3[0], u3[1])]
        d = [u3, u4]
        e = [u4, (u4[0], m33[1] - 1.75), (m33[0], m33[1] - 1.75 + (u4[0] - m33[0])), m33]
        return [a, c, d, e]
    dmx = u6[0] - m32[0]
    dm = [[(a7, yj), (a7, yj + 1.15), (b7, yj + 1.15), (b7, yj)],               # stub below
          [(b7, yj), (b7, yj + 1.0), (u1[0], yj + 1.0 + (u1[0] - b7)), (u1[0], u1[1])],
          [u1, u6],
          [u6, (u6[0], u6[1] + 0.75), (m32[0] + 0.4, u6[1] + 0.75 + dmx - 0.4), (m32[0], u6[1] + 0.75 + dmx), m32]]
    ldm = sum(length(q) for q in dm)
    ldp0 = sum(length(q) for q in dp_paths(0))
    md = max(0.0, (ldm - ldp0) / 2)
    for q in dp_paths(md):
        tr('DP', q, 0.25)
    for q in dm:
        tr('DM', q, 0.25)
    print('DP meander depth %.3f mm' % md)

    # --- crystal, 0.2 wide. Pins 5/6 at the bottom of the QFN, caps below, crystal below them.
    p5, p6 = P('U301', '5'), P('U301', '6')
    c310, c311 = P('C310', '1'), P('C311', '1')
    y1, y3 = P('Y301', '1'), P('Y301', '3')
    # OSC_IN: pin 5 down, 45 left above C310's GND pad, into C310.1, then left-down around Y301.4 to Y301.1
    tr('XI', [p5, (p5[0], p5[1] + 0.55), (p5[0] - 0.65, p5[1] + 1.2), (c310[0] + 0.4, p5[1] + 1.2),
              (c310[0], p5[1] + 1.6), c310], 0.2)
    tr('XI', [c310, (c310[0] - 0.45, c310[1] + 0.45), (c310[0] - 0.45, y1[1] - 0.45), (c310[0], y1[1]), y1], 0.2)
    # OSC_OUT: pin 6 down, 45 right into C311.1, then down and right into Y301.3
    tr('XO', [p6, (p6[0], p6[1] + 0.7), (c311[0], p6[1] + 0.7 + (c311[0] - p6[0])), c311], 0.2)
    tr('XO', [c311, (c311[0], y3[1]), y3], 0.2)

    items = [t for t in seq(b.Tracks()) if t.GetNetname() in nets.values()]   # all copper of these nets is ours
    g = pcbnew.PCB_GROUP(b); g.SetName(GROUP); b.Add(g)
    for it in items:
        g.AddItem(it)
    L = {}
    for k in ('DP', 'DM'):
        L[k] = sum(T.mm(s.GetLength()) for s in seq(b.Tracks()) if s.Type() == pcbnew.PCB_TRACE_T and s.GetNetname() == nets[k])
    print('USB DP %.2f mm, DM %.2f mm, skew %.3f mm' % (L['DP'], L['DM'], abs(L['DP'] - L['DM'])))
    os.makedirs(S, exist_ok=True)
    out = os.path.join(S, os.path.basename(path)); b.Save(out); shutil.copy(out, path)
    print('%d segments in group %s -> %s' % (len(items), GROUP, path))

if __name__ == '__main__':
    main()
