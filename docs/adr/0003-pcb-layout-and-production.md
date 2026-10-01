# 0003 - PCB layout and board production

**Status**: Accepted (review asks answered 2026-09-17; connectors and board size
amended 2026-10-01, see Decision 9)
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

- Single 2-layer board, 1.6 mm, 1 oz, assembled by JLCPCB. Amended 2026-10-01: the
  board carries no connectors except USB-C (Decision 9), so Jan solders five wire
  looms into plated holes when he builds the boxes. The class still receives finished
  boxes and touches no solder.
- The board is the top face of a desk console; display and encoder on top, all jacks on
  the rear edge (ADR 0001 section 10).
- Parts, LCSC numbers, footprint gotchas: `Hardware/graver-controller/docs/parts-*.md`.

What is still open on the bench and can still change the copper:

- The 24 V punch test (ADR 0001 open question). If 24-30 V is not enough, a boost rail
  comes back and the power block grows. Layout must not start on the power block until
  this is answered, or must leave room for it.
- Coil inductance, which sizes the TVS energy (parts already chosen with margin).
- Display module pin order and outline, checked on one bench module only. Amended
  2026-10-01: the rest of this list (DC jack, the 5.08 mm terminal's 1.2 mm drill, the
  Neutrik normalling contacts, encoder lug spacing) went away with the connectors.
  Decision 9 replaced every one of them with plated holes from the stock KiCad
  libraries, which is the single largest reduction of layout risk in this ADR.

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
   way. The board is hidden under a **printed cover plate** with cutouts for the
   encoder shaft, the status LED and the rear connectors; the PCB is not the cosmetic
   surface. The **display module is mounted in the cover plate**, not on the PCB, and
   reaches the board through a 7-way ribbon (decided 2026-09-17): the glass position is
   then a property of the print alone, and the cover height is no longer tied to the
   module's 11 mm stack. This is a refinement of ADR 0001's "PCB is the top face": the PCB
   is the top structural layer, the print is the skin.
3. **Board outline 95 x 70 mm** (amended 2026-10-01; was 110 x 70 while the rear edge
   had to seat four connector bodies), rectangle, 2 mm corner radius, four M3 holes at
   4 mm from each corner with 6 mm ground-free keepout. Rear edge (long side) carries,
   left to right seen from the front: the power wire pads, USB-C, the handpiece pads,
   the pedal pads. Front half carries the display pad row (left) and the encoder pad
   row (right). Power block behind the power pads, driver block behind the handpiece
   pads, MCU in the middle, analog front end between driver and MCU. The 12.5 x 20 mm
   bulk capacitor stands upright; the cover plate has a dome over it.

   Why 95: measured on the routed 110 x 70 board, every part except the connectors,
   the encoder and the mounting holes fits inside 84.5 x 64.0 mm, and only four parts
   (R205-R208, Q203) sat beyond x=130. The connectors, not the electronics, were
   setting the width. 95 clears the parts with routing headroom rather than squeezing
   to 85, and it brings the long side under JLCPCB's 100 x 100 mm price band, which is
   worth having across 17 boards. Confirm the band on order day; it is a vendor
   pricing tier, not a design rule.
4. **Layer use**: top = parts and signal, bottom = ground pour with the few crossing
   traces. One ground net, but the shunt's power-ground tap is a single point: the
   sense side of R204 (the 1 ohm shunt) joins the pour only at the shunt, and the
   flyback loop (FET drain, TVS, diode, bulk cap, terminal) is routed as a tight top-side
   loop over solid bottom ground, away from the ADC inputs.
