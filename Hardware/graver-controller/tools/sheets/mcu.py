"""MCU sheet: STM32F411CEU6 with decoupling at its pins, crystal, reset/boot,
USB-C + ESD, SWD header and the status LED.

All coordinates are absolute sheet mm on the 1.27 grid (A3 = 420 x 297)."""

# labelled MCU pins: (pin number, global label)
LEFT_LABELS = [
    ('2', 'LED_STAT'), ('18', 'VIN_SENSE'), ('19', 'NTC'),
    ('40', 'ENC_A'), ('41', 'ENC_B'), ('42', 'LCD_BL'), ('43', 'ENC_SW'),
    ('21', 'LCD_DC'), ('25', 'OC_TRIP'), ('27', 'DECAY_SLOW'), ('28', 'LCD_RST'),
]
RIGHT_LABELS = [
    ('11', 'PEDAL_TIP'), ('12', 'PEDAL_RING'), ('15', 'LCD_SCK'), ('16', 'I_SENSE'),
    ('17', 'LCD_MOSI'), ('29', 'GATE_IN'), ('34', 'SWDIO'), ('37', 'SWCLK'),
]
NC_PINS = ['3', '4', '39', '45', '46', '26', '10', '13', '14', '30', '38']


def mcu(sh):
    X = lambda s: sh.pin(s)[0]   # noqa: E731
    Y = lambda s: sh.pin(s)[1]   # noqa: E731

    sh.place('U301', 220.98, 144.78, ref_at=(238.76, 187.96), val_at=(226.06, 190.5))
    # pin rows: left x=203.2, right x=238.76, top y=101.6, bottom y=185.42

    # ---- +3V3 rail over the VDD pins, decoupling caps on the rail ------------
    rail = 91.44
    for pin in ('1', '24', '36', '48'):
        sh.w('U301.%s' % pin, (X('U301.%s' % pin), rail))
    sh.w((160.02, rail), (X('U301.48'), rail))
    sh.pwr('+3V3', 160.02, rail)
    xs = [165.1, 175.26, 185.42, 195.58, 205.74]
    for x, ref in zip(xs, ('C301', 'C302', 'C303', 'C304', 'C305')):
        sh.place(ref, x, rail + 3.81)
    sh.w((xs[0], rail + 7.62), (xs[-1], rail + 7.62))
    sh.pwr('GND', xs[0], rail + 7.62)
    sh.text('C301-C304: one per VDD/VBAT pin, C305 bulk', 168.91, 85.09, 1.27)

    # ---- VDDA filter ----------------------------------------------------------
    vy = 88.9
    sh.w('U301.9', (X('U301.9'), vy))
    sh.place('FB301', 261.62, vy, rot=270)          # pin2 left (VDDA), pin1 right (+3V3)
    sh.w((X('U301.9'), vy), 'FB301.2')
    sh.w('FB301.1', (269.24, vy))
    sh.pwr('+3V3', 269.24, vy)
    for x, ref in ((233.68, 'C306'), (243.84, 'C307')):
        sh.place(ref, x, vy + 3.81)
        sh.pwr('GND', x, vy + 7.62)
    sh.pwr('PWR_FLAG', 228.6, vy)
    sh.label('VDDA', (X('U301.9'), 95.25), rot=90)

    # ---- VSS / VSSA -----------------------------------------------------------
    sh.w('U301.23', (X('U301.23'), 190.5))
    sh.w('U301.8', (X('U301.8'), 187.96), (X('U301.23'), 187.96))
    sh.pwr('GND', X('U301.23'), 190.5)

    # ---- VCAP -----------------------------------------------------------------
    y = Y('U301.22')
    sh.w('U301.22', (190.5, y))
    sh.place('C308', 190.5, y + 3.81)
    sh.pwr('GND', 190.5, y + 7.62)

    # ---- crystal --------------------------------------------------------------
    y0, y1 = Y('U301.5'), Y('U301.6')                # PH0 = OSC_IN, PH1 = OSC_OUT
    cy = 129.54
    sh.place('Y301', 152.4, cy, ref_at=(158.75, 128.27), val_at=(158.75, 130.81))
    sh.w('U301.5', (148.59, y0), 'Y301.1')
    sh.w('U301.6', (156.21, y1), 'Y301.3')
    sh.w('Y301.2', (152.4, cy + 7.62))
    sh.pwr('GND', 152.4, cy + 7.62)
    sh.place('C310', 143.51, 124.46, rot=270)         # pin1 right, on the OSC_IN drop
    sh.w('C310.1', (148.59, 124.46))
    sh.pwr('GND', 139.7, 124.46, rot=270)
    sh.place('C311', 166.37, 124.46, rot=90)          # pin1 left, on the OSC_OUT drop
    sh.w('C311.1', (156.21, 124.46))
    sh.pwr('GND', 170.18, 124.46, rot=90)
    sh.label('OSC_IN', (190.5, y0))
    sh.label('OSC_OUT', (190.5, y1))

    # ---- NRST -----------------------------------------------------------------
    ny = 139.7
    sh.w('U301.7', (127, Y('U301.7')), (127, ny), (106.68, ny))
    sh.place('SW302', 111.76, ny + 5.08, rot=270, ref_at=(100.33, 143.51), val_at=(100.33, 146.05))
    sh.pwr('GND', 111.76, ny + 10.16)
    sh.place('C309', 119.38, ny + 3.81)
    sh.pwr('GND', 119.38, ny + 7.62)
    sh.glabel('NRST', (106.68, ny), rot=180)

    # ---- BOOT0 ----------------------------------------------------------------
    by = 167.64
    sh.place('R302', 111.76, by, rot=270)             # pin1 right, pin2 left
    sh.w('U301.44', (129.54, Y('U301.44')), (129.54, by), 'R302.1')
    sh.place('R301', 119.38, by + 3.81)
    sh.pwr('GND', 119.38, by + 7.62)
    sh.place('SW301', 104.14, by - 5.08, rot=90, ref_at=(92.71, 160.02), val_at=(92.71, 162.56))
    sh.pwr('+3V3', 104.14, by - 10.16)
    sh.w('R302.2', 'SW301.1')
    sh.text('hold at power-up: USB DFU', 100.33, 185.42, 1.27)

    # ---- BOOT1 (PB2) ----------------------------------------------------------
    y = Y('U301.20')
    sh.w('U301.20', (177.8, y))
    sh.place('R303', 177.8, y + 3.81)
    sh.pwr('GND', 177.8, y + 7.62)

    # ---- labelled pins and no-connects ---------------------------------------
    for pin, name in LEFT_LABELS:
        x, y = sh.pin('U301.%s' % pin)
        sh.w((x, y), (x - 5.08, y))
        sh.glabel(name, (x - 5.08, y), rot=180)
    for pin, name in RIGHT_LABELS:
        x, y = sh.pin('U301.%s' % pin)
        sh.w((x, y), (x + 5.08, y))
        sh.glabel(name, (x + 5.08, y), rot=0)
    for pin in NC_PINS:
        sh.nc('U301.%s' % pin)

    # ---- PA10 pull-up (ROM bootloader picks USB DFU) -------------------------
    y = Y('U301.31')
    sh.w('U301.31', (260.35, y))
    sh.place('R307', 260.35, y - 3.81, rot=180)       # pin1 bottom on PA10, pin2 top
    sh.pwr('+3V3', 260.35, y - 7.62)

    # ---- USB: PA11/PA12 -> ESD -> connector ------------------------------------
    sh.place('U302', 270.51, Y('U301.32'), val_at=(262.89, 155.58))   # pin1 on PA11, pin3 on PA12
    sh.w('U301.32', 'U302.1')
    sh.w('U301.33', 'U302.3')
    # USBLC6 is a flow-through part: pins 1/6 and 3/4 are one line each
    sh.label('USB_DM', (246.38, Y('U301.32')))
    sh.label('USB_DP', (246.38, Y('U301.33')))
    sh.label('USB_DM', (287.02, 146.05), rot=90)
    sh.label('USB_DP', (279.4, 148.59), rot=90)
    sh.w('U302.2', (X('U302.2'), Y('U302.2') + 2.54))
    sh.pwr('GND', X('U302.2'), Y('U302.2') + 2.54)
    sh.place('J301', 320.04, 152.4, mirror='y', ref_at=(306.07, 130.81), val_at=(306.07, 179.07))
    # D-: pin6 -> A7/B7, D+: pin4 -> A6/B6
    sh.w('U302.6', (287.02, Y('U302.6')), (287.02, Y('J301.B7')), 'J301.B7')
    sh.w((287.02, Y('J301.A7')), 'J301.A7')
    sh.w('U302.4', (279.4, Y('U302.4')), (279.4, Y('J301.B6')), 'J301.B6')
    sh.w((279.4, Y('J301.A6')), 'J301.A6')
    # VBUS to the ESD array and off-sheet
    sh.w('J301.A4', (299.72, Y('J301.A4')), (299.72, 125.73), (X('U302.5'), 125.73), 'U302.5')
    sh.glabel('VBUS', (284.48, 125.73))
    # CC pull-downs via local labels (keeps the D+/D- routing clean)
    for pin, name in (('A5', 'USB_CC1'), ('B5', 'USB_CC2')):
        x, y = sh.pin('J301.%s' % pin)
        sh.w((x, y), (x - 5.08, y))
        sh.label(name, (x - 5.08, y), rot=180)
    sh.nc('J301.A8')
    sh.nc('J301.B8')
    gx, gy = sh.pin('J301.A1')
    sh.w('J301.A1', (gx, gy + 5.08))
    sh.w('J301.SH', (X('J301.SH'), gy + 2.54), (gx, gy + 2.54))
    sh.pwr('GND', gx, gy + 5.08)
    for x, ref, name in ((340.36, 'R305', 'USB_CC1'), (347.98, 'R306', 'USB_CC2')):
        sh.place(ref, x, 152.4)
        sh.w('%s.1' % ref, (x, 146.05))
        sh.label(name, (x, 146.05), rot=90)
        sh.pwr('GND', x, 156.21)

    # ---- SWD header -----------------------------------------------------------
    sh.place('J302', 320.04, 200.66, ref_at=(316.23, 191.77), val_at=(317.5, 210.82))
    for pin, name in (('2', 'SWDIO'), ('3', 'SWCLK'), ('4', 'NRST')):
        x, y = sh.pin('J302.%s' % pin)
        sh.w((x, y), (x - 5.08, y))
        sh.glabel(name, (x - 5.08, y), rot=180)
    x, y = sh.pin('J302.1')
    sh.w((x, y), (x - 5.08, y), (x - 5.08, y - 5.08))
    sh.pwr('+3V3', x - 5.08, y - 5.08)
    x, y = sh.pin('J302.5')
    sh.w((x, y), (x - 5.08, y), (x - 5.08, y + 5.08))
    sh.pwr('GND', x - 5.08, y + 5.08)

    # ---- status LED -----------------------------------------------------------
    sh.place('R304', 270.51, 182.88)
    sh.pwr('+3V3', 270.51, 179.07)
    sh.place('D301', 270.51, 193.04, rot=90, ref_at=(273.05, 191.77), val_at=(273.05, 194.31))
    sh.w('R304.2', 'D301.2')
    sh.w('D301.1', (270.51, 199.39), (275.59, 199.39))
    sh.glabel('LED_STAT', (275.59, 199.39))

    sh.paper = 'A4'
    sh.translate(-95.25, -62.23)
