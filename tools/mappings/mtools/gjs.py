"""Run the extension's accelerator parser (accelerator.js) under gjs."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

HARNESS = Path(__file__).resolve().parent / "gjs" / "parse_accels.js"
KEYSYNTH_REL = Path("global-menu@unmade.space") / "accelerator.js"
FALLBACK = Path("/home/ravi/fildem") / KEYSYNTH_REL


def find_keysynth():
    """$GLOBAL_MENU_KEYSYNTH, else the nearest checkout above this tool, else ~/fildem."""
    env = os.environ.get("GLOBAL_MENU_KEYSYNTH")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / KEYSYNTH_REL).exists():
            return parent / KEYSYNTH_REL
    return FALLBACK


def parse_accels(accels, names=(), keysynth=None):
    keysynth = Path(keysynth or find_keysynth())
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"accels": list(accels), "names": list(names)}, fh)
        path = fh.name
    try:
        proc = subprocess.run(["gjs", "-m", str(HARNESS), str(keysynth), path],
                              capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(path)
    if proc.returncode != 0:
        raise RuntimeError(f"gjs failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)
