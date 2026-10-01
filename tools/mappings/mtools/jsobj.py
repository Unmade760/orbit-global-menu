"""A lenient JavaScript/TypeScript/JSONC reader for object and array literals.

It does not evaluate anything. It tokenizes the file (strings, template
literals, comments and regex literals included), then groups brackets into
nodes: Obj for an object literal, Arr for an array literal, Group for (...)
and Block for any {...} that is not an object literal. Every node and token
keeps its source offsets, so callers can report lines and slice raw text.
"""

import re
import sys

from .srctext import unescape

sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))


class Tok:
    __slots__ = ("type", "value", "start", "end")

    def __init__(self, type_, value, start, end):
        self.type = type_
        self.value = value
        self.start = start
        self.end = end

    def __repr__(self):
        return f"Tok({self.type}, {self.value!r})"


class Node:
    kind = "node"

    def __init__(self, start):
        self.start = start
        self.end = start


class Value:
    """The items (tokens and nodes) of one expression, e.g. a property value."""

    def __init__(self, items):
        self.items = items

    @property
    def start(self):
        return self.items[0].start if self.items else -1

    @property
    def end(self):
        return self.items[-1].end if self.items else -1

    def single(self):
        return self.items[0] if len(self.items) == 1 else None

    def __repr__(self):
        return f"Value({self.items!r})"


class Obj(Node):
    kind = "obj"

    def __init__(self, start):
        super().__init__(start)
        self.props = []  # [(key or None, Value, key token)]

    def get(self, key):
        for k, v, _ in self.props:
            if k == key:
                return v
        return None

    def keys(self):
        return [k for k, _, _ in self.props]

    def key_tok(self, key):
        for k, _, t in self.props:
            if k == key:
                return t
        return None


class Arr(Node):
    kind = "arr"

    def __init__(self, start):
        super().__init__(start)
        self.elements = []  # [Value]


class Group(Node):
    kind = "group"

    def __init__(self, start):
        super().__init__(start)
        self.items = []


class Block(Node):
    kind = "block"

    def __init__(self, start):
        super().__init__(start)
        self.items = []


PUNCT3 = {"===", "!==", "...", "**=", "<<=", ">>=", "&&=", "||=", "??="}
PUNCT2 = {"=>", "==", "!=", "<=", ">=", "&&", "||", "??", "?.", "++", "--", "+=", "-=",
          "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>", "::"}
REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^") | {"return", "typeof", "case", "=>", "&&", "||", "??"}
IDENT = re.compile(r"[A-Za-z_$À-￿][\w$À-￿]*")
NUMBER = re.compile(r"\d[\w.]*|\.\d[\w]*")


def tokenize(text):
    toks = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if ch in "\"'`":
            j = i + 1
            while j < n and text[j] != ch:
                if text[j] == "\\":
                    j += 1
                elif text[j] == "\n" and ch != "`":
                    break
                j += 1
            toks.append(Tok("str", unescape(text[i + 1:j]), i, min(j + 1, n)))
            i = j + 1
            continue
        if ch == "/":
            prev = toks[-1] if toks else None
            if prev is None or (prev.type == "punct" and prev.value in REGEX_PREV) or \
                    (prev.type == "id" and prev.value in REGEX_PREV):
                j, in_class = i + 1, False
                while j < n and text[j] != "\n":
                    c = text[j]
                    if c == "\\":
                        j += 2
                        continue
                    if c == "[":
                        in_class = True
                    elif c == "]":
                        in_class = False
                    elif c == "/" and not in_class:
                        break
                    j += 1
                j += 1
                while j < n and text[j].isalpha():
                    j += 1
                toks.append(Tok("regex", text[i:j], i, j))
                i = j
                continue
        m = IDENT.match(text, i)
        if m:
            toks.append(Tok("id", m.group(0), i, m.end()))
            i = m.end()
            continue
        m = NUMBER.match(text, i)
        if m:
            toks.append(Tok("num", m.group(0), i, m.end()))
            i = m.end()
            continue
        if text[i:i + 3] in PUNCT3:
            toks.append(Tok("punct", text[i:i + 3], i, i + 3))
            i += 3
            continue
        if text[i:i + 2] in PUNCT2:
            toks.append(Tok("punct", text[i:i + 2], i, i + 2))
            i += 2
            continue
        toks.append(Tok("punct", ch, i, i + 1))
        i += 1
    return toks


