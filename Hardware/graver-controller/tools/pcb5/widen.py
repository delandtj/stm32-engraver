#!/usr/bin/env python3
"""Widen router stubs to their net class width where the board allows it.

    python3 tools/pcb5/widen.py [board.kicad_pcb]

KRT necks power/GND tracks at pads and plane taps. Every segment below its
class width is set to the class width, kicad-cli DRC runs, and the segments
that now violate clearance (or edge/hole clearance) go back to their old
width; repeat until DRC is stable. Prints how many stayed narrow per net.
The .kicad_dru floors (half the class width) still apply to those.
"""
import json, os, re, shutil, subprocess, sys
import pcbnew

S = os.path.join(os.environ.get('SCRATCH', os.path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'graver-pcb5')), 'widen')
MM = pcbnew.ToMM
ALLOWED = (0.2, 0.25, 0.4, 0.5, 0.8, 1.0)   # ADR 0005 Decision 3 widths

def seq(c):
    return [c[i] for i in range(len(c))]

def class_widths(pro):
    d = json.load(open(pro)); ns = d['net_settings']
    w = {c['name']: c['track_width'] for c in ns['classes']}
    return {p['pattern']: w[p['netclass']] for p in ns.get('netclass_patterns', [])}

def drc(board, rpt):
    # refill: the pour steps back from a widened track, so without a refill
    # the stale fill reports a clearance violation that is not real
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--severity-error', '--refill-zones', '--save-board', '-o', rpt, board],
                   check=True, capture_output=True)
    txt = open(rpt).read()
    pts = set()
    for m in re.finditer(r'^\[(clearance|copper_edge_clearance|hole_clearance|shorting_items|tracks_crossing)\].*?(?=^\[|\Z)', txt, re.S | re.M):
        for x, y in re.findall(r'@\(([-\d.]+) mm, ([-\d.]+) mm\): Track', m.group(0)):
            pts.add((round(float(x), 3), round(float(y), 3)))
    return pts

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'graver-controller.kicad_pcb'
    pro = path.replace('.kicad_pcb', '.kicad_pro')
    cw = class_widths(pro)
    os.makedirs(S, exist_ok=True)
    for f in (pro, path.replace('.kicad_pcb', '.kicad_dru')):
        if os.path.exists(f):
            shutil.copy(f, S)
    work = os.path.join(S, os.path.basename(path))
    b = pcbnew.LoadBoard(path)
    old = {}
    snapped = 0
    for t in seq(b.Tracks()):
        if t.Type() != pcbnew.PCB_TRACE_T:
            continue
        # KRT escalations leave odd widths (0.24, 0.32): snap down to the ADR set first
        w0 = round(MM(t.GetWidth()), 3)
        if w0 not in ALLOWED:
            t.SetWidth(pcbnew.FromMM(max([a for a in ALLOWED if a <= w0 + 1e-6] or [0.2]))); snapped += 1
        w = cw.get(t.GetNetname())
        if w and MM(t.GetWidth()) + 1e-6 < w:
            old[t.m_Uuid.AsString()] = (t, MM(t.GetWidth()))
            t.SetWidth(pcbnew.FromMM(w))
    print('odd widths snapped:', snapped, ' candidates widened:', len(old))
    reverted = 0
    for rnd in range(12):
        b.Save(work)
        pts = drc(work, os.path.join(S, 'drc.rpt'))
        b = pcbnew.LoadBoard(work)              # the refilled board; re-find our tracks
        byid = {t.m_Uuid.AsString(): t for t in seq(b.Tracks())}
        old = {u: (byid[u], w0) for u, (t, w0) in old.items() if u in byid}
        hit = []
        for uid, (t, w0) in old.items():
            if MM(t.GetWidth()) == w0:
                continue
            a, c = t.GetStart(), t.GetEnd()
            # DRC reports the segment start; match either end
            if (round(MM(a.x), 3), round(MM(a.y), 3)) in pts or (round(MM(c.x), 3), round(MM(c.y), 3)) in pts:
                hit.append(t)
        if not hit:
            print('round %d: DRC clean of width-induced errors' % rnd)
            break
        for t in hit:
            w0 = old[t.m_Uuid.AsString()][1]; w = MM(t.GetWidth())
            lower = [a for a in ALLOWED if w0 + 1e-6 < a < w - 1e-6]   # next width down in the ADR set
            t.SetWidth(pcbnew.FromMM(max(lower) if lower else w0))
        reverted += len(hit)
        print('round %d: %d reverted' % (rnd, len(hit)))
    b.Save(work)
    drc(work, os.path.join(S, 'drc.rpt')); shutil.copy(work, path)   # leave it refilled
    narrow = {}
    for uid, (t, w0) in old.items():
        if MM(t.GetWidth()) == w0:
            narrow[t.GetNetname()] = narrow.get(t.GetNetname(), 0) + 1
    print('still below class width:', narrow or 0)

if __name__ == '__main__':
    main()
