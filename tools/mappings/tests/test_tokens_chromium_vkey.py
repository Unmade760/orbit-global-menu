from mtools import accel, tokens


def chords(text):
    return [seq for _, _, _, seq in tokens.find_chords(text)]


def test_chromium_accelerator_table_entries():
    assert chords("{ui::VKEY_F7, ui::EF_NONE, IDC_CARET_BROWSING_TOGGLE},") == [accel.parse_grammar("F7")]
    assert chords("{ui::VKEY_D, ui::EF_PLATFORM_ACCELERATOR, IDC_BOOKMARK_THIS_TAB},") == [accel.parse_grammar("<Ctrl>d")]
    assert chords("{ui::VKEY_NEXT, ui::EF_CONTROL_DOWN | ui::EF_SHIFT_DOWN, X},") == [accel.parse_grammar("<Ctrl><Shift>Page_Down")]
    assert chords("{ui::VKEY_1, ui::EF_ALT_DOWN, IDC_SELECT_TAB_0},") == [accel.parse_grammar("<Alt>1")]
    assert chords("{ui::VKEY_OEM_PLUS, ui::EF_SHIFT_DOWN | ui::EF_CONTROL_DOWN, IDC_ZOOM_PLUS},") == [accel.parse_grammar("<Ctrl><Shift>plus")]


def test_chromium_accelerator_table_entry_split_over_lines():
    text = "{ui::VKEY_D, ui::EF_SHIFT_DOWN | ui::EF_PLATFORM_ACCELERATOR,\n IDC_BOOKMARK_ALL_TABS},"
    assert chords(text) == [accel.parse_grammar("<Ctrl><Shift>d")]


def test_chromium_accelerator_constructor():
    text = "*accelerator = ui::Accelerator(ui::VKEY_X, ui::EF_PLATFORM_ACCELERATOR);"
    assert chords(text) == [accel.parse_grammar("<Ctrl>x")]


def test_chromium_accelerator_skips_keys_with_no_linux_chord():
    assert chords("{ui::VKEY_LEFT, ui::EF_ALTGR_DOWN, IDC_BACK},") == []
    assert chords("{ui::VKEY_Z, ui::EF_COMMAND_DOWN, IDC_X},") == []
    assert chords("{ui::VKEY_BROWSER_BACK, ui::EF_NONE, IDC_BACK},") == []


def test_blink_editing_behavior_entries():
    assert accel.parse_grammar("<Ctrl>z") in chords('{\'Z\', kCtrlKey, "Undo"},')
    assert accel.parse_grammar("<Ctrl><Shift>z") in chords('{\'Z\', kCtrlKey | kShiftKey, "Redo"},')
    assert accel.parse_grammar("<Ctrl>a") not in chords('{\'A\', kMetaKey, "SelectAll"},')
