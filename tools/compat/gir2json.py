#!/usr/bin/env python3
"""Condense GIR files (dumped from typelibs with g-ir-generate) into one JSON
index for tools/compat/resolve.mjs.

    gir2json.py OUT.json FILE.gir...

The index keeps what the compat check needs to follow types through the
extension's code: each namespace's classes, interfaces, records and unions
with their parent, interfaces, methods (return and parameter types),
static functions, properties, signals and fields; enums and bitfields with
their members as gjs names them; namespace functions and constants.

Type references are qualified ("Meta.Window"). Arrays, GList and GSList
become {"array": <element type>}. Names follow gjs: property "gtk-application-id"
is "gtk_application_id", enum member "keyboard_moving" is "KEYBOARD_MOVING".
"""

import json
import re
import sys
import xml.etree.ElementTree as ET

CORE = '{http://www.gtk.org/introspection/core/1.0}'
GLIB = '{http://www.gtk.org/introspection/glib/1.0}'
C = '{http://www.gtk.org/introspection/c/1.0}'


def qualify(name, ns):
    if not name:
        return None
    if '.' in name or name in ('none', 'utf8', 'filename', 'gboolean', 'gint',
                               'guint', 'gint8', 'guint8', 'gint16', 'guint16',
                               'gint32', 'guint32', 'gint64', 'guint64',
                               'gfloat', 'gdouble', 'gpointer', 'gconstpointer',
                               'gchar', 'guchar', 'gsize', 'gssize', 'glong',
                               'gulong', 'gunichar', 'GType', 'va_list',
                               'gshort', 'gushort', 'goffset', 'gintptr',
                               'guintptr', 'time_t'):
        return name
    return f'{ns}.{name}'


def type_of(el, ns):
    """Type of a <return-value>, <parameter>, <property> or <field>."""
    if el is None:
        return None
    for child in el:
        tag = child.tag
        if tag == CORE + 'type':
            name = child.get('name')
            if name in ('GLib.List', 'GLib.SList', 'GLib.PtrArray', 'GLib.Array'):
                inner = child.find(CORE + 'type')
                return {'array': qualify(inner.get('name'), ns) if inner is not None else None}
            return qualify(name, ns)
        if tag == CORE + 'array':
            inner = child.find(CORE + 'type')
            return {'array': qualify(inner.get('name'), ns) if inner is not None else None}
        if tag == CORE + 'callback':
            return 'callback'
    return None


def callable_info(el, ns):
    params = []
    plist = el.find(CORE + 'parameters')
    if plist is not None:
        for p in plist.findall(CORE + 'parameter'):
            params.append({
                'name': p.get('name'),
                'type': type_of(p, ns),
                'dir': p.get('direction', 'in'),
            })
    return {
        'ret': type_of(el.find(CORE + 'return-value'), ns),
        'params': params,
    }


def js_prop_name(name):
    return name.replace('-', '_')


def enum_member_name(member):
    return member.get('name').upper().replace('-', '_')


def container_info(el, ns, kind):
    info = {'kind': kind}
    parent = el.get('parent')
    if parent:
        info['parent'] = qualify(parent, ns)
    impls = [qualify(i.get('name'), ns) for i in el.findall(CORE + 'implements')]
    if impls:
        info['implements'] = impls
    prereq = [qualify(i.get('name'), ns) for i in el.findall(CORE + 'prerequisite')]
    if prereq:
        info['prerequisites'] = prereq
    methods = {}
    for m in el.findall(CORE + 'method'):
        methods[m.get('name')] = callable_info(m, ns)
    info['methods'] = methods
    statics = {}
    for tag in ('constructor', 'function'):
        for f in el.findall(CORE + tag):
            ci = callable_info(f, ns)
            if tag == 'constructor':
                ci['ret'] = f'{ns}.{el.get("name")}'
            statics[f.get('name')] = ci
    info['statics'] = statics
    props = {}
    for p in el.findall(CORE + 'property'):
        props[js_prop_name(p.get('name'))] = {
            'type': type_of(p, ns),
            'writable': p.get('writable') == '1',
            'construct_only': p.get('construct-only') == '1',
        }
    info['props'] = props
    signals = {}
    for s in el.findall(GLIB + 'signal'):
        signals[s.get('name')] = callable_info(s, ns)
    info['signals'] = signals
    fields = {}
    for f in el.findall(CORE + 'field'):
        if f.get('private') == '1':
            continue
        fields[f.get('name')] = type_of(f, ns)
    info['fields'] = fields
    return info


