# 0007 - Input protection: TPS26602 eFuse replaces fuse and reverse-polarity FET

**Status**: Accepted (2026-10-19), board rev 2 (branch board-rev2)
**Date**: 2026-10-19
**Amends**: ADR 0001 power input, ADR 0003 input-power block; supersedes the
F101 PTC swap of commit 71073a3 for rev 2 (the PTC stays the rework for rev 1)

---

## Context

Board 1 of the first batch blew F101 on its first 24 V connection. F101 was a
Littelfuse 0437001.WR, a fast 1 A fuse (0.100 A2s), and hot-plugging 24 V into
C101 (470 uF) is roughly 0.27-0.45 A2s. Rev 1 boards get a 1206 PTC
(1206L035/30WR) as a one-part rework. That survives the inrush, but nothing on
the board actually limits it: Q101 (DMP6023LE) only handles reverse polarity,
and its body diode conducts forward, so a soft-start on its gate would do
nothing. In a classroom the brick is plugged into a live socket many times.

Jan chose (2026-10-19) a real input protection IC over a discrete soft-start.

## Decision

The rev 2 input path is J101 -> U103 TPS26602PWPR -> VIN. U103 replaces F101,
Q101, D101 and R101. D102 (SMBJ36A), C101 (470 uF), C102/C103/C105/C106/C107,
the VIN sense divider R102/R103/C104 and everything downstream are unchanged
and stay on VIN (U103 OUT).

### Part

- TI TPS26602PWPR, HTSSOP-16 with PowerPAD, LCSC C2872872 (JLC extended).
  4.2-55 V operating, +/-60 V withstand, back-to-back internal FETs 150 mohm,
  reverse input polarity protection with no external parts, fixed 38 V output
  clamp (TPS26602 only), circuit-breaker / current-limit options, thermal
  shutdown.
- Datasheet: TI SLVSDG2G (TPS2660x), December 2019.

### Pins (HTSSOP-16)

| Pin | Name | Connection |
|---|---|---|
| 1, 2 | IN | J101 pin 2 (+24V), C108-new 100 nF 100 V to GND next to the pins |
| 3 | UVLO | RTN: internal default, UV rising 14.9 V typ (14.25-15.75) |
| 4, 13 | N.C | unconnected |
| 5 | OVP | RTN: selects the fixed 38 V clamp on the TPS26602 |
| 6 | MODE | RTN: current limit with auto-retry |
| 7 | SHDN | IN through 100k (always on; SHDN is rated to 62 V) |
| 8 | RTN | RTN island, see layout |
| 9 | GND | system GND |
| 10 | IMON | unconnected (floating is allowed) |
| 11 | ILIM | R_ILIM to RTN |
| 12 | dVdT | C_dVdT to RTN |
| 14 | FLT | unconnected (open drain, floating is allowed) |
| 15, 16 | OUT | VIN |
| PAD | PowerPAD | RTN island (never GND) |

RTN must never connect to GND: the reverse-polarity block sits between them,
and shorting them destroys the part on a reversed supply.

### Values

- Current limit: I_OL = 12 / R_ILIM(kohm). R_ILIM = 12k 1 % (JLC basic; 12.1k
  is extended only) -> 1.00 A.
  Worst-case peak load is 0.29 A (coil 170 mA + logic), so this is 3.4x
  headroom and still well under the 2 A brick.
- Inrush: t_ramp = 8e3 x V_IN x C_dVdT. C_dVdT = 220 nF X7R gives 42 ms at 24 V,
  so charging C101 takes 470 uF x 24 V / 42 ms = 0.27 A, below the 1 A limit.
  U103 dissipates about 12 V x 0.27 A = 3.2 W on average for 42 ms (0.14 J).
- UVLO default 14.9 V rising / about 13.8 V falling (0.925 x). This lines up
  with the LM5164 enable (about 14 V) and the firmware's VIN_MIN_FIRE_MV
  (15 V).
- OVP: fixed 38 V clamp. The brick is 24 V, and D102 clamps VIN at 36 V
  standoff.
- MODE to RTN gives current limiting with auto-retry. A short on VIN or a
  shorted coil FET holds the output at 1 A until thermal shutdown, then
  retries. No latch, so a student never needs to power-cycle.

### Layout

- U103 sits where F101/Q101/D101/R101 were, right behind J101 and before D102
  and C101. The current path is J101 -> IN, OUT -> D102/C101 at 0.8 mm
  (power_nets), short.
- RTN gets its own copper island on F.Cu under the IC, with the PowerPAD
  soldered to it and stitched with vias to an RTN island on B.Cu. No GND pour or
  inner-plane connection: inner planes keep out under U103, and RTN is a
  separate net from GND. R_ILIM, C_dVdT and the UVLO/OVP/MODE straps go to that
  island with the shortest traces.
- A 100 nF 100 V ceramic from IN to GND goes at pins 1/2 and 9, with a minimum
  loop.

## Consequences

- BOM: +1 extended part (TPS26602PWPR, about USD 2.3, plus JLC's extended-part
  fee) and 4 passives. -4 parts (F101, Q101, D101, R101).
- A hot-plugged brick now ramps VIN over about 42 ms. VIN is below 15 V for the
  first 25 ms, so the firmware briefly shows LowVin after plug-in, as it does
  today.
- A short anywhere on VIN is limited to 1 A and retried, instead of blowing or
  tripping a part.
- The 36 V electronics ceiling now also has the 38 V clamp behind it.

## Not done (possible later)

- FLT and IMON are not wired to the MCU. Both are referenced to RTN, not GND.
  If they are ever wanted on spare pins (PA0, PA3), check the RTN-GND offset
  first, and what the pins see on a reversed supply.
