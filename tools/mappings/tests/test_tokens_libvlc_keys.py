from mtools import accel, tokens


def chords(text):
    return [seq for _, _, _, seq in tokens.find_chords(text)]


def test_libvlc_define_with_a_punctuation_key():
    for key in ('+', '-', '=', '[', ']'):
        assert accel.parse_grammar(key) in chords('#   define KEY_FASTER             "%s"' % key)


def test_libvlc_define_with_page_keys():
    assert accel.parse_grammar("Page_Up") in chords('#   define KEY_VIEWPOINT_FOV_IN   "Page Up"')
    assert accel.parse_grammar("Page_Down") in chords('#   define KEY_VIEWPOINT_FOV_OUT  "Page Down"')


def test_libvlc_define_with_a_media_key_alias_reads_the_first_key():
    assert accel.parse_grammar("space") in chords('#   define KEY_PLAY_PAUSE         "Space\\tMedia Play Pause"')


def test_a_punctuation_string_outside_a_key_define_is_not_a_chord():
    assert chords('#define SEPARATOR "+"') == []
    assert chords('x = "-";') == []
