# Schematic generator

The four child sheets (power, driver, mcu, io) are generated from Python
layouts so the drawing can be reworked without touching the verified circuit.

- `ref/` - the captured sheets the parts and nets are harvested from
  (values, footprints, LCSC fields). Treat as the netlist of record.
- `kisch.py` - s-expression parser, symbol geometry, sheet builder (wires,
  labels, power symbols, junctions, no-connects) and the .kicad_sch writer.
- `sheets/*.py` - one layout per sheet. Coordinates are mm on the 1.27 grid;
  wires attach to pins with `REF.PIN` specs so pin positions come from the
  symbol library.
- `build.py` - regenerates the sheets in the project root.
- `verify.sh` - exports the XML netlist of the project and of `ref/`, compares
  components (ref, value, footprint, LCSC) and every net by pin set, runs ERC
  and renders PNGs into `output/verify/`.

    python3 tools/build.py            # all sheets, or: build.py mcu io
    tools/verify.sh                   # must print NETLIST OK and 0 violations
    python3 tools/build.py --pins     # symbol pin geometry, for layout work

Editing in eeschema is fine, but the generator overwrites the sheets: change
`sheets/*.py` for drawing changes, and update `ref/` (or the harvest) when
the circuit itself changes.
