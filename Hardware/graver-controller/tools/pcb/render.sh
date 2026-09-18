#!/usr/bin/env bash
# Render the placed board to PNG for review. No GUI, no routing.
#
#   tools/pcb/render.sh
#
# Writes into output/pcb/ (gitignored):
#   placement.png  bodies + courtyards + outline - the view to judge placement
#   copper.png     F.Cu + outline, nothing else
#   silk.png       what the finished top side will look like
#   critical.png   the speed/loop-critical nets as straight lines
#
# The page (not the board area) is plotted and then cropped with a margin, so
# the rear connectors' intended overhang past the edge stays visible. Plotting
# "board area only" clips it and the board looks flush when it is not.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
proj="$(cd "$here/../.." && pwd)"
pcb="$proj/graver-controller.kicad_pcb"
out="$proj/output/pcb"

# must match ORIGIN / BOARD_W / BOARD_H in place.py
ox=50; oy=50; bw=110; bh=70; margin=8
page_w=297                      # A4 landscape, the default kicad-cli page
pxmm="${PXMM:-18}"              # output pixels per board mm

mkdir -p "$out"
page_px=$(python3 -c "print(int($page_w*$pxmm))")
crop=$(python3 -c "print('%dx%d+%d+%d' % (
    ($bw+2*$margin)*$pxmm, ($bh+2*$margin)*$pxmm,
    ($ox-$margin)*$pxmm, ($oy-$margin)*$pxmm))")

render() {
    local name="$1" layers="$2" src="${3:-$pcb}"
    kicad-cli pcb export svg \
        --layers "$layers" \
        --page-size-mode 1 \
        --exclude-drawing-sheet \
        --mode-single \
        -o "$out/$name.svg" "$src" >/dev/null
    rsvg-convert -b white -w "$page_px" -o "$out/$name.full.png" "$out/$name.svg"
    magick "$out/$name.full.png" -crop "$crop" +repage "$out/$name.png"
    rm -f "$out/$name.full.png"
    echo "$out/$name.png"
}

render placement "F.Fab,F.Courtyard,Edge.Cuts"
render copper "F.Cu,Edge.Cuts"
render silk "F.Silkscreen,F.Cu,Edge.Cuts"
# the scripted copper (copper.py): each layer on its own and both over F.Fab
render top "F.Cu,User.2,Edge.Cuts"
render bottom "B.Cu,User.2,Edge.Cuts"
render both "B.Cu,F.Cu,F.Fab,Edge.Cuts"
# the critical nets as straight lines, from the review-only copy place.py
# writes alongside the board (User.1 is not in the committed .kicad_pcb)
if [ -f "$out/critical.kicad_pcb" ]; then
    render critical "F.Fab,User.1,Edge.Cuts" "$out/critical.kicad_pcb"
fi

# Zoom crops off the placement view, for reviewing one block at a time.
zoom() {   # name x_mm y_mm w_mm h_mm
    local name="$1"
    local geo
    geo=$(python3 -c "print('%dx%d+%d+%d' % (
        $4*$pxmm, $5*$pxmm, ($2+$margin)*$pxmm, ($3+$margin)*$pxmm))")
    magick "$out/placement.png" -crop "$geo" +repage -resize 1600x "$out/$name.png"
    echo "$out/$name.png"
}
zoom zoom-rear   0  0 110 30
zoom zoom-mcu   30 20  40 35
zoom zoom-power  0 12  36 50
zoom zoom-driver 48 10  52 30

# Crops off the copper views, for reviewing the scripted copper block by
# block: stubs colliding, vias on pads, the guard ring crossing a trace.
czoom() {   # name source x_mm y_mm w_mm h_mm
    local name="$1" src="$2"
    local geo
    geo=$(python3 -c "print('%dx%d+%d+%d' % (
        $5*$pxmm, $6*$pxmm, ($3+$margin)*$pxmm, ($4+$margin)*$pxmm))")
    magick "$out/$src.png" -crop "$geo" +repage -resize 1600x "$out/$name.png"
    echo "$out/$name.png"
}
czoom cu-qfn    top  38 30  20 22
czoom cu-xtal   top  41 40  16 12
czoom cu-usb    top  22  0  24 32
czoom cu-driver top  48  8  32 26
czoom cu-buck   top   2 38  36 26
