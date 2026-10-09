#!/usr/bin/env python3
"""Placement for the compact 4-layer graver controller (ADR 0005).

Run from the project root:  python3 tools/pcb5/place.py
Board: 85 x 60 mm, origin (50, 50); rear edge y=50, front edge y=110.
Re-runnable: every footprint is re-placed from scratch and the rule areas,
inner plane zones and EP thermal vias this script owns (group "place-owned")
are deleted and recreated. Saves to a scratch file and copies only the
.kicad_pcb back, so pcbnew does not rewrite the project's .kicad_pro.

Blocks (x ranges): power 51.5-82 (rear-left) + 77-88 front extension,
MCU 83-101 centre, driver 103-133.5 (rear-right), IO along the front edge.
ADR 0004 boost reserve keeps x 51.5-76.5, y 88.5-108.5 empty (L-shaped
around the MH403 hole keepout).
"""
import math, os, shutil, sys
sys.path.insert(0, os.path.expanduser('~/Electronics/pcbkit'))
import pcbnew
from pcbkit.pcbtool import MM, mm, P, seq, cbox, load, add_via, pad_xy, Placer

PCB = 'graver-controller.kicad_pcb'
SCRATCH = '/tmp/claude-1000/-home-delandtj-Electronics-stm32-engraver/92f71cd3-1b38-4f2e-aa05-92c476a0c5b2/scratchpad/place'
OUT = os.path.join(SCRATCH, 'out.kicad_pcb')
GROUP = 'place-owned'

BX0, BY0, BX1, BY1 = 50.0, 50.0, 135.0, 110.0
MARGIN = 1.5
BOOST = (51.5, 88.5, 76.5, 108.5)          # ADR 0004 reserve
HOLES = {'MH401': (54, 54), 'MH402': (131, 54), 'MH403': (54, 106), 'MH404': (131, 106)}

b = load(PCB)
pl = Placer(b, gap=0.5, step=0.5)
FP = pl.fp

# ------------------------------------------------------------ cleanup
for g in seq(b.Groups()):
    if g.GetName() == GROUP:
        for it in list(g.GetItems()):
            b.Delete(it)
        b.Delete(g)
for z in [b.Zones()[i] for i in range(len(b.Zones()))]:
    if z.GetZoneName() in ('ADR0004 boost reserve', 'xtal keepout', 'clamp-bias', 'fine-pitch') or z.GetZoneName().startswith('MH40') \
            or (not z.GetIsRuleArea() and z.GetLayerSet().Contains(pcbnew.In1_Cu) | z.GetLayerSet().Contains(pcbnew.In2_Cu)):
        b.Delete(z)
for t in [b.Tracks()[i] for i in range(len(b.Tracks()))]:
    if t.GetClass() == 'PCB_VIA' and t.GetNetname() == 'GND' and b.FindFootprintByReference('U301') \
            and FP['U301'].HitTest(t.GetPosition()):
        b.Delete(t)
# park everything off board so stale positions never count as obstacles
for i, f in enumerate(FP.values()):
    f.SetOrientationDegrees(0)
    f.SetPosition(pcbnew.VECTOR2I_MM(20, 20 + i * 0.1))

group = pcbnew.PCB_GROUP(b)
group.SetName(GROUP)
b.Add(group)


def _warn(ref):
    me = pl.placed.pop()
    if pl.hit(me):
        print(f'  WARN {ref} courtyard {tuple(round(v, 2) for v in me)} hits a placed part')
    pl.placed.append(me)

def put(ref, x, y, rot=0):
    pl.put(ref, x, y, rot); _warn(ref)

def putc(ref, cx, cy, rot=0):
    pl.put_c(ref, cx, cy, rot); _warn(ref)

def pack(refs, regions, rot=0):
    left = pl.pack(refs, regions, rot)
    return left

# ------------------------------------------------------------ mounting holes
for r, (x, y) in HOLES.items():
    put(r, x, y)
# boost reserve is an obstacle for the placer (gap applies); MH403 sits in it by ADR
pl.placed.append(BOOST)

# ------------------------------------------------------------ rear edge row (y 53.5 pad line)
put('J101', 60.5, 53.5, 0)          # power in, pad 1 GND left
putc('SW301', 72.5, 54.5, 0)       # BOOT0, on the rear edge
putc('SW302', 81.0, 54.5, 0)      # RESET
put('J301', 93.0, 54.0, 180)        # USB-C, mouth flush with the rear edge (courtyard 0.2 proud)
put('J201', 104.5, 53.5, 90)        # handpiece 1..4 left to right
put('J402', 117.0, 53.5, 90)        # pedal

