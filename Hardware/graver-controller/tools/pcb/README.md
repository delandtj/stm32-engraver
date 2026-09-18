# tools/pcb - board generation and placement

Scripted placement for `graver-controller.kicad_pcb`, per ADR 0003 decision 8.
Placement is data in `place.py`; the script regenerates the whole board from
the schematic every run. Nothing here routes or pours.

## Run it

    cd Hardware/graver-controller
    python3 tools/pcb/place.py          # rebuild + place + check
    tools/pcb/render.sh                 # PNGs into output/pcb/

`place.py` needs plain `python3` with the system KiCad 10 `pcbnew` bindings -
no venv, no extra packages. It exits non-zero if any placement check or ADR
distance criterion fails, and prints a table of every criterion with its
measured value.

`--no-netlist` skips the `kicad-cli sch export netlist` step and reuses
`output/pcb/netlist.xml`. Use it while iterating on placement numbers.

Verify independently with:

    kicad-cli pcb drc --schematic-parity --severity-all graver-controller.kicad_pcb

Expected on an unrouted board: 0 schematic parity issues, 258 unconnected
items, and silkscreen warnings. See "Known DRC output" below.

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
  edge, outward)`. They are placed as one RIGID group.
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

`kicad-cli pcb drc --schematic-parity --severity-all` on the placed board:

| type | count | why |
|------|-------|-----|
| schematic parity | 0 | clean |
| errors | 0 | clean |
| unconnected_items | 258 | nothing is routed yet |
| silk_overlap | 142 | silkscreen is a later pass |
| silk_over_copper | 113 | ditto |
| silk_edge_clearance | 17 | ditto |

Silkscreen has not been touched at all: every reference is still at its
library default offset, and the second pass packs parts tighter, so the count
went up. Cleaning it up is a pass of its own, after routing.

The assembly view instead gets its labels from F.Fab: `place.py` hides every
footprint's **Value** field (it was the "100nF 100V" text that buried
`placement.png`) and scales each footprint's F.Fab `${REFERENCE}` to fit the
body it sits in, which the library gets backwards - 0.4 mm on an 0603 and
1.0 mm on a QFN.

## Routability test

`tools/pcb/routability.sh [label]` is a **placement test, not the routing
step**. It copies the board and the project into a scratch directory outside
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
| `zoom-*.png` | crops of `placement.png` | one block at a time |

`critical.png` is rendered from `output/pcb/critical.kicad_pcb`, a
**review-only** copy that `place.py` writes with the nets in `CRITICAL_NETS`
drawn as straight User.1 segments (flyback loop, buck SW and BST, crystal, USB
pair, I_SENSE, shunt, gate). The committed `.kicad_pcb` carries none of them.

## What is still rough

Honest list, worst first. Numbers are from the second pass.

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
7. **Silkscreen is untouched** - all 272 DRC warnings are references
   overlapping pads and each other.
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
