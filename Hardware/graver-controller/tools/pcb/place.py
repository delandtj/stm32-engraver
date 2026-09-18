#!/usr/bin/env python3
"""Generate graver-controller.kicad_pcb from the schematic, placed.

Single entry point. Idempotent: every run throws the previous board away and
rebuilds it from the schematic netlist, so the .kicad_pcb is a derived file
until Jan starts routing.

What it does
  1. exports the kicadxml netlist with kicad-cli into output/pcb/
  2. creates a board, loads every footprint, links it to its symbol by UUID
     (so "Update PCB from schematic" in the GUI is a no-op)
  3. draws the 110 x 70 mm outline with 2 mm corner radii
  4. places all 117 parts: explicit tables for the anchors, rules for the
     satellites (decoupling caps, RC filters, pull-ups)
  5. checks courtyards, board containment, M3 keepouts and the ADR 0003
     distance criteria, and exits non-zero if any of them fail
  6. prints a per-net ratsnest length (MST over the pads) to guide nudging

It does NOT route and it does NOT pour. See README.md.

Usage:  python3 tools/pcb/place.py [--no-netlist]
"""

import collections
import json
import math
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pcbnew

# KiCad 10 + Python 3.14: the SWIG iterator lost its .next shim.
if not hasattr(pcbnew.SwigPyIterator, "next"):
    pcbnew.SwigPyIterator.next = pcbnew.SwigPyIterator.__next__

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.normpath(os.path.join(HERE, "..", ".."))
NAME = "graver-controller"
SCH = os.path.join(PROJ, NAME + ".kicad_sch")
PCB = os.path.join(PROJ, NAME + ".kicad_pcb")
PRO = os.path.join(PROJ, NAME + ".kicad_pro")
OUT = os.path.join(PROJ, "output", "pcb")
NETLIST = os.path.join(OUT, "netlist.xml")
FPLIB = "/usr/share/kicad/footprints"

# ---------------------------------------------------------------- board ----
BOARD_W = 110.0
BOARD_H = 70.0
CORNER_R = 2.0
# Board top-left corner on the KiCad page; also the aux/grid origin.
ORIGIN = (50.0, 50.0)
EDGE_LINE_W = 0.05

M3 = 4.0              # mounting hole inset from each corner
M3_KEEPOUT = 6.0      # ground-free / parts-free radius around each hole
HOLES = {
    "MH401": (M3, M3),
    "MH402": (BOARD_W - M3, M3),
    "MH403": (BOARD_W - M3, BOARD_H - M3),
    "MH404": (M3, BOARD_H - M3),
}

GRID = 0.5            # passives snap to this
COURTYARD_GAP = 0.5   # minimum air between courtyards of UNRELATED parts
GROUP_GAP = 0.15      # ... and between parts of the same function group

# ------------------------------------------------------- rear-edge parts ----
# Right-angle connectors. `out_axis` is the LOCAL footprint direction the
# mating face points at rotation 0, worked out from each footprint's own F.Fab
# geometry (see README). `rot` turns that direction into board -y (out of the
# rear edge). `overhang` is how far the face may sit past y=0.
#
#   J101 BarrelJack_Horizontal : F.Fab -13.7..0.8 in x with a flange line at
#         -10.2; the 3.5 mm beyond it is the barrel nose      -> local -x
#   J301 USB-C HRO 31-M-12     : F.Fab body -3.65..3.65 in y, contact tails
#         at y=-4.045 behind it, so the mouth is the +y face  -> local +y
#   J201 Phoenix MSTBA 4-G     : silkscreen draws four wire-entry funnels at
#         y=8.61..10.11, one per contact                      -> local +y
#   J402 Neutrik NMJ6HCD2      : F.Fab body ends at x=16.7 with the 3 mm
#         chrome ferrule drawn out to x=19.7                  -> local +x
#
# J301 moved 3 mm left (32.0 -> 29.0) in the second pass to open the gap for
# the SWD header, which now lies ALONG the rear edge instead of sticking down
# into the MCU's rear side.
EDGE_PARTS = {
    # ref:   (x, rot, out_axis, overhang_mm)
    "J101": (17.5, 270, "-x", 3.5),
    "J301": (29.0, 180, "+y", 0.5),
    "J201": (69.5, 180, "+y", 0.0),
    "J402": (80.0, 90, "+x", 3.0),
}

# ------------------------------------------------------------- anchors -----
# Block anchor -> list of (ref, dx, dy, rotation). Nudge these numbers; the
# satellite placer and the checks follow automatically.
ANCHORS = {
    # Power block, behind the DC jack, down the left edge. Input section at
    # the top (fuse / P-FET / TVS / bulk), buck and LDO towards the front
    # where there is room for their passives.
    "POWER": ((4.0, 14.0), [
        ("F101",  13.5,  3.0,  90),   # 1 A fuse in the VIN chain
        ("Q101",  13.5,  9.5,   0),   # DMP6023 reverse-polarity P-FET
        ("D102",   5.0,  8.0,  90),   # SMBJ36A input TVS
        ("C101",   7.0, 17.0,   0),   # 470 uF bulk, upright under the dome
        # Buck: pads 1-4 (GND, VIN, EN, RON) face -x, pads 5-8 (FB, PGOOD,
        # BST, SW) face +x. So CIN goes to its left and the inductor to its
        # right, and the SW node never crosses the input caps.
        ("U101",  12.0, 32.0,   0),   # LM5164 buck
        ("L101",  27.0, 32.0,   0),   # 33 uH on the SW side
        ("D105",  23.0, 40.0,   0),   # buck-output ORing Schottky
        ("D103",  16.0, 40.0,   0),   # VBUS ORing Schottky
        ("U102",   9.0, 44.0,   0),   # AP2112K 3V3 LDO
    ]),
    # Solenoid driver, behind the handpiece terminal.
    "DRIVER": ((50.0, 14.0), [
        # Q201/D201/D202/Q202/C102/C103 come from FLYBACK_CANDIDATES, and
        # U201/R202/R204/U202 hang off the FET (see DRIVER_SATS) so they
        # follow whichever flyback arrangement wins.
        #
        # Slow-decay bypass control. J402's courtyard owns x 78..98 down to
        # y 24, so this cluster has to sit below it rather than beside Q202.
        ("Q203",  36.0, 14.0,   0),   # BSS123
        ("R205",  30.0, 16.0,  90),   # CLAMP divider top
        ("R206",  36.0, 18.0,  90),   # to Q203 drain
        ("R207",  40.0, 16.0,  90),   # DECAY_SLOW gate divider
        ("R208",  40.0, 19.0,  90),
    ]),
    # Rear half, position-fixed and therefore placed BEFORE the MCU search:
    # the two buttons must line up with holes in the printed rear wall, and
    # the CC resistors belong at the USB-C connector.
    "REAR": ((0.0, 0.0), [
        # CC1's contact is at x=30.25 and CC2's at x=27.25, and the locked
        # USB pair leaves the connector between them (x 28.25 / 28.75). Each
        # pull-down therefore sits on ITS OWN side of the pair - CC1 east,
        # CC2 west - and rotation 270 turns the CC pad towards the connector.
        # With both at x=25/27 (first pass) CC1 had to cross the pair.
        ("R305",  30.0, 10.6, 270),   # CC1 5k1, east of the pair
        ("R306",  26.5, 10.6, 270),   # CC2 5k1, west of the pair
        # Buttons stacked rather than side by side: at 7.6 mm courtyard each
        # they do not both fit between J301 and J201, and they must stay out
        # of the VIN corridor along the rear half.
        ("SW301", 39.0, 10.5,   0),   # BOOT0 button
        ("SW302", 39.0, 21.0,   0),   # RESET button
    ]),
    # Front edge: display ribbon left, encoder right, indicators between.
    "FRONT": ((0.0, 0.0), [
        ("J401",  20.0, 61.0,   0),   # JST XH 1x7 to the display in the cover
        ("SW401", 80.5, 52.5,   0),   # Alps EC11 encoder, shaft at (88, 55)
        # Indicators between the display pocket and the encoder, where the
        # cover has room for two light pipes.
        ("D301",  66.0, 63.0,   0),   # status LED
        ("D104",  61.0, 63.0,   0),   # power LED
    ]),
    # SWD header lying ALONG the rear edge (rot 90), in the gap J301's 3 mm
    # shift opened up. Pin 1 at the left end.
    "SWD": ((0.0, 0.0), [
        ("J302",  37.0,  2.5,  90),
    ]),
    # Pedal ESD array sits at the jack, not at the MCU.
    "PEDAL": ((0.0, 0.0), [
        ("U401",  76.0, 14.0,  90),
    ]),
}

# Blocks placed before the MCU search runs (their positions do not depend on
# where the MCU lands), in this order.
FIXED_BLOCKS = ("POWER", "DRIVER", "REAR", "FRONT", "SWD", "PEDAL")

# Driver parts anchored to the FET, placed right after the flyback corner is
# chosen and before the MCU search (the search links to U201/U202/R207).
# ref: (host pad, own pin, out, side, group)
DRIVER_SATS = [
    ("U201", ("Q201.1", "5", 4.0, -1.5), "gatedrv"),   # driver out at the gate
    ("R202", ("U201.3", "2", 2.6, 0.0), "gatedrv"),    # GATE_IN pulldown
    ("R204", ("Q201.3", "1", 3.2, 2.5), "shunt"),      # 1 R shunt at the source
    ("U202", ("R204.1", "4", 5.0, 0.0), "opamp"),      # TLV9062 at the shunt
]