5. **Design rules**: JLC 2-layer capability with margin (JLC floor 0.127 mm track and
   gap). Board minimums: track 0.2 mm, clearance 0.15 mm, via 0.3 mm drill / 0.6 mm pad,
   no smaller via anywhere. Signal tracks are 0.2 mm at the 0.5 mm pitch parts (QFN48,
   USB-C) and 0.25 mm elsewhere where there is room; power and flyback tracks 1.0 mm,
   coil and VIN tracks 0.8 mm, 3V3 and 5 V distribution 0.4-0.5 mm. Amended 2026-09-17
   after the autorouter trial: the first draft (0.25 mm track, 0.2 mm clearance, 0.2 mm
   only inside the QFN fan-out) cannot escape the QFN48 or the USB-C, whose pads sit
   0.2 mm apart, and the router has no per-area rules. These numbers go into the
   `.kicad_pro` (board constraints and net classes) during project prep, and every
   routed result is graded with `kicad-cli pcb drc` against that committed file. Solder
   mask expansion 0.05 mm. Silkscreen 0.15 mm lines, 1.0 mm text minimum, every
   connector labelled with its function and pin 1.
6. **Production package**: JLC Gerber set from kicad-cli, BOM with LCSC column and CPL
   with rotation corrections, 3D STEP of the assembled board for the enclosure, a PDF
   assembly drawing, and a per-board test sheet. Order: 10 assembled + 2 spare assembled,
   plus 5 bare boards; display modules and GX12 pigtails ordered separately from single
   listings, 12 of each.
7. **First-article bring-up** on one board before the class batch is touched: the
   bench-rig test order (`docs/bench-rig.md`) plus the checks in "The mechanical work"
   below; firmware flashed over the SWD header with the ST-LINK; the remaining boards
   flashed the same way by Jan, with USB DFU as the field update path.
8. **Layout method** (added 2026-09-17 after a trial on the MCU block): placement and
   the critical copper are scripted with the pcbnew Python API and locked: crystal and
   its keepout, 3V3 / 5 V distribution, flyback loop, shunt Kelvin traces, buck, USB
   pair. The remaining GPIO, SPI and UI nets go to the KiCadRoutingTools autorouter
   (github.com/drandyhaas/KiCadRoutingTools), which leaves locked and existing copper
   alone. The router runs on a copy of the project, never on the committed files, and
   its own pass messages are ignored; see the risk below. Jan reviews in pcbnew before
   anything is ordered.
