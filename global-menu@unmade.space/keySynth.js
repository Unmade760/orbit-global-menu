
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {parseAccelerator} from './accelerator.js';

let debug = false;

export function setDebug(enabled) {
	debug = enabled;
}

function logDebug(msg) {
	if (debug)
		console.log(`[global-menu-keysynth] ${msg}`);
}

// space chords out or apps waiting on a prefix key
// cannot tell them apart
const CHORD_GAP_US = 1000;

// wait for the menu to release its grab
// or the shell gets the keystroke
const AFTER_MENU_DELAY_MS = 100;

const pendingSends = new Set();

export function sendShortcut(accel) {
	const chords = parseAccelerator(accel);
	if (!chords) {
		console.warn(`[global-menu-keysynth] Unparseable accelerator: ${accel}`);
		return false;
	}
	logDebug(`Synthesizing ${accel}`);
	try {
		synthesize(chords);
	} catch (e) {
		console.error(`[global-menu-keysynth] Synthesis failed for "${accel}": ${e}`);
	}
	return true;
}

export function sendShortcutAfterMenu(accel) {
	const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, AFTER_MENU_DELAY_MS, () => {
		pendingSends.delete(id);
		sendShortcut(accel);
		return GLib.SOURCE_REMOVE;
	});
	pendingSends.add(id);
}

// the shortcut stands in when the window has no gtk action bus
// or the app refuses the action
function activateAction(action, target, shortcut) {
	const win = global.display.get_focus_window();
	const bus = win?.gtk_unique_bus_name;
	const path = win?.gtk_application_object_path;
	const fallback = reason => {
		logDebug(`Action ${action} failed: ${reason}`);
		if (shortcut)
			sendShortcut(shortcut);
	};
	if (!bus || !path) {
		fallback('window has no gtk action bus');
		return;
	}
	const parameter = target === undefined ? [] : [GLib.Variant.new_int32(target)];
	Gio.DBus.session.call(bus, path, 'org.gtk.Actions', 'Activate',
		new GLib.Variant('(sava{sv})', [action, parameter, {}]),
		null, Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
			try {
				conn.call_finish(res);
			} catch (e) {
				fallback(e.message);
			}
		});
}

export function activateActionAfterMenu(action, target, shortcut) {
	const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, AFTER_MENU_DELAY_MS, () => {
		pendingSends.delete(id);
		activateAction(action, target, shortcut);
		return GLib.SOURCE_REMOVE;
	});
	pendingSends.add(id);
}

export function cancelPendingShortcuts() {
	for (const id of pendingSends)
		GLib.source_remove(id);
	pendingSends.clear();
	// run_dispose frees the virtual keyboard and any held key now
	// instead of at garbage collection like keyboard.js does
	device?.run_dispose();
	device = null;
}

let device = null;

function synthesize(chords) {
	if (!device) {
		const seat = global.stage.context.get_backend().get_default_seat();
		device = seat.create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
	}
	const dev = device;
	let t = GLib.get_monotonic_time();
	for (const {modifiers, keyval} of chords) {
		for (const mod of modifiers)
			dev.notify_keyval(t += 10, mod, Clutter.KeyState.PRESSED);
		dev.notify_keyval(t += 10, keyval, Clutter.KeyState.PRESSED);
		dev.notify_keyval(t += 10, keyval, Clutter.KeyState.RELEASED);
		for (const mod of [...modifiers].reverse())
			dev.notify_keyval(t += 10, mod, Clutter.KeyState.RELEASED);
		t += CHORD_GAP_US;
	}
}