# ------------------------------------------------------------ MCU search ----
# The MCU and everything that must sit at its pins form one rigid cluster.
# Rather than hand-picking a pose, score all four rotations over a coarse grid
# and take the best. Each link is (MCU pad, target pad on an already-placed
# part, weight); the score is sum(weight * distance).
MCU_SEARCH_X = (34.0, 70.0, 2.0)
MCU_SEARCH_Y = (24.0, 48.0, 2.0)
MCU_LINKS = [
    ("33", "J301.A6", 3.0),     # USB_DP
    ("32", "J301.A7", 3.0),     # USB_DM
    ("15", "J401.3", 2.0),      # LCD_SCK
    ("17", "J401.4", 2.0),      # LCD_MOSI
    ("21", "J401.6", 2.0),      # LCD_DC
    ("28", "J401.5", 2.0),      # LCD_RST
    ("42", "J401.7", 2.0),      # LCD_BL (through R401 at the connector)
    ("16", "U202.1", 2.0),      # I_SENSE, through R212/R210 to the op-amp
    ("25", "U202.7", 2.0),      # OC_TRIP
    ("29", "U201.3", 2.0),      # GATE_IN
    ("27", "R207.1", 2.0),      # DECAY_SLOW
    ("11", "J402.T", 1.5),      # PEDAL_TIP
    ("12", "J402.R", 1.5),      # PEDAL_RING
    ("19", "J201.3", 1.5),      # NTC
    ("18", "C101.1", 1.5),      # VIN_SENSE, divider fed from the bulk cap
    ("40", "SW401.A", 1.0),     # ENC_A
    ("41", "SW401.B", 1.0),     # ENC_B
    ("43", "SW401.S1", 1.0),    # ENC_SW
    ("34", "J302.2", 1.0),      # SWDIO
    ("37", "J302.3", 1.0),      # SWCLK
    ("7", "J302.4", 1.0),       # NRST
    ("44", "SW301.1", 1.0),     # BOOT0
]
# The cluster needs this much clear room around the QFN for its own ring of
# decoupling, crystal island, VDDA filter and ADC filters.
MCU_HALO = 5.0
# Escape channels around the QFN (third pass). RING2_GAP is the clear annulus
# between the first ring (VDD decaps + crystal island) and everything else;
# CORRIDOR_W x CORRIDOR_LEN is the radial corridor reserved out from the
# middle of each side so the tangential channel has somewhere to drain to.
RING2_GAP = 3.0
CORRIDOR_W = 3.6
CORRIDOR_LEN = 10.0
# VIN has to get from the bulk capacitor to J201 pin 1 along the rear half
# without crossing the MCU or the analog front end. Reserved band, no parts.
VIN_CORRIDOR = (21.0, 14.0, 57.0, 17.0)
XTAL_SIDE_GAP = 0.15      # shallower band on the crystal side: the island
                         # has to reach in to keep the far OSC leg under 5 mm
MCU_MIN_TO_BUCK = 15.0      # ADR: buck >= 15 mm from crystal and analog
MCU_REFERENCE_POSE = (42.0, 36.0, 180)   # what pass 1 picked by hand

# ------------------------------------------------------- satellite rules ----
# A satellite is placed next to a HOST pad. `host` is a pad "REF.PADNUM" or a
# bare "REF" (its centre). The satellite's own pad `pin` is aimed at it.
# `out` is how far along the host pin's outward normal, `side` is the offset
# across it (so two caps can flank one pin instead of queueing up behind it).
# Anything not listed and not an anchor falls back to nearest-connected-part.
#
# ref:     (host pad,   own pin, out, side)
DECAPS = {
    # One 100 nF per VDD/VBAT pin, pad 1 facing the pin. Placed before
    # everything else that wants MCU-adjacent space.
    "C301": ("U301.1", "1", 2.0, 0.0),
    "C302": ("U301.24", "1", 2.0, 0.0),
    "C303": ("U301.36", "1", 2.0, 0.0),
    "C304": ("U301.48", "1", 2.0, 0.0),
}
SATELLITES = {
    "C305": ("U301.48", "1", 1.8, 3.0),     # 4u7 bulk on +3V3
    "C308": ("U301.22", "1", 2.0, 0.0),     # VCAP1
    "C309": ("U301.7", "1", 1.8, 0.0),      # NRST
    # side is measured along the QFN edge; POSITIVE runs towards the LOW pin
    # numbers, i.e. into the crystal island. The VDDA chain therefore marches
    # NEGATIVE, out over pads 10-12 (PA0 unconnected, PA1/PA2 pedal).
    "C306": ("U301.9", "1", 1.8, 0.0),      # VDDA 1 uF
    "C307": ("U301.9", "1", 1.8, -2.2),     # VDDA 100 nF
    "FB301": ("U301.9", "2", 1.8, -4.4),    # VDDA ferrite
    # Buck: both CIN caps within 3 mm of VIN, flanking the pin; BST at pin 7.
    # Both 1206 CIN caps flank the VIN pin so each stays inside 3 mm; the
    # 100 nF sits just outside them.
    "C105": ("U101.2", "1", 2.2, -1.5),
    "C106": ("U101.2", "1", 2.2, 1.5),
    "C107": ("U101.2", "1", 2.2, 4.5),
    "C108": ("U101.7", "1", 1.8, 0.0),      # BST, right at the pins
    "R107": ("U101.4", "1", 2.2, 0.0),      # RON
    "R105": ("U101.3", "2", 2.2, 0.0),      # EN/UVLO top
    "R106": ("U101.3", "2", 2.2, 2.0),      # EN/UVLO bottom
    "C113": ("U102.1", "1", 2.2, 0.0),      # 5 V input cap at the LDO
    "C114": ("U102.5", "1", 2.2, 0.0),      # 1 uF, the LDO's stability cap
    # ADR 0003: "the 3V3 output caps near the MCU". The 10 uF bulk belongs at
    # the load, beside the MCU's own 4u7, not back at the regulator.
    "C115": ("C305.1", "1", 2.6, 0.0),
    # Gate drive and the FET.
    "R201": ("U201.5", "1", 2.2, 0.0),      # gate resistor at the driver out
    "R203": ("Q201.1", "2", 2.6, 0.0),      # gate pulldown at the FET
    "C201": ("U201.1", "1", 2.2, 0.0),      # driver bypass at its pins
    "C202": ("U201.1", "1", 2.2, 2.0),
    # Shunt sense: Kelvin taps at the shunt pads, feedback at the op-amp.
    "R209": ("R204.1", "1", 2.4, 0.0),
    "R213": ("R204.1", "1", 2.4, 2.2),
    "C204": ("U202.3", "1", 2.4, 0.0),
    "R210": ("U202.1", "1", 2.4, 0.0),
    "R211": ("U202.2", "2", 2.4, 0.0),
    "R214": ("U202.5", "2", 2.4, 0.0),
    "R215": ("U202.6", "2", 2.4, 0.0),
    "R216": ("U202.6", "2", 2.4, 2.2),
    "C206": ("U202.6", "1", 2.4, 4.4),
    "C203": ("U202.8", "1", 2.4, 0.0),      # op-amp 3V3 bypass
    # ADC-side RC filters, next to the MCU pin each one feeds.
    "R212": ("U301.16", "2", 2.2, 0.0),     # I_SENSE 330 R
    "C205": ("U301.16", "1", 2.2, 2.2),     # I_SENSE 10 nF
    "R103": ("U301.18", "2", 2.2, 0.0),     # VIN divider low side
    "R102": ("U301.18", "2", 2.2, 2.2),     # VIN divider high side
    "C104": ("U301.18", "1", 2.2, -2.2),    # VIN_SENSE cap
    "R217": ("U301.19", "2", 2.2, 0.0),     # NTC pull-up
    "C207": ("U301.19", "1", 2.2, 2.2),     # NTC cap
    # Encoder debounce at the MCU, pull-ups chained outward behind them.
    "C401": ("U301.40", "1", 2.2, 0.0),
    "R402": ("C401.1", "2", 2.4, 0.0),
    "C402": ("U301.41", "1", 2.2, 0.0),
    "R403": ("C402.1", "2", 2.4, 0.0),
    "C403": ("U301.43", "1", 2.2, 0.0),
    "R404": ("C403.1", "2", 2.4, 0.0),
    # Pedal: the 10 nF filter caps sit at the MCU pins, the 1 k series
    # resistors and the pull-ups chain outward into the quiet zone.
    "C405": ("U301.11", "1", 2.2, 0.0),
    "R408": ("C405.1", "2", 2.4, 0.0),
    "R407": ("R408.1", "2", 2.4, 0.0),
    "C404": ("U301.12", "1", 2.2, 0.0),
    "R406": ("C404.1", "2", 2.4, 0.0),
    "R405": ("R406.1", "2", 2.4, 0.0),
    # Display backlight series resistor at the connector's BLK pin.
    "R401": ("J401.7", "2", 2.2, 0.0),
    # Odds and ends anchored to their partner.
    "R301": ("U301.44", "1", 2.2, 0.0),     # BOOT0 pulldown
    "R302": ("SW301.1", "1", 2.6, 0.0),     # BOOT0 series
    "R303": ("U301.20", "1", 2.2, 0.0),     # PB2 pulldown
    "R307": ("U301.31", "1", 2.2, 0.0),     # PA10 pull-up
    "R304": ("D301.2", "2", 2.2, 0.0),      # status LED series
    "R104": ("D104.2", "2", 2.2, 0.0),      # power LED series
    "D101": ("Q101.1", "2", 3.0, 0.0),      # gate zener at the P-FET
    "R101": ("Q101.1", "1", 3.0, 2.6),      # gate pulldown
    "D203": ("Q202.1", "1", 3.0, 0.0),      # bypass gate zener
    "R110": ("U101.5", "1", 3.0, 0.0),      # buck FB divider
    "R109": ("R110.1", "2", 2.0, 0.0),
    "C109": ("R109.1", "1", 2.0, 0.0),      # feed-forward
    "C110": ("R109.1", "1", 2.0, 2.0),
    "C111": ("D105.1", "1", 2.6, 0.0),      # buck output caps
    "C112": ("C111.1", "1", 2.6, 0.0),  # chained off C111 so the pair stays together
    "R108": ("U101.8", "1", 2.6, 0.0),      # SW node, one side only
}