def _is(tok, value):
    return tok is not None and tok.type == "punct" and tok.value == value


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.n = len(toks)

    def tok(self, i):
        return self.toks[i] if i < self.n else None

    def parse_items(self, i, closer):
        """Items until `closer` (a punct value) at this level; returns (items, index of closer)."""
        items = []
        while i < self.n:
            t = self.toks[i]
            if t.type == "punct":
                if t.value == closer:
                    return items, i
                if t.value in (")", "]", "}"):
                    return items, i  # unbalanced; stop here
                if t.value in ("{", "[", "("):
                    node, i = self.parse_bracket(i)
                    items.append(node)
                    continue
            items.append(t)
            i += 1
        return items, i

    def parse_bracket(self, i):
        t = self.toks[i]
        if t.value == "[":
            return self.parse_array(i)
        if t.value == "(":
            node = Group(t.start)
            node.items, j = self.parse_items(i + 1, ")")
            node.end = self.toks[j].end if j < self.n else t.end
            return node, j + 1
        obj = self.try_object(i)
        if obj is not None:
            return obj
        node = Block(t.start)
        node.items, j = self.parse_items(i + 1, "}")
        node.end = self.toks[j].end if j < self.n else t.end
        return node, j + 1

    def parse_array(self, i):
        node = Arr(self.toks[i].start)
        j = i + 1
        while j < self.n:
            if _is(self.tok(j), "]"):
                node.end = self.toks[j].end
                return node, j + 1
            items, j = self.parse_value(j, (",", "]"))
            node.elements.append(Value(items))
            if _is(self.tok(j), ","):
                j += 1
            elif not _is(self.tok(j), "]"):
                break
        node.end = self.toks[min(j, self.n - 1)].end if self.n else node.start
        return node, j + 1

    def parse_value(self, i, stops):
        items = []
        while i < self.n:
            t = self.toks[i]
            if t.type == "punct":
                if t.value in stops:
                    return items, i
                if t.value in (")", "]", "}"):
                    return items, i
                if t.value in ("{", "[", "("):
                    node, i = self.parse_bracket(i)
                    items.append(node)
                    continue
            items.append(t)
            i += 1
        return items, i

    def try_object(self, i):
        obj = Obj(self.toks[i].start)
        j = i + 1
        while j < self.n:
            t = self.toks[j]
            if _is(t, "}"):
                obj.end = t.end
                return obj, j + 1
            if _is(t, "..."):
                items, j = self.parse_value(j + 1, (",", "}"))
                obj.props.append(("...", Value(items), t))
            else:
                if t.type in ("id", "str", "num"):
                    key, key_tok = t.value, t
                    j += 1
                elif _is(t, "["):
                    end = self._skip_bracket(j)
                    if end is None:
                        return None
                    key, key_tok = None, t
                    j = end
                else:
                    return None
                nt = self.tok(j)
                if nt is not None and nt.type == "id" and key in ("get", "set", "async", "static"):
                    key, key_tok = nt.value, nt
                    j += 1
                    nt = self.tok(j)
                if _is(nt, ":"):
                    items, j = self.parse_value(j + 1, (",", "}"))
                    obj.props.append((key, Value(items), key_tok))
                elif _is(nt, ",") or _is(nt, "}"):
                    obj.props.append((key, Value([key_tok]), key_tok))
                elif _is(nt, "("):
                    group, j = self.parse_bracket(j)
                    if not _is(self.tok(j), "{"):
                        return None
                    body, j = self.parse_bracket(j)
                    obj.props.append((key, Value([group, body]), key_tok))
                else:
                    return None
            t = self.tok(j)
            if _is(t, ","):
                j += 1
                continue
            if _is(t, "}"):
                obj.end = t.end
                return obj, j + 1
            return None
        return None

    def _skip_bracket(self, i):
        depth = 0
        for j in range(i, self.n):
            t = self.toks[j]
            if t.type == "punct" and t.value in "([{":
                depth += 1
            elif t.type == "punct" and t.value in ")]}":
                depth -= 1
                if depth == 0:
                    return j + 1
        return None


def parse(text):
    """Top-level items of a JS/TS/JSON file."""
    toks = tokenize(text)
    parser = Parser(toks)
    items, _ = parser.parse_items(0, "\0")
    return items


def children(node):
    if isinstance(node, Obj):
        for _, value, _ in node.props:
            yield from value.items
    elif isinstance(node, Arr):
        for value in node.elements:
            yield from value.items
    elif isinstance(node, (Group, Block)):
        yield from node.items


def walk(items):
    """Every node under `items`, depth first."""
    stack = list(reversed(items))
    while stack:
        item = stack.pop()
        if isinstance(item, Node):
            yield item
            stack.extend(reversed(list(children(item))))


def strings(value):
    """String tokens directly in a value, and inside call groups in it."""
    out = []
    for item in value.items:
        if isinstance(item, Tok) and item.type == "str":
            out.append(item)
        elif isinstance(item, Group):
            out.extend(strings(Value(item.items)))
    return out
