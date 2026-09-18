# tools/pcb - board generation, placement, the scripted copper and the silk

Scripted placement, scripted critical copper and a scripted silkscreen for
`graver-controller.kicad_pcb`, per ADR 0003 decision 8. Placement is data in
`place.py`, which regenerates the whole board from the schematic every run;
the critical copper is data in `copper.py`, which draws it on top of that and
locks it; the silkscreen is `silk.py`, which searches rather than tabulates.
None of them routes the rest.

## Run it

    cd Hardware/graver-controller
    python3 tools/pcb/place.py          # rebuild + place + check
    python3 tools/pcb/copper.py         # zones, keepouts, critical copper
    python3 tools/pcb/silk.py           # references, connector labels, title
    python3 tools/pcb/autoroute.py      # route the rest, grade it, import it
    tools/pcb/render.sh                 # PNGs into output/pcb/

or in one go:

    python3 tools/pcb/place.py --copper --silk --route

`place.py`, `copper.py` and `silk.py` need plain `python3` with the system
KiCad 10 `pcbnew` bindings - no venv, no extra packages. `autoroute.py` also
needs the KiCadRoutingTools checkout and its venv (see "Routing the rest").
`place.py` exits non-zero if any placement check or ADR distance criterion
fails, and prints a table of every criterion with its measured value.

`--no-netlist` skips the `kicad-cli sch export netlist` step and reuses
`output/pcb/netlist.xml`. Use it while iterating on placement numbers.

Verify independently with:

    kicad-cli pcb drc --schematic-parity --severity-all graver-controller.kicad_pcb

Expected after `place.py` alone: 0 schematic parity issues, ~250 unconnected
items, and silkscreen warnings. After `copper.py`: 0 errors, 0 parity, 101
unconnected items. After `silk.py`: no silkscreen warnings at all. After
`autoroute.py`: 0 errors, 0 parity, 13 unconnected items. See "Known DRC
output" below.

## What it does

1. Exports the kicadxml netlist into `output/pcb/`.
2. Builds a board from all 117 components. Every footprint is linked back to
   its symbol with a KIID path `/<sheet uuid>/<symbol uuid>` taken from the
   netlist, and carries sheetname, sheetfile, Value, LCSC, MPN, Datasheet and
   Description, plus the `in_bom` / `dnp` flags read out of the `.kicad_sch`
   files. That is what makes "Update PCB from schematic" in the GUI a no-op.
3. Draws the 110 x 70 mm outline with 2 mm corner radii on Edge.Cuts and sets
   the aux and grid origin to the board's top-left corner at page (50, 50).
4. Places everything, checks it, and saves.

Orientation is KiCad top view: rear edge (connectors) at y = 0, front edge at
y = 70, x = 0 at the left as the seated user sees the console.

## How to nudge a part

Everything is in a handful of tables near the top of `place.py`.

- `EDGE_PARTS` - the four rear connectors: `(x, rotation, out_axis,
  overhang)`. Only `x` and `overhang` are normally worth changing; the script
  slides each part along y itself so the mating face lands `overhang` mm past
  the rear edge.
- `ANCHORS` - one entry per block, `(anchor_x, anchor_y)` plus rows of
  `(ref, dx, dy, rotation)`. Move a whole block by editing its anchor.
- `DECAPS` and `SATELLITES` - `(host pad, own pin, out, side)`. The part is
  put on the outward normal of the host pin, `out` mm away and `side` mm
  across. Two caps flanking one pin is `side = -1.5` and `side = +1.5`. The
  named pin is aimed at the host automatically: all four rotations are tried
  and the one that puts that pad nearest the host pad wins.
- `MCU_LINKS` / `MCU_SEARCH_X` / `MCU_SEARCH_Y` / `MCU_HALO` - the MCU pose
  search (below). `MCU_REFERENCE_POSE` is only there so the run prints how the
  winner compares with the first pass's hand-picked pose.
- `FLYBACK_CANDIDATES` - named arrangements for the clamp corner. The script
  tries each, scores it by clamp-loop perimeter, and keeps the best; add a
  candidate rather than editing the winner.
- `XTAL_ISLAND` - the crystal and its two load caps as offsets `(along the QFN
  edge, outward, rotation)`. They are placed as one RIGID group, and the
  rotation is DICTATED rather than searched: which of the crystal's four pads
  faces the MCU decides whether the two oscillator legs can be drawn at all,
  which a distance search cannot see. See "The crystal island lives in the
  corner" below.
- `KELVIN_TAPS` and `OPAMP_WEST` - two more rigid groups, R209/R213 off the
  shunt's sense pad and R210/C204/R211 off the op-amp's pin 1. Both were
  satellites in the second pass and both got thrown 12-16 mm away by the row
  search; see "The analog corner is placed, not resolved" below.
- `GROUP_SEED` / `GROUP_OVERRIDE` - which parts start a function group.
  Satellites inherit their host's group, and `COURTYARD_GAP` (0.5 mm) applies
  only between different groups; inside a group it is `GROUP_GAP` (0.15 mm).
  That is what lets a decoupling cap sit against its IC while unrelated blocks
  stay half a millimetre apart.

### MCU pose by search

The MCU plus everything that must sit at its pins is treated as one rigid
cluster. `place.py` places every block whose position does NOT depend on the
MCU first (rear connectors, power, driver, buttons, front furniture), then
scores all four rotations over a 2 mm grid in x 34..70 / y 24..48, rejecting
any pose whose `MCU_HALO` ring is not clear or that comes within 15 mm of the
buck. The score is a weighted sum of straight-line distances from MCU pads to
the fixed parts they have to reach: USB 3, LCD and the driver signals 2,
pedal/NTC/VIN_SENSE 1.5, encoder and SWD/NRST/BOOT0 1. The run prints the top
five poses, the per-link distances and the comparison with the first pass.

Every placement is snapped to a 0.5 mm grid (0.25 mm for the MCU decoupling)
and then spiral-searched outwards until its courtyard is clear, so a seed that
collides still lands somewhere sane - the script prints every nudge it made.
If you see a part nudged by more than about 2 mm, its table entry is wrong,
not the resolver.

`CRITERIA` holds the ADR distance rules that get measured and printed.
`WATCH_NETS` holds the nets whose ratsnest length (MST over the pads) is
printed every run - use it to tell whether a nudge helped.

## Rules

- **The autorouter never runs on these files.** ADR 0003 risk "Autorouter
  rewrites the rules": KiCadRoutingTools relaxes the minimums in the sibling
  `.kicad_pro` to whatever it managed to build and then grades itself against
  them. Copy the project elsewhere, run it there with `--escalation off
  --strict-sizes`, and grade only with `kicad-cli pcb drc` against the
  committed `.kicad_pro`.
- **`graver-controller.kicad_pro` is a committed file and must not move.**
  `pcbnew.SaveBoard` rewrites it as a side effect, so `place.py` snapshots it
  before saving and restores it afterwards, printing which of the two
  happened. If a run ever reports the project as changed and not restored,
  that is a bug - do not commit the result.
- `graver-controller.kicad_pcb` is derived. Until routing starts, do not hand
  edit it; change `place.py` and re-run. Once Jan starts routing, this script
  stops being safe to re-run and the board becomes the source of truth.

## Connector orientation

Each right-angle connector's mating direction was read off its own footprint
geometry rather than guessed:

| ref  | footprint evidence | local face | rot | overhang |
|------|--------------------|-----------|-----|----------|
| J101 | F.Fab -13.7..0.8 in x with a flange line at -10.2; the 3.5 mm beyond it is the barrel nose | -x | 270 | 3.5 mm |
| J301 | F.Fab body -3.65..3.65 in y, contact tails at y = -4.045 behind it | +y | 180 | 0.5 mm |
| J201 | silkscreen draws four wire-entry funnels at y = 8.61..10.11, one per contact | +y | 180 | 0 mm |
| J402 | F.Fab body ends at x = 16.7 with the 3 mm chrome ferrule out to 19.7 | +x | 90 | 3.0 mm |

Rotation 180 is **forced** for J201: the four wire-entry funnels are drawn on
its +y side, so nothing else points them out of the rear edge. That reverses
the pin order on the board. Seen from the front, left to right:

| board x | pin | net |
|---------|-----|-----|
| 54.26 | 4 | GND |
| 59.34 | 3 | NTC |
| 64.42 | 2 | COIL_NEG |
| 69.50 | 1 | VIN |

