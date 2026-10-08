import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

import {ShortcutStore} from './shortcutStore.js';
import {ApplicationsPage} from './prefsPages/applicationsPage.js';
import {AppearancePage} from './prefsPages/appearancePage.js';
import {_} from './i18n.js';

export default class GlobalMenuPreferences extends ExtensionPreferences {
	fillPreferencesWindow(window) {
		const settings = this.getSettings();

		const page = new Adw.PreferencesPage({title: _('General'), icon_name: 'preferences-system-symbolic'});
		const group = new Adw.PreferencesGroup({title: _('Menus')});
		page.add(group);

		const fallbackRow = new Adw.SwitchRow({
			title: _('Fallback menu'),
			subtitle: _('Show a generic app name, File, Edit, Go and Window menu for apps that have none of their own'),
		});
		settings.bind('enable-fallback-menu', fallbackRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(fallbackRow);

		const shortcutRow = new Adw.SwitchRow({
			title: _('Shortcut menus'),
			subtitle: _('For supported apps without a menu of their own, show curated menus that send the app\'s real keyboard shortcuts'),
		});
		settings.bind('shortcut-menus-enabled', shortcutRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		group.add(shortcutRow);

		const devGroup = new Adw.PreferencesGroup({title: _('Development')});
		page.add(devGroup);

		const debugRow = new Adw.SwitchRow({
			title: _('Debug shortcut menus'),
			subtitle: _('Log shortcut-menu resolution and key synthesis to the journal'),
		});
		settings.bind('debug-shortcut-menus', debugRow, 'active', Gio.SettingsBindFlags.DEFAULT);
		devGroup.add(debugRow);

		window.add(page);
		window.add(new AppearancePage({settings}).page);

		const userDir = Gio.File.new_for_path(GLib.build_filenamev(
			[GLib.get_user_config_dir(), 'global-menu', 'shortcuts']));
		const store = new ShortcutStore(this.dir.get_child('shortcuts'), userDir);
		const applicationsPage = new ApplicationsPage({
			window,
			settings,
			store,
			userAppsDir: userDir.get_child('apps'),
		});
		window.add(applicationsPage.page);
	}
}
