
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';

import * as SystemActions from 'resource:///org/gnome/shell/misc/systemActions.js';
import * as Dialog from 'resource:///org/gnome/shell/ui/dialog.js';
import * as ModalDialog from 'resource:///org/gnome/shell/ui/modalDialog.js';
import {showScreenshotUI} from 'resource:///org/gnome/shell/ui/screenshot.js';

import {MenuBarButton} from './menuBarButton.js';
import {addBarButton} from './panelBar.js';
import {WindowActions, actionLabel} from './windowActions.js';
import {sendShortcutAfterMenu} from './keySynth.js';
import {_, N_} from './i18n.js';

// daemon reports no menus briefly while windows switch
// so wait before concluding an app has none
const SHOW_FALLBACK_DELAY_MS = 400;

const DIRECT_ACTIONS = {
	'open-files': () => openUri(`file://${GLib.get_home_dir()}`),
	'open-settings': () => launchDesktopApp('org.gnome.Settings.desktop', 'gnome-control-center.desktop'),
	'new-folder': () => makeDesktopFolder(),
	'empty-trash': () => emptyTrash(),
	'screenshot-area': () => showScreenshotUI(),
	'lock-screen': () => SystemActions.getDefault().activateLockScreen(),
	'suspend': () => SystemActions.getDefault().activateSuspend(),
	'log-out': () => SystemActions.getDefault().activateLogout(),
	'power-off': () => SystemActions.getDefault().activatePowerOff(),
	'close': () => new WindowActions().doAction('Close'),
	'show-desktop': () => minimizeEverything(),
	'hibernate': () => hibernate(),
};

// the shell has no hibernate call so use login1 like suspend
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

let fileCancellable = null;
let trashDialog = null;

const TRASH_BATCH_SIZE = 100;

function fileOperations() {
	fileCancellable ??= new Gio.Cancellable();
	return fileCancellable;
}

function cancelFileOperations() {
	fileCancellable?.cancel();
	fileCancellable = null;
	trashDialog?.close();
	trashDialog = null;
}

function logFileError(what, e) {
	if (e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
		return;
	console.error(`[global-menu-fallback] could not ${what}: ${e.message}`);
}

function makeDirectory(dir, cancellable, done) {
	dir.make_directory_async(GLib.PRIORITY_DEFAULT, cancellable, (_o, res) => {
		try {
			dir.make_directory_finish(res);
		} catch (e) {
			done(e);
			return;
		}
		done();
	});
}

function makeDesktopFolder() {
	const desktop = Gio.File.new_for_path(
		GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP) ??
		GLib.build_filenamev([GLib.get_home_dir(), 'Desktop']));
	const cancellable = fileOperations();
	makeDirectory(desktop, cancellable, () => makeNumberedFolder(desktop, cancellable, 0));
}

function makeNumberedFolder(desktop, cancellable, n) {
	if (n >= 100)
		return;
	const name = n === 0 ? _('Untitled Folder') : _('Untitled Folder %d').replace('%d', n + 1);
	makeDirectory(desktop.get_child(name), cancellable, e => {
		if (!e)
			return;
		if (e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.EXISTS))
			makeNumberedFolder(desktop, cancellable, n + 1);
		else
			logFileError(`create ${name}`, e);
	});
}

function emptyTrash() {
	if (trashDialog)
		return;
	const dialog = new ModalDialog.ModalDialog();
	trashDialog = dialog;
	dialog.connect('closed', () => {
		if (trashDialog === dialog)
			trashDialog = null;
	});
	dialog.contentLayout.add_child(new Dialog.MessageDialogContent({
		title: _('Empty all items from Trash?'),
		description: _('All items in the Trash will be permanently deleted.'),
	}));
	dialog.setButtons([
		{
			label: _('Cancel'),
			action: () => dialog.close(),
			key: Clutter.KEY_Escape,
		},
		{
			label: _('Empty Trash'),
			action: () => {
				dialog.close();
				deleteTrashItems();
			},
		},
	]);
	dialog.open();
}

