# 0004 - Settable Boost Coil Rail (24 V brick -> VIN..40 V) with Thermal Overdrive

**Status**: Proposed
**Date**: 2026-10-09

---

## Context

ADR 0001 sized the board for a 141 ohm coil fired straight from the brick: 24 V standard,
electronics rated 18-36 V. It listed an on-board boost rail as an alternative and left
open whether 24-36 V gives enough punch.

Bench results (2026-10-08/09, Blackpill + IBT-2 + the real coil, see `docs/bench-rig.md`):

- The full strike path works: TIM1 one-pulse, pedal/strength mapping, supply
  compensation, break input, watchdog. What remains for an MVP is software.
- At 24 V the hit is usable but soft. Force goes roughly with I^2 and the coil current is
  set by V/R (0.17 A at 24 V), so more punch means more volts, not a bigger brick.
- The user wants the drive voltage **settable** up to 36-40 V from the front panel, from
  the same small 24 V brick, and wants **overdrive** to be possible: an experienced
  engraver may run the coil above its rating and manage heat themselves. The handpiece
  carries an NTC on the coil body, so the firmware can enforce a hard thermal stop.

Constraints carried over from ADR 0001 / 0003:

- Input side stays as built: fuse, DMP6023LE reverse-polarity P-FET (-60 V), SMBJ36A,
  470 uF 63 V, LM5164 buck (100 V). The brick is still 24 V.
- Strike path stays: IRLR3410 (100 V) low side, UCC27517, 1 ohm shunt, TLV9062 x11 +
  ~0.8 A comparator into TIM1_BKIN, SS110 + SMBJ24A fast decay with SI2309 slow-decay
  bypass.
- Supported coils: >= ~100 ohm.
- The board is electrically complete (commit fbcd727). Adding a boost stage is a respin
  of the power section (ADR 0001 already priced it that way).

---

## Decision

Add a **boost converter between the protected input and the coil**, producing a
separate rail **VCOIL**, settable by firmware from VIN (boost idle) up to **40 V**, with
a **hardware ceiling of ~44 V** that firmware cannot exceed. Everything that used VIN
for the coil (COIL+ on J201, the fast-decay clamp return) moves to VCOIL. Logic, buck
and VIN sense stay on VIN.

