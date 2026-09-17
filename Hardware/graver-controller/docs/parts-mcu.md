# Graver controller - MCU / USB / UI / connector part picks

Source data: JLCPCB catalog via jlcsearch (live, 2026-09-13), EasyEDA footprint API
(pad geometry of the LCSC parts), KiCad library at /usr/share/kicad (KiCad 10),
STM32F411 datasheet DocID026289 (WeAct mirror), ST STM32_open_pin_data
(STM32F411C(C-E)Ux.xml). Prices are jlcsearch unit prices (low-qty tier, USD); at
qty 20 they are the same or slightly lower. "Ext" = JLC Extended (one-time ~3 USD
feeder fee per unique part per order). Stock is LCSC/JLC stock at time of query.

## 1. Summary table

| # | Function | MPN | LCSC | Basic/Ext | Stock | Unit USD | Package | KiCad symbol | KiCad footprint |
|---|----------|-----|------|-----------|-------|----------|---------|--------------|-----------------|
| U1 | MCU | STM32F411CEU6 | C60420 | Ext | 819 | 3.66 | UFQFPN-48 7x7 | MCU_ST_STM32F4:STM32F411CEUx | Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.6x5.6mm (symbol default) |
| U1 alt | MCU fallback | STM32F401CCU6 | C79861 | Ext | 242 | 5.91 | UFQFPN-48 7x7 | MCU_ST_STM32F4:STM32F401CCUx | same |
| Y1 | HSE 25 MHz, 10 pF (preferred) | X322525MMB4SI (YXC) | C70582 | Ext | 67,449 | 0.104 | SMD3225-4P | Device:Crystal_GND24 | Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm |
| Y1 alt | HSE 25 MHz, 12 pF, 40 ohm | X322525MOB4SI (YXC) | C9006 | Basic | 236,320 | 0.104 | SMD3225-4P | Device:Crystal_GND24 | Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm |
| Y2 | LSE 32.768 kHz, 7 pF, 70k | SC-32S 32.768kHz 20PPM 7pF (Seiko) | C97604 | Ext | 131,335 | 0.187 | SMD3215-2P | Device:Crystal | Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm |
| Y2 alt | LSE 32.768 kHz, 6 pF, 70k | Q13FC13500049 (Epson FC-135) | C95361 | Ext | 132,940 | 0.208 | SMD3215-2P | Device:Crystal | Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm |
| J1 | USB-C 16P USB2.0 | TYPE-C-31-M-12 (HRO) | C165948 | Ext | 89,797 | 0.186 | SMD + THT shell | Connector:USB_C_Receptacle_USB2.0_16P | Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12 |
| R | CC pull-downs 5.1k x2 | 0603WAF5101T5E | C23186 | Basic | 3.7M | 0.002 | 0603 | Device:R | Resistor_SMD:R_0603_1608Metric |
| U2 | USB ESD | USBLC6-2SC6 (ST) | C7519 | Ext | 36,380 | 0.164 | SOT-23-6 | Power_Protection:USBLC6-2SC6 | Package_TO_SOT_SMD:SOT-23-6 |
| U2 alt | USB ESD (2nd-source listing) | USBLC6-2SC6 | C2687116 | Ext | 150,192 | 0.048 | SOT-23-6 | same | same |
| J2 | SWD 1x5 2.54 THT | PZ254V-11-05P | C492404 | Ext | 251,600 | 0.033 | THT | Connector_Generic:Conn_01x05 | Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical |
| SW1,SW2 | BOOT0, NRST tact | TS-1187A-B-A-B (XKB) | C318884 | Basic | 1.68M | 0.020 | SMD 5.1x5.1, top-actuated | Switch:SW_Push | Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A |
| SW3 | Encoder 24/24 + push (preferred) | PEC11R-4220F-S0024 (Bourns) | C143797 | Ext | 889 | 2.68 | THT vertical, 20 mm flatted shaft | Device:RotaryEncoder_Switch_MP | NOT in std lib - see notes (copy of Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm with MP moved) |
| SW3 alt | Encoder 30 det / 15 pulse + push | EC11E15244G1 (Alps) | C370970 | Ext | 5,515 | 2.26 | THT vertical, 20 mm flat shaft | Device:RotaryEncoder_Switch_MP | Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm |
| J3 | Display ribbon header 1x7, keyed, 2.5 mm | B7B-XH-A(LF)(SN) (JST) | C144398 | Ext | 11,035 | 0.117 | THT vertical | Connector_Generic:Conn_01x07 | Connector_JST:JST_XH_B7B-XH-A_1x07_P2.50mm_Vertical |
| J3 old | Display socket 1x7 2.54 | PM254V-11-07-H85 | C2832270 | Ext | 46,203 | 0.098 | THT, 8.5 mm | Connector_Generic:Conn_01x07 | Connector_PinSocket_2.54mm:PinSocket_1x07_P2.54mm_Vertical |
| J4 | DC jack 5.5x2.1 RA 3 A | DC-005-A200 (XUNPU) | C720557 | Ext | 76,247 | 0.144 | THT right angle | Connector:Barrel_Jack_Switch | Connector_BarrelJack:BarrelJack_Horizontal (compatible, see notes) |
| J5 | 6.35 mm TRS jack, switched | NMJ6HCD2 (Neutrik) | C368502 | Ext | 2,090 | 3.34 | THT horizontal, nut | custom (AudioJack3_SwitchTR + SN pin) | Connector_Audio:Jack_6.35mm_Neutrik_NMJ6HCD2_Horizontal |
| J6 | 4P 5.08 pluggable header, RA, closed | WJ2EDGRC-5.08-04P-14-00A (Kangnex) | C8446 | Ext | 14,588 | 0.096 | THT right angle | Connector_Generic:Conn_01x04 | Connector_Phoenix_MC_HighVoltage:PhoenixContact_MC_1,5_4-G-5.08_1x04_P5.08mm_Horizontal with drill enlarged (see notes) |
| (loose) | Matching 4P screw plug | WJ2EDGK-5.08-04P-14-00A (Kangnex) | C71372 | Ext (order as loose part) | 38,790 | 0.382 | plug | - | - |
| D1 | Pedal tip/ring ESD, 2-ch bidir | PESD5V0S2BT,215 (Nexperia) | C49338 | Ext | 28,300 | 0.125 | SOT-23 | Device:D_TVS_Dual_AAC | Package_TO_SOT_SMD:SOT-23 |
| D1 alt | same, cheap clone, 20 pF | PESD5V0S2BT | C5451656 | Ext | ~2-20k | 0.031 | SOT-23 | same | same |
| D2 | Status LED red | KT-0603R | C2286 | Basic | 8.1M | 0.007 | 0603 | Device:LED | LED_SMD:LED_0603_1608Metric |
| D3 | Power LED white (basic) | KT-0603W | C2290 | Basic | 2.2M | 0.012 | 0603 | Device:LED | LED_SMD:LED_0603_1608Metric |
| D3 alt | Power LED green (ext) | KT-0603G | C12624 | Ext | 366,908 | 0.012 | 0603 | Device:LED | LED_SMD:LED_0603_1608Metric |
| Q1 | Backlight N-FET | AO3400A | C20917 | Basic | 1.5M | 0.085 | SOT-23 | Transistor_FET:AO3400A | Package_TO_SOT_SMD:SOT-23 |

