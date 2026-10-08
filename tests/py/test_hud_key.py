# The HUD key is grabbed on X11 through libkeybinder, which fails when the
# shell already holds the chord. GNOME binds <Alt>space (activate-window-menu),
# <Super>space and <Shift><Super>space (switch-input-source).

import logging
import re

import pytest

# Defaults of GNOME 48 that the rules for this project list, plus the three
# bindings on the space bar
GNOME_DEFAULT_BINDINGS = {
	'<Alt>space', '<Super>space', '<Shift><Super>space',
	'<Control><Alt>Left', '<Control><Alt>Right', '<Control><Alt>Up', '<Control><Alt>Down',
	'<Control><Shift><Alt>Left', '<Control><Shift><Alt>Right',
	'<Control><Shift><Alt>Up', '<Control><Shift><Alt>Down',
	'<Alt>F2', '<Shift><Alt>F6', 'Print', '<Shift>Print', '<Alt>Print',
	'<Ctrl><Shift><Alt>R', '<Control><Alt>Delete',
} | {'<Super>%d' % n for n in range(1, 10)}


def normalize_chord(chord):
	mods = re.findall(r'<(\w+)>', chord)
	key = re.sub(r'<\w+>', '', chord)
	alias = {'control': 'ctrl', 'primary': 'ctrl'}
	return (frozenset(alias.get(m.lower(), m.lower()) for m in mods), key.lower())


@pytest.fixture
def hud_bind(monkeypatch):
	from gi.repository import GLib
	from globalmenu import keybinder

	bound = []

	class FakeKeybinder:
		result = True

		@staticmethod
		def bind(chord, callback, *args):
			bound.append(chord)
			return FakeKeybinder.result

	class Loop:
		def run(self):
			pass

	monkeypatch.setattr(keybinder, 'Keybinder', FakeKeybinder)
	monkeypatch.setattr(keybinder, 'DBusGMainLoop', lambda **kw: None)
	monkeypatch.setattr(keybinder, 'DbusMenu', lambda: None)
	monkeypatch.setattr(GLib, 'MainLoop', Loop)

	def run(bind_result=True):
		FakeKeybinder.result = bind_result
		keybinder.run_keybinder(lambda *a: None)
		return bound

	return run


def test_hud_chord_is_not_one_gnome_binds_by_default(hud_bind):
	(chord,) = hud_bind()
	taken = {normalize_chord(c) for c in GNOME_DEFAULT_BINDINGS}
	assert normalize_chord(chord) not in taken


def test_failed_hud_bind_is_logged(hud_bind, caplog):
	with caplog.at_level(logging.WARNING):
		(chord,) = hud_bind(bind_result=False)
	assert chord in caplog.text


def test_successful_hud_bind_logs_nothing(hud_bind, caplog):
	with caplog.at_level(logging.WARNING):
		hud_bind()
	assert caplog.text == ''
