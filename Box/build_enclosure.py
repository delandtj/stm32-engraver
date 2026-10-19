# build_enclosure.py - regenerate the graver controller enclosure from the
# "Params" spreadsheet (ADR 0006).
#
# Run inside FreeCAD (Macro > Macros... > build_enclosure.py > Execute) with
# Box/enclosure.FCStd open, or with no document open (it opens or creates it).
# Edit a cell in Params, run the macro again: Tray, Cover, PCB and the check
# bodies are rebuilt, clearances are printed, and the STL/STEP exports in Box/
# are rewritten (set EXPORT = False below to skip exports).
#
# Coordinates: X left->right seen from the front, Y front->rear, Z up.
# Origin is the outer front-left-bottom corner of the tray.

import math
import os

import FreeCAD as App
import Part

EXPORT = True
DOC_NAME = "enclosure"

try:
    BOX_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    BOX_DIR = os.path.expanduser("~/Electronics/stm32-engraver/Box")

# (alias, default, comment). ADR 0006 names first, then derived/extra values.
DEFAULTS = [
    ("PCB_W", 85.0, "ADR: board width (Edge.Cuts)"),
    ("PCB_D", 60.0, "ADR: board depth (Edge.Cuts)"),
    ("PCB_T", 1.6, "board thickness"),
    ("HOLE_PX", 77.0, "ADR HOLE_PITCH x (MH401-404)"),
    ("HOLE_PY", 52.0, "ADR HOLE_PITCH y"),
    ("HOLE_INSET", 4.0, "ADR: holes 4 mm from corners"),
    ("HOLE_D", 3.2, "board NPTH hole"),
    ("WALL", 2.4, "ADR: 6 perimeters at 0.4"),
    ("STANDOFF", 6.0, "ADR: board bottom above tray floor"),
    ("USB_GAP", 0.5, "ADR: rear wall inner face behind board rear edge"),
    ("FRONT_BAY", 25.0, "ADR: tray depth in front of the board"),
    ("TRAY_LIP", 4.0, "ADR: lip height above floor"),
    ("TILT", 15.0, "ADR: top slope, deg"),
    ("H_FRONT", 35.0, "ADR: cover front wall height (above tray floor)"),
    ("USB_W", 13.0, "ADR: USB-C opening width"),
    ("USB_H", 8.0, "ADR: USB-C opening height"),
    ("USB_Z", 1.6, "TBD measure: receptacle centre above board top"),
    ("GX12_D", 12.2, "TBD measure: GX12 panel hole (ADR 'GX12 hole')"),
    ("GX16_D", 16.2, "TBD measure: GX16 panel hole (ADR 'GX16 hole')"),
    ("CABLE_D", 5.0, "TBD measure: brick cable OD (hole = +0.5)"),
    ("DISP_W", 27.5, "ADR: module PCB width (vendor drawing)"),
    ("DISP_L", 39.0, "ADR: module PCB length (vendor drawing)"),
    ("DISP_PCB_T", 1.2, "module PCB thickness (vendor drawing)"),
    ("LCD_T", 1.9, "glass/BL stack on the PCB front, measured 2026-10-19, total 3.1"),
    ("DISP_T", "=DISP_PCB_T + LCD_T", "ADR: PCB + glass stack (formula)"),
    ("BL_W", 26.16, "ADR GLASS: glass/backlight width, centred (vendor drawing)"),
    ("BL_L", 29.22, "ADR GLASS: glass/backlight length (vendor drawing)"),
    ("BL_Y0", 4.89, "BL edge from the PCB header edge"),
    ("DISP_ACTIVE", 23.4, "ADR: active area AA, square, centred left-right (vendor drawing)"),
    ("AA_Y0", 6.22, "AA edge from the PCB header edge (AA centre 17.92)"),
    ("DISP_LIP", 1.7, "ADR: rail lip, inner edge this far in from the PCB long edge"),
    ("HDR_N", 7.0, "header pins"),
    ("HDR_PITCH", 2.54, "header pitch"),
    ("HDR_Y", 2.5, "header row from the PCB header edge"),
    ("HDR_FRONT", 1.5, "max pin tail height on the PCB front (top skin keeps +0.5)"),
    ("HDR_BACK", 8.5, "header body + pins behind the PCB (check body only)"),
    ("DISP_HOLE_PX", 22.5, "module mounting hole pitch across"),
    ("DISP_HOLE_PY", 34.0, "module mounting hole pitch along (2.5 from each short edge)"),
    ("DISP_HOLE_D", 2.2, "module mounting hole dia (assumed)"),
    ("FPC_RELIEF", 1.0, "relief for the FPC fold strip past the BL far edge / in the end stop"),
    ("ENC_BUSH", 7.8, "ADR: encoder bushing dia, measured 2026-10-19 (hole = +0.3)"),
    ("ENC_BUSH_L", 6.0, "encoder bushing length, measured 2026-10-19"),
    ("ENC_NUT_AF", 10.0, "encoder nut across flats, measured 2026-10-19"),
    ("ENC_NUT_T", 2.0, "encoder nut thickness, measured 2026-10-19 (one under, one on top)"),
    ("ENC_PANEL", 2.0, "ADR: local top thickness at encoder (2 nuts + panel = bushing)"),
    # --- extra, not in the ADR table ---
    ("SIDE_GAP", 9.5, "board edge to side wall inner face (room for screw columns)"),
    ("LIP_T", 1.6, "tray lip wall thickness"),
    ("LIP_GAP", 0.2, "clearance cover wall to tray lip"),
    ("INSERT_D", 4.0, "M3 heat-set insert hole dia"),
    ("INSERT_L", 5.5, "M3 heat-set insert hole depth"),
    ("BOSS_D", 8.0, "insert boss OD"),
    ("CBOSS_H", 6.0, "tray corner boss height above floor"),
    ("COL_D", 9.0, "cover screw boss OD (also tray corner boss OD)"),
    ("COL_H", 10.0, "cover screw boss length from its bottom face (sits on the tray boss)"),
    ("GUSSET_ANGLE", 65.0, "boss gusset angle from horizontal in the cover print orientation, deg"),
    ("SCREW_CLR", 3.4, "M3 clearance hole in tray corner bosses"),
    ("CBORE_D", 6.0, "counterbore for M3 socket head, from below the tray"),
    ("CBORE_H", 3.4, "counterbore depth (head 3.0 sits 0.4 below the floor)"),
    ("SAC_LAYER", 0.3, "sacrificial bridge over the screw hole at the counterbore top; pierce it"),
    ("FOOT_D", 10.0, "rubber foot recess dia"),
    ("FOOT_H", 1.0, "rubber foot recess depth"),
    ("FOOT_INSET", 15.0, "foot centre from outer edges (clear of the screw counterbores)"),
    ("KICAD_X0", 50.0, "KiCad x of board left edge"),
    ("KICAD_Y0", 50.0, "KiCad y of board rear edge"),
    ("DISP_KX", 80.0, "KiCad x of display module centre (J401)"),
    ("DISP_Y0", 0.0, "module lower end, mm behind board front edge (plan)"),
    ("RAIL_W", 2.0, "rail leg width"),
    ("RAIL_LIP_T", 1.2, "rail lip thickness at its tip"),
    ("LIP_ANGLE", 60.0, "rail lip underside slope from horizontal in print orientation, deg"),
    ("WIN_CHAMF_ANGLE", 60.0, "window chamfer angle from horizontal in print orientation, deg"),
    ("TEARDROP_ANGLE", 60.0, "GX hole teardrop sides, min angle from horizontal in print, deg"),
    ("RAIL_CLR", 0.2, "module side/end clearance in rails"),
    ("WIN_MARGIN", 0.5, "ADR: window = active + 0.5 per side"),
    ("WIN_CHAMF", 1.5, "45 deg chamfer depth on window outside"),
    ("LATCH_T", 1.4, "snap tongue thickness (cut from the top, flexes outward)"),
    ("LATCH_L", 20.0, "snap tongue flex length (strain ~1.5 % at full deflection)"),
    ("LATCH_W", 4.0, "snap tongue width"),
    ("LATCH_HOOK", 0.9, "hook engagement over the module PCB end edge"),
    ("LATCH_DX", 11.5, "tongue offset from module centre (outside the 7-pin header)"),
    ("LATCH_SLIT", 0.6, "slit around the tongue, through the top"),
    ("ENC_KX", 108.0, "KiCad x of encoder axis (J403 at 101.5, moved for knob)"),
    ("ENC_BODY", 12.0, "EC11 body square"),
    ("ENC_BODY_H", 7.0, "EC11 body height below panel"),
    ("ENC_LUGS", 10.0, "room for loom solder on EC11 lugs"),
    ("KNOB_D", 20.0, "assumed knob dia (>= 3 mm from window)"),
    ("GX12_KX", 104.5, "KiCad x of GX12 axis (J201)"),
    ("GX12_Z", 18.0, "GX12 axis height above tray bottom"),
    ("GX12_DEPTH", 20.0, "TBD GX12 depth behind panel"),
    ("GX12_NUT", 15.0, "TBD GX12 nut across flats"),
    ("GX16_KX", 117.0, "KiCad x of GX16 axis (J402)"),
    ("GX16_Z", 20.0, "GX16 axis height above board top"),
    ("GX16_DEPTH", 22.0, "TBD GX16 depth behind panel"),
    ("GX16_NUT", 19.0, "TBD GX16 nut across flats"),
    ("CABLE_Z", 5.0, "cable hole centre above board top (hole x = middle of left side gap)"),
    ("TIE_LEN", 7.0, "cable-tie post length along the cable, starts 1 mm inside rear wall"),
    ("TIE_SLOT_W", 3.0, "tie slot width (for 2.5 mm ties)"),
    ("TIE_SLOT_H", 1.6, "tie slot height"),
    ("COL_RL_DY", 30.0, "rear-left column centre, mm in front of rear wall inner face (frees cable corner)"),
    ("USB_KX", 93.0, "KiCad x of J301"),
    ("C101_KX", 56.0, "KiCad x of C101"),
    ("C101_KY", 65.0, "KiCad y of C101"),
    ("C101_D", 12.5, "C101 dia"),
    ("C101_H", 20.0, "C101 height"),
    ("PARTS_H", 5.0, "check envelope: parts + solder joints above board"),
]

