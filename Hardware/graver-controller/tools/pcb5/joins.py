#!/usr/bin/env python3
"""Post-route joins for the pairs KRT leaves open (ADR 0005 Decision 5: scripted
hand routes where the router fails), group "hand-joins".

    python3 tools/pcb5/joins.py [board.kicad_pcb]

- pin 7 (NRST) escape back on fan row A, pin 8 (VSSA) as a straight stub
  into C311.2, PEDAL_TIP back to its fan stub + via tied on B.Cu; VDDA then
  runs straight down from pin 9 and 45 degrees into C306.1.
- a GND via in the pour island beside J302.5.
- +5V: U102.1 (the LDO input, whose plane via sat in the pad) to the B.Cu
  +5V run with a via beside the pad.
- NRST: pin 7's fan via north under the QFN between the EP vias, west in the
  corridor above the EP, then to the NRST cluster via at (88.7, 67.9). This
  corridor is where KRT put LCD_MOSI: delete that net first and re-route it
  (krt-reroute LCD_MOSI), it has a free path south like LCD_SCK.
Re-runnable: drops its group and re-draws. Geometry from the board, with the
few hand-picked coordinates below.
"""
import os, shutil, sys
sys.path.insert(0, os.path.expanduser('~/Electronics/pcbkit'))
import pcbnew
from pcbkit import pcbtool as T

GROUP = 'hand-joins'
S = os.path.join(os.environ.get('SCRATCH', os.path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'graver-pcb5')), 'joins')

