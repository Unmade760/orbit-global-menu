// Global Menu
//
// Menus are rendered as shell PopupMenus in the panel. The menu data comes
// from three sources, in priority order: the menu the app exports itself,
// delivered as a JSON tree by the global-menu daemon (nativeMenu.js); a
// curated per-app mapping whose items fire the app's real keyboard shortcuts
// (shortcutMenu.js); or a generic window and system menu (fallbackMenu.js).

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {createManager as createAppearanceManager} from './appearance.js';
import {DaemonManager} from './daemon.js';
import {FallbackMenu} from './fallbackMenu.js';
import {NativeMenu} from './nativeMenu.js';
import {ShortcutMenu} from './shortcutMenu.js';
import {ShortcutStore} from './shortcutStore.js';
import {WindowActions, cancelPendingActions} from './windowActions.js';
import * as KeySynth from './keySynth.js';

const BUS_NAME = 'space.unmade.GlobalMenu';
const BUS_PATH = '/space/unmade/GlobalMenu';

// Mutter refuses transient-for loops; this only bounds the walk up from a
// dialog to the window that holds the menu
const MAX_TRANSIENT_STEPS = 8;

// Menu trees are large and the daemon takes a moment to answer, so the last
// few are kept per application to make alt-tabbing back instant.
class MenuTreeCache {
	constructor(size = 10) {
		this._size = size;
		this._lru = [];
		this._entries = new Map();
		this._lastQueried = '';
	}

	get(appId) {
		this._lastQueried = appId;
		return this._entries.get(appId);
	}

	/**
	 * Store a tree that arrived from the daemon. It answers the most
	 * recent get(), since a window switch always queries the cache before it
	 * asks the daemon.
	 *
	 * @param {object[]} items - the tree's top-level nodes
	 */
	storeForLastQuery(items) {
		const key = this._lastQueried;
		if (this._entries.has(key))
			this._lru.splice(this._lru.indexOf(key), 1);
		this._lru.push(key);
		this._entries.set(key, items);

		if (this._lru.length > this._size)
			this._entries.delete(this._lru.shift());
	}
}

/** Decides which of the three menu sources is on screen. */
class MenuBar {
	constructor(fallbackMenu, uuid, store, settings) {
		this._winTracker = Shell.WindowTracker.get_default();
		this._fallback = fallbackMenu ?? null;
		this._store = store;
		this._settings = settings;
		this._shortcutMapping = null;
		this._cache = new MenuTreeCache();

		this._proxy = new DaemonProxy({
			onMenuTree: items => {
				// A window without a menubar gets an empty tree. Cached under
				// the app id, it would stand in for the app's own menu the
				// next time the app is focused.
				if (items.length > 0)
					this._cache.storeForLastQuery(items);
				this.setMenuTree(items);
			},
			// A daemon that started after enable(), or restarted after a
			// crash, has not been told which window is focused
			onDaemonAppeared: () => this.refresh(),
		});
		this._native = new NativeMenu(this._proxy, uuid, source => this._fallback?.setAppItems(source));
		this._shortcuts = new ShortcutMenu(uuid);

		this._shellHandlers = [
			[global.display, global.display.connect('notify::focus-window', () => this.refresh())],
			[Main.overview, Main.overview.connect('showing', () => this._closeAllMenus())],
			// At shell shutdown the extension stays enabled while the shell
			// destroys the panel, our buttons with it, and windows are still
			// closing. This handler runs before the panel's children go.
			[Main.panel, Main.panel.connect('destroy', () => this._disconnectInputs())],
		];

		// Enabling starts with a window already focused, and so does every
		// unlock, since the extension is disabled on the lock screen
		this.refresh();
	}

	setFallback(fallbackMenu) {
		this._fallback = fallbackMenu;
		this._fallback?.setAppItems(this._native.appMenuSource());
		this._fallback?.setNativeMenusPresent(this._native.hasMenus() || this._shortcuts.hasMenus());
	}

	/**
	 * Native tree beats shortcut mapping beats generic fallback.
	 *
	 * @param {object[]} items - the daemon's tree, empty when the app has none
	 */
	setMenuTree(items) {
		this._native.setItems(items);
		if (items.length > 0) {
			this._shortcuts.setMapping(null);
			this._fallback?.setNativeMenusPresent(true);
		} else if (this._shortcutMapping) {
			this._shortcuts.setMapping(this._shortcutMapping);
			this._fallback?.setNativeMenusPresent(true);
		} else {
			this._shortcuts.setMapping(null);
			this._fallback?.setNativeMenusPresent(false);
		}
	}

