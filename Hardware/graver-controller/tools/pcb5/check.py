#!/usr/bin/env python3
"""ADR 0005 acceptance checks on graver-controller.kicad_pcb (component spec).

    python3 tools/pcb5/check.py [board.kicad_pcb] [--rpt drc.rpt]

Prints a PASS/FAIL table and exits 1 on any FAIL. Checks: board size, via and
width sets, per-net width floors, inner layers track-free, In1 GND one region
under the USB pair / crystal / analog front end, USB pair skew / vias, the
ADR 0003 placement distances, and the DRC report summary when given.
Run after a zone refill (kicad-cli pcb drc --refill-zones --save-board, or
pcbkit gndpour) so the In1 polygon exists.
"""
import math, re, sys
import pcbnew

MM = pcbnew.ToMM
VIA_SET = {(0.5, 0.2), (0.6, 0.3)}
WIDTH_SET = {0.2, 0.25, 0.4, 0.5, 0.8, 1.0}
# net -> (class width, hard floor incl. necking). ADR 0003 D5 / ADR 0005 D3.
FLOORS = {
    'VIN': (0.8, 0.4), '/Driver/COIL_NEG': (0.8, 0.4), '/Driver/CLAMP': (0.8, 0.4),
    '/Driver/SHUNT_HI': (0.8, 0.4), 'Net-(U101-SW)': (0.8, 0.4),
    'Net-(J101-Pin_2)': (0.8, 0.4), 'Net-(Q101-D)': (0.8, 0.4),
    '+5V': (0.5, 0.25), 'VBUS': (0.5, 0.25), 'Net-(D105-A)': (0.5, 0.25),
    '+3V3': (0.4, 0.2), '/MCU/VDDA': (0.4, 0.2), 'GND': (0.4, 0.2),
}
USB = ('/MCU/USB_DP', '/MCU/USB_DM')
CEILING = (85.0, 60.0)
SKEW_MAX = 0.15

rows = []
def row(name, ok, val):
    rows.append((name, 'PASS' if ok else 'FAIL', val))

def seq(c):
    return [c[i] for i in range(len(c))]

def fp(b, ref):
    f = b.FindFootprintByReference(ref)
    assert f, ref
    return f

def center(b, ref):
    p = fp(b, ref).GetPosition(); return (MM(p.x), MM(p.y))

def pad(b, ref, num):
    for p in seq(fp(b, ref).Pads()):
        if p.GetNumber() == str(num):
            return p
    raise KeyError((ref, num))

def pad_xy(b, ref, num):
    q = pad(b, ref, num).GetPosition(); return (MM(q.x), MM(q.y))

def dist(a, c):
    return math.hypot(a[0] - c[0], a[1] - c[1])

def pdist(b, r1, n1, r2, n2):
    # pad edge to pad edge (bounding boxes), as the ADR distances are read
    A, C = pad(b, r1, n1).GetBoundingBox(), pad(b, r2, n2).GetBoundingBox()
    dx = max(0, MM(C.GetLeft()) - MM(A.GetRight()), MM(A.GetLeft()) - MM(C.GetRight()))
    dy = max(0, MM(C.GetTop()) - MM(A.GetBottom()), MM(A.GetTop()) - MM(C.GetBottom()))
    return math.hypot(dx, dy)