### MCU support passives (all JLC Basic)

| Qty | Use | Value | LCSC | Package |
|-----|-----|-------|------|---------|
| 1 | VCAP_1 (pin 22) | 4.7 uF X5R, ESR < 1 ohm | C19666 (CL10A475KO8NNNC) | 0603 |
| 1 | Bulk on one VDD pin | 4.7 uF | C19666 | 0603 |
| 4 | VDD pins 24, 36, 48 + VBAT pin 1 | 100 nF | C1525 (0402) or C14663 (0603) | 0402/0603 |
| 1 | VDDA (pin 9) | 1 uF | C15849 (CL10A105KB8NNNC) | 0603 |
| 1 | VDDA (pin 9) | 100 nF (or 10 nF per DS Fig. 43) | C1525 | 0402 |
| 1 | NRST (pin 7) to GND | 100 nF | C1525 | 0402 |
| 1 | BOOT0 (pin 44) pull-down | 10k | C25744 (0402WGF1002TCE) | 0402 |
| 1 | PB2/BOOT1 pull-down | 10k | C25744 | 0402 |
| 2 | HSE load caps for C70582 (CL 10 pF) | 12 pF C0G | C1547 | 0402 |
| 2 | HSE load caps for C9006 (CL 12 pF) | 15 pF C0G | C1548 | 0402 |
| 2 | LSE load caps for C97604 (CL 7 pF) | 10 pF C0G (gives CL ~8 pF, a few ppm slow - irrelevant) | C32949 | 0402 |
| 2 | Encoder A/B pull-up (+ push) | 10k | C25744 | 0402 |
| 1 | LED resistors | 1k | C21190 (0603WAF1001T5E) | 0603 |