The silkscreen legend and the GX12 pigtail wiring both have to follow that
order, not the schematic's.

J302 (SWD) lies **along** the rear edge at rotation 90, pin 1 at x = 37.0 and
pin 5 at x = 47.16, all at y = 2.5. It fits there because J301 moved 3 mm left
(x 32.0 -> 29.0); at rotation 0 it stuck 14 mm down into the MCU's rear side.

## Known DRC output

`kicad-cli pcb drc --schematic-parity --severity-all` on the finished board -
placement, scripted copper, scripted silk and the router's copper:

| type | after copper + silk | after autoroute.py | why |
|------|--------------------|--------------------|-----|
| schematic parity | 0 | 0 | clean |
| errors | 0 | 0 | clean |
| unconnected_items | 101 | 13 | see "Routing the rest" for the eight nets |
| silk_overlap | 0 | 0 | was 92 before `silk.py` |
| silk_over_copper | 0 | 0 | was 92 |
| silk_edge_clearance | 0 | 0 | was 17 |
| lib_footprint_mismatch | 4 | 4 | J101, J201, J301, J402 - `silk.py` trims their library silkscreen back to the board outline, see "Silkscreen" below |
| track_dangling | 18 | 9 | QFN fanout stubs whose net the router never reached |
| via_dangling | 7 | 3 | fanout and stitching vias the router never reached |

226 warnings before the silk pass, 29 after, 16 once the router's copper is
in: the 12 remaining deliberate dangling ends plus the 4 trimmed connectors.

The assembly view instead gets its labels from F.Fab: `place.py` hides every
footprint's **Value** field (it was the "100nF 100V" text that buried
`placement.png`) and scales each footprint's F.Fab `${REFERENCE}` to fit the
body it sits in, which the library gets backwards - 0.4 mm on an 0603 and
1.0 mm on a QFN.

## Copper

`copper.py` draws the scripted, locked critical copper ADR 0003 decision 8
calls for. It runs after `place.py` and is idempotent: everything it makes
goes into a PCB group named `scripted-copper`, and the first thing a run does
is delete that group's members, so re-running replaces the copper instead of
stacking it. Every item it makes is **locked**, which is what keeps the
autorouter off it - KiCadRoutingTools refuses to rip KiCad-locked copper.

    python3 tools/pcb/copper.py              # draw + refill + DRC
    python3 tools/pcb/copper.py --no-drc     # skip the kicad-cli DRC step
    python3 tools/pcb/copper.py --no-refill  # skip the zone fill

Like `place.py` it snapshots `graver-controller.kicad_pro` before saving and
restores it afterwards, and prints which of the two happened.

### What is scripted and locked

| # | what | numbers |
|---|------|---------|
| 1 | GND pour on B.Cu over the whole outline | 0.25 mm clearance, 0.20 mm min width, thermal reliefs on THT, solid on SMD |
| 1 | four ground-free rule areas at the M3 holes | 6 mm diameter, both layers, no pour; User.2 copies for `--keepout` |
| 1 | crystal keepout over Y301/C310/C311 | rule area = no vias both layers; User.2 copy = no router tracks; the pour is kept (ADR: ground guard, no signal under it) |
| 2 | U301 QFN fanout | 0.20 mm radial stubs on 21 pads, 0.56-1.11 mm of new copper past each pad edge; 4 vias 0.6/0.3 at 1.55 mm on pads 18/20/42/44; a 0.97 mm same-net jumper on pad 1 and a 6.56 mm channel lane + via on pad 2, the two the island shadows |
| 2 | U301 GND pins 8/23/35/47 | 0.20 mm, 0.64 mm into the EP copper |
| 2 | U301 EP | 4 vias 0.6/0.3 inside the pad |
| 3 | decoupling | 13 pin-to-cap traces on F.Cu; 61 of 63 SMD ground pads get their own via into the pour |
| 3 | U101 PowerPAD | 4 thermal vias 0.6/0.3 |
| 4 | crystal | OSC_IN 6.33 mm, OSC_OUT 7.23 mm (both including the load-cap tap), F.Cu only, 0 vias; F.Cu ground guard bracket, 3 of 3 legs + 2 stitching vias |
| 5 | VDDA | FB301 -> C306/C307 at 0.40 mm; pin 9 -> C306 is now a 2.5 mm radial escape, left to the router on this pose (see below) |
| 6 | USB | D+ 37.88 mm, D- 37.88 mm, skew 0.00 mm, **0 vias on either net**; 17 User.2 bands 0.15 mm off the centre line so the router cannot cross under the pair on B.Cu |
| 7 | power | VIN chain 0.8 mm, flyback loop 1.0 mm, gate 0.4 mm, shunt 1.0 mm, Kelvin taps 0.2 mm off the shunt pad's own copper edge, buck, +5 V/+3V3 0.5 mm; sense-side ground tree 0.20/0.25 mm |
| 8 | ADC filters | the RC parts at the MCU pins, 0.25 mm, only where the part is within 6.5 mm |

### Budgets, and how they came out

| budget | source | measured |
|--------|--------|----------|
| USB pair <= 40 mm, 0 vias, <= 1 mm skew | ADR 0003 component breakdown 3 | 37.88 / 37.88 mm, 0 vias, 0.00 mm skew - PASS with 2.1 mm of margin. The U302 -> MCU legs are octilinear now instead of L-shaped, which is worth 4.7 mm each and is what absorbed the MCU moving 4 mm back from the receptacle to make room for the Kelvin taps |
| USB coupled 0.2 mm / 0.15 mm | ADR + Jan 2026-09-18 | 0.15 mm gap on the long connector segment; 0.30 mm on the two U302 -> MCU lanes, which U302's own 1.9 mm pin pitch forces |
| flyback loop closed within ~15 mm | ADR decision 4 | 20.26 mm of real copper over its four legs, parts inside a 10 x 12 mm block under the terminal |
| buck CIN within 3 mm of the VIN pin | ADR component breakdown 2 | 2.88 / 2.74 mm pad to pad, 6.95 mm of copper |
| crystal keepout clean | ADR decision 8 | clean: only OSC_IN, OSC_OUT and the ground guard are inside it (VDDA no longer needs to be) |
| shunt is the single ground tie of the sense side | ADR decision 4 | CHECKED, row per pad, and the run exits non-zero on a FAIL: C204.2, R211.2, R216.2, C206.2 and U202.4 each reach R204 pad 2 over scripted F.Cu with no via of their own, and R204 pad 2 carries the 2-via cluster that is the sense side's only path into the pour. C203.2 and C205.2 are deliberately NOT in that set - see below |
| VIN 0 vias | this brief | the long VIN link is NOT scripted - see below |
| flyback loop perimeter | ADR | 20.26 mm; buck CIN 6.95 mm; OSC_IN 6.33 mm, OSC_OUT 7.23 mm |
| Kelvin traces from the shunt PADS to the op-amp | ADR component breakdown 4 | 1.15 mm and 1.23 mm of bare laminate between R204's sense pad and each tap's own pad, 0.20 mm traces drawn from the pad EDGE, not from the 1.0 mm power trace |

### How the geometry is made

Explicit straight and 45-degree segments computed from real pad positions.
Every candidate path - two-segment octilinear, then three-segment detours at
22 perpendicular offsets - is clearance-checked against every pad, every
piece of copper already drawn, the board edge and the keepouts BEFORE it is
committed, at the pairwise net-class clearance read out of the committed
`.kicad_pro` (Default 0.15, Power 0.2, HighCurrent 0.4). A path that cannot
be made to clear is **reported, not drawn**: the run prints a
"COULD NOT DRAW" list and those nets are left to the router.

Order matters and is deliberate: the crystal island and the VDDA lane inside
it have exactly one way out each, so they claim their space first; the ground
stitching runs last, because its stubs would otherwise close escape routes a
signal needed.

### The crystal island lives in the corner, and two pads pay for it

Third pass. The island used to sit in front of pads 5-12 and leave a 0.51 mm
channel - one 0.20 mm trace, which VDDA needed - so pad 7 (NRST), pad 11
(PEDAL_TIP) and pad 12 (PEDAL_RING) had no escape at all. It now sits in the
corner at the LOW pin numbers, where the pads it covers are pad 1 (VBAT), pad
2 (PC13, the status LED), pads 3 and 4 (unconnected on this design) and the two
OSC pins that want to be there anyway. Pads 7-12 get plain radial stubs and
their first-ring parts: NRST's cap is 2.05 mm from pin 7 and VDDA's 1 uF
2.50 mm from pin 9, both of which used to be 6-8 mm out and advisory.

