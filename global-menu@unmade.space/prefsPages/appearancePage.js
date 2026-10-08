// Styling options for the menu bar and its popups, plus the Blur My Shell
// integration. Every row binds straight to GSettings and appearance.js
// applies the change live, with no logout.

import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

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
			title: 'Appearance',
			icon_name: 'applications-graphics-symbolic',
		});

		this._buildBlurGroup();
		this._buildPopupGroup();
		this._buildBarGroup();
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
			title: 'Popup Blur',
			description: installed
				? 'Blurs what is behind popup menus, through Blur My Shell. ' +
				  'The panel bar itself is blurred by Blur My Shell\'s own "Panel" setting.'
				: 'Blur My Shell is not installed, so these options will have no effect.',
		});
		this.page.add(group);

		const blurRow = new Adw.SwitchRow({
			title: 'Blur behind popup menus',
			subtitle: 'Dynamic blur: re-rendered as the content behind moves',
		});
		this._settings.bind('blur-popups', blurRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(blurRow);

		const sigmaRow = this._spinRow({
			title: 'Blur intensity',
			subtitle: 'Sigma of the gaussian blur',
			key: 'popup-blur-sigma', lower: 0, upper: 100,
		});
		const brightnessRow = this._spinRow({
			title: 'Brightness',
			subtitle: '1.00 = no dimming of the blurred area',
			key: 'popup-blur-brightness', lower: 0.1, upper: 1.0, step: 0.05, digits: 2,
		});
		for (const row of [sigmaRow, brightnessRow]) {
			this._settings.bind('blur-popups', row, 'sensitive', Gio.SettingsBindFlags.GET);
			group.add(row);
		}
	}

	_buildPopupGroup() {
		const group = new Adw.PreferencesGroup({title: 'Popup Menus'});
		this.page.add(group);

		group.add(this._spinRow({
			title: 'Background opacity',
			subtitle: 'Lower is more translucent. Blur is invisible at 100%.',
			key: 'popup-opacity', lower: 20, upper: 100, step: 5,
		}));
		group.add(this._spinRow({
			title: 'Corner radius',
			subtitle: 'In pixels',
			key: 'popup-corner-radius', lower: 0, upper: 24,
		}));

		const arrowRow = new Adw.SwitchRow({
			title: 'Hide pointer arrow',
			subtitle: 'Menus drop straight down from the bar instead of pointing at the button',
		});
		this._settings.bind('hide-popup-arrow', arrowRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(arrowRow);
	}

	_buildBarGroup() {
		const group = new Adw.PreferencesGroup({title: 'Menu Bar'});
		this.page.add(group);

		group.add(this._spinRow({
			title: 'Button spacing',
			subtitle: 'Horizontal button padding in pixels. The GNOME default is 12.',
			key: 'button-spacing', lower: 0, upper: 16,
		}));
		group.add(this._spinRow({
			title: 'Font size',
			subtitle: 'In points. 0 keeps the theme default.',
			key: 'menu-font-size', lower: 0, upper: 16,
		}));

		const boldRow = new Adw.SwitchRow({
			title: 'Bold app name',
			subtitle: 'Show the focused app\'s name button in bold',
		});
		this._settings.bind('bold-app-name', boldRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(boldRow);

		const appNameRow = new Adw.SwitchRow({
			title: 'Hide App Name',
			subtitle: 'Removes the focused app\'s name button from the bar',
		});
		this._settings.bind('hide-app-name', appNameRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(appNameRow);

		const workspaceRow = new Adw.SwitchRow({
			title: 'Hide workspace indicator',
			subtitle: 'Hides GNOME\'s Activities and workspace pill at the left of the panel',
		});
		this._settings.bind('hide-workspace-indicator', workspaceRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(workspaceRow);
	}
}
