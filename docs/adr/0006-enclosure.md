# 0006 - Enclosure: printed wedge, tray plus cover, slide-in display

**Status**: Proposed (2026-10-19)
**Date**: 2026-10-19
**Amends**: ADR 0001 enclosure concept (board as top layer, cover skin), ADR 0003
cover-plate notes (12 mm cover, 22 mm dome over C101, status LED light pipe)

---

## Context

The board (ADR 0005) is 85 x 60 mm, 1.6 mm, 1.0 mm corner radius, all parts on the
top side, four M3 NPTH holes 3.2 mm at 4 mm from each corner (77 x 52 mm pitch).
Board coordinates below are KiCad coordinates: x 50..135 (left to right seen from
the front), y 50 (rear edge) .. 110 (front edge).

Rear edge, left to right: J101 power wire pads (60.5, 53.5), SW301 BOOT0 (72.5, 54.5),
SW302 RESET (81, 54.5), J301 USB-C (93, 54, mouth to the rear, 0.5 mm past the edge),
J201 handpiece pads (104.5, 53.5), J402 pedal pads (117, 53.5).
Front edge: J401 display pads (80, 106.5), J403 encoder pads (101.5, 106.5).
Tallest part: C101 470 uF, 12.5 mm diameter x 20 mm, upright at (56, 65).

The earlier concept (board as the top structural layer under a thin cover skin)
needed a dome over C101 and put the display directly over the board. Jan chose
(2026-10-19) a wedge instead, with the sockets split front and back and the display
sliding into a holder, because screwing a module with no mounting holes into a
bezel is a hassle in a class build. The printer is a Creality K2 Plus
(350 x 350 x 350 mm), so every part prints in one piece. CAD is FreeCAD, driven
through the CADPilot MCP; sources live in `Box/`.

## Decision

The enclosure is two printed parts, a **tray** and a **cover**, joined with four
M3 screws. The cover is a wedge: low at the front, high at the back, its top face
sloping toward the user. All dimensions are parameters (table below); the FreeCAD
model is driven from a spreadsheet with exactly these names.

### 1. Tray

- Flat floor, `WALL` thick, with four PCB bosses on the board's hole pattern. The
  board sits `STANDOFF` above the floor, fixed with M3 x 6 screws into M3 heat-set
  inserts in the bosses.
- The board is pushed to the rear: the rear wall's inner face is `USB_GAP` behind the
  board's rear edge, so J301 reaches the USB-C opening.
- In front of the board the tray continues for `FRONT_BAY` mm. That bay holds the
  handpiece socket body and the display holder that hangs under the cover.
- Low perimeter lip (`TRAY_LIP` high) that the cover's walls sit over, so the joint
  is not a straight line of sight to the board.
- The cover is screwed on from below: four M3 x 10 socket head screws go up
  through counterbores in the tray floor (heads 0.4 mm below the floor) into M3
  heat-set inserts at the bottom of the cover's corner columns. The cover top has
  no screw holes. The rear-left column sits `COL_RL_DY` in front of the rear wall,
  because the cable entry takes that corner.
- Rubber-foot recesses (10 mm diameter, 1 mm deep), `FOOT_INSET` from the edges,
  clear of the screw heads.

### 2. Cover

- Walls `WALL` thick on four sides, a sloped top at `TILT` degrees, front wall height
  `H_FRONT`, rear height following from the tilt and depth.
- Rear wall carries:
  - USB-C opening `USB_W` x `USB_H`, centred on J301 (x = 93) at the receptacle's
    centre height. This is the only opening that must line up with a board part.
  - No BOOT0/RESET holes: SW301/SW302 (TS-1187A) are top-press, so a paperclip
    through the wall cannot reach them. DFU is entered by holding the encoder push
    at power-up; anything worse means opening the box.
  - The pedal socket (GX12-3, decided 2026-10-19; same size as the handpiece
    socket, only the pin count keys them apart, so never GX12-4 here) on the
    right, above J402, its body and nut above the
    board's parts.
  - The brick cable entry in the left side gap (the board covers the floor under
    J101): a hole `CABLE_D` + 0.5 mm, and directly inside it a floor post with a
    cradle and a tie slot (`TIE_SLOT_W` x `TIE_SLOT_H`) as strain relief, so a pull
    on the cable never reaches the solder joints in J101. From the post the cable
    runs about 15 mm behind C101 to J101.
- Front wall carries the handpiece socket (GX12-4), in the front bay, placed to
  clear the display holder and the encoder body above it. The GX12 pigtail runs
  back to J201 under the cover (about 100 mm of wire).
