// Sends GTK-style accelerator strings ("<Ctrl><Shift>N") to the focused
// window through a Clutter virtual keyboard device. Keyvals, not raw evdev
// scancodes, so a shortcut lands on the right key whatever the keyboard
// layout is. Shell process only: the preferences process uses
// accelerator.js, which has no Clutter.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';

import {parseAccelerator} from './accelerator.js';

let debug = false;

/**
 * Turn debug logging on or off.
 *
 * @param {boolean} enabled
 */
export function setDebug(enabled) {
	debug = enabled;
}

function logDebug(msg) {
	if (debug)
		console.log(`[global-menu-keysynth] ${msg}`);
}

// Chords land as one burst otherwise, and an app waiting on a prefix key
// cannot tell them apart.
const CHORD_GAP_US = 1000;

// When a menu item activates the shell still holds the input grab, and the
// target window may not have keyboard focus back yet, so synthesizing
// immediately delivers the keystroke to the shell instead of the app.
const AFTER_MENU_DELAY_MS = 100;

// Keystrokes waiting for their menu to let go. The extension's disable()
// removes them.
const pendingSends = new Set();

/**
 * Parse and synthesize an accelerator. Returns false and logs a warning if
 * the accelerator is unparseable, true if synthesis was dispatched.
 *
 * @param {string} accel
 * @returns {boolean}
 */
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

/**
 * sendShortcut() for a menu item's activate handler: the keystroke goes
 * out once the menu has released its grab.
 *
 * @param {string} accel
 */
export function sendShortcutAfterMenu(accel) {
	const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, AFTER_MENU_DELAY_MS, () => {
		pendingSends.delete(id);
		sendShortcut(accel);
		return GLib.SOURCE_REMOVE;
	});
	pendingSends.add(id);
}

export function cancelPendingShortcuts() {
	for (const id of pendingSends)
		GLib.source_remove(id);
	pendingSends.clear();
	// Releases the device and any key it still holds now, not at the next
	// garbage collection. The shell's keyboard.js does the same.
	device?.run_dispose();
	device = null;
}

// One device serves every shortcut, created on first use and released by
// cancelPendingShortcuts() when the extension is disabled.
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