# Parts that must own the ring immediately around the QFN, placed before the
# rest of the satellites compete for it. ref -> function group.
# Split in two: the parts with a 3 mm target go in BEFORE the crystal island,
# because the crystal has slack (5 mm limit, it lands near 4.4) and VDDA/NRST
# have none. Pads 5-9 are five consecutive pins on 2 mm of QFN edge and the
# crystal, its two load caps and the VDDA network all want that space.
MCU_RING_FIRST = (
    "C306", "FB301",                # VDDA ferrite + 1 uF, the essential pair
    "C309",                         # NRST
)
MCU_RING = (
    "C307",                         # VDDA 100 nF, after the crystal
    "C308", "C305",                 # VCAP1, 3V3 bulk
    "R212", "C205",                 # I_SENSE
    "R103", "C104",                 # VIN_SENSE
    "R217", "C207",                 # NTC
    "C401", "C402", "C403",         # encoder debounce
    "C405", "C404",                 # pedal filters
)

# "Related" means "attached to the same thing". A satellite INHERITS its
# host's group, so a decoupling cap is automatically related to its IC and can
# sit tight against it, while two unrelated blocks keep COURTYARD_GAP apart.
# This table only names the group of the parts that start a chain.
GROUP_SEED = {
    # power
    "F101": "vin", "Q101": "vin", "D102": "vin", "C101": "vin",
    "U101": "buck", "L101": "buck",
    "D103": "oring", "D105": "oring", "U102": "ldo",
    # driver
    "Q201": "flyback", "D201": "flyback", "D202": "flyback",
    "Q202": "flyback", "C102": "flyback", "C103": "flyback",
    "U201": "flyback",          # the gate loop belongs with the FET
    "R204": "shunt", "U202": "analog",
    "Q203": "decay", "R205": "decay", "R206": "decay",
    "R207": "decay", "R208": "decay",
    # mcu and the rear/front furniture
    "U301": "mcu", "U302": "usb", "R305": "usb", "R306": "usb",
    "SW301": "button", "SW302": "button",
    "J401": "lcd", "SW401": "enc", "D301": "led", "D104": "led",
    "J302": "swd", "U401": "pedal-esd",
    "Y301": "mcu", "C310": "mcu", "C311": "mcu",
}
# Explicit overrides where inheritance would give the wrong answer.
GROUP_OVERRIDE = {
    "R102": "mcu",   # VIN divider: an MCU-pin part fed from the power block
}

# Crystal: keep the oscillator island clear of everything else.
XTAL = "Y301"
XTAL_OSC_PADS = ("5", "6")
XTAL_LOADS = ("C310", "C311")
XTAL_CLEAR = 0.4          # extra courtyard air around the island. Small on
                          # purpose: "no signal under the crystal" is a
                          # ROUTING rule (draw a User.2 keepout before
                          # routing), not a reason to push the MCU's own
                          # VDDA and NRST caps 6 mm away from their pins.
# Island layout: (ref, offset along the QFN edge, offset outward) in mm.
# One row, all three parts at the same distance out, so the island clears the
# RING2_GAP annulus and leaves a tangential channel between itself and the QFN
# wide enough for the six signals on this side (OSC, NRST, VDDA, PA1, PA2,
# LED_STAT) to run sideways and around its ends. Stacking the caps between
# crystal and MCU - the ADR's wording - puts them 1.5 mm out, in the middle of
# the escape path, and a strict autoroute then leaves those six nets open.
# Flanking keeps each cap about 1.2 mm from the crystal pin it damps, which is
# the loop that actually matters.
# Crystal close in, load caps BEHIND it rather than flanking, so the island
# is only ~4.3 mm wide and leaves about 2 mm of clear QFN side at each end for
# pads 1-4 and 9-12 to escape radially. Pads 1 and 3 of a 3225 sit on opposite
# corners, 1.7 mm apart, so one OSC leg always pays that; keeping the body at
# 3.9 mm out is what holds the far one under the 5 mm limit.
# C310 is the OSC_IN load cap and C311 the OSC_OUT one, so C310 goes on the
# OSC_IN pin's side of the island (pad 5) and C311 on pad 6's. With them the
# other way round - and with the crystal flip the distance search prefers -
# the two oscillator legs have to cross each other between the pin row and
# the caps, which on one layer is not routable at all.
XTAL_ISLAND = (
    ("Y301",   0.0, 3.8),
    ("C310",   1.7, 1.5),
    ("C311",  -1.7, 1.5),
)
# Which way round the crystal goes is a ROUTING decision, not a distance one:
# the flip has to put the crystal's own OSC_IN pad (pad 1) on the same side as
# C310 and MCU pad 5. The search below still runs and prints both, so the cost
# in worst-leg length is visible; None = let the search decide.
XTAL_FORCE_FLIP = 0
                          # far enough back to clear the load caps
XTAL_BIAS = -1.5          # slide the island along the edge, away from the
                          # VBAT decap on pad 1, which otherwise collides
                          # with the left load cap and throws the whole
                          # group 1-2 mm out

# ---------------------------------------------- ADR 0003 distance checks ----
# (label, kind, a, b, limit, direction) - direction "max" = must be <= limit.
CRITERIA = [
    ("100 nF C301 to VDD pin U301.1", "pad", "C301.1", "U301.1", 2.0, "max"),
    ("100 nF C302 to VDD pin U301.24", "pad", "C302.1", "U301.24", 2.0, "max"),
    ("100 nF C303 to VDD pin U301.36", "pad", "C303.1", "U301.36", 2.0, "max"),
    ("100 nF C304 to VDD pin U301.48", "pad", "C304.1", "U301.48", 2.0, "max"),
    ("crystal Y301 to OSC_IN U301.5", "pad", "Y301.1", "U301.5", 5.0, "max"),
    ("crystal Y301 to OSC_OUT U301.6", "pad", "Y301.3", "U301.6", 5.0, "max"),
    ("gate driver U201 out to FET gate Q201.1", "pad", "U201.5", "Q201.1", 5.0, "max"),
    ("op-amp U202 to shunt R204", "part", "U202", "R204", 10.0, "max"),
    ("CIN C105 to buck VIN pin U101.2", "pad", "C105.1", "U101.2", 3.0, "max"),
    ("CIN C106 to buck VIN pin U101.2", "pad", "C106.1", "U101.2", 3.0, "max"),
    ("BST cap C108 to U101.7", "pad", "C108.1", "U101.7", 3.0, "max"),
    ("buck U101 to crystal Y301", "part", "U101", "Y301", 15.0, "min"),
    ("buck U101 to op-amp U202", "part", "U101", "U202", 15.0, "min"),
    ("buck U101 to I_SENSE filter C205", "part", "U101", "C205", 15.0, "min"),
    ("bulk cap C101 to encoder SW401", "part", "C101", "SW401", 10.0, "min"),
    ("USB pair U301.33 to J301.A6", "pad", "U301.33", "J301.A6", 40.0, "max"),
    ("display J401 to SPI pin U301.15", "pad", "J401.3", "U301.15", 40.0, "max"),
    # Added in the second pass.
    ("VDDA 1uF C306 to U301.9", "pad", "C306.1", "U301.9", 3.0, "max"),
    ("VDDA 100nF C307 to U301.9", "pad", "C307.1", "U301.9", 3.0, "max"),
    ("VDDA ferrite FB301 to U301.9", "pad", "FB301.2", "U301.9", 3.0, "max"),
    ("NRST cap C309 to U301.7", "pad", "C309.1", "U301.7", 3.0, "max"),
]

# Criteria that are REPORTED but do not gate the exit code, because the target
# is known to be unreachable with the footprints the schematic specifies. Each
# one carries the reason, printed with the table.
ADVISORY = {
    "VDDA 1uF C306 to U301.9": (
        "Pads 1 and 5-12 all sit on one 6 mm stretch of QFN edge and want "
        "eleven parts: the VBAT decoupling cap, the crystal with its two load "
        "caps, the three-part VDDA network, the NRST cap and the two pedal "
        "filter caps. Only four fit in the first ring; the rest go to a second "
        "ring at 4.5-7 mm. The crystal's hard 5 mm limit and the four VDD "
        "decoupling caps' 2 mm limit are met first, so the VDDA network and "
        "the NRST cap are what give. Both are filters - VDDA behind a ferrite, "
        "NRST a slow node with a switch on it."),
    "VDDA 100nF C307 to U301.9": "see the VDDA 1uF note above",
    "VDDA ferrite FB301 to U301.9": "see the VDDA 1uF note above",
    "NRST cap C309 to U301.7": "see the VDDA 1uF note above",
    "clamp loop (no FET)": (
        "Floor is about 24 mm: the closing edge between J201's own VIN and "
        "coil pins is 5.08 mm, each of the two legs that touch those pads has "
        "to drop at least 3.4 mm clear of the terminal's 12.6 mm body before "
        "it reaches anything, and the SMA/SMB/0805 chain adds two hops of "
        "about 5 mm. ADR 0003's 'closed within about 15 mm' is a statement "
        "about the loop AREA over solid bottom ground, which this arrangement "
        "does satisfy - the parts sit in a 10 x 12 mm block directly under "
        "the terminal."),
    "flyback loop perimeter": (
        "J201's own body is 12.6 mm deep, so both legs touching its pads cost "
        "4 mm of vertical run before any part is reached; its pins are 5.08 mm "
        "apart; and the TO-252 plus the SMB span ~14 mm on their own. The "
        "6-vertex path the brief specifies also revisits the terminal, so it "
        "cannot close under about 30 mm. The clamp-only loop below is the "
        "number ADR 0003 actually cares about."),
}

# Closed polygons whose perimeter is measured and reported.
LOOPS = [
    # (label, target, vertices) - vertices are pad specs or bare refs.
    ("flyback loop perimeter", 16.0,
     ["J201.2", "Q201.2", "D201.2", "D202.1", "C102.1", "J201.1"]),
    ("clamp loop (no FET)", 16.0,
     ["J201.2", "D201", "D202", "C102", "J201.1"]),
]

