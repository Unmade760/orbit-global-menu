from gi.repository import Adw, Gdk, Gtk

ACCELS = [
    ("app.quit", ["<primary>q"]),
    ("win.toggle-sidebar", ["F9", "<primary>backslash"]),
]


class Application(Adw.Application):
    def do_startup(self):
        self.set_accels_for_action("win.find", ["<primary>f"])  # "win.fake" <primary>k is a comment
        trigger = Gtk.ShortcutTrigger.parse_string("<Control><Shift>p")
        action = Gtk.NamedAction.new("win.palette")


class Window(Adw.ApplicationWindow):
    def __init__(self):
        self.add_binding_action(Gdk.KEY_n, Gdk.ModifierType.CONTROL_MASK, "win.new-note")