V = App.Vector


def get_doc():
    doc = App.listDocuments().get(DOC_NAME)
    if doc is None:
        path = os.path.join(BOX_DIR, "enclosure.FCStd")
        doc = App.openDocument(path) if os.path.exists(path) else App.newDocument(DOC_NAME)
    App.setActiveDocument(doc.Name)
    return doc


def ensure_params(doc):
    """Rewrite Params in DEFAULTS order, keeping values already in the sheet
    and dropping aliases that are no longer used."""
    sh = doc.getObject("Params")
    keep = {}
    if sh is None:
        sh = doc.addObject("Spreadsheet::Sheet", "Params")
    else:
        for alias, _, _ in DEFAULTS:
            cell = sh.getCellFromAlias(alias)
            if cell:
                keep[alias] = sh.getContents(cell)
        sh.clearAll()
    sh.set("A1", "Name")
    sh.set("B1", "Value (mm / deg)")
    sh.set("C1", "Comment")
    for i, (alias, val, comment) in enumerate(DEFAULTS):
        row = i + 2
        sh.set("A%d" % row, alias)
        sh.set("B%d" % row, keep.get(alias, val if isinstance(val, str) else str(val)))
        sh.setAlias("B%d" % row, alias)
        sh.set("C%d" % row, comment)
    doc.recompute()
    return sh


