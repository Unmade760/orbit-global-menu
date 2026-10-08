// Generic menu for applications that export no menu of their own and have no
// curated shortcut mapping either. Adapted from Global Menu for GNOME
// (globalmenu@ShiroOSL.github.io).
//
// Items act through window operations, the shell's own system actions, or a
// keyboard shortcut synthesized into the focused app. Nothing here shells out.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';

import * as SystemActions from 'resource:///org/gnome/shell/misc/systemActions.js';

import {MenuBarButton} from './menuBarButton.js';
import {addBarButton} from './panelBar.js';
import {WindowActions} from './windowActions.js';
import {sendShortcut} from './keySynth.js';

// The daemon briefly reports no menus while windows are switching, so wait
// this long before concluding an app really has none.
const SHOW_FALLBACK_DELAY_MS = 400;

// Actions with a real API behind them. Everything else in the menu is a
// keystroke, which is a guess; these are not.
const DIRECT_ACTIONS = {
	'open-files': () => openUri(`file://${GLib.get_home_dir()}`),
	'open-settings': () => launchDesktopApp('org.gnome.Settings.desktop', 'gnome-control-center.desktop'),
	'new-folder': () => makeDesktopFolder(),
	'empty-trash': () => emptyTrash(),
	'lock-screen': () => SystemActions.getDefault().activateLockScreen(),
	'suspend': () => SystemActions.getDefault().activateSuspend(),
	'log-out': () => SystemActions.getDefault().activateLogout(),
	'power-off': () => SystemActions.getDefault().activatePowerOff(),
	'close': () => new WindowActions().doAction('Close'),
	'show-desktop': () => minimizeEverything(),
	'hibernate': () => hibernate(),
};

// login1 is where the shell's own suspend ends up; it has no hibernate call
// of its own, so this is the same route with a different method name.
function hibernate() {
	Gio.DBus.system.call('org.freedesktop.login1', '/org/freedesktop/login1',
		'org.freedesktop.login1.Manager', 'Hibernate',
		new GLib.Variant('(b)', [true]), null, Gio.DBusCallFlags.NONE, -1, null,
		(bus, res) => {
			try {
				bus.call_finish(res);
			} catch (e) {
				console.error(`[global-menu-fallback] hibernate failed: ${e.message}`);
			}
		});
}

function openUri(uri) {
	Gio.AppInfo.launch_default_for_uri_async(uri, null, null, (_o, res) => {
		try {
			Gio.AppInfo.launch_default_for_uri_finish(res);
		} catch (e) {
			console.error(`[global-menu-fallback] could not open ${uri}: ${e.message}`);
		}
	});
}

function launchDesktopApp(id, fallbackId) {
	const system = Shell.AppSystem.get_default();
	const app = system.lookup_app(id) ?? system.lookup_app(fallbackId);
	if (app)
		app.activate();
	else
		console.warn(`[global-menu-fallback] ${id} is not installed`);
}

// A folder on the desktop, numbered if the plain name is taken, the way a
// file manager would do it.
function makeDesktopFolder() {
	const desktop = Gio.File.new_for_path(
		GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP) ??
		GLib.build_filenamev([GLib.get_home_dir(), 'Desktop']));
	for (let n = 0; n < 100; n++) {
		const name = n === 0 ? 'Untitled Folder' : `Untitled Folder ${n + 1}`;
		try {
			desktop.get_child(name).make_directory_with_parents(null);
			return;
		} catch (e) {
			if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.EXISTS)) {
				console.error(`[global-menu-fallback] could not create ${name}: ${e.message}`);
				return;
			}
		}
	}
}