Note: C25804 (0603 10k) showed 0 stock today; use the 0402 C25744 or recheck.

## 2. MCU notes

- **Stock/price**: F411CEU6 C60420 is the only LCSC listing, 819 pcs, 3.66 USD. The F401CCU6
  "cheaper fallback" is now *more* expensive on LCSC (C79861, 5.91 USD, 242 pcs). Keep the
  F401 as a pin-compatible paper fallback only; it is not a cost saver at JLC today.
- **VCAP_1**: DS Table 16: single-VCAP package -> CEXT = 4.7 uF, ESR < 1 ohm. (The 2x 2.2 uF
  figure in the DS applies to 100-pin packages with VCAP_2.)
- **Decoupling** (DS Fig. 14 note 2 + "Caution"): 100 nF per VDD/VSS pair, one 4.7 uF on
  one VDD pin, VDDA/VSSA its own 1 uF + 100 nF (DS Fig. 43 shows 1 uF + 10 nF; either is
  fine). On UFQFPN48 VREF+ is bonded to VDDA. Optional 0603 ferrite (~600 ohm @100 MHz)
  from 3V3 to VDDA - recommended since the ADC reads coil current and the pedal (live
  search for a basic bead timed out; pick one at schematic time).
- **Exposed pad (pin 49)** = VSS, must be soldered to GND with vias.
- **VBAT**: tie to 3V3 + 100 nF (no coin cell).
- **NRST**: internal pull-up RPU 30-50 kohm (DS Table 53); 100 nF to GND per DS Fig. 32
  "Recommended NRST pin protection". Button from NRST to GND.
- **BOOT0**: 10k to GND, button to 3V3. **PB2 = BOOT1** must be low at reset for the ROM
  bootloader (BOOT0=1, BOOT1=0 -> system memory); add a 10k pull-down (Blackpill does).
- **DFU gotcha**: the ROM bootloader also listens on USART1 (PA9/PA10). Noise on a floating
  PA10 can make it pick USART and ignore USB (known Blackpill DFU flakiness). Add a 10k
  pull-up on PA10 (or tie it to a defined level). AN2606 check for F411: USB DFU needs an HSE;
  25 MHz is what the Blackpill ships with and works.
- **USB**: OTG_FS has the internal D+ pull-up; no external pull-up or series resistors
  required.

## 3. Crystals - gm check (DS Table 37/38, AN2867 method)

gmcrit = 4 * ESR * (2*pi*f)^2 * (C0 + CL)^2, must be < Gm_crit_max.

- **HSE** Gm_crit_max = 1 mA/V (DS Table 37).
  - C9006 X322525MOB4SI: 12 pF, ESR 40 ohm (max), C0 assumed 1.5-3 pF ->
    gmcrit = 0.72-0.89 mA/V. Passes, but only ~1.1x margin at worst-case C0.
  - C70582 X322525MMB4SI: 10 pF, same series (ESR 40 ohm) -> 0.52-0.67 mA/V. Better margin;
    same price, extended. **Recommended.** (WeAct V3.1 uses a 9 pF 25 MHz with 8 pF caps,
    same idea.)
  - C2901685 SX3B25.000F1210F30 (12 pF, 30 ohm) is another good-margin option (0.54-0.67).
  - Do NOT use 18/20 pF 25 MHz parts: ~2 mA/V, fails.
  - Load caps: C1 = C2 = 2 * (CL - Cstray), Cstray ~3-4 pF -> 12 pF for CL 10, 15 pF for CL 12.