9. **Wire pads instead of connectors** (added 2026-10-01). Every board connector
   except USB-C becomes a row of plated through-holes, and the rotary encoder moves
   off the board onto wires. Jan solders the looms when he builds the boxes; the class
   still receives finished units. Reason: the mating halves were the sourcing problem,
   not the board halves. GX12 pigtails, 4-pin screw plugs, XH-7 crimp housings and
   ready-made ribbon leads all had to be found, ordered and assembled separately,
   while the board-side sockets were the four parts in this project whose footprints
   were still unverified against real hardware. Soldering a wire costs a joint; a
   wrong THT footprint costs a re-spin.

   | Ref | Function | Footprint | Pads | Drill |
   |---|---|---|---|---|
   | J101 | Power in from the brick | `Connector_Wire:SolderWire-1sqmm_1x02_P5.4mm_D1.4mm_OD2.7mm` | 2 | 1.4 mm |
   | J201 | Handpiece | `Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical` | 4 | 1.0 mm |
   | J301 | USB-C, unchanged | HRO 31-M-12, SMD | - | - |
   | J401 | Display | `Connector_PinHeader_2.54mm:PinHeader_1x07_P2.54mm_Vertical` | 7 | 1.0 mm |
   | J402 | Pedal | `Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical` | 4 | 1.0 mm |
   | J403 | Encoder (replaces SW401) | `Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical` | 4 | 1.0 mm |

   Pin order as actually captured 2026-10-01, verified against the exported netlist.
   These are the numbers the silkscreen and the wiring card must carry:

   | Ref | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
   |---|---|---|---|---|---|---|---|
   | J101 | GND | +24V | | | | | |
   | J201 | VIN | COIL_NEG | NTC | GND | | | |
   | J401 | GND | +3V3 | SCL | SDA | RES | DC | BLK |
   | J402 | tip | ring-normal (GND) | ring | sleeve (GND) | | | |
   | J403 | ENC_A | GND | ENC_B | ENC_SW | | | |

   J101 has ground on pad 1 because that is what let the existing +24V run to the
   fuse survive the swap untouched; the silkscreen says GND and +24V, so no one reads
   a pad number anyway. J402 pads 2 and 4 are both ground: pad 2 is the socket's
   ring-normal contact and pad 4 its sleeve, and they are separate wires precisely so
   the normalling contact can do the plug detection. J403 merges the EC11's two
   commons onto pad 2.

   All six are stock KiCad library footprints, so nothing here needs measuring
   against a loose part first. The 2.54 mm rows take 22 AWG comfortably and, as a free
   option, accept an ordinary 0.1 inch pin header if a pluggable joint is ever wanted.
   Only the power feed gets 1.4 mm holes, because it is the one joint that takes
   mechanical strain from a brick lead; it gets a strain-relief anchor beside it so
   the solder is not the mechanical joint.

   Consequences that are decisions in their own right:

   - **The encoder is now 4 wires**: ENC_A, ENC_B, ENC_SW and one GND. The EC11's
     two commons (encoder C and switch S2) are already the same net, so they join at
     the encoder body. Run 5 wires instead if that bridge is unwanted. The 10k
     pull-ups R402-R404 and the 10 nF debounce caps C401-C403 stay on the board at the
     MCU. Risk: the A/B lines now leave the board at 10k impedance. Keep the encoder
     loom away from the handpiece cable; if it miscounts on the bench, drop R402-R404
     to 2.2k.
   - **The pedal gets 4 pads, not 3**: tip, ring-normal, ring, sleeve. The pedal
     socket choice is deliberately deferred (see Open Questions). Four pads keep both
     answers alive: a 6.35 mm TRS socket in the box wall wires all four and the
     plugged-in detection of ADR 0001 section 8 keeps working untouched, because the
     detection is the socket's ring-normal contact grounding the ring. A GX12-3 later
     wires three and leaves the fourth empty, and then the detection has to be
     redesigned in both schematic and firmware. Nothing on the board forces either.
     The anti-mixup requirement that motivated 3 pins lives on the box shell, where
     GX12-3 and GX12-4 cannot mate, not on the board where these are soldered once.
   - **Through-hole soldering is nearly gone, but not gone.** Wire pads are holes with
     nothing to insert, so what is left is C101 (470 uF radial), J302 (the 1x5 SWD
     header), and - easy to miss - **J301's four plated shell tabs**: the HRO
     TYPE-C-31-M-12 is 16 SMD signal pads plus 4 PTH tabs and 2 NPTH locating pegs, so
     the USB-C is not a pure SMD part. In practice it is one of JLC's most common SMT
     line items and they handle it routinely; the point is only that "SMT-only" is not
     literally true while it is on the board. Whether the THT service still earns its
     fee is an open question below; default is to keep it, because changing the bulk
     capacitor is a separate decision with its own stock and ripple-rating risk.

---

## Architecture Overview

### Component Breakdown

Blocks as they appear on the board, each with what it must satisfy in layout.

1. **Input power** (`power.kicad_sch`): power wire pads J101, fuse, reverse-polarity
   P-FET, SMBJ36A, 470 uF bulk, VIN sense divider R102/R103. Placement: J101 on the rear
   edge at the left, fuse and P-FET immediately behind it, TVS and bulk cap next; the
   bulk cap stands upright (standard 5 mm radial footprint) under the cover's dome, kept
   10 mm or more from the encoder and clear of the display pocket in the cover above, so
   the dome does not crowd them. The
   VIN divider sits next to the MCU, not at the jack: it is an ADC
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
   between connector and MCU, D+/D- as a coupled pair (0.2 mm tracks, 0.15 mm gap) over
   unbroken bottom ground, 40 mm or shorter, no vias, length matched within 1 mm, kept
   away from the driver. A true 90 ohm pair is not reachable on 1.6 mm 2-layer FR4 and
   is not needed: the F411 is full-speed (12 Mbit/s) only and the run is a few
   centimetres.
