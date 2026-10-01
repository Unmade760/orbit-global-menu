"""Lookups into the generated standard shortcut tables (data/standard_keys.json)."""

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "standard_keys.json"


@lru_cache(maxsize=1)
def load():
    return json.loads(DATA.read_text())


def source(name):
    """{"url", "commit", "files"} of one upstream the tables were read from."""
    return load()["sources"][name]


def qt_standard_key(name, scheme="gnome"):
    """QKeySequence::<name> bindings under a keyboard scheme, first = primary.

    Qt apps in a GNOME session use the GNOME scheme (QGnomeTheme). Returns
    None for an unknown key name.
    """
    entry = load()["qt_standard_keys"].get(name)
    if entry is None:
        return None
    return entry[scheme]


def kstandard_shortcut(name):
    """KStandardShortcut::<name> defaults (enum name, e.g. "Save")."""
    entry = load()["kstandard_shortcuts"].get(name)
    return entry["shortcuts"] if entry else None


def kstandard_shortcut_function(name):
    """Enum name behind a KStandardShortcut accessor (openNew -> New), or None."""
    return load()["kstandard_shortcut_functions"].get(name)


def _lower_first(name):
    return name[:1].lower() + name[1:]


def kstandard_action(name):
    """A KStandardAction by function name (save, openNew), enum name (Save)
    or XMLGUI action name (file_save). Returns {action_name, label,
    shortcut, shortcuts, file, line} or None."""
    data = load()
    actions = data["kstandard_actions"]
    ident = None
    if name in data["kstandard_action_functions"]:
        ident = data["kstandard_action_functions"][name]
    elif name in actions:
        ident = name
    else:
        for key, info in actions.items():
            if info["action_name"] == name:
                ident = key
                break
    if ident is None:
        return None
    info = dict(actions[ident])
    info["id"] = ident
    info["shortcuts"] = kstandard_shortcut(info["shortcut"]) or []
    return info


def electron_role(name):
    """Default label and accelerator of an Electron menu role on Linux.

    Role names are case-insensitive in Electron (the table keys are lower
    case). Returns None for an unknown role.
    """
    return load()["electron_roles"].get(name.lower())


def electron_submenu(name):
    """Role list a submenu role (fileMenu, editMenu, viewMenu, windowMenu)
    expands to on Linux; None marks a separator."""
    entry = load()["electron_submenus"].get(name.lower())
    return entry["roles"] if entry else None
