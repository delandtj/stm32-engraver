# Graver controller - capture netlist (draft, parts TBD from parts-power.md / parts-mcu.md)

All inter-sheet nets are GLOBAL labels. Power nets: VIN, +5V, +3V3, GND, VBUS.
Reference ranges per sheet: Power 1xx, Driver 2xx, MCU 3xx, IO 4xx.

## Power sheet (power.kicad_sch)

- J101 DC jack: TIP -> VIN_RAW, SLEEVE -> GND, switch pin NC.
- F101 fuse 1 A slow: VIN_RAW -> VIN_F.
- Q101 P-FET reverse polarity: D -> VIN_F, S -> VIN, G -> Q101_G.
- R101 100k: Q101_G -> GND.
- D101 zener 12 V: K -> VIN, A -> Q101_G.
- D102 TVS SMBJ36A: K -> VIN, A -> GND.
- C101 470 uF 63 V electrolytic: + VIN, - GND.
- C102 1 uF 100 V, C103 100 nF 100 V: VIN - GND.
- R102 100k: VIN -> VIN_SENSE. R103 8.2k: VIN_SENSE -> GND. C104 100 nF: VIN_SENSE - GND.
- U101 LM5164 buck, full reference design exactly as in parts-power.md (FB 340k/100k,
  RON 33k, ripple injection 150k + 3.3 nF + 100 pF C0G, CIN 2x 2.2 uF 100 V, COUT 2x 22 uF,
  BST 2.2 nF (NOT 100 nF), EN divider 1M/120k from VIN, L101 33 uH FXL0630-330-M):
  VIN -> +5V_BUCK, GND.
- D105 SS14: A +5V_BUCK, K +5V.   D103 SS14: A VBUS, K +5V.
- U102 AP2112K-3.3: VIN/EN -> +5V, VOUT -> +3V3, 1 uF in / 1 uF out (+ 10 uF on +3V3 bulk).
- D104 power LED + R104 2.2k: +3V3 -> R104 -> D104 A, D104 K -> GND.
- PWR_FLAG on VIN, GND, +5V, +3V3 (only here, nowhere else).

## Driver sheet (driver.kicad_sch)

- U201 gate driver: VDD -> +5V, GND -> GND, IN+ -> GATE_IN, IN- -> GND, OUT -> R201 10R -> GATE.
- R202 100k: GATE_IN -> GND.  R203 100k: GATE -> GND.
- C201 1 uF + C202 100 nF: +5V - GND at U201.
- Q201 N-FET 100 V: G -> GATE, D -> COIL_NEG, S -> SHUNT_HI.
- R204 1R 2512 1%: SHUNT_HI -> GND (Kelvin).
- Flyback: D201 fast diode: A -> COIL_NEG, K -> CLAMP.
  D202 TVS SMBJ24A: K -> CLAMP, A -> VIN.
- Decay bypass: Q202 P-FET -60 V: S -> CLAMP, D -> VIN, G -> Q202_G.
  R205 100k: Q202_G -> CLAMP.  D203 zener 12 V: K -> CLAMP, A -> Q202_G.
  R206 22k: Q202_G -> Q203_D.  Q203 BSS123 (100 V): D -> Q203_D, S -> GND, G -> Q203_G.
  R207 100R: DECAY_SLOW -> Q203_G.  R208 100k: Q203_G -> GND.
- Current amp U202A (dual op-amp, +3V3 / GND, C203 100 nF):
  R209 1k: SHUNT_HI -> U202A +IN.  C204 1 nF: +IN - GND.
  R210 10k: OUT_A -> -IN_A.  R211 1k: -IN_A -> GND.  (gain 11)
  R212 330R: OUT_A -> I_SENSE.  C205 10 nF: I_SENSE - GND.
- Overcurrent comparator U202B:
  R213 1k: SHUNT_HI -> +IN_B.  R214 1M: OUT_B -> +IN_B (hysteresis).
  R215 33k: +3V3 -> -IN_B (OC_REF).  R216 10k: OC_REF -> GND.  C206 100 nF: OC_REF - GND.  (~0.77 A)
  OUT_B -> OC_TRIP.
- J201 handpiece terminal 4-pin 5.08: 1 -> VIN (COIL+), 2 -> COIL_NEG, 3 -> NTC, 4 -> GND.
- R217 10k: +3V3 -> NTC.  C207 100 nF: NTC - GND.

## MCU sheet (mcu.kicad_sch)

