"""Small helpers shared by the command line entry points."""

import json
import sys


def emit(data):
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def fail(message, code=2, **extra):
    """Print {"error": message, ...} on stdout and exit with `code`."""
    emit({"error": message, **extra})
    sys.exit(code)
