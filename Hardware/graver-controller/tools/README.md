# Schematic generator (retired)

**Retired 2026-09-17 (ADR 0003).** Layout has started, so eeschema is the
source of truth: edit the .kicad_sch sheets in the project root directly. The
sheets have already diverged from `ref/` (J401 is a JST XH header now), so
`build.py` refuses to run without `--force-overwrite`; do not use that unless
you mean to throw the eeschema edits away.

What still gets used:

    tools/verify.sh                   # ERC (must be 0 violations) + PNG renders
    python3 tools/build.py --pins     # symbol pin geometry

`verify.sh` renders into `output/verify/` with kicad-cli + rsvg-convert.

## History: how rev 0.1 was drawn

The four child sheets (power, driver, mcu, io) were generated from Python
layouts so the drawing could be reworked without touching the verified circuit.

- `ref/` - the captured sheets the parts and nets were harvested from
  (values, footprints, LCSC fields). The netlist of record for rev 0.1 only.
- `kisch.py` - s-expression parser, symbol geometry, sheet builder (wires,
  labels, power symbols, junctions, no-connects) and the .kicad_sch writer.
- `sheets/*.py` - one layout per sheet. Coordinates are mm on the 1.27 grid;
  wires attach to pins with `REF.PIN` specs so pin positions come from the
  symbol library.
- `build.py` - regenerated the sheets in the project root.
