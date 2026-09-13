# Power + solenoid-driver part picks (JLCPCB/LCSC)

Source spec: docs/adr/0001-graver-controller-board.md, sections 1, 2, 4, 5.
Stock and prices are live jlcsearch data from 2026-09-13. Price is the low-quantity
tier, which is about the qty-20 price. B = Basic, EP = Preferred Extended (no loading fee),
E = Extended (loading fee per unique part).
KiCad lib_ids were checked against the installed KiCad 10.0.6 libraries
(/usr/share/kicad/symbols, /usr/share/kicad/footprints).

## Main table

| # | Function | Pick (MPN) | LCSC | Class | Stock | $/pc | Package | Symbol lib_id | Footprint lib_id |
|---|----------|------------|------|-------|-------|------|---------|---------------|------------------|
| 1 | Fuse 1 A slow-blow | Littelfuse 0437001.WR (437 series, Slo-Blo, 63 V) | C99537 | E | 1,968 | 0.134 | 1206 | Device:Fuse | Fuse:Fuse_1206_3216Metric |
| 1b | Fuse fallback (1206) | JFC1206-1100TS (TS = time-lag, check datasheet) | C43323031 | E | 2,960 | 0.074 | 1206 | Device:Fuse | Fuse:Fuse_1206_3216Metric |
| 1c | Fuse fallback (2410, deep stock) | Littelfuse 0452001.MRL (Nano2 452, Slo-Blo, 125 V) | C44669 | E | 10,297 | 0.271 | 2410 | Device:Fuse | Fuse:Fuse_Littelfuse-NANO2-451_453 |
| 2 | Reverse-polarity P-FET | Diodes DMP6023LE-13 (-60 V, 35 mohm at -4.5 V, Vgs +-20 V) | C154901 | E | 28,081 | 0.553 | SOT-223 | Transistor_FET:Q_PMOS_GDS | Package_TO_SOT_SMD:SOT-223-3_TabPin2 |
| 2b | P-FET fallback | JSCJ CJQ60P05 (-60 V, 58 mohm at -10 V) | C504137 | E | 10,280 | 0.257 | SOP-8 | (no generic SO-8 P-FET symbol; see notes) | Package_SO:SOIC-8_3.9x4.9mm_P1.27mm |
| 2z | 12 V zener (Vgs clamp; reused in item 12) | BZT52C12 | C19077410 | EP | 589,587 | 0.015 | SOD-123 | Device:D_Zener | Diode_SMD:D_SOD-123 |
| 3 | Input TVS | SMBJ36A (unidirectional, 58.1 V clamp) | C19077588 | EP | 38,166 | 0.051 | SMB | Device:D_Zener (see notes) | Diode_SMD:D_SMB |
| 3b | TVS fallback | SMBJ36A (listed as unidirectional) | C114001 | E | 20,815 | 0.056 | SMB | Device:D_Zener | Diode_SMD:D_SMB |
| 4 | Bulk electrolytic | Rubycon 63ZLJ470M12.5X20 (470 uF 63 V, low-Z ZLJ) | C2940725 | E | 8,956 | 0.472 | THT radial 12.5x20, 5 mm | Device:C_Polarized | Capacitor_THT:CP_Radial_D12.5mm_P5.00mm |
| 4b | Bulk fallback | Aishi ERJ1JM471W25OT (31 mohm, 2.46 A ripple) | C106569 | E | 3,211 | 0.254 | THT radial 12.5x25 | Device:C_Polarized | Capacitor_THT:CP_Radial_D12.5mm_P5.00mm |
| 4c | 100 nF 100 V ceramic | Samsung CL21B104KCFNNNE X7R | C28233 | B | 243,637 | 0.031 | 0805 | Device:C | Capacitor_SMD:C_0805_2012Metric |
| 4d | 1 uF 100 V ceramic | Yageo CC0805KKX7R0BB105 X7R | C5370002 | E | 508,436 | 0.060 | 0805 | Device:C | Capacitor_SMD:C_0805_2012Metric |
| 5 | 5 V sync buck | TI LM5164DDAR (6-100 V in, 1 A, sync COT) | C477928 | E | 6,260 | 1.360 | SO-8 PowerPAD (DDA) | Regulator_Switching:LM5164DDA | Package_SO:HSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.1mm_ThermalVias (symbol default) |
| 5b | Buck fallback A | TI LMR36006AQRNXRQ1 (60 V, 0.6 A, 400 kHz) | C1850338 | E | 2,995 | 1.531 | VQFN-12 2x3 HotRod | none in KiCad lib; draw a custom symbol | Package_DFN_QFN:Texas_RNX0012C_VQFN-14-11-1EP_2x3mm_P0.5mm_EP0.25x1.825mm (check against the RNX land pattern) |
| 5c | Buck fallback B (non-sync) | TI TPS54360BDDAR (60 V, 3.5 A, needs a 60 V Schottky) | C524806 | E | 31,101 | 0.745 | SO-8 PowerPAD | Regulator_Switching:TPS54360DDA | Package_SO:TI_SO-PowerPAD-8_ThermalVias |
| 5L | Buck inductor 33 uH | Changjiang FXL0630-330-M (Isat 2.5 A, 310 mohm, molded) | C177245 | E | 228,367 | 0.096 | 7x6.6 mm | Device:L | Inductor_SMD:L_Changjiang_FXL0630 |
| 5Lb | Inductor fallback | Changjiang FNR6045S330MT (1.6/1.8 A, 178 mohm) | C168083 | E | 6,120 | 0.068 | 6x6 mm | Device:L | Inductor_SMD:L_Changjiang_FNR6045S |
| 6 | 3.3 V LDO (recommended) | Diodes AP2112K-3.3TRG1 (600 mA, 250 mV dropout at 600 mA, 6 V max) | C51118 | E | 79,480 | 0.158 | SOT-23-5 | Regulator_Linear:AP2112K-3.3 | Package_TO_SOT_SMD:SOT-23-5 |
| 6b | 3.3 V LDO (Basic option) | AMS1117-3.3 | C6186 | B | 2,007,447 | 0.200 | SOT-223 | Regulator_Linear:AMS1117-3.3 | Package_TO_SOT_SMD:SOT-223-3_TabPin2 |
| 7 | ORing Schottky (x2) | SS14 (40 V 1 A, 0.55 V at 1 A) | C2480 | B | 2,818,967 | 0.017 | SMA | Device:D_Schottky | Diode_SMD:D_SMA |
| 8 | Low-side gate driver | TI UCC27517DBVR (4 A/4 A, TTL inputs) | C99395 | E | 67,575 | 0.296 | SOT-23-5 | Driver_FET:FAN3111C (same pinout; no UCC27517 symbol in lib) | Package_TO_SOT_SMD:SOT-23-5 |
| 8b | Driver fallback | UMW UCC27517DBVR clone | C20623191 | E | 45,497 | 0.135 | SOT-23-5 | Driver_FET:FAN3111C | Package_TO_SOT_SMD:SOT-23-5 |
| 9 | Solenoid N-FET | Infineon IRLR3410TRPBF (100 V, 125 mohm at 5 V, 155 mohm at 4 V, Vgs +-16 V) | C3017 | E | 9,663 | 0.418 | DPAK | Transistor_FET:Q_NMOS_GDS | Package_TO_SOT_SMD:TO-252-2 |
| 9b | N-FET fallback | Prisemi PTD15N10 (100 V, 82 mohm at 4.5 V) | C479050 | E | 20,499 | 0.138 | DPAK | Transistor_FET:Q_NMOS_GDS (check pinout) | Package_TO_SOT_SMD:TO-252-2 |
| 10 | Flyback diode | SS110 (100 V 1 A Schottky, 0.85 V at 1 A) | C18199178 | EP | 19,866 | 0.021 | SMA | Device:D_Schottky | Diode_SMD:D_SMA |
| 10b | Flyback fallback | ES1D (200 V 1 A, 35 ns) / US1M (Basic, 1000 V, 75 ns) | C18199158 / C412437 | EP / B | 106,118 / 2.48 M | 0.013 / 0.012 | SMA | Device:D | Diode_SMD:D_SMA |
| 11 | Flyback clamp TVS | SMBJ24A (unidirectional, 38.9 V clamp at 15.4 A) | C19077578 | EP | 40,505 | 0.053 | SMB | Device:D_Zener (see notes) | Diode_SMD:D_SMB |
| 12a | Decay-bypass P-FET | Vishay SI2309CDS-T1-GE3 (-60 V, 1.6 A, 450 mohm at -4.5 V) | C10493 | E | 117,166 | 0.132 | SOT-23 | Transistor_FET:Q_PMOS_GSD | Package_TO_SOT_SMD:SOT-23 |
| 12b | Level-shift N-FET | BSS123 (100 V, 200 mA) -- NOT 2N7002, see notes | C427379 | E | 163,429 | 0.017 | SOT-23 | Transistor_FET:BSS123 | Package_TO_SOT_SMD:SOT-23 |
| 12b' | (2N7002, Basic, only if the spec changes) | 2N7002 (60 V) | C8545 | B | 432,340 | 0.016 | SOT-23 | Transistor_FET:2N7002 | Package_TO_SOT_SMD:SOT-23 |
| 12c | Vgs zener | reuse BZT52C12 | C19077410 | EP | -- | -- | SOD-123 | Device:D_Zener | Diode_SMD:D_SOD-123 |
| 13 | Current shunt | FOJAN FRC1206F1R00TS (1 ohm 1% 0.25 W) | C2907374 | E | 2,054,685 | 0.011 | 1206 | Device:R | Resistor_SMD:R_1206_3216Metric |
| 14 | Dual op-amp | TI TLV9062IDR (RRIO, 10 MHz, 6.5 V/us, 1.8-5.5 V) | C398355 | E | 151,400 | 0.144 | SOIC-8 | Amplifier_Operational:TLV9062xD | Package_SO:SOIC-8_3.9x4.9mm_P1.27mm |
| 14b | Op-amp fallback | TI TLV9002IDR (RRIO, 1 MHz, 2 V/us) | C398360 | E | 64,618 | 0.128 | SOIC-8 | Amplifier_Operational:TLV9062xD (same dual SOIC-8 pinout) | Package_SO:SOIC-8_3.9x4.9mm_P1.27mm |