# ------------------------------------------------------------ power block
put('C101', 56.0, 65.0, 0)          # 470 uF radial, rear-left (origin = pad 1)
putc('F101', 67.0, 60.0, 270)       # fuse below J101 pad 2
putc('Q101', 73.5, 62.0, 0)         # reverse-polarity PMOS, drain at F101
putc('D102', 71.0, 68.5, 0)         # VIN TVS
putc('D101', 79.5, 67.5, 0)         # gate zener
putc('R101', 79.5, 70.0, 0)         # gate pulldown
putc('U101', 61.5, 79.5, 0)         # LM5164
putc('C105', 54.5, 76.5, 180)      # CIN 2.2u, VIN pad right at pins 1/2
putc('C107', 54.5, 79.5, 180)      # CIN 100n, at pins 1/2
putc('C106', 54.5, 82.5, 180)      # CIN 2.2u
putc('C108', 67.0, 78.0, 90)      # BST cap across pins 7/8
putc('L101', 72.0, 79.0, 270)       # SW pad up at pin 8, output pad down
putc('C111', 78.0, 79.0, 90)      # buck out
putc('C112', 81.0, 79.0, 90)
putc('D105', 79.5, 88.0, 90)        # buck out -> +5V OR diode
putc('D103', 84.0, 88.0, 90)        # VBUS -> +5V OR diode
putc('U102', 81.5, 95.0, 0)         # LDO

# ------------------------------------------------------------ MCU block
U = (93.5, 72.0)
putc('U301', U[0], U[1], 90)        # pins 25-36 face the rear (J301)
put('J302', 84.5, 61.0, 0)          # SWD, pad 1 towards the rear
putc('U302', 93.5, 64.0, 270)       # USBLC6 in line on the pair
putc('C303', 90.0, 65.5, 90)        # VDD 36
putc('C302', 100.0, 67.5, 0)       # clear of C308 (moved for the VCAP1 stub)        # VDD 24
putc('C308', 100.5, 70.25, 0)       # pad 1 straight out from VCAP1 pin 22 (fan stub)        # VCAP1 22
putc('C304', 87.0, 75.0, 180)       # VDD 48
putc('C301', 89.0, 78.5, 270)       # VDD 1
putc('C305', 86.0, 77.5, 180)       # 4u7 bulk
putc('C310', 91.5, 77.5, 0)        # OSC_IN load
putc('C311', 94.0, 77.5, 0)        # OSC_OUT load
putc('Y301', 93.0, 80.5, 0)
putc('C306', 97.5, 77.5, 0)         # VDDA 1u, VDDA pad left
putc('C307', 98.5, 80.0, 0)       # VDDA 10n
putc('FB301', 98.5, 82.5, 180)      # ferrite, VDDA pad left
putc('R305', 100.0, 59.0, 90)       # CC1
putc('R306', 102.5, 59.0, 90)       # CC2

# ------------------------------------------------------------ driver block
put('Q201', 108.0, 61.5, 90)        # tab (COIL_NEG) up towards J201 pin 2
putc('R201', 106.0, 69.5, 180)      # gate resistor, pad 1 (OUT) right
putc('U201', 106.0, 73.5, 0)        # UCC27517
putc('R204', 110.5, 70.0, 180)      # 1R shunt, SHUNT_HI pad right, under the source
putc('R209', 115.0, 69.0, 0)        # Kelvin taps
putc('R213', 115.0, 71.5, 0)
putc('U202', 121.0, 72.0, 0)        # TLV9062
putc('D201', 116.0, 59.0, 180)      # COIL_NEG pad left towards the tab
putc('D202', 116.0, 64.0, 180)
putc('Q202', 122.5, 64.0, 0)
putc('U401', 122.5, 59.0, 0)        # pedal ESD at J402

# ------------------------------------------------------------ IO front row
put('J401', 80.0, 106.5, 90)        # display 1..7 left to right
put('J403', 101.5, 106.5, 90)       # encoder

# ------------------------------------------------------------ passive rows
def row(refs, x0, dx, y, rot=90):
    """Courtyard centres from x0 in steps of dx along y (None skips a slot)."""
    for i, r in enumerate(refs):
        if r:
            putc(r, x0 + i * dx, y, rot)

def col(refs, x, y0, dy, rot=0):
    for i, r in enumerate(refs):
        if r:
            putc(r, x, y0 + i * dy, rot)