def seq(c):
    return [c[i] for i in range(len(c))]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'graver-controller.kicad_pcb'
    b = pcbnew.LoadBoard(path)
    T.drop_group(b, GROUP)
    before = {t.m_Uuid.AsString() for t in seq(b.Tracks())}
    P = lambda r, n: T.pad_xy(b, r, n)

    # xtal keepout: same shape as place.py now draws (no margin on the MCU side)
    for z in seq(b.Zones()):
        if z.GetZoneName() == 'xtal keepout':
            xb = [T.cbox(b.FindFootprintByReference(r)) for r in ('Y301', 'C310', 'C311')]
            x0, y0, x1, y1 = min(q[0] for q in xb) - 1, min(q[1] for q in xb), max(q[2] for q in xb), max(q[3] for q in xb) + 1
            o = z.Outline(); o.RemoveAllContours(); o.NewOutline()
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                o.Append(T.MM(x), T.MM(y))

    # +5V at U102.1: KRT's GND plane tap for C113.2 / U102.2 boxes the pad in
    # (tracks at y 93.2 and x 79.1, via at (80.9, 93.2)). Replace that tap by a
    # via west of it, drop the redundant B.Cu GND trunk that started at the old
    # via (every GND via lands on the In1 plane), and put the +5V via north of
    # pad 1 with a B.Cu tie into the +5V run at x 80.0.
    u1 = P('U102', '1')
    gone = 0
    for t in seq(b.Tracks()):
        if t.GetNetname() != 'GND':
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            x, y = T.mm(t.GetPosition().x), T.mm(t.GetPosition().y)
            if abs(x - 80.9) < 0.05 and abs(y - 93.2) < 0.05:
                b.Delete(t); gone += 1
        else:
            a, c = (T.mm(t.GetStart().x), T.mm(t.GetStart().y)), (T.mm(t.GetEnd().x), T.mm(t.GetEnd().y))
            pts = sorted([a, c])
            if pts in ([(79.1, 93.7), (79.6, 93.2)], [(79.6, 93.2), (80.9, 93.2)], [(80.9, 93.2), (85.1, 93.2)]):
                b.Delete(t); gone += 1
    print('GND tap items removed at U102:', gone)
    T.add_track(b, 'GND', 'F.Cu', [(79.1, 93.7), (79.1, 93.1)], 0.4)
    T.add_via(b, 'GND', 79.1, 93.1, 0.6, 0.3)
    T.add_via(b, '+5V', 80.4, 93.3, 0.6, 0.3)
    T.add_track(b, '+5V', 'F.Cu', [(80.4, 93.3), (80.4, u1[1])], 0.5)
    T.add_track(b, '+5V', 'B.Cu', [(80.4, 93.3), (80.0, 93.3)], 0.5)

    # NRST: pin 7's fan stub and via back on row A (krt-reroute had moved them),
    # then north under the QFN
    p7, p8 = P('U301', '7'), P('U301', '8')
    for t in seq(b.Tracks()):
        if t.GetNetname() in ('NRST', 'GND'):
            x, y = T.mm(t.GetPosition().x), T.mm(t.GetPosition().y)
            if 93.6 < x < 94.7 and 75.5 < y < 76.7 and (t.Type() == pcbnew.PCB_VIA_T or t.GetParentGroup() and t.GetParentGroup().GetName() == 'hand'):
                b.Delete(t)          # old pin 7 / pin 8 escapes (hand group) and their vias
    for t in seq(b.Tracks()):        # the fan stubs of pins 7 and 8 start at the pad centres
        if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetname() in ('NRST', 'GND'):
            a = (T.mm(t.GetStart().x), T.mm(t.GetStart().y)); c = (T.mm(t.GetEnd().x), T.mm(t.GetEnd().y))
            if (a in (p7, p8) or c in (p7, p8)) and max(a[1], c[1]) < 76.7:
                b.Delete(t)
    v7 = (p7[0], p7[1] + 0.9)
    T.add_track(b, 'NRST', 'F.Cu', [p7, v7], 0.2)
    T.add_via(b, 'NRST', v7[0], v7[1], 0.5, 0.2)
    # pin 8 (VSSA): straight 0.2 stub into C311.2 below it, 0.07 right of the pad
    # centre to keep 0.2 from the NRST via
    c311 = P('C311', '2')
    T.add_track(b, 'GND', 'F.Cu', [(p8[0] + 0.07, p8[1]), (p8[0] + 0.07, c311[1])], 0.2)
    yc = 69.4                                       # corridor between the QFN pads row and the EP vias
    T.add_track(b, 'NRST', 'B.Cu', [v7, (93.5, v7[1] - (v7[0] - 93.5)), (93.5, yc), (90.3, yc), (89.3, yc - 1.0),
                                    (88.9, yc - 1.0), (88.7, yc - 1.2), (88.7, 68.1)], 0.2)
    # PEDAL_TIP: krt-reroute (rip) replaced pin 11's fan stub by an F.Cu run down
    # the corridor VDDA needs. Back to the fan geometry (stub + via at row A)
    # with a B.Cu tie to the rest of the net at its via (96.5, 78.45).
    p11 = P('U301', '11')
    for t in seq(b.Tracks()):
        if t.GetNetname() == 'PEDAL_TIP' and t.Type() == pcbnew.PCB_TRACE_T and b.GetLayerName(t.GetLayer()) == 'F.Cu':
            a, c = (T.mm(t.GetStart().x), T.mm(t.GetStart().y)), (T.mm(t.GetEnd().x), T.mm(t.GetEnd().y))
            if min(a[1], c[1]) > 75.3 and max(a[0], c[0]) < 96.6 and max(a[1], c[1]) < 78.6:
                b.Delete(t)
    T.add_track(b, 'PEDAL_TIP', 'F.Cu', [p11, (p11[0], p11[1] + 0.9)], 0.2)
    T.add_via(b, 'PEDAL_TIP', p11[0], p11[1] + 0.9, 0.5, 0.2)
    T.add_track(b, 'PEDAL_TIP', 'B.Cu', [(p11[0], p11[1] + 0.9), (p11[0], 77.7), (96.5, 78.45)], 0.2)
    # VDDA: pin 9 -> jog right past the pin 8 GND via -> down -> 45 into C306.1's row
    p9, c306 = P('U301', '9'), P('C306', '1')
    T.add_track(b, '/MCU/VDDA', 'F.Cu', [p9, (p9[0], c306[1] - 0.7), (p9[0] + 0.7, c306[1]), c306], 0.2)
    # GND via in the pour island beside J302.5 (its spokes landed on an isolated island)
    T.add_via(b, 'GND', 85.3, 72.3, 0.6, 0.3)

    items = [t for t in seq(b.Tracks()) if t.m_Uuid.AsString() not in before]
    g = pcbnew.PCB_GROUP(b); g.SetName(GROUP); b.Add(g)
    for it in items:
        g.AddItem(it)
    os.makedirs(S, exist_ok=True)
    out = os.path.join(S, os.path.basename(path)); b.Save(out); shutil.copy(out, path)
    print('%d items in group %s -> %s' % (len(items), GROUP, path))

if __name__ == '__main__':
    main()