Op-amp input offset: TLV9062 is +-0.3 mV typ, +-1.6 mV max at 25 C, +-2 mV max from -40 to
125 C (Vs = 5 V). TLV9002 is +-0.4 mV typ, about +-1.6 mV max. At gain 10, 1.6 mV is 16 mV
at the output: 0.6% of a 0.26 A full scale and 6% at 26 mA. That's fine for strike
monitoring and for an 0.8 A trip. I picked TLV9062 over TLV9002 because the comparator half
drives TIM1_BKIN, and 6.5 V/us responds several times faster than 2 V/us. Add hysteresis
(positive feedback) to the comparator half.

## Item 5 detail: LM5164 design for 5 V, 0.5 A, 18-36 V in (58 V transient)

Why LM5164 instead of LMR36006: it's rated 100 V (40+ V of margin over the 58 V TVS clamp,
where LMR36006 has 60 V), it's synchronous and good for 1 A, it comes in an SO-8 PowerPAD
that is easy to place and inspect, it has twice the stock (6.3k vs 3.0k), and it already
has a KiCad symbol (LMR36006 doesn't). The downside is that it's COT, so it needs a
three-part ripple-injection network.

Pins (SO-8 DDA): 1 GND, 2 VIN, 3 EN/UVLO, 4 RON, 5 FB, 6 PGOOD, 7 BST, 8 SW, EP -> GND
plane. FB reference is 1.2 V, internal soft-start is 3 ms, and peak current limit is
1.5 A typ (1.75 A max).

The datasheet reference design (Fig 7-1) is 12 V out at 1 A, 300 kHz, 68 uH, with
RFB1 453k / RFB2 49.9k, RRON 100k, CBST 2.2 nF, CIN 2x 2.2 uF 100 V, COUT 2x 22 uF, and a
Type-3 ripple network of RA 453k / CA 3.3 nF / CB 56 pF. I rescaled it for this board with
the datasheet equations (10, 12, 20, 24, 25, 26):

| Ref | Value | Why | Part (LCSC) |
|-----|-------|-----|-------------|
| RFB1 (VOUT to FB) | 340k 1% | VOUT = 1.2*(1+340/100) = 5.28 V (compensates the SS14 drop, item 7) | 0603 1% (any; 330k Basic gives 5.16 V) |
| RFB2 (FB to GND) | 100k 1% | TI recommends RFB1 of 100k-1M | C25803 (B) |
| RRON | 33k 1% | RRON[k] = VOUT*2500/Fsw[kHz] -> 400 kHz. tON = 0.37 us at 36 V, 0.23 us at 58 V (> 50 ns min) | 0603 1% |
| LO | 33 uH | dIL = 0.31 A p-p at 24 V, 0.34 A at 36 V (about 65% of 0.5 A); Ipk about 0.67 A; Isat 2.5 A > 1.75 A current limit | FXL0630-330-M C177245 |
| RA (SW to CA) | 150k | RA*CA <= tON*(Vin-Vout)/20 mV = 515 us at 24 V. Gives 19 mV FB ripple at 18 V, 23 mV at 36 V (spec: 12 mV min, 20 mV target) | C22807 (B) |
| CA (RA node to VOUT) | 3.3 nF X7R | >= 10/(Fsw*(RFB1 par RFB2)) = 323 pF; 3.3 nF keeps RA practical | C1613 (B) |
| CB (RA/CA node to FB) | 100 pF C0G | >= 75 us/(3*RFB1) = 74 pF. Must be C0G | C14858 (B) |
| CBST (BST-SW) | 2.2 nF 50 V X7R, exactly | Abs max 1.5-2.5 nF. A larger value damages the internal VCC regulator. Don't use 100 nF | C1604 (B) |
| CIN | 2x 2.2 uF 100 V X7R 1206 + 100 nF 100 V 0805 | Datasheet: >= 2.2 uF X7R rated 2x Vin max; the electrolytic from item 4 handles bulk | CL31B225KCHSNNE C170101 (E, 17.9k) + C28233 (B) |
| COUT | 2x 22 uF 25 V X5R 0805 | Datasheet example uses 2x 22 uF; >= 3 uF by eq 21 | CL21A226MAQNNNE C45783 (B) |
| EN/UVLO | 1M to VIN, 120k to GND | EN starts at 1.5 V -> start at about 14 V VIN, so the buck stays off while USB alone powers the 5 V rail. EN is rated to 100 V, so tying it straight to VIN also works | C22935 (B), C25808 (B) |
| PGOOD | NC, or 100k pull-up to 3V3 into a GPIO | open drain | -- |

LMR36006 values, in case you go with fallback 5b: the datasheet Table 1 for 5 V at 1 MHz
(B variant) is L = 15 uH, RFBT 100k, RFBB 24.9k, COUT 2x 15 uF, CIN 4.7 uF + 2x 220 nF,
CFF 20 pF, CBOOT 100 nF, CVCC 1 uF. The in-stock A variant (C1850338) runs at 400 kHz,
so it needs about 33 uH (the same FXL0630-330-M works). There's no KiCad symbol for it,
and its 2x3 mm HotRod QFN is harder to lay out.

## Item 6 detail: LDO

- AP2112K-3.3 pins (SOT-23-5): 1 VIN, 2 GND, 3 EN (tie to VIN), 4 NC, 5 VOUT. Caps: 1 uF
  minimum in and out per datasheet; use 10 uF 25 V 0805 CL21A106KAYNNNE C15850 (B) on each
  side.
- AMS1117-3.3 pins: 1 GND/ADJ, 2 VOUT (tab), 3 VIN. Caps: 10 uF in (C15850), 22 uF out
  (C45783). The datasheet asks for 22 uF tantalum; ceramic works in practice, but put the
  22 uF right at the pin.
- Why AP2112K: in USB-only mode the rail is VBUS (4.75 V worst case) minus the SS14 drop
  (about 0.35 V) = 4.4 V. AMS1117 needs about 1.0-1.1 V of headroom, which leaves it right
  at the edge of regulation. AP2112K's 250 mV dropout doesn't have that problem. On the
  brick the rail is about 4.93 V, and either part is fine. AMS1117 dissipates about 0.5 W
  at 300 mA, which SOT-223 handles.

## Item 7 detail: ORing topology (recommended)

    buck OUT (5.28 V) --|>|-- SS14 --+-- +5V rail (gate driver, LDO, display)
    USB VBUS          --|>|-- SS14 --+

- Use two Schottkys, one per source. Set the buck to 5.28 V (FB taken before its diode),
  so the rail is about 4.93 V on the brick.
- The diode after the buck blocks backfeed into the buck output when only USB is present.
  Without it, USB current would flow through the high-side body diode into VIN and part-
  charge the 470 uF bulk cap and the VIN sense divider.
- The diode on VBUS keeps the brick from driving VBUS/the laptop.
- With the brick connected, VBUS at 5.0-5.25 V can share load with the 4.93 V buck path. That's
  harmless: USB supplies less than 500 mA, and the rail is still the higher of the two.
  If you want the brick to always win, raise the buck to about 5.5 V (RFB1 = 360k). AP2112K
  (6 V max) and UCC27517 are both fine with that.
- UCC27517 UVLO: VON is 4.2 V typ, 4.5 V max at 25 C, and 4.65 V max over temperature. The
  4.93 V brick rail clears it. A 4.4 V USB-only rail may leave the driver in UVLO with its
  output held low. That's acceptable, because firmware refuses to fire below VIN = 15 V anyway.

## Pinout notes

- DMP6023LE-13 (SOT-223): pin 1 G, pin 2 D, pin 3 S, tab = D (standard Diodes Inc SOT-223
  MOSFET). Use it with Q_PMOS_GDS on SOT-223-3_TabPin2 (tab is pad 2). The datasheet PDF
  pin drawing is an image, so check it once by eye.
- IRLR3410 (DPAK): 1 G, 2 D (tab), 3 S. The KiCad TO-252-2 footprint has pads 1 and 3 on the
  leads and pad 2 as the big tab, which matches Q_NMOS_GDS.
- SI2309CDS and BSS123 (SOT-23): 1 G, 2 S, 3 D -> Q_PMOS_GSD / BSS123 (which extends
  Q_NMOS_GSD).
- UCC27517DBV: 1 VDD, 2 GND, 3 IN+, 4 IN-, 5 OUT. That matches Driver_FET:FAN3111C
  (VDD 1, GND 2, IN+ 3, ~IN- 4, OUT 5). Do NOT use UCC27511ADBV: it's SOT-23-6 with a
  different pinout. Tie IN- to GND. Input thresholds are VIN_H 2.2 V typ / 2.4 V max and
  VIN_L 1.0-1.2 V, independent of VDD, so 3.3 V logic drives it directly.
- Unidirectional TVS symbol: Device:D_TVS in KiCad 10 is BIDIRECTIONAL (pins A1/A2). The
  Diode:SM6T24A / SM6T36A symbols are unidirectional SMB parts with Diode_SMD:D_SMB, but
  their pins are also named A1/A2, so the cathode side is ambiguous. The pin-safe choice is
  Device:D_Zener (K = 1, A = 2; D_SMB pad 1 = cathode band), with Value set to SMBJ36A /
  SMBJ24A.
- C19077588 (SMBJ36A) has no LCSC description, so direction isn't stated. The MPN
  "SMBJ36A" without a C means unidirectional, but check the datasheet before ordering.
  C114001 is explicitly listed as unidirectional.
- The CJQ60P05 fallback is a standard SO-8 single P-FET (1-3 S, 4 G, 5-8 D). KiCad has no
  generic SO-8 P-FET symbol, so if you use it, make a small custom symbol. Better to stay
  with the SOT-223 DMP6023LE.
- LM5164 BST cap must be 2.2 nF (1.5-2.5 nF abs max). This catches people who copy a
  100 nF bootstrap cap from other bucks.
- TLV9062xD in KiCad extends NCS2325D (standard dual SOIC-8: 1 OUTA, 2 -INA, 3 +INA,
  4 V-, 5 +INB, 6 -INB, 7 OUTB, 8 V+). TLV9002IDR has the same pinout.

## Things I could not find / caveats

- There's no Basic or Preferred SMD slow-blow 1 A fuse. The best 1206 option (Littelfuse
  0437001.WR) has only 1,968 in stock. The JFC 1206 "TS" part has 2,960. The 2410 Littelfuse
  Nano2 0452001.MRL has 10k in stock and a KiCad footprint (Fuse_Littelfuse-NANO2-451_453);
  use it if the 1206 stock runs out. PTC resettables are everywhere, but they aren't what
  the spec asks for.