- **LSE** Gm_crit_max = 0.56 uA/V (low-power, default) / 1.50 uA/V (high-drive, LSEMOD=1).
  - JLC basic C32346 (12.5 pF, 70k): 2.2 uA/V -> fails in both modes. **Do not use.**
  - C97604 SC-32S 7 pF, 70k: 0.74 uA/V (0.94 with 10 pF caps) -> needs high-drive mode.
  - C95361 FC-135 6 pF, 70k: 0.58 uA/V -> marginal in low-power, fine in high-drive.
  - Firmware must set RCC_BDCR.LSEMOD = 1 before LSEON. (WeAct uses a 6 pF crystal.)
  - The ADR lists no RTC function (settings live in flash). LSE can be DNP to save an
    extended part; keep the footprint.

## 4. USB-C notes

- TYPE-C-31-M-12 (C165948) is the standard JLC USB-C: SMD signal pads + 4 THT shell tabs
  + 2 NPTH pegs, assembled routinely on the SMT line. KiCad pad names A1/A4/A5/A6/A7/A8/A9/A12,
  B1/B4/B5/B6/B7/B8/B9/B12, SH x4.
- Tie A6+B6 (D+) and A7+B7 (D-). CC1 (A5) and CC2 (B5) each get **their own** 5.1k to GND
  (one shared resistor breaks e-marked/C-C cables). SBU A8/B8 NC. VBUS A4/A9/B4/B9 together.
  Shell: to GND via 1M || 4.7 nF or direct - choose at schematic time.
- USBLC6-2SC6 pinout: 1 = I/O1, 2 = GND, 3 = I/O2, 4 = I/O2, 5 = VBUS, 6 = I/O1.
  Pin 5 goes to USB VBUS (5 V), not 3V3. Place between connector and MCU.

## 5. SWD - recommendation

Populate the 1x5 THT header (C492404, 0.03 USD). The board already needs THT assembly for
the encoder, jacks, socket and terminal, so the marginal cost is a few joints. Pin order
suggestion: 1 3V3, 2 SWCLK (PA14), 3 GND, 4 SWDIO (PA13), 5 NRST. Zero-cost alternative:
Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical pads (needs a ~40 USD cable);
not worth it for a class batch that will be flashed over USB DFU anyway.

## 6. Tact switches

TS-1187A-B-A-B (C318884, Basic) is top-actuated, 5.1x5.1x1.5 mm. KiCad footprint
SW_Push_1P1T_XKB_TS-1187A matches the LCSC land pattern (pads +/-3.0 mm, 3.75 vs 3.70 mm
pitch - fine). Pads 1-1 and 2-2 are internally paired. Since the PCB is the top face,
put them on the top side under two pin-holes in the bezel (paperclip access) - that keeps
them Basic and single-side assembly. If rear-edge access is required instead, a
right-angle SMD tact such as TS24CA (C393942, Ext, 444k stock, 0.025 USD) works but has
no KiCad std-lib footprint (import from EasyEDA/LCSC).

## 7. Encoder - no 20/20 part on LCSC

- Searched every EC11/PEC11 listing on JLC. **No 20 detent / 20 pulse part is stocked.**
- Datasheet facts: Alps EC11E18244A5 = **36 detents / 18 pulses** (Farnell/Alps);
  EC11E1834403 = 18 pulses, **no detent**; EC11E15244G1 = 30 detents / 15 pulses, 20 mm flat
  shaft, push switch. Most JLC "EC11" listings are 30/15.
- **Preferred: Bourns PEC11R-4220F-S0024** (C143797): 24 pulses / 24 detents (LCSC
  parametric "24/24" on the PEC11R-42xxF-S0024 family), 20 mm flatted 6 mm shaft, push
  switch. Detent == pulse, so the ADR rule holds (4 counts per detent in TIM x4 mode).
  Stock 889 - enough for 10 + spares, order early.
  Footprint gotcha: LCSC/EasyEDA land pattern: A-C-B at 2.5 mm, switch pins 5.0 mm apart,
  rows 14.5 mm apart (same as the KiCad Alps EC11E footprint), but **mounting lugs 12.0 mm
  apart** vs 11.2 mm in the KiCad Alps footprint (Alps EasyEDA: 11.0 mm). Make a project
  copy of RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm with the MP slots moved to
  +/-6.0 mm from the A-C-B centre line (or widened), and confirm with the Bourns PEC11R
  drawing.
