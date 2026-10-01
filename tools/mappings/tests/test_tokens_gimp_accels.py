from mtools import accel, tokens


def chords(text):
    return [seq for _, _, _, seq in tokens.find_chords(text)]


def test_gimp_accelerator_array_with_a_keysym_name():
    assert accel.parse_grammar("-") in chords('{ "minus", "KP_Subtract", "ZoomOut", NULL },')
    assert accel.parse_grammar("+") in chords('{ "plus", "KP_Add", "ZoomIn", NULL },')
    assert accel.parse_grammar("`") in chords('{ "grave", NULL },')
    assert accel.parse_grammar("!") in chords('{ "exclam", NULL },')
    assert accel.parse_grammar("/") in chords('{ "slash", "KP_Divide", NULL },')


def test_gimp_accelerator_array_with_prior_and_next():
    assert accel.parse_grammar("Page_Up") in chords('{ "Prior", NULL },')
    assert accel.parse_grammar("Page_Down") in chords('{ "Next", NULL },')


def test_a_keysym_name_outside_an_accelerator_array_is_not_a_chord():
    assert chords('const char *next = "Next";') == []
    assert chords('{ "minus", "plus" }') == []
    assert chords('{ "slash", 3 }') == []
