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
# net -> (class width, ADR 0003 D5 floor as in .kicad_dru). ADR 0005 D3 keeps them.
FLOORS = {
    'VIN': (0.8, 0.5), '/Driver/COIL_NEG': (0.8, 0.5), '/Driver/CLAMP': (0.8, 0.5),
    '/Driver/SHUNT_HI': (0.8, 0.5), 'Net-(U101-SW)': (0.8, 0.5),
    'Net-(J101-Pin_2)': (0.8, 0.5),
    '+5V': (0.5, 0.3), 'VBUS': (0.5, 0.3), 'Net-(D105-A)': (0.5, 0.3),
    '+3V3': (0.4, 0.3), '/MCU/VDDA': (0.4, 0.3), 'GND': (0.4, 0.2),
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
    # exemptions the .kicad_dru states: the CLAMP gate-bias branch, and 0.2 mm at
    # the 0.5 mm pitch parts (ADR 0003 D5) for the Power classes
    bias = [z for z in seq(b.Zones()) if z.GetZoneName() == 'clamp-bias']
    fine = [z for z in seq(b.Zones()) if z.GetZoneName() == 'fine-pitch']
    def inside(zs, s):
        a, c = s.GetStart(), s.GetEnd()
        return any(z.Outline().Contains(a) or z.Outline().Contains(c) for z in zs)
    POWER = ('+5V', 'VBUS', 'Net-(D105-A)', '+3V3', '/MCU/VDDA')
    for net, (cls, floor) in FLOORS.items():
        ss = [s for s in segs if s.GetNetname() == net and not (net == '/Driver/CLAMP' and inside(bias, s))
              and not (net in POWER and inside(fine, s))]
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
    # corridor: no foreign copper on F.Cu within 0.5 mm of the pair (CC1/CC2/VBUS
    # stay outside it), no copper at all on In1 (plane only), and the B.Cu
    # crossings listed with the length that lies under the pair
    # Inside the 'fine-pitch' areas (USB-C, USBLC6, QFN) the pad neighbours sit
    # at 0.5 mm pitch by construction, so there only DRC clearance applies; the
    # 0.5 mm corridor is demanded on open board.
    fine = [z for z in seq(b.Zones()) if z.GetZoneName() == 'fine-pitch']
    def in_fine_pt(p):
        return any(z.Outline().Contains(p) for z in fine)
    near, under, closest = set(), {}, []
    fcu, bcu = b.GetLayerID('F.Cu'), b.GetLayerID('B.Cu')
    for u in usb_segs:
        for s in segs:
            if s.GetNetname() in USB:
                continue
            if s.GetLayer() == fcu:
                gap = seg_seg_dist(s, u) - 0.125 - MM(s.GetWidth()) / 2
                if gap < 0.5:
                    closest.append((round(gap, 2), s.GetNetname()))
                    if not (in_fine_pt(s.GetStart()) or in_fine_pt(s.GetEnd())):
                        near.add(s.GetNetname())
            if s.GetLayer() == bcu and seg_cross(s, u):
                under[s.GetNetname()] = round(under.get(s.GetNetname(), 0) + min(MM(s.GetLength()), 1.0), 2)
    for v in vias:
        if v.GetNetname() in USB:
            continue
        for u in usb_segs:
            gap = pt_seg_dist(v.GetPosition(), u) - 0.125 - MM(v.GetWidth(pcbnew.F_Cu)) / 2
            if gap < 0.5:
                closest.append((round(gap, 2), 'via ' + v.GetNetname()))
                if not in_fine_pt(v.GetPosition()):
                    near.add('via ' + v.GetNetname())
    row('USB corridor: foreign F.Cu copper within 0.5 mm on open board = 0', not near, str(sorted(near)))
    rows.append(('USB nearest foreign F.Cu items at the fine-pitch parts (gap mm)', 'INFO', sorted(set(closest))[:6]))
    in1 = [s for s in segs if b.GetLayerName(s.GetLayer()) == 'In1.Cu']
    row('USB corridor: In1 copper = plane only', not in1, '%d In1 segments' % len(in1))
    rows.append(('USB B.Cu crossers (net: mm under the pair)', 'INFO', under))

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

def pt_seg_dist(p, u):
    a, c = u.GetStart(), u.GetEnd()
    ax, ay, cx, cy, px, py = MM(a.x), MM(a.y), MM(c.x), MM(c.y), MM(p.x), MM(p.y)
    vx, vy = cx - ax, cy - ay; L = vx * vx + vy * vy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * vx + (py - ay) * vy) / L))
    return math.hypot(px - ax - t * vx, py - ay - t * vy)

def seg_seg_dist(s, u):
    if seg_cross(s, u):
        return 0.0
    return min(pt_seg_dist(s.GetStart(), u), pt_seg_dist(s.GetEnd(), u), pt_seg_dist(u.GetStart(), s), pt_seg_dist(u.GetEnd(), s))

def seg_cross(s, u):
    def o(p, q, r):
        return (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)
    p1, p2, p3, p4 = s.GetStart(), s.GetEnd(), u.GetStart(), u.GetEnd()
    d1, d2, d3, d4 = o(p3, p4, p1), o(p3, p4, p2), o(p1, p2, p3), o(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4

if __name__ == '__main__':
    main()
