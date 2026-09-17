"""RETIRED 2026-09-17 (ADR 0003): eeschema is the source of truth now and the
sheets in the project root have diverged from tools/ref/. Running this would
overwrite them, so it refuses unless --force-overwrite is given. --pins still
works. Kept as history of how rev 0.1 was drawn.

Regenerate the four child sheets from the layouts in sheets/.

    python3 tools/build.py            # write power/driver/mcu/io .kicad_sch
    python3 tools/build.py --pins     # print symbol pin geometry (layout aid)

Parts, values, footprints and LCSC fields are harvested from the reference
sheets in tools/ref/ (the verified capture); only the drawing is new.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REF = HERE / 'ref'
sys.path.insert(0, str(HERE))

import kisch  # noqa: E402

ROOT_UUID = 'd303ff23-e0bc-456d-81fe-4c8aea3d493e'
SHEETS = {
    # name: (sheet symbol uuid in root, title, power ref start)
    'power': ('eea3b213-e666-47c8-aad0-1a186ad95509', 'Power', 101),
    'driver': ('5a5c39c8-1b78-4397-9a1d-6791b96c5210', 'Driver', 201),
    'mcu': ('4845781e-7088-4051-9c5d-7734bf4421a6', 'MCU', 301),
    'io': ('2f15ba9a-6165-4167-85f8-f67e3d99cc62', 'IO', 401),
}


def load_lib():
    lib = kisch.Lib()
    for name in SHEETS:
        lib.load_sheet(REF / ('%s.kicad_sch' % name))
    # the capture embedded a stale derived BSS123 (ERC lib mismatch); Q203 is
    # drawn with the generic G-S-D NMOS symbol instead, value stays BSS123
    lib.load_kicad_sym('/usr/share/kicad/symbols/Transistor_FET.kicad_sym', 'Q_NMOS_GSD',
                       'Transistor_FET:Q_NMOS_GSD')
    return lib


def make_sheet(lib, name):
    sym_uuid, title, pwr = SHEETS[name]
    ref_path = REF / ('%s.kicad_sch' % name)
    inst = kisch.harvest_instances(ref_path)
    if 'Q203' in inst:
        inst['Q203']['lib_id'] = 'Transistor_FET:Q_NMOS_GSD'
    return kisch.Sheet(lib, inst, title, kisch.sheet_uuid(ref_path),
                       '/%s/%s' % (ROOT_UUID, sym_uuid), 'graver-controller',
                       pwr_start=pwr)


def print_pins(lib):
    seen = set()
    for name in SHEETS:
        inst = kisch.harvest_instances(REF / ('%s.kicad_sch' % name))
        for ref, d in sorted(inst.items()):
            for u in d['units']:
                key = (d['lib_id'], u)
                if key in seen:
                    continue
                seen.add(key)
                print('%s unit %d  bbox %s   e.g. %s' % (d['lib_id'], u,
                      tuple(round(v, 2) for v in lib.bbox(d['lib_id'], u)), ref))
                for p in lib.pins(d['lib_id'], u):
                    print('   %-4s %-12s at (%6.2f,%6.2f) ang %3d  %s' % (
                        p['number'], p['name'], p['x'], p['y'], p['angle'], p['etype']))
    for n in ('GND', '+3V3', '+5V', 'PWR_FLAG'):
        print('power:%s' % n, lib.pins('power:' + n, 1))


def main():
    lib = load_lib()
    if '--pins' in sys.argv:
        print_pins(lib)
        return
    if '--force-overwrite' not in sys.argv:
        sys.exit('build.py is retired (ADR 0003): the .kicad_sch sheets are edited in '
                 'eeschema and this would overwrite them. See tools/README.md.')
    import sheets  # noqa: E402
    problems = 0
    only = [a for a in sys.argv[1:] if not a.startswith('-')]
    for name in SHEETS:
        if only and name not in only:
            continue
        sh = make_sheet(lib, name)
        getattr(sheets, name)(sh)
        bad = sh.unplaced()
        loose = sh.unconnected_pins()
        if bad:
            print('%s: NOT PLACED: %s' % (name, ' '.join(bad)))
            problems += 1
        if loose:
            print('%s: pins without wire/label/nc: %s' % (name, ' '.join(loose)))
            problems += 1
        (ROOT / ('%s.kicad_sch' % name)).write_text(sh.render())
        print('%s: %d symbols, %d wires, %d junctions, %d labels' % (
            name, len(sh.placed) + len(sh.power), len(sh.wires), len(sh.junctions()), len(sh.labels)))
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