4. **Solenoid driver** (`driver.kicad_sch`): UCC27517 gate driver within 5 mm of the
   FET gate, its 1 uF bypass at its pins; IRLR3410 DPAK with the drain tab as a small
   copper island; SS110 + SMBJ24A + SI2309 bypass forming a loop of minimum area with the
   coil pins of J201 and the bulk cap. 1 ohm 1206 shunt R204 from FET source to power
   ground, Kelvin traces from the shunt pads to the TLV9062 (R209/R213), op-amp within 10
   mm of the shunt, its output filtered (R212/C205) at the MCU pin PA6. The comparator
   output to PB12 is a short track. Handpiece pads J201 right of centre on the rear
   edge, between USB-C and the pedal pads: pin 1 VIN, 2 COIL_NEG, 3 NTC, 4 GND; NTC
   pull-up and cap near the MCU. The 7.6 mm pad row replaced a 21 mm terminal body,
   which shortens the flyback loop rather than lengthening it.
5. **UI** (`io.kicad_sch`): display pads J401 in the front-left, a 1x7 row on 2.54 mm
   pitch carrying the drawn pin order GND VCC SCL SDA RES DC BLK, with pin names on
   the silkscreen. The module sits in a pocket of the cover plate and reaches the board
   through a 7-way loom, 100 mm or shorter, soldered at the board end by Jan and
   terminated in a 1x7 2.54 mm female housing on the module's own pin header. J401
   within 40 mm of the MCU's SPI pins, SCL routed next to a ground return; backlight
   FET and 100 R nearby. If the loom rings, the SPI clock comes down in firmware before
   any part is added. Encoder pads J403 front-right (ENC_A, ENC_B, ENC_SW, GND), with
   the 10k pull-ups and 10 nF debounce staying at the MCU; the encoder itself mounts in
   the cover plate, so the old shaft-clearance and bulk-cap-height constraints against
   SW401 no longer apply to the board. Status LED with a light pipe hole in the cover.
   Pedal pads J402 at the right of the rear edge (T, RN, R, S), PESD5V0S2BT and the
   ring 1k/10n filter on the board as drawn.
6. **Mechanical**: four M3 holes; outline; cover plate reference points (J401 position
   for the display loom run, J403 for the encoder loom, LED, the USB-C face and the
   wire exits) exported as a STEP so FreeCAD builds the console around the real
   geometry. Tallest part is now the bulk cap at 20 mm upright (22 mm dome in the
   cover); with the encoder and the jacks off the board, nothing else stands proud.
   The cover plate now carries the encoder and its shaft, the display, and whatever
   sockets the box gets, so the tolerance loop that used to run through the board
   runs through the print alone.

### Data Flow / Interaction

    rear   +--------------------------------------------------+
    y=0    |  [J101 2p] [USB-C]   [J201 4p]      [J402 4p]     |
           |   power     DFU       handpiece      pedal        |
           |  fuse P-FET TVS [470uF up]  gate drv FET TVS diode|
           |                                                   |
           |  buck 5V   crystal, caps    analog: shunt amp,    |
           |  LDO 3V3   [  STM32F411  ]  VIN div, NTC, pedal   |
           |                                                   |
           |  [J401 7p]                  [J403 4p]             |
    front  |   display loom               encoder loom   (M3)  |
    y=70   +--------------------------------------------------+
           x=0                95 x 70 mm, top view           x=95

    Every bracket except USB-C is a row of plated holes, not a part.

Top view as KiCad shows it and as the user sees the console from their seat: front edge
towards the user, rear edge with the looms and USB-C away from them, power pads at the left.
(The first draft drew this upside down, which mirrored left and right against the text.)

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
- **The idea**: JLC does the SMT only, the THT parts are soldered at home.
- **Status 2026-10-01**: partly adopted by Decision 9, for a different reason than
  this entry assumed. The connectors did not move to hand assembly, they stopped being
  parts at all; what Jan hand-solders is wire into holes, during box build, which he
  was going to do at the box end of every loom anyway.
- **Sharpest tradeoff as originally framed**: ten boards times eight parts, including
  a 6-pin Neutrik jack and a 12.5 mm capacitor, and the reproducibility rule of ADR
  0001 broken by hand. That objection still stands for C101, which is why the bulk
  capacitor stays a JLC insertion by default.
- **Bets on**: the THT fee being significant. For 10 boards it is tens of euros, and
  after Decision 9 it buys the insertion of one capacitor and one header.

