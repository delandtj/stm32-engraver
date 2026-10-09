#!/usr/bin/env bash
# Renders for the ADR 0005 acceptance set: whole board plus the USB, power
# and driver areas, into output/pcb/. Regions follow the parts, not fixed
# coordinates. Usage: tools/pcb5/render.sh [board.kicad_pcb]
set -euo pipefail
PK=${PCBKIT:-$HOME/Electronics/pcbkit}/bin/pcbkit
B=${1:-graver-controller.kicad_pcb}
RPT=output/pcb/drc.rpt
mkdir -p output/pcb
python3 - "$B" <<'PY' | while read -r name x0 y0 x1 y1 nets; do
    echo "render $name ($x0 $y0 $x1 $y1) $nets"
    # shellcheck disable=SC2086
    $PK render "$B" "output/pcb/$name.png" "$x0" "$y0" "$x1" "$y1" ${RPT:+--rpt $RPT} $nets 2>&1 | grep -v property.h || true
done
import sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1]); mm = pcbnew.ToMM
bb = b.GetBoardEdgesBoundingBox()
X0, Y0, X1, Y1 = mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())
def region(refs, m=3.0):
    xs, ys = [], []
    for r in refs:
        f = b.FindFootprintByReference(r); c = f.GetBoundingBox(False, False)
        xs += [mm(c.GetLeft()), mm(c.GetRight())]; ys += [mm(c.GetTop()), mm(c.GetBottom())]
    return (max(X0, min(xs) - m), max(Y0, min(ys) - m), min(X1, max(xs) + m), min(Y1, max(ys) + m))
print('board', X0, Y0, X1, Y1, '')
print('usb', *region(['J301', 'U302', 'U301']), '/MCU/USB_DP /MCU/USB_DM')
print('power', *region(['J101', 'F101', 'Q101', 'C101', 'U101', 'L101', 'U102']), 'VIN +5V Net-(U101-SW)')
print('driver', *region(['J201', 'Q201', 'D201', 'D202', 'U201', 'U202', 'R204']), 'VIN /Driver/COIL_NEG /Driver/CLAMP /Driver/SHUNT_HI')
PY