- **Alternative: Alps EC11E15244G1** (C370970, 5.5k stock): drops straight into
  Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm. 30 detents / 15 pulses ->
  exactly 2 counts per detent in TIM3 x4 mode; firmware divides by 2 and there are no
  half-steps (rest states alternate 00/11, both at even counts).
- KiCad pin names on the footprint: A, C (common), B, S1, S2, MP.

## 8. Display socket

- **Superseded for the production board (ADR 0003, 2026-09-17; J401 in the schematic,
  swapped the same day):** the module is mounted
  in the cover plate and connects with a 7-way ribbon; J3 becomes a keyed 7-pin JST XH
  header, B7B-XH-A(LF)(SN) (C144398, 11k stock, 0.12 USD), same nets and pin order.
  **XH pitch is 2.50 mm, not 2.54**: use Connector_JST:JST_XH_B7B-XH-A_1x07_P2.50mm_Vertical,
  not a pin-header footprint. Cable side: housing XHP-7 (C144406), crimp contact
  SXH-001T-P0.6 (C140573, AWG 22-28). The module end is a 1x7 2.54 mm female ("Dupont")
  housing on the module's pin header; no LCSC part verified for it, a pre-crimped
  XH-7 to Dupont lead from a cable seller is the easier source. The notes below on pin
  order and BLK stay valid.
- PM254V-11-07-H85 (C2832270): 1x7 female, 8.5 mm body. With the module's male header the
  glass sits ~11 mm above the PCB - feed that to the bezel design.
- **Do not use a 1x8 with an extra pad.** The 8-pin variants of these modules insert CS
  *between* DC and BLK (GND VCC SCL SDA RES DC CS BLK), so a 1x8 footprint would not align
  BLK for either variant. Keep the 1x7 and route PA4 (CS) to a separate test pad, as the ADR
  says.
- Backlight gotcha: on most of these modules BLK drives an on-module transistor and is
  pulled up on the module (float = on). A low-side AO3400A on BLK then gives inverted PWM,
  and FET-off = full brightness. Check the actual module: PB6 may be able to drive BLK
  directly (drop Q1), or Q1 should switch the module's LED supply instead.

## 9. DC jack

- DC-005-A200 (XUNPU, C720557): 2.0 mm pin (fits 5.5x2.1 plugs), **3 A, rated 30 V**,
  right angle THT. 30 V covers the 24 V brick; it is below the ADR's 36 V upper operating
  limit - note it in the ADR or keep the brick spec at 24 V.
- EasyEDA land pattern: pins 1 and 2 are 6.0 mm apart on one line, pin 3 4.65 mm to the side,
  2.5 mm from pin 1; slots ~0.9 x 3.1 mm. KiCad Connector_BarrelJack:BarrelJack_Horizontal:
  pads at (0,0), (-6,0), (-3,4.7), 1 x 3 mm slots -> compatible (pin 3's 0.5 mm offset
  still lands in its 3 mm slot). Symbol Connector:Barrel_Jack_Switch: 1 = centre pin (+),
  2 = sleeve (-), 3 = switch. Confirm pin 1 = centre against the XUNPU drawing (the LCSC
  PDF is bot-blocked, so I could not fetch it).

## 10. 6.35 mm jack

- Neutrik NMJ6HCD2 (C368502, 3.34 USD, 2090 stock): 1/4" stereo, **3 switching contacts**
  (0.5 A / 50 V), 3 A main contacts, horizontal PCB, mounting nut included, rear panel
  mounting, panel < 4.7 mm.
- KiCad footprint pads: T (0,0), R (6.35,0), S (12.7,0) front row; TN, RN, SN rear row at
  16.23 mm. The EasyEDA land pattern has the same geometry (1.5 mm vs 1.4 mm drill).
- Pin functions: T = tip, R = ring, S = sleeve; TN / RN / SN = normalling (break) contacts
  that touch T / R / S with no plug and open when a plug goes in. (The Neutrik datasheet
  text confirms "switched, 3 switching contacts"; the contact drawing is graphic-only. Check
  one part with a meter before layout.)
