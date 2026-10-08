# Each HUD opens its own WindowActions, so closing the HUD has to drop the
# signal receiver or every later ListWindowActionsSignal reaches dead windows.

from types import SimpleNamespace

import dbus
import pytest

from fakes import FakeSession
from globalmenu.handlers.default import HudMenu
from globalmenu.utils.service import MyService
from globalmenu.utils.window import WindowActions


@pytest.fixture
def session(monkeypatch):
	session = FakeSession()
	monkeypatch.setattr(dbus, 'SessionBus', lambda: session)
	return session


def emit_actions(session, actions):
	session.emit(MyService.BUS_NAME, MyService.BUS_PATH, None, 'ListWindowActionsSignal', actions)


def test_closed_window_actions_stop_receiving_signals(session):
	seen = []
	window_actions = WindowActions(seen.append)
	emit_actions(session, ['Close'])
	window_actions.close()
	emit_actions(session, ['Minimize'])
	assert seen == [['Close']]


def test_closing_one_window_actions_keeps_the_others(session):
	first, second = [], []
	closed = WindowActions(first.append)
	WindowActions(second.append)
	closed.close()
	emit_actions(session, ['Close'])
	assert (first, second) == ([], [['Close']])


def test_hiding_the_hud_closes_its_window_actions(session):
	calls = []
	window_actions = WindowActions()
	window_actions.close = lambda: calls.append('close')
	hud = SimpleNamespace(window_actions=window_actions,
		window=SimpleNamespace(set_dark_variation=lambda dark: None, destroy=lambda: None),
		quit=lambda: None)
	HudMenu.on_hide_window(hud)
	assert calls == ['close']
