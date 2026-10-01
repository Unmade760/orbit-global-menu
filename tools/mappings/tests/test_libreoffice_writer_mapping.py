import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAPPING = ROOT / "global-menu@unmade.space" / "shortcuts" / "apps" / "libreoffice-writer.json"
SOURCES = ROOT / "tools" / "mapping-sources" / "libreoffice-writer.sources.json"


def shortcuts(entries, path):
    for entry in entries:
        if "items" in entry:
            yield from shortcuts(entry["items"], path + [entry["label"]])
        elif "shortcut" in entry:
            yield tuple(path + [entry["label"]]), entry["shortcut"]


def load():
    mapping = json.loads(MAPPING.read_text())
    found = dict(s for m in mapping["menus"] for s in shortcuts(m["items"], [m["label"]]))
    return mapping, found


def test_menus_follow_writers_menu_bar_order():
    mapping, _ = load()
    labels = [m["label"] for m in mapping["menus"]]
    order = ["File", "Edit", "View", "Insert", "Format", "Styles", "Table", "Tools", "Window", "Help"]
    assert labels == order


def test_labels_are_writers_own():
    _, found = load()
    labels = {path[-1] for path in found}
    wrong = {"Open Document", "Save Document", "Print Document", "Close Document", "Exit LibreOffice",
             "Toggle Sidebar", "Toggle Fullscreen", "Insert Page Break", "Insert Table", "Manage Styles",
             "Spelling / Grammar Check", "Thesaurus"}
    assert not labels & wrong
    assert {"Open…", "Save", "Print…", "Close", "Exit", "Sidebar", "Full Screen", "Page Break"} <= labels
    assert not [p for p in found if "..." in p[-1]]


def test_covers_the_default_chords_of_the_styles_table_and_window_menus():
    _, found = load()
    assert found[("Styles", "Styles")] == "F11"
    assert found[("Table", "Edit Formula")] == "F2"
    assert found[("Window", "Close Window")] == "<Ctrl>W"
    assert len(found) >= 80


def test_flatpak_desktop_id_is_claimed():
    mapping, _ = load()
    assert "org.libreoffice.LibreOffice.writer.desktop" in mapping["identifiers"]


def test_every_shortcut_has_a_source_record():
    _, found = load()
    records = {tuple(r["path"]): r["shortcut"] for r in json.loads(SOURCES.read_text())["items"]}
    assert records == found
