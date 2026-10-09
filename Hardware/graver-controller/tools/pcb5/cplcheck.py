#!/usr/bin/env python3
"""Verify the CPL rotation corrections against the EasyEDA/JLC footprints.

    python3 tools/pcb5/cplcheck.py [fab/graver-controller-cpl.csv]

For every placed part with an LCSC number except the unpolarized two-pad
passives, it
downloads the EasyEDA footprint behind the LCSC number (the one JLC places
with), finds the rotation that maps the KiCad library footprint's pads onto
it (by pad number, 0/90/180/270), and compares the implied KiCad -> JLC
correction with what jlcfab applied. The sign convention is calibrated on
the parts whose corrections were confirmed in JLC's preview for
granite_controller (SOIC-8 C398355 = 270, SOT-23-6 C7519 = 270). Downloads
are cached in $SCRATCH/easyeda and parsed as data only.
"""
import json, math, os, re, subprocess, sys
import pcbnew

MM = pcbnew.ToMM
CACHE = os.path.join(os.environ.get('SCRATCH', os.path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'graver-pcb5')), 'easyeda')
FPDIR = os.environ.get('KICAD10_FOOTPRINT_DIR', '/usr/share/kicad/footprints')
MIL10 = 0.254                      # EasyEDA unit = 10 mil

def seq(c):
    return [c[i] for i in range(len(c))]

def easyeda_pads(lcsc):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, lcsc + '.json')
    if not os.path.exists(f):
        subprocess.run(['curl', '-s', '-m', '40', '-o', f, 'https://easyeda.com/api/products/%s/components?version=6.4.19.5' % lcsc], check=True)
    d = json.load(open(f))
    shapes = d['result']['packageDetail']['dataStr']['shape']
    pads = []
    for sh in shapes:
        if not sh.startswith('PAD~'):
            continue
        p = sh.split('~')
        # PAD~shape~x~y~w~h~layer~net~number~hole~points~rot~...
        pads.append((p[8], float(p[2]) * MIL10, float(p[3]) * MIL10))
    return pads

def kicad_pads(lib, name):
    fp = pcbnew.FootprintLoad(os.path.join(FPDIR, lib + '.pretty'), name)
    return [(p.GetNumber(), MM(p.GetPosition().x), MM(p.GetPosition().y)) for p in seq(fp.Pads())]

def centre(pads):
    xs = [x for _, x, _ in pads]; ys = [y for _, _, y in pads]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

def rot(x, y, deg):
    # KiCad: positive = counter-clockwise on screen, y down
    t = math.radians(deg); c, s = math.cos(t), math.sin(t)
    return x * c + y * s, -x * s + y * c

def best_rotation(kp, ep):
    kc, ec = centre(kp), centre(ep)
    k = [(n, x - kc[0], y - kc[1]) for n, x, y in kp]
    e = {}
    for n, x, y in ep:
        e.setdefault(n, []).append((x - ec[0], y - ec[1]))
    # KiCad numbers repeat on parts whose pins are internally joined (tactile
    # switches: 1,1,2,2 against EasyEDA's 1,2,3,4); there the numbers say
    # nothing and the pad pattern alone decides (0/180 ambiguity is harmless,
    # the joined pads are symmetric)
    from collections import Counter
    counts = Counter(n for n, _, _ in k)
    unique = {n for n, c in counts.items() if c == 1 and n in e}
    by_number = bool(unique)          # QFN: 48 unique pins plus a split EP numbered 49
    allpads = [v for vs in e.values() for v in vs]
    best = None
    for deg in (0, 90, 180, 270):
        err = 0.0; cnt = 0
        for n, x, y in k:
            rx, ry = rot(x, y, deg)
            if by_number and n not in unique:
                continue
            pool = e.get(n) if by_number else allpads
            if not pool:
                continue
            err += min(math.hypot(rx - ex, ry - ey) for ex, ey in pool); cnt += 1
        if cnt and (best is None or err / cnt < best[1] - 1e-9):
            best = (deg, err / cnt, cnt)
    return best

UNPOLARIZED = re.compile(r'^(R|C|L|Fuse)_\d{4}_\d{4}Metric$')

def main():
    cpl = sys.argv[1] if len(sys.argv) > 1 else 'fab/graver-controller-cpl.csv'
    b = pcbnew.LoadBoard('graver-controller.kicad_pcb')
    import csv
    jlc_rot = {}
    with open(cpl) as f:
        for r in csv.DictReader(f):
            jlc_rot[r['Designator']] = float(r['Rotation'])
    rows = []
    for fp in seq(b.Footprints()):
        ref = fp.GetReference()
        if ref not in jlc_rot:
            continue
        lib, name = fp.GetFPID().GetLibNickname().wx_str(), fp.GetFPID().GetLibItemName().wx_str()
        if UNPOLARIZED.match(name):
            continue
        lcsc = ''
        for fld in seq(fp.GetFields()):
            if fld.GetName() == 'LCSC':
                lcsc = fld.GetText()
        applied = round((jlc_rot[ref] - fp.GetOrientationDegrees()) % 360)
        try:
            ep = easyeda_pads(lcsc)
        except Exception as ex:
            rows.append((ref, name, lcsc, applied, None, 'fetch failed: %s' % ex)); continue
        kp = kicad_pads(lib, name)
        bst = best_rotation(kp, ep)
        if not bst:
            rows.append((ref, name, lcsc, applied, None, 'no common pad numbers')); continue
        deg, err, cnt = bst
        rows.append((ref, name, lcsc, applied, deg, 'fit %.2f mm over %d pads' % (err, cnt)))
    cal = [(r[4], r[3]) for r in rows if r[2] in ('C398355', 'C7519') and r[4] is not None]
    conv = None
    for cname, f in (('corr = deg', lambda d: d % 360), ('corr = -deg', lambda d: (-d) % 360)):
        if cal and all(f(d) == a for d, a in cal):
            conv = (cname, f)
    print('calibration parts:', cal, '->', conv[0] if conv else 'INCONSISTENT')
    bad = 0
    for ref, fpname, lcsc, applied, deg, note in sorted(rows):
        if deg is None:
            print('  ?    %-6s %-45s %-9s applied %3d  %s' % (ref, fpname[:45], lcsc, applied, note)); bad += 1; continue
        want = conv[1](deg) if conv else None
        ok = want == applied
        bad += not ok
        print('  %s %-6s %-45s %-9s applied %3d  easyeda = kicad%+4d -> want %s  %s' % ('ok ' if ok else 'BAD', ref, fpname[:45], lcsc, applied, deg, want, note))
    print('%d of %d parts disagree with the table' % (bad, len(rows)))
    sys.exit(1 if bad else 0)

if __name__ == '__main__':
    main()