	/** Rebuild for the currently focused window. */
	refresh() {
		this._fallback?.updateAppName();
		this._shortcutMapping = null;

		const focusApp = this._winTracker.focus_app;
		const win = focusApp ? this._menuWindow(focusApp) : null;
		if (!win) {
			this._showNothing();
			return;
		}

		const candidates = this._shortcutCandidates(focusApp, win);
		const mapping = this._store.resolveMapping(candidates);
		this._shortcutMapping = mapping && this._shortcutsEnabledForApp(mapping) ? mapping : null;
		if (this._settings.get_boolean('debug-shortcut-menus')) {
			console.log(`[global-menu-shortcuts] resolution: candidates=[${candidates}] ` +
				`matched ${this._shortcutMapping?.app ?? 'nothing'}`);
		}

		const appId = focusApp.get_id();
		const cached = this._cache.get(appId);
		if (cached) {
			// The buttons are not torn down first: NativeMenu.setItems is a
			// no-op when the cached tree is the one already on the panel
			this.setMenuTree(cached);
		} else if (this._shortcutMapping) {
			// Whether the app has a menu of its own is still unknown, so show
			// the shortcut menu now and let a native tree displace it
			this._native.clear();
			this._shortcuts.setMapping(this._shortcutMapping);
			this._fallback?.setNativeMenusPresent(true);
		} else {
			// Assume no native menu until the daemon says otherwise. Its
			// answer cancels the fallback's debounce timer.
			this._showNothing();
		}

		this._proxy.WindowSwitched(this._windowData(win));
	}

	destroy() {
		this._disconnectInputs();
		this._shortcuts.destroy();
		this._shortcuts = null;
		this._native.destroy();
		this._native = null;
		this._proxy = null;
		this._shortcutMapping = null;
		this._store = null;
		this._settings = null;
		this._winTracker = null;
	}

	// Everything outside that calls into the menus. Runs from destroy() and
	// from the panel's destroy, so a second run must do nothing.
	_disconnectInputs() {
		for (const [source, id] of this._shellHandlers)
			source.disconnect(id);
		this._shellHandlers = [];
		this._proxy.destroy();
	}

	_closeAllMenus() {
		this._native.closeAllMenus();
		this._shortcuts.closeAllMenus();
		this._fallback?.closeAllMenus();
	}

	_showNothing() {
		this._native.clear();
		this._shortcuts.setMapping(null);
		this._fallback?.setNativeMenusPresent(false);
	}

	// A dialog (file chooser, About) has none of the gtk_* properties that
	// lead the daemon to a menu, so the menu comes from the window it is
	// transient for. Attached dialogs are transient too. A parent that
	// belongs to another app is not used: its menu is not the focused app's.
	_menuWindow(app) {
		let win = global.display.focus_window;
		for (let step = 0; win && step < MAX_TRANSIENT_STEPS; step++) {
			const parent = win.get_transient_for();
			if (!parent || this._winTracker.get_window_app(parent) !== app)
				break;
			win = parent;
		}
		return win;
	}

	_shortcutsEnabledForApp(mapping) {
		return this._settings.get_boolean('shortcut-menus-enabled') &&
			!this._settings.get_strv('shortcut-disabled-apps').includes(mapping.app);
	}

	_shortcutCandidates(focusApp, win) {
		const candidates = new Set();
		const add = value => {
			if (value)
				candidates.add(String(value).toLowerCase());
		};
		const appId = focusApp.get_id();
		add(appId);
		if (appId?.endsWith('.desktop'))
			add(appId.slice(0, -'.desktop'.length));
		add(win.get_wm_class());
		add(win.get_wm_class_instance());
		add(focusApp.get_name());
		return [...candidates];
	}

