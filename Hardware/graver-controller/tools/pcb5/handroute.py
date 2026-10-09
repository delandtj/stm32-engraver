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
Also a staggered stub-and-via escape for every used MCU pin (qfn_fan).
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


FAN_SKIP = {'+3V3', '/MCU/VDDA', '/MCU/USB_DP', '/MCU/USB_DM', '/MCU/OSC_IN', '/MCU/OSC_OUT'}

def fan_targets(b):
    """Nets of U301 pins that get a stub + via escape (not the hand-routed and
    not the same-net-neighbour ones: VDD to its decap, VDDA, VCAP1)."""
    out = []
    for p in seq(b.FindFootprintByReference('U301').Pads()):
        n = p.GetNetname()
        if n and not n.startswith('unconnected') and n not in FAN_SKIP and p.GetNumber() != '49':
            out.append((p.GetNumber(), n))
    return out

def qfn_fan(b, nets):
    """Staggered QFN48 escape: from each used pin a straight 0.2 stub outward
    and a via on one of two rows (about 1.0 / 1.8 mm out), each via placed at
    the first clear spot along the pad's outward ray. GND pins get 0.6/0.3
    vias where they fit, 0.5/0.2 otherwise. Returns the nets touched."""
    import math
    u = b.FindFootprintByReference('U301')
    cx, cy = T.mm(u.GetPosition().x), T.mm(u.GetPosition().y)
    CLR = 0.15
    PWR = {'GND', '+3V3', '/MCU/VDDA', '+5V', 'VBUS', 'VIN'}      # classes with 0.2 clearance
    def clr(a, c):
        return 0.2 if (a in PWR or c in PWR) else CLR
    DEBUG = os.environ.get('FAN_DEBUG')
    # obstacles: every pad bbox (except the pin itself), existing tracks and vias
    pads = []
    for f in seq(b.Footprints()):
        for p in seq(f.Pads()):
            bb = p.GetBoundingBox()
            pads.append((f.GetReference(), p.GetNumber(), p.GetNetname(),
                         (T.mm(bb.GetLeft()), T.mm(bb.GetTop()), T.mm(bb.GetRight()), T.mm(bb.GetBottom()))))
    segs, vias = [], []
    for t in seq(b.Tracks()):
        if t.Type() == pcbnew.PCB_VIA_T:
            v = t.Cast(); vias.append((T.mm(v.GetPosition().x), T.mm(v.GetPosition().y), T.mm(v.GetWidth(pcbnew.F_Cu)) / 2, v.GetNetname()))
        elif t.Type() == pcbnew.PCB_TRACE_T:
            a, c = t.GetStart(), t.GetEnd()
            segs.append(((T.mm(a.x), T.mm(a.y)), (T.mm(c.x), T.mm(c.y)), T.mm(t.GetWidth()) / 2, t.GetNetname()))
    def box_dist(x, y, bx):
        dx = max(bx[0] - x, 0, x - bx[2]); dy = max(bx[1] - y, 0, y - bx[3]); return math.hypot(dx, dy)
    def seg_dist(x, y, a, c):
        ax, ay = a; cx_, cy_ = c; vx, vy = cx_ - ax, cy_ - ay; L = vx * vx + vy * vy
        t = 0 if L == 0 else max(0, min(1, ((x - ax) * vx + (y - ay) * vy) / L))
        return math.hypot(x - ax - t * vx, y - ay - t * vy)
    def why(x, y, r, net, ref, num):
        # the first obstacle a via of radius r at (x, y) would violate, or None
        for rf, pn, pnet, bx in pads:
            if rf == ref and pn == num:
                continue
            need = r + clr(net, pnet) if pnet != net else r      # no via in a same-net pad either
            if box_dist(x, y, bx) < need - 0.001:
                return 'pad %s.%s %s' % (rf, pn, pnet)
        for vx, vy, vr, vnet in vias:
            if math.hypot(x - vx, y - vy) < r + vr + (clr(net, vnet) if vnet != net else 0) - 0.001:
                return 'via %s (%.2f, %.2f)' % (vnet, vx, vy)
        for a, c, hw, snet in segs:
            if snet != net and seg_dist(x, y, a, c) < r + hw + clr(net, snet) - 0.001:
                return 'track %s %s-%s' % (snet, a, c)
        return None
    def clear(x, y, r, net, ref, num):
        return why(x, y, r, net, ref, num) is None
    def stub_why(p0, p1, net, ref, num):
        # the stub (half width 0.1) against foreign pads and vias
        for rf, pn, pnet, bx in pads:
            if (rf == ref and pn == num) or pnet == net:
                continue
            for k in range(11):
                x = p0[0] + (p1[0] - p0[0]) * k / 10; y = p0[1] + (p1[1] - p0[1]) * k / 10
                if box_dist(x, y, bx) < 0.1 + clr(net, pnet) - 0.001:
                    return 'stub vs pad %s.%s %s' % (rf, pn, pnet)
        for vx, vy, vr, vnet in vias:
            if vnet != net and seg_dist(vx, vy, p0, p1) < vr + 0.1 + clr(net, vnet) - 0.001:
                return 'stub vs via %s (%.2f, %.2f)' % (vnet, vx, vy)
        return None
    def stub_clear(p0, p1, net, ref, num):
        return stub_why(p0, p1, net, ref, num) is None
    touched = []
    placed = {}
    want = {n for n, _ in fan_targets(b)}
    pins = sorted([p for p in seq(u.Pads()) if p.GetNumber() in want], key=lambda p: int(p.GetNumber()))
    # pins 1-12 bottom, 13-24 right, 25-36 top, 37-48 left: alternate the two
    # rows (0.9 / 1.7 mm out) along each side so neighbours never share a lane
    for p in pins:
        px, py = T.mm(p.GetPosition().x), T.mm(p.GetPosition().y); net = p.GetNetname(); num = p.GetNumber()
        # outward unit vector: the pad's side of the package
        dx, dy = px - cx, py - cy
        if abs(dx) > abs(dy):
            ux, uy = (1 if dx > 0 else -1), 0
        else:
            ux, uy = 0, (1 if dy > 0 else -1)
        # a same-net pad straight out within 3.5 mm (C311.2 under VSSA, C308 at VCAP1): plain stub
        hit = None
        for rf, pn, pnet, bx in pads:
            if pnet != net or rf == 'U301':
                continue
            if ux and bx[1] <= py <= bx[3] and 0 < (bx[0] if ux > 0 else px - bx[2]) * 1 and ((ux > 0 and 0 < bx[0] - px < 3.5) or (ux < 0 and 0 < px - bx[2] < 3.5)):
                hit = ((bx[0] + bx[2]) / 2, py)
            if uy and bx[0] <= px <= bx[2] and ((uy > 0 and 0 < bx[1] - py < 3.5) or (uy < 0 and 0 < py - bx[3] < 3.5)):
                hit = (px, (bx[1] + bx[3]) / 2)
        if hit and DEBUG:
            print('  pin %s %s straight to %s: %s' % (num, net, hit, stub_why((px, py), hit, net, 'U301', num) or 'ok'))
        if hit and stub_clear((px, py), hit, net, 'U301', num):
            T.add_track(b, net, 'F.Cu', [(px, py), hit], 0.2)
            segs.append(((px, py), hit, 0.1, net)); placed[num] = (net, 0, 0, 0); touched.append(net)
            continue
        sizes = [(0.3, 0.15), (0.25, 0.1)] if net == 'GND' else [(0.25, 0.1)]
        rows = (0.9, 1.7) if int(num) % 2 == 1 else (1.7, 0.9)
        cands = [r0 + 0.1 * k for r0 in rows for k in (0, 1, 2, 3, 4)] + [2.4 + 0.1 * k for k in range(8)]
        done = False
        for r, dr in sizes:
            for d in cands:
                for lat in (0, 0.1, -0.1, 0.2, -0.2, 0.3, -0.3):
                    vx = px + ux * d + (-uy) * lat; vy = py + uy * d + ux * lat
                    # stub: straight out to d - |lat|, then 45 degrees to the via
                    jx = px + ux * (d - abs(lat)); jy = py + uy * (d - abs(lat))
                    if not clear(vx, vy, r, net, 'U301', num):
                        continue
                    if not (stub_clear((px, py), (jx, jy), net, 'U301', num) and stub_clear((jx, jy), (vx, vy), net, 'U301', num)):
                        continue
                    pts = [(px, py), (jx, jy)] + ([(vx, vy)] if lat else [])
                    T.add_track(b, net, 'F.Cu', pts, 0.2)
                    T.add_via(b, net, vx, vy, 2 * r, 2 * dr)
                    vias.append((vx, vy, r, net))
                    segs.append(((px, py), (jx, jy), 0.1, net)); segs.append(((jx, jy), (vx, vy), 0.1, net))
                    placed[num] = (net, round(d, 2), lat, 2 * r); touched.append(net); done = True
                    break
                if done: break
            if done: break
        if not done:
            print('FAN: no clear via for pin %s %s' % (num, net))
            if DEBUG:
                for d in rows:
                    vx, vy = px + ux * d, py + uy * d
                    print('    row %.1f at (%.2f, %.2f): %s / %s' % (d, vx, vy, why(vx, vy, 0.25, net, 'U301', num), stub_why((px, py), (vx, vy), net, 'U301', num)))
    print('QFN fan: %d pins escaped: %s' % (len(placed), ' '.join('%s@%.1f%s' % (k, v[1], '' if v[2] == 0 else '%+.1f' % v[2]) for k, v in sorted(placed.items(), key=lambda kv: int(kv[0])))))
    return touched


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'graver-controller.kicad_pcb'
    b = pcbnew.LoadBoard(path)
    T.drop_group(b, GROUP)
    # start from bare placement: every track and via goes, and the outer-layer
    # pours (gndpour re-makes them); rule areas and the inner planes stay
    for t in seq(b.Tracks()):
        b.Delete(t)
    inner = {b.GetLayerID('In1.Cu'), b.GetLayerID('In2.Cu')}
    for z in seq(b.Zones()):
        if not z.GetIsRuleArea() and z.GetLayer() not in inner:
            b.Delete(z)
    # the four EP thermal vias of U301 belong to place.py: put them back
    ep = [p for p in seq(b.FindFootprintByReference('U301').Pads()) if p.GetNumber() == '49'][0]
    ex, ey = T.mm(ep.GetPosition().x), T.mm(ep.GetPosition().y)
    for ddx in (-1.2, 1.2):
        for ddy in (-1.2, 1.2):
            T.add_via(b, 'GND', ex + ddx, ey + ddy, 0.6, 0.3)
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
    tr('XO', [p6, (p6[0], c311[1]), c311], 0.2)     # C311.1 (0402) spans pin 6's x: straight down
    tr('XO', [c311, (c311[0], y3[1]), y3], 0.2)

    fan_nets = qfn_fan(b, nets)
    items = [t for t in seq(b.Tracks()) if t.GetNetname() in list(nets.values()) + fan_nets]
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
