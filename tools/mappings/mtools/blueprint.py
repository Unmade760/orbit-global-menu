"""A reader for GTK Blueprint (.blp) files: objects, properties, menus.

Blueprint syntax: https://gnome.pages.gitlab.gnome.org/blueprint-compiler/
Statements are `Type [id] { ... }` objects, `name: value;` properties,
`menu id { section { item { label: ...; } item (_("Label"), "app.action") } }`
menus, and odds and ends (`using Gtk 4.0;`, `[child-type]`, `styles [...]`,
signal handlers `clicked => $cb();`) that are skipped.
"""

import re

from .srctext import LineIndex

TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<arrow>=>)
  | (?P<ident>[$A-Za-z_][\w.\-$]*)
  | (?P<num>-?\d[\d.]*)
  | (?P<punct>[{}()\[\];:,=|])
  | (?P<other>.)
""", re.X | re.S)


class Tok:
    __slots__ = ("type", "value", "pos")

    def __init__(self, type_, value, pos):
        self.type = type_
        self.value = value
        self.pos = pos


def tokenize(text):
    out = []
    for m in TOKEN.finditer(text):
        kind = m.lastgroup
        if kind in ("ws", "comment"):
            continue
        value = m.group(0)
        if kind == "str":
            value = re.sub(r"\\(.)", r"\1", value[1:-1])
        out.append(Tok(kind, value, m.start()))
    return out


class Obj:
    def __init__(self, header, pos):
        self.header = header  # list of Tok before "{"
        self.pos = pos
        self.props = {}       # name -> (list of Tok, pos, Obj or None)
        self.children = []    # Obj and ShortItem
        self.parent = None

    @property
    def type(self):
        """Type name, e.g. "Adw.ShortcutsItem", "menu", "section", "item"."""
        words = [t.value for t in self.header if t.type == "ident"]
        if not words:
            return None
        if words[0] == "template" and len(words) > 1:
            return words[-1]
        return words[0]

    @property
    def ident(self):
        words = [t.value for t in self.header if t.type == "ident"]
        return words[1] if len(words) > 1 and words[0] != "template" else None

    def prop_string(self, name):
        """The user-visible string of a property: _("x"), C_("ctx", "x") or "x"."""
        entry = self.props.get(name)
        if not entry:
            return None
        toks = entry[0]
        strings = [t.value for t in toks if t.type == "str"]
        if not strings:
            idents = [t.value for t in toks if t.type == "ident"]
            return idents[0] if idents else None
        if toks and toks[0].type == "ident" and toks[0].value == "C_" and len(strings) > 1:
            return strings[-1]
        return strings[0]

    def prop_pos(self, name):
        entry = self.props.get(name)
        if not entry:
            return self.pos
        toks = entry[0]
        for t in toks:
            if t.type == "str":
                return t.pos
        return entry[1]

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class ShortItem:
    """menu shorthand: item (_("Label"), "app.action", "icon")"""

    def __init__(self, args, pos):
        self.args = args
        self.pos = pos
        self.parent = None
        self.type = "item-short"


class Reader:
    def __init__(self, toks):
        self.toks = toks
        self.n = len(toks)

    def at(self, i, value):
        return i < self.n and self.toks[i].value == value and self.toks[i].type != "str"

    def skip_group(self, i, open_, close):
        depth = 0
        while i < self.n:
            t = self.toks[i]
            if t.type != "str":
                if t.value == open_:
                    depth += 1
                elif t.value == close:
                    depth -= 1
                    if depth == 0:
                        return i + 1
            i += 1
        return i

    def block(self, i, owner):
        """Statements until the matching "}"; returns the index after it."""
        while i < self.n:
            t = self.toks[i]
            if self.at(i, "}"):
                return i + 1
            if self.at(i, ";") or self.at(i, ","):
                i += 1
                continue
            if self.at(i, "["):
                i = self.skip_group(i, "[", "]")
                continue
            if t.type == "ident" and t.value == "item" and self.at(i + 1, "("):
                end = self.skip_group(i + 1, "(", ")")
                args = [x for x in self.toks[i + 2:end - 1] if x.type == "str"]
                item = ShortItem(args, t.pos)
                item.parent = owner
                owner.children.append(item)
                i = end
                continue
            if t.type == "ident" and self.at(i + 1, ":"):
                i = self.property(i, owner)
                continue
            # A header up to "{" (an object) or ";" (anything else)
            j = i
            while j < self.n and not (self.at(j, "{") or self.at(j, ";") or self.at(j, "}")):
                if self.at(j, "("):
                    j = self.skip_group(j, "(", ")")
                elif self.at(j, "["):
                    j = self.skip_group(j, "[", "]")
                else:
                    j += 1
            if self.at(j, "{"):
                obj = Obj(self.toks[i:j], t.pos)
                obj.parent = owner
                owner.children.append(obj)
                i = self.block(j + 1, obj)
            else:
                i = j + 1 if self.at(j, ";") else j
        return i

    def property(self, i, owner):
        name, pos = self.toks[i].value, self.toks[i].pos
        j = i + 2
        value, child = [], None
        while j < self.n and not self.at(j, ";") and not self.at(j, "}"):
            if self.at(j, "{"):
                child = Obj(value[:], self.toks[j].pos)
                child.parent = owner
                owner.children.append(child)
                j = self.block(j + 1, child)
                continue
            if self.at(j, "["):
                end = self.skip_group(j, "[", "]")
                value.extend(self.toks[j:end])
                j = end
                continue
            value.append(self.toks[j])
            j += 1
        owner.props[name] = (value, pos, child)
        return j + 1 if self.at(j, ";") else j


def parse(text):
    """(root Obj, LineIndex)."""
    root = Obj([], 0)
    reader = Reader(tokenize(text))
    i = 0
    while i < reader.n:
        i = reader.block(i, root)
        if i < reader.n and reader.at(i - 1, "}"):
            continue
    return root, LineIndex(text)


def walk(node):
    yield node
    for child in getattr(node, "children", []):
        yield from walk(child)