// Gio has no empty-the-trash call, so the entries are deleted one by one.
// trash:/// hands back the top-level items only, and deleting one takes its
// contents with it.
function emptyTrash() {
	const trash = Gio.File.new_for_uri('trash:///');
	trash.enumerate_children_async(Gio.FILE_ATTRIBUTE_STANDARD_NAME,
		Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, GLib.PRIORITY_DEFAULT, null,
		(_o, res) => {
			let entries;
			try {
				entries = trash.enumerate_children_finish(res);
			} catch (e) {
				console.error(`[global-menu-fallback] could not read the trash: ${e.message}`);
				return;
			}
			let info;
			while ((info = entries.next_file(null)) !== null) {
				try {
					entries.get_child(info).delete(null);
				} catch (e) {
					console.error(`[global-menu-fallback] could not delete ${info.get_name()}: ${e.message}`);
				}
			}
			entries.close(null);
		});
}

function minimizeEverything() {
	global.workspace_manager.get_active_workspace().list_windows()
		.filter(w => !w.minimized && !w.is_skip_taskbar())
		.forEach(w => w.minimize());
}

// Actions sent to the focused app as keystrokes. These are the stock GNOME
// and application defaults, so a user who has rebound one gets a stale guess.
// There is no way to ask an app what its shortcut for Copy is.
const ACTION_SHORTCUTS = {
	'copy': '<Ctrl>C',
	'paste': '<Ctrl>V',
	'cut': '<Ctrl>X',
	'undo': '<Ctrl>Z',
	'redo': '<Ctrl>Y',
	'select-all': '<Ctrl>A',
	'new-tab': '<Ctrl>T',
	'go-back': '<Alt>Left',
	'go-forward': '<Alt>Right',
	'delete-item': 'Delete',
	'virtual-open': 'Return',
	'properties': '<Alt>Return',
	'screenshot-full': 'Print',
	'screenshot-window': '<Alt>Print',
	'screenshot-area': '<Shift>Print',
	'snap-left': '<Super>Left',
	'snap-right': '<Super>Right',
	'switch-windows': '<Super>Tab',
	'cycle-windows': '<Alt>Escape',
	'cycle-app-windows': '<Super>`',
	'window-menu': '<Alt>space',
	'next-workspace': '<Super>Page_Down',
	'previous-workspace': '<Super>Page_Up',
	'first-workspace': '<Super>Home',
	'show-applications': '<Super>A',
	'show-notifications': '<Super>V',
};

function executeFallbackAction(action) {
	const direct = DIRECT_ACTIONS[action];
	if (direct) {
		try {
			direct();
		} catch (e) {
			console.error(`[global-menu-fallback] ${action} failed: ${e.message}`);
		}
		return true;
	}

	const accel = ACTION_SHORTCUTS[action];
	if (accel)
		return sendShortcut(accel);

	return false;
}

// Mirrors gnome-shell's own window menu, so it is rebuilt on every open from
// the live window state, plus a static block of window-switching and tiling
// shortcuts that do not depend on the focused window.
function windowMenuSpecs() {
	const windowActions = new WindowActions();
	const actions = windowActions.getActions();
	const specs = actions.length === 0
		? [{label: 'No Window', enabled: false}]
		: actions.map(action => ({
			label: action,
			onActivate: () => windowActions.doAction(action),
		}));
	specs.push(
		{separator: true},
		actionSpec('Snap Window Left', 'snap-left'),
		actionSpec('Snap Window Right', 'snap-right'),
		{separator: true},
		actionSpec('Switch Between Windows', 'switch-windows'),
		actionSpec('Cycle Through Windows', 'cycle-windows'),
		actionSpec('Switch Windows of Same App', 'cycle-app-windows'),
		actionSpec('Window Menu', 'window-menu')
	);
	return specs;
}

function actionSpec(label, action) {
	return {label, accel: ACTION_SHORTCUTS[action], onActivate: () => executeFallbackAction(action)};
}

function toSpecs(items) {
	return items.map(item => item.separator ? {separator: true} : actionSpec(item.label, item.action));
}