Three things had to be true at once, and none of them is a distance:

- **The crystal's rotation, not its distance.** At 270 degrees the 3225 puts
  XIN on its near-west pad and XOUT on its far-east one, which is the only one
  of the four rotations where OSC_IN is both nearest the MCU and west of
  OSC_OUT - the order pads 5 and 6 come in. At 0 degrees (second pass) XIN is
  the far south-west pad with a GND pad directly north of it, and the only way
  in is the crystal's own 0.8 mm centre slot, which OSC_OUT's load cap needs
  too. The old flip search scored distance and could not see this, so
  `XTAL_ISLAND` now carries the rotation and the search is gone.
- **The load caps go outside the crystal, not between it and the MCU.** One
  west of it, one behind it, both standing on end, so the face the QFN sees is
  the crystal's own 2.9 mm of pads and nothing wider. Each cap is 1.7 mm from
  the crystal pin it damps.
- **The corner has to be free when the island is placed.** The escape annulus
  reserved a 3 mm band on three sides INCLUDING the corners of the crystal's
  side, and a cap parked at pad 1 was placed before the island and took the
  rest. So the two bands perpendicular to the crystal's side are clipped back
  to the courtyard there, and C301 is pushed 3.25 mm along the pin row to sit
  against C304, pad 48's own 100 nF. That costs C301's 2 mm criterion (2.93 mm,
  advisory): pad 1 is VBAT, tied to VDD on a part with no battery, and it also
  gets a 0.97 mm jumper to pad 48 so it is decoupled by C304 whatever happens.

What is left is a 1.03 mm channel between the pin-row copper and the island's
keepout - two 0.20 mm lanes at 0.21 mm, not one. The outer lane carries OSC_IN
across to XIN; the inner one carries LED_STAT out past the island's west flank
to a via at (37.94, 48.19), which is a real escape on B.Cu clear of the
keepout rather than a stub that dies against the island. OSC_OUT never enters
the channel: it leaves pad 6 straight out, 0.20 mm clear of the crystal's near
GND pad and 0.30 mm clear of pad 7's stub, and turns once into XOUT.

