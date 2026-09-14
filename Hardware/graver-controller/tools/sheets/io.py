"""IO sheet: display header, rotary encoder with RC debounce, expression
pedal jack with ESD protection, mounting holes."""


def io(sh):
    X = lambda s: sh.pin(s)[0]   # noqa: E731
    Y = lambda s: sh.pin(s)[1]   # noqa: E731

    # ---- display header (7-pin ST7789 module, no CS) ---------------------------
    sh.place('J401', 60.96, 50.8, ref_at=(58.42, 40.64), val_at=(58.42, 62.23))
    sh.w('J401.1', (50.8, Y('J401.1')))
    sh.pwr('GND', 50.8, Y('J401.1'), rot=270)
    sh.w('J401.2', (40.64, Y('J401.2')), (40.64, 38.1))
    sh.pwr('+3V3', 40.64, 38.1)
    for pin, name in (('3', 'LCD_SCK'), ('4', 'LCD_MOSI'), ('5', 'LCD_RST'), ('6', 'LCD_DC')):
        x, y = sh.pin('J401.%s' % pin)
        sh.w((x, y), (x - 5.08, y))
        sh.glabel(name, (x - 5.08, y), rot=180)
    sh.place('R401', 45.72, 63.5, rot=90)               # pin1 left = LCD_BL, pin2 to the module
    sh.w('J401.7', (50.8, Y('J401.7')), (50.8, 63.5), 'R401.2')
    sh.w('R401.1', (38.1, 63.5))
    sh.glabel('LCD_BL', (38.1, 63.5), rot=180)
    sh.text('1.3in ST7789 240x240 module, 3V3, no CS: SPI mode 3', 35.56, 71.12, 1.27)
    sh.text('BLK: module has its own backlight transistor', 35.56, 73.66, 1.27)

    # ---- rotary encoder ------------------------------------------------------------
    sh.place('SW401', 139.7, 50.8, ref_at=(134.62, 40.64), val_at=(144.78, 64.77))
    sh.nc('SW401.MP')
    # A: up to its own row, pull-up and RC to GND
    sh.w('SW401.A', (129.54, Y('SW401.A')), (129.54, 38.1), (96.52, 38.1))
    sh.place('R402', 121.92, 34.29)
    sh.pwr('+3V3', 121.92, 30.48)
    sh.place('C401', 101.6, 41.91)
    sh.pwr('GND', 101.6, 45.72)
    sh.glabel('ENC_A', (96.52, 38.1), rot=180)
    # B: down to its row
    sh.w('SW401.B', (129.54, Y('SW401.B')), (129.54, 66.04), (96.52, 66.04))
    sh.place('R403', 121.92, 62.23)
    sh.pwr('+3V3', 121.92, 58.42)
    sh.place('C402', 101.6, 69.85)
    sh.pwr('GND', 101.6, 73.66)
    sh.glabel('ENC_B', (96.52, 66.04), rot=180)
    # common
    sh.w('SW401.C', (118.11, Y('SW401.C')))
    sh.pwr('GND', 118.11, Y('SW401.C'), rot=270)
    # push switch
    sy = Y('SW401.S1')
    sh.w('SW401.S1', (170.18, sy))
    sh.place('R404', 154.94, sy - 3.81)
    sh.pwr('+3V3', 154.94, sy - 7.62)
    sh.place('C403', 165.1, sy + 3.81)
    sh.pwr('GND', 165.1, sy + 7.62)
    sh.glabel('ENC_SW', (170.18, sy))
    sh.w('SW401.S2', (152.4, Y('SW401.S2')))
    sh.pwr('GND', 152.4, Y('SW401.S2'))
    sh.text('EC11E15244G1: 30 detents / 15 pulses, TIM3 encoder mode', 96.52, 80.01, 1.27)

    # ---- expression pedal jack ------------------------------------------------------
    sh.place('J402', 60.96, 111.76, ref_at=(50.8, 101.6), val_at=(50.8, 124.46))
    sh.nc('J402.TN')
    sh.w('J402.S', (76.2, Y('J402.S')))
    sh.pwr('GND', 76.2, Y('J402.S'), rot=90)
    sh.w('J402.RN', (71.12, Y('J402.RN')))
    sh.pwr('GND', 71.12, Y('J402.RN'), rot=90)
    ry = Y('J402.R')
    ty = 129.54
    sh.place('R406', 106.68, ry, rot=90)
    sh.place('R408', 109.22, ty, rot=90)
    # ESD array across ring and tip
    sh.place('U401', 83.82, 120.65, rot=90, ref_at=(80.01, 118.11), val_at=(74.93, 123.19))
    sh.w('J402.R', 'R406.1')
    sh.w('J402.T', (73.66, Y('J402.T')), (73.66, ty), 'R408.1')
    sh.w('U401.3', (87.63, 120.65))
    sh.pwr('GND', 87.63, 120.65, rot=90)
    # ring: 1k to 3V3 (plug detect + mono-plug safe), 1k/10n to the ADC
    sh.place('R405', 96.52, ry - 3.81)
    sh.pwr('+3V3', 96.52, ry - 7.62)
    sh.w('R406.2', (124.46, ry))
    sh.place('C404', 114.3, ry + 3.81)
    sh.pwr('GND', 114.3, ry + 7.62)
    sh.glabel('PEDAL_RING', (124.46, ry))
    # tip: 100k pull-up (footswitch fallback), 1k/10n to the ADC
    sh.place('R407', 99.06, ty - 3.81)
    sh.pwr('+3V3', 99.06, ty - 7.62)
    sh.w('R408.2', (127, ty))
    sh.place('C405', 119.38, ty + 3.81)
    sh.pwr('GND', 119.38, ty + 7.62)
    sh.glabel('PEDAL_TIP', (127, ty))
    sh.text('TRS: tip = wiper, ring = 3V3 feed, sleeve = GND', 45.72, 142.24, 1.27)
    sh.text('no plug or mono plug: RN grounds the ring -> firmware sees no pedal', 45.72, 144.78, 1.27)

    # ---- mounting holes ---------------------------------------------------------------
    for i, ref in enumerate(('MH401', 'MH402', 'MH403', 'MH404')):
        sh.place(ref, 154.94 + 10.16 * i, 120.65)
    sh.text('M3 mounting holes', 152.4, 127, 1.27)

    sh.paper = 'A4'
    sh.translate(12.7, 12.7)
