"""Small KiCad 10 schematic toolkit: s-expression parsing, symbol geometry
and a sheet builder that emits .kicad_sch files with real wires.

Used by build.py to regenerate the four child sheets of the graver controller
from a hand-designed layout while keeping the verified parts and nets.
"""
import math
import re
import uuid
from pathlib import Path

# ---------------------------------------------------------------- s-expressions


class Sym(str):
    """A bare (unquoted) atom."""


def parse(text):
    """Parse an s-expression string into nested lists of Sym/str/float/int."""
    tok = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)
    text = text.strip()
    pos = 0
    stack = [[]]
    n = len(text)
    while pos < n:
        m = tok.match(text, pos)
        if not m:
            raise ValueError('parse error at %d' % pos)
        pos = m.end()
        if m.group(1):
            stack.append([])
        elif m.group(2):
            done = stack.pop()
            stack[-1].append(done)
        elif m.group(3) is not None:
            stack[-1].append(m.group(3).replace('\\"', '"'))
        elif m.group(4):
            a = m.group(4)
            try:
                v = float(a)
                stack[-1].append(int(v) if re.fullmatch(r'-?\d+', a) else v)
            except ValueError:
                stack[-1].append(Sym(a))
        else:
            break
    return stack[0]


def fmt(v):
    if isinstance(v, float):
        s = ('%.4f' % v).rstrip('0').rstrip('.')
        return s if s not in ('', '-0') else '0'
    return str(v)


def dump(node, indent=0):
    """Serialize a nested list back to KiCad-style indented text."""
    pad = '\t' * indent
    if not isinstance(node, list):
        if isinstance(node, Sym):
            return node
        if isinstance(node, str):
            return '"%s"' % node.replace('"', '\\"')
        return fmt(node)
    if not node:
        return '()'
    # one line if it contains no sublists
    if all(not isinstance(x, list) for x in node):
        return '(' + ' '.join(dump(x) for x in node) + ')'
    head = []
    i = 0
    while i < len(node) and not isinstance(node[i], list):
        head.append(dump(node[i]))
        i += 1
    lines = [pad + '(' + ' '.join(head)]
    for x in node[i:]:
        if isinstance(x, list):
            lines.append(dump(x, indent + 1))
        else:
            lines.append('\t' * (indent + 1) + dump(x))
    lines.append(pad + ')')
    return '\n'.join(lines)


def find(node, key):
    for x in node:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None


def findall(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]


# ---------------------------------------------------------------- library data


class Lib:
    """Symbol definitions harvested from existing .kicad_sch lib_symbols blocks."""

    def __init__(self):
        self.symbols = {}   # lib_id -> sexpr node

    def load_sheet(self, path):
        doc = parse(Path(path).read_text())[0]
        for s in findall(find(doc, 'lib_symbols'), 'symbol'):
            self.symbols.setdefault(s[1], s)

    def load_kicad_sym(self, path, name, lib_id):
        """Take one symbol from a .kicad_sym library file (fixes lib mismatch)."""
        doc = parse(Path(path).read_text())[0]
        for s in findall(doc, 'symbol'):
            if s[1] == name:
                s = [x for x in s]
                s[1] = lib_id
                # sub-unit symbols keep their short names ("BSS123_0_1")
                self.symbols[lib_id] = s
                return
        raise KeyError(name)

    def units(self, lib_id):
        s = self.symbols[lib_id]
        return findall(s, 'symbol')

    def pins(self, lib_id, unit=1):
        """Pins of a symbol for the given unit (unit 0 = common), in lib coords."""
        out = []
        for sub in self.units(lib_id):
            m = re.match(r'.*_(\d+)_(\d+)$', sub[1])
            u = int(m.group(1))
            if u not in (0, unit):
                continue
            for p in findall(sub, 'pin'):
                at = find(p, 'at')
                out.append(dict(
                    number=str(find(p, 'number')[1]),
                    name=str(find(p, 'name')[1]),
                    x=float(at[1]), y=float(at[2]), angle=float(at[3]),
                    length=float(find(p, 'length')[1]),
                    etype=str(p[1]),
                ))
        return out

    def bbox(self, lib_id, unit=1):
        """Graphic bounding box (lib coords, y up) of body + pins."""
        xs, ys = [], []
        for sub in self.units(lib_id):
            m = re.match(r'.*_(\d+)_(\d+)$', sub[1])
            if int(m.group(1)) not in (0, unit):
                continue
            for item in sub:
                if not isinstance(item, list):
                    continue
                for k in ('start', 'end', 'center', 'at', 'xy', 'mid'):
                    for n in _walk(item, k):
                        xs.append(float(n[1]))
                        ys.append(float(n[2]))
                if item[0] == 'circle':
                    r = float(find(item, 'radius')[1])
                    c = find(item, 'center')
                    xs += [float(c[1]) - r, float(c[1]) + r]
                    ys += [float(c[2]) - r, float(c[2]) + r]
        if not xs:
            return (-1.27, -1.27, 1.27, 1.27)
        return (min(xs), min(ys), max(xs), max(ys))


