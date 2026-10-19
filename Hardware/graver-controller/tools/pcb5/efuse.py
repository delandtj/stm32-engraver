#!/usr/bin/env python3
"""ADR 0007 input eFuse block (rev 2): U103 TPS26602 and its passives, the
power path and the RTN island, all in group "efuse".

    python3 tools/pcb5/efuse.py [board.kicad_pcb]

Re-runnable: deletes group "efuse" and all copper of the block's own nets
(J101 +24V, RTN, ILIM, dVdT, SHDN), places U103/C117/R111/C116/R112 at the
fixed spots below and redraws:
- IN  0.8 mm: J101.2 down the old fuse column to C117.1 and U103 pins 1/2;
- OUT 0.8 mm: U103 pins 15/16 east to x 80.3, then north-east into the
  existing VIN via at (83.6, 59.3) (driver side) and south into the existing
  VIN chain at (79.6, 65.7) -> D102 / C101;
- RTN: pins 3/5/6/8 strapped into the PowerPAD on F.Cu; F.Cu island under
  the IC, B.Cu island under the IC and R112/C116, joined by the footprint's
  15 PowerPAD vias plus one via at R112/C116. Both islands are zones with
  priority 2, so the outer GND pours (priority 1) keep clear of them; a rule
  area keeps the In1 GND and In2 +3V3 planes out from under the block.
  RTN must never touch GND (ADR 0007).
krt-route keeps the group ([krt] keep_groups). The two VIN tie points (the
via at 83.6/59.3 and the chain end at 79.6/65.7) belong to the routing that
was on the board when U103 went in (2026-10-19); after a full krt-route
check them and let krt-reroute --keep VIN close what they no longer meet.
Run after place.py. Saves to scratch, copies only the .kicad_pcb back.
"""
import os, shutil, sys
sys.path.insert(0, os.path.expanduser('~/Electronics/pcbkit'))
import pcbnew
from pcbkit.pcbtool import MM, P, mm, seq, tracks, drop_group

GROUP = 'efuse'
S = os.path.join(os.environ.get('SCRATCH', os.path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'graver-pcb5')), 'efuse')

IN, RTN, ILIM, DVDT, SHDN = ('Net-(J101-Pin_2)', '/Power/RTN', 'Net-(U103-ILIM)',
                             'Net-(U103-dVdT)', 'Net-(U103-~{SHDN})')