# power
row(['C102', 'C103'], 59.5, 4.0, 73.5, 0)                      # HF caps by C101, VIN pad left
row(['R105', 'R106', 'R107', 'R108', 'C109', 'C110', 'R110', 'R109'], 52.5, 2.5, 86.0)  # EN/RON, FB, ripple inj.
putc('C113', 78.0, 95.0, 90)                                    # LDO in
putc('C114', 85.0, 95.0, 90)                                    # LDO out, towards the MCU
putc('C115', 87.5, 95.0, 90)
row(['R102', 'R103', 'C104', 'R104', 'D104'], 78.0, 2.5, 100.0) # VIN sense, power LED
# MCU
putc('C309', 87.25, 70.5, 90)      # NRST cap, clear of the left fan rows (x > 88.1)                                    # NRST, between J302 pin 4 and U301
putc('R307', 97.0, 64.5, 90)                                    # PA10 pull-up at pin 31
row(['R301', 'R302', 'R303'], 87.5, 2.5, 86.5)                  # BOOT0 / PB2 straps
row(['R402', 'R403', 'R404'], 87.5, 2.0, 90.5)                  # encoder pull-ups
row(['C401', 'C402', 'C403'], 94.0, 2.5, 90.5)                  # encoder debounce
row(['D301', 'R304', 'R401'], 92.0, 4.0, 100.0, 0)              # status LED, backlight R at J401.7
# driver: one row under U201 / U202, gate parts left, analog right
row(['C201', 'C202', 'R202', 'C205', 'R212', 'R210', 'R211', 'C204'], 105.5, 2.5, 77.5)
# pedal filter right of U401
row(['R407', 'R408', 'C405'], 126.0, 2.5, 60.0)
row(['R405', 'R406', 'C404'], 126.0, 2.5, 64.0)
putc('Q203', 127.5, 68.0, 0)
putc('D203', 131.5, 68.5, 90)
# right grid: comparator / NTC / decay network
col(['C203', 'R214', 'R215', 'R216', 'C206', 'C207'], 127.0, 72.5, 2.5, 0)
col(['R205', 'R206', 'R207', 'R208', 'R217', 'R203'], 131.0, 72.5, 2.5, 0)
leftover_after_pack = [r for r, f in FP.items() if mm(f.GetPosition().x) < BX0]

# ------------------------------------------------------------ owned copper / areas
def own(item):
    b.Add(item)
    group.AddItem(item)

def lset(*layers):
    s = pcbnew.LSET()
    for L in layers:
        s.AddLayer(L)
    return s

CU4 = (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu)

def rule_area(name, pts, layers, footprints=False):
    z = pcbnew.ZONE(b)
    z.SetIsRuleArea(True)
    z.SetZoneName(name)
    z.SetLayerSet(lset(*layers))
    o = z.Outline(); o.NewOutline()
    for x, y in pts:
        o.Append(MM(x), MM(y))
    z.SetDoNotAllowTracks(True); z.SetDoNotAllowVias(True); z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowPads(footprints); z.SetDoNotAllowFootprints(footprints)
    own(z)
    return z

def circle(cx, cy, r, n=24):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]

def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

for r, (x, y) in HOLES.items():
    rule_area(f'{r} keepout', circle(x, y, 3.25), CU4)
# L-shaped: the corner at MH403 belongs to the hole keepout, not the reserve
BOOST_POLY = [(BOOST[0], BOOST[1]), (BOOST[2], BOOST[1]), (BOOST[2], BOOST[3]), (58.5, BOOST[3]), (58.5, 101.5), (BOOST[0], 101.5)]
rule_area('ADR0004 boost reserve', BOOST_POLY, CU4, footprints=True)
# 'fine-pitch': ADR 0003 D5 allows 0.2 mm tracks at the 0.5 mm pitch parts; the
# .kicad_dru power floors skip these areas (courtyard + 1.2 mm)
for r in ('U301', 'J301', 'U302'):
    fx0, fy0, fx1, fy1 = cbox(FP[r])
    zf = rule_area('fine-pitch', rect(fx0 - 1.2, fy0 - 1.2, fx1 + 1.2, fy1 + 1.2), (pcbnew.F_Cu, pcbnew.B_Cu))
    for fn in (zf.SetDoNotAllowTracks, zf.SetDoNotAllowVias, zf.SetDoNotAllowZoneFills):
        fn(False)
zb = rule_area('clamp-bias', rect(123.6, 65.0, 133.4, 77.0), CU4)
for fn in (zb.SetDoNotAllowTracks, zb.SetDoNotAllowVias, zb.SetDoNotAllowZoneFills):
    fn(False)   # no keepout: a named area for the .kicad_dru width exception only
