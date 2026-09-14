"""Power sheet, drawn as one left-to-right chain: barrel jack, fuse,
reverse-polarity P-FET, TVS and bulk caps, VIN sense, LM5164 buck to 5.28 V,
ORing diodes (buck / USB VBUS) into +5V, AP2112K LDO to +3V3, power LED."""


def power(sh):
    X = lambda s: sh.pin(s)[0]   # noqa: E731
    Y = lambda s: sh.pin(s)[1]   # noqa: E731
    rail = 53.34                                       # VIN rail

    # ---- input: jack, fuse, reverse-polarity P-FET ----------------------------
    sh.place('J101', 35.56, 55.88, ref_at=(27.94, 48.26), val_at=(27.94, 63.5))
    sh.nc('J101.3')
    sh.place('F101', 55.88, rail, rot=90)              # pin1 left
    sh.w('J101.1', 'F101.1')
    sh.w('J101.2', (48.26, Y('J101.2')), (48.26, 63.5), (50.8, 63.5))
    sh.pwr('GND', 48.26, 63.5)
    sh.pwr('PWR_FLAG', 50.8, 63.5)
    sh.place('Q101', 71.12, 55.88, rot=90, ref_at=(64.77, 46.99), val_at=(64.77, 49.53))   # D left, S right, G below
    sh.w('F101.2', 'Q101.2')
    sh.w('Q101.1', (71.12, 63.5), (78.74, 63.5))
    sh.place('R101', 71.12, 67.31)
    sh.pwr('GND', 71.12, 71.12)
    sh.place('D101', 78.74, 59.69, rot=270)            # K top to VIN, A bottom to the gate
    sh.w('D101.1', (78.74, rail))
    sh.w('Q101.3', (152.4, rail))
    sh.text('reverse polarity: body diode conducts, then Q101 turns on', 27.94, 78.74, 1.27)

    # ---- TVS, bulk, VIN sense --------------------------------------------------
    sh.place('D102', 93.98, 57.15, rot=270)            # K top on VIN, A to GND
    sh.pwr('GND', 93.98, 60.96)
    for x, ref in ((106.68, 'C101'), (121.92, 'C102'), (137.16, 'C103')):
        sh.place(ref, x, 57.15)
        sh.pwr('GND', x, 60.96)
    sh.place('R102', 152.4, 57.15)
    sh.w('R102.2', (166.37, 60.96))
    sh.place('R103', 152.4, 64.77)
    sh.pwr('GND', 152.4, 68.58)
    sh.place('C104', 160.02, 64.77)
    sh.pwr('GND', 160.02, 68.58)
    sh.glabel('VIN_SENSE', (166.37, 60.96))
    sh.text('36 V -> 2.73 V at the ADC', 152.4, 77.47, 1.27)
    sh.w((152.4, rail), (177.8, rail))
    sh.pwr('PWR_FLAG', 172.72, rail)
    sh.glabel('VIN', (177.8, rail))

    # ---- second row: LM5164 buck -------------------------------------------------
    r2 = 110.49                                        # VIN rail, row 2
    sh.glabel('VIN', (35.56, r2), rot=180)
    sh.place('U101', 107.95, 123.19, ref_at=(95.25, 109.22), val_at=(104.14, 109.22))
    sh.w((35.56, r2), (95.25, r2), 'U101.2')
    for x, ref in ((45.72, 'C105'), (60.96, 'C106'), (76.2, 'C107')):
        sh.place(ref, x, r2 + 3.81)
        sh.pwr('GND', x, r2 + 7.62)
    # EN divider 1M / 120k: starts at ~14 V
    sh.place('R105', 88.9, r2 + 3.81)
    sh.place('R106', 88.9, r2 + 16.51)
    sh.w('R105.2', 'R106.1')
    sh.w('U101.3', (88.9, Y('U101.3')))
    sh.pwr('GND', 88.9, r2 + 20.32)
    # RON
    sh.w('U101.4', (93.98, Y('U101.4')), (93.98, 133.35))
    sh.place('R107', 93.98, 137.16)
    sh.pwr('GND', 93.98, 140.97)
    sh.w('U101.1', (X('U101.1'), 140.97))
    sh.w('U101.9', (X('U101.9'), 140.97), (X('U101.1'), 140.97))
    sh.pwr('GND', X('U101.1'), 140.97)
    sh.nc('U101.6')
    # bootstrap, switch node, inductor
    sw = Y('U101.8')
    sh.place('C108', 128.27, Y('U101.7'), rot=90)      # pin1 left on BST
    sh.w('U101.7', 'C108.1')
    sh.w('C108.2', (132.08, sw))
    sh.place('L101', 142.24, sw, rot=90)               # pin1 left on SW
    sh.w('U101.8', 'L101.1')
    # ripple injection: R108 from SW, C109 to the output, C110 to FB
    sh.place('R108', 135.89, 128.27)
    sh.w('R108.1', (135.89, sw))
    rip = 132.08
    sh.w('R108.2', (151.13, rip))
    sh.place('C109', 151.13, 128.27, rot=180)          # pin1 bottom on RIPPLE, pin2 up to BUCK_5V
    sh.w('C109.2', (151.13, sw))
    fb = 139.7
    sh.place('C110', 143.51, 135.89)                   # pin1 RIPPLE, pin2 FB
    sh.w('U101.5', (125.73, Y('U101.5')), (125.73, fb), (161.29, fb))
    sh.place('R110', 133.35, 143.51)
    sh.pwr('GND', 133.35, 147.32)
    sh.place('R109', 161.29, 135.89)
    sh.w('R109.1', (161.29, sw))
    sh.label('BUCK_FB', (154.94, fb))
    sh.text('5.28 V set (340k/100k); BST cap is 2.2 nF, not 100 nF', 90.17, 157.48, 1.27)
    # output caps and ORing diode
    sh.w('L101.2', (198.12, sw))
    for x, ref in ((171.45, 'C111'), (186.69, 'C112')):
        sh.place(ref, x, sw + 3.81)
        sh.pwr('GND', x, sw + 7.62)
    sh.place('D105', 201.93, sw, rot=180)              # A left (buck), K right (+5V)

    # ---- +5V node: buck OR USB VBUS, then the LDO ------------------------------
    sh.w('D105.1', (240.03, sw))
    sh.pwr('+5V', 210.82, sw)
    sh.pwr('PWR_FLAG', 215.9, sw)
    sh.place('D103', 218.44, sw + 6.35, rot=270, ref_at=(210.82, 124.46), val_at=(210.82, 127))
    sh.w('D103.1', (218.44, sw))
    sh.w('D103.2', (218.44, 135.89), (210.82, 135.89))
    sh.glabel('VBUS', (210.82, 135.89), rot=180)
    sh.place('C113', 224.79, sw + 3.81)
    sh.pwr('GND', 224.79, sw + 7.62)
    sh.text('USB alone runs the logic (~4.6 V); firmware will not fire below 15 V VIN', 181.61, 157.48, 1.27)
    sh.place('U102', 247.65, 123.19, ref_at=(241.3, 113.03), val_at=(251.46, 135.89))
    sh.w('U102.3', (237.49, Y('U102.3')), (237.49, sw))
    sh.nc('U102.4')
    sh.w('U102.2', (X('U102.2'), 135.89))
    sh.pwr('GND', X('U102.2'), 135.89)
    sh.w('U102.5', (290.83, sw))
    for x, ref in ((262.89, 'C114'), (273.05, 'C115')):
        sh.place(ref, x, sw + 3.81)
        sh.pwr('GND', x, sw + 7.62)
    sh.pwr('+3V3', 290.83, sw)
    # power LED
    sh.place('R104', 283.21, sw + 3.81)
    sh.place('D104', 283.21, sw + 12.7, rot=90)        # A top, K bottom
    sh.w('R104.2', 'D104.2')
    sh.pwr('GND', 283.21, sw + 16.51)

    sh.translate(25.4, 50.8)