PLACE = {            # ref: (x, y, rot)  -- pad 1 of the 2-pin parts is on top / left
    'U103': (72.5, 61.0, 0),     # pins 1-8 left (IN top), 9-16 right (OUT top, GND bottom)
    'C117': (67.6, 59.95, 270),  # IN bypass: pad 1 on the IN track, pad 2 -> GND via
    'R111': (65.8, 60.6, 270),   # SHDN pull-up under the IN column
    'C116': (77.6, 61.2, 0),     # dVdT
    'R112': (77.6, 62.85, 0),    # ILIM
}
GND_VIAS = [(67.8, 61.95), (75.275, 64.6)]     # C117.2, U103.9
RTN_VIA = (79.3, 62.0)
F_ISLAND = (70.35, 58.35, 74.65, 63.65)
B_ISLAND = (69.6, 58.2, 79.75, 63.8)
INNER_KEEPOUT = (69.3, 57.9, 80.0, 64.1)
VIN_X = 80.3


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'graver-controller.kicad_pcb'
    b = pcbnew.LoadBoard(path)
    drop_group(b, GROUP)
    for t in tracks(b):
        if t.GetNetname() in (IN, RTN, ILIM, DVDT, SHDN):
            b.Delete(t)
    g = pcbnew.PCB_GROUP(b); g.SetName(GROUP); b.Add(g)

    def own(it):
        b.Add(it); g.AddItem(it)

    for r, (x, y, rot) in PLACE.items():
        f = b.FindFootprintByReference(r)
        f.SetOrientationDegrees(rot)
        f.SetPosition(pcbnew.VECTOR2I_MM(x, y))

    def pad(r, n):
        p = b.FindFootprintByReference(r).FindPadByNumber(str(n)).GetPosition()
        return (round(mm(p.x), 4), round(mm(p.y), 4))

    def tr(net, pts, w, layer=pcbnew.F_Cu):
        n = b.FindNet(net); assert n, net
        for a, c in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(b); t.SetStart(P(*a)); t.SetEnd(P(*c))
            t.SetWidth(MM(w)); t.SetLayer(layer); t.SetNet(n); own(t)

    def via(net, x, y, d=0.6, h=0.3):
        v = pcbnew.PCB_VIA(b); v.SetPosition(P(x, y)); v.SetWidth(MM(d)); v.SetDrill(MM(h))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(b.FindNet(net)); own(v)

    # sanity: pad sides as the coordinates below assume
    p1, p2, p15, p16, p9 = pad('U103', 1), pad('U103', 2), pad('U103', 15), pad('U103', 16), pad('U103', 9)
    assert p1[0] < 72.5 < p16[0] and p1[1] < p2[1] and p16[1] < p15[1] and p9[1] > 63, (p1, p16, p9)
    c117, r111 = pad('C117', 1), pad('R111', 1)
    assert c117[1] < pad('C117', 2)[1] and r111[1] < pad('R111', 2)[1]
    assert pad('C116', 1)[0] < pad('C116', 2)[0] and pad('R112', 1)[0] < pad('R112', 2)[0]

    # IN: 0.8 along y 58.9 (inside pin 1, clear of pin 3), 0.5 stubs into pin 2 and R111.1
    j = pad('J101', 2)
    yi = p1[1] + 0.175
    tr(IN, [j, (j[0], yi), (c117[0], yi), (p1[0], yi)], 0.8)
    tr(IN, [(p1[0], yi), (p2[0], p2[1] - 0.175)], 0.5)
    tr(IN, [(j[0], yi), r111], 0.5)

    # OUT -> VIN, same pattern on the right
    yo = p16[1] + 0.175
    tr('VIN', [(p16[0], yo), (VIN_X, yo), (83.2, yo), (83.6, 59.3)], 0.8)
    tr('VIN', [(p16[0], yo), (p15[0], p15[1] - 0.175)], 0.5)
    tr('VIN', [(VIN_X, yo), (VIN_X, 65.0), (79.6, 65.7)], 0.8)
    tr('VIN', [(77.8, 67.5), (77.6, 67.7)], 0.8)     # bridge where D101's VIN pad was

    # RTN straps on F.Cu into the PowerPAD
    for n in (3, 5, 6, 8):
        x, y = pad('U103', n)
        tr(RTN, [(x, y), (x + 1.5, y)], 0.25)
    # SHDN from R111.2 to pin 7
    r2, p7 = pad('R111', 2), pad('U103', 7)
    tr(SHDN, [r2, (r2[0], p7[1] - 0.525), (r2[0] + 0.525, p7[1]), p7], 0.25)
    # dVdT and ILIM on the right
    tr(DVDT, [pad('U103', 12), pad('C116', 1)], 0.25)
    p11, r1 = pad('U103', 11), pad('R112', 1)
    tr(ILIM, [p11, (p11[0] + 0.825, p11[1]), (r1[0], p11[1] + (r1[0] - p11[0] - 0.825)), r1], 0.25)
    c2, rr2 = pad('C116', 2), pad('R112', 2)
    tr(RTN, [c2, rr2], 0.25)
    tr(RTN, [(c2[0], RTN_VIA[1]), RTN_VIA], 0.25)
    via(RTN, *RTN_VIA)
    # GND: C117.2 and U103.9 straight to the In1 plane
    tr('GND', [pad('C117', 2), GND_VIAS[0]], 0.4)
    tr('GND', [p9, GND_VIAS[1]], 0.4)
    for x, y in GND_VIAS:
        via('GND', x, y)

    # zones
    def rect(x0, y0, x1, y1):
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def island(layer, box, name):
        z = pcbnew.ZONE(b); z.SetLayer(layer); z.SetNet(b.FindNet(RTN)); z.SetZoneName(name)
        o = z.Outline(); o.NewOutline()
        for x, y in rect(*box):
            o.Append(MM(x), MM(y))
        z.SetLocalClearance(MM(0.2)); z.SetMinThickness(MM(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL); z.SetAssignedPriority(2)
        own(z)

    island(pcbnew.F_Cu, F_ISLAND, 'RTN island F')
    island(pcbnew.B_Cu, B_ISLAND, 'RTN island B')
    k = pcbnew.ZONE(b); k.SetIsRuleArea(True); k.SetZoneName('RTN inner keepout')
    s = pcbnew.LSET(); s.AddLayer(pcbnew.In1_Cu); s.AddLayer(pcbnew.In2_Cu); k.SetLayerSet(s)
    o = k.Outline(); o.NewOutline()
    for x, y in rect(*INNER_KEEPOUT):
        o.Append(MM(x), MM(y))
    k.SetDoNotAllowZoneFills(True); k.SetDoNotAllowTracks(False); k.SetDoNotAllowVias(False)
    k.SetDoNotAllowPads(False); k.SetDoNotAllowFootprints(False)
    own(k)

    os.makedirs(S, exist_ok=True)
    out = os.path.join(S, os.path.basename(path)); b.Save(out); shutil.copy(out, path)
    print('%d items in group %s -> %s' % (len(list(g.GetItems())), GROUP, path))


if __name__ == '__main__':
    main()