// gio has no empty trash call and deleting a top level
// trash item deletes its contents
function deleteTrashItems() {
	const trash = Gio.File.new_for_uri('trash:///');
	const cancellable = fileOperations();
	trash.enumerate_children_async(Gio.FILE_ATTRIBUTE_STANDARD_NAME,
		Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, GLib.PRIORITY_DEFAULT, cancellable,
		(_o, res) => {
			let entries;
			try {
				entries = trash.enumerate_children_finish(res);
			} catch (e) {
				logFileError('read the trash', e);
				return;
			}
			deleteNextBatch(entries, cancellable);
		});
}

function deleteNextBatch(entries, cancellable) {
	entries.next_files_async(TRASH_BATCH_SIZE, GLib.PRIORITY_DEFAULT, cancellable, (_o, res) => {
		let infos = [];
		try {
			infos = entries.next_files_finish(res);
		} catch (e) {
			logFileError('read the trash', e);
		}
		if (infos.length === 0) {
			closeEntries(entries);
			return;
		}
		let pending = infos.length;
		infos.forEach(info => {
			const child = entries.get_child(info);
			child.delete_async(GLib.PRIORITY_DEFAULT, cancellable, (_f, deleted) => {
				try {
					child.delete_finish(deleted);
				} catch (e) {
					logFileError(`delete ${info.get_name()}`, e);
				}
				pending--;
				if (pending === 0)
					deleteNextBatch(entries, cancellable);
			});
		});
	});
}

// not cancellable because a cancelled enumerator
// must still be closed
function closeEntries(entries) {
	entries.close_async(GLib.PRIORITY_DEFAULT, null, (_o, res) => {
		try {
			entries.close_finish(res);
		} catch (e) {
			logFileError('close the trash', e);
		}
	});
}

function minimizeEverything() {
	global.workspace_manager.get_active_workspace().list_windows()
		.filter(w => !w.minimized && !w.is_skip_taskbar())
		.forEach(w => w.minimize());
}

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
	'snap-left': '<Super>Left',
	'snap-right': '<Super>Right',
	'switch-applications': '<Super>Tab',
	'cycle-windows': '<Alt>Escape',
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
	if (accel) {
		sendShortcutAfterMenu(accel);
		return true;
	}

	return false;
}

function windowMenuSpecs() {
	const windowActions = new WindowActions();
	const actions = windowActions.getActions();
	const specs = actions.length === 0
		? [{label: _('No Window'), enabled: false}]
		: actions.map(action => ({
			label: actionLabel(action),
			onActivate: () => windowActions.doAction(action),
		}));
	specs.push(
		{separator: true},
		actionSpec('Snap Window Left', 'snap-left'),
		actionSpec('Snap Window Right', 'snap-right'),
		{separator: true},
		actionSpec('Switch Between Applications', 'switch-applications'),
		actionSpec('Cycle Through Windows', 'cycle-windows'),
		actionSpec('Window Menu', 'window-menu')
	);
	return specs;
}

function actionSpec(label, action) {
	return {label: _(label), accel: ACTION_SHORTCUTS[action], onActivate: () => executeFallbackAction(action)};
}

function toSpecs(items) {
	return items.map(item => {
		if (item.separator)
			return {separator: true};
		const spec = actionSpec(item.label, item.action);
		if (item.requires && !SystemActions.getDefault()[item.requires])
			spec.enabled = false;
		return spec;
	});
}

function appMenuSpecs(appMenuSource) {
	const app = Shell.WindowTracker.get_default().focus_app;
	const specs = appMenuSource ? appMenuSource() : [];
	if (!app)
		return specs;
	if (specs.length > 0)
		specs.push({separator: true});
	if (app.can_open_new_window())
		specs.push({label: _('New Window'), onActivate: () => app.open_new_window(-1)});
	const name = app.get_name();
	specs.push(
		{
			label: _('Hide %s').replace('%s', name),
			onActivate: () => app.get_windows()
				.filter(w => w.can_minimize() && !w.minimized)
				.forEach(w => w.minimize()),
		},
		{separator: true},
		{label: _('Quit %s').replace('%s', name), onActivate: () => app.request_quit()}
	);
	return specs;
}

