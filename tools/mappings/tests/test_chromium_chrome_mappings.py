import json
from pathlib import Path

APPS = Path(__file__).resolve().parents[3] / "global-menu@unmade.space" / "shortcuts" / "apps"


def items(app):
    mapping = json.loads((APPS / f"{app}.json").read_text())
    out = {}

    def walk(entries, path):
        for entry in entries:
            if "items" in entry:
                walk(entry["items"], path + [entry["label"]])
            elif "shortcut" in entry:
                out[tuple(path + [entry["label"]])] = entry["shortcut"]

    for menu in mapping["menus"]:
        walk(menu["items"], [menu["label"]])
    return out


def test_no_alternative_labels():
    for app in ("chrome", "chromium"):
        assert not [p for p in items(app) if "Alternative" in p[-1]]


def test_chromium_is_chrome_without_the_branded_feedback_item():
    chrome, chromium = items("chrome"), items("chromium")
    branded = {path: sc for path, sc in chrome.items() if sc == "<Alt><Shift>i"}
    assert len(branded) == 1
    rebranded = {tuple(p.replace("Chrome", "Chromium") for p in path): sc
                 for path, sc in chrome.items() if path not in branded}
    assert chromium == rebranded


def test_every_chord_is_used_once_per_mapping():
    for app in ("chrome", "chromium"):
        chords = list(items(app).values())
        assert len(chords) == len(set(chords)), app