def read_params(sh):
    p = {}
    for alias, _, _ in DEFAULTS:
        v = sh.get(alias)
        p[alias] = float(getattr(v, "Value", v))
    return p


def box(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def cyl_z(x, y, d, z0, z1):
    return Part.makeCylinder(d / 2.0, z1 - z0, V(x, y, z0), V(0, 0, 1))


def cyl_y(x, z, d, y0, y1):
    return Part.makeCylinder(d / 2.0, y1 - y0, V(x, y0, z), V(0, 1, 0))


def fuse_all(shapes):
    s = shapes[0]
    if len(shapes) > 1:
        s = s.multiFuse(shapes[1:])
    return s.removeSplitter()


def build(p):
    g = {}
    t = math.radians(p["TILT"])
    WALL = p["WALL"]
    W = p["PCB_W"] + 2 * p["SIDE_GAP"] + 2 * WALL
    D = WALL + p["FRONT_BAY"] + p["PCB_D"] + p["USB_GAP"] + WALL
    bx0 = WALL + p["SIDE_GAP"]
    by_front = WALL + p["FRONT_BAY"]
    by_rear = by_front + p["PCB_D"]
    z_pcb_bot = WALL + p["STANDOFF"]
    z_pcb_top = z_pcb_bot + p["PCB_T"]
    z_cov0 = WALL

    def kx(x):
        return bx0 + (x - p["KICAD_X0"])

    def ky(y):
        return by_rear - (y - p["KICAD_Y0"])

    def ztop(y):
        return z_cov0 + p["H_FRONT"] + y * math.tan(t)

    def zund(y):
        return ztop(y) - WALL / math.cos(t)

    g.update(W=W, D=D, H_front=ztop(0), H_rear=ztop(D))

    # ---------------- PCB reference ----------------
    slab = box(bx0, bx0 + p["PCB_W"], by_front, by_rear, z_pcb_bot, z_pcb_top)
    vedges = [e for e in slab.Edges if abs(e.tangentAt(e.FirstParameter).z) > 0.99]
    slab = slab.makeFillet(1.0, vedges)
    hx = [bx0 + p["HOLE_INSET"], bx0 + p["HOLE_INSET"] + p["HOLE_PX"]]
    hy = [by_rear - p["HOLE_INSET"], by_rear - p["HOLE_INSET"] - p["HOLE_PY"]]
    holes = [(x, y) for x in hx for y in hy]
    for x, y in holes:
        slab = slab.cut(cyl_z(x, y, p["HOLE_D"], z_pcb_bot - 1, z_pcb_top + 1))
    c101 = cyl_z(kx(p["C101_KX"]), ky(p["C101_KY"]), p["C101_D"], z_pcb_top, z_pcb_top + p["C101_H"])
    ux = kx(p["USB_KX"])
    j301 = box(ux - 4.5, ux + 4.5, by_rear + p["USB_GAP"] - 7.3, by_rear + p["USB_GAP"],
               z_pcb_top, z_pcb_top + 3.2)
    g["PCB"] = fuse_all([slab, c101, j301])
    g["C101"] = c101
    g["PartsEnvelope"] = box(bx0, bx0 + p["PCB_W"], by_front, by_rear, z_pcb_top, z_pcb_top + p["PARTS_H"])

    # ---------------- Tray ----------------
    floor = box(0, W, 0, D, 0, WALL)
    lo = WALL + p["LIP_GAP"]
    li = lo + p["LIP_T"]
    lip = box(lo, W - lo, lo, D - lo, WALL, WALL + p["TRAY_LIP"]).cut(
        box(li, W - li, li, D - li, WALL - 1, WALL + p["TRAY_LIP"] + 1))
    # cover screw columns: three corners, the rear-left one moved forward
    # (COL_RL_DY) so the cable entry and its tie post own the rear-left corner
    ci = WALL + p["BOSS_D"] / 2.0
    cols = [(ci, ci), (W - ci, ci), (ci, D - WALL - p["COL_RL_DY"]), (W - ci, D - ci)]
    g["cols"] = cols
    parts = [floor, lip]
    for x, y in holes:
        parts.append(cyl_z(x, y, p["BOSS_D"], WALL - 0.1, z_pcb_bot))
    zc0 = WALL + p["CBOSS_H"]
    keep_in = box(lo, W - lo, lo, D - lo, 0, zc0 + 1)  # stay inside the cover walls
    for x, y in cols:
        parts.append(cyl_z(x, y, p["COL_D"], WALL - 0.1, zc0).common(keep_in))
    # cable entry in the left side gap; tie post just inside the rear wall,
    # cable lies in a cradle on top, tie goes through a slot under it
    cab_x = (li + bx0) / 2.0
    cab_z = z_pcb_top + p["CABLE_Z"]
    cab_d = p["CABLE_D"] + 0.5
    tx0, tx1 = li - 0.1, bx0 - 0.5
    ty1 = D - WALL - 1.0
    ty0 = ty1 - p["TIE_LEN"]
    post = box(tx0, tx1, ty0, ty1, WALL - 0.1, cab_z)
    post = post.cut(cyl_y(cab_x, cab_z, cab_d, ty0 - 1, ty1 + 1))
    sz1 = cab_z - cab_d / 2.0 - 1.0
    tym = (ty0 + ty1) / 2.0
    post = post.cut(box(tx0 - 1, tx1 + 1, tym - p["TIE_SLOT_W"] / 2, tym + p["TIE_SLOT_W"] / 2,
                        sz1 - p["TIE_SLOT_H"], sz1))
    parts.append(post)
    g["TiePost"] = post
    tray = fuse_all(parts)
    cuts = []
    for x, y in holes:
        cuts.append(cyl_z(x, y, p["INSERT_D"], z_pcb_bot - p["INSERT_L"], z_pcb_bot + 1))
    for x, y in cols:
        # M3 from below: counterbore flush with the floor, clearance hole up
        cuts.append(cyl_z(x, y, p["SCREW_CLR"], p["CBORE_H"] + p["SAC_LAYER"], zc0 + 1))
        cuts.append(cyl_z(x, y, p["CBORE_D"], -1, p["CBORE_H"]))
    fi = p["FOOT_INSET"]
    for x, y in [(fi, fi), (W - fi, fi), (fi, D - fi), (W - fi, D - fi)]:
        cuts.append(cyl_z(x, y, p["FOOT_D"], -1, p["FOOT_H"]))
    g["Tray"] = tray.cut(fuse_all(cuts)).removeSplitter()

    # ---------------- Cover ----------------
    def prism(y0, y1, z0, f0, f1, x0, x1):
        w = Part.makePolygon([V(x0, y0, z0), V(x0, y1, z0), V(x0, y1, f1), V(x0, y0, f0), V(x0, y0, z0)])
        return Part.Face(w).extrude(V(x1 - x0, 0, 0))

    outer = prism(0, D, z_cov0, ztop(0), ztop(D), 0, W)
    inner = prism(WALL, D - WALL, z_cov0 - 1, zund(WALL), zund(D - WALL), WALL, W - WALL)
    shell = outer.cut(inner)
    # short screw bosses at the rim, fused into the adjacent wall(s), with a
    # 45 deg gusset above them back into the wall(s) so they print top-down
    # without supports
    r = p["COL_D"] / 2.0
    zb1 = zc0 + p["COL_H"]
    big = max(W, D) + 20
    # gusset slope k = horizontal extent per mm of height (assembly frame), chosen
    # so the side-wall gusset face is GUSSET_ANGLE from horizontal once the cover
    # is rotated 180 - TILT about X for printing
    cb_ = math.cos(math.radians(p["GUSSET_ANGLE"]))
    ct_ = math.cos(t)
    k = cb_ / math.sqrt(max(ct_ * ct_ - cb_ * cb_, 1e-6))

    def wedge_x(wx, sgn, h):
        # region |x - wx| <= zb1 + h - z (sgn: side of the wall the box is on)
        pts = [V(wx - sgn, -10, zb1 - 1), V(wx + sgn * (h + 1), -10, zb1 - 1),
               V(wx + sgn * h, -10, zb1), V(wx, -10, zb1 + h / k), V(wx - sgn, -10, zb1 + h / k + 1),
               V(wx - sgn, -10, zb1 - 1)]
        return Part.Face(Part.makePolygon(pts)).extrude(V(0, big, 0))

    def wedge_y(wy, sgn, h):
        pts = [V(-10, wy - sgn, zb1 - 1), V(-10, wy + sgn * (h + 1), zb1 - 1),
               V(-10, wy + sgn * h, zb1), V(-10, wy, zb1 + h / k), V(-10, wy - sgn, zb1 + h / k + 1),
               V(-10, wy - sgn, zb1 - 1)]
        return Part.Face(Part.makePolygon(pts)).extrude(V(big, 0, 0))

    bosses = []
    for i, (x, y) in enumerate(cols):
        sx = -1 if x < W / 2 else 1           # which side wall
        wx = WALL if sx < 0 else W - WALL
        walls_y = i != 2                       # rear-left boss sits on the left wall only
        sy = -1 if y < D / 2 else 1
        wy = WALL if sy < 0 else D - WALL
        ox, oy = wx + sx * 0.5, wy + sy * 0.5   # 0.5 into the wall
        fp = [Part.makeCylinder(r, 1.0, V(x, y, 0)),
              box(min(ox, x), max(ox, x), y - r, y + r, 0, 1.0)]
        if walls_y:
            fp.append(box(x - r, x + r, min(oy, y), max(oy, y), 0, 1.0))
            fp.append(box(min(ox, x), max(ox, x), min(oy, y), max(oy, y), 0, 1.0))
        foot = fuse_all(fp)
        h = abs(x - wx) + r
        if walls_y:
            h = max(h, abs(y - wy) + r)
        m = App.Matrix()
        m.scale(1, 1, zb1 + h / k - zc0)
        solid = foot.transformGeometry(m)
        solid.translate(V(0, 0, zc0))
        # the side-wall gusset alone supports the whole footprint (h covers it).
        # A front-wall gusset is added too; a rear-wall one would be a 60 deg
        # overhang once the cover is tilted TILT for printing, so it is left out.
        gus = wedge_x(wx, -sx, h)
        if walls_y and sy < 0:
            gus = gus.fuse(wedge_y(wy, -sy, h))
        keep = box(-1, W + 1, -1, D + 1, zc0 - 1, zb1).fuse(gus)
        bosses.append(solid.common(keep))
    colsolid = fuse_all(bosses).common(outer)
    g["boss_top"] = zb1

    # roof frame: x = world x, y = up the slope from the module lower end,
    # z = outward normal (0 = roof underside, WALL = roof outer face)
    y_l = by_front + p["DISP_Y0"]
    roof_pl = App.Placement(V(0, y_l, zund(y_l)), App.Rotation(V(1, 0, 0), p["TILT"]))

    def roof(s):
        s = s.copy()
        s.Placement = roof_pl.multiply(s.Placement)
        return s

    dcx = kx(p["DISP_KX"])
    hw = p["DISP_W"] / 2.0
    slot_h = p["DISP_T"] + 0.3
    # lip underside (the PCB back rests on its edge line) rises at LIP_ANGLE
    # from the PCB edge inward, so it prints roof-down without supports
    lip_rise = (p["DISP_LIP"]) * math.tan(math.radians(p["LIP_ANGLE"]))
    rail_z0 = -(slot_h + lip_rise + p["RAIL_LIP_T"])
    rc = p["RAIL_CLR"]
    holder = []
    for s in (-1, 1):
        a = dcx + s * (hw + rc)
        b = dcx + s * (hw + rc + p["RAIL_W"])
        holder.append(box(min(a, b), max(a, b), 0, p["DISP_L"] + rc, rail_z0, 0.5))
        # one straight slope through the PCB edge point (xe, -slot_h); outside
        # the module it continues up into the leg, so no flat strip is left
        xl = dcx + s * (hw + rc + 0.5)     # inside the leg
        xt = dcx + s * (hw - p["DISP_LIP"])  # lip tip
        tl = math.tan(math.radians(p["LIP_ANGLE"]))
        zl = -slot_h + (rc + 0.5) * tl
        prof = Part.makePolygon([V(xl, 0, zl), V(xt, 0, -slot_h - lip_rise),
                                 V(xt, 0, rail_z0), V(xl, 0, rail_z0), V(xl, 0, zl)])
        holder.append(Part.Face(prof).extrude(V(0, p["DISP_L"] + rc, 0)))
    ow = hw + rc + p["RAIL_W"]
    estop = box(dcx - ow, dcx + ow, p["DISP_L"] + rc, p["DISP_L"] + rc + 2.0, rail_z0, 0.5)
    fr = p["FPC_RELIEF"]
    nw = p["DISP_ACTIVE"] / 2.0  # notch keeps the stop on the PCB corners only
    estop = estop.cut(box(dcx - nw, dcx + nw, p["DISP_L"] + rc - 0.1, p["DISP_L"] + rc + fr, rail_z0 - 1, 0.4))
    holder.append(estop)
    holder = roof(fuse_all(holder))

    # snap latch: two tongues cut from the top in front of the open rail end,
    # free end at the module end edge, hook reaches down over the PCB end edge.
    # The module slides in glass first, pushes the hooks outward over its ramp,
    # and the tongues spring back behind the PCB edge (header end).
    lt, ll, lw, sl = p["LATCH_T"], p["LATCH_L"], p["LATCH_W"], p["LATCH_SLIT"]
    v_f = -rc                                     # catch face, 0.2 in front of module
    z_hb = -p["LCD_T"] - p["LATCH_HOOK"]          # hook bottom, PCB front is at -LCD_T
    z_tu = WALL - lt                              # tongue underside
    ramp = (z_tu - z_hb) * 1.2
    latch_cut, latch_add = [], []
    for s in (-1, 1):
        cx = dcx + s * p["LATCH_DX"]
        latch_cut.append(box(cx - lw / 2 - sl, cx + lw / 2 + sl, v_f - ll, v_f + sl, -1, WALL + 1))
        latch_add.append(box(cx - lw / 2, cx + lw / 2, v_f - ll - 0.5, v_f, z_tu, WALL))
        prof = Part.makePolygon([V(cx - lw / 2, v_f, z_tu + 0.2), V(cx - lw / 2, v_f, z_hb),
                                 V(cx - lw / 2, v_f - 1.0, z_hb),
                                 V(cx - lw / 2, v_f - 1.0 - ramp, z_tu + 0.2),
                                 V(cx - lw / 2, v_f, z_tu + 0.2)])
        latch_add.append(Part.Face(prof).extrude(V(lw, 0, 0)))
    g["latch_strain"] = 1.5 * lt * (-z_hb) / (ll * ll)

    cover = fuse_all([shell, colsolid, holder])

    cc = []
    # screw columns: heat-set insert from below, top stays closed
    for x, y in cols:
        cc.append(cyl_z(x, y, p["INSERT_D"], zc0 - 1, zc0 + p["INSERT_L"]))
    # rear wall
    ry0, ry1 = D - WALL - 1, D + 1
    uz = z_pcb_top + p["USB_Z"]
    ub = box(ux - p["USB_W"] / 2, ux + p["USB_W"] / 2, ry0, ry1, uz - p["USB_H"] / 2, uz + p["USB_H"] / 2)
    yedges = [e for e in ub.Edges if abs(e.tangentAt(e.FirstParameter).y) > 0.99]
    cc.append(ub.makeFillet(1.0, yedges))
    g16x, g16z = kx(p["GX16_KX"]), z_pcb_top + p["GX16_Z"]
    # GX holes: teardrop pointing down in assembly (= up when the cover prints
    # top-down), truncated inside the nut's across-flats circle
    ct = math.cos(math.radians(p["TEARDROP_ANGLE"])) / math.cos(t)
    td_half = math.radians(90.0) - math.acos(min(1.0, ct))   # side half-angle from vertical

    def teardrop_y(x, z, dia, y0, y1, flat_r):
        rr = dia / 2.0
        tip = rr / math.sin(td_half)
        tz = min(tip, flat_r)
        hw_ = (tip - tz) * math.tan(td_half)
        tx = rr * math.cos(td_half)
        tzz = rr * math.sin(td_half)
        pts = [V(x - tx, y0, z - tzz), V(x - hw_, y0, z - tz), V(x + hw_, y0, z - tz), V(x + tx, y0, z - tzz)]
        if hw_ < 1e-3:
            pts = [pts[0], V(x, y0, z - tip), pts[3]]
        pts.append(V(x, y0, z))
        pts.append(pts[0])
        wedge = Part.Face(Part.makePolygon(pts)).extrude(V(0, y1 - y0, 0))
        return cyl_y(x, z, dia, y0, y1).fuse(wedge)

    g["td"] = {}
    for nm, (hx, hz, hd, nut, y0_, y1_) in {
            "GX16": (g16x, g16z, p["GX16_D"], p["GX16_NUT"], ry0, ry1),
            "GX12": (kx(p["GX12_KX"]), p["GX12_Z"], p["GX12_D"], p["GX12_NUT"], -1, WALL + 1)}.items():
        fr_ = nut / 2.0 - 0.5
        cc.append(teardrop_y(hx, hz, hd, y0_, y1_, fr_))
        tip_ = hd / 2.0 / math.sin(td_half)
        g["td"][nm] = (min(tip_, fr_), 2 * (tip_ - min(tip_, fr_)) * math.tan(td_half), nut / 2.0)
    cc.append(cyl_y(cab_x, cab_z, cab_d, ry0, ry1))
    # front wall
    g12x, g12z = kx(p["GX12_KX"]), p["GX12_Z"]
    # (GX12 hole is cut above, with the teardrop)
    # roof: display window with outside chamfer, M2 pilots
    vc = p["AA_Y0"] + p["DISP_ACTIVE"] / 2.0       # AA centre from the header edge
    win = p["DISP_ACTIVE"] + 2 * p["WIN_MARGIN"]
    rc_cuts = [box(dcx - win / 2, dcx + win / 2, vc - win / 2, vc + win / 2, -1, WALL + 1)]

    def sq(cx, cy, a, z):
        h = a / 2.0
        return Part.makePolygon([V(cx - h, cy - h, z), V(cx + h, cy - h, z), V(cx + h, cy + h, z),
                                 V(cx - h, cy + h, z), V(cx - h, cy - h, z)])

    ch = p["WIN_CHAMF"]
    wc = 1.0 / math.tan(math.radians(p["WIN_CHAMF_ANGLE"]))  # widening per mm of depth
    rc_cuts.append(Part.makeLoft([sq(dcx, vc, win, WALL - ch), sq(dcx, vc, win + 2 * (ch + 1) * wc, WALL + 1)], True))
    rc_cuts.extend(latch_cut)
    # top skin relief over the front pin tails of the header (+0.5 mm)
    hspan = (p["HDR_N"] - 1) * p["HDR_PITCH"] / 2.0 + 1.0
    hd = p["HDR_FRONT"] + 0.5 - p["LCD_T"]
    if hd > 0.01:
        rc_cuts.append(box(dcx - hspan, dcx + hspan, p["HDR_Y"] - 1.0, p["HDR_Y"] + 1.0, -1, hd))
    # relief over the FPC fold strip past the BL far edge
    bl1 = p["BL_Y0"] + p["BL_L"]
    rc_cuts.append(box(dcx - p["BL_W"] / 2, dcx + p["BL_W"] / 2, bl1, bl1 + 0.9 + fr, -1, fr))
    g["win_v"] = vc
    # encoder
    ecx = kx(p["ENC_KX"])
    rc_cuts.append(cyl_z(ecx, vc, p["ENC_BUSH"] + 0.3, -1, WALL + 1))
    # no anti-rotation slot: the inner nut holds the body off the panel.
    # Round pocket thins the top to ENC_PANEL over the nut clearance circle.
    nut_clr = p["ENC_NUT_AF"] / math.cos(math.radians(30)) + 2.0
    pz = WALL - p["ENC_PANEL"]
    if pz > 0.01:
        rc_cuts.append(cyl_z(ecx, vc, nut_clr, -1, pz))
    cc.append(roof(fuse_all(rc_cuts)))
    cover = cover.cut(fuse_all(cc))
    g["Cover"] = fuse_all([cover, roof(fuse_all(latch_add))])

    # ---------------- check bodies ----------------
    pcb = box(dcx - hw, dcx + hw, 0, p["DISP_L"], -p["DISP_T"], -p["LCD_T"])
    hx2, hy0 = p["DISP_HOLE_PX"] / 2.0, (p["DISP_L"] - p["DISP_HOLE_PY"]) / 2.0
    for sx in (-1, 1):
        for yy in (hy0, hy0 + p["DISP_HOLE_PY"]):
            pcb = pcb.cut(cyl_z(dcx + sx * hx2, yy, p["DISP_HOLE_D"], -10, 10))
    bl = box(dcx - p["BL_W"] / 2, dcx + p["BL_W"] / 2, p["BL_Y0"], p["BL_Y0"] + p["BL_L"], -p["LCD_T"], 0)
    hsp = (p["HDR_N"] - 1) * p["HDR_PITCH"] / 2.0
    tails = box(dcx - hsp - 0.5, dcx + hsp + 0.5, p["HDR_Y"] - 0.5, p["HDR_Y"] + 0.5,
                -p["LCD_T"], -p["LCD_T"] + p["HDR_FRONT"])
    back = box(dcx - hsp - 1.27, dcx + hsp + 1.27, p["HDR_Y"] - 1.27, p["HDR_Y"] + 1.27,
               -p["DISP_T"] - p["HDR_BACK"], -p["DISP_T"])
    g["DisplayModule"] = roof(fuse_all([pcb, bl, back]))
    g["HdrTails"] = roof(tails)
    g["HdrBack"] = roof(back)
    g["LatchHooks"] = roof(fuse_all(latch_add))
    g["DispPCB"] = roof(pcb)
    eb = p["ENC_BODY"] / 2.0
    zb = pz - p["ENC_NUT_T"]   # body sits under the inner nut
    g["EncoderKeepout"] = roof(box(ecx - eb, ecx + eb, vc - eb, vc + eb,
                                   zb - p["ENC_BODY_H"] - p["ENC_LUGS"], zb))
    g["EncNutClear"] = roof(cyl_z(ecx, vc, nut_clr, pz - p["ENC_NUT_T"] - 1.0, pz))
    # flat seat on the outside: nothing may stand above the top face there
    g["EncSeat"] = roof(cyl_z(ecx, vc, nut_clr, WALL, WALL + 5.0))
    n12 = p["GX12_NUT"] / math.cos(math.radians(30))
    g["GX12Keepout"] = fuse_all([cyl_y(g12x, g12z, p["GX12_D"], WALL, WALL + p["GX12_DEPTH"]),
                                 cyl_y(g12x, g12z, n12, WALL, WALL + 2.5)])
    n16 = p["GX16_NUT"] / math.cos(math.radians(30))
    g["GX16Keepout"] = fuse_all([cyl_y(g16x, g16z, p["GX16_D"], D - WALL - p["GX16_DEPTH"], D - WALL),
                                 cyl_y(g16x, g16z, n16, D - WALL - 3.0, D - WALL)])
    g["knob_gap"] = (ecx - p["KNOB_D"] / 2) - (dcx + win / 2)
    g["print_rot"] = 180.0 - p["TILT"]
    return g


def put(doc, name, shape, visible=True, color=None, transp=0, group=None):
    obj = doc.getObject(name)
    if obj is None:
        obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    if group is not None and obj not in group.Group:
        group.addObject(obj)
    if App.GuiUp:
        vo = obj.ViewObject
        vo.Visibility = visible
        if color:
            vo.ShapeColor = color
        vo.Transparency = transp
    return obj


def clearance(a, b):
    d = a.distToShape(b)[0]
    common = a.common(b).Volume if d < 1e-6 else 0.0
    return d, common


def report(g):
    print("Box outer: W %.1f x D %.1f, height front %.1f rear %.1f (from tray bottom)"
          % (g["W"], g["D"], g["H_front"], g["H_rear"]))
    print("Knob edge to window edge: %.1f mm" % g["knob_gap"])
    print("Window centre: %.2f mm up the slope from the module header edge" % g["win_v"])
    for nm, (d_, w_, nr) in g["td"].items():
        print("%s teardrop: flat %.1f mm below axis, flat width %.1f mm, nut inscribed radius %.1f"
              % (nm, d_, w_, nr))
    print("Latch tongue bending strain at full deflection: %.2f %%" % (100 * g["latch_strain"]))
    pairs = [("Cover", "PCB"), ("Cover", "PartsEnvelope"), ("DisplayModule", "PCB"),
             ("DisplayModule", "PartsEnvelope"), ("EncoderKeepout", "PCB"),
             ("EncoderKeepout", "PartsEnvelope"), ("GX12Keepout", "PCB"),
             ("GX12Keepout", "PartsEnvelope"), ("GX16Keepout", "PCB"),
             ("GX16Keepout", "PartsEnvelope"), ("GX16Keepout", "C101"), ("Tray", "PCB"),
             ("Tray", "Cover"), ("GX12Keepout", "DisplayModule"), ("GX12Keepout", "EncoderKeepout"),
             ("GX12Keepout", "Tray"), ("GX16Keepout", "Tray"), ("EncoderKeepout", "Cover"),
             ("DisplayModule", "Cover"), ("TiePost", "PCB"), ("TiePost", "C101"),
             ("HdrTails", "Cover"), ("HdrTails", "LatchHooks"), ("HdrBack", "Cover"),
             ("HdrBack", "PCB"), ("HdrBack", "PartsEnvelope"), ("LatchHooks", "DispPCB"),
             ("EncNutClear", "Cover"), ("EncSeat", "Cover")]
    for a, b in pairs:
        d, v = clearance(g[a], g[b])
        print("  %-15s vs %-14s dist %6.2f mm  common %8.2f mm3" % (a, b, d, v))


def export(g):
    import Mesh
    import MeshPart
    tray = g["Tray"]
    cover = g["Cover"].copy()
    cover.rotate(V(0, 0, 0), V(1, 0, 0), g["print_rot"])
    for name, s in (("tray", tray), ("cover", cover)):
        m = Mesh.Mesh(MeshPart.meshFromShape(Shape=s, LinearDeflection=0.05, AngularDeflection=0.2,
                                             Relative=False))
        bb = m.BoundBox  # exact on the mesh; the OCC shape box is padded
        m.translate(-bb.XMin, -bb.YMin, -bb.ZMin)
        m.write(os.path.join(BOX_DIR, name + ".stl"))
    tray.exportStep(os.path.join(BOX_DIR, "tray.step"))
    g["Cover"].exportStep(os.path.join(BOX_DIR, "cover.step"))
    print("Exported tray/cover .stl (print orientation) and .step (assembly position) to " + BOX_DIR)


def main(do_export=EXPORT):
    doc = get_doc()
    sh = ensure_params(doc)
    p = read_params(sh)
    g = build(p)
    grp = doc.getObject("Checks") or doc.addObject("App::DocumentObjectGroup", "Checks")
    put(doc, "Tray", g["Tray"], True, (0.25, 0.45, 0.75))
    put(doc, "Cover", g["Cover"], True, (0.85, 0.55, 0.2), 60)
    put(doc, "PCB", g["PCB"], True, (0.1, 0.55, 0.2))
    put(doc, "PartsEnvelope", g["PartsEnvelope"], False, (0.9, 0.9, 0.2), 70, grp)
    put(doc, "DisplayModule", g["DisplayModule"], True, (0.1, 0.1, 0.1), 0, grp)
    put(doc, "EncoderKeepout", g["EncoderKeepout"], True, (0.8, 0.1, 0.1), 50, grp)
    put(doc, "GX12Keepout", g["GX12Keepout"], True, (0.6, 0.6, 0.6), 30, grp)
    put(doc, "GX16Keepout", g["GX16Keepout"], True, (0.6, 0.6, 0.6), 30, grp)
    doc.recompute()
    report(g)
    if do_export:
        export(g)
    if doc.FileName:
        doc.save()
    return g


if __name__ == "__main__":
    main()
