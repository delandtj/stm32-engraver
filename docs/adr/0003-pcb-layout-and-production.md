# 0003 - PCB layout and board production

**Status**: Proposed
**Date**: 2026-09-17

---

## Context

ADR 0001 fixed the circuit; schematic rev 0.1 is captured, ERC-clean, every part has
a value, footprint and LCSC number (`Hardware/graver-controller/`). ADR 0002 fixed the
firmware, which runs on the Blackpill bench rig with the same pin map. The
`.kicad_pcb` is empty. This ADR is the spec for turning the schematic into 8-10
assembled boards plus spares, so that a session can open KiCad and start placing parts
without re-deriving anything.

What is settled and must not be re-litigated here:

- Single 2-layer board, 1.6 mm, 1 oz, fully assembled by JLCPCB (SMT + THT). Builders
  plug in the display, screw in the GX12 pigtail, mount the board. No soldering.
- The board is the top face of a desk console; display and encoder on top, all jacks on
  the rear edge (ADR 0001 section 10).
- Parts, LCSC numbers, footprint gotchas: `Hardware/graver-controller/docs/parts-*.md`.

What is still open on the bench and can still change the copper:

- The 24 V punch test (ADR 0001 open question). If 24-30 V is not enough, a boost rail
  comes back and the power block grows. Layout must not start on the power block until
  this is answered, or must leave room for it.
- Coil inductance, which sizes the TVS energy (parts already chosen with margin).
- Footprints not yet checked against real parts: DC jack (J101), 5.08 mm terminal
  (J201, KiCad drill 1.2 mm vs 1.5-1.7 mm needed), Neutrik NMJ6HCD2 normalling
  contacts, encoder lug spacing, display module pin order and outline.

Constraints from the class context: below EUR 150 per complete unit, 10 identical units
that behave identically, a printed enclosure (Creality K2 Max, FreeCAD), Jan does the
first-article bring-up alone with an ST-LINK, the class never sees a probe.

---

## Decision

1. **Retire the schematic generator when layout starts.** From the first placed
   footprint on, eeschema is the source of truth. `tools/ref/` and `tools/sheets/` stay
   in the repo as history; `tools/verify.sh` keeps only its ERC and render steps. Reason:
   layout needs incremental schematic edits (net ties, test points, mounting holes,
   footprint swaps) and a generator that overwrites sheets fights that.
2. **All components on the top side**, SMT and THT alike, so JLC assembles one side
   ("economic" PCBA) and the THT parts are soldered from the bottom without SMD in the
   way. The board is hidden under a **printed cover plate** with cutouts for the display
   glass, the encoder shaft, the status LED and the rear connectors; the PCB is not the
   cosmetic surface. This is a refinement of ADR 0001's "PCB is the top face": the PCB
   is the top structural layer, the print is the skin.
3. **Board outline 100 x 70 mm**, rectangle, 2 mm corner radius, four M3 holes at 4 mm
   from each corner with 6 mm ground-free keepout. Rear edge (long side) carries, left
   to right seen from the front: DC jack, USB-C, pedal jack, handpiece terminal. Front
   half carries display (left) and encoder (right). Power block behind the DC jack, driver
   block behind the handpiece terminal, MCU in the middle, analog front end between
   driver and MCU. Sized so the 12.5 x 20 mm bulk capacitor lies flat under the cover.
4. **Layer use**: top = parts and signal, bottom = ground pour with the few crossing
   traces. One ground net, but the shunt's power-ground tap is a single point: the
   sense side of R204 (the 1 ohm shunt) joins the pour only at the shunt, and the
   flyback loop (FET drain, TVS, diode, bulk cap, terminal) is routed as a tight top-side
   loop over solid bottom ground, away from the ADC inputs.
5. **Design rules**: JLC 2-layer capability with margin. Track 0.25 mm min (0.2 mm allowed
   inside the QFN fan-out), clearance 0.2 mm, via 0.3 mm drill / 0.6 mm pad, power and
   flyback tracks 1.0 mm, coil and VIN tracks 0.8 mm. Solder mask expansion 0.05 mm.
   Silkscreen 0.15 mm lines, 1.0 mm text minimum, every connector labelled with its
   function and pin 1.