# ------------------------------------------------------ flyback variants ----
# The clamp corner is boxed in by J201's body (above), Q201's 11 mm DPAK, the
# shunt (below) and J402's courtyard (right), so instead of one hand-tuned
# arrangement the script tries several and keeps the one with the shortest
# clamp loop. Coordinates are absolute - they are tied to J201, not to a block
# anchor. (ref, x, y, rot)
FLYBACK_CANDIDATES = {
    # D201 pad 2 is COIL_NEG and pad 1 CLAMP, so rot 0 puts COIL_NEG to the
    # right; D202 pad 1 is CLAMP and pad 2 VIN.
    "row-under-terminal": [
        ("D201", 60.0, 15.0, 0), ("D202", 67.5, 15.4, 0),
        ("C103", 67.0, 19.5, 0), ("C102", 71.5, 19.5, 0),
        ("Q201", 59.5, 21.5, 0), ("Q202", 71.5, 23.0, 0),
    ],
    "fet-under-coil-pin": [
        ("Q201", 64.0, 19.5, 90), ("D201", 69.5, 15.5, 0),
        ("D202", 69.5, 19.8, 0), ("C102", 72.5, 23.0, 0),
        ("C103", 68.5, 23.5, 0), ("Q202", 60.0, 15.5, 0),
    ],
    "diodes-between-pins": [
        ("D201", 63.0, 15.2, 0), ("D202", 63.0, 19.6, 0),
        ("C102", 69.0, 15.2, 0), ("C103", 69.0, 18.0, 0),
        ("Q201", 63.5, 25.0, 0), ("Q202", 72.5, 16.0, 0),
    ],
    "stack-under-coil-pin": [
        ("D201", 63.5, 15.2, 0), ("D202", 67.0, 19.6, 0),
        ("C102", 69.5, 15.2, 0), ("C103", 73.0, 15.2, 0),
        ("Q201", 63.0, 25.5, 0), ("Q202", 74.0, 23.0, 0),
    ],
    "fet-right-diodes-left": [
        ("Q201", 68.0, 19.5, 0), ("D201", 58.5, 15.2, 0),
        ("D202", 58.5, 19.8, 0), ("C102", 63.5, 15.2, 0),
        ("C103", 63.5, 18.0, 0), ("Q202", 63.0, 23.0, 0),
    ],
}

# Nets whose ratsnest length is worth watching every run.
WATCH_NETS = [
    "/Driver/CLAMP", "/Driver/COIL_NEG", "/Driver/SHUNT_HI", "VIN",
    "/MCU/OSC_IN", "/MCU/OSC_OUT", "/MCU/USB_DP", "/MCU/USB_DM",
    "+3V3", "+5V", "I_SENSE", "Net-(U101-SW)", "Net-(Q201-G)",
]


def kicad_netname(name):
    """Match KiCad's own net-name escaping.

    kicad-cli writes the netlist with the raw pin name, so the auto-generated
    name for U101's EN/UVLO pin comes out as 'Net-(U101-EN/UVLO)' while KiCad
    itself stores 'Net-(U101-EN{slash}UVLO)'. Without this the board and the
    schematic disagree on three pads (net_conflict). Only the text inside the
    Net-(...) wrapper is escaped - the slashes in a hierarchical name like
    /MCU/USB_DP are sheet-path separators and must stay.
    """
    if name.startswith("Net-(") and name.endswith(")"):
        inner = name[5:-1]
        for bad, good in (("{", "{brace}"), ("\\", "{backslash}"),
                          ("/", "{slash}")):
            inner = inner.replace(bad, good)
        return "Net-(" + inner + ")"
    return name


def mm(v):
    return pcbnew.FromMM(v)


def tomm(v):
    return pcbnew.ToMM(v)


def snap(v, g=GRID):
    return round(v / g) * g if g else v


def at(x, y):
    """Board-local mm -> page VECTOR2I."""
    return pcbnew.VECTOR2I(mm(ORIGIN[0] + x), mm(ORIGIN[1] + y))


def local(pos):
    """Page VECTOR2I -> board-local mm."""
    return (tomm(pos.x) - ORIGIN[0], tomm(pos.y) - ORIGIN[1])


# =========================================================== netlist =======
Comp = collections.namedtuple(
    "Comp", "ref value footprint sheet sheet_uuid uuid fields")


def export_netlist():
    os.makedirs(OUT, exist_ok=True)
    subprocess.run(
        ["kicad-cli", "sch", "export", "netlist", "--format", "kicadxml",
         "-o", NETLIST, SCH],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def read_netlist():
    root = ET.parse(NETLIST).getroot()
    comps = {}
    for c in root.find("components"):
        sp = c.find("sheetpath")
        fields = {}
        fl = c.find("fields")
        if fl is not None:
            for f in fl:
                fields[f.get("name")] = f.text or ""
        comps[c.get("ref")] = Comp(
            ref=c.get("ref"),
            value=c.findtext("value") or "",
            footprint=c.findtext("footprint") or "",
            sheet=sp.get("names") if sp is not None else "/",
            sheet_uuid=(sp.get("tstamps") if sp is not None else "/"),
            uuid=c.findtext("tstamps") or "",
            fields=fields,
        )
    nets = []
    for n in root.find("nets"):
        nodes = [(nd.get("ref"), nd.get("pin")) for nd in n.findall("node")]
        nets.append((n.get("name"), nodes))
    sheetfile = {}
    for c in root.find("components"):
        for p in c.findall("property"):
            if p.get("name") == "Sheetfile":
                sheetfile[c.get("ref")] = p.get("value")
    return comps, nets, sheetfile


# ============================================================= build =======
def read_sch_flags(refs):
    """ref -> {'in_bom': bool, 'dnp': bool} read out of the .kicad_sch files.

    The kicadxml netlist does not carry these, and setting them by hand here
    would show up as a footprint/symbol attribute mismatch in the parity
    check. In a symbol instance the flags precede the Reference property, so
    look back from each reference we care about.
    """
    import re
    want = set(refs)
    out = {}
    for fn in sorted(os.listdir(PROJ)):
        if not fn.endswith(".kicad_sch"):
            continue
        txt = open(os.path.join(PROJ, fn)).read()
        for m in re.finditer(r'\(property "Reference" "([^"]+)"', txt):
            ref = m.group(1)
            if ref not in want:
                continue
            head = txt[max(0, m.start() - 900):m.start()]
            bom = re.findall(r"\(in_bom (yes|no)\)", head)
            dnp = re.findall(r"\(dnp (yes|no)\)", head)
            rec = out.setdefault(ref, {})
            if bom:
                rec["in_bom"] = bom[-1] == "yes"
            if dnp:
                rec["dnp"] = dnp[-1] == "yes"
    return out


def build_board(comps, nets, sheetfile):
    board = pcbnew.CreateEmptyBoard()
    bds = board.GetDesignSettings()
    bds.SetCopperLayerCount(2)
    org = pcbnew.VECTOR2I(mm(ORIGIN[0]), mm(ORIGIN[1]))
    bds.SetAuxOrigin(org)
    bds.SetGridOrigin(org)

    draw_outline(board)

    schflags = read_sch_flags(comps)
    fps = {}
    for ref, c in sorted(comps.items()):
        lib, name = c.footprint.split(":", 1)
        fp = pcbnew.FootprintLoad(os.path.join(FPLIB, lib + ".pretty"), name)
        if fp is None:
            raise SystemExit("footprint not found for %s: %s" % (ref, c.footprint))
        # FootprintLoad drops the library nickname, which makes every part
        # read as a footprint/symbol mismatch in the parity check.
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(c.value)
        # UUID link back to the symbol: /<sheet uuid>/<symbol uuid>
        path = c.sheet_uuid.rstrip("/") + "/" + c.uuid
        if not path.startswith("/"):
            path = "/" + path
        fp.SetPath(pcbnew.KIID_PATH(path))
        fp.SetSheetname(c.sheet.strip("/") or "Root")
        fp.SetSheetfile(sheetfile.get(ref, ""))
        # Copy the symbol fields so a schematic/PCB field comparison is quiet.
        # SetField creates them VISIBLE on F.Silkscreen, which would bury the
        # board in MPNs; push them to F.Fab and hide them.
        for fname in ("LCSC", "MPN", "Datasheet", "Description"):
            val = c.fields.get(fname, "")
            if val:
                fp.SetField(fname, val)
                f = fp.GetField(fname)
                f.SetVisible(False)
                f.SetLayer(pcbnew.F_Fab)
        # DNP / BOM flags come from the schematic, never from here: the parity
        # check compares them and eeschema is the source of truth.
        flags = schflags.get(ref, {})
        if "in_bom" in flags:
            fp.SetExcludedFromBOM(not flags["in_bom"])
        if flags.get("dnp"):
            fp.SetDNP(True)
        board.Add(fp)
        fps[ref] = fp

    assign_nets(board, fps, nets)
    return board, fps


def draw_outline(board):
    w, h, r = BOARD_W, BOARD_H, CORNER_R
    segs = [((r, 0), (w - r, 0)), ((w, r), (w, h - r)),
            ((w - r, h), (r, h)), ((0, h - r), (0, r))]
    for a, b in segs:
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetStart(at(*a))
        s.SetEnd(at(*b))
        s.SetWidth(mm(EDGE_LINE_W))
        board.Add(s)
    k = r * (1 - math.sqrt(0.5))
    arcs = [((r, 0), (k, k), (0, r)),
            ((w - r, 0), (w - k, k), (w, r)),
            ((w, h - r), (w - k, h - k), (w - r, h)),
            ((r, h), (k, h - k), (0, h - r))]
    for start, mid, end in arcs:
        a = pcbnew.PCB_SHAPE(board)
        a.SetShape(pcbnew.SHAPE_T_ARC)
        a.SetLayer(pcbnew.Edge_Cuts)
        a.SetArcGeometry(at(*start), at(*mid), at(*end))
        a.SetWidth(mm(EDGE_LINE_W))
        board.Add(a)


def assign_nets(board, fps, nets):
    index = {}
    for ref, fp in fps.items():
        for pad in fp.Pads():
            num = pad.GetNumber()
            if num:
                index.setdefault((ref, num), []).append(pad)
    made = 0
    assigned = 0
    unmatched = []
    for netname, nodes in nets:
        mine = [(r, p) for r, p in nodes if r in fps]
        if not mine:
            continue
        net = pcbnew.NETINFO_ITEM(board, kicad_netname(netname))
        board.Add(net)
        made += 1
        for r, p in mine:
            pads = index.get((r, p))
            if not pads:
                unmatched.append("%s.%s" % (r, p))
                continue
            for pad in pads:
                pad.SetNet(net)
                assigned += 1
    board.BuildListOfNets()
    print("nets %d, pad assignments %d" % (made, assigned))
    if unmatched:
        print("WARNING netlist pins with no matching pad: %s" % ", ".join(unmatched))
    return made, assigned


# ========================================================== placement =====
def crtyd(fp):
    """Courtyard bbox in board-local mm, falling back to the footprint bbox."""
    try:
        poly = fp.GetCourtyard(pcbnew.F_CrtYd)
        if poly.OutlineCount() > 0:
            b = poly.BBox()
            return (tomm(b.GetLeft()) - ORIGIN[0], tomm(b.GetTop()) - ORIGIN[1],
                    tomm(b.GetRight()) - ORIGIN[0], tomm(b.GetBottom()) - ORIGIN[1])
    except Exception:
        pass
    b = fp.GetBoundingBox(False, False)
    return (tomm(b.GetLeft()) - ORIGIN[0], tomm(b.GetTop()) - ORIGIN[1],
            tomm(b.GetRight()) - ORIGIN[0], tomm(b.GetBottom()) - ORIGIN[1])


def fab_bbox(fp):
    """F.Fab bbox in board-local mm - the real BODY outline.

    Text is skipped on purpose: tidy_fab_text() grows each footprint's
    ${REFERENCE} to fill its body, and counting that as body made the
    rear-edge overhang check read 1.27 mm of silk as 1.27 mm of connector.
    """
    pts = []
    for it in fp.GraphicalItems():
        if it.GetClass() in ("PCB_TEXT", "PCB_TEXTBOX"):
            continue
        if it.GetLayer() == pcbnew.F_Fab:
            b = it.GetBoundingBox()
            pts.append((tomm(b.GetLeft()) - ORIGIN[0], tomm(b.GetTop()) - ORIGIN[1],
                        tomm(b.GetRight()) - ORIGIN[0], tomm(b.GetBottom()) - ORIGIN[1]))
    if not pts:
        return crtyd(fp)
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[2] for p in pts), max(p[3] for p in pts))