- There's no 12 V zener, 100 V Schottky, 100 V logic-level N-FET, or -60 V P-FET in the
  Basic library. The zener, flyback diode and TVSs are Preferred Extended, so no loading
  fee. US1M is Basic, but it's a 75 ns / 1.7 V part: it works, just slower than SS110.
- There's no 1 ohm 1% 1206 in Basic (FRC1206F1R00TS is Extended, 2M stock).
- There's no 60 V synchronous buck in Basic. LM5164, LMR36006, and LMR38010 (C5219310,
  80 V 1 A, 2.5k stock, no KiCad symbol) are all Extended.

## Spec changes I recommend

1. Level shifter: use a 100 V N-FET (BSS123), not a 2N7002. Its drain sits on the
   diode/TVS node through the gate pull-up, and that node reaches VIN + TVS clamp:
   36 + about 28 V = 64 V at working current, up to 36 + 38.9 = 75 V at the SMBJ24A's rated
   clamp. Both exceed the 2N7002's 60 V rating.
2. The "coils down to 30 ohm (1.2 A)" claim conflicts with three other blocks: the 1 A fuse,
   the 0.8 A overcurrent trip, and the 1 ohm 1206 shunt, which dissipates 1.44 W at 1.2 A
   against a 0.25 W rating. For the 141 ohm coil everything is fine (68 mW in the shunt at
   100% duty). Either narrow the spec to about 100 ohm minimum, or plan a 0.33 ohm 1 W 2512
   shunt with gain about 30, a 2 A slow fuse, and a trip threshold that scales with the coil.
3. Buck: name LM5164 as the primary part instead of LMR36006 (100 V rating, stock, SO-8,
   KiCad symbol). Add an EN/UVLO divider that starts the buck at about 14 V.
4. 5 V rail: use two-Schottky ORing with the buck set to about 5.3 V, and raise the LDO
   requirement to "dropout <= 0.5 V at 300 mA" so USB-only works (AP2112K).
5. Drain voltage budget: section 5 uses VIN_max = 36 V. During an input surge the TVS
   holds VIN at 58 V, and the flyback clamp adds about 28-39 V, giving 86-97 V at the
   drain. That's still under 100 V but at 86-97% of the rating, not 80%. It's acceptable
   only because surges are rare and brief. A 150 V FET would restore margin, but there are
   few logic-level 150 V DPAKs on JLC; I didn't search that further.