`copper.py` works out which pads the island shadows from the real geometry
(a pad whose radial stub cannot be drawn, on the island's side of the part)
and gives each one a same-net jumper if one is available and a channel lane
plus a via if not. There is no hand-written list of shadowed pads any more.

### The analog corner is placed, not resolved

Three rigid groups now, for the same reason the crystal island is one: the
satellite resolver walks a row outward from a host pad, and when the first
ring is full it keeps walking. In the second pass that put R209 and R213 - the
shunt's Kelvin taps - 12.5 mm away on the far side of the op-amp, because pad
1's outward normal points east straight into Q201's 11 mm DPAK courtyard.

- `KELVIN_TAPS`: R209 flat and R213 on end, 2.5 and 3.25 mm south of R204's
  sense pad, which is the floor (the 1206's courtyard reaches 1.175 mm south
  of its pad centre, group air is 0.15 mm, and an 0603 is 0.775 mm half
  height lying down). That leaves 1.15 mm and 1.23 mm of bare laminate
  between the shunt pad's copper and each tap's own pad. The centre-to-centre
  figure cannot be under 2 mm with a 1206 and an 0603, so the criteria table
  measures the copper EDGES.
  R213 stands on end rather than lying beside R209 because flat it is 3.05 mm
  wide and its far pad lands on x 51.5-52.3 - the only lane between the MCU's
  east fanout vias and the shunt, which the sense-side ground trunk needs.
- `OPAMP_WEST`: R210, C204 and R211 down the column at U202's west pads, on
  end, 3.6 mm apart. The 3.6 is 0.4 mm more than they need: it leaves 1.1 mm
  between each pair of pads, and the ground trunk crosses this column.
- U202 itself moved from 5.0 to 7.0 mm off the shunt's sense pad. At 5.0 the
  Kelvin taps and the op-amp between them left a column one part wide and
  R210 and R211 ended up 12-14 mm north, next to the handpiece terminal. The
  ADR limit is 10 mm part to part; it is 4.47 mm.

The taps are why the MCU sits 4 mm further from the USB receptacle than in the
second pass: they are inside its 5 mm halo at every closer pose, the halo
check is what makes the pose legal, and the Kelvin requirement is an ADR one
while the pose is not. The USB pair paid for it in the copper instead, by
going octilinear.

### The sense-side ground is a checked tree, not a star

ADR 0003 decision 4 says the sense side of R204 joins the pour only at the
shunt. `copper.py` draws the trunk from U202 pin 4 to R204's ground pad first
and then chains each remaining sense pad to whichever pad is already on the
trunk and nearest to it. A star at pin 4 asked the OC_REF pads, which sit on
the op-amp's east face, to go right round the part; chained, each hop is a
couple of millimetres. When the ordinary two-segment search fails, `zroute`
SCANS the middle line of a Z-shaped path in 0.05 mm steps - the lanes through
the feedback column and between the two Kelvin taps are about 1.1 mm and
0.8 mm wide and the offset that works is not on any fixed ladder.

It is then CHECKED, pad by pad, by walking the copper the run actually drew:
`sense_ground_table` builds a graph of the scripted F.Cu GND segments, finds
which of them land on each pad, and asks whether the pad reaches R204's ground
pad through that graph and whether any scripted via sits in its copper. The
run exits non-zero if a row fails. All five rows pass.

**C203.2 and C205.2 are deliberately not in that set.** C203 is the op-amp's
+3V3 bypass: its ground carries the supply's return current, not a
measurement, and tying it to the single point instead of to the plane directly
under it turns 15 mm of 0.20 mm trace around the op-amp into the bypass's
return path - worse for the op-amp than the thing the rule protects against.
C205 is the I_SENSE RC cap at the MCU pin, 20 mm away at the other end of the
board. Both take an ordinary stitching via.

### The USB-C's reversible duplicate contacts

The HRO TYPE-C-31-M-12 brings D+ out on A6 **and** B6 and D- on A7 **and**
B7, and on this footprint the four sit on one row, interleaved:
B6 28.25 | A7 28.75 | A6 29.25 | B7 29.75. Both duplicate pairs have to be
bridged and each bridge has to cross the other net.

The run therefore leaves from **B6 (D+) and A7 (D-)** - adjacent, and with
D+ on the low-x side, which is the order U302 (rotated 180 degrees by
`place.py`) and the MCU both want, so the pair never swaps sides. Both
duplicates then sit east of the run, and the two bridges can use opposite
sides of the pad row: D+ A6 <-> B6 3.39 mm **in front** of the pads, where A7
has no copper, and D- B7 <-> A7 3.06 mm **behind** them, where A6 has none.
That is why the whole USB section has **zero vias**. Take the run from A7/A6
instead and both bridges have to go behind, which four interleaved contacts
cannot do in one plane - it costs two vias and about 4 mm of B.Cu slot under
the connector, right under the pair's own reference.

Both legs turn 45 degrees at the same y (`USB_TURN_Y` = 13.4, the minimum
that keeps the diagonals clear of R305's pads and SW302's), which makes the
two diagonals automatically 0.354 mm apart - the 0.2 mm / 0.15 mm pair.
`place.py` puts R305 (CC1) east of the pair and R306 (CC2) west of it, one on
each side, so neither pull-down crosses it.

### Fanout vias are zero-sum at 0.5 mm pitch

`QFN_VIA_PADS` in `copper.py` is the list of pads that get a via at the end
of a longer stub. The geometry is hard: at 0.5 mm pitch a 0.6 mm via has to
sit **1.43 mm or more** out of the pad centre to keep 0.15 mm from a
neighbouring 1.15 mm stub's end cap, two vias need 0.75 mm of copper and
0.80 mm of hole-to-hole between them - so at most every second pad of a row -
and the via then denies BOTH its neighbours any radial escape past about
1.15 mm, because a 0.25 mm trace 0.5 mm to the side of it clears by 0.50 mm
where it needs 0.575 mm.

Measured, that is a wash. Adding vias on pads 18/20/42/44 closed VIN_SENSE,
Net-(U301-PB2), LCD_BL and Net-(U301-BOOT0), and opened ENC_SW, LED_STAT,
LCD_DC and PEDAL_RING: still 7 open nets, 9 unconnected items instead of 10.
The four are kept because the count is marginally better and because the two
ADC nets among them are the ones a via harms least, but **more of them will
not help**. What is left is second-ring congestion, not fanout.

### Nothing routed by the tool is imported without a kicad-cli grade

The autorouter never runs on a repo file, and no track it produces is copied
into `graver-controller.kicad_pcb` unless `kicad-cli pcb drc` against the
**committed** `.kicad_pro` passes on the routed copy and the net meets a
stated budget. In this pass no router output was imported at all: the one
candidate, the long VIN link, cannot be via-free (see below), so it was not
taken.

### What is left for the router, and the exact command

After `copper.py` the board has 101 unconnected pad pairs over 49 nets -
the GPIO, SPI, UI and long power links ADR 0003 decision 8 hands to
KiCadRoutingTools. Run it on a **copy**, never on the repo:

    tools/pcb/routability.sh after

which copies the board and the project outside the repo, detects that
`copper.py` has already run (it looks for the `scripted-copper` group), skips
the plane pour and the diff-pair step because both are scripted, and calls

    route.py <copy> <out> --nets "*" \
        --track-width 0.2 --clearance 0.15 --via-size 0.6 --via-drill 0.3 \
        --grid-step 0.05 --escalation off --strict-sizes --write-fill \
        --keepout --keepout-layer User.2 --keep-input-copper \
        --power-nets GND +3V3 +5V VBUS /MCU/VDDA VIN /Driver/COIL_NEG \
            /Driver/CLAMP /Driver/SHUNT_HI \
        --power-nets-widths 0.4 0.5 0.5 0.5 0.4 0.8 0.8 0.8 0.8

`--keepout` reads the User.2 polygons `copper.py` draws; `--keep-input-copper`
stops the cleanup passes rewriting the locked fanout stubs, whose far ends
are dangling on purpose. It then copies the pristine `.kicad_pro` back over
whatever the router wrote and grades only with `kicad-cli pcb drc`.

### The long VIN link is deliberately not scripted

VIN has to get from the bulk capacitor (x 12) to the terminal's pin 1
(x 69.5) and the USB pair has to get from the receptacle (x 28) to the MCU
(x 47): the two runs are opposite diagonals across the same rear half and
they cross. The reserved VIN corridor at y 14..17 is exactly where the pair
crosses it. Something has to change layer, and the ADR says the pair does
not ("no vias, over unbroken bottom ground"), so the pair is scripted
via-free and the VIN link is handed to the router with
`--power-nets-widths 0.8`.

What the router did with it, and what is committed: **VIN is 191.24 mm of
0.8 mm copper with 5 vias**. It is not via-free and on this placement it
cannot be - the rear edge has no second corridor - so the vias are the price
of keeping the USB pair via-free, which is the ADR requirement of the two.
None of them is under the pair: the pair is on F.Cu over unbroken B.Cu pour
for its whole 37.88 mm, checked by `autoroute.py` and enforced by the User.2
bands `copper.py` draws along it. The fix if Jan wants VIN flat is a
placement one (the DC jack and the terminal on the same side of the USB-C,
or the pedal jack's slot reused), not a routing one.

## Routing the rest

`autoroute.py` is the routing step. `routability.sh` is the placement test
and imports nothing; this one produces the copper that ships.

    cd Hardware/graver-controller
    python3 tools/pcb/autoroute.py            # route, grade, import, report
    python3 tools/pcb/autoroute.py --strip    # undo: remove it and refill
    python3 tools/pcb/place.py --copper --silk --route      # the whole board

It needs the KiCadRoutingTools checkout and its venv (`--system-site-packages`
plus numpy, scipy, shapely, Pillow, so `pcbnew` stays importable). Both are
found through `KRT_DIR` / `KRT_PY`, which default into the scratch directory
`PCB_SCRATCH` points at. The stage refuses to run if its work directory is
inside the git repository.

Options: `--strip`, `--no-import` (route and grade, touch nothing),
`--reuse` (grade and import the copy already routed), `--ordering NAME` (one
ordering instead of all four), `--first A,B,...`, `--nets ...`,
`--label NAME`, `--rip`, `--no-drc`.

### What the stage does

1. **Removes** the group `autorouted` from the board, refills the zones and
   saves. That is what makes it idempotent and what `--strip` stops after:
   the router's copper is never edited in place, it is thrown away and
   redone.
2. **Asks kicad-cli what is still open** on that stripped board. Those nets,
   minus `NO_ROUTE` and the auto-named `unconnected-*` ones, are the scope,
   and nothing outside the scope is ever imported.
3. **Routes a copy** outside the repository, in passes:
   - pass 1: the nets in `FIRST`, so the QFN escapes get first pick of the
     corridors;
   - pass 2: everything else, on pass 1's output;
   - up to two mop-up passes for whatever is still short, with
     `--rip-existing-nets '*'`.

   The whole chain is run once per entry in `ORDERINGS` (mps, inside_out,
   bus, original) and the best-scoring attempt is the one that gets imported.
4. **Grades** - see below.
5. **Imports** the surviving nets' tracks and vias into the repo board, not
   locked (they are the router's and regenerable) but grouped `autorouted`,
   and refills the zones with pcbnew's `ZONE_FILLER` so the pour closes round
   the new copper.
6. **Reports**: kicad-cli on the repo board, vias total and per net, the
   longest ten nets, the keepout check and the ADC-versus-switching
   parallel-run check.

The exact router call, per pass:

    route.py <in> <out> --nets <scope> \
        --track-width 0.2 --clearance 0.15 --via-size 0.6 --via-drill 0.3 \
        --grid-step 0.05 --escalation off --strict-sizes \
        --keepout --keepout-layer User.2 --keep-input-copper \
        --ordering <mps|inside_out|bus|original> \
        --power-nets GND +3V3 +5V VBUS /MCU/VDDA VIN /Driver/COIL_NEG \
            /Driver/CLAMP /Driver/SHUNT_HI \
        --power-nets-widths 0.4 0.5 0.5 0.5 0.5 0.8 0.8 0.8 0.8

The widths come out of the committed `.kicad_pro` net classes (Power 0.5,
HighCurrent 0.8); GND is a Default-class net and gets 0.4 because its job
here is the return path between two pour islands, not a signal. There is
**no `--write-fill`**: the pour is `copper.py`'s, and the router's own refill
of it does not apply the 0.25 mm hole clearance to J301's two NPTH pegs -
that is the pair of `hole_clearance` errors `routability.sh` has always
reported. The candidate board is filled by pcbnew instead, which does.

### The grading rule

The router's own pass messages are ignored, and so is `kicad-cli` on the
router's **output file**: its writer re-emits the GND pour, and a run that
routed nothing at all still graded 433 errors, all of them the zone. What is
graded is the board the stage **would commit**: the stripped repo board plus
the copper about to be imported, filled by `ZONE_FILLER`, with the pristine
`.kicad_pro` beside it. Nothing is written to the repo until that candidate
passes.

Four gates, in order, each of which only ever **removes** a net from the
import:

| gate | rule |
|------|------|
| size | a net with any track under 0.20 mm or any via under 0.6/0.3 is dropped whole. `--strict-sizes` is not enough: the tool's "net rescue" narrows a via to 0.45/0.20 and then writes the relaxed floor into the sibling `.kicad_pro` so its own check passes |
| complete | a net still showing an unconnected pad pair on the candidate is dropped whole; its partial copper is not worth the dangling ends |
| errors | every kicad-cli error whose items include a track or via of a net being imported takes that net out, one net at a time, **cheapest first** - a violation names two nets and dropping +3V3 to save GND costs twenty-one pad pairs to save two |
| final | any error left on the candidate refuses the whole import and the board is not written |

Imported copper is **not locked**. `copper.py`'s copper is, and that is what
keeps the router off it; the router's own copper is regenerable and the point
of the `autorouted` group is that step 1 can find it again.

### What never gets imported

- Anything on a net that was not already open before the run. The stage only
  ever adds copper, so a net the scripted copper finished is untouchable.
- The USB pair. `NO_ROUTE` holds `/MCU/USB_DP` and `/MCU/USB_DM`: ADR 0003
  wants them via-free and length-matched, `copper.py` draws them that way and
  locks them. The two pad pairs kicad-cli still counts on them are U302's own
  I/O pins - pads 3/4 on D+ and 1/6 on D-, which the ESD device's die joins
  and copper does not. No router can close those and none should try.
- `unconnected-(SW401-PadMP)`: two mounting pads of the encoder that KiCad
  lumps into one invented net. There is nothing to route between them.
- Zones. The stage imports tracks and vias only; the pour is `copper.py`'s.

### Where it came out

101 unconnected pad pairs before, **13 after**, over 8 nets, with 0 errors
and 0 schematic parity issues on the repo board. 41 nets routed, 1331 tracks
and 115 vias imported (193 vias on the board in all).

| net | pairs | why it is still open |
|-----|-------|----------------------|
| NTC | 3 | QFN pad 19, and pads 18 and 20 either side of it both carry a fan-out via. `QFN_VIA_PADS` is zero-sum: taking those two vias out closes NTC and ENC_B and opens LCD_BL and VCAP1 instead, for the same total |
| ENC_SW | 3 | QFN pad 43, boxed in by the locked stubs of pads 41, 42 and 44 (ENC_B, LCD_BL, BOOT0). The router reports it `boxed_in_static` after 5157 iterations and names only pre-existing copper as the blocker |
| ENC_B | 2 | QFN pad 41, the same west-face jam as ENC_SW |
| +5V, LCD_RST | 1 each | the router produced no copper for them at all on the winning attempt. Both were routed before the USB band went in; they are the price of it |
| /MCU/USB_DP, /MCU/USB_DM | 1 each | U302's own I/O pins, joined by the die - see above |
| unconnected-(SW401-PadMP) | 1 | the encoder's two mounting pads - see above |

**The USB band costs three of those thirteen.** Without it the board closes
at 10 open pad pairs, but eleven B.Cu tracks cross under the pair (+3V3,
+5V, VBUS, ENC_A, LCD_RST and SWDIO, twice each bar VBUS) and the reference
ADR 0003 asks for is cut eleven times. With it, 0 crossings and three more
pad pairs for Jan's hand route. `USB_KEEP = 0` in `copper.py` turns the band
off and gives the other trade back.

Levers tried on NTC and ENC_SW, and what each cost. All of these were
measured before the USB band went in, so compare them against 10, not 13:

| lever | result |
|-------|--------|
| net ordering | mps and bus agree and win, inside_out and original both lose by 4 to 7 pad pairs. The tool is not reproducible across board files whose only difference is the serialisation order, which is why all four are run and the best kept |
| `--rip-existing-nets` on the blockers, named exactly | refused: the tool protects a whole NET as soon as any of its copper is KiCad-locked, and `copper.py` locks a fan-out stub on nearly every net at the QFN. Unlocking the router's own copper between passes (the stage does this) is the only rip that works |
| `QFN_VIA_PADS = ()` | closes NTC, opens LCD_BL and VCAP1: 12 open, 40 nets |
| `QFN_VIA_PADS = ("42", "44")` | closes NTC and ENC_B, opens VCAP1, and lets a +3V3 via land 0.18 mm from a GND track: 12 open, 41 nets |
| a User.2 band round the crystal ground guard | the router treats any User.2 polygon as a hard block whatever its size, and a 0.05 mm band closes the west corridor: 12 open |
| GND at 0.20 mm clearance via `--net-clearances` | same, 12 open - and the flag REPLACES the whole cross-class map, so the file has to carry the Power and HighCurrent nets too or they route at 0.15 |

The committed `QFN_VIA_PADS = ("18", "20", "42", "44")` is what wins. Each
lever was tried on NTC and ENC_SW and none improved the total; the honest
remainder is the three pad pairs of each, and the fix is a hand route in
pcbnew or a placement change that gives the QFN's west face somewhere to go.
`SWCLK` and `DECAY_SLOW` also appeared and disappeared from the remainder
between attempts, which is the same ordering noise.

### What the renders show

`tools/pcb/render.sh` after the stage; `top.png`, `bottom.png` and
`both.png` are the three to look at.

- **The bottom pour survives.** The router's B.Cu copper is a knot round the
  MCU and two long diagonals up to the driver block; the rest of the 110 x
  70 mm is solid. GND is complete on the finished board.
- **`/Driver/CLAMP` is 55.56 mm**, of which about 50 is the router's: the
  `D202 -> Q202` clamp tap that `copper.py` could not draw (Q201's 11 mm DPAK
  tab is in the way) went the long way round, down the right-hand side of the
  board and back west. The flyback loop itself is scripted, locked and still
  20.26 mm, so this is the bypass FET's gate-side tap and not the switching
  loop - but it is the longest unnecessary thing on the board and the obvious
  candidate for a hand route or for a `copper.py` path that ducks under the
  DPAK.
- **The encoder runs are long** (ENC_A 87.61 mm): inherent, the encoder is
  front-right and the MCU is centre-left, and "What is still rough" item 4
  already says so.
- **The QFN fan-out is tidy.** No via landed in the first ring, the escapes
  leave radially as designed, and the leftover stubs on the west face are the
  three nets below.
- **Nothing crosses the crystal island but GND**, and nothing at all is in an
  M3 ring.
- **Nothing crosses under the USB pair on B.Cu.** It did on the first run -
  a +3V3 track straight under D-, which is exactly the broken reference ADR
  0003 component breakdown 3 forbids - so `copper.py` now draws a User.2 band
  along every segment of the pair (`USB_KEEP`, 0.15 mm off the centre line)
  and `autoroute.py` checks it afterwards. The band costs almost nothing on
  F.Cu, because the locked pair is already there.

### How to redo it

    python3 tools/pcb/autoroute.py --strip     # board back to scripted-only
    python3 tools/pcb/autoroute.py             # route it again

A re-run does the strip itself, so the second line alone is enough. Changing
`copper.py` or `place.py` means re-running those first, because the stage
starts from what is on the board:

    python3 tools/pcb/place.py --copper --silk --route

Artefacts for one run land in `$PCB_SCRATCH/autoroute/<label>/<ordering>/`:
`route-1.log` / `route-2.log` / `route-m1.log` and their JSON summaries,
`stage1.kicad_pcb`, `routed.kicad_pcb`, and `candidate.kicad_pcb` with the
DRC report that graded it. None of it is ever committed.

## Silkscreen

`silk.py` runs after `copper.py` (or as `place.py --copper --silk`) and
touches **F.Silkscreen only**: it creates no copper item, moves none and
deletes none, and it leaves F.Fab exactly as `place.py` made it. The run
prints a before/after copper census (tracks, vias, zones) and exits non-zero
if any of the three numbers moved.

    python3 tools/pcb/silk.py             # place + DRC before/after
    python3 tools/pcb/silk.py --no-drc    # skip both kicad-cli DRC runs
    python3 tools/pcb/silk.py --verbose   # one line per reference

It is idempotent in two different ways, because there are two kinds of silk.
Everything it **creates** - the rear-edge connector labels, the two pin
legends, the pin-1 markers and the board title - goes into a PCB group named
`scripted-silk`, and the first thing a run does is delete that group's
members, exactly as `copper.py` does with `scripted-copper`. Everything it
**moves** - every footprint's reference field - is positioned absolutely from
the part's own body box and never relative to where the field currently
sits, so a second run computes the same answer. Verified: re-running on an
already-silked board gives a byte-for-byte identical set of 739 silk items.

### What the stage does

1. **Clips the library silkscreen to the board outline.** All four rear
   connectors are right-angle parts that overhang the rear edge on purpose
   (`EDGE_PARTS` in `place.py`), and their library outlines overhang with
   them - that is 15 of the 17 `silk_edge_clearance` warnings. A graphic that
   still has a piece inside the board is shortened in place, one that is
   wholly outside is removed: 15 shortened, 11 dropped. Clipping an already
   clipped segment is a no-op, which is what keeps this idempotent. The price
   is 4 `lib_footprint_mismatch` warnings, one per trimmed connector; there
   is no way to trim a footprint's own graphics and keep it byte-identical to
   the library, and the alternative is silk printed over the board edge.
2. **Resets every reference** to 1.0 mm text at 0.15 mm stroke on
   F.Silkscreen, upright, `keep_upright` off (ADR 0003 decision 5 minimum).
   The four mounting-hole references (`MH401`-`MH404`) are hidden instead -
   brief item 4, they do not need a silk label. The other 2 edge-clearance
   warnings were two of those.
3. **Places the labels first**, before any reference: they are the ones that
   have to be somewhere specific.
4. **Places the 113 references** by searching.

### The obstacle set, and the search

Every candidate position is tested as the text's **real** bounding box -
`PCB_TEXT::GetBoundingBox()` after actually setting the position and angle,
not a width estimate - against:

- every **mask opening** on the front, taken as the pad's bounding box grown
  by 0.05 mm, with 0.03 mm of air required. That is KiCad's `silk_over_copper`
  rule ("silkscreen clipped by solder mask"); vias are tented on this board
  so they have no opening and do not count.
- every **silk graphic** of every footprint, decomposed to segments
  (rectangles to four edges, circles to 16 chords, arcs through their mid
  point, polygons to their outline), 0.03 mm of air past the line's own half
  width. That is `silk_overlap`.
- every **silk text already placed**, same 0.03 mm.
- the **board outline** with its 2 mm corner radii, 0.5 mm of clearance,
  which is the brief's number and stricter than `silk_edge_clearance` needs.

The box is always larger than the glyphs it contains - about 0.25 mm on each
side at 1.0 mm text - so a box that clears by 0.03 mm has a quarter of a
millimetre of real ink clearance. 1024 obstacles go into a 4 mm spatial hash,
because the search probes tens of thousands of positions and a linear scan
would be minutes.

Candidate order per part, first legal wins:

1. **inside its own body outline** for a part whose F.Fab body is 20 mm2 or
   more - the connectors, the QFN, the DPAK, the SO-8s, the inductor, the
   buttons and the encoder. 10 references land here. The part's own outline
   is still an obstacle, so this only succeeds where the body really is
   empty: the QFN's exposed pad and the USB receptacle's shell pads push
   those two back out.
2. **ring by ring outwards**, 0.15 mm to 1.50 mm in 0.15 mm steps, and inside
   a ring above, below, left, right, then the four corners - the brief's
   order. Text runs across the part above and below it and along the part at
   its two sides, which is what stops a row of standing 0603s fighting for
   one lane.
3. the same ladder out to 3.0 mm.
4. **a 0.25 mm grid sweep** out to 12 mm round the body centre, nearest
   first. The eight ring directions are a ladder and a ladder misses pockets
   that are not on an axis; where a whole block is this tight what comes out
   of the sweep is a line of references above or below the row of parts,
   which is the brief's "reference row".

Parts are placed big bodies first (they are the ones that can carry their
reference inside their own outline), then small parts **most crowded first**:
the tightest neighbourhood gets first pick, because a part with room to spare
still has room after its neighbour has taken the one lane that was left.

### A legal label is not a readable one

DRC cannot ask which part a label belongs to. A reference that sits nearer
someone else's body than its own reads as that other part's, which is worse
than a reference 4 mm out in clear space. So the search runs twice: the first
pass requires the part's own body to be the nearest body, give or take
`OWN_SLACK` (0.25 mm, without which two 0603s 1.6 mm apart could never both
be labelled); the second pass drops that test for the 12 parts that are boxed
in on all sides, and for those it does **not** take the first legal position
but collects the legal candidates at roughly the best distance available and
picks the one with the most air round it. Without that, R210's reference
landed 7.15 mm from R210 and 0.20 mm from U202 and read as the op-amp's; it
is now 6.52 mm out with 0.70 mm of air.

The run prints every label that is still nearer another body than its own,
worst first. 28 of 113 are, but 21 of those are ties inside a quarter of a
millimetre between two adjacent passives, which context resolves. The ones
worth knowing about:

| ref | from itself | nearest other | why |
|-----|-------------|---------------|-----|
| R210 | 6.52 | 0.70 (U202) | the `OPAMP_WEST` column: three 0603s on end at 3.6 mm pitch between the op-amp and the ground trunk, no gap anywhere near them |
| C308 | 4.27 | 1.35 (U301) | second ring behind the QFN's east pin row |
| R211 | 4.35 | 1.69 (R408) | as R210 |
| C102 | 2.27 | 0.00 (J201) | inside the terminal's outline, above C102. The 1.8 mm band in front of J201 is 0.01 mm too narrow for 1.0 mm text and D202 owns everything past it |
| C405, R212 | 5.10, 4.80 | 4.85, 4.57 | both out in clear space below the MCU; ambiguous but not misleading |

### Where the counts came out

| bucket | count |
|--------|-------|
| inside its own body outline | 10 |
| ring 1, <= 1.5 mm of air | 87 |
| ring 2, <= 3.0 mm of air | 7 |
| reference row, > 3.0 mm | 9 |
| own-part test relaxed (boxed in) | 12 of the above |
| no legal position anywhere | 0 |
| silk label dropped | 4 (MH401-404) |

The nine in a reference row are Y301 3.75, R212 4.80, R211 4.35, C311 3.50,
C405 5.10, C308 4.27, R210 6.52, R407 3.85, R405 3.49 mm - the VDDA / crystal
fan below the QFN and the op-amp column, the same two blocks the placement's
own "What is still rough" list already calls out.

### How to nudge a label

`REF_OVERRIDE` at the top of `silk.py`, same shape as the placement tables in
`place.py`: `ref -> (dx, dy, rot)` puts that reference at the footprint
**origin** plus `(dx, dy)` mm at `rot` degrees and skips the search entirely.

    REF_OVERRIDE = {
        "C102": (0.0, -2.5, 0),      # 2.5 mm above C102's origin, upright
        "R210": (1.6, 0.0, 90),      # 1.6 mm east, running along the part
    }

The run counts these separately, and because it still tests them it prints
`OVERRIDE <ref> is not legal: <what it hits>` when a nudge lands on a pad or
on another label. It does not move it back - a nudge is an instruction, not a
suggestion - so read the line.

Everything else is a table too:

- `REAR_LABELS` - `(ref, text, seed (x, y), size)` for the five rear names.
  The seed is intent, not a coordinate: the label is searched outwards from it
  on a 0.1 mm grid and the run prints how far off the seed it ended up (all
  five landed on their seed).
- `PIN_LEGEND` - `(ref, pad, text, offset from that pad, rot, size)`. The
  offset is from the **pad**, so the legend follows the connector if
  `place.py` moves it.
- `PIN1_MARKS` - `(ref, pad, seed, direction the tip points)` for the filled
  triangles.
- `TITLE` - the board title lines.
- `EDGE_CLR`, `PAD_CLR`, `SILK_CLR`, `OWN_SLACK`, `BIG_AREA`, `FREE_R` - the
  numbers behind the search, one comment each.

### The rear edge, and the two connectors that are their own label

ADR 0003's "Polish" item, plus SWD:

| ref | text | at | note |
|-----|------|----|------|
| J101 | `DC 24V` | 17.60, 1.58 | inside the jack outline, between the rear edge and the +24 V pad. 1.2 mm text in a 2.17 mm band, which is why the label size is the bottom of the brief's 1.2-1.5 mm range |
| J301 | `USB` | 29.00, 4.20 | inside the receptacle outline, between the two rows of shell pads |
| J302 | `SWD` | 43.60, 5.60 | in front of the header, with a filled triangle at 37.00, 4.95 pointing at pin 1 |
| J201 | `HANDPIECE` | 61.90, 4.60 | plus `4 GND` / `3 NTC` / `2 COIL` / `1 VIN` at 1.0 mm on the pin pitch at y = 7.00, and a triangle at 71.85, 10.05 pointing west at pin 1 |
| J402 | `PEDAL` | 88.00, 1.75 | inside the Neutrik outline |
| J401 | pin names | y = 66.90 | `G 3V3 SCK SDA RST DC BL` rotated 90 degrees along the pins, in front of the body, plus a triangle at 20.00, 57.30 pointing down at pin 1 |

The J201 legend follows the **board** order, not the schematic's: J201 is
forced to rotation 180 because its four wire-entry funnels are drawn on its
+y side, which reverses the pins. Seen from the front, left to right, it is
4 GND / 3 NTC / 2 COIL_NEG / 1 VIN. See "Connector orientation" above.

Two of the six labels are honest compromises and worth stating. J201's and
J402's names sit **inside their own connector body outline**, because both
parts are right-angle types that cover the board from the rear edge inwards
and the space in front of them is occupied (D201, D202, C102, U401 for the
terminal; U401, D203, C103, Q202 for the jack). The brief asks for the label
"just inside the rear edge next to each connector", which is where they are;
they will be under the part once it is mounted. The same is true of `DC 24V`
and `USB`. If Jan wants them visible on an assembled board the fix is
mechanical - the names belong on the rear wall of the cover plate - not a
silkscreen one.

`J401`'s pin-1 triangle is the one marker that is not next to its pin name
row: the name row is in front of the connector and C111/C112 sit under pins
1 and 2 there, so the triangle went into the 1.7 mm band **above** the
connector at pin 1's own x. Pin 1's name, `G`, is also 1.1 mm further out
than the other six for the same reason.

The board title is `GRAVER CTRL r0.1` at 57.00, 67.30 and `2026-09` at
74.00, 67.30, both 1.4 mm, in the empty front-centre strip.

## Routability test

`tools/pcb/routability.sh [label]` is a **placement test, not the routing
step** - `autoroute.py` is the routing step, see "Routing the rest". Run this
one to compare two placements; it is a single strict autoroute with no
passes, no mop-up and no import, so its open-net count is a lower bound on
what the placement can do, not what the board ends up with. It copies the board and the project into a scratch directory outside
the repo, autoroutes the copy at the committed design rules with the router
forbidden to relax them (`--escalation off --strict-sizes` on both routing
steps), copies the pristine `.kicad_pro` back over whatever the router wrote,
and grades only with `kicad-cli pcb drc`. It prints open nets, via count and
error counts by type. It refuses to run if its work directory is inside the
git repo.

    tools/pcb/routability.sh it1          # scratch dir named after the label
    WORK=/tmp/elsewhere tools/pcb/routability.sh probe

Nothing it produces is ever committed, and the router never sees a repo file.
Use the numbers to compare placements; do not read the routed copy as a
routing proposal.

Third-pass history (open nets / vias / kicad-cli errors):

| iteration | change | open | vias | errors |
|-----------|--------|------|------|--------|
| it0 | pass-2 placement, strict | 17 | 165 | 9 |
| it1 | 2 mm annulus + 4 corridors, VIN corridor, buttons moved | 13 | 168 | 12 |
| it2 | one-row crystal island outside the annulus | 14 | 186 | 14 |
| it3 | 3 mm annulus, 10 mm corridors, decaps out to 2.0 | **7** | 202 | 6 |
| it4 | 5 mm corridors | 14 | 205 | 12 |
| it5 | island biased off the VBAT decap | 10 | 180 | 15 |
| it6 | it3 geometry, criteria-passing crystal | 14 | 192 | 6 |
| it7 | fab-text/overhang fix, buttons stacked | 11 | 178 | 25 |
| before | it7 + the copper.py place.py changes, no copper | 9 | 189 | 24 |
| after | + all of copper.py, no fanout vias | 7 | 135 | 2 |
| after2 | + 4 fanout vias on pads 18/20/42/44 | **7** | 140 | **2** |
| p3final | third pass: island in the corner, Kelvin taps, sense ground | **6** | **120** | **2** |

Third pass, the two rows that matter (`p3before` is `after2` re-run on the
same day for a fair comparison):

| iteration | open nets | vias | kicad-cli errors |
|-----------|-----------|------|------------------|
| p3before | 7: NTC, LED_STAT, PEDAL_TIP, NRST, PEDAL_RING, LCD_DC, LCD_MOSI | 130 | 2 hole_clearance |
| p3final | 6: /MCU/VDDA, NTC, LCD_DC, LCD_RST, PEDAL_TIP, LCD_MOSI | 120 | 2 hole_clearance |

NRST, PEDAL_RING and LED_STAT close because the crystal island stopped
standing in front of their pads. /MCU/VDDA and LCD_RST open instead: VDDA's
own 2.5 mm hop is now the router's (see the table in "What is still rough"),
and LCD_RST is second-ring congestion on the MCU's new pose. PEDAL_TIP has a
radial stub now and is congestion rather than a trap. Ten fewer vias, and the
two remaining errors are the same router pour artefact at J301's NPTH pegs as
in the second pass - `copper.py`'s own fill applies the 0.25 mm hole clearance
and the committed board reports 0 errors.

The second pass's rows: the scripted copper took a strict autoroute from 9
open nets / 189 vias / 24 errors to 7 / 140 / 2. The
17 `track_width` errors are gone because the USB pair is now scripted at
exactly 0.2 mm instead of the router's 0.1996 mm, and five of the seven
`hole_clearance` errors are gone because of the M3 keepouts. The **two that
remain are a router artefact of a third kind**: the router's own
`--write-fill` refill of the scripted GND pour does not apply the 0.25 mm
hole clearance to J301's two NPTH pegs. `copper.py`'s own fill does, and the
committed board reports 0 errors. The two `hole_to_hole` warnings are two
+3V3 vias the router placed 0.4517 mm apart.

it3 routed best but missed the crystal's 5 mm limit by 0.16 mm, so the shipped
placement is it7: every ADR criterion passes and 11 nets are left open.

## Renders

`tools/pcb/render.sh` writes into `output/pcb/`:

| file | layers | for |
|------|--------|-----|
| `placement.png` | F.Fab + F.Courtyard + Edge.Cuts | judging placement |
| `copper.png` | F.Cu + Edge.Cuts | pads only |
| `silk.png` | F.Silkscreen + F.Cu + Edge.Cuts | what the top side will look like |
| `critical.png` | F.Fab + User.1 + Edge.Cuts | the loop/speed-critical nets as straight lines |
| `top.png` | F.Cu + User.2 + Edge.Cuts | the scripted top copper and the keepouts |
| `bottom.png` | B.Cu + User.2 + Edge.Cuts | the pour, its cut-outs and the M3 keepouts |
| `both.png` | B.Cu under F.Cu over F.Fab | both layers against the bodies |
| `zoom-*.png` | crops of `placement.png` | one block at a time |
| `cu-*.png` | crops of `top.png` | the scripted copper one block at a time: qfn, xtal, usb, driver, buck |
| `silk-*.png` | crops of `silk.png` | the silkscreen one block at a time: rear-l, rear-r, mcu, front, power |

`PXMM=24 tools/pcb/render.sh` is worth it for the silk crops - the default 18
pixels per mm is marginal for reading 1.0 mm references.

The crop windows in `render.sh` are tied to the current MCU pose (46, 44) and
to the crystal island being south-west of the part. Move the MCU and they need
moving too - they are plain mm rectangles at the bottom of the script.

`critical.png` is rendered from `output/pcb/critical.kicad_pcb`, a
**review-only** copy that `place.py` writes with the nets in `CRITICAL_NETS`
drawn as straight User.1 segments (flyback loop, buck SW and BST, crystal, USB
pair, I_SENSE, shunt, gate). The committed `.kicad_pcb` carries none of them.

## What is still rough

Honest list, worst first. Items -3..-1 are copper; the rest are placement
and the numbers in them are from the second pass.

-3. **The crystal island: done.** It sits in the corner at the low pin
    numbers, the OSC legs are 3.24 and 4.75 mm (were 4.99 and 4.13), the
    channel is 1.03 mm and takes two lanes (was 0.51 mm and one), and no pad
    is trapped: pads 7-12 have plain radial stubs, pad 1 has a 0.97 mm
    same-net jumper and pad 2 a 6.56 mm channel lane and a via. What it cost
    is C301, VBAT's 100 nF, which is now 2.93 mm from pad 1 instead of 1.79
    and prints OVER (advisory) with the reason. See "The crystal island lives
    in the corner" above.

-2. **The Kelvin taps: done.** R209 and R213 are 1.15 and 1.23 mm of bare
    laminate from R204's sense pad and the 0.20 mm taps are drawn from that
    pad's copper EDGE, not from its centre and not off the 1.0 mm power
    trace. The follow-on run R213 pad 2 -> U202 pin 5 is still not drawn (it
    is 14 mm, across the gate drive) and is left to the router; that segment
    carries no measurement current, only the comparator's high-impedance
    input after the series resistor.

-1. **Twelve local traces still could not be drawn** (was 29 in the second
    pass, and the numbers below are from the current run's "COULD NOT DRAW"
    list). The sense-side ground is no longer among them - all five rows of
    the new checked table pass - and neither is the op-amp's feedback network
    or the crystal guard's west leg. What is left, with the blocker:

    | trace | blocked by | verdict |
    |-------|-----------|---------|
    | pin 22 -> C308 (VCAP1) | FB301's VDDA pad, 0.04 mm | router; both are first-ring parts on the same 2 mm of edge |
    | pin 9 -> C306 (VDDA) | C309's pad | router, 2.5 mm. The island's courtyard pushes the NRST cap 1.0 mm east onto pin 9's own slot, and the corridor between C309's pad and pad 11's stub is 0.53 mm where 0.85 is needed. Both parts are inside their 3 mm criteria, so this is a 2.5 mm job for the router, not a trap |
    | D202 -> Q202 (CLAMP) | Q201's drain tab | router; the 0.5 mm clamp tap has to go round an 11 mm DPAK |
    | R213 -> U202 pin 5 | R307's pad | router; 14 mm, see -2 |
    | U202 pin 7 -> R214 (OC_TRIP) | R215's pad, 0.16 mm | router; R214/R215/R216 are stacked at 2 mm pitch off three adjacent op-amp pins and their pads interleave |
    | C109 -> R109 (FB feed-forward) | the buck's own SW pad | router |
    | R105 -> U101 pin 3, R105 -> C105 (EN/UVLO) | U102's +5V pad, R106's own pad | router; the EN/UVLO divider ended up on the far side of the LDO from the buck. Placement lever, not copper: it is the one part of the buck block that is still resolved rather than placed |
    | D103 -> J301 A4 (VBUS) | D105's +5V pad | router by design: 28 mm from the ORing diode to the receptacle, across the rear half |
    | pin 19 -> C207, pin 11 -> C405, pin 12 -> C404 | VIN_SENSE's fanout via, C306's VDDA pad | router; all three parts are in the second ring behind a first-ring cap |

    The buck's FB divider no longer folds back over the part (`R109` used to
    be chained off `R110` and landed across the SW node, which ADR 0003
    explicitly wants kept clear); both now hang off the FB pin and march
    south along U101's east face. `RC_MAX` came down from 12 to 6.5 mm for
    the same kind of reason: a "filter at the MCU pin" 8 mm away is not a
    filter link, and drawn as one straight trace across the corner of the
    part it cut five QFN escapes.

0. **A strict autoroute still leaves 11 nets open** (see the table above):
   /MCU/OSC_OUT, Net-(U301-PB2), /MCU/VDDA, VIN_SENSE, OC_TRIP, LCD_BL, SWDIO,
   NTC, LCD_RST, LCD_MOSI, LCD_SCK. All of them are QFN escapes. Two things
   cap what placement can do here: at 0.2 mm track / 0.15 mm clearance no
   track fits between two adjacent QFN pads (0.25 mm gap needs 0.5 mm), so
   every one of the 33 signals must escape radially; and a 0.6 mm via needs
   0.75 mm of clear radius, which does not exist anywhere in the first ring,
   so nothing can drop to B.Cu near the part. The remaining opens are
   congestion in the corridors, not parts in the way - the router reports
   them blocked by *previously routed nets*, not by footprints. Realistic
   fixes are a QFN fanout pass at a locally relaxed clearance (ADR 0003
   decision 5 already anticipates this) or routing these by hand; both are
   routing decisions, not placement.

1. **VDDA network and NRST cap are 4.9-6.8 mm from their pins**, not the 3 mm
   they are graded against. Those four rows print `OVER (advisory)` and do not
   fail the run, with the reason printed under the table: pads 1 and 5-12 sit
   on one 6 mm stretch of QFN edge and eleven parts want it (VBAT decoupling,
   crystal + two load caps, three-part VDDA network, NRST cap, two pedal
   filter caps). Four fit in the first ring. The crystal's hard 5 mm limit and
   the four VDD caps' 2 mm limit are satisfied first, so the filters give.
   Both are filters - VDDA behind a ferrite, NRST a slow node with a button on
   it - so this is the right thing to trade.
2. **Clamp loop is 25.9 mm of perimeter, flyback loop 46.5 mm**, against a
   16 mm target; both advisory with the arithmetic printed. The floor for the
   clamp loop is about 24 mm: J201's own pins are 5.08 mm apart, its body is
   12.6 mm deep so each leg touching those pads drops >= 3.4 mm before it
   reaches anything, and the SMA/SMB/0805 chain adds two ~5 mm hops. The
   parts do sit in a 10 x 12 mm block directly under the terminal, which is
   what ADR 0003's "closed within about 15 mm" is really about (loop area over
   solid bottom ground). The 6-vertex "flyback loop" figure additionally
   walks out to the FET and back to the terminal, so it is a comparison
   number between runs, not a target.
3. **About a fifth of the board is empty**: x 45..78 / y 45..70 and
   x 78..100 / y 30..50. The MCU search puts the cluster at (38, 30) because
   USB, the SWD header, the LCD connector and the driver all pull it up and
   left, and the encoder (weight 1) cannot pull it back. On a 2-layer board
   that space is routing room rather than waste, but if Jan wants it used the
   lever is `MCU_LINKS` weights or moving the encoder left.
4. **ENC_SW is 66 mm, ENC_A/B 52-54 mm, DECAY_SLOW ~50 mm.** Inherent: the
   encoder is front-right by ADR decision and the MCU is centre-left, and
   Q203 sits with the bypass circuitry it switches. None is speed-critical.
5. **U202.7 -> PB12 (OC_TRIP) is ~20 mm**, not the "short track" the ADR asks
   for. The op-amp has to be within 10 mm of the shunt (it is, 1.5 mm) and the
   shunt is ~20 mm from the MCU, so the two rules fight. Keep it away from the
   coil node when routing.
6. **C111/C112 (buck output caps) drift to y ~64**, below J401, about 10 mm
   from D105. They are the last of the "oring" group to be placed and the
   front-left is full by then.
7. **Silkscreen: done.** `silk.py` takes the three silk warning types from
   92 / 92 / 17 to 0 / 0 / 0. What it cannot fix is that 12 parts are boxed
   in hard enough that their reference has to leave its own neighbourhood -
   the VDDA / crystal fan below the QFN and the three-part op-amp column -
   and 4 footprints now differ from their library copy because their
   overhanging silk was trimmed to the board edge. See "Silkscreen" above.
8. **No keepouts drawn yet.** ADR 0003 wants a ground guard and no signal
   under the crystal; `place.py` only keeps other *parts* off the island
   (`XTAL_CLEAR`). Draw a User.2 polygon over Y301/C310/C311 before any
   routing and give the router `--keepout`.
9. The `.kicad_pcb` is not byte-stable between runs - KiCad regenerates item
   UUIDs and writes footprints in a UUID-dependent order. Part positions and
   rotations are identical run to run (verified); only the serialisation
   moves.

## TODO for Jan

1. **Mounting holes.** ADR 0003 wants them as schematic symbols - they already
   are (`MH401`-`MH404` on the IO sheet, `Mechanical:MountingHole`), so the
   script places them from the netlist like any other part and adds nothing of
   its own. They are currently `in_bom yes`; if you want them off the BOM and
   the CPL, set "Exclude from bill of materials" on the four symbols in
   eeschema. `place.py` copies whatever the schematic says.
2. **EP thermal vias** (0.3 mm drill / 0.6 mm pad, 4 of them) get added by
   the copper script. U101 now uses the plain
   `Package_SO:HSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.1mm` footprint, so the
   board no longer carries the library's 0.2 mm thermal vias and DRC reports
   zero errors.

3. **THT footprints pending caliper measurements** on the loose parts
   (ADR 0003 "Known unknowns"). All four are placed with the stock KiCad
   footprints, so the overhangs in the table above are the library's idea of
   the part, not a measured one:
   - `J201` handpiece terminal: drill needs to go from KiCad's 1.2 mm to
     1.6 mm.
   - `SW401` encoder: lug spacing unverified (currently the Alps EC11E
     12.0 mm variant).
   - `J402` Neutrik: normalling (SN/RN/TN) contacts unverified, and the
     footprint only draws 3 mm of ferrule. The rear wall is 3 mm at the jack,
     so there is no thread left for the nut if 3 mm is all there is - measure
     before ordering.
   - `J101` DC jack: body and slot dimensions unverified.
4. **Cover-plate reference export.** The positions this script produces are
   the input to the DXF/STEP reference for FreeCAD (ADR 0003 mechanical step
   2). Not written yet.
5. **Power block is provisional** until the 24 V punch test lands
   (ADR 0003 open question). It occupies x 4..32, y 14..62; if a boost stage
   comes back, that is the block to grow.