# gi-decompile-typelib (GLib 2.84 to 2.90) writes stray bytes into the
# glib:async-func, glib:sync-func and glib:finish-func attributes. Nothing
# here reads them.
FUNC_ATTR_RE = re.compile(rb'\s(?:glib:)?(?:async|sync|finish)-func="[^"]*"')
CONTROL_RE = re.compile(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]')
# Top-level entries of a namespace, as the decompilers indent them
TOP_CLOSE_RE = re.compile(
    rb'\n    </(?:class|interface|record|union|enumeration|bitfield|callback|'
    rb'function|constant|alias|docsection|glib:boxed)>|\n    <(?:constant|alias|function|callback)\b[^\n]*/>')


def load_xml(path):
    """Parse a GIR dump. A dump cut short by a crashing decompiler is cut
    back to its last complete top-level entry and closed, so everything
    before the crash is kept. Returns (root, salvaged)."""
    with open(path, 'rb') as fh:
        data = fh.read()
    data = CONTROL_RE.sub(b'', FUNC_ATTR_RE.sub(b'', data))
    salvaged = False
    if b'</repository>' not in data[-64:]:
        ends = [m.end() for m in TOP_CLOSE_RE.finditer(data)]
        if not ends:
            raise ET.ParseError(f'{path}: truncated before the first entry')
        data = data[:ends[-1]] + b'\n  </namespace>\n</repository>\n'
        salvaged = True
    return ET.fromstring(data), salvaged


def convert(path, index):
    root, salvaged = load_xml(path)
    for nsel in root.findall(CORE + 'namespace'):
        ns = nsel.get('name')
        out = index.setdefault(ns, {
            'version': nsel.get('version'),
            'types': {},
            'functions': {},
            'constants': [],
        })
        if salvaged:
            out['partial'] = True
            print(f'gir2json: {path} was cut short; kept what came before', file=sys.stderr)
        for tag, kind in (('class', 'class'), ('interface', 'interface'),
                          ('record', 'record'), ('union', 'union')):
            for el in nsel.findall(CORE + tag):
                if el.get(GLIB + 'is-gtype-struct-for'):
                    continue
                out['types'][el.get('name')] = container_info(el, ns, kind)
        # Boxed types without a C struct (GVariant) appear as glib:boxed
        for el in nsel.findall(GLIB + 'boxed'):
            name = el.get(GLIB + 'name')
            if name and name not in out['types']:
                out['types'][name] = container_info(el, ns, 'record')
        for tag in ('enumeration', 'bitfield'):
            for el in nsel.findall(CORE + tag):
                out['types'][el.get('name')] = {
                    'kind': 'enum',
                    'members': [enum_member_name(m) for m in el.findall(CORE + 'member')],
                    'statics': {f.get('name'): callable_info(f, ns)
                                for f in el.findall(CORE + 'function')},
                }
        for el in nsel.findall(CORE + 'function'):
            out['functions'][el.get('name')] = callable_info(el, ns)
        for el in nsel.findall(CORE + 'constant'):
            out['constants'].append(el.get('name'))


def main(argv):
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    index = {}
    for path in argv[2:]:
        try:
            convert(path, index)
        except ET.ParseError as e:
            print(f'gir2json: cannot parse {path}: {e}', file=sys.stderr)
            return 1
    with open(argv[1], 'w', encoding='utf-8') as fh:
        json.dump(index, fh, separators=(',', ':'), sort_keys=True)
    print(f'gir2json: {len(index)} namespaces -> {argv[1]}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