### Socketed Blackpill on the production board
- Rejected in ADR 0001; unchanged.

### Larger board, everything on a comfortable 120 x 90 mm
- **The idea**: no placement pressure at all.
- **Optimizes for**: a first layout that succeeds at the first try.
- **Sharpest tradeoff**: the console grows, the printed cover plate approaches the
  K2 Max's comfortable single-piece size, and every extra square centimetre of a board
  ordered twelve times is paid for.
- **Bets on**: 110 x 70 mm being too tight. The rear edge was the constraint: jack
  14 mm, USB-C 9 mm, terminal 21 mm, Neutrik 19 mm, plus gaps = about 80 mm, which
  fits. Moot after Decision 9: the same rear edge now needs USB-C 9 mm plus three pad
  rows totalling 21 mm, and the board went the other way, down to 95 x 70.

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
  the encoder shaft. Since 2026-10-01 the encoder is mounted in the plate rather than
  passing through it, so that loop is now internal to the print. The display is
  likewise fastened to the print, at the price of one loom per unit.
- Everything on top means the top-side silkscreen must carry the assembly information
  as well as the connector labels.
- Decision 9 moves work from ordering to soldering. Five looms per box, about twenty
  joints at the board plus the box ends, times twelve boards, all done by Jan. That
  is the price paid for deleting four unverified footprints, the crimp tooling and
  most of the loose-parts order. It also removes the keying those connectors provided,
  so the silkscreen legend and a continuity check become load-bearing.
- The enclosure gains the encoder and the box sockets, and loses all but one of the
  tolerances that used to run between a board-mounted jack and a printed wall. The
  exception is USB-C, which is still soldered to the board and still has to line up
  with a hole in the printed rear wall. It is the one connector whose mating half is a
  cable nobody has to source, which is exactly why it stayed.

### Risks
- **JLC stock**: STM32F411CEU6 (819 in stock at the last check) can vanish.
  Mitigation: STM32F401CCU6 is pin compatible; check stock the day the order is
  placed. The encoder left this risk on 2026-10-01: it is no longer a JLC line item,
  so it can be bought from any seller in any quantity without touching the board.
- **Footprint errors on the THT connectors**: retired 2026-10-01 by Decision 9. The
  terminal, the barrel jack, the Neutrik and the encoder are no longer on the board,
  and their replacements are stock KiCad pad rows. What remains of this risk is the
  display loom's pin order, which is a wiring mistake and not a re-spin.
- **Soldered looms have no keying**: the connectors that are gone were also what
  stopped a loom going on backwards. Mitigation: pin 1 marked on the silkscreen of
  every row, the function legend printed beside it, the rows given different pad
  counts where they sit near each other, and Jan builds a wiring card for the box
  assembly. A reversed display loom puts +3V3 on GND; a reversed handpiece loom puts
  24 V on the NTC input. Both are worth a continuity check before first power-up, and
  the per-board test sheet gets that line.
- **CPL rotation**: JLC's part orientation convention differs from KiCad's for QFN,
  SOT-23-6 and diodes. Mitigation: review the JLC assembly preview image for every
  polarised or asymmetric part before confirming.
- **Autorouter rewrites the rules**: KiCadRoutingTools relaxes the minimums in the
  sibling `.kicad_pro` to whatever it built and then grades itself against them; in the
  trial it reported no violations on a board with 139 errors at the ADR rules. It also
  has no notion of intent: it ran a signal under the crystal and put the oscillator nets
  through vias. Mitigation: run it on a copy with `--escalation off --strict-sizes`,
  lock the critical copper and draw keepouts first, grade only with `kicad-cli pcb drc`
  against the committed `.kicad_pro`.
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
A: The cover gets a 22 mm dome over the capacitor. The footprint stays the KiCad 5 mm
radial and JLC's THT service inserts it upright, so the boards need no rework after
delivery. Bending the capacitor flat was the alternative: a lower cover, but one manual
operation on each of twelve boards and stressed leads; a horizontal-mount 470 uF is not
stocked at JLC. Decided 2026-09-17: dome.