def boxes_clash(a, b, gap=COURTYARD_GAP):
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0] or
                a[3] + gap <= b[1] or b[3] + gap <= a[1])


def pair_gap(ga, gb):
    """Air required between two courtyards: tight inside a function group,
    COURTYARD_GAP between unrelated parts."""
    if ga and gb and ga == gb:
        return GROUP_GAP
    return COURTYARD_GAP


def put(fp, x, y, rot):
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(at(x, y))


def pad_xy(fps, spec):
    """'REF.PAD' -> board-local mm, or 'REF' -> its origin."""
    if "." in spec:
        ref, num = spec.split(".", 1)
        pad = fps[ref].FindPadByNumber(num)
        if pad is None:
            raise KeyError(spec)
        return local(pad.GetPosition())
    return local(fps[spec].GetPosition())


class Field:
    """Occupied courtyard boxes, each tagged with its function group."""

    def __init__(self):
        self.boxes = []       # (box, group)
        self.reserved = []    # (box, group) - virtual, no part

    def add(self, box, group=None):
        self.boxes.append((box, group))

    def reserve(self, box, group=None):
        self.reserved.append((box, group))

    def snapshot(self):
        return (len(self.boxes), len(self.reserved))

    def rollback(self, mark):
        del self.boxes[mark[0]:]
        del self.reserved[mark[1]:]

    def free(self, box, group=None, allow_overhang=0.0):
        if box[0] < 0.3 or box[2] > BOARD_W - 0.3:
            return False
        if box[1] < -allow_overhang or box[3] > BOARD_H - 0.3:
            return False
        for hx, hy in HOLES.values():
            if box_near_point(box, hx, hy) < M3_KEEPOUT:
                return False
        for t, tg in self.boxes + self.reserved:
            if boxes_clash(box, t, pair_gap(group, tg)):
                return False
        return True


def box_near_point(box, px, py):
    dx = max(box[0] - px, 0.0, px - box[2])
    dy = max(box[1] - py, 0.0, py - box[3])
    return math.hypot(dx, dy)


def box_gap(a, b):
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def resolve(fp, x, y, rot, field, ref, radial=None, step=GRID, rings=64,
            group=None, quiet=False, perp=None):
    """Place fp as near (x, y) as the field allows.

    With `radial` (the host pin's outward normal) and `perp` (along the host's
    edge) the search walks the ROW first and only then steps out a row. A
    plain radial spiral puts each nudged part on its own diagonal, which is
    what made the first pass read as a cloud of parts instead of rows.
    """
    if radial is not None and perp is not None:
        for ring in range(rings):
            cands = []
            for i in range(-2 * ring - 2, 2 * ring + 3):
                cands.append((ring * step * radial[0] + i * step * perp[0],
                              ring * step * radial[1] + i * step * perp[1]))
            cands.sort(key=lambda d: abs(d[0] * perp[0] + d[1] * perp[1]))
            for dx, dy in cands:
                nx, ny = snap(x + dx, step), snap(y + dy, step)
                put(fp, nx, ny, rot)
                box = crtyd(fp)
                if field.free(box, group):
                    field.add(box, group)
                    if ring and not quiet:
                        print("  row %-6s +%.1f mm out -> (%.1f, %.1f)"
                              % (ref, ring * step, nx, ny))
                    return box
        if quiet:
            return None
        raise SystemExit("no room for %s near (%.1f, %.1f)" % (ref, x, y))

    for ring in range(rings):
        if ring == 0:
            cands = [(0.0, 0.0)]
        else:
            r = ring * step
            n = max(8, 8 * ring)
            cands = []
            for k in range(n):
                a = 2 * math.pi * k / n
                dx, dy = r * math.cos(a), r * math.sin(a)
                if radial is not None:
                    # prefer candidates pointing away from the host pad
                    if dx * radial[0] + dy * radial[1] < -0.2 * r:
                        continue
                cands.append((dx, dy))
            cands.sort(key=lambda d: -(d[0] * radial[0] + d[1] * radial[1])
                       if radial else 0.0)
        for dx, dy in cands:
            nx, ny = snap(x + dx), snap(y + dy)
            put(fp, nx, ny, rot)
            box = crtyd(fp)
            if field.free(box, group):
                field.add(box, group)
                if ring and not quiet:
                    print("  nudge %-6s %+.1f mm -> (%.1f, %.1f)"
                          % (ref, ring * step, nx, ny))
                return box
    if quiet:
        return None
    raise SystemExit("no room for %s near (%.1f, %.1f)" % (ref, x, y))


def place_satellite(fps, ref, spec, field, step=GRID, group=None):
    """Put `ref` on the outward normal of its host pin, `side` mm across it."""
    host, pin, out, side = spec
    hostref = host.split(".")[0]
    hx, hy = pad_xy(fps, host)
    cx, cy = local(fps[hostref].GetPosition())
    vx, vy = hx - cx, hy - cy
    n = math.hypot(vx, vy)
    if n < 0.2:
        vx, vy, n = 0.0, 1.0, 1.0
    vx, vy = vx / n, vy / n
    # square the normal up so passives all sit at 0/90 degrees
    if abs(vx) >= abs(vy):
        vx, vy = (1.0 if vx > 0 else -1.0), 0.0
    else:
        vx, vy = 0.0, (1.0 if vy > 0 else -1.0)
    px, py = -vy, vx
    fp = fps[ref]
    tx = hx + out * vx + side * px
    ty = hy + out * vy + side * py
    # Aim the named pin at the host: try all four orthogonal rotations at the
    # target point and keep the one that puts that pad closest to the host pad.
    # (Doing this by hand only worked for two-pad parts; a SOT-23-5 whose
    # output is pin 5 came out backwards.)
    best = (1e9, 0)
    for cand in (0, 90, 180, 270):
        put(fp, snap(tx, step), snap(ty, step), cand)
        pad = fp.FindPadByNumber(pin)
        if pad is None:
            best = (0.0, cand)
            break
        p = local(pad.GetPosition())
        best = min(best, (math.hypot(p[0] - hx, p[1] - hy), cand))
    rot = best[1]
    return resolve(fp, snap(tx, step), snap(ty, step), rot, field, ref,
                   radial=(vx, vy), perp=(px, py), step=step, group=group)


def mcu_out_side(mcu, pads):
    """Which board direction the given pads face, as a unit (dx, dy)."""
    pts = [local(mcu.FindPadByNumber(p).GetPosition()) for p in pads]
    c = local(mcu.GetPosition())
    ux = sum(p[0] for p in pts) / len(pts) - c[0]
    uy = sum(p[1] for p in pts) / len(pts) - c[1]
    if abs(ux) >= abs(uy):
        return (1 if ux > 0 else -1, 0)
    return (0, 1 if uy > 0 else -1)


