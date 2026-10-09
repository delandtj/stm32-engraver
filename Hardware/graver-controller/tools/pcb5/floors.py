#!/usr/bin/env python3
"""Restore ADR 0003's power width floors (0.3 mm Power, 0.5 mm HighCurrent)
away from the 0.5 mm pitch parts, where ADR 0003 Decision 5 itself allows
0.2 mm.

    python3 tools/pcb5/floors.py [board.kicad_pcb]
    pcbkit krt-reroute --keep LCD_SCK ENC_SW LCD_BL LCD_RST "Net-(R210-Pad1)" PEDAL_TIP

KRT routes signals first and necks the power nets around them. This script
rips the handful of signal tracks that block the power necks (they are
re-routed afterwards with --keep, around the now wider copper), re-draws
two necks whose shape, not a neighbour, was the problem (the +3V3 stub to
R404.1 and the VDDA run from U301 pin 9 to C306.1), widens every other
power neck away from the fine-pitch parts to its class width, and adds the
'fine-pitch' rule areas the .kicad_dru floor exception refers to. Saves to
scratch, copies only the .kicad_pcb back.
"""
import math, os, shutil, sys
sys.path.insert(0, os.path.expanduser('~/Electronics/pcbkit'))
import pcbnew
from pcbkit import pcbtool as T

S = os.path.join(os.environ.get('SCRATCH', os.path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'graver-pcb5')), 'floors')
RIP = ['LCD_SCK', 'ENC_SW', 'LCD_BL', 'LCD_RST', 'Net-(R210-Pad1)']
CLASS = {'+3V3': 0.4, '/MCU/VDDA': 0.4, 'VBUS': 0.5, '+5V': 0.5, 'Net-(D105-A)': 0.5}
FINE = ('U301', 'J301', 'U302')          # 0.5 mm pitch: 0.2 mm tracks allowed (ADR 0003 D5)

def seq(c):
    return [c[i] for i in range(len(c))]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'graver-controller.kicad_pcb'
    b = pcbnew.LoadBoard(path)
    mm = T.mm
    P = lambda r, n: T.pad_xy(b, r, n)
    # fine-pitch areas: courtyard + 1.2 mm, as named rule areas with no keepout
    for z in seq(b.Zones()):
        if z.GetZoneName() == 'fine-pitch':
            b.Delete(z)
    for r in FINE:
        x0, y0, x1, y1 = T.cbox(b.FindFootprintByReference(r))
        z = pcbnew.ZONE(b); z.SetIsRuleArea(True); z.SetZoneName('fine-pitch')
        ls = pcbnew.LSET(); ls.AddLayer(pcbnew.F_Cu); ls.AddLayer(pcbnew.B_Cu); z.SetLayerSet(ls)
        o = z.Outline(); o.NewOutline()
        for x, y in ((x0 - 1.2, y0 - 1.2), (x1 + 1.2, y0 - 1.2), (x1 + 1.2, y1 + 1.2), (x0 - 1.2, y1 + 1.2)):
            o.Append(T.MM(x), T.MM(y))
        for fn in (z.SetDoNotAllowTracks, z.SetDoNotAllowVias, z.SetDoNotAllowZoneFills, z.SetDoNotAllowPads, z.SetDoNotAllowFootprints):
            fn(False)
        b.Add(z)
    fine = [z for z in seq(b.Zones()) if z.GetZoneName() == 'fine-pitch']
    def in_fine(t):
        a, c = t.GetStart(), t.GetEnd()
        return any(z.Outline().Contains(a) or z.Outline().Contains(c) for z in fine)
    # 1. rip the blocking signals (PEDAL_TIP only east of the MCU: its QFN end is a hand join)
    n = T.delete_net_copper(b, RIP)
    for t in seq(b.Tracks()):
        if t.GetNetname() == 'PEDAL_TIP' and mm(t.GetPosition().x) > 100:
            b.Delete(t); n += 1
    print('signal items ripped:', n)
    # 2. re-draw the two necks whose shape was the problem
    for t in seq(b.Tracks()):
        if t.Type() != pcbnew.PCB_TRACE_T:
            continue
        x, y = mm(t.GetStart().x), mm(t.GetStart().y); net = t.GetNetname()
        if (net == '+3V3' and 90.2 < x < 91.8 and 90.9 < y < 92.6) or (net == '/MCU/VDDA' and 94.7 < x < 96.8 and 75.5 < y < 77.6):
            b.Delete(t)
    r404 = P('R404', '1')
    T.add_track(b, '+3V3', 'F.Cu', [(90.3, 92.0), (91.3, 91.0), r404], 0.4)
    p9, c306 = P('U301', '9'), P('C306', '1')
    # 0.2 while inside the fine-pitch area (past the pin 8 GND stub and the
    # PEDAL_TIP via), 0.4 from there to C306.1
    T.add_track(b, '/MCU/VDDA', 'F.Cu', [p9, (p9[0], 76.5), (95.0, 76.85)], 0.2)
    T.add_track(b, '/MCU/VDDA', 'F.Cu', [(95.0, 76.85), (95.2, 77.05), (95.2, 77.1), (95.6, 77.5), c306], 0.4)
    # VBUS B.Cu diagonal past the NRST cluster via (88.7, 67.9): kink it 0.1 NW
    for t in seq(b.Tracks()):
        if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetname() == 'VBUS' and b.GetLayerName(t.GetLayer()) == 'B.Cu':
            a, c = (round(mm(t.GetStart().x), 2), round(mm(t.GetStart().y), 2)), (round(mm(t.GetEnd().x), 2), round(mm(t.GetEnd().y), 2))
            if {a, c} == {(89.5, 66.2), (87.2, 68.5)}:
                b.Delete(t)
                T.add_track(b, 'VBUS', 'B.Cu', [(89.5, 66.2), (89.4, 66.2), (87.1, 68.5), (87.2, 68.5)], 0.5)
                print('VBUS diagonal kinked past the NRST via')
    # 3. widen the remaining power necks away from the fine-pitch parts
    w = 0
    for t in seq(b.Tracks()):
        if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetname() in CLASS and mm(t.GetWidth()) + 1e-6 < 0.3 and not in_fine(t):
            t.SetWidth(T.MM(CLASS[t.GetNetname()])); w += 1
    print('power necks widened to class width:', w)
    os.makedirs(S, exist_ok=True)
    out = os.path.join(S, os.path.basename(path)); b.Save(out); shutil.copy(out, path)

if __name__ == '__main__':
    main()