const MENU_DATA = [
	{
		label: N_('Desktop'),
		appName: true,
		items: [],
	},
	{
		label: N_('File'),
		items: [
			{label: N_('New Folder on Desktop'), action: 'new-folder'},
			{label: N_('New Tab'), action: 'new-tab'},
			{label: N_('Open'), action: 'virtual-open'},
			{separator: true},
			{label: N_('Properties'), action: 'properties'},
			{separator: true},
			{label: N_('Show Desktop'), action: 'show-desktop'},
			{separator: true},
			{label: N_('Close Window'), action: 'close'},
		],
	},
	{
		label: N_('Edit'),
		items: [
			{label: N_('Undo'), action: 'undo'},
			{label: N_('Redo'), action: 'redo'},
			{separator: true},
			{label: N_('Cut'), action: 'cut'},
			{label: N_('Copy'), action: 'copy'},
			{label: N_('Paste'), action: 'paste'},
			{label: N_('Delete'), action: 'delete-item'},
			{separator: true},
			{label: N_('Select All'), action: 'select-all'},
			{separator: true},
			{label: N_('Take Screenshot'), action: 'screenshot-full'},
			{label: N_('Screenshot of Window'), action: 'screenshot-window'},
			{label: N_('Screenshot of Area'), action: 'screenshot-area'},
		],
	},
	{
		label: N_('Go'),
		items: [
			{label: N_('Back'), action: 'go-back'},
			{label: N_('Forward'), action: 'go-forward'},
			{separator: true},
			{label: N_('Next Workspace'), action: 'next-workspace'},
			{label: N_('Previous Workspace'), action: 'previous-workspace'},
			{label: N_('First Workspace'), action: 'first-workspace'},
		],
	},
	{
		label: N_('Window'),
		windowActions: true,
	},
	{
		label: N_('System'),
		live: true,
		items: [
			{label: N_('Show Applications'), action: 'show-applications'},
			{label: N_('Show Notifications'), action: 'show-notifications'},
			{separator: true},
			{label: N_('Open Files'), action: 'open-files'},
			{label: N_('Settings'), action: 'open-settings'},
			{separator: true},
			{label: N_('Empty Trash…'), action: 'empty-trash'},
			{separator: true},
			{label: N_('Lock Screen'), action: 'lock-screen', requires: 'canLockScreen'},
			{label: N_('Suspend'), action: 'suspend', requires: 'canSuspend'},
			{label: N_('Hibernate'), action: 'hibernate'},
			{separator: true},
			{label: N_('Log Out'), action: 'log-out', requires: 'canLogout'},
			{label: N_('Power Off / Restart'), action: 'power-off', requires: 'canPowerOff'},
		],
	},
];

export class FallbackMenu {
	constructor(uuid) {
		this._buttons = [];
		this._appButton = null;
		this._showTimeoutId = 0;
		this._blank = false;
		this._appMenuSource = null;

		MENU_DATA.forEach((entry, index) => {
			const btn = new MenuBarButton(_(entry.label), entry.appName ? {appName: true} : {});
			if (entry.appName)
				btn.setItems(() => appMenuSpecs(this._appMenuSource));
			else if (entry.windowActions)
				btn.setItems(windowMenuSpecs);
			else if (entry.live)
				btn.setItems(() => toSpecs(entry.items));
			else
				btn.setItems(toSpecs(entry.items));
			addBarButton(`${uuid}-fallback-${index}`, btn, index);
			this._buttons.push(btn);
			if (entry.appName)
				this._appButton = btn;
		});

		this.updateAppName();
	}

	updateAppName() {
		const app = Shell.WindowTracker.get_default().focus_app;
		this._appButton?.setLabel(app?.get_name() ?? _('Desktop'));
	}

	setAppItems(source) {
		this._appMenuSource = source;
	}

	setBlank(blank) {
		if (blank === this._blank)
			return;
		this._blank = blank;
		this._cancelPendingShow();
		if (blank)
			this._buttons.forEach(btn => btn.hide());
		else
			this._appButton?.show();
	}

	setNativeMenusPresent(present) {
		if (this._blank)
			return;
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
		cancelFileOperations();
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
