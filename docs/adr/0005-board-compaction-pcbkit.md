# 0005 - Compact 4-layer board, laid out with pcbkit in the granite_controller style

**Status**: Accepted (2026-10-09, laid out on branch adr-0005-compact-4layer)
**Date**: 2026-10-09
**Amends**: ADR 0003 Decisions 3 (outline), 4 (layer use), 5 (design rules), 8 (layout method)

---

## Context

The board as of tag `pcb-pre-pcbkit` is electrically complete on 95 x 70 mm, 2 layers:
DRC 0 errors, 0 parity, 0 unconnected, 11 warnings (1 lib_footprint_mismatch J301,
4 track_dangling, 6 via_dangling). It works, but:

- It is loose. The 117 courtyards add up to about 1880 mm2 on a 6650 mm2 board (28 %).
  ADR 0003 Decision 3 chose 95 for routing headroom, not because the parts need it.
- It was reached by a project-specific pipeline (`Hardware/graver-controller/tools/pcb/`:
  place.py, autoroute.py, close_open.py, manual.json) with stale helpers
  (close_pairs.py) and a non-deterministic router (4-17 open pairs per run).
- The USB pair is not a controlled-impedance line. On 1.6 mm 2-layer FR4 the reference
  plane is 1.5 mm away, so 90 ohm is out of reach (ADR 0003, MCU block), and the pair
  already has one +5V crossing under it on the bottom layer, allowed by a whitelist.
- `../pcbkit` now holds the tools that produced the granite_controller board
  (~/Granite/Electronics/granite_controller), which Jan rates as the look to match.

The granite_controller design language, counted from its .kicad_pcb:

- 4 layers, JLC04161H-7628 stackup: F.Cu / B.Cu 1 oz, In1 = solid GND plane,
  In2 = solid +3V3 plane, no tracks on the inner layers.
- Straight segments only, 45-degree and orthogonal (no arcs, no teardrops), both outer
  layers carry signal, no strict H/V layer split.
- Few widths, used consistently: 0.2 signal, 0.4 GND/3V3, 0.5 5 V rails, heavier only on
  real power. Two via sizes only: 0.5/0.2 signal, 0.6/0.3 power and stitching.
- GND pours on both outer layers, inset 1.0 mm from the panel-rail edges, stitching vias
  in a re-runnable group (edge row every 4 mm, 5 mm grid).
- Functional blocks in clear bands, big parts anchored, passives packed per sheet.
- Silk: values on F.Fab, small-part refs hidden, remaining refs 1.0 mm / 0.15 mm,
  every connector labelled "J3 19V IN" style with 2-character pin legends.
- Graded with kicad-cli DRC only, never with the router's own checks.

ADR 0004 (boost coil rail, Proposed) adds a power stage that is not in the schematic yet.

---

## Decision

1. **Four layers, JLC04161H-7628.** In1.Cu = GND plane, In2.Cu = +3V3 plane, both solid
   and track-free. Outer layers carry parts (top only, ADR 0003 Decision 2 stands) and
   signals, with GND pours. This replaces ADR 0003 Decision 4: the shunt single-point
   ground rule moves to the In1 plane (R204's sense side joins GND only at the shunt,
   via its own via pair; no other GND via inside the Kelvin area), and the flyback loop
   stays a tight top-side loop, now 0.21 mm above solid ground instead of 1.5 mm.

2. **Outline: smallest rectangle that meets the acceptance criteria, target 75 x 55 mm,
   ceiling 85 x 60 mm.** 1 mm corner radius, four M3 holes 4 mm from the corners.
   The rear edge keeps its order (power pads, USB-C, handpiece pads, pedal pads); pad
   rows for display and encoder may move to the side edges if that buys area. The
   cover plate (enclosure print) follows the board, not the other way round.