def _walk(node, key):
    if isinstance(node, list):
        if node and node[0] == key:
            yield node
        for x in node:
            yield from _walk(x, key)


def harvest_instances(path):
    """Component instances of a sheet: ref -> dict(lib_id, unit, value, footprint, props)."""
    doc = parse(Path(path).read_text())[0]
    out = {}
    for s in findall(doc, 'symbol'):
        lib_id = find(s, 'lib_id')[1]
        props = {}
        for p in findall(s, 'property'):
            props[p[1]] = p[2]
        ref = props.get('Reference', '')
        unit = int(find(s, 'unit')[1])
        if ref.startswith('#'):
            continue
        d = out.setdefault(ref, dict(lib_id=lib_id, units={}, value=props.get('Value', ''),
                                     footprint=props.get('Footprint', ''),
                                     datasheet=props.get('Datasheet', ''),
                                     description=props.get('Description', ''),
                                     props={k: v for k, v in props.items()
                                            if k not in ('Reference', 'Value', 'Footprint',
                                                         'Datasheet', 'Description')}))
        d['units'][unit] = True
    return out


def sheet_uuid(path):
    doc = parse(Path(path).read_text())[0]
    return find(doc, 'uuid')[1]


# ---------------------------------------------------------------- geometry


def rot_vec(px, py, rot, mirror=None):
    """Lib-coordinate offset (y up) -> sheet offset (y down) for a symbol rotation."""
    vx, vy = px, -py
    if mirror == 'y':
        vx = -vx
    elif mirror == 'x':
        vy = -vy
    if rot == 0:
        return vx, vy
    # KiCad: (at x y 90) turns the symbol counter-clockwise on screen
    if rot == 90:
        return vy, -vx
    if rot == 180:
        return -vx, -vy
    if rot == 270:
        return -vy, vx
    raise ValueError(rot)


def snap(v):
    return round(round(v / 1.27) * 1.27, 2)


# ---------------------------------------------------------------- sheet builder


class Placed:
    def __init__(self, ref, lib_id, unit, x, y, rot, inst, pins, extra, mirror=None):
        self.ref, self.lib_id, self.unit = ref, lib_id, unit
        self.x, self.y, self.rot, self.mirror = x, y, rot, mirror
        self.inst = inst
        self.pins = pins           # number -> (x, y, angle_on_sheet, name, etype)
        self.extra = extra


