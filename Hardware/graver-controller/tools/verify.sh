#!/bin/sh
# Prove the regenerated sheets still describe the verified circuit:
#   1. XML netlist of the live project == netlist of tools/ref (parts, values,
#      footprints, LCSC, nets)   2. ERC   3. PNG renders for eyeballing.
# Usage: tools/verify.sh [outdir]
set -u
STATUS=0
HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$(dirname "$HERE")
OUT=${1:-$PROJ/output/verify}
mkdir -p "$OUT"

kicad-cli sch export netlist --format kicadxml -o "$OUT/ref.xml" "$HERE/ref/graver-controller.kicad_sch" >/dev/null
kicad-cli sch export netlist --format kicadxml -o "$OUT/new.xml" "$PROJ/graver-controller.kicad_sch" >/dev/null
python3 - "$OUT/ref.xml" "$OUT/new.xml" <<'EOF'
import sys, xml.etree.ElementTree as ET
def norm(path):
    r = ET.parse(path).getroot()
    out = []
    for c in r.find('components'):
        f = {x.get('name'): (x.text or '') for x in c.iter('field')}
        out.append('COMP %s | %s | %s | LCSC=%s' % (c.get('ref'), c.findtext('value'),
                   c.findtext('footprint'), f.get('LCSC', '')))
    for n in r.find('nets'):
        pins = sorted('%s.%s' % (p.get('ref'), p.get('pin')) for p in n.iter('node'))
        if len(pins) < 2:
            continue
        # nets are compared by their pin set; the name is informational only
        out.append('NET ' + ' '.join(pins))
    return sorted(out)
a, b = norm(sys.argv[1]), norm(sys.argv[2])
sa, sb = set(a), set(b)
if sa == sb:
    print('NETLIST OK: %d components, %d nets identical' % (
        sum(1 for x in a if x.startswith('COMP')), sum(1 for x in a if x.startswith('NET'))))
else:
    for x in sorted(sa - sb):
        print('- ' + x)
    for x in sorted(sb - sa):
        print('+ ' + x)
    print('NETLIST MISMATCH')
    sys.exit(1)
EOF
[ $? -eq 0 ] || STATUS=1

kicad-cli sch erc -o "$OUT/erc.rpt" "$PROJ/graver-controller.kicad_sch" | grep -i 'violation' || true
grep -E '^\[' "$OUT/erc.rpt" | sort | uniq -c || true

kicad-cli sch export svg -o "$OUT" "$PROJ/graver-controller.kicad_sch" >/dev/null
for f in "$OUT"/graver-controller-*.svg; do
    rsvg-convert -b white -w 2400 "$f" -o "${f%.svg}.png"
done
echo "renders in $OUT"
exit $STATUS
