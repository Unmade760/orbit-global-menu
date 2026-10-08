import gi

from globalmenu.utils.wayland import is_wayland

# Keybinder is X11 only and optional: without it the daemon runs with no
# global key bindings. This is the only module that may import it.
Keybinder = None
if not is_wayland():
	try:
		gi.require_version('Keybinder', '3.0')
		from gi.repository import Keybinder
	except (ValueError, ImportError):
		Keybinder = None


class GlobalKeybinder:
	"""
	Global keybinder for mnemonic, like Alt+F for files, etc.
	"""
	def __init__(self, callback=None):
		Keybinder.init()
		self.keybinding_strings = []
		self.keybinder_callback = callback

	@classmethod
	def create(cls, callback=None):
		if Keybinder is not None:
			return cls(callback)
		else:
			return DummyKeybinder()

	def add_keybinding(self, character):
		acc = '<Alt>' + character
		Keybinder.bind(acc, lambda accelerator: self.on_keybind_activated(character))
		self.keybinding_strings.append(acc)

	def on_keybind_activated(self, char):
		self.keybinder_callback(char)

	def remove_all_keybindings(self):
		for k in self.keybinding_strings:
			Keybinder.unbind(k)
		self.keybinding_strings = []


class DummyKeybinder:

	def add_keybinding(self, character):
		pass

	def remove_all_keybindings(self):
		pass
