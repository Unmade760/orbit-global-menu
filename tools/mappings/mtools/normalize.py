"""normalize: accelerators in any supported dialect to the mapping grammar."""

import argparse
import sys

from . import accel, gjs
from .cli import emit

DIALECT_CHOICES = ("auto",) + accel.DIALECTS


def normalize_one(text, dialect):
    results = accel.normalize_all(text, dialect)
    first = results[0]
    out = {"input": text, "from": first.dialect, "accel": first.accel}
    if len(results) > 1:
        out["alternatives"] = [r.accel for r in results]
    errors = [r.error for r in results if r.error]
    if errors:
        out["error"] = "; ".join(errors)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="normalize",
        description="Normalize accelerators to the Global Menu mapping grammar "
                    "(docs/shortcut-mappings.md). One input prints one JSON object "
                    "{input, from, accel, alternatives?, error?, extension_parses?}; several print "
                    "{results: [...]}. Exits 1 if any input does not normalize, or with --gjs if the "
                    "extension's own parser rejects a result.")
    parser.add_argument("accel", nargs="+", help="accelerator text, e.g. 'Ctrl+Shift+S' or '<Primary>s'")
    parser.add_argument("--from", dest="dialect", default="auto", choices=DIALECT_CHOICES,
                        help="source dialect (default: auto-detect per input)")
    parser.add_argument("--gjs", action="store_true",
                        help="also run each result through keySynth.js parseAccelerator() under gjs")
    args = parser.parse_args(argv)

    results = [normalize_one(text, args.dialect) for text in args.accel]
    ok = all("error" not in r for r in results)
    if args.gjs:
        accels = [r["accel"] for r in results if r["accel"]]
        parsed = gjs.parse_accels(accels)["parsed"] if accels else []
        verdict = dict(zip(accels, (p is not None for p in parsed)))
        for r in results:
            if r["accel"]:
                r["extension_parses"] = verdict[r["accel"]]
                ok = ok and r["extension_parses"]
    emit(results[0] if len(results) == 1 else {"results": results})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