6. **Production package**: JLC Gerber set from kicad-cli, BOM with LCSC column and CPL
   with rotation corrections, 3D STEP of the assembled board for the enclosure, a PDF
   assembly drawing, and a per-board test sheet. Order: 10 assembled + 2 spare assembled,
   plus 5 bare boards; display modules and GX12 pigtails ordered separately from single
   listings, 12 of each.
7. **First-article bring-up** on one board before the class batch is touched: the
   bench-rig test order (`docs/bench-rig.md`) plus the checks in "The mechanical work"
   below; firmware flashed over the SWD header with the ST-LINK; the remaining boards
   flashed the same way by Jan, with USB DFU as the field update path.

---

## Architecture Overview

### Component Breakdown

Blocks as they appear on the board, each with what it must satisfy in layout.

1. **Input power** (`power.kicad_sch`): DC jack J101, fuse, reverse-polarity P-FET,
   SMBJ36A, 470 uF bulk, VIN sense divider R102/R103. Placement: DC jack on the rear
   edge at the left, fuse and P-FET immediately behind it, TVS and bulk cap next; the
   bulk cap lies flat (radial, bent leads, or a horizontal-mount footprint) pointing away
   from the edge. The VIN divider sits next to the MCU, not at the jack: it is an ADC
   node.
2. **5 V buck** (LM5164, `power.kicad_sch`): PowerPAD to the bottom pour through the
   footprint's thermal vias, CIN caps within 3 mm of VIN/GND pins, SW node short (one
   side of the inductor only), BST cap right at the pins, FB divider away from SW. Output
   ORing Schottkys and the AP2112K LDO follow, with the 3V3 output caps near the MCU.
   Keep the buck 15 mm or more from the ADC front end and from the crystal.
3. **MCU** (`mcu.kicad_sch`): STM32F411 QFN48 with the EP to ground via vias, one 100 nF
   per VDD pin within 2 mm, the 4.7 uF and the VDDA filter (ferrite/10 ohm + 1 uF + 100
   nF) on the VDDA side. Crystal within 5 mm of OSC pins, its load caps between crystal
   and MCU, ground guard, no signal under it. BOOT0 and NRST tactile switches on the rear
   half, reachable through holes in the printed rear wall. SWD 1x5 header along the rear
   edge, inside the box. PA10 pull-up as drawn. USB-C on the rear edge with the USBLC6
   between connector and MCU, D+/D- as a 90 ohm pair, length matched within 1 mm, kept
   away from the driver.
4. **Solenoid driver** (`driver.kicad_sch`): UCC27517 gate driver within 5 mm of the
   FET gate, its 1 uF bypass at its pins; IRLR3410 DPAK with the drain tab as a small
   copper island; SS110 + SMBJ24A + SI2309 bypass forming a loop of minimum area with the
   coil pins of J201 and the bulk cap. 1 ohm 1206 shunt R204 from FET source to power
   ground, Kelvin traces from the shunt pads to the TLV9062 (R209/R213), op-amp within 10
   mm of the shunt, its output filtered (R212/C205) at the MCU pin PA6. The comparator
   output to PB12 is a short track. Handpiece terminal J201 at the right of the rear
   edge: pin 1 VIN, 2 COIL_NEG, 3 NTC, 4 GND; NTC pull-up and cap near the MCU.
5. **UI** (`io.kicad_sch`): display socket J3 (1x7, 8.5 mm) in the front-left, glass
   11 mm above the PCB, backlight FET and 100 R nearby; encoder SW401 front-right,
   shaft centre at least 20 mm from the display edge for a knob, its 10k/10 nF debounce
   at the MCU; status LED with a light pipe hole in the cover; pedal jack J5 (Neutrik)
   on the rear edge with the nut on the rear wall (wall thickness under 4.7 mm at the
   jack), PESD5V0S2BT at the jack, ring 1k/10n filter as drawn.
6. **Mechanical**: four M3 holes; outline; cover plate reference points (display glass
   outline, encoder shaft, LED, rear connector faces) exported as a STEP so FreeCAD builds
   the console around the real geometry. Tallest parts: bulk cap 12.5 mm lying flat,
   display 11 mm, encoder shaft 20 mm, pedal jack nose through the wall.