const MENU_DATA = [
	{
		// Holds nothing until the app-name menu is built from the focused
		// app's own actions. An empty menu does not open.
		label: 'Desktop',
		appName: true,
		items: [],
	},
	{
		label: 'File',
		items: [
			{label: 'New Folder on Desktop', action: 'new-folder'},
			{label: 'New Tab', action: 'new-tab'},
			{label: 'Open', action: 'virtual-open'},
			{separator: true},
			{label: 'Properties', action: 'properties'},
			{separator: true},
			{label: 'Show Desktop', action: 'show-desktop'},
			{separator: true},
			{label: 'Close Window', action: 'close'},
		],
	},
	{
		label: 'Edit',
		items: [
			{label: 'Undo', action: 'undo'},
			{label: 'Redo', action: 'redo'},
			{separator: true},
			{label: 'Cut', action: 'cut'},
			{label: 'Copy', action: 'copy'},
			{label: 'Paste', action: 'paste'},
			{label: 'Delete', action: 'delete-item'},
			{separator: true},
			{label: 'Select All', action: 'select-all'},
			{separator: true},
			{label: 'Take Screenshot', action: 'screenshot-full'},
			{label: 'Screenshot of Window', action: 'screenshot-window'},
			{label: 'Screenshot of Area', action: 'screenshot-area'},
		],
	},
	{
		label: 'Go',
		items: [
			{label: 'Back', action: 'go-back'},
			{label: 'Forward', action: 'go-forward'},
			{separator: true},
			{label: 'Next Workspace', action: 'next-workspace'},
			{label: 'Previous Workspace', action: 'previous-workspace'},
			{label: 'First Workspace', action: 'first-workspace'},
		],
	},
	{
		label: 'Window',
		windowActions: true,
	},
	{
		label: 'System',
		items: [
			{label: 'Show Applications', action: 'show-applications'},
			{label: 'Show Notifications', action: 'show-notifications'},
			{separator: true},
			{label: 'Open Files', action: 'open-files'},
			{label: 'Settings', action: 'open-settings'},
			{separator: true},
			{label: 'Empty Trash', action: 'empty-trash'},
			{separator: true},
			{label: 'Lock Screen', action: 'lock-screen'},
			{label: 'Suspend', action: 'suspend'},
			{label: 'Hibernate', action: 'hibernate'},
			{separator: true},
			{label: 'Log Out', action: 'log-out'},
			{label: 'Power Off / Restart', action: 'power-off'},
		],
	},
];

/**
 * The first button always shows the focused app's name. The generic ones are
 * hidden by MenuBar whenever the app has a menu of its own.
 */
export class FallbackMenu {
	constructor(uuid) {
		this._buttons = [];
		this._appButton = null;
		this._showTimeoutId = 0;

		MENU_DATA.forEach((entry, index) => {
			const btn = new MenuBarButton(entry.label, entry.appName ? {appName: true} : {});
			btn.setItems(entry.windowActions ? windowMenuSpecs : toSpecs(entry.items));
			// MENU_DATA[0] is the app name, so the index doubles as the rank
			addBarButton(`${uuid}-fallback-${index}`, btn, index);
			this._buttons.push(btn);
			if (entry.appName)
				this._appButton = btn;
		});

		this.updateAppName();
	}

	updateAppName() {
		const app = Shell.WindowTracker.get_default().focus_app;
		this._appButton?.setLabel(app?.get_name() ?? 'Desktop');
	}

	setNativeMenusPresent(present) {
		this._cancelPendingShow();
		if (present) {
			this._genericButtons().forEach(btn => btn.hide());
			return;
		}
		this._showTimeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, SHOW_FALLBACK_DELAY_MS, () => {
			this._genericButtons().forEach(btn => btn.show());
			this._showTimeoutId = 0;
			return GLib.SOURCE_REMOVE;
		});
	}

	closeAllMenus() {
		this._buttons.forEach(btn => btn.menu.close());
	}

	destroy() {
		this._cancelPendingShow();
		this._buttons.forEach(btn => btn.destroy());
		this._buttons = [];
		this._appButton = null;
	}

	_genericButtons() {
		return this._buttons.filter(btn => btn !== this._appButton);
	}

	_cancelPendingShow() {
		if (!this._showTimeoutId)
			return;
		GLib.source_remove(this._showTimeoutId);
		this._showTimeoutId = 0;
	}
}
