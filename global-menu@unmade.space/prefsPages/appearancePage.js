// Styling options for the menu bar and its popups, plus the Blur My Shell
// integration. Every row binds straight to GSettings and appearance.js
// applies the change live, with no logout.

import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import {_} from '../i18n.js';

const BMS_UUID = 'blur-my-shell@aunetx';

function blurMyShellInstalled() {
	const dirs = [
		GLib.build_filenamev([GLib.get_user_data_dir(), 'gnome-shell', 'extensions', BMS_UUID]),
		GLib.build_filenamev(['/usr', 'share', 'gnome-shell', 'extensions', BMS_UUID]),
	];
	return dirs.some(path => GLib.file_test(path, GLib.FileTest.IS_DIR));
}

export class AppearancePage {
	constructor({settings}) {
		this._settings = settings;

		this.page = new Adw.PreferencesPage({
			title: _('Appearance'),
			icon_name: 'applications-graphics-symbolic',
		});

		this._buildBlurGroup();
		this._buildPopupGroup();
		this._buildShortcutGroup();
		this._buildBarGroup();
	}

	/**
	 * A combo row bound to a string key with a fixed set of choices.
	 *
	 * @param {object} params
	 * @param {string} params.title - row title
	 * @param {string} params.key - settings key
	 * @param {Array<Array<string>>} params.choices - [value, label] pairs
	 */
	_choiceRow({title, key, choices}) {
		const row = new Adw.ComboRow({
			title,
			model: Gtk.StringList.new(choices.map(([, label]) => label)),
		});
		const values = choices.map(([value]) => value);
		const sync = () => {
			row.selected = Math.max(values.indexOf(this._settings.get_string(key)), 0);
		};
		sync();
		const id = this._settings.connect(`changed::${key}`, sync);
		row.connect('destroy', () => this._settings.disconnect(id));
		row.connect('notify::selected', () => {
			const value = values[row.selected];
			if (value !== undefined && value !== this._settings.get_string(key))
				this._settings.set_string(key, value);
		});
		return row;
	}

	_buildShortcutGroup() {
		const group = new Adw.PreferencesGroup({title: _('Keyboard Shortcuts')});
		this.page.add(group);

		group.add(this._choiceRow({
			title: _('Show shortcuts'),
			key: 'shortcut-labels',
			choices: [
				['always', _('Always')],
				['hold', _('While holding a key')],
				['never', _('Never')],
			],
		}));

		const keyRow = this._choiceRow({
			title: _('Key to hold'),
			key: 'shortcut-hold-key',
			choices: [
				['alt', _('Alt')],
				['ctrl', _('Ctrl')],
				['shift', _('Shift')],
				['super', _('Super')],
			],
		});
		const syncKeyRow = () => {
			keyRow.sensitive = this._settings.get_string('shortcut-labels') === 'hold';
		};
		syncKeyRow();
		const id = this._settings.connect('changed::shortcut-labels', syncKeyRow);
		keyRow.connect('destroy', () => this._settings.disconnect(id));
		group.add(keyRow);
	}

	_spinRow({title, subtitle, key, lower, upper, step = 1, digits = 0}) {
		const row = new Adw.SpinRow({
			title,
			subtitle: subtitle ?? null,
			digits,
			adjustment: new Gtk.Adjustment({
				lower,
				upper,
				step_increment: step,
				page_increment: step * 5,
			}),
		});
		this._settings.bind(key, row, 'value', Gio.SettingsBindFlags.DEFAULT);
		return row;
	}

	_buildBlurGroup() {
		const installed = blurMyShellInstalled();
		const group = new Adw.PreferencesGroup({
			title: _('Popup Blur'),
			description: installed
				? _('Blurs what is behind popup menus, through Blur My Shell. The panel bar itself is blurred by Blur My Shell\'s own "Panel" setting.')
				: _('Blur My Shell is not installed, so these options will have no effect.'),
		});
		this.page.add(group);

		const blurRow = new Adw.SwitchRow({
			title: _('Blur behind popup menus'),
			subtitle: _('Dynamic blur: re-rendered as the content behind moves'),
		});
		this._settings.bind('blur-popups', blurRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(blurRow);

		const sigmaRow = this._spinRow({
			title: _('Blur intensity'),
			subtitle: _('Sigma of the gaussian blur'),
			key: 'popup-blur-sigma', lower: 0, upper: 100,
		});
		const brightnessRow = this._spinRow({
			title: _('Brightness'),
			subtitle: _('1.00 = no dimming of the blurred area'),
			key: 'popup-blur-brightness', lower: 0.1, upper: 1.0, step: 0.05, digits: 2,
		});
		for (const row of [sigmaRow, brightnessRow]) {
			this._settings.bind('blur-popups', row, 'sensitive', Gio.SettingsBindFlags.GET);
			group.add(row);
		}
	}

	_buildPopupGroup() {
		const group = new Adw.PreferencesGroup({title: _('Popup Menus')});
		this.page.add(group);

		group.add(this._spinRow({
			title: _('Background opacity'),
			subtitle: _('Lower is more translucent. Blur is invisible at 100%.'),
			key: 'popup-opacity', lower: 20, upper: 100, step: 5,
		}));
		group.add(this._spinRow({
			title: _('Corner radius'),
			subtitle: _('In pixels'),
			key: 'popup-corner-radius', lower: 0, upper: 24,
		}));

		const arrowRow = new Adw.SwitchRow({
			title: _('Hide pointer arrow'),
			subtitle: _('Menus drop straight down from the bar instead of pointing at the button'),
		});
		this._settings.bind('hide-popup-arrow', arrowRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(arrowRow);
	}

	_buildBarGroup() {
		const group = new Adw.PreferencesGroup({title: _('Menu Bar')});
		this.page.add(group);

		group.add(this._spinRow({
			title: _('Button spacing'),
			subtitle: _('Horizontal button padding in pixels. The GNOME default is 12.'),
			key: 'button-spacing', lower: 0, upper: 16,
		}));
		group.add(this._spinRow({
			title: _('Font size'),
			subtitle: _('In points. 0 keeps the theme default.'),
			key: 'menu-font-size', lower: 0, upper: 16,
		}));

		const boldRow = new Adw.SwitchRow({
			title: _('Bold app name'),
			subtitle: _('Show the focused app\'s name button in bold'),
		});
		this._settings.bind('bold-app-name', boldRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(boldRow);

		const appNameRow = new Adw.SwitchRow({
			title: _('Hide App Name'),
			subtitle: _('Removes the focused app\'s name button from the bar'),
		});
		this._settings.bind('hide-app-name', appNameRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(appNameRow);

		const workspaceRow = new Adw.SwitchRow({
			title: _('Hide workspace indicator'),
			subtitle: _('Hides GNOME\'s Activities and workspace pill at the left of the panel'),
		});
		this._settings.bind('hide-workspace-indicator', workspaceRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(workspaceRow);
	}
}