### Data Flow / Interaction

    front  +-----------------------------------------------------------+
           |  [display 1.3"]           [encoder]                (M3)   |
           |   J3 socket                 SW401                          |
           |                                                            |
           |  LDO 3V3   [   STM32F411   ]   analog: shunt amp, VIN div, |
           |  buck 5V   crystal, caps       NTC, pedal filter           |
           |                                                            |
           |  fuse P-FET TVS [470uF flat]   gate drv FET TVS diode      |
    rear   |  [DC jack] [USB-C] [pedal jack TRS]   [4p 5.08 terminal]   |
           +-----------------------------------------------------------+
                                100 x 70 mm, connectors on the rear edge

Current paths: brick -> jack -> fuse -> P-FET -> bulk cap -> J201 pin 1 -> coil ->
J201 pin 2 -> FET -> shunt -> power ground -> pour -> jack sleeve. The flyback path
(coil -> SS110/TVS -> back to VIN at the bulk cap) must be inside the same tight loop.
Everything analog references the pour at one point next to the shunt.

---

## Alternatives Considered

### 4-layer board
- **The idea**: dedicated ground and power planes, signals on the outer layers.
- **Optimizes for**: routing freedom and a guaranteed ground reference everywhere.
- **Sharpest tradeoff**: roughly double the bare-board price and a longer lead time,
  for a board carrying 0.26 A and one 25 MHz crystal.
- **Bets on**: 2-layer being too crowded or too noisy. With a solid bottom pour and
  the switching loop kept tight, this is not expected; the ADC reads at 200 Hz with
  heavy filtering.

### SMD on the bottom, THT on top
- **The idea**: the PCB face is clean and cosmetic, all SMD hidden inside.
- **Optimizes for**: the ADR 0001 wording, no cover plate.
- **Sharpest tradeoff**: JLC two-side assembly is a separate, dearer service, and an
  exposed FR4 top face with THT solder joints on the bottom needs a finish and a bezel
  anyway. The cover plate solves cosmetics for the price of one print.
- **Bets on**: the class caring how the raw PCB looks. The cover plate makes the bet moot.

### Hand assembly of the THT parts by Jan
- **The idea**: JLC does the SMT only, the eight THT parts are soldered at home.
- **Optimizes for**: avoiding JLC's THT assembly fee and its footprint constraints.
- **Sharpest tradeoff**: ten boards times eight parts, including a 6-pin Neutrik jack
  and a 12.5 mm capacitor, and the reproducibility rule of ADR 0001 is broken by hand.
- **Bets on**: the THT fee being significant. For 10 boards it is tens of euros.

### Socketed Blackpill on the production board
- Rejected in ADR 0001; unchanged.

### Larger board, everything on a comfortable 120 x 90 mm
- **The idea**: no placement pressure at all.
- **Optimizes for**: a first layout that succeeds at the first try.
- **Sharpest tradeoff**: the console grows, the printed cover plate approaches the
  K2 Max's comfortable single-piece size, and every extra square centimetre of a board
  ordered twelve times is paid for.
- **Bets on**: 100 x 70 mm being too tight. The rear edge is the constraint: jack 14 mm,
  USB-C 9 mm, Neutrik 19 mm, terminal 21 mm, plus gaps = about 80 mm, which fits.

---

## Consequences

### Positive
- One order, one assembly side, one printed cover: the cheapest reproducible path.
- The bench-verified firmware runs unchanged; layout adds no new nets.
- STEP-first mechanical work: the enclosure is drawn around real part positions.

### Negative
- The generator is retired; the drawing discipline from rev 0.1 now depends on the
  person editing in eeschema.
- A cover plate is a second printed part per unit and needs a tolerance loop against
  the display glass and the encoder shaft.
- Everything on top means the top-side silkscreen must carry the assembly information
  as well as the connector labels.

### Risks
- **JLC stock**: STM32F411CEU6 (819 in stock at the last check) and the Bourns encoder
  (889) can vanish. Mitigation: STM32F401CCU6 is pin compatible, the Alps EC11E15244G1 is
  the drawn encoder; check stock the day the order is placed.
- **Footprint errors on the THT connectors**: the terminal's drill and the Neutrik's
  normalling contacts are unverified. Mitigation: buy one of each loose part first and
  measure; a wrong THT footprint is a re-spin.
- **CPL rotation**: JLC's part orientation convention differs from KiCad's for QFN,
  SOT-23-6 and diodes. Mitigation: review the JLC assembly preview image for every
  polarised or asymmetric part before confirming.
- **Punch test result**: if 24 V is not enough, the power block changes. Mitigation:
  run the test before placing the power block, or reserve 20 x 25 mm next to it.

---

## What an Expert Would Ask

**Q: Your ADC reads a 1 ohm shunt at 0.17 A while a 100 V flyback clamp fires 60
times a second a few centimetres away. What keeps the current reading meaningful?**
A: The clamp loop is closed within about 15 mm on the top layer over solid ground, so
its loop area and its dV/dt coupling are small; the shunt is read through Kelvin
traces into an op-amp placed at the shunt, then filtered with 330 R / 10 nF at the
MCU pin; the firmware averages 200 Hz samples and only uses the value for display,
the trip is hardware. If the reading still jumps during pulses, the firmware can
sample synchronously between pulses (TIM1 update -> ADC trigger), which is a software
change. Layout provides the option by keeping the trace short; nothing else is needed.

**Q: Why not put the ground of the shunt and the analog ground on separate nets?**
A: Two nets on a 2-layer board with one pour invite a split-plane mistake that is
worse than the problem. One net, one pour, and the rule that the only thing tying the
sense side to the pour is the shunt's own pad. The op-amp ground pin returns to that
pad, not to the nearest via.

**Q: The bulk capacitor is 20 mm tall and the cover sits at about 12 mm. What gives?**
A: The capacitor lies flat, leads bent 90 degrees, held by a silkscreened outline and
a dab of the cover's underside. The footprint stays the KiCad 5 mm radial; JLC's THT
service inserts it upright, so the flat orientation must be done after delivery, or the
part becomes a horizontal-mount 470 uF (Rubycon has none at JLC). Decision: order upright,
bend after delivery, one operation per board by Jan. If that is unacceptable, the cover
gets a 22 mm dome over the capacitor; the ADR will say which after the first article.

**Q: How does the Neutrik jack's nut end up on the outside of the rear wall if JLC
solders the jack before the box exists?**
A: The jack nose passes through a hole in the printed rear wall and the nut is fitted
during final assembly; the wall is 3 mm at the jack, under the 4.7 mm limit. The board
is screwed to the console first, then the nut goes on. The DC jack and the terminal do
not need nuts.

**Q: You are ordering 12 assembled boards with about 30 extended parts. What does the
setup cost look like next to the parts?**
A: About 3 USD per extended part per order, so around 90 USD once, plus roughly 25 USD
per board of parts and assembly. Under 15 EUR of the 150 EUR unit budget goes to the
board. Not worth reducing the extended-part count for; worth ordering in one batch.

**Q: What happens when the first article fails a check?**
A: A schematic-level fix is a re-spin of the bare board only if copper changes; JLC
holds the parts list. A footprint fix on a THT connector is a re-spin. A firmware fix
is free. The first article is one board, ordered in the same batch, tested before the
other eleven are opened; it is the reason for ordering 12 rather than 10.

---

## Implementation Plan

### Decisions you will probably want to tweak

- **Board size and rear-edge order.** Choice: 100 x 70 mm, jack / USB-C / pedal /
  terminal from left to right. Alternative: 110 x 70 mm with the pedal jack at the
  far right so the pedal cable leaves the console at its edge. Cost to change later:
  before the first order, nothing; after, a re-spin and a new cover.
- **Cover plate over the PCB.** Choice: printed skin, PCB hidden. Alternative: PCB as the
  cosmetic face, ENIG finish, black solder mask, SMD on the bottom. Cost to change later:
  assembly side changes, so a re-order.
- **Bulk cap orientation.** Choice: upright footprint, bent flat after delivery.
  Alternative: dome in the cover. Cost to change later: cover print only.
- **Retiring the generator.** Choice: eeschema is truth from now on. Alternative: keep
  the generator and mirror layout-time schematic edits into `tools/sheets`. Cost to
  change later: none, the files stay in git.

### Known unknowns and how the plan absorbs them

- **Punch at 24 V**: default is the ADR 0001 power block as drawn; signal to pivot is
  the bench test saying steel needs more than 30 V. Layout order puts the power block
  last so the answer can arrive during layout.
- **THT footprints**: default is the KiCad library footprints with the terminal drill
  enlarged to 1.6 mm; signal to pivot is a caliper measurement on the loose parts that
  disagrees by more than 0.2 mm. Loose parts are ordered before layout begins.
- **Display module pin order**: default GND VCC SCL SDA RES DC BLK, verified on the bench
  module in September; signal to pivot is a second module from the batch listing with a
  different silkscreen. The 12 modules for the class come from one listing in one order.
- **JLC part availability on order day**: default is the BOM as drawn; signal is a
  zero-stock line in the JLC BOM upload; fallbacks are listed per part in parts-*.md.

### The mechanical work

Component specs, in the order that lets unknowns land late:

1. **Project prep**: retire the generator (README note, verify.sh reduced to ERC +
   render), import the project footprints (encoder with 12.0 mm lugs, terminal with
   1.6 mm drills, Neutrik with SN pin symbol), add mounting holes and outline to the
   schematic as symbols, run ERC, update the PCB from the schematic.
2. **Outline and fixed parts**: 100 x 70 mm, M3 holes, rear-edge connectors placed on
   the edge line with their 3D models checked for clashes, display socket and encoder
   placed from the front, cover-plate cutouts derived from these positions and exported
   as a DXF reference.
3. **MCU block**: QFN, decoupling, crystal, VDDA filter, SWD, BOOT0/NRST, USB-C with
   ESD and the differential pair, status LED. Route this block first, it has the most
   pins.
4. **Analog block**: shunt amp, VIN divider, NTC, pedal filters, all within the
   "quiet" zone between the driver and the MCU, referenced to the shunt's ground pad.
5. **Driver block**: gate driver, FET, flyback parts, terminal, tight loop, drain island.
6. **Power block**: jack, fuse, P-FET, TVS, bulk cap, buck, ORing diodes, LDO. Placed
   last so the punch-test outcome can still change it.
7. **Ground pour and DRC**: bottom pour, top pour where it helps, thermal reliefs on
   THT, DRC with the rules in the Decision, review the ratsnest for zero unrouted.
8. **Exports**: Gerber + drill (JLC preset in kicad-cli), BOM (LCSC), CPL with
   rotation review, STEP, PDF assembly drawing with connector pinouts, a per-board test
   sheet listing: VIN and 5 V / 3V3 rails, gate low at reset, DFU enumeration, display,
   encoder, pedal jack presence detect, one strike into a 141 ohm coil at 24 V.
9. **Order**: 12 assembled, 5 bare, loose parts (display modules, GX12 pigtails and
   plugs, 4-pin terminal plugs, encoder knobs), all in one week.

Review asks, each yes/no or pick-one:

1. Cover plate over a hidden PCB (yes) or the PCB as the visible top face (no)?
2. Rear-edge order jack / USB-C / pedal / terminal, or pedal jack at the far right?
3. Bulk cap bent flat after delivery, or a dome in the cover?
4. Order the loose THT connectors for measurement before layout starts (yes/no)?

---

## Open Questions

**Architecture-changers**
- [ ] Punch at 24-30 V confirmed on the bench with the real FET (blocks the power block).
- [ ] Cover plate versus visible PCB (review ask 1).

**Behavior definers**
- [ ] Terminal drill and Neutrik normalling contacts measured on loose parts.
- [ ] Whether the display glass needs a gasket or the cover's cutout holds it alone.
- [ ] BOOT0 and NRST through the rear wall or the bottom.

**Polish**
- Silkscreen wording on the rear edge (proposed: DC 24V, USB, PEDAL, HANDPIECE with the
  four pin numbers).