class Sheet:
    FONT = 1.27

    def __init__(self, lib, instances, title, file_uuid, inst_path, project, paper='A3',
                 pwr_start=1):
        self.lib = lib
        self.instances = instances
        self.title = title
        self.uuid = file_uuid
        self.inst_path = inst_path
        self.project = project
        self.paper = paper
        self.placed = {}          # (ref, unit) -> Placed
        self.power = []           # (name, x, y, rot, ref)
        self.wires = []           # [(x1,y1),(x2,y2)] segments
        self.labels = []          # (kind, text, x, y, rot, shape, justify)
        self.ncs = []             # (x, y)
        self.texts = []           # (text, x, y, size)
        self.pwr_n = pwr_start
        self.used_pins = set()
        self.ox, self.oy = 0.0, 0.0   # layout offset applied to every coordinate

    # -- placement -------------------------------------------------------
    def place(self, ref, x, y, rot=0, unit=1, ref_at=None, val_at=None, hide_value=False,
              mirror=None):
        inst = self.instances[ref]
        lib_id = inst['lib_id']
        x, y = snap(x + self.ox), snap(y + self.oy)
        pins = {}
        for p in self.lib.pins(lib_id, unit):
            dx, dy = rot_vec(p['x'], p['y'], rot, mirror)
            ang = (p['angle'] + rot) % 360
            if mirror == 'y' and ang in (0, 180):
                ang = 180 - ang
            if mirror == 'x' and ang in (90, 270):
                ang = 360 - ang
            pins[p['number']] = (round(x + dx, 2), round(y + dy, 2), ang, p['name'], p['etype'])
        if ref_at:
            ref_at = (ref_at[0] + self.ox, ref_at[1] + self.oy)
        if val_at:
            val_at = (val_at[0] + self.ox, val_at[1] + self.oy)
        pl = Placed(ref, lib_id, unit, x, y, rot, inst, pins,
                    dict(ref_at=ref_at, val_at=val_at, hide_value=hide_value), mirror)
        self.placed[(ref, unit)] = pl
        return pl

    def pin(self, spec, unit=None):
        """'R301.1' -> (x, y) on the sheet."""
        ref, num = spec.split('.')
        if unit is None:
            cands = [k for k in self.placed if k[0] == ref]
            for k in cands:
                if num in self.placed[k].pins:
                    unit = k[1]
                    break
            if unit is None:
                raise KeyError(spec)
        pl = self.placed[(ref, unit)]
        self.used_pins.add((ref, num))
        return pl.pins[num][:2]

    def pwr(self, name, x, y, rot=0):
        ref = '#PWR%03d' % self.pwr_n
        self.pwr_n += 1
        x, y = snap(x + self.ox), snap(y + self.oy)
        self.power.append((name, x, y, rot, ref))
        return (x, y)

    # -- wiring ----------------------------------------------------------
    def _raw(self, p):
        """Point already in sheet coordinates (or a pin spec)."""
        if isinstance(p, str):
            return self.pin(p)
        return (round(p[0], 2), round(p[1], 2))

    def _pt(self, p):
        if isinstance(p, str):
            return self.pin(p)
        return (round(p[0] + self.ox, 2), round(p[1] + self.oy, 2))

    def seg(self, a, b):
        a, b = self._raw(a), self._raw(b)
        if a == b:
            return
        if a[0] != b[0] and a[1] != b[1]:
            raise ValueError('diagonal wire %s -> %s' % (a, b))
        self.wires.append((a, b))

    def w(self, *pts, via=None):
        """Polyline through points. Consecutive points that are not aligned are
        joined with an L: horizontal first, or vertical first if via='v'."""
        pts = [self._pt(p) for p in pts]
        for a, b in zip(pts, pts[1:]):
            if a[0] == b[0] or a[1] == b[1]:
                self.seg(a, b)
            elif via == 'v':
                self.seg(a, (a[0], b[1]))
                self.seg((a[0], b[1]), b)
            else:
                self.seg(a, (b[0], a[1]))
                self.seg((b[0], a[1]), b)

    def wa(self, *pts, via=None):
        """Like w() but points are absolute sheet coordinates (no offset)."""
        pts = [self._raw(p) for p in pts]
        for a, b in zip(pts, pts[1:]):
            if a[0] == b[0] or a[1] == b[1]:
                self.seg(a, b)
            elif via == 'v':
                self.seg(a, (a[0], b[1]))
                self.seg((a[0], b[1]), b)
            else:
                self.seg(a, (b[0], a[1]))
                self.seg((b[0], a[1]), b)

    def wz(self, a, b, mx=None, my=None):
        """Z route: a -> b with the middle leg at x=mx (horizontal ends) or y=my."""
        a, b = self._pt(a), self._pt(b)
        if mx is not None:
            mx = round(mx + self.ox, 2)
            self.seg(a, (mx - self.ox, a[1] - self.oy))
            self.seg((mx - self.ox, a[1] - self.oy), (mx - self.ox, b[1] - self.oy))
            self.seg((mx - self.ox, b[1] - self.oy), b)
        else:
            my = round(my + self.oy, 2)
            self.seg(a, (a[0] - self.ox, my - self.oy))
            self.seg((a[0] - self.ox, my - self.oy), (b[0] - self.ox, my - self.oy))
            self.seg((b[0] - self.ox, my - self.oy), b)

    def stub(self, spec, length=2.54):
        """Wire from a pin outward along its direction; returns the far end."""
        ref, num = spec.split('.')
        for k, pl in self.placed.items():
            if k[0] == ref and num in pl.pins:
                x, y, ang, _, _ = pl.pins[num]
                break
        else:
            raise KeyError(spec)
        # pin angle points from the connection point toward the body
        dx, dy = {0: (-1, 0), 90: (0, 1), 180: (1, 0), 270: (0, -1)}[int(ang) % 360]
        end = (round(x + dx * length, 2), round(y + dy * length, 2))
        self.seg((x, y), end)
        self.used_pins.add((ref, num))
        return end

    def glabel(self, text, at, rot=0, shape='bidirectional'):
        x, y = self._pt(at)
        self.labels.append(('global', text, x, y, rot, shape))

    def label(self, text, at, rot=0):
        x, y = self._pt(at)
        self.labels.append(('local', text, x, y, rot, None))

    def nc(self, spec):
        x, y = self.pin(spec)
        self.ncs.append((x, y))

    def text(self, s, x, y, size=1.5):
        self.texts.append((s, x + self.ox, y + self.oy, size))

    # -- checks ------------------------------------------------------------
    def junctions(self):
        pts = {}

        def add(p, n=1):
            pts[p] = pts.get(p, 0) + n
        for a, b in self.wires:
            add(a)
            add(b)
        for pl in self.placed.values():
            for num, (x, y, _, _, et) in pl.pins.items():
                add((x, y))
        for _, x, y, _, _ in self.power:
            add((x, y))
        out = []
        for p, n in pts.items():
            through = 0
            for a, b in self.wires:
                if p != a and p != b and _on_seg(p, a, b):
                    through += 2
            if n + through >= 3:
                out.append(p)
        return out

    def unconnected_pins(self):
        ends = set()
        for a, b in self.wires:
            ends.add(a)
            ends.add(b)
        ends.update((x, y) for _, x, y, _, _ in self.power)
        ncs = set(self.ncs)
        lab = set((x, y) for _, _, x, y, _, _ in self.labels)
        out = []
        for pl in self.placed.values():
            for num, (x, y, _, name, et) in pl.pins.items():
                p = (x, y)
                if p in ends or p in ncs or p in lab:
                    continue
                if any(_on_seg(p, a, b) for a, b in self.wires):
                    continue
                out.append('%s.%s(%s)' % (pl.ref, num, name))
        return out

    def unplaced(self):
        out = []
        for ref, inst in self.instances.items():
            for u in inst['units']:
                if (ref, u) not in self.placed:
                    out.append('%s/%d' % (ref, u))
        return out

    def translate(self, dx, dy):
        """Shift the whole drawing (call once, before render)."""
        def mv(x, y):
            return (round(x + dx, 2), round(y + dy, 2))
        for pl in self.placed.values():
            pl.x, pl.y = mv(pl.x, pl.y)
            pl.pins = {k: mv(v[0], v[1]) + v[2:] for k, v in pl.pins.items()}
            for key in ('ref_at', 'val_at'):
                if pl.extra[key]:
                    pl.extra[key] = mv(*pl.extra[key])
        self.power = [(n, *mv(x, y), r, ref) for n, x, y, r, ref in self.power]
        self.wires = [(mv(*a), mv(*b)) for a, b in self.wires]
        self.labels = [(k, t, *mv(x, y), r, sh) for k, t, x, y, r, sh in self.labels]
        self.ncs = [mv(x, y) for x, y in self.ncs]
        self.texts = [(t, *mv(x, y), sz) for t, x, y, sz in self.texts]

    # -- output ------------------------------------------------------------
    def render(self):
        L = []
        L.append('(kicad_sch')
        L.append('\t(version 20260306)')
        L.append('\t(generator "eeschema")')
        L.append('\t(generator_version "10.0")')
        L.append('\t(uuid "%s")' % self.uuid)
        L.append('\t(paper "%s")' % self.paper)
        L.append('\t(title_block\n\t\t(title "%s")\n\t)' % self.title)
        # lib symbols
        used = set(pl.lib_id for pl in self.placed.values())
        used.update('power:' + n for n, *_ in self.power)
        L.append('\t(lib_symbols')
        for lib_id in sorted(used):
            L.append(dump(self.lib.symbols[lib_id], 2))
        L.append('\t)')
        for p in self.junctions():
            L.append('\t(junction\n\t\t(at %s %s)\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)\n\t\t(uuid "%s")\n\t)'
                     % (fmt(p[0]), fmt(p[1]), uuid.uuid4()))
        for x, y in self.ncs:
            L.append('\t(no_connect\n\t\t(at %s %s)\n\t\t(uuid "%s")\n\t)' % (fmt(x), fmt(y), uuid.uuid4()))
        for a, b in self.wires:
            L.append('\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "%s")\n\t)'
                     % (fmt(a[0]), fmt(a[1]), fmt(b[0]), fmt(b[1]), uuid.uuid4()))
        for s, x, y, size in self.texts:
            L.append('\t(text "%s"\n\t\t(exclude_from_sim no)\n\t\t(at %s %s 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size %s %s)\n\t\t\t)\n\t\t\t(justify left top)\n\t\t)\n\t\t(uuid "%s")\n\t)'
                     % (s.replace('"', '\\"'), fmt(x), fmt(y), fmt(size), fmt(size), uuid.uuid4()))
        for kind, text, x, y, rot, shape in self.labels:
            just = {0: 'left', 90: 'left', 180: 'right', 270: 'right'}[rot]
            if kind == 'local':
                L.append('\t(label "%s"\n\t\t(at %s %s %d)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify %s bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)'
                         % (text, fmt(x), fmt(y), rot, just, uuid.uuid4()))
            else:
                L.append('\t(global_label "%s"\n\t\t(shape %s)\n\t\t(at %s %s %d)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify %s)\n\t\t)\n\t\t(uuid "%s")\n\t\t(property "Intersheetrefs" "${INTERSHEET_REFS}"\n\t\t\t(at %s %s 0)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)'
                         % (text, shape, fmt(x), fmt(y), rot, just, uuid.uuid4(), fmt(x), fmt(y)))
        for pl in self.placed.values():
            L.append(self._symbol(pl))
        for name, x, y, rot, ref in self.power:
            L.append(self._power(name, x, y, rot, ref))
        L.append('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)')
        L.append(')')
        return '\n'.join(L) + '\n'

    def _prop(self, name, value, x, y, hide=False, rot=0, justify=None, size=1.27):
        j = '\n\t\t\t\t(justify %s)' % justify if justify else ''
        return ('\t\t(property "%s" "%s"\n\t\t\t(at %s %s %d)\n%s\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size %s %s)\n\t\t\t\t)%s\n\t\t\t)\n\t\t)'
                % (name, value.replace('"', '\\"'), fmt(x), fmt(y), rot,
                   '\t\t\t(hide yes)\n' if hide else '', fmt(size), fmt(size), j))

    def _text_pos(self, pl):
        """Reference/Value positions: right of vertical passives, above/below ICs."""
        x0, y0, x1, y1 = self.lib.bbox(pl.lib_id, pl.unit)
        corners = [rot_vec(px, py, pl.rot, pl.mirror) for px in (x0, x1) for py in (y0, y1)]
        bx0 = pl.x + min(c[0] for c in corners)
        bx1 = pl.x + max(c[0] for c in corners)
        by0 = pl.y + min(c[1] for c in corners)
        by1 = pl.y + max(c[1] for c in corners)
        w, h = bx1 - bx0, by1 - by0
        if w > 12 or h > 12:      # IC / connector: ref top-left, value bottom-left
            return ((bx0, by0 - 1.5, 'left'), (bx0, by1 + 1.5, 'left'))
        if h >= w:                # vertical passive: stack to the right
            return ((bx1 + 0.8, pl.y - 1.4, 'left'), (bx1 + 0.8, pl.y + 1.4, 'left'))
        return ((pl.x, by0 - 1.4, None), (pl.x, by1 + 1.4, None))   # horizontal passive

    def _symbol(self, pl):
        inst = pl.inst
        (rx, ry, rj), (vx, vy, vj) = self._text_pos(pl)
        if pl.extra['ref_at']:
            rx, ry = pl.extra['ref_at']
            rj = None
        if pl.extra['val_at']:
            vx, vy = pl.extra['val_at']
            vj = None
        L = ['\t(symbol', '\t\t(lib_id "%s")' % pl.lib_id,
             '\t\t(at %s %s %d)' % (fmt(pl.x), fmt(pl.y), pl.rot)]
        if pl.mirror:
            L.append('\t\t(mirror %s)' % pl.mirror)
        L += ['\t\t(unit %d)' % pl.unit, '\t\t(body_style 1)',
             '\t\t(exclude_from_sim no)', '\t\t(in_bom yes)', '\t\t(on_board yes)',
             '\t\t(in_pos_files yes)', '\t\t(dnp no)', '\t\t(uuid "%s")' % uuid.uuid4()]
        # field angle adds to the symbol's: 90/270 need the complement; at 180 KiCad
        # keeps the text upright but mirrors the justification
        frot = {0: 0, 90: 270, 180: 0, 270: 90}[pl.rot]
        if pl.rot == 180:
            flip = {'left': 'right', 'right': 'left', None: None}
            rj, vj = flip[rj], flip[vj]
        L.append(self._prop('Reference', pl.ref, rx, ry, justify=rj, rot=frot))
        L.append(self._prop('Value', inst['value'], vx, vy, hide=pl.extra['hide_value'], justify=vj, rot=frot))
        L.append(self._prop('Footprint', inst['footprint'], pl.x, pl.y, hide=True))
        L.append(self._prop('Datasheet', inst['datasheet'], pl.x, pl.y, hide=True))
        L.append(self._prop('Description', inst['description'], pl.x, pl.y, hide=True))
        for k, v in inst['props'].items():
            L.append(self._prop(k, v, pl.x, pl.y, hide=True))
        for num in pl.pins:
            L.append('\t\t(pin "%s"\n\t\t\t(uuid "%s")\n\t\t)' % (num, uuid.uuid4()))
        L.append('\t\t(instances\n\t\t\t(project "%s"\n\t\t\t\t(path "%s"\n\t\t\t\t\t(reference "%s")\n\t\t\t\t\t(unit %d)\n\t\t\t\t)\n\t\t\t)\n\t\t)'
                 % (self.project, self.inst_path, pl.ref, pl.unit))
        L.append('\t)')
        return '\n'.join(L)

    def _power(self, name, x, y, rot, ref):
        lib_id = 'power:' + name
        below = name in ('GND',)
        if rot == 0:
            vx, vy = x, (y + 5.08 if below else y - 5.08)
        elif rot == 180:
            vx, vy = x, (y - 5.08 if below else y + 5.08)
        elif rot == 90:      # graphic to the right of the pin
            vx, vy = (x + 5.08 if below else x - 5.08), y
        else:                # 270: graphic to the left
            vx, vy = (x - 5.08 if below else x + 5.08), y
        L = ['\t(symbol', '\t\t(lib_id "%s")' % lib_id,
             '\t\t(at %s %s %d)' % (fmt(x), fmt(y), rot),
             '\t\t(unit 1)', '\t\t(body_style 1)', '\t\t(exclude_from_sim no)',
             '\t\t(in_bom yes)', '\t\t(on_board yes)', '\t\t(in_pos_files yes)', '\t\t(dnp no)',
             '\t\t(uuid "%s")' % uuid.uuid4()]
        frot = {0: 0, 90: 270, 180: 0, 270: 90}[rot]
        L.append(self._prop('Reference', ref, x, y + (6.35 if below else -6.35), hide=True))
        L.append(self._prop('Value', name, vx, vy, hide=(name == 'PWR_FLAG'), rot=frot))
        L.append(self._prop('Footprint', '', x, y, hide=True))
        L.append(self._prop('Datasheet', '', x, y, hide=True))
        L.append(self._prop('Description', '', x, y, hide=True))
        L.append('\t\t(pin "1"\n\t\t\t(uuid "%s")\n\t\t)' % uuid.uuid4())
        L.append('\t\t(instances\n\t\t\t(project "%s"\n\t\t\t\t(path "%s"\n\t\t\t\t\t(reference "%s")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)'
                 % (self.project, self.inst_path, ref))
        L.append('\t)')
        return '\n'.join(L)


def _on_seg(p, a, b, eps=0.01):
    if abs(a[0] - b[0]) < eps:      # vertical
        return abs(p[0] - a[0]) < eps and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps
    if abs(a[1] - b[1]) < eps:      # horizontal
        return abs(p[1] - a[1]) < eps and min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
    return False
