from mtools import accel, tokens

BIND = ('<bind gaction="win.canvas-zoom-in"                    keys="plus,  equal,        KP_Add" />\n'
        '<bind gaction="win.canvas-zoom-1-1"                   keys="1,                   KP_1" />\n'
        '<bind gaction="app.path-union" keys="&lt;primary&gt;plus,\n'
        '                                     &lt;primary&gt;KP_Add" />\n')


def chords(text):
    return [seq for _, _, _, seq in tokens.find_chords(text)]


def test_inkscape_bind_keys_without_modifiers():
    found = chords(BIND)
    assert accel.parse_grammar("+") in found
    assert accel.parse_grammar("=") in found
    assert accel.parse_grammar("KP_Add") in found
    assert accel.parse_grammar("1") in found


def test_inkscape_bind_keys_read_across_lines():
    assert accel.parse_grammar("<Ctrl>KP_Add") in chords(BIND)


def test_inkscape_bare_keys_in_shifted_symbols():
    text = '<bind gaction="doc.show-all-guides" keys="&lt;shift&gt;bar,        bar" />'
    assert accel.parse_grammar("|") in chords(text)
    text = '<bind gaction="win.canvas-zoom-prev" keys="grave,   KP_8" />'
    assert accel.parse_grammar("`") in chords(text)


def test_keys_attribute_outside_a_bind_is_not_read():
    assert chords('<item keys="plus">') == []
    assert chords('<bind gaction="tool.all.quick-zoom" />') == []
