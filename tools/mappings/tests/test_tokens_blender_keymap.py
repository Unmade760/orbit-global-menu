from mtools import accel, tokens

ITEMS = (
    '("wm.open_mainfile", {"type": \'O\', "value": \'PRESS\', "ctrl": True}, None),\n'
    '("screen.workspace_cycle", {"type": \'PAGE_DOWN\', "value": \'PRESS\', "ctrl": True},\n'
    '("render.render", {"type": \'F12\', "value": \'PRESS\', "ctrl": True, "alt": True},\n'
    '("ed.redo", {"type": \'Z\', "value": \'PRESS\', "shift": True, "ctrl": True, "repeat": True}, None),\n'
    '("view3d.view_selected", {"type": \'NUMPAD_PERIOD\', "value": \'PRESS\'}, None),\n'
    '("wm.context_toggle", {"type": \'COMMA\', "value": \'PRESS\', "ctrl": True}, None),\n'
    'op_menu_pie("VIEW3D_MT_shading_pie", {"type": \'Z\', "value": params.pie_value}),\n'
)


def chords(text):
    return [seq for _, _, _, seq in tokens.find_chords(text)]


def test_blender_keymap_items_read_modifiers_and_key():
    found = chords(ITEMS)
    for chord in ("<Ctrl>O", "<Ctrl>Page_Down", "<Ctrl><Alt>F12", "<Ctrl><Shift>Z", "KP_Decimal",
                  "<Ctrl>comma", "Z"):
        assert accel.parse_grammar(chord) in found, chord


def test_blender_keymap_item_keeps_its_modifiers():
    line = '("render.render", {"type": \'F12\', "value": \'PRESS\', "ctrl": True},\n'
    ok, _ = tokens.contains(line, accel.parse_grammar("<Ctrl>F12"))
    assert ok
    ok, _ = tokens.contains(line, accel.parse_grammar("<Alt>F12"))
    assert not ok


def test_blender_event_that_is_not_a_press_is_not_read():
    text = '("object.delete", {"type": \'F2\', "value": \'DOUBLE_CLICK\', "ctrl": True}, None),\n'
    assert accel.parse_grammar("<Ctrl>F2") not in chords(text)
    text = '("screen.animation_step", {"type": \'TIMER0\', "value": \'ANY\', "any": True}, None),\n'
    assert chords(text) == []