def place_group(fps, rows, bx, by, field, group, label, step=0.25, rings=80,
                quiet=False):
    """Place several parts as ONE rigid unit: spiral the whole arrangement
    outward from (bx, by) until every member's courtyard is free at once.

    The crystal island needs this. Placing the crystal and then its load caps
    one at a time let whichever went first steal the other's slot, and the
    caps ended up 5 mm from the pins they belong to.
    """
    for ring in range(rings):
        if ring == 0:
            offs = [(0.0, 0.0)]
        else:
            r = ring * step
            n = max(8, 6 * ring)
            offs = [(r * math.cos(2 * math.pi * k / n),
                     r * math.sin(2 * math.pi * k / n)) for k in range(n)]
        for dx, dy in offs:
            boxes = []
            for ref, ox, oy, rot in rows:
                put(fps[ref], snap(bx + dx + ox, step),
                    snap(by + dy + oy, step), rot)
                boxes.append(crtyd(fps[ref]))
            ok = all(field.free(b, group) for b in boxes)
            for i in range(len(boxes)):
                for k in range(i + 1, len(boxes)):
                    if boxes_clash(boxes[i], boxes[k], GROUP_GAP):
                        ok = False
            if ok:
                for b in boxes:
                    field.add(b, group)
                if ring and not quiet:
                    print("  nudge %-6s %+.1f mm (whole group)"
                          % (label, ring * step))
                return True
    raise SystemExit("no room for the %s group near (%.1f, %.1f)"
                     % (label, bx, by))


def place_edge(fp, ref, field):
    x, rot, axis, over = EDGE_PARTS[ref]
    put(fp, x, 0.0, rot)
    fb = fab_bbox(fp)
    # slide along y so the mating face lands `over` mm past the rear edge
    dy = -over - fb[1]
    put(fp, x, dy, rot)
    box = crtyd(fp)
    field.add(box)
    fb = fab_bbox(fp)
    print("  %-6s rot %3d  face y=%+.2f  body y[%.2f, %.2f]  x[%.2f, %.2f]"
          % (ref, rot, fb[1], fb[1], fb[3], box[0], box[2]))
    return box


def tidy_fab_text(fps):
    """Make the assembly view readable.

    Hide the Value field (it is what buried placement.png in "100nF 100V"
    strings) and grow each footprint's F.Fab ${REFERENCE} text to fill the
    body it sits in - the library default is 0.4 mm on a 0603 and 1.0 mm on a
    QFN, which is the wrong way round for reading a board. Silkscreen is not
    touched.
    """
    grown = 0
    for ref, fp in fps.items():
        fp.Value().SetVisible(False)
        w = h = None
        b = fab_bbox(fp)
        w, h = b[2] - b[0], b[3] - b[1]
        budget = max(w, h) / max(1.0, 0.78 * len(ref))
        size = max(0.4, min(1.2, min(min(w, h) * 0.7, budget)))
        for it in fp.GraphicalItems():
            if it.GetClass() == "PCB_TEXT" and it.GetLayer() == pcbnew.F_Fab \
                    and "REFERENCE" in it.GetText():
                it.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
                it.SetTextThickness(mm(max(0.08, size * 0.15)))
                grown += 1
    print("fab reference text scaled on %d footprints, Value hidden on %d"
          % (grown, len(fps)))


CRITICAL_NETS = [
    "/Driver/CLAMP", "/Driver/COIL_NEG", "VIN",          # flyback loop
    "Net-(U101-SW)", "Net-(U101-BST)",                   # buck switching node
    "/MCU/OSC_IN", "/MCU/OSC_OUT",                       # crystal
    "/MCU/USB_DP", "/MCU/USB_DM",                        # USB pair
    "I_SENSE", "/Driver/SHUNT_HI", "Net-(Q201-G)",       # sense and gate
]


def write_critical_board(board, fps):
    """Save a REVIEW-ONLY copy with the critical nets drawn as straight lines
    on User.1, for render.sh to turn into critical.png. The committed
    .kicad_pcb stays free of them."""
    pads = collections.defaultdict(list)
    for ref, fp in fps.items():
        for pad in fp.Pads():
            if pad.GetNetname() in CRITICAL_NETS:
                pads[pad.GetNetname()].append(local(pad.GetPosition()))
    drawn = 0
    for net, pts in pads.items():
        if len(pts) < 2:
            continue
        inside, edges = {0}, []
        while len(inside) < len(pts):
            best = (1e18, None, None)
            for i in inside:
                for j in range(len(pts)):
                    if j in inside:
                        continue
                    d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
                    if d < best[0]:
                        best = (d, i, j)
            edges.append((pts[best[1]], pts[best[2]]))
            inside.add(best[2])
        for a, b in edges:
            s = pcbnew.PCB_SHAPE(board)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetLayer(pcbnew.User_1)
            s.SetStart(at(*a))
            s.SetEnd(at(*b))
            s.SetWidth(mm(0.15))
            board.Add(s)
            drawn += 1
    out = os.path.join(OUT, "critical.kicad_pcb")
    pcbnew.SaveBoard(out, board)
    print("wrote %s (%d critical ratsnest lines on User.1, review only)"
          % (out, drawn))


def loop_perimeter(fps, verts):
    pts = [pad_xy(fps, v) for v in verts]
    return sum(math.hypot(pts[i][0] - pts[(i + 1) % len(pts)][0],
                          pts[i][1] - pts[(i + 1) % len(pts)][1])
               for i in range(len(pts)))


def place_flyback(fps, field):
    """Try each flyback arrangement, keep the shortest clamp loop."""
    verts = dict((lbl, v) for lbl, _t, v in LOOPS)["clamp loop (no FET)"]
    results = []
    for name, rows in FLYBACK_CANDIDATES.items():
        mark = field.snapshot()
        ok = True
        for ref, x, y, rot in rows:
            if resolve(fps[ref], x, y, rot, field, ref, group="flyback",
                       quiet=True, rings=14) is None:
                ok = False
                break
        score = loop_perimeter(fps, verts) if ok else float("inf")
        results.append((score, name, ok))
        field.rollback(mark)
    results.sort()
    print("flyback corner candidates (clamp loop, mm):")
    for score, name, ok in results:
        print("  %-22s %s" % (name, "%.1f" % score if ok else "did not fit"))
    best = results[0][1]
    for ref, x, y, rot in FLYBACK_CANDIDATES[best]:
        resolve(fps[ref], x, y, rot, field, ref, group="flyback")
    print("  chosen: %s" % best)
    return best


def search_mcu(fps, field):
    """Score every rotation x anchor for U301 and return the best pose."""
    mcu = fps["U301"]
    targets = []
    for pad, tgt, w in MCU_LINKS:
        try:
            targets.append((pad, pad_xy(fps, tgt), w, tgt))
        except KeyError:
            print("  MCU search: skipping link to %s (not placed)" % tgt)
    buck = crtyd(fps["U101"])
    x0, x1, xs = MCU_SEARCH_X
    y0, y1, ys = MCU_SEARCH_Y
    n = int(round((x1 - x0) / xs)) + 1
    m = int(round((y1 - y0) / ys)) + 1
    halo_mm = MCU_HALO
    cands = []
    while halo_mm >= 2.0 and not cands:
        for rot in (0, 90, 180, 270):
            for i in range(n):
                for j in range(m):
                    x, y = x0 + i * xs, y0 + j * ys
                    put(mcu, x, y, rot)
                    box = crtyd(mcu)
                    halo = (box[0] - halo_mm, box[1] - halo_mm,
                            box[2] + halo_mm, box[3] + halo_mm)
                    if not field.free(halo, "mcu-halo"):
                        continue
                    if box_gap(box, buck) < MCU_MIN_TO_BUCK:
                        continue
                    score = 0.0
                    per = {}
                    for pad, tp, w, label in targets:
                        p = local(mcu.FindPadByNumber(pad).GetPosition())
                        d = math.hypot(p[0] - tp[0], p[1] - tp[1])
                        score += w * d
                        per[label] = d
                    cands.append((score, x, y, rot, per))
        if not cands:
            halo_mm -= 1.0
    if not cands:
        raise SystemExit("MCU search found no legal pose at any halo")
    if halo_mm < MCU_HALO:
        print("  MCU search: halo relaxed %.0f -> %.0f mm to find a pose"
              % (MCU_HALO, halo_mm))
    cands.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    print("MCU pose search: %d legal poses of %d tried"
          % (len(cands), 4 * n * m))
    for score, x, y, rot, per in cands[:5]:
        worst = sorted(per.items(), key=lambda kv: -kv[1])[:4]
        print("  score %7.1f  at (%.1f, %.1f) rot %3d   %s"
              % (score, x, y, rot,
                 " ".join("%s %.0f" % (k.split('.')[0], v) for k, v in worst)))
    # score the first pass's hand-picked pose for comparison
    rx, ry, rrot = MCU_REFERENCE_POSE
    put(mcu, rx, ry, rrot)
    ref_score = sum(w * math.hypot(
        local(mcu.FindPadByNumber(pad).GetPosition())[0] - tp[0],
        local(mcu.FindPadByNumber(pad).GetPosition())[1] - tp[1])
        for pad, tp, w, _l in targets)
    print("  pass-1 hand-picked pose (%.1f, %.1f) rot %d scores %.1f"
          % (rx, ry, rrot, ref_score))
    score, x, y, rot, per = cands[0]
    print("  chosen (%.1f, %.1f) rot %d, score %.1f (%+.1f%% vs pass 1)"
          % (x, y, rot, score, 100.0 * (score - ref_score) / ref_score))
    print("  per-link: " + "  ".join("%s=%.1f" % (k, v)
                                     for k, v in sorted(per.items())))
    put(mcu, x, y, rot)
    field.add(crtyd(mcu), "mcu")
    return x, y, rot, score


