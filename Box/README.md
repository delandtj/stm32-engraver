# Graver controller enclosure

Printed wedge enclosure for the graver controller board, per
docs/adr/0006-enclosure.md: a tray (floor, PCB bosses, lip) and a cover
(sloped top with display holder and encoder, sockets in front and rear walls),
joined with four M3 screws from below. The cover top carries only the display
window and the encoder; there are no screw heads on top and no poke holes (DFU
is entered by holding the encoder push at power-up).

## Files

- enclosure.FCStd - FreeCAD model: spreadsheet `Params`, solids `Tray`, `Cover`,
  `PCB` (reference board: slab, holes, C101, J301) and a `Checks` group
  (display module, encoder, GX12/GX16 keep-out bodies, board parts envelope).
  `PCB` and `Checks` are reference only and never exported.
- build_enclosure.py - regeneration macro. All geometry comes from `Params`.
- tray.stl, cover.stl - print-ready, already in print orientation.
- tray.step, cover.step - same parts in assembly position.
- preview-assembly.png, preview-cover-underside.png - screenshots.

## Changing the design

1. Open enclosure.FCStd in FreeCAD (1.0 or newer).
2. Edit the value in column B of `Params` (the cell alias is the name in
   column A, e.g. WALL, STANDOFF, TILT, H_FRONT, FRONT_BAY, DISP_T).
   Rows marked TBD in column C are placeholders: measure the real part.
3. Macro > Macros... > select build_enclosure.py (add Box/ as the user macro
   folder, or use "Execute macro" from the file) > Execute.
   The macro rebuilds Tray, Cover, PCB and Checks, prints the box size and a
   clearance table to the report view, rewrites the four export files and saves
   the document. Set `EXPORT = False` at the top to skip exports.
4. Check the clearance table: every "common" volume must be 0, except
   Tray/PCB and Tray/Cover which touch by design.

Display holder follows the vendor drawing of the 1.3 in module: PCB DISP_W x
DISP_L x DISP_PCB_T (27.5 x 39 x 1.2), backlight BL_W x BL_L at BL_Y0, active
area DISP_ACTIVE at AA_Y0 (window centred on the AA, 17.92 mm from the header
edge), header row HDR_Y with front pin tails HDR_FRONT (the top skin is
relieved over them), FPC_RELIEF at the far end. DISP_T is a formula
(DISP_PCB_T + LCD_T); LCD_T = 1.9 measured 2026-10-19 (module 3.1 total).

Cells most likely to change after measuring: DISP_ACTIVE, ENC_BUSH,
USB_Z, CABLE_D, GX12_D, GX16_D, GX12_NUT, GX16_NUT.
Display latch: LATCH_T, LATCH_L, LATCH_W, LATCH_HOOK, LATCH_DX, LATCH_SLIT
(the macro prints the tongue bending strain; keep it under about 2 % for PLA,
3 % for PETG). Cable entry: CABLE_Z, TIE_LEN, TIE_SLOT_W/H, COL_RL_DY.

The macro rewrites the sheet in its own order on every run and keeps the
values already in it; a cell whose alias the macro no longer uses is dropped.
Layout cells: DISP_KX, ENC_KX, GX12_KX, GX12_Z, GX16_KX, GX16_Z, CABLE_KX
(KiCad x coordinates or heights).

## Printing (Creality K2 Plus, 0.4 nozzle)

- Material: PETG preferred (insert heat, toughness); PLA works.
- 0.2 mm layers, 4 walls (the 2.4 mm walls come out solid), 20 % gyroid infill.
- Tray: as exported, floor on the bed. No supports. The foot recesses
  (10 mm discs) and the screw counterbores (6 mm discs) are flat bridges;
  each counterbore is closed by a 0.3 mm sacrificial layer (SAC_LAYER) over
  the screw hole - push the screw through it or open it with a 3.5 mm drill.
- Cover: as exported, upside down with the sloped top flat on the bed (the
  model is rotated 165 deg about X). No supports. The display rail lips
  have a 60 deg underside (LIP_ANGLE): the module PCB rests on the slope
  line at its edge. The window chamfer is 60 deg (WIN_CHAMF_ANGLE). The GX12
  and GX16 holes are teardrops pointing to the rim (TEARDROP_ANGLE 60),
  truncated flat 0.5 mm inside the nut's across-flats circle so the shape is
  hidden under the nut.
  The two latch tongues are part of the top skin (cut free by 0.6 mm slits,
  thinned to 1.4 mm from the inside) and their hooks grow straight up from
  them with the ramp facing up, so they need no supports either.
  The four cover screw bosses are short (COL_H = 10 mm) blocks at the rim,
  merged into the walls, with a gusset above them back into the side wall at
  GUSSET_ANGLE (65 deg from horizontal in print orientation).
  Everything flatter than 60 deg left on the cover is a bridge: USB-C
  opening top (13 mm), GX16 teardrop flat (8.0 mm), GX12 teardrop flat
  (5.8 mm), the 5.5 mm cable hole top.
  Footprint about 109 x 103 mm, 57 mm high.

## Hardware (per box)

- 8 x M3 heat-set inserts, hole 4.0 mm x 5.5 mm deep (e.g. M3 x 5.7 x 4.6
  short). 4 in the tray PCB bosses (from above), 4 in the bottom ends of the
  cover's screw bosses (pressed in from below, cover upside down).
- 4 x M3 x 6 screws: board to tray.
- 4 x M3 x 10 socket head screws (ISO 4762): cover to tray, from below. The
  head sits in a 6.0 x 3.4 mm counterbore, 0.4 mm below the floor; 5.0 mm of
  tray (floor + boss) is clamped, leaving 5 mm of thread in the insert.
  The rear-left screw is 30 mm in front of the rear wall, not in the corner:
  that corner holds the brick cable entry.
- 1 x cable tie, up to 2.5 mm wide, through the slot in the cable post just
  inside the rear-left cable hole.
- 4 x rubber feet, 10 mm dia, up to 1 mm recessed, 15 mm in from the edges
  (clear of the screw counterbores).
- GX12-4 panel socket (front), GX16-5 panel socket (rear right), encoder
  (7.8 mm bushing, 6 mm long) with two nuts, knob up to 20 mm dia.

## Assembly order

Inserts into the tray and the cover screw bosses, board onto the PCB bosses.
Encoder into the cover with one nut under the 2.0 mm panel and one on top
(no anti-rotation slot; the two nuts clamp it). The panel is thinned from
the inside over a 13.5 mm circle so the inner nut can be turned. Slide the display into the rails from the lower (front)
end, glass first, header last: the two hooks ride up over the glass, the
tongues lift out of the top by about 2.8 mm, and they click down behind the
module's PCB edge when it reaches the end stop. To remove it, lift both
tongues from outside (thin screwdriver in the slits) and slide it out. Mount
the GX sockets and solder the looms. Feed the brick cable through the
rear-left hole, lay it in the cradle on the post and tie it there before it
runs to J101. Lower the cover over the tray lip and screw it on from below.