3. **Rules (via pcbkit `setrules`, values in `Hardware/graver-controller/pcbkit.toml`):**

   | Item | Value |
   |---|---|
   | Board minimums | track 0.127, clearance 0.127, via 0.45 / annular 0.15, hole-to-hole 0.4, copper-to-edge 0.3 |
   | Default / signal | 0.2 track, 0.15 clearance, via 0.5/0.2 |
   | GND, +3V3 | 0.4, 0.2, via 0.6/0.3 |
   | +5V, VBUS | 0.5, 0.2, via 0.6/0.3 |
   | VIN, coil, flyback, buck SW | 0.8-1.0 as ADR 0003 Decision 5, via 0.6/0.3, several in parallel where current needs it |
   | Shunt Kelvin | 0.2, routed as a pair, no vias except at the op-amp |
   | USB (diff pair) | see Decision 4 |

   Two via sizes on the whole board: 0.5/0.2 and 0.6/0.3. No vias in SMD pads except
   the QFN48 EP thermal vias (`--same-net-pad-clearance 0.15` for the router).

4. **USB D+/D- as a 90 ohm differential pair.**
   - Surface microstrip on F.Cu over unbroken In1 GND, start from granite's 0.25 mm
     track / 0.15 mm gap and confirm with JLC's impedance calculator for
     JLC04161H-7628 before routing; the computed width/gap go into the USB net class.
   - Intra-pair length mismatch <= 0.15 mm over the whole run, connector pad to MCU
     pad, measured with KiCad's length tuner (meanders on the shorter leg, near the
     mismatch source). USB 1.1 full-speed does not need this; it is there so the same
     layout serves a high-speed part later.
   - No vias, no layer change, no other net crossing it on F.Cu or In1. The USB-C's
     A6/B6 and A7/B7 pads are joined under the connector with stubs as short as the
     footprint allows. USBLC6 placed in-line on the pair, not on a branch.
   - Impedance-controlled ordering at JLC is optional and decided on order day; the
     geometry is right either way.

5. **Tools: pcbkit, no project-specific router glue.** The board is built and checked
   with `../pcbkit` (mkboard, outline, setrules, krt-route / krt-reroute, viaout, prune,
   gndpour, silk, connlabels, jlcfab, render). The only project code is one placement
   script on `pcbtool.Placer` plus, where the router fails, scripted hand routes with
   `pcbtool.add_track` / `add_via` (the granite pattern). Fixes that are general go
   into pcbkit, not into project copies. `tools/pcb/` of ADR 0003 is retired; it stays
   reachable at tag `pcb-pre-pcbkit`. Every pcbnew save goes to a scratch directory,
   only the .kicad_pcb is copied back.

6. **Look: match granite_controller.** Straight 45-degree routing, the width and via
   set above and nothing else, outer GND pours with stitching, refs and connector
   labels by `silk` + `connlabels` (e.g. "J101 24V IN", "J201 HANDPIECE", "J402 PEDAL",
   pin legends + - / VI CN NT G and so on), values on F.Fab.

7. **ADR 0004 boost stage: reserved area.** Decided 2026-10-09 (Jan): the boost stage
   is not drawn yet (ADR 0004 is Proposed, controller unpicked, 24 V brick stays), so
   the board carries an empty rule area "ADR0004 boost reserve" of 25 x 20 mm at the
   front left (x 51.5-76.5, y 88.5-108.5 on the sheet, L-shaped around the MH403
   hole keepout), keepout for footprints, tracks, vias and pours on all four layers.
   It is sized from ADR 0004's part list (controller, FET, diode, inductor, 100 uF
   100 V caps, dividers). This is why the board sits at the 85 x 60 ceiling rather
   than the 75 x 55 target: without the reserve the same placement fits in about
   77 x 60.

---

## Component spec: the finished board

Acceptance criteria, all checked by tool output, not by eye:

- `kicad-cli pcb drc --schematic-parity --severity-all` after a zone refill:
  0 errors, 0 unconnected, 0 parity, warnings only from an explained, listed set
  (target: none).
