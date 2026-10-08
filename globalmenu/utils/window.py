import dbus
import gi

from gi.repository import Gio

from globalmenu.utils.service import MyService
from globalmenu.utils.wayland import is_wayland

'''
The extension reports every window switch over D-Bus on Wayland and on X11
alike. Bamf is X11 only and optional: it supplies the window the daemon
starts with when the standalone HUD runs without the extension. This is the
only module that may import Bamf.
'''
# If the session type looks wrong:
# loginctl show-session $(loginctl | grep $(whoami) | awk '{print $1}') -p Type
Bamf = None
if not is_wayland():
	try:
		gi.require_version('Bamf', '3')
		from gi.repository import Bamf
	except (ValueError, ImportError):
		Bamf = None


class Window(object):
	def __init__(self, bamf_window=None):
		super(Window, self).__init__()
		self.bamf_window = bamf_window
		self.xid = 0
		self.props = {}

	def get_xid(self):
		if self.bamf_window != None:
			return self.bamf_window.get_xid()

		return self.xid

	def set_xid(self, xid):
		self.xid = xid

	def get_utf8_prop(self, id):
		if self.bamf_window != None:
			return self.bamf_window.get_utf8_prop(id)

		return self.props[id] if id in self.props else None
  
	def set_utf8_prop(self, key, value):
		self.props[key] = value

	def get_app_name(self):
		if 'appName' in self.props:
			return self.props['appName']
		if self.bamf_window != None:
			return WindowManager.get_app_name()

		return ''


class WindowActions(object):
	"""Window actions from the shell from the alt-space menu"""
	def __init__(self, callback=None):
		super(WindowActions, self).__init__()

		self.listeners = []
		if callback is not None:
			self.listeners.append(callback)

		session = dbus.SessionBus()
		self.proxy = session.get_object(MyService.BUS_NAME, MyService.BUS_PATH)
		self.actions = []
		self.proxy.connect_to_signal("ListWindowActionsSignal", self.on_actions_receive)

	def request_window_actions(self):
		self.proxy.RequestWindowActions()

	def on_actions_receive(self, actions):
		self.actions = actions
		for callback in self.listeners:
			callback(actions)

	def activate_action(self, action):
		self.proxy.ActivateWindowAction(action)


class WindowManager(object):
	"""
	Used as a class rather than an instance. There is only ever one window
	manager, so the class itself is the singleton.

	Attributes
	----------
	listers: List[Callable[Window]]
		list of callback functions to be called. There will be only
		one anyways.
	matcher: Bamf.Matcher
		Bamf matcher.
		https://lazka.github.io/pgi-docs/Bamf-3/classes/Matcher.html
 
	Methods
	-------
	new_window(win_data={})
		Returns a window object. To be used when initializing and
		on window switching. `win_data` is the info from the extension.
	"""
	listeners = []
	matcher = None

	@classmethod
	def _start_listener(cls):
		session = dbus.SessionBus()
		proxy  = session.get_object('space.unmade.GlobalMenu', '/space/unmade/GlobalMenu')
		proxy.connect_to_signal("WindowSwitchedSignal", cls._window_switched)

	@classmethod
	def _get_matcher(cls):
		if cls.matcher == None:
			cls.matcher = Bamf.Matcher.get_default()
		return cls.matcher

	@classmethod
	def new_window(cls, win_data={}):
		if not win_data and Bamf is not None:
			return Window(cls._get_matcher().get_active_window())

		win = Window()
		for p in win_data:
			if p == 'xid':
				win.set_xid(int(win_data[p]) if win_data[p] != '' else 0)
			else:
				win.set_utf8_prop('_' + p.upper(), win_data[p])

		return win

	@classmethod
	def _window_switched(cls, win_data):
		win = cls.new_window(win_data)
		cls._call_all_listeners(win)

	@classmethod
	def _call_all_listeners(cls, window):
		for callback in cls.listeners:
			callback(window)

	@classmethod
	def add_listener(cls, callback):
		if len(cls.listeners) == 0:
			cls._start_listener()
		cls.listeners.append(callback)

	@classmethod
	def get_app_name(cls):
		app  = cls._get_matcher().get_active_application()
		file = app.get_desktop_file()
		info = Gio.DesktopAppInfo.new_from_filename(file)

		return info.get_string('Name')