xb = [cbox(FP[r]) for r in ('Y301', 'C310', 'C311')]
# no margin on the MCU side: the bottom fan-via row (y about 76.3-77.1) and its B.Cu exits sit there
XT = (min(q[0] for q in xb) - 1, min(q[1] for q in xb), max(q[2] for q in xb), max(q[3] for q in xb) + 1)
# B.Cu only, tracks only: the crystal's own F.Cu tracks are hand-routed by
# tools/pcb5/handroute.py and its GND pads need vias to the In1 plane.
z = rule_area('xtal keepout', rect(*XT), (pcbnew.B_Cu,))
z.SetDoNotAllowVias(False); z.SetDoNotAllowZoneFills(False)

def plane(layer, net):
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(b.FindNet(net))
    z.SetZoneName(f'{net} plane')
    o = z.Outline(); o.NewOutline()
    for x, y in rect(BX0 + 0.5, BY0 + 0.5, BX1 - 0.5, BY1 - 0.5):
        o.Append(MM(x), MM(y))
    z.SetLocalClearance(MM(0.25))
    z.SetMinThickness(MM(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetAssignedPriority(0)
    own(z)

plane(pcbnew.In1_Cu, 'GND')
plane(pcbnew.In2_Cu, '+3V3')

ep = FP['U301'].FindPadByNumber('49').GetPosition()
ex, ey = mm(ep.x), mm(ep.y)
for dx in (-1.2, 1.2):
    for dy in (-1.2, 1.2):
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(P(ex + dx, ey + dy)); v.SetWidth(MM(0.6)); v.SetDrill(MM(0.3))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(b.FindNet('GND'))
        own(v)

# ------------------------------------------------------------ checks
def padbox(p):
    bb = p.GetBoundingBox()
    return (mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))

def bdist(a, c):
    dx = max(0.0, c[0] - a[2], a[0] - c[2])
    dy = max(0.0, c[1] - a[3], a[1] - c[3])
    return math.hypot(dx, dy)

def pad(ref, num):
    return FP[ref].FindPadByNumber(str(num))

def pd(r1, n1, r2, n2):
    return bdist(padbox(pad(r1, n1)), padbox(pad(r2, n2)))

def net_pad(ref, net):
    return [p for p in seq(FP[ref].Pads()) if p.GetNetname().split('/')[-1] == net]

def fp_pad_dist(r1, r2, nums2=None):
    ps2 = [p for p in seq(FP[r2].Pads()) if nums2 is None or p.GetNumber() in nums2]
    return min(bdist(padbox(a), padbox(c)) for a in seq(FP[r1].Pads()) if a.GetNumber() for c in ps2)

def cy_dist(r1, r2):
    return bdist(cbox(FP[r1]), cbox(FP[r2]))

rows = []
def chk(name, val, ok, unit='mm'):
    rows.append((name, val, ok, unit))

def le(name, v, lim): chk(f'{name} <= {lim}', v, v <= lim + 1e-6)
def ge(name, v, lim): chk(f'{name} >= {lim}', v, v >= lim - 1e-6)

le('Y301.1 - U301.5 (pad)', pd('Y301', 1, 'U301', 5), 5)
le('Y301.3 - U301.6 (pad)', pd('Y301', 3, 'U301', 6), 5)
for c, pin in (('C301', 1), ('C302', 24), ('C303', 36), ('C304', 48)):
    v = min(bdist(padbox(p), padbox(pad('U301', pin))) for p in net_pad(c, '+3V3'))
    le(f'{c}+3V3 - U301.{pin} VDD (pad)', v, 2)
le('C305 - U301 VDD pin (pad, near)', min(bdist(padbox(p), padbox(pad('U301', n))) for p in net_pad('C305', '+3V3') for n in (1, 24, 36, 48)), 4)
le('C308 - U301.22 VCAP (pad)', min(bdist(padbox(p), padbox(pad('U301', 22))) for p in seq(FP['C308'].Pads())), 2)
le('C306 - U301.9 VDDA (pad)', min(bdist(padbox(p), padbox(pad('U301', 9))) for p in net_pad('C306', 'VDDA')), 2)
for c in ('C105', 'C106', 'C107'):
    le(f'{c} VIN pad - U101.2 VIN (pad)', min(bdist(padbox(p), padbox(pad('U101', 2))) for p in net_pad(c, 'VIN')), 3)
ANALOG = ('U202', 'R204', 'C205', 'R210', 'R211', 'R212')
for r in ('U101', 'L101'):
    ge(f'{r} - Y301 (courtyard)', cy_dist(r, 'Y301'), 15)
    ge(f'{r} - analog front end (courtyard)', min(cy_dist(r, a) for a in ANALOG), 15)
le('U201 - Q201 gate pad (pad)', fp_pad_dist('U201', 'Q201', ['1']), 5)
le('U202 - R204 (pad)', fp_pad_dist('U202', 'R204'), 10)
le('R209/R213 - R204.1 (pad)', max(pd('R209', 1, 'R204', 1), pd('R213', 1, 'R204', 1)), 2)
ge('C101 - J401/J403 (courtyard)', min(cy_dist('C101', 'J401'), cy_dist('C101', 'J403')), 10)
u33 = pad_xy(b, 'U301', 33)
usb = max(math.dist(pad_xy(b, 'J301', n), u33) for n in ('A6', 'B6'))
le('USB J301 A6/B6 - U301.33 (straight)', usb, 40)
drv = [r for r in pl.sheet('Driver')]
usbp = [padbox(p) for r in ('J301', 'U302', 'U301') for p in seq(FP[r].Pads()) if p.GetNetname().split('/')[-1] in ('USB_DP', 'USB_DM')]
xtp = [padbox(p) for p in seq(FP['Y301'].Pads())]
drvp = [padbox(p) for r in drv for p in seq(FP[r].Pads())]
ge('driver pads - Y301 pads', min(bdist(a, c) for a in drvp for c in xtp), 10)
ge('driver pads - USB pair pads', min(bdist(a, c) for a in drvp for c in usbp), 10)

boxes = {r: cbox(f) for r, f in FP.items()}
ov = []
refs = sorted(boxes)
for i, a in enumerate(refs):
    for c in refs[i + 1:]:
        A, C = boxes[a], boxes[c]
        if not (A[2] + 0.5 <= C[0] + 1e-6 or C[2] + 0.5 <= A[0] + 1e-6 or A[3] + 0.5 <= C[1] + 1e-6 or C[3] + 0.5 <= A[1] + 1e-6):
            ov.append(f'{a}/{c}')
chk('courtyard overlaps (gap < 0.5) = 0', len(ov), not ov, '')
mg = [r for r, q in boxes.items() if r not in HOLES and r != 'J301' and
      (q[0] < BX0 + MARGIN - 1e-6 or q[1] < BY0 + MARGIN - 1e-6 or q[2] > BX1 - MARGIN + 1e-6 or q[3] > BY1 - MARGIN + 1e-6)]
chk('courtyards >= 1.5 inside outline (excl. MH, J301) = 0', len(mg), not mg, '')
outside = [r for r, f in FP.items() if not (BX0 <= mm(f.GetPosition().x) <= BX1 and BY0 <= mm(f.GetPosition().y) <= BY1)]
chk('parts outside board = 0', len(outside), not outside, '')
inb = [r for r, q in boxes.items() if r != 'MH403' and bdist(q, BOOST) < 1e-6 and
       not (q[2] <= BOOST[0] or q[0] >= BOOST[2] or q[3] <= BOOST[1] or q[1] >= BOOST[3])]
chk('courtyards inside boost keepout (excl. MH403) = 0', len(inb), not inb, '')
flipped = [r for r, f in FP.items() if f.IsFlipped()]
chk('flipped parts = 0', len(flipped), not flipped, '')
def _ongrid(v, g=0.25):
    return abs(v / g - round(v / g)) < 1e-4
offgrid = [r for r, f in FP.items() if not (_ongrid(mm(f.GetPosition().x)) and _ongrid(mm(f.GetPosition().y)))]
chk('origins off the 0.25 mm grid = 0', len(offgrid), not offgrid, '')
badrot = [r for r, f in FP.items() if round(f.GetOrientationDegrees()) % 90]
chk('rotations not a multiple of 90 = 0', len(badrot), not badrot, '')

print(f'{"check":52s} {"value":>8s}  result')
for name, v, ok, unit in rows:
    print(f'{name:52s} {v:8.2f}  {"PASS" if ok else "FAIL"}')
for lbl, lst in (('overlaps', ov), ('margin', mg), ('outside', outside), ('boost', inb), ('offgrid', offgrid), ('unpacked', leftover_after_pack)):
    if lst:
        print(f'  {lbl}: {" ".join(lst)}')

# free space: extent of all courtyards except the mounting holes
ext = [q for r, q in boxes.items() if r not in HOLES]
print(f'courtyard extent x {min(q[0] for q in ext):.2f}..{max(q[2] for q in ext):.2f}  '
      f'y {min(q[1] for q in ext):.2f}..{max(q[3] for q in ext):.2f}')

os.makedirs(SCRATCH, exist_ok=True)
b.Save(OUT)
shutil.copy(OUT, PCB)
print('saved', OUT, '->', PCB)
bad = [r for r in rows if not r[2]]
sys.exit(1 if (outside or leftover_after_pack or bad) else 0)