- ERC: unchanged from the tagged state or better.
- Outline at or under the ceiling in Decision 2.
- In1 and In2 have no tracks; In1 is one connected GND region under the USB pair,
  the crystal and the analog front end (render check plus a scripted zone query).
- USB pair: net class geometry as computed, skew <= 0.15 mm, 0 vias, 0 crossings.
- Per-net width floors of ADR 0003 Decision 5 hold (re-use the floor check, as a
  pcbkit-side or project-script check).
- ADR 0003 placement rules still hold: crystal within 5 mm of OSC pins with its
  keepout, decoupling within 2 mm of VDD pins, buck >= 15 mm from ADC front end and
  crystal, gate driver within 5 mm of the FET gate, op-amp within 10 mm of the shunt.
- Only the two via sizes; only the widths in Decision 3.
- `jlcfab` produces Gerbers, drill, BOM and CPL with no unresolved "check" parts.
- Renders (`pcbkit render`) of the whole board and of the USB, power and driver
  areas committed under `Hardware/graver-controller/output/pcb/`.

---

## Alternatives Considered

### Keep 2 layers and only compact
- Cheaper per board (a few EUR at this quantity; confirm on order day).
- No reference plane close enough for a 90 ohm pair, the +5V crossing under USB stays,
  and every power rail competes with signals on the bottom. Compacting makes that
  worse. The granite look depends on the inner planes.

### Keep the existing tools/pcb pipeline
- It works and produced a clean board, but it is project glue around a
  non-deterministic router with per-geometry fixups. pcbkit is the same router with
  the lessons generalised; keeping two pipelines doubles the maintenance.

### Six layers / impedance stackup with thinner prepreg
- Nothing on this board needs it.

---

## Consequences

### Positive
- Smaller board and cover plate, a real 90 ohm USB pair, no split-ground risk,
  shorter and quieter flyback and buck loops.
- One toolchain shared with granite_controller.

### Negative
- 4-layer fab cost per board goes up.
- Full re-place and re-route; the 2-layer layout's verification work is redone.
- The enclosure print needs new dimensions.

### Risks
- KRT is not deterministic; budget hand routing for the last opens (granite needed it).
- A dense board puts the buck close to the analog front end; the 15 mm rule may set
  the floor on size before routing does.
- The USB-C footprint (lib_footprint_mismatch on J301 today) must be settled before
  the pair is length-matched to its pads.

---

## Open Questions

1. ~~ADR 0004 boost stage: schematic first or a reserved keepout area?~~ Decided
   2026-10-09: reserved keepout (Decision 7).
2. Is a 4-layer cost increase accepted for the 17-board order? Confirm on order day
   with JLC's quote; the layout does not depend on it.
3. ~~May the display and encoder pad rows move off the front edge?~~ Decided
   2026-10-09: yes, if it buys area. The placement kept them on the front edge
   (J401 centre, J403 right) because the width is set by the rear edge row.

## As built (2026-10-09)

Deviations from the text above, all deliberate:

- J302 (SWD) stands inside the board between the power block and the MCU, not on
  the rear edge: the rear edge is full with J101, SW301/SW302, J301, J201 and J402
  between the two hole keepouts. SW301/SW302 took its place on the rear edge.
- The crystal keepout blocks tracks on B.Cu only. Its own F.Cu tracks and the GND
  vias of its pads are scripted by `tools/pcb5/handroute.py`.
- The USB pair is scripted, not routed by KRT (route_diff.py cannot attach to the
  0.5 mm pitch USB-C pads): D+ pads joined above the pad row, D- pads below, an
  orthogonal detour on the D+ connector leg sized from the two leg lengths. Skew
  0.000 mm, 0 vias, F.Cu only.
- Width floors in `.kicad_dru` are half the class width (necking at pads), the
  per-net class-width count is reported by `tools/pcb5/check.py`.
- pcbkit gained three general fixes for this board (commits in ../pcbkit):
  krt-route keeps rule areas and the `[krt] keep_groups` groups, `[[krt.diff]]`
  takes `extra` flags.
