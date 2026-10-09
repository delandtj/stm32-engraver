#!/usr/bin/env bash
# ADR 0005 board pipeline for graver-controller (4-layer, pcbkit). Run from
# Hardware/graver-controller. Each stage is a separate command so a step can
# be repeated on its own; the committed .kicad_pcb is the artifact.
#
#   tools/pcb5/build.sh board     # netlist -> mkboard -> outline -> setrules -> place
#   tools/pcb5/build.sh route     # krt-route (slow), then viaout, inner-layer cleanup
#   tools/pcb5/build.sh finish    # gndpour -> DRC -> prune -> silk -> connlabels -> refill
#   tools/pcb5/build.sh check     # DRC + tools/pcb5/check.py + renders
#   tools/pcb5/build.sh fab       # jlcfab -> fab/
#
# pcbnew Save rewrites the .kicad_pro next to the file it saves, so every
# pcbnew step writes to $SCRATCH and only the .kicad_pcb is copied back.
set -euo pipefail
PK=${PCBKIT:-$HOME/Electronics/pcbkit}/bin/pcbkit
N=graver-controller
SCRATCH=${SCRATCH:-${XDG_RUNTIME_DIR:-/tmp}/graver-pcb5}
mkdir -p "$SCRATCH" output/pcb
step() { echo "== $*"; }
drc() { kicad-cli pcb drc --schematic-parity --severity-all --refill-zones --save-board \
            -o "$SCRATCH/drc.rpt" "$1" 2>&1 | grep -v property.h | tail -3; }

case "${1:-}" in
board)
    step netlist; kicad-cli sch export netlist --format kicadxml -o "$SCRATCH/net.xml" $N.kicad_sch
    step mkboard; $PK mkboard "$SCRATCH/net.xml" . "$SCRATCH/mk.kicad_pcb"
    step outline; $PK outline "$SCRATCH/mk.kicad_pcb" "$SCRATCH/ol.kicad_pcb"
    cp "$SCRATCH/ol.kicad_pcb" $N.kicad_pcb
    step setrules; $PK setrules $N.kicad_pcb $N.kicad_pro
    step place; python3 tools/pcb5/place.py
    ;;
route)
    step krt-route; $PK krt-route
    step viaout; $PK viaout $N.kicad_pcb "$SCRATCH/vo.kicad_pcb" && cp "$SCRATCH/vo.kicad_pcb" $N.kicad_pcb
    step inner-cleanup; python3 tools/pcb5/postroute.py
    ;;
finish)
    step gndpour; $PK gndpour $N.kicad_pcb "$SCRATCH/gp.kicad_pcb" && cp "$SCRATCH/gp.kicad_pcb" $N.kicad_pcb
    step drc; drc $N.kicad_pcb
    step prune; $PK prune $N.kicad_pcb "$SCRATCH/drc.rpt"
    step silk; $PK silk $N.kicad_pcb "$SCRATCH/sk.kicad_pcb" && cp "$SCRATCH/sk.kicad_pcb" $N.kicad_pcb
    step connlabels; $PK connlabels $N.kicad_pcb "$SCRATCH/cl.kicad_pcb" && cp "$SCRATCH/cl.kicad_pcb" $N.kicad_pcb
    step refill; drc $N.kicad_pcb
    ;;
check)
    step drc; drc $N.kicad_pcb; cp "$SCRATCH/drc.rpt" output/pcb/drc.rpt
    step check; python3 tools/pcb5/check.py $N.kicad_pcb --rpt output/pcb/drc.rpt
    step render; tools/pcb5/render.sh
    ;;
fab)
    step jlcfab; $PK jlcfab $N.kicad_pcb fab
    ;;
*) sed -n 2,14p "$0"; exit 1 ;;
esac
