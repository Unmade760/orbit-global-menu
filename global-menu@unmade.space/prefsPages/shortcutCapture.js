// Shortcut capture dialog, behaving like the one in GNOME Settings' Keyboard
// panel: press a combination, see it echoed live, Escape cancels, Backspace
// disables.

import Adw from 'gi://Adw';
import Gdk from 'gi://Gdk';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import {parseAccelerator} from '../accelerator.js';

const MODIFIER_KEYVALS = new Set([
	Gdk.KEY_Control_L, Gdk.KEY_Control_R,
	Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
	Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
	Gdk.KEY_Super_L, Gdk.KEY_Super_R,
	Gdk.KEY_Meta_L, Gdk.KEY_Meta_R,
]);

/**
 * Presents the capture dialog over parentWindow. onCaptured is called with:
 *   a string    the captured accelerator, already validated against
 *               accelerator.parseAccelerator and so known to be synthesizable
 *   null        Backspace was pressed: clear the shortcut
 *   undefined   cancelled with Escape or by dismissing the dialog
 *
 * @param {object} options
 * @param {Adw.Window} options.parentWindow
 * @param {string} options.itemLabel
 * @param {Function} options.onCaptured
 */
export function captureShortcut({parentWindow, itemLabel, onCaptured}) {
	const dialog = new Adw.Dialog({content_width: 420, can_close: true});

	const box = new Gtk.Box({
		orientation: Gtk.Orientation.VERTICAL,
		spacing: 12,
		margin_top: 28,
		margin_bottom: 28,
		margin_start: 28,
		margin_end: 28,
		halign: Gtk.Align.CENTER,
	});
	dialog.set_child(box);

	box.append(new Gtk.Label({label: 'Set Shortcut', css_classes: ['title-2']}));

	box.append(new Gtk.Label({
		label: `Enter new shortcut to change <b>${GLib.markup_escape_text(itemLabel, -1)}</b>`,
		use_markup: true,
		wrap: true,
		justify: Gtk.Justification.CENTER,
	}));

	const preview = new Gtk.Label({
		label: 'Enter a new shortcut…',
		css_classes: ['title-1'],
		margin_top: 12,
		margin_bottom: 12,
	});
	box.append(preview);

	box.append(new Gtk.Label({
		label: 'Press Esc to cancel or Backspace to disable the keyboard shortcut',
		css_classes: ['dim-label'],
		wrap: true,
		justify: Gtk.Justification.CENTER,
	}));

	let finished = false;
	const finish = result => {
		if (finished)
			return;
		finished = true;
		dialog.close();
		onCaptured(result);
	};

	const controller = new Gtk.EventControllerKey();
	controller.connect('key-pressed', (_controller, keyval, _keycode, state) => {
		if (keyval === Gdk.KEY_Escape) {
			finish(undefined);
			return true;
		}
		if (keyval === Gdk.KEY_BackSpace) {
			finish(null);
			return true;
		}

		const mods = state & Gtk.accelerator_get_default_mod_mask();

		if (MODIFIER_KEYVALS.has(keyval)) {
			// Modifiers only so far: preview them and keep listening
			preview.set_label(Gtk.accelerator_get_label(0, mods) || 'Enter a new shortcut…');
			return true;
		}

		const accel = Gtk.accelerator_name(keyval, mods);
		if (!parseAccelerator(accel)) {
			preview.set_label(`"${Gtk.accelerator_get_label(keyval, mods)}" is not supported, try another`);
			return true;
		}

		finish(accel);
		return true;
	});
	dialog.add_controller(controller);
	dialog.connect('closed', () => finish(undefined));

	dialog.present(parentWindow);
}