- Sloped top carries, side by side, the display window on the left (over J401's side)
  and the encoder on the right (over J403's side).
- No dome: in the wedge, C101 (top about 20 mm above the board at the rear left) is
  under the high end of the cover.
- No ventilation: the board dissipates well under 1 W (buck, LDO, gate driver).

### 3. Display holder (part of the cover)

- Module (vendor drawing, 2026-10-19): PCB 27.5 x 39.0 x 1.2 mm, header (7 pins,
  2.54 mm, centred) 2.5 mm from one short edge with pin tails up to 1.5 mm on the
  front. Glass/backlight 26.16 x 29.22 mm, centred, 4.89 mm from both short edges.
  Active area 23.4 x 23.4 mm, 6.22 mm from the header edge (1.6 mm off the module
  centre, toward the header). Four M2 holes, 22.5 x 34.0 mm, 2.5 mm from the short
  edges. PCB + glass measured 3.1 mm, so the glass stack is 1.9 mm (LCD_T).
- Two U-rails on the underside of the sloped top, running along the 39 mm edges,
  long axis running up the slope. Rail slot depth `DISP_T` + 0.3 mm, rail lip
  `DISP_LIP` over the glass edge (inside the black border, outside the active area).
- The window in the top is the active area plus 0.5 mm per side, chamfered 45 deg on
  the outside so the screen reads at an angle.
- The module slides in from the lower (front) end, glass first, header last, until
  it hits an end stop at the upper end. The header end faces J401, so the 7-way
  loom is short. Two snap tongues cut from the top skin in front of the open rail
  end (`LATCH_DX` either side of the module centre, outside the header pins) flex
  up as the module passes and hook `LATCH_HOOK` over the module's PCB end edge.
  Tongue `LATCH_T` x `LATCH_L` x `LATCH_W`, freed by `LATCH_SLIT` slits; bending
  strain about 1.5 % for PLA/PETG. The slits show on the cover top. Assumes the
  header is centred on the short edge and nothing stands on the PCB face within
  1 mm of its corners - check on the real module.
- Picture orientation is set in firmware (`src/ui.rs`); 180/270 deg also needs an
  80 px offset, see ui.rs `OFFSET_X/OFFSET_Y`.

### 4. Encoder mount

- EC11 through the sloped top: round hole `ENC_BUSH` + 0.3 mm. The bushing
  (7.8 mm, 6 mm long, measured) is clamped with two nuts, one under the panel and
  one on top, which also sets the knob height; local top thickness `ENC_PANEL`
  2.0 mm. No anti-rotation slot: the inner nut holds the body off the panel.
- Under the panel a clear 13.5 mm circle, 3 mm deep (nut 10 mm AF x 2 mm, measured), so the inner nut can be
  turned.
- Knob clears the display window by at least 3 mm.

### 5. Status LED

- No light pipe. D301 is a firmware heartbeat, not a user signal; the screen shows
  status. D104 (power) is visible through the USB-C opening only. This drops the
  ADR 0003 light-pipe hole.

## Parameters

| Name | Value | Source |
|---|---|---|
| PCB_W x PCB_D | 85 x 60 mm | .kicad_pcb Edge.Cuts |
| HOLE_PITCH | 77 x 52 mm, 4 mm from corners | .kicad_pcb MH401-404 |
| SIDE_GAP | 9.5 mm | board edge to side wall, room for the rear columns |
| WALL | 2.4 mm | default (6 perimeters at 0.4) |
| STANDOFF | 6 mm | default |
| USB_GAP | 0.5 mm | J301 overhang |
| FRONT_BAY | 25 mm | default, check against GX12 depth |
| TRAY_LIP | 4 mm | default |
| TILT | 15 deg | default |
| H_FRONT | 35 mm | default, check against GX12 and display holder |
| USB_W x USB_H | 13 x 8 mm | default for a moulded plug, check |
| USB_Z | 1.6 mm | confirmed 2026-10-19 |
| GX12 hole | 12.2 mm, nut 15 AF, 20 mm deep | nominal, both sockets, measure |
| CABLE_D | 5.0 mm | confirmed 2026-10-19 |
| DISP_W x DISP_L | 27.5 x 39 mm | vendor drawing |
| BL_W x BL_L | 26.16 x 29.22 mm | vendor drawing |
| DISP_T | 3.1 mm (1.2 PCB + 1.9 LCD_T) | measured 2026-10-19 |
| DISP_ACTIVE | 23.4 x 23.4 mm, 6.22 mm from header edge | vendor drawing |
| DISP_LIP | 1.7 mm from the PCB long edge | active area starts at 2.05 |
| ENC_BUSH | 7.8 mm, 6 mm long | measured 2026-10-19 |
| ENC_PANEL | 2.0 mm | bushing length minus two 2 mm nuts |

## Consequences

- One print per part, no supports. The tray prints floor down. The cover prints
  with its sloped top flat on the bed (rotated 165 deg about X); printed on its wall
  rim instead, the 15 deg roof would need full supports. Design rule: nothing
  flatter than 60 deg from horizontal except bridges. Rail lip undersides, window
  chamfer, GX12 teardrops (flat hidden under the nut) and the cover boss
  gussets (65 deg) follow it; the tray counterbores get a 0.3 mm sacrificial
  layer that the screw pushes through.
- Cover screw bosses are short (COL_H 10 mm) at the cover rim, fused into the
  walls, not full-height columns.
- Model: `Box/enclosure.FCStd` with a `Params` sheet; `Box/build_enclosure.py`
  rebuilds geometry and exports from the sheet (a cell change needs a rerun).
  Cells beyond the table above (SIDE_GAP, ENC_KX, LATCH_*, TIE_*, COL_RL_DY,
  FOOT_INSET, ...) are documented in the sheet's comment column.
- Result with the defaults: 108.8 W x 90.3 D, 37.4 mm high at the front and
  61.6 mm at the rear. The encoder sits at KiCad x 108 (6.5 mm right of J403) so a
  20 mm knob clears the display window.
- The handpiece pigtail and the pedal socket wiring both cross the board under the
  cover; the cover height leaves room for that.
- Heat-set inserts (8 per box) are the only non-printed hardware besides M3 screws.

## Open items

- Measure: GX12 real hole, nut and body depth. USB_Z (1.6) and CABLE_D (5.0)
  confirmed by Jan 2026-10-19.
- J301 has no STEP model; the USB-C opening is placed from the real board until one
  is added.
- ADR 0004 (boost rail, Proposed) reserves 25 x 20 mm at the board's front left; if
  it lands, recheck heights under the display holder.
