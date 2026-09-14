"""Driver sheet: handpiece connector, low-side MOSFET with gate driver,
flyback clamp with the slow-decay bypass, shunt amplifier and the
overcurrent comparator into TIM1_BKIN."""


def driver(sh):
    X = lambda s: sh.pin(s)[0]   # noqa: E731
    Y = lambda s: sh.pin(s)[1]   # noqa: E731

    # ---- handpiece terminal, pins pointing down: 1 VIN, 2 COIL-, 3 NTC, 4 GND --
    sh.place('J201', 83.82, 30.48, rot=90, ref_at=(74.93, 25.4), val_at=(74.93, 22.86))
    sh.w('J201.4', (X('J201.4'), 40.64), (93.98, 40.64))
    sh.pwr('GND', 93.98, 40.64)
    sh.w('J201.1', (X('J201.1'), 38.1), (73.66, 38.1))
    sh.glabel('VIN', (73.66, 38.1), rot=180)
    # NTC: pull-up to 3V3, RC to the ADC
    ny = 48.26
    sh.w('J201.3', (X('J201.3'), ny), (109.22, ny))
    sh.place('C207', 96.52, ny + 3.81)
    sh.pwr('GND', 96.52, ny + 7.62)
    sh.place('R217', 104.14, ny - 3.81)
    sh.pwr('+3V3', 104.14, ny - 7.62)
    sh.glabel('NTC', (109.22, ny))
    sh.text('optional NTC', 111.76, 43.18, 1.27)

    # ---- coil node, flyback column above the FET drain ------------------------
    cn = 63.5                                          # COIL_NEG line
    sh.w('J201.2', (X('J201.2'), cn), (142.24, cn))
    sh.label('COIL_NEG', (115.57, cn))
    sh.place('D201', 142.24, cn - 3.81, rot=270)       # A bottom on COIL_NEG, K top = CLAMP
    clamp = 55.88
    sh.place('D202', 142.24, 48.26, rot=90)            # K bottom = CLAMP, A top = VIN
    sh.w('D202.1', (142.24, clamp))
    vin = 40.64
    sh.w('D202.2', (142.24, vin), (134.62, vin))
    sh.glabel('VIN', (134.62, vin), rot=180)
    sh.label('CLAMP', (147.32, clamp))
    sh.text('fast decay: coil sees VIN + 24 V TVS at turn-off', 147.32, 30.48, 1.27)

    # ---- slow-decay bypass: P-FET shorts the TVS when DECAY_SLOW is high ------
    sh.place('Q202', 165.1, 48.26, mirror='y', ref_at=(160.02, 35.56), val_at=(160.02, 38.1))
    sh.w('Q202.3', (X('Q202.3'), vin), (142.24, vin))
    sh.w('Q202.2', (X('Q202.2'), clamp), (142.24, clamp))
    sh.w((X('Q202.2'), clamp), (185.42, clamp))
    sh.w('Q202.1', (193.04, Y('Q202.1')))
    sh.place('R205', 172.72, 52.07, rot=180)          # pin1 bottom on CLAMP
    sh.place('D203', 185.42, 52.07, rot=90)            # K bottom = CLAMP, A top = gate
    sh.place('R206', 209.55, 48.26, rot=90)            # pin1 left (gate), pin2 right
    sh.w((193.04, 48.26), 'R206.1')
    sh.place('Q203', 215.9, 53.34)
    sh.w('R206.2', 'Q203.3')
    sh.w('Q203.2', (X('Q203.2'), 60.96))
    sh.pwr('GND', X('Q203.2'), 60.96)
    sh.place('R207', 210.82, 60.96, rot=180, ref_at=(203.2, 59.69), val_at=(203.2, 62.23))
    sh.w('Q203.1', 'R207.2')
    sh.w('R207.1', (210.82, 68.58), (218.44, 68.58))
    sh.glabel('DECAY_SLOW', (218.44, 68.58))
    sh.w('Q203.1', (198.12, Y('Q203.1')))
    sh.place('R208', 198.12, 57.15)
    sh.pwr('GND', 198.12, 60.96)
    sh.text('DECAY_SLOW high: Q202 shorts D202, plain diode flyback', 147.32, 33.02, 1.27)

    # ---- gate driver and MOSFET -------------------------------------------------
    sh.place('U201', 101.6, 91.44, ref_at=(104.14, 80.01), val_at=(105.41, 100.33))
    gy = Y('U201.3')                                   # IN+ row
    sh.w('U201.3', (71.12, gy))
    sh.glabel('GATE_IN', (71.12, gy), rot=180)
    sh.place('R202', 81.28, gy + 3.81)
    sh.pwr('GND', 81.28, gy + 7.62)
    sh.w('U201.4', (88.9, Y('U201.4')), (88.9, 104.14), (101.6, 104.14))
    sh.w('U201.2', (101.6, 104.14))
    sh.pwr('GND', 101.6, 104.14)
    sh.w('U201.1', (101.6, 71.12), (83.82, 71.12))
    sh.pwr('+5V', 101.6, 71.12)
    sh.place('C201', 93.98, 74.93)
    sh.place('C202', 83.82, 74.93)
    sh.w((83.82, 78.74), (93.98, 78.74))
    sh.pwr('GND', 83.82, 78.74)
    sh.place('R201', 118.11, gy, rot=90)               # pin1 left from OUT, pin2 to gate
    sh.w('U201.5', 'R201.1')
    sh.place('Q201', 139.7, gy, ref_at=(146.05, 86.36), val_at=(146.05, 88.9))
    sh.w('R201.2', 'Q201.1')
    sh.place('R203', 127, gy + 3.81)
    sh.pwr('GND', 127, gy + 7.62)
    sh.w('Q201.2', (142.24, cn))
    # shunt and the SHUNT_HI tap to the sense block
    sh.place('R204', 142.24, 104.14)
    sh.w('Q201.3', 'R204.1')
    sh.pwr('GND', 142.24, 107.95)
    sh.w((142.24, 97.79), (152.4, 97.79), (152.4, 170.18))
    sh.label('SHUNT_HI', (152.4, 110.49), rot=90)
    sh.text('R204: Kelvin-route to R209/R213', 156.21, 104.14, 1.27)

    # ---- current amplifier (U202A, gain 11) --------------------------------------
    ay = 127
    sh.place('U202', 185.42, ay, unit=1, ref_at=(180.34, 118.11), val_at=(180.34, 135.89))
    sh.place('R209', 165.1, ay - 2.54, rot=90)         # pin1 left on SHUNT_HI
    sh.w((152.4, ay - 2.54), 'R209.1')
    sh.w('R209.2', 'U202.3')
    sh.place('C204', 170.18, ay + 1.27)
    sh.pwr('GND', 170.18, ay + 5.08)
    sh.w('U202.2', (175.26, Y('U202.2')), (175.26, 142.24), (181.61, 142.24))
    sh.place('R211', 175.26, 146.05)
    sh.pwr('GND', 175.26, 149.86)
    sh.place('R210', 185.42, 142.24, rot=270)          # pin2 left = AMP_INN, pin1 right = OUT
    sh.w('R210.1', (198.12, 142.24), (198.12, ay))
    sh.w('U202.1', (201.93, ay))
    sh.place('R212', 205.74, ay, rot=90)               # pin1 left
    sh.w('R212.2', (218.44, ay))
    sh.place('C205', 213.36, ay + 3.81)
    sh.pwr('GND', 213.36, ay + 7.62)
    sh.glabel('I_SENSE', (218.44, ay))
    sh.text('0.26 A -> 2.9 V at the ADC', 203.2, 119.38, 1.27)

    # ---- overcurrent comparator (U202B) -> TIM1 break -----------------------------
    cy = 172.72
    sh.place('U202', 185.42, cy, unit=2, ref_at=(180.34, 163.83), val_at=(180.34, 181.61))
    sh.place('R213', 165.1, cy - 2.54, rot=90)
    sh.w((152.4, cy - 2.54), 'R213.1')
    sh.w('R213.2', 'U202.5')
    sh.place('R214', 185.42, 162.56, rot=270)          # pin2 left = CMP_INP, pin1 right = OUT
    sh.w('R214.2', (172.72, 162.56), (172.72, cy - 2.54))
    sh.w('R214.1', (198.12, 162.56), (198.12, cy))
    sh.w('U202.7', (205.74, cy))
    sh.glabel('OC_TRIP', (205.74, cy))
    oy = 185.42
    sh.w('U202.6', (175.26, Y('U202.6')), (175.26, oy), (149.86, oy))
    sh.place('R215', 149.86, oy - 3.81)
    sh.pwr('+3V3', 149.86, oy - 7.62)
    sh.place('R216', 165.1, oy + 3.81)
    sh.pwr('GND', 165.1, oy + 7.62)
    sh.place('C206', 157.48, oy + 3.81)
    sh.pwr('GND', 157.48, oy + 7.62)
    sh.label('OC_REF', (168.91, oy))
    sh.text('trip ~0.77 A, 1M hysteresis', 203.2, 180.34, 1.27)

    # ---- op-amp supply --------------------------------------------------------------
    sh.place('U202', 246.38, 165.1, unit=3, ref_at=(248.92, 161.29), val_at=(248.92, 168.91))
    sh.w('U202.8', (246.38, 152.4), (256.54, 152.4))
    sh.pwr('+3V3', 246.38, 152.4)
    sh.place('C203', 256.54, 156.21)
    sh.pwr('GND', 256.54, 160.02)
    sh.w('U202.4', (246.38, 177.8))
    sh.pwr('GND', 246.38, 177.8)

    sh.translate(80.01, 30.48)