	// What the daemon needs to find the window's exported menu. The X11 id is
	// read from the description, which mutter starts with "0x<id> (" for an
	// X11 window; a Wayland window has none, and its description holds only
	// a counter and the title. The gtk_* properties are only set on windows
	// that export a GMenu.
	_windowData(win) {
		const data = {xid: '0'};
		if (win.get_client_type() === Meta.WindowClientType.X11) {
			const xid = win.get_description()?.match(/^0x[0-9a-f]+/);
			if (xid)
				data.xid = String(parseInt(xid[0]));
		}

		const gtkProps = [
			'gtk_unique_bus_name',
			'gtk_application_id',
			'gtk_application_object_path',
			'gtk_window_object_path',
			'gtk_app_menu_object_path',
			'gtk_menubar_object_path',
		];
		for (const prop of gtkProps) {
			if (win[prop] != null)
				data[prop] = win[prop];
		}
		// The daemon names the app in its log; Bamf is gone on Wayland
		const appName = this._winTracker.get_window_app(win)?.get_name();
		if (appName)
			data.appName = appName;
		return data;
	}
}

const ifaceXml = `
<node>
  <interface name="space.unmade.GlobalMenu">
	<method name="WindowSwitched">
	  <arg name="win_data" type="a{ss}" direction="in"/>
	</method>

	<signal name="SendMenuTree">
	  <arg name="tree_json" type="s"/>
	</signal>
	<method name="ActivateMenuItem">
	  <arg name="item_path" type="s" direction="in"/>
	</method>
	<method name="RequestMenuTree"/>

	<signal name="RequestWindowActionsSignal"/>
	<method name="ListWindowActions">
	  <arg name="actions" type="as" direction="in"/>
	</method>
	<signal name="ActivateWindowActionSignal">
	  <arg name="action" type="s"/>
	</signal>
  </interface>
</node>`;

const MenuProxy = Gio.DBusProxy.makeProxyWrapper(ifaceXml);

// What a call gets back when the daemon is not running, or exits before it
// answers. daemon.js reports a missing or crashed daemon once.
const DAEMON_GONE_ERRORS = [
	Gio.DBusError.SERVICE_UNKNOWN,
	Gio.DBusError.NAME_HAS_NO_OWNER,
	Gio.DBusError.NO_REPLY,
];

class DaemonProxy {
	/**
	 * @param {object} callbacks
	 * @param {Function} callbacks.onMenuTree - receives every tree the daemon sends
	 * @param {Function} callbacks.onDaemonAppeared - the daemon took its bus name
	 */
	constructor({onMenuTree, onDaemonAppeared}) {
		this._onMenuTree = onMenuTree;
		this._onDaemonAppeared = onDaemonAppeared;
		this._signalIds = [];
		this._ownerChangedId = 0;
		this._currentWindow = null;
		this._cancellable = new Gio.Cancellable();
		this._proxy = new MenuProxy(Gio.DBus.session, BUS_NAME, BUS_PATH,
			(proxy, error) => this._onProxyReady(error), this._cancellable);
	}

	WindowSwitched(windowData) {
		this._call('WindowSwitched', windowData);
	}

	ActivateMenuItem(itemPath) {
		this._call('ActivateMenuItem', itemPath);
	}

	RequestMenuTree() {
		this._call('RequestMenuTree');
	}

	// MenuBar may call this twice, see _disconnectInputs()
	destroy() {
		this._cancellable.cancel();
		for (const id of this._signalIds)
			this._proxy.disconnectSignal(id);
		this._signalIds = [];
		if (this._ownerChangedId)
			this._proxy.disconnect(this._ownerChangedId);
		this._ownerChangedId = 0;
		this._proxy = null;
		this._currentWindow = null;
	}

	// Skips a daemon that is not on the bus. The callback is not optional:
	// gjs logs every failed call made without one.
	_call(method, ...args) {
		if (!this._proxy.g_name_owner)
			return;
		this._proxy[`${method}Remote`](...args, (result, error) => {
			if (error && !DAEMON_GONE_ERRORS.some(code => error.matches(Gio.DBusError, code)))
				console.warn(`[global-menu] ${method} failed: ${error.message}`);
		});
	}

	_onProxyReady(error) {
		// The wrapper constructor is async, and destroy() cancels it. A proxy
		// that comes up afterwards would leave signals nobody disconnects.
		if (this._cancellable.is_cancelled())
			return;
		// A missing daemon is not one of these errors: the proxy comes up
		// without a name owner
		if (error) {
			console.warn(`[global-menu] no proxy for ${BUS_NAME}: ${error.message}`);
			return;
		}

		this._signalIds.push(
			this._proxy.connectSignal('SendMenuTree', this._onSendMenuTree.bind(this)),
			this._proxy.connectSignal('RequestWindowActionsSignal', this._onRequestWindowActions.bind(this)),
			this._proxy.connectSignal('ActivateWindowActionSignal', this._onActivateWindowAction.bind(this))
		);
		// The daemon that enable() spawned, and every restart. One that
		// owned the name before this point is never notified, so it is
		// announced here.
		this._ownerChangedId = this._proxy.connect('notify::g-name-owner', () => {
			if (this._proxy.g_name_owner)
				this._onDaemonAppeared();
		});
		if (this._proxy.g_name_owner)
			this._onDaemonAppeared();
	}