def main():
    args = [a for a in sys.argv[1:]]
    rpt = None
    if '--rpt' in args:
        i = args.index('--rpt'); rpt = args[i + 1]; del args[i:i + 2]
    path = args[0] if args else 'graver-controller.kicad_pcb'
    b = pcbnew.LoadBoard(path)
    nets = b.GetNetsByName()

    # board size
    bb = b.GetBoardEdgesBoundingBox()
    W, H = MM(bb.GetWidth()) - 0.1, MM(bb.GetHeight()) - 0.1   # minus the 0.1 edge line
    row('outline <= %.0f x %.0f' % CEILING, W <= CEILING[0] + 0.01 and H <= CEILING[1] + 0.01,
        '%.1f x %.1f mm' % (W, H))

    tracks = seq(b.Tracks())
    vias = [t.Cast() for t in tracks if t.Type() == pcbnew.PCB_VIA_T]
    segs = [t for t in tracks if t.Type() == pcbnew.PCB_TRACE_T]
    arcs = [t for t in tracks if t.Type() == pcbnew.PCB_ARC_T]
    row('no arcs', not arcs, '%d arcs' % len(arcs))

    vs = {(round(MM(v.GetWidth(pcbnew.F_Cu)), 2), round(MM(v.GetDrillValue()), 2)) for v in vias}
    row('via sizes in {0.5/0.2, 0.6/0.3}', vs <= VIA_SET, '%d vias, sizes %s' % (len(vias), sorted(vs)))
    ws = {round(MM(s.GetWidth()), 3) for s in segs}
    row('track widths in ADR set', ws <= WIDTH_SET, '%d segments, widths %s' % (len(segs), sorted(ws)))

    # per-net width floors
    bad = []
    bias = [z for z in seq(b.Zones()) if z.GetZoneName() == 'clamp-bias']
    def in_bias(s):
        a, c = s.GetStart(), s.GetEnd()
        return bool(bias) and bias[0].Outline().Contains(pcbnew.VECTOR2I((a.x + c.x) // 2, (a.y + c.y) // 2))
    for net, (cls, floor) in FLOORS.items():
        ss = [s for s in segs if s.GetNetname() == net and not (net == '/Driver/CLAMP' and in_bias(s))]
        if not ss:
            continue
        mn = min(MM(s.GetWidth()) for s in ss)
        below = sum(1 for s in ss if MM(s.GetWidth()) + 1e-6 < cls)
        tag = '%s min %.2f (class %.1f, %d/%d below class)' % (net, mn, cls, below, len(ss))
        row('floor ' + net, mn + 1e-6 >= floor, tag)

    # inner layers
    inner = [s for s in segs if b.GetLayerName(s.GetLayer()) in ('In1.Cu', 'In2.Cu')]
    row('In1/In2 track-free', not inner, '%d inner tracks' % len(inner))
    for layer, net in (('In1.Cu', 'GND'), ('In2.Cu', '+3V3')):
        lid = b.GetLayerID(layer)
        zs = [z for z in seq(b.Zones()) if not z.GetIsRuleArea() and z.IsOnLayer(lid) and z.GetNetname() == net]
        row('%s plane zone %s' % (layer, net), len(zs) == 1, '%d zones' % len(zs))

    # In1 one region under USB, crystal, analog front end
    lid = b.GetLayerID('In1.Cu')
    zs = [z for z in seq(b.Zones()) if not z.GetIsRuleArea() and z.IsOnLayer(lid) and z.GetNetname() == 'GND']
    if zs:
        poly = zs[0].GetFilledPolysList(lid)
        row('In1 GND filled, one region', poly.OutlineCount() == 1, '%d outlines' % poly.OutlineCount())
        pts = []
        for s in segs:
            if s.GetNetname() in USB and b.GetLayerName(s.GetLayer()) == 'F.Cu':
                a, c = s.GetStart(), s.GetEnd()
                pts.append(('usb', pcbnew.VECTOR2I((a.x + c.x) // 2, (a.y + c.y) // 2)))
        for ref in ('Y301', 'C310', 'C311', 'U202', 'R204', 'R209', 'R213', 'R210', 'R211', 'C205'):
            pts.append((ref, fp(b, ref).GetPosition()))
        miss = [n for n, p in pts if not poly.Contains(p)]
        row('In1 GND under USB/xtal/analog', not miss, '%d points, missing %s' % (len(pts), sorted(set(miss))))

    # USB pair
    L = {}
    for net in USB:
        L[net] = sum(MM(s.GetLength()) for s in segs if s.GetNetname() == net)
    skew = abs(L[USB[0]] - L[USB[1]])
    row('USB skew <= %.2f mm' % SKEW_MAX, skew <= SKEW_MAX, 'DP %.2f mm, DM %.2f mm, skew %.3f mm' % (L[USB[0]], L[USB[1]], skew))
    uv = [v for v in vias if v.GetNetname() in USB]
    row('USB vias = 0', not uv, '%d vias' % len(uv))
    ul = {b.GetLayerName(s.GetLayer()) for s in segs if s.GetNetname() in USB}
    row('USB on F.Cu only', ul <= {'F.Cu'}, str(sorted(ul)))
    uw = {round(MM(s.GetWidth()), 3) for s in segs if s.GetNetname() in USB}
    row('USB width 0.25', uw == {0.25}, str(sorted(uw)))
    # B.Cu tracks of other nets crossing under the pair (allowed, reported)
    usb_segs = [s for s in segs if s.GetNetname() in USB]
    cross = set()
    for s in segs:
        if s.GetNetname() in USB or b.GetLayerName(s.GetLayer()) == 'In1.Cu':
            continue
        if b.GetLayerName(s.GetLayer()) == 'In2.Cu':
            continue
        for u in usb_segs:
            if seg_cross(s, u):
                cross.add((s.GetNetname(), b.GetLayerName(s.GetLayer())))
    row('USB crossings on F.Cu/In1 = 0', not any(l != 'B.Cu' for _, l in cross),
        'B.Cu crossings (allowed): %s' % sorted(cross))

    # placement distances (ADR 0003 component breakdown)
    d = max(pdist(b, 'Y301', '1', 'U301', '5'), pdist(b, 'Y301', '3', 'U301', '6'))
    row('crystal <= 5 mm from OSC pins', d <= 5, '%.2f mm' % d)
    worst = 0
    for pin in ('1', '24', '36', '48'):
        dd = min(min(pdist(b, 'U301', pin, c, n) for n in ('1', '2')) for c in ('C301', 'C302', 'C303', 'C304'))
        worst = max(worst, dd)
    row('100n within 2 mm of each VDD pin', worst <= 2, 'worst %.2f mm' % worst)
    analog = ('U202', 'R204', 'R210', 'R211', 'R212', 'C205')
    dmin = min(dist(center(b, u), center(b, a)) for u in ('U101', 'L101') for a in analog + ('Y301',))
    row('buck >= 15 mm from analog + crystal', dmin >= 15, '%.1f mm' % dmin)
    d = pdist(b, 'U201', '5', 'Q201', '1')
    row('gate driver <= 5 mm from FET gate', d <= 5, '%.2f mm' % d)
    d = min(pdist(b, 'U202', n, 'R204', m) for n in ('2', '3') for m in ('1', '2'))
    row('op-amp <= 10 mm from shunt', d <= 10, '%.2f mm' % d)

    # vias in SMD pads other than the QFN EP
    inpad = []
    for v in vias:
        for f in seq(b.Footprints()):
            for p in seq(f.Pads()):
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.HitTest(v.GetPosition()):
                    if not (f.GetReference() == 'U301' and p.GetNumber() == '49'):
                        inpad.append((f.GetReference(), p.GetNumber()))
    row('no vias in SMD pads except U301 EP', not inpad, str(sorted(set(inpad))[:8]))

    if rpt:
        txt = open(rpt).read()
        kinds = re.findall(r'^\[([a-z_]+)\]', txt, re.M)
        from collections import Counter
        c = Counter(kinds)
        unc = re.search(r'Found (\d+) unconnected', txt)
        par = re.search(r'Found (\d+) (?:schematic parity|Footprint)', txt)
        errs = len(re.findall(r'; error$', txt, re.M))
        row('DRC 0 errors', errs == 0, '%d errors' % errs)
        row('DRC 0 unconnected', unc and unc.group(1) == '0', unc.group(0) if unc else '?')
        row('DRC 0 parity', par and par.group(1) == '0', par.group(0) if par else '?')
        rows.append(('DRC warnings', 'INFO', dict(c)))

    w = max(len(r[0]) for r in rows)
    fails = 0
    for name, st, val in rows:
        fails += st == 'FAIL'
        print('%-*s  %s  %s' % (w, name, st, val))
    print('%d FAIL' % fails)
    sys.exit(1 if fails else 0)

def seg_cross(s, u):
    def o(p, q, r):
        return (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)
    p1, p2, p3, p4 = s.GetStart(), s.GetEnd(), u.GetStart(), u.GetEnd()
    d1, d2, d3, d4 = o(p3, p4, p1), o(p3, p4, p2), o(p1, p2, p3), o(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4

if __name__ == '__main__':
    main()