def place_all(board, fps):
    field = Field()
    placed = set()
    # ref -> function group, filled in as parts land; satellites inherit.
    groups = dict(GROUP_SEED)

    def grp(ref, host=None):
        if ref in GROUP_OVERRIDE:
            return GROUP_OVERRIDE[ref]
        if ref in groups:
            return groups[ref]
        g = groups.get(host) if host else None
        g = g or "misc-" + ref
        groups[ref] = g
        return g

    # 1. mounting holes
    for ref, (x, y) in HOLES.items():
        put(fps[ref], x, y, 0)
        field.add(crtyd(fps[ref]), "mech")
        placed.add(ref)

    # 2. rear-edge connectors
    print("rear edge:")
    for ref in EDGE_PARTS:
        place_edge(fps[ref], ref, field)
        placed.add(ref)

    # 2b. VIN has to reach J201 pin 1 from the bulk capacitor along the rear
    # half without going past the MCU or the analog parts. Reserve the band
    # before anything else can sit in it.
    field.reserve(VIN_CORRIDOR, "vin-corridor")
    print("  VIN corridor reserved x[%.1f, %.1f] y[%.1f, %.1f]" % VIN_CORRIDOR)

    # 3. blocks whose position does not depend on the MCU
    for block in FIXED_BLOCKS:
        anchor, rows = ANCHORS[block]
        for ref, dx, dy, rot in rows:
            if ref in placed:
                continue
            resolve(fps[ref], anchor[0] + dx, anchor[1] + dy, rot, field, ref,
                    group=grp(ref) if ref in groups else block.lower())
            placed.add(ref)

    # 3b. the flyback corner, by trial
    for ref, _x, _y, _r in FLYBACK_CANDIDATES["row-under-terminal"]:
        placed.add(ref)
    place_flyback(fps, field)

    # 3c. gate driver, shunt and op-amp follow the FET
    for ref, spec, _g in DRIVER_SATS:
        place_satellite(fps, ref, spec, field,
                        group=grp(ref, spec[0].split(".")[0]))
        placed.add(ref)

    # 4. MCU pose by search, then the cluster around it
    search_mcu(fps, field)
    placed.add("U301")

    # 4a. USBLC6 on the line from the connector to the MCU's USB pads
    j = pad_xy(fps, "J301.A6")
    u = pad_xy(fps, "U301.33")
    # 180 degrees off the natural orientation: the USBLC6's pins 3/4 are one
    # I/O pair and 1/6 the other, and this pose is the one that puts D+ on the
    # LOW-x side at both rows. The MCU has D+ on pad 33 (low x) and the
    # connector's run leaves from B6 (low x), so with the other pose the pair
    # would have to cross itself once on each side of the diode.
    resolve(fps["U302"], snap((j[0] + u[0]) / 2), snap((j[1] + u[1]) / 2),
            180 if abs(u[0] - j[0]) > abs(u[1] - j[1]) else 270,
            field, "U302", group=grp("U302"))
    placed.add("U302")

    # 4b. MCU decoupling: it owns the ring right against the QFN.
    for ref in DECAPS:
        place_satellite(fps, ref, DECAPS[ref], field, step=0.25,
                        group=grp(ref, "U301"))
        placed.add(ref)

    # 4b2. ESCAPE CHANNELS, reserved before anything past the decaps lands.
    # The first ring is now closed: four VDD decoupling caps and the crystal
    # island, nothing else. The annulus keeps the second ring RING2_GAP clear
    # of the courtyard, which leaves a continuous tangential channel for pins
    # to run sideways in; one radial corridor per side gives them somewhere to
    # drain to. Without this the ADC filters, encoder debounce, pedal caps,
    # VDDA network and NRST cap walled the part in - a strict autoroute of the
    # pass-2 placement left 17 nets open, every one "boxed_in_static".
    mbox = crtyd(fps["U301"])
    g = RING2_GAP
    xtal_side = mcu_out_side(fps["U301"], XTAL_OSC_PADS)
    # One band per side, skipping the crystal's: the island has to come in to
    # 1.4 mm of the courtyard to stay inside its 5 mm limit. The neighbouring
    # bands still cover the corners.
    bands = {
        (0, -1): (mbox[0] - g, mbox[1] - g, mbox[2] + g, mbox[1]),
        (0, 1): (mbox[0] - g, mbox[3], mbox[2] + g, mbox[3] + g),
        (-1, 0): (mbox[0] - g, mbox[1] - g, mbox[0], mbox[3] + g),
        (1, 0): (mbox[2], mbox[1] - g, mbox[2] + g, mbox[3] + g),
    }
    for side, box in bands.items():
        if side != xtal_side:
            field.reserve(box, grp("U301"))
        else:
            # the crystal side gets a shallower band: the island has to reach
            # in to about 1.5 mm to keep the far OSC leg under 5 mm
            sx = XTAL_SIDE_GAP
            field.reserve((mbox[0] - sx, mbox[3], mbox[2] + sx, mbox[3] + sx)
                          if side == (0, 1) else
                          (mbox[0] - sx, mbox[1] - sx, mbox[2] + sx, mbox[1])
                          if side == (0, -1) else
                          (mbox[0] - sx, mbox[1] - sx, mbox[0], mbox[3] + sx)
                          if side == (-1, 0) else
                          (mbox[2], mbox[1] - sx, mbox[2] + sx, mbox[3] + sx),
                          grp("U301"))
    mcx = (mbox[0] + mbox[2]) / 2.0
    mcy = (mbox[1] + mbox[3]) / 2.0
    hw = CORRIDOR_W / 2.0
    n_corr = 0
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        if (dx, dy) == xtal_side:
            continue          # the crystal island lives on this side
        if dy:
            y0 = mbox[3] if dy > 0 else mbox[1] - CORRIDOR_LEN
            field.reserve((mcx - hw, y0, mcx + hw, y0 + CORRIDOR_LEN),
                          grp("U301"))
        else:
            x0 = mbox[2] if dx > 0 else mbox[0] - CORRIDOR_LEN
            field.reserve((x0, mcy - hw, x0 + CORRIDOR_LEN, mcy + hw),
                          grp("U301"))
        n_corr += 1
    print("  escape channels: %.1f mm bands on 3 sides + %d x %.1f mm "
          "corridors; crystal side %s exempt (island holds it)"
          % (RING2_GAP, n_corr, CORRIDOR_W, xtal_side))

    # 4c. crystal island, driven off the real OSC pad positions
    mcu = fps["U301"]
    osc = [local(mcu.FindPadByNumber(p).GetPosition()) for p in XTAL_OSC_PADS]
    mcu_c = local(mcu.GetPosition())
    ox = sum(p[0] for p in osc) / 2.0
    oy = sum(p[1] for p in osc) / 2.0
    ux, uy = ox - mcu_c[0], oy - mcu_c[1]
    if abs(ux) >= abs(uy):
        out = (1.0 if ux > 0 else -1.0, 0.0)
    else:
        out = (0.0, 1.0 if uy > 0 else -1.0)
    # Slide the whole island sideways, away from the higher pin numbers.
    # VDDA/VSSA/NRST (pads 7-9) are two pins from OSC_IN/OSC_OUT, so an island
    # centred on the OSC pads parks itself in front of them and pushes the
    # VDDA filter 6 mm out. Biasing towards pad 5's end keeps both happy.
    p5, p6 = osc
    sx, sy = p5[0] - p6[0], p5[1] - p6[1]
    n = math.hypot(sx, sy) or 1.0
    bias = (sx / n * XTAL_BIAS, sy / n * XTAL_BIAS)
    ox, oy = ox + bias[0], oy + bias[1]
    perp = (-out[1], out[0])
    xr = 90 if out[0] else 0
    # The island is RIGID: load caps flanking the OSC pair between crystal
    # and MCU as ADR 0003 requires, crystal behind them. Placing the three one
    # at a time let whichever went first steal the others' slot, which put the
    # load caps 5 mm from the pins they belong to.
    # Try the crystal both ways round and keep whichever puts XIN/XOUT
    # (pads 1 and 3) nearer OSC_IN/OSC_OUT - the footprint's pad 1 is at a
    # corner, so the wrong way costs over a millimetre on one leg.
    best = None
    for flip in (0, 180):
        mark = field.snapshot()
        rows = []
        for ref, po, oo in XTAL_ISLAND:
            rows.append((ref,
                         po * perp[0] + oo * out[0],
                         po * perp[1] + oo * out[1],
                         (xr + flip) % 360 if ref == XTAL
                         else (90 if out[0] else 0)))
        place_group(fps, rows, ox, oy, field, grp(XTAL), "Y301 island",
                    quiet=True)
        d = max(measure(fps, "pad", "Y301.1", "U301.%s" % XTAL_OSC_PADS[0]),
                measure(fps, "pad", "Y301.3", "U301.%s" % XTAL_OSC_PADS[1]))
        field.rollback(mark)
        if best is None or d < best[0]:
            best = (d, flip, rows)
    if XTAL_FORCE_FLIP is not None and best[1] != XTAL_FORCE_FLIP:
        print("  crystal flip: search preferred %d deg (%.2f mm), forced to "
              "%d deg so OSC_IN stays on pad 5's side"
              % (best[1], best[0], XTAL_FORCE_FLIP))
        for flip, rows in (("keep", None),):
            pass
        rows = []
        for ref, po, oo in XTAL_ISLAND:
            rows.append((ref,
                         po * perp[0] + oo * out[0],
                         po * perp[1] + oo * out[1],
                         (xr + XTAL_FORCE_FLIP) % 360 if ref == XTAL
                         else (90 if out[0] else 0)))
        best = (best[0], XTAL_FORCE_FLIP, rows)
    place_group(fps, best[2], ox, oy, field, grp(XTAL), "Y301 island")
    print("  crystal flip %d deg, worst OSC leg %.2f mm"
          % (best[1], max(measure(fps, "pad", "Y301.1", "U301.%s" % XTAL_OSC_PADS[0]),
                          measure(fps, "pad", "Y301.3", "U301.%s" % XTAL_OSC_PADS[1]))))
    for ref, _p, _o in XTAL_ISLAND:
        placed.add(ref)
    # keep the island clear
    island = [crtyd(fps[r]) for r in (XTAL,) + XTAL_LOADS]
    field.reserve((min(b[0] for b in island) - XTAL_CLEAR,
                   min(b[1] for b in island) - XTAL_CLEAR,
                   max(b[2] for b in island) + XTAL_CLEAR,
                   max(b[3] for b in island) + XTAL_CLEAR), grp(XTAL))

    # 4d. VDDA filter and the NRST cap next, now outside the annulus.
    for ref in MCU_RING_FIRST:
        host = SATELLITES[ref][0].split(".")[0]
        place_satellite(fps, ref, SATELLITES[ref], field, step=0.25,
                        group=grp(ref, host))
        placed.add(ref)

    # 4e. the rest of the ring
    for ref in MCU_RING:
        if ref in SATELLITES:
            host = SATELLITES[ref][0].split(".")[0]
            place_satellite(fps, ref, SATELLITES[ref], field, step=0.25,
                            group=grp(ref, host))
            placed.add(ref)

    # 5. satellites, in dependency order
    pending = [r for r in SATELLITES if r not in placed]
    guard = 0
    while pending and guard < 40:
        guard += 1
        again = []
        for ref in pending:
            if SATELLITES[ref][0].split(".")[0] not in placed:
                again.append(ref)
                continue
            host = SATELLITES[ref][0].split(".")[0]
            place_satellite(fps, ref, SATELLITES[ref], field,
                            group=grp(ref, host))
            placed.add(ref)
        pending = again
    for ref in pending:
        print("  WARNING unresolved satellite host for %s" % ref)

    # 6. whatever is left: next to the nearest already-placed part it shares a
    #    net with, else into the first free slot in the front strip.
    rest = [r for r in fps if r not in placed]
    if rest:
        print("  generic placement (no rule): %s" % ", ".join(sorted(rest)))
    netmates = build_netmates(board, fps)
    for ref in sorted(rest, key=lambda r: -len(netmates.get(r, ()))):
        seed = None
        best = 1e9
        for mate in netmates.get(ref, ()):
            if mate in placed:
                mx, my = local(fps[mate].GetPosition())
                d = math.hypot(mx - BOARD_W / 2, my - BOARD_H / 2)
                if d < best:
                    best, seed = d, (mx, my)
        if seed is None:
            seed = (BOARD_W / 2, BOARD_H - 8)
        resolve(fps[ref], snap(seed[0]), snap(seed[1] + 3.0), 0, field, ref)
        placed.add(ref)
    return field