	_onSendMenuTree(proxy, nameOwner, args) {
		let items = [];
		try {
			items = JSON.parse(args[0]);
		} catch (e) {
			console.warn(`[global-menu] daemon sent an unreadable menu tree: ${e.message}`);
		}
		this._onMenuTree(items);
	}

	_onRequestWindowActions() {
		this._currentWindow = new WindowActions();
		this._call('ListWindowActions', this._currentWindow.getActions());
	}

	_onActivateWindowAction(proxy, nameOwner, args) {
		this._currentWindow?.doAction(args[0]);
	}
}

export default class GlobalMenuExtension extends Extension {
	enable() {
		this._settings = this.getSettings();
		this._settingsHandlerIds = [];

		// Started before the menu bar's proxy, so the name is being claimed
		// by the time the proxy binds to it
		this._daemon = new DaemonManager();
		this._daemon.start();

		KeySynth.setDebug(this._settings.get_boolean('debug-shortcut-menus'));
		this._store = new ShortcutStore(
			this.dir.get_child('shortcuts'),
			Gio.File.new_for_path(GLib.build_filenamev(
				[GLib.get_user_config_dir(), 'global-menu', 'shortcuts']))
		);
		this._store.load();
		this._logStoreWarnings();

		this._fallback = this._settings.get_boolean('enable-fallback-menu')
			? new FallbackMenu(this.uuid) : null;
		this._menubar = new MenuBar(this._fallback, this.uuid, this._store, this._settings);
		// Styles the buttons that exist and every one made later
		this._appearance = createAppearanceManager(this._settings);

		this._watch('enable-fallback-menu', () => this._toggleFallback());
		// The preferences bump the revision after writing a mapping file
		this._watch('shortcuts-revision', () => {
			this._store.load();
			this._logStoreWarnings();
			this._menubar.refresh();
		});
		this._watch('shortcut-menus-enabled', () => this._menubar.refresh());
		this._watch('shortcut-disabled-apps', () => this._menubar.refresh());
		this._watch('debug-shortcut-menus',
			() => KeySynth.setDebug(this._settings.get_boolean('debug-shortcut-menus')));
	}

	disable() {
		for (const id of this._settingsHandlerIds ?? [])
			this._settings.disconnect(id);
		this._settingsHandlerIds = [];
		cancelPendingActions();
		// Reverse order of enable(). The appearance manager goes while the
		// buttons are still alive: styling is undone per button, and a blur
		// effect has to go back to Blur My Shell rather than vanish with the
		// actor it was attached to.
		this._appearance?.destroy();
		this._appearance = null;
		this._menubar?.destroy();
		this._menubar = null;
		this._fallback?.destroy();
		this._fallback = null;
		this._store = null;
		KeySynth.setDebug(false);
		this._daemon?.destroy();
		this._daemon = null;
		this._settings = null;
	}

	_watch(key, callback) {
		this._settingsHandlerIds.push(this._settings.connect(`changed::${key}`, callback));
	}

	// Informational findings (duplicate shortcuts, mostly) would put dozens
	// of lines in the journal on every enable, so they need debugging on.
	_logStoreWarnings() {
		const debug = this._settings.get_boolean('debug-shortcut-menus');
		for (const {file, message, level} of this._store.warnings) {
			if (level !== 'info')
				console.warn(`[global-menu-shortcuts] ${file}: ${message}`);
			else if (debug)
				console.log(`[global-menu-shortcuts] ${file}: ${message}`);
		}
	}

	_toggleFallback() {
		const enabled = this._settings.get_boolean('enable-fallback-menu');
		if (enabled && !this._fallback) {
			this._fallback = new FallbackMenu(this.uuid);
		} else if (!enabled && this._fallback) {
			this._fallback.destroy();
			this._fallback = null;
		}
		this._menubar.setFallback(this._fallback);
	}
}