- **Plug detect recommendation: use SN, not TN.** S = GND, SN -> GPIO (PB13) with pull-up:
  no plug = SN on GND = low, plug in = high. It does not touch the tip (wiper) or ring nets.
  Using TN would put the detect GPIO on the wiper/100k pull-up node and make both readings
  ambiguous. (Fallback if SN proves to be something else: RN -> GPIO with 100k pull-down,
  since the ring is fed from 3V3 through 330 ohm.)
- No KiCad std symbol has an SN pin (AudioJack3_SwitchTR has T, TN, R, RN, S). Make a
  project symbol = AudioJack3_SwitchTR + SN.
- Mechanical: the nut clamps the rear wall, so the jack nose must pass through the rear
  wall as the PCB goes in (split or open-backed enclosure).
- Cheaper generics exist (PJ-612 C309284, 0.53 USD; PJ-609/611/625 families) but their
  pinouts/footprints are unverified and not in KiCad. For 10 boards the Neutrik is the
  low-risk pick.

## 11. Handpiece terminal

- Header WJ2EDGRC-5.08-04P-14-00A (C8446) + plug WJ2EDGK-5.08-04P-14-00A (C71372), same
  maker (Ningbo Kangnex), mating pair. Order the plug as a loose part (10 + spares).
  No LCSC listing exists for "15EDGRC 5.08 4P" RA. The 15EDGK-5.08 plug (C49352919) has
  199 stock and costs 1.06 USD, so skip it.
- Footprint gotcha: the LCSC/EasyEDA land pattern uses **1.7 mm drill / 3.0 mm pads** at
  5.08 mm pitch. The KiCad Phoenix MC 1,5/4-G-5.08 footprint (same pitch, single row) has a
  1.2 mm drill, likely too tight for the Kangnex pins. Use a project copy with the drill at
  1.5-1.7 mm, and check the body overhang vs the board edge against the Kangnex drawing.

## 12. Pedal ESD, LEDs, FET

- PESD5V0S2BT pinout: 1 = line A, 2 = line B, 3 = common (GND) -> Device:D_TVS_Dual_AAC
  (common on pin 3). 5 V standoff suits 3.3 V tip/ring. No JLC Basic 2-ch SOT-23 TVS found.
  The genuine Nexperia part (C49338) is 35 pF; capacitance is irrelevant for a pot wiper.
- LEDs: only red (C2286) and white (C2290) exist as 0603 Basic today; green is Extended.
  Status LED on PC13 active-low: anode -> 1k -> 3V3, cathode -> PC13. PC13 can sink only
  ~3 mA (backup-domain pin), so keep the LED current <= 2 mA.
- AO3400A: 1 = G, 2 = S, 3 = D (SOT-23).

## 13. Pin map check vs STM32F411C(C-E)Ux (ST open pin data)

| ADR pin | ADR function | Signals on pin (ST data) | Result |
|---------|--------------|--------------------------|--------|
| PA8 | TIM1_CH1 | TIM1_CH1, MCO_1, I2C3_SCL, USART1_CK, OTG_FS_SOF, SDIO_D1 | OK |
| PB12 | TIM1_BKIN | TIM1_BKIN, SPI2_NSS, I2S2_WS, ... | OK |
| PB4 | TIM3_CH1 | TIM3_CH1, SYS_JTRST, SPI1/3_MISO, I2C3_SDA | OK (JTRST default - configure as AF2) |
| PB5 | TIM3_CH2 | TIM3_CH2, SPI1/3_MOSI, I2C1_SMBA | OK |
| PB6 | TIM4_CH1 | TIM4_CH1, I2C1_SCL, USART1_TX | OK |
| PA5 | SPI1_SCK | SPI1_SCK, ADC1_IN5, TIM2_CH1/ETR | OK |
| PA7 | SPI1_MOSI | SPI1_MOSI, ADC1_IN7, TIM1_CH1N, TIM3_CH2 | OK |
| PA1 | ADC1_IN1 | ADC1_IN1, TIM2_CH2, TIM5_CH2 | OK |
| PA2 | ADC1_IN2 | ADC1_IN2, TIM2_CH3, USART2_TX | OK |
| PA6 | ADC1_IN6 | ADC1_IN6, TIM1_BKIN, TIM3_CH1, SPI1_MISO | OK (analog mode, so its TIM1_BKIN / TIM3_CH1 AFs are unused) |
| PB0 | ADC1_IN8 | ADC1_IN8, TIM3_CH3, TIM1_CH2N | OK |
| PB1 | ADC1_IN9 | ADC1_IN9, TIM3_CH4, TIM1_CH3N | OK |
| PA4 | GPIO (CS) | SPI1_NSS, ADC1_IN4 | OK |
| PB7 | GPIO | TIM4_CH2, I2C1_SDA | OK |
| PB10/13/14/15 | GPIO | PB13/14/15 = TIM1_CH1N/CH2N/CH3N | OK as GPIO; never enable TIM1 complementary outputs in firmware |
| PC13 | LED | RTC_AF1 | OK (3 mA sink limit) |