- U301 STM32F411CEUx. VDD/VBAT pins -> +3V3; VSS/EP -> GND.
  C301-C304 100 nF (one per VDD), C305 4.7 uF bulk.
  VDDA: +3V3 -> FB301 ferrite -> VDDA; C306 1 uF + C307 10 nF: VDDA - GND.
  VCAP1 -> C308 (value per datasheet, expected 4.7 uF low ESR) -> GND.
  BOOT0 -> R301 10k -> GND; SW301 BOOT: BOOT0 -> +3V3 (via R302 1k).
  NRST -> C309 100 nF -> GND; SW302 RESET: NRST -> GND. NRST -> global NRST.
  PB2 (BOOT1) -> R303 10k -> GND.
  PA10 -> R307 10k -> +3V3 (keeps the ROM bootloader from picking USART1 over USB DFU).
  VBAT -> +3V3 with its own 100 nF.
  PH0/PH1 -> Y301 25 MHz (C70582, 10 pF load) + C310/C311 12 pF (C1547).
  No LSE crystal: PC14/PC15 no-connect.
  VDDA ferrite FB301: any JLC Basic 0603 ferrite (~600 ohm @ 100 MHz); find its LCSC number.
- Pin labels (global): PA1 PEDAL_TIP, PA2 PEDAL_RING, PA5 LCD_SCK, PA6 I_SENSE,
  PA7 LCD_MOSI, PA8 GATE_IN, PA11 USB_DM, PA12 USB_DP, PA13 SWDIO, PA14 SWCLK,
  PB0 VIN_SENSE, PB1 NTC, PB4 ENC_A, PB5 ENC_B, PB6 LCD_BL, PB7 ENC_SW, PB10 LCD_DC,
  PB12 OC_TRIP, PB14 DECAY_SLOW, PB15 LCD_RST, PC13 LED_STAT.
  All unused pins: no-connect flags.
- D301 status LED + R304 1k: +3V3 -> R304 -> D301 A, D301 K -> LED_STAT.
- J301 USB-C: VBUS -> VBUS; CC1 -> R305 5.1k -> GND; CC2 -> R306 5.1k -> GND;
  D+ (A6,B6) -> USB_DP_C; D- (A7,B7) -> USB_DM_C; GND/shield -> GND.
- U302 USBLC6-2SC6: I/O1 USB_DM_C <-> USB_DM, I/O2 USB_DP_C <-> USB_DP, VBUS -> VBUS, GND.
  (Flow-through: connector-side and MCU-side pins of each channel are the same net in USBLC6;
  so USB_DM_C == USB_DM electrically -- just one net each: USB_DM, USB_DP.)
- J302 SWD 1x5: 1 +3V3, 2 SWDIO, 3 SWCLK, 4 NRST, 5 GND.

## IO sheet (io.kicad_sch)

- J401 display header 1x7 female (C2832270): 1 GND, 2 +3V3, 3 LCD_SCK, 4 LCD_MOSI, 5 LCD_RST,
  6 LCD_DC, 7 LCD_BL_OUT. No CS.
- R401 100R: LCD_BL -> LCD_BL_OUT (module BLK pin has its own transistor on common modules;
  ADR deviation: no external backlight FET).
- SW401 encoder Alps EC11E15244G1 (C370970, 30 detents / 15 pulses; stock KiCad footprint
  Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm):
  A -> ENC_A, B -> ENC_B, C -> GND, S1 -> ENC_SW, S2 -> GND.
  R402/R403/R404 10k: +3V3 -> ENC_A / ENC_B / ENC_SW.  C401/C402/C403 10 nF: each -> GND.
- J402 Neutrik NMJ6HCD2 (C368502), symbol Connector_Audio:AudioJack3_SwitchTR (or closest with
  T, TN, R, RN, S): S -> GND; R -> PEDAL_RING_J; T -> PEDAL_TIP_J; RN (ring normal) -> GND;
  TN no-connect. SN pad exists on the footprint only, leave unconnected.
  (no plug: ring shorted to GND -> "no pedal"; mono plug: also ring = 0 V).
  R405 1k: +3V3 -> PEDAL_RING_J.  R406 1k: PEDAL_RING_J -> PEDAL_RING.  C404 10 nF: PEDAL_RING - GND.
  R407 100k: +3V3 -> PEDAL_TIP_J (footswitch pull-up).  R408 1k: PEDAL_TIP_J -> PEDAL_TIP.  C405 10 nF: PEDAL_TIP - GND.
  U401 PESD5V0S2BT (C49338), symbol Device:D_TVS_Dual_AAC: PEDAL_TIP_J, PEDAL_RING_J, common -> GND.
- MH401-MH404 M3 mounting holes (MountingHole:MountingHole_3.2mm_M3), not connected.