Firmware treats VCOIL as the coil supply: compensation, power budget and the pre-fire
check use the measured VCOIL. Overdrive (running above the coil's 4 W continuous rating)
is allowed from a menu setting, but **only while a working NTC is present**; the NTC
hard limit is never bypassable.

The **36 V brick without boost** (Option 1 below) is documented as the fallback: it
needs no board change and covers most of the range if the boost slips.

---

## Architecture Overview

```
 brick 24 V -> fuse -> rev-pol P-FET -> SMBJ36A -> 470 uF = VIN
                                                     |
                     +-------------------------------+---------------+
                     |                               |               |
                LM5164 buck -> 5.28 V          BOOST (new)        VIN sense (PB0)
                (logic, unchanged)             VIN..44 V              |
                                                 |                    |
                     BOOST_EN (PB9) ------------>|                    |
                     BOOST_SET PWM (PB8) --RC--> FB injection         |
                                                 |                    |
                                              VCOIL ---- VCOIL sense (PA3)
                                                 |
                              J201 pin 1 COIL+ --+-- fast-decay clamp return (TVS anode)
                              J201 pin 2 COIL- -- IRLR3410 drain (unchanged)
                              J201 pin 3/4 NTC -- PB1 (now required for overdrive)
```

### Component Breakdown

1. **Boost stage** (new, power section of the schematic)
   - Topology: non-synchronous boost, external N-FET + Schottky. Controller class:
     TI LM5155 / LM51551 (2.2 MHz capable, VIN to 45 V, external FET, same vendor
     family as the LM5164). Integrated-switch parts with a 40 V switch (TPS61175 class)
     are rejected: no margin at 40 V out.
   - Rating: **0.4 A continuous at 40 V** (16 W out, covers a 100 ohm coil at 40 V and
     any duty), ~0.75 A input at 24 V. Power FET and diode >= 100 V; inductor sized for
     the controller's chosen frequency with >= 30% current headroom.
   - Output capacitance: >= 100 uF, **100 V-rated** (input surge passes through the
     boost diode while the SMBJ36A clamps at ~58 V, so 63 V parts are not enough), plus
     ceramic HF decoupling at the coil connector.
   - Bleeder: ~47k across VCOIL so a lowered setpoint decays within seconds without the
     coil (34 mW at 40 V).
   - Boost cannot go below VIN: with the setpoint at or below VIN the controller idles
     and VCOIL = VIN - one diode drop. "24 V" on a 24 V brick therefore means "boost off".

2. **Setpoint and ceiling** (feedback network)
   - FB divider alone sets the **ceiling, ~44 V**. This is the hardware maximum,
     independent of firmware.
   - BOOST_SET (PB8, TIM4_CH3, ~20 kHz PWM) through a 2-pole RC and a resistor into the
     FB node. The injection only pulls the output **down** from the ceiling, arranged so
     that **0% duty / pin low / MCU in reset = lowest output** and 100% = ceiling. A dead
     or resetting MCU therefore cannot drive VCOIL up.
   - BOOST_EN (PB9) drives the controller's EN/UVLO, 100k pulldown: boost off until the
     firmware enables it, off in reset, off while unprogrammed.
   - Pins: PB8, PB9 and PA3 are free on the current pin map (PB4/PA15-style JTAG
     gotchas do not apply). Verify against the AF table and the routed board before
     capture; PB8 shares TIM4 with the backlight (CH1), so both run at the same PWM
     frequency, which is fine for both.

3. **VCOIL sense** (new ADC channel)
   - Divider 100k / 6.8k to PA3 (ADC1_IN3), 100 nF at the pin: 51.8 V full scale, so a
     surge above the ceiling still reads instead of saturating.
   - VIN sense on PB0 stays and keeps its job (brick health, LOW VIN lockout).

4. **Strike path voltage budget** (unchanged parts, re-checked)
   - Drain peak in fast decay = VCOIL_max (44 V) + SMBJ24A clamp (~30 V at working
     current) + diode = **~75 V**, 75% of the IRLR3410's 100 V: inside the 80% derating
     used in ADR 0001.
   - Input-surge transient: as in ADR 0001, 58 V clamp + 30 V + diode = 86-97 V,
     transient-only exception, unchanged.
   - SI2309 (-60 V) sits across the TVS only and sees the clamp voltage, unchanged.
     BSS123 (100 V) level shifter sees VCOIL + clamp, ~75 V: OK.
   - Overcurrent comparator at ~0.8 A: a 100 ohm coil at 44 V draws 0.44 A, still 1.8x
     margin to the trip. Fuse stays on the input; it now carries boost input current
     (~0.75 A at full load), so the fuse rating is re-checked (>= 1.5 A slow).
   - TVS energy per strike rises with I^2: at 0.28 A and L = 100 mH, 3.9 mJ; 0.24 W at
     60 Hz. Inside SMB. Re-check once L is measured.

5. **Thermal sensing** (J201 pins 3/4, PB1, unchanged hardware)
   - The NTC becomes part of the standard handpiece build (glued to the coil body), not
     optional. Without it, overdrive is unavailable (see firmware).
   - Backup estimate: coil resistance from VCOIL / I_shunt during each pulse (copper
     ~0.39%/degC). Used to detect a detached NTC (NTC says cold, R says hot).

6. **Firmware: rail control** (`Firmware/graver-controller/src/`, new `boost.rs`)
   - Menu value **VCOIL target**, 24-40 V in 1 V steps, saved in flash.
   - Open-loop duty from a calibration curve, plus a slow integral trim on the PA3
     reading (tens of ms). The boost's own loop does the fast regulation; firmware only
     sets the reference.
   - **Pre-fire check**: no firing until VCOIL is within +-2 V of target (or of VIN when
     the target is <= VIN). VCOIL above ceiling + 2 V = fault, boost off, "VCOIL HIGH".
   - Enable sequence: boost enabled only after the self-check (gate low, break clear),
     disabled on any fault latch and on watchdog reset (pin defaults).

7. **Firmware: power budget and overdrive** (`control.rs`)
   - Compensation, duty and budget all use measured VCOIL instead of VIN.
   - **Normal mode** (default): average coil power `VCOIL^2 / R_coil * duty` <= 4 W
     (the coil's 24 V continuous rating). The fixed 35% duty cap stays as an upper
     bound. Raising VCOIL then buys a faster current rise and a harder hit per stroke at
     the same heat, with the duty limit tightening automatically.
   - **Overdrive mode** (menu, off by default, resets to off at power-up): the power
     budget is lifted; only the 35% duty cap and the NTC limit remain. Shown on the
     display as a permanent "OVERDRIVE" badge and the live coil temperature.
   - **NTC is mandatory for overdrive**: NTC open/shorted = overdrive refused, budget
     back to 4 W. NTC and R-estimate disagreeing by > 20 degC = treated as no NTC.
   - **Thermal limits, never bypassable**: warn at 60 degC, no firing at 70 degC,
     re-arm below 60 degC (existing `TEMP_MAX_C`, plus hysteresis).
   - Supply compensation keeps its meaning: on = volt-seconds of a 24 V supply (same
     feel at any VCOIL), off = raw pulse at VCOIL. With a settable rail, compensation
     on + higher VCOIL gives a shorter, sharper pulse with the same energy.

### Data Flow / Interaction

```
 menu: VCOIL target ----> boost.rs: duty = curve(target) + trim(PA3)
                                   |            ^
                                   v            |
                          BOOST_SET PWM -> FB -> VCOIL -> PA3 ADC
                                                 |
 analog task: VCOIL, VIN, NTC, I_shunt ----------+
                    |
                    v
 control.rs: armed = pedal ok && VIN ok && VCOIL in window && temp ok && !fault
             t_on  = strength -> compensation(VCOIL) -> min(duty cap,
                                                         power budget unless overdrive)
                    |
                    v
 strike.rs: TIM1 one-pulse (unchanged)
```

---

## Alternatives Considered

### Option 1: 36 V brick, no boost (documented fallback)
- **The idea**: keep the board as built and ship a 36 V brick instead of 24 V. The
  electronics are already rated 18-36 V; with the DC jack gone nothing else limits it.
  "Settable" comes from firmware: compensation on = 24 V-equivalent volt-seconds,
  off = full 36 V pulse, strength in between.
- **Optimizes for**: zero hardware change, no switching converter in a class batch.
- **Sharpest tradeoff**: the peak current is fixed at V/R = 0.255 A; firmware can
  shorten pulses but cannot lower the voltage or the current slope, and there is no path
  above 36 V. 36 V is also the SMBJ36A standoff: a brick that sits at 37-38 V starts
  leaking into the TVS, so the brick must be a tight 36 V part.
- **Bets on**: 36 V being enough punch for everyone, and a sourceable, tight-tolerance
  36 V brick. Firmware work is the same as this ADR minus `boost.rs` (power budget,
  overdrive with NTC, compensation off), so nothing written for it is wasted if the
  boost later lands.

### Boost to 48-60 V (ADR 0001's original sketch)
- **The idea**: a higher rail for maximum overdrive.
- **Optimizes for**: the hardest hit from a 24 V brick.
- **Sharpest tradeoff**: drain budget becomes 60 + 30 + 1 = ~91 V steady, which breaks
  the 80% derating of the 100 V FET and the BSS123; needs 150 V parts and a new
  clamp, and coil heating at 60 V (25 W on) makes overdrive dangerous even with an NTC.
- **Bets on**: 40 V not being enough. Revisit only if bench hits at 40 V are still soft.

### Separate external boost module (off-board, XL6009 class)
- **The idea**: a cheap adjustable boost module between brick and board.
- **Optimizes for**: no respin.
- **Sharpest tradeoff**: not settable from the front panel, a trimpot per box, a second
  enclosure item in a class batch, and the board's 36 V input rating caps it anyway.
- **Bets on**: users setting the voltage once and never touching it.

---

## Consequences

### Positive
- Punch becomes a front-panel setting from one standard 24 V brick.
- The hardware ceiling (FB divider) and the reset-safe PWM polarity keep a firmware bug
  from over-volting the coil.
- The strike path, its parts and its voltage budget stay valid; only the coil supply
  node moves.
- Overdrive is possible without removing the thermal stop.

### Negative
- Respin of the power section and of the board layout around it (ADR 0003).
- More parts per box (controller, FET, diode, inductor, caps, two dividers): roughly
  EUR 3-5 per unit at class quantity.
- Brick sizing goes up: ~16 W boost output + logic needs a **24 V >= 1.5 A** brick
  (the ADR 0001/HANDOFF sizing assumed direct drive).
- Another switching converter next to the analog front end (shunt amp, pedal, NTC).

### Risks
- **Boost noise into the shunt amplifier / comparator** -> false break trips. Mitigation:
  separate power-ground return for the boost, keep the boost loop away from the Kelvin
  shunt route, check with the scope on the bench prototype before layout freeze.
- **Overdrive cooks a handpiece** -> NTC mandatory, NTC/R cross-check, 70 degC stop,
  overdrive resets to off at power-up.
- **Reservoir dumps into a shorted cable** -> the overcurrent comparator still cuts the
  pulse within one TIM1 clock; the boost's own current limit caps the refill.
- **Setpoint below VIN** confuses users ("I set 20 V and it shows 23.5") -> the menu
  range starts at the measured VIN, rounded up.

---

## What an Expert Would Ask

**Q: What stops a firmware bug or a stuck PWM from putting 60 V on the coil?**
A: The FB divider sets an absolute ceiling of ~44 V that no PWM duty can exceed; the
injection only pulls the output down from that ceiling toward VIN. Reset or an
unprogrammed MCU means PWM low and BOOST_EN pulled low, i.e. boost off and VCOIL = VIN.
A failed boost controller that runs open-loop is not covered by the ceiling; the VCOIL
sense then trips "VCOIL HIGH" and disables firing and the boost, but the parts would
see the overvoltage until the controller's own OVP acts. Choose a controller with a
separate OVP pin and give it its own divider.

**Q: The boost can deliver 0.4 A, but a long strike at 40 V into 141 ohm draws 0.28 A
for 15 ms. Does the rail sag?**
A: A boost at 0.4 A continuous covers the steady coil current, so the reservoir only
covers the controller's loop response. 100 uF sags ~0.5 V in the first 200 us of a step
from 0 to 0.28 A, which the pre-fire window and compensation tolerate. If the chosen
controller is slower, more capacitance is cheap at 100 V.

**Q: Why let users overdrive at all? Who is liable for a burnt coil?**
A: Experienced engravers already overdrive solenoid gravers; refusing it pushes them to
external supplies with no thermal stop at all. Overdrive is off by default, resets at
power-up, is visibly flagged, and still stops at 70 degC on a verified NTC. A class
unit can be built with overdrive compiled out (feature flag) if the teacher wants that.

**Q: The NTC is glued to the coil body, but the winding is hotter than the body. Is
70 degC on the NTC safe?**
A: Not proven. The hot-spot lags and exceeds the body temperature, more so in short,
hard bursts. The coil-resistance estimate measures the average winding temperature and
reacts faster; the firmware should take the higher of the two. The 70 degC limit is a
starting value to be confirmed with a burst test (NTC vs R-estimate) on the bench.

**Q: Does a faster current rise at 40 V actually feel harder, or only hotter?**
A: The bet is yes: with compensation on, the same energy in a shorter pulse means a
sharper impact. Unmeasured until L is known (handoff open item: 1 ohm shunt, tau =
L/R). Bench test at 36-40 V with a bare 100 V FET before the schematic freezes.

---

## Implementation Plan

### Decisions you will probably want to tweak

- **Ceiling 44 V / menu max 40 V**
  - Alternative: 36 V ceiling (no change to anything downstream, less punch).
  - Cost to change later: a resistor value in the FB divider and a firmware constant;
    cheap until the drain budget is re-derived for a higher value.
- **Boost controller with external FET (LM5155 class)**
  - Alternative: integrated-switch boost with a 60 V+ switch, fewer parts.
  - Cost to change later: footprint change in the power section, before layout only.
- **NTC mandatory for overdrive, overdrive resets at power-up**
  - Alternative: overdrive persists across power cycles.
  - Cost to change later: one setting and one line in the settings loader.
- **Power budget 4 W in normal mode**
  - Alternative: per-handpiece profile (coil R and rated W from the menu).
  - Cost to change later: firmware only.

### Known unknowns and how the plan absorbs them

- **Coil inductance L**: default assumption 50-150 mH. Pivot signal: tau > 5 ms, which
  makes short pulses at 40 V pointless and argues for Option 1.
- **Is 40 V enough?**: default yes. Pivot signal: bench hits at 40 V still soft ->
  48-60 V alternative with 150 V parts.
- **Boost noise into the analog front end**: default "layout handles it". Pivot signal:
  false BKIN trips or noisy I_shunt on the prototype -> slower switching edges, lower
  frequency, or a pi filter on VCOIL.

### The mechanical work

- Schematic: boost stage, FB network with PWM injection, BOOST_EN pulldown, VCOIL sense
  divider, VCOIL net replacing VIN on J201 pin 1 and the TVS anode, fuse re-rate.
- Layout: power section re-placed (ADR 0003 rules: tight boost loop, separate return).
- Firmware: `boost.rs` (rail control, pre-fire window, faults), analog task gains
  VCOIL, `control.rs` switches compensation/budget to VCOIL and adds overdrive and the
  thermal hysteresis, UI shows VCOIL and the OVERDRIVE badge.
- Bench: lab PSU at 36-40 V + IRL540N + coil + NTC before capture; then a boost
  breakout (eval board) driven from the Blackpill's PB8/PB9/PA3.
- Docs: HANDOFF brick sizing (24 V >= 1.5 A), bench-rig, ADR 0001 alternative marked
  as taken up here.

### Review asks

1. Ceiling 44 V with a 40 V menu max: yes / lower to 36 V?
2. Overdrive resets to off at every power-up: yes / persist?
3. Respin now (before the first board order) or keep rev 1 as built with Option 1
   (36 V brick) and put the boost in rev 2?
4. Overdrive compiled into class units by default: yes / feature flag off for classes?

---

## Open Questions

**Architecture-changers**
- [ ] Respin now or rev 2 (review ask 3). Decides whether rev 1 ships with a 24 V or a
      36 V brick.
- [ ] Bench answer: does 36-40 V give a clearly harder hit than 24 V on this coil?

**Behavior definers**
- [ ] Thermal limit: 70 degC on the body NTC confirmed by a burst test against the
      R-estimate, or lowered.
- [ ] Brick: 24 V 1.5 A minimum; is a 2 A brick worth it for the inrush into the larger
      combined bulk capacitance?
- [ ] Controller with a separate OVP pin (expert question 1): pick the part on that basis.