**Q: How does the Neutrik jack's nut end up on the outside of the rear wall if JLC
solders the jack before the box exists?**
A: Obsolete since 2026-10-01. It was a real problem and Decision 9 dissolved it: no
board-mounted jack means no nose through a wall, no nut fitted around a soldered part,
and no dependency between the print's wall thickness and a connector's thread length.
Whatever socket the box gets is mounted in the print on its own and wired back to a
pad row, so the board and the enclosure stop constraining each other's tolerances.

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

- **Board size and rear-edge order.** Choice (2026-10-01): 95 x 70 mm, power / USB-C /
  handpiece / pedal from left to right as pad rows. Supersedes the 2026-09-17 choice
  of 110 x 70 with connector bodies, which was sized by the connectors. Alternative:
  100 x 70 if 95 fights the router. Cost to change later: before the first order,
  nothing; after, a re-spin and a new cover.
- **Cover plate over the PCB.** Choice: printed skin, PCB hidden. Alternative: PCB as the
  cosmetic face, ENIG finish, black solder mask, SMD on the bottom. Cost to change later:
  assembly side changes, so a re-order.
- **Bulk cap orientation.** Choice (2026-09-17): upright as delivered, dome in the
  cover. Alternative: bent flat after delivery. Cost to change later: cover print only.
- **Retiring the generator.** Choice: eeschema is truth from now on. Alternative: keep
  the generator and mirror layout-time schematic edits into `tools/sheets`. Cost to
  change later: none, the files stay in git.

### Known unknowns and how the plan absorbs them

- **Punch at 24 V**: default is the ADR 0001 power block as drawn; signal to pivot is
  the bench test saying steel needs more than 30 V. Layout order puts the power block
  last so the answer can arrive during layout.
- **THT footprints**: resolved 2026-10-01. Decision 9 removed every connector whose
  footprint was in doubt, so there is nothing left to measure and no loose part to
  order before layout. What replaced them are stock pad rows whose geometry is a
  drill size, not a part.
- **Display module pin order**: default GND VCC SCL SDA RES DC BLK, verified on the bench
  module in September; signal to pivot is a second module from the batch listing with a
  different silkscreen. The 12 modules for the class come from one listing in one order.
- **JLC part availability on order day**: default is the BOM as drawn; signal is a
  zero-stock line in the JLC BOM upload; fallbacks are listed per part in parts-*.md.

### The mechanical work

Component specs, in the order that lets unknowns land late:

1. **Project prep**: retire the generator (README note, verify.sh reduced to ERC +
   render; done 2026-09-17), enter the design rules of Decision 5 in the `.kicad_pro`,
   add mounting holes and outline to the schematic as symbols, run ERC, update the PCB
   from the schematic. The project-footprint import step is void since 2026-10-01: no
   custom footprints are needed any more.
2. **Outline and fixed parts**: 95 x 70 mm, M3 holes, USB-C on the rear edge line with
   its 3D model checked for clashes, the four pad rows placed at the edges their looms
   leave from, cover-plate cutouts derived from these positions and exported as a DXF
   reference. The cover plate also now carries the encoder and the box sockets, so the
   DXF has to name the loom exit points, not just the connector faces.
3. **MCU block**: QFN, decoupling, crystal, VDDA filter, SWD, BOOT0/NRST, USB-C with
   ESD and the differential pair, status LED. Route this block first, it has the most
   pins.
4. **Analog block**: shunt amp, VIN divider, NTC, pedal filters, all within the
   "quiet" zone between the driver and the MCU, referenced to the shunt's ground pad.
5. **Driver block**: gate driver, FET, flyback parts, handpiece pads, tight loop,
   drain island.
6. **Power block**: jack, fuse, P-FET, TVS, bulk cap, buck, ORing diodes, LDO. Placed
   last so the punch-test outcome can still change it.
7. **Ground pour and DRC**: bottom pour, top pour where it helps, thermal reliefs on
   THT, DRC with the rules in the Decision, review the ratsnest for zero unrouted.
