// Sends GTK-style accelerator strings ("<Ctrl><Shift>N") to the focused window
// through a Clutter virtual keyboard.
// Uses keyvals, not scancodes, so the layout does not matter. Shell process
// only; preferences use accelerator.js.

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

// On activation the shell still holds the input grab and the target may lack
// focus, so an immediate keystroke goes to the shell.
const AFTER_MENU_DELAY_MS = 100;

// Keystrokes waiting for their menu to let go. The extension's disable()
// removes them.
const pendingSends = new Set();

/**
 * Parse and synthesize an accelerator. Returns false and logs a warning if it
 * is unparseable.
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
 * sendShortcut() for a menu item's activate handler: sent once the menu has
 * released its grab.
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
	// Release the device and any held keys now, not at garbage collection, as
	// the shell's keyboard.js does.
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