def build_netmates(board, fps):
    """ref -> set of refs it shares a non-power net with (power nets are too
    big to say anything about locality)."""
    pads_by_net = collections.defaultdict(list)
    for ref, fp in fps.items():
        for pad in fp.Pads():
            if pad.GetNetCode():
                pads_by_net[pad.GetNetname()].append(ref)
    mates = collections.defaultdict(set)
    for net, refs in pads_by_net.items():
        if net in ("GND", "+3V3", "+5V", "VIN") or len(set(refs)) > 6:
            continue
        for a in refs:
            for b in refs:
                if a != b:
                    mates[a].add(b)
    return mates


# ============================================================= checks =====
def check_all(fps, field):
    fail = []
    boxes = {r: crtyd(f) for r, f in fps.items()}

    for a in sorted(boxes):
        for b in sorted(boxes):
            if a >= b:
                continue
            if boxes_clash(boxes[a], boxes[b], gap=0.0):
                fail.append("courtyard overlap: %s / %s" % (a, b))

    # Containment. The rear connectors are allowed to hang their BODY over the
    # rear edge by the amount EDGE_PARTS declares; their courtyard may follow
    # it out by up to another millimetre. Everything else stays inside.
    for ref, box in sorted(boxes.items()):
        over = EDGE_PARTS[ref][3] if ref in EDGE_PARTS else 0.0
        body = fab_bbox(fps[ref])
        if box[0] < -0.01 or box[2] > BOARD_W + 0.01:
            fail.append("%s courtyard outside board in x: %.2f..%.2f"
                        % (ref, box[0], box[2]))
        if box[3] > BOARD_H + 0.01:
            fail.append("%s courtyard past the front edge: %.2f" % (ref, box[3]))
        if body[1] < -over - 0.01:
            fail.append("%s body %.2f mm past the rear edge (allowed %.2f)"
                        % (ref, -body[1], over))
        if box[1] < -(over + 1.0) - 0.01:
            fail.append("%s courtyard %.2f mm past the rear edge (allowed %.2f)"
                        % (ref, -box[1], over + 1.0))

    for hole, (hx, hy) in sorted(HOLES.items()):
        for ref, box in sorted(boxes.items()):
            if ref in HOLES:
                continue
            d = box_near_point(box, hx, hy)
            if d < M3_KEEPOUT:
                fail.append("%s is %.2f mm from %s (keepout %.1f)"
                            % (ref, d, hole, M3_KEEPOUT))

    off = [r for r, f in fps.items() if f.IsFlipped()]
    if off:
        fail.append("not on the top side: %s" % ", ".join(sorted(off)))
    return fail


def measure(fps, kind, a, b):
    if kind == "pad":
        ax, ay = pad_xy(fps, a)
        bx, by = pad_xy(fps, b)
        return math.hypot(ax - bx, ay - by)
    return box_gap(crtyd(fps[a]), crtyd(fps[b]))


def criteria_table(fps):
    print("\nADR 0003 placement criteria")
    print("  %-46s %9s %9s  %s" % ("criterion", "measured", "limit", ""))
    bad = []
    for label, kind, a, b, limit, direction in CRITERIA:
        try:
            d = measure(fps, kind, a, b)
        except KeyError as e:
            print("  %-46s %9s %9s  SKIP (%s)" % (label, "-", "-", e))
            continue
        ok = d <= limit if direction == "max" else d >= limit
        adv = label in ADVISORY
        print("  %-46s %8.2f %s%8.2f  %s"
              % (label, d, "<=" if direction == "max" else ">=", limit,
                 "PASS" if ok else ("OVER (advisory)" if adv else "FAIL")))
        if not ok and not adv:
            bad.append(label)

    for label, target, verts in LOOPS:
        try:
            d = loop_perimeter(fps, verts)
        except KeyError as e:
            print("  %-46s %9s %9s  SKIP (%s)" % (label, "-", "-", e))
            continue
        adv = label in ADVISORY
        ok = d <= target
        print("  %-46s %8.2f <=%8.2f  %s"
              % (label, d, target,
                 "PASS" if ok else ("OVER (advisory)" if adv else "FAIL")))
        if not ok and not adv:
            bad.append(label)

    shown = set()
    for label in [c[0] for c in CRITERIA] + [l[0] for l in LOOPS]:
        if label in ADVISORY and label not in shown:
            shown.add(label)
            print("  advisory - %s:" % label)
            for line in _wrap(ADVISORY[label], 68):
                print("      " + line)
    return bad


def _wrap(text, width):
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        out.append(line)
    return out


def ratsnest(board, fps):
    """Sum of the MST over each net's pad positions - a placement cost."""
    pads = collections.defaultdict(list)
    for ref, fp in fps.items():
        for pad in fp.Pads():
            if pad.GetNetCode() and not pad.GetNetname().startswith("unconnected-"):
                pads[pad.GetNetname()].append(local(pad.GetPosition()))
    out = {}
    for net, pts in pads.items():
        if len(pts) < 2:
            out[net] = 0.0
            continue
        inside = {0}
        total = 0.0
        while len(inside) < len(pts):
            best = (1e18, None)
            for i in inside:
                for j in range(len(pts)):
                    if j in inside:
                        continue
                    d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
                    if d < best[0]:
                        best = (d, j)
            total += best[0]
            inside.add(best[1])
        out[net] = total
    return out


def ratsnest_report(rn):
    print("\nratsnest (MST over pads, mm)")
    print("  total over all nets: %.0f" % sum(rn.values()))
    for net in WATCH_NETS:
        if net in rn:
            print("  %-22s %7.1f" % (net, rn[net]))
    worst = sorted(rn.items(), key=lambda kv: -kv[1])[:8]
    print("  longest nets: " + ", ".join("%s %.0f" % (n, d) for n, d in worst))


# =============================================================== main =====
def main():
    do_netlist = "--no-netlist" not in sys.argv
    do_copper = "--copper" in sys.argv
    pro_before = None
    if os.path.exists(PRO):
        with open(PRO, "rb") as fh:
            pro_before = fh.read()

    if do_netlist:
        export_netlist()
    comps, nets, sheetfile = read_netlist()
    print("components in netlist: %d" % len(comps))

    board, fps = build_board(comps, nets, sheetfile)
    field = place_all(board, fps)

    tidy_fab_text(fps)
    fail = check_all(fps, field)
    bad = criteria_table(fps)
    rn = ratsnest(board, fps)
    ratsnest_report(rn)

    board.BuildConnectivity()
    pcbnew.SaveBoard(PCB, board)
    print("\nwrote %s" % PCB)
    write_critical_board(board, fps)

    # pcbnew.SaveBoard may touch the sibling project; the .kicad_pro is a
    # committed file and must not move.
    if pro_before is not None:
        with open(PRO, "rb") as fh:
            if fh.read() != pro_before:
                with open(PRO, "wb") as w:
                    w.write(pro_before)
                print("restored %s (SaveBoard had rewritten it)" % os.path.basename(PRO))
            else:
                print("%s unchanged" % os.path.basename(PRO))

    if fail:
        print("\nPLACEMENT CHECK FAILED (%d)" % len(fail))
        for f in fail:
            print("  " + f)
    if bad:
        print("\nADR CRITERIA FAILED (%d): %s" % (len(bad), "; ".join(bad)))
    if fail or bad:
        return 1
    print("\nall placement checks and ADR criteria pass")
    if do_copper:
        print("\n=== copper.py ===")
        return subprocess.call([sys.executable,
                                os.path.join(HERE, "copper.py")]
                               + [a for a in sys.argv[1:]
                                  if a in ("--no-drc", "--no-refill")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
