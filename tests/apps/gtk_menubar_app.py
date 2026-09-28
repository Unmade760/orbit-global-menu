#!/usr/bin/env python3
"""A GtkApplication with a known menubar, for tools/checks/daemon.sh.

    python3 tests/apps/gtk_menubar_app.py --gtk 4
    python3 tests/apps/gtk_menubar_app.py --gtk 3

Items with a shortcut carry it twice, as apps built from GtkBuilder
menus do: as the menu item's "accel" attribute, which is what the exported
org.gtk.Menus model shows, and through set_accels_for_action.

The menubar holds every item kind the daemon has to convert: plain items
with accelerators, a nested submenu, sections, a check item, a radio group
and a disabled item. tests/daemon/daemon_check.py holds the exact tree it
expects, so a change here needs a change there.

Two actions stay out of the menu and exist for the check to call over
org.gtk.Actions.Activate:
    test-add-item      appends "Added _Later" to the View menu
    test-quit          quits the app
"""

import argparse
import sys

import gi

APP_ID = 'space.unmade.GlobalMenuTestApp'

MENUBAR = [
	('_File', [
		[('_New', 'app.new', None, '<Primary>n'), ('_Open', 'app.open', None, '<Primary>o')],
		[('_Export', [
			[('As _PDF', 'app.export-pdf', None, '<Primary><Shift>e'), ('As P_NG', 'app.export-png', None, None)],
		])],
		[('_Quit', 'app.quit', None, '<Primary>q')],
	]),
	('_View', [
		[('Show _Sidebar', 'app.sidebar', None, 'F9')],
		[('_Small', 'app.size', 'small', '<Primary>1'), ('_Large', 'app.size', 'large', '<Primary>2')],
		[('_Unavailable', 'app.unavailable', None, '<Primary>u')],
	]),
]


def parse_args():
	parser = argparse.ArgumentParser()
	parser.add_argument('--gtk', choices=['3', '4'], default='4')
	return parser.parse_args()


def main():
	args = parse_args()
	gi.require_version('Gtk', args.gtk + '.0')
	from gi.repository import Gio, GLib, Gtk

	def build_menu(sections):
		menu = Gio.Menu()
		for section in sections:
			part = Gio.Menu()
			for entry in section:
				if isinstance(entry[1], list):
					part.append_submenu(entry[0], build_menu(entry[1]))
					continue
				label, action, target, accel = entry
				item = Gio.MenuItem.new(label, None)
				if target is None:
					item.set_action_and_target_value(action, None)
				else:
					item.set_action_and_target_value(action, GLib.Variant('s', target))
				if accel:
					# What a GtkBuilder menu's <attribute name="accel"> gives
					item.set_attribute_value('accel', GLib.Variant('s', accel))
				part.append_item(item)
			menu.append_section(None, part)
		return menu

	app = Gtk.Application(application_id=APP_ID)
	state = {'view': None, 'window': None}

	def add(name, callback=None, param=None, value=None):
		if value is None:
			action = Gio.SimpleAction.new(name, param)
		else:
			action = Gio.SimpleAction.new_stateful(name, param, value)
		action.connect('activate', callback or (lambda a, p: print('activated', name, p, flush=True)))
		app.add_action(action)
		return action

	def toggle(action, _param):
		action.set_state(GLib.Variant('b', not action.get_state().get_boolean()))
		print('sidebar', action.get_state().get_boolean(), flush=True)

	def choose(action, param):
		action.set_state(param)
		print('size', param.get_string(), flush=True)

	def add_item(_action, _param):
		item = Gio.MenuItem.new('Added _Later', 'app.new')
		state['view'].append_item(item)
		print('added item', flush=True)

	def on_startup(_app):
		for name in ('new', 'open', 'export-pdf', 'export-png'):
			add(name)
		add('quit', lambda a, p: app.quit())
		add('sidebar', toggle, None, GLib.Variant('b', True))
		add('size', choose, GLib.VariantType.new('s'), GLib.Variant('s', 'large'))
		add('unavailable').set_enabled(False)
		add('test-add-item', add_item)
		add('test-quit', lambda a, p: app.quit())

		menubar = Gio.Menu()
		for title, sections in MENUBAR:
			sub = build_menu(sections)
			if title == '_View':
				# A section of its own at the end, where test-add-item writes
				state['view'] = Gio.Menu()
				sub.append_section(None, state['view'])
			menubar.append_submenu(title, sub)
		app.set_menubar(menubar)

		def accels(sections):
			for section in sections:
				for entry in section:
					if isinstance(entry[1], list):
						accels(entry[1])
					elif entry[3]:
						detailed = entry[1] if entry[2] is None else '%s::%s' % (entry[1], entry[2])
						app.set_accels_for_action(detailed, [entry[3]])
		for _title, sections in MENUBAR:
			accels(sections)

	def on_activate(_app):
		window = Gtk.ApplicationWindow(application=app, title='Global Menu test app')
		window.set_show_menubar(True)
		window.set_default_size(400, 300)
		state['window'] = window
		if args.gtk == '3':
			window.show_all()
		else:
			window.present()
		GLib.idle_add(report_ready)

	def report_ready():
		window = state['window']
		print('ready bus=%s app_path=%s window_id=%d' % (
			app.get_dbus_connection().get_unique_name(),
			app.get_dbus_object_path(),
			window.get_id()), flush=True)
		return False

	app.connect('startup', on_startup)
	app.connect('activate', on_activate)
	return app.run([sys.argv[0]])


if __name__ == '__main__':
	sys.exit(main())
