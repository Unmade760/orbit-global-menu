"""A small XML tree with a line number on every element (expat, stdlib)."""

import re
import xml.parsers.expat


class Element:
    __slots__ = ("tag", "attrs", "line", "children", "parent", "text_parts")

    def __init__(self, tag, attrs, line, parent):
        self.tag = tag
        self.attrs = attrs
        self.line = line
        self.children = []
        self.parent = parent
        self.text_parts = []

    @property
    def text(self):
        """Direct character data of this element, joined and stripped."""
        return "".join(self.text_parts).strip()

    def all_text(self):
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(child.all_text())
        return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()

    def iter(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            yield from child.iter(tag)

    def find_children(self, tag):
        return [c for c in self.children if c.tag == tag]

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def get(self, name, default=None):
        return self.attrs.get(name, default)


def parse(text):
    """Parse XML text into an Element tree, or return None if it is not XML.

    Undefined entities (DocBook's &Ctrl;) are kept as their literal text.
    """
    root = Element("#document", {}, 1, None)
    stack = [root]
    parser = xml.parsers.expat.ParserCreate()
    parser.UseForeignDTD(True)
    parser.SetParamEntityParsing(xml.parsers.expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def start(tag, attrs):
        el = Element(tag, attrs, parser.CurrentLineNumber, stack[-1])
        stack[-1].children.append(el)
        stack.append(el)

    def end(tag):
        stack.pop()

    def chars(data):
        stack[-1].text_parts.append(data)

    def default(data):
        if data.startswith("&") and data.endswith(";"):
            stack[-1].text_parts.append(data)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.DefaultHandler = default
    try:
        parser.Parse(text, True)
    except xml.parsers.expat.ExpatError:
        return None
    return root
