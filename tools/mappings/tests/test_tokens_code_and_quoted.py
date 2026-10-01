from mtools import accel, tokens


def chords(text):
    return [seq for _, _, _, seq in tokens.find_chords(text)]


def test_keyboard_event_code_names():
    assert chords("{ keys: 'ControlLeft+ShiftLeft+KeyZ', action: 'redo' }") == [accel.parse_grammar("<Ctrl><Shift>z")]
    assert chords("{ keys: 'Space' }") == [accel.parse_grammar("space")]
    assert accel.parse_grammar("<Shift><Alt>Page_Up") in chords("'ShiftLeft+AltLeft+PageUp'")


def test_keyboard_event_code_names_skip_meta_and_bare_words():
    assert chords("'MetaLeft+KeyZ'") == []
    assert chords("the Space between") == []


def test_single_character_string_literal_is_a_bare_key():
    assert chords('{QStringLiteral("split"), QStringLiteral("S")},') == [accel.parse_grammar("s")]
    assert chords('sequence: "3"') == [accel.parse_grammar("3")]
    assert chords('name = "ab"') == []
