from mtools import accel, tokens


def chords(text):
    return [seq for _, _, _, seq in tokens.find_chords(text)]


def test_accelerators_xcu_node_names():
    assert chords('<node oor:name="S_SHIFT_MOD1" oor:op="replace">') == [accel.parse_grammar("<Ctrl><Shift>S")]
    assert chords('<node oor:name="F3_MOD1">') == [accel.parse_grammar("<Ctrl>F3")]
    assert chords('<node oor:name="ADD_MOD1">') == [accel.parse_grammar("<Ctrl>KP_Add")]
    assert chords('<node oor:name="K_MOD1_MOD2">') == [accel.parse_grammar("<Ctrl><Alt>K")]


def test_accelerators_xcu_ignores_mac_and_section_nodes():
    assert chords('<node oor:name="A_MOD3">') == []
    assert chords('<node oor:name="PrimaryKeys">') == []
    assert chords('<node oor:name="COPY">') == []