8. **Exports**: Gerber + drill (JLC preset in kicad-cli), BOM (LCSC), CPL with
   rotation review, STEP, PDF assembly drawing with the pad-row pinouts, a per-board
   test sheet listing: loom continuity and orientation before first power-up, VIN and
   5 V / 3V3 rails, gate low at reset, DFU enumeration, display, encoder, pedal
   presence detect, one strike into a 141 ohm coil at 24 V.
9. **Order**: 12 assembled, 5 bare, loose parts (display modules, encoders and knobs,
   GX12 pigtails and plugs for the handpiece, hook-up wire, whatever the pedal
   question below settles on), all in one week. Shorter than the 2026-09-17 list: the
   XH housings, crimp contacts, ready-made ribbon leads and 4-pin screw plugs are all
   gone, and with them the XH-size crimp tool.

Review asks, answered by Jan on 2026-09-17:

1. Cover plate over a hidden PCB, or the PCB as the visible top face? -> cover plate.
2. Rear-edge order jack / USB-C / pedal / terminal, or pedal jack at the far right?
   -> pedal jack at the far right (board 110 x 70 mm). Superseded 2026-10-01: the
   connectors are pad rows and the board is 95 x 70.
3. Bulk cap bent flat after delivery, or a dome in the cover? -> dome in the cover.
4. Order the loose THT connectors for measurement before layout starts? -> yes.
   Superseded 2026-10-01: there are none to order.

Further direction from Jan, 2026-10-01: sourcing connectors is the problem, soldering
is not. Power in is two soldered wires; the handpiece keeps an easily sourced 4-way
connector on the box; the pedal gets a 3-way one on the box so the two cannot be
swapped; the display and the encoder go on soldered looms. Decision 9 implements this,
with the pedal's board side left at 4 pads so the socket question stays open.

---

## Open Questions

**Architecture-changers**
- [ ] Punch at 24-30 V confirmed on the bench with the real FET (blocks the power block).
- [x] Cover plate versus visible PCB (review ask 1): cover plate, 2026-09-17.

**Behavior definers**
- [x] Terminal drill and Neutrik normalling contacts measured on loose parts:
      dropped 2026-10-01, both parts are off the board (Decision 9).
- [ ] **Pedal socket.** Deliberately deferred; the board carries 4 pads that serve
      either answer. A bought expression pedal has a moulded 6.35 mm TRS plug, so it
      needs a TRS socket in the box wall, and the plugged-in detection of ADR 0001
      section 8 then works unchanged. A GX12-3 needs the pedals built or re-leaded and
      a redesigned detection: a pulldown on the wiper so an unplugged pedal reads
      heel-down and cannot fire, which is fail-safe but loses the "no pedal" message.
      Blocks: the box wall cutout, the loose-parts order, and one io.kicad_sch change
      if GX12 wins.
- [ ] **Keep JLC's THT assembly service?** After Decision 9 the only parts needing it
      are C101 and J302 (J301's four shell tabs are through-hole too, but that part is
      standard JLC SMT - confirm how they bill it when the order is placed). Options: keep it (default, no change); move C101 to an SMD 470 uF and go
      SMT-only, which needs a stock and ripple-rating check; or hand-fit C101 on 12
      boards, which breaks the ADR 0001 reproducibility rule for a tall electrolytic.
- [ ] How the cover holds the display module (pocket plus clips, or two M2 screws) and
      whether the glass needs a gasket. Now also: how it holds the encoder.
- [x] J3 part number: superseded 2026-10-01. J401 is a 1x7 2.54 mm pad row; the loom
      is plain hook-up wire soldered at the board end, so the XH housing, the crimp
      contacts and the crimp tool are all out of the project.
- [ ] Display loom length and wire gauge, and whether the module end keeps its 1x7
      female housing or is also soldered.
- [ ] BOOT0 and NRST through the rear wall or the bottom.

**Polish**
- Silkscreen wording on the rear edge (proposed: 24V + -, USB, HANDPIECE, PEDAL with
  per-pad function letters and a pin-1 mark on every row). With no keyed connectors
  left, this legend is the only thing standing between a builder and a reversed loom,
  so it is worth the board space.