**No mismatches.** All listed peripheral signals exist on the stated pins.

## 14a. Loose parts order before layout (ADR 0003 ask 4)

Checked on jlcsearch 2026-09-17. Two of each, for calipers and a paper-print fit check:

| Ref | Part | LCSC | Stock | USD | What to measure |
|---|---|---|---|---|---|
| J4/J101 | DC-005-A200 (XUNPU) | C720557 | 76,247 | 0.144 | pin slots vs BarrelJack_Horizontal, body overhang past the board edge |
| J6/J201 | WJ2EDGRC-5.08-04P-14-00A (Kangnex) | C8446 | 14,588 | 0.096 | pin diameter -> drill 1.5-1.7 mm, body overhang |
| (plug) | WJ2EDGK-5.08-04P-14-00A (Kangnex) | C71372 | 38,790 | 0.382 | mates with the header; order the class quantity here too (12) |
| J5 | NMJ6HCD2 (Neutrik) | C368502 | 2,090 | 3.34 | SN/RN/TN normalling contacts with a meter, nose length vs 3 mm wall |
| SW3 | PEC11R-4220F-S0024 (Bourns) | C143797 | 889 | 2.68 | lug spacing 12.0 mm, detent feel vs the Alps |
| SW3 alt | EC11E15244G1 (Alps) | C370970 | 5,515 | 2.26 | same, 30/15 part |
| J3 | B7B-XH-A(LF)(SN) (JST) | C144398 | 11,035 | 0.117 | height under the cover, keying direction vs pin 1 |
| (cable) | XHP-7 housing (JST) | C144406 | 12,111 | 0.042 | 15 pcs |
| (cable) | SXH-001T-P0.6 crimp (JST) | C140573 | 1.4M | 0.013 | 150 pcs, needs an XH-size crimp tool |

Not on LCSC: GX12 4-pin socket with pigtail and plug, display modules, encoder knobs,
XH-7 to 1x7 2.54 mm female ribbon leads (if bought ready made instead of crimped).

## 14. Recommended spec (ADR) changes

1. Encoder: change "20 detents / 20 pulses" to "detents == pulses (24/24 Bourns PEC11R)
   or detents == 2 x pulses (30/15 Alps EC11E) with the firmware divisor set to match".
   No 20/20 part is stocked at JLC.
2. LSE: add "RCC_BDCR.LSEMOD = 1 (high-drive)" with a 6-7 pF crystal, or mark LSE DNP.
   Never use the JLC basic 12.5 pF 32.768 kHz part.
3. HSE: specify a 25 MHz crystal with CL <= 12 pF (10 pF preferred) and ESR <= 40 ohm.
4. Pedal plug detect: use the sleeve-normal (SN) contact, not the tip switch.
5. Fallback MCU: the F401CCU6 is no longer cheaper at LCSC; keep it for pin compatibility only.
6. DC jack voltage rating: 30 V typical for DC-005-class jacks. Cap the brick at 24 V, or
   state the 36 V limit only for other connectors.
7. Display: keep a 1x7 socket and move CS to a test pad; verify the BLK behaviour before
   committing to a low-side FET.
8. Add a PA10 pull-up and a PB2 pull-down for reliable ROM-DFU entry.
