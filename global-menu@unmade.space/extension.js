
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {createManager as createAppearanceManager} from './appearance.js';
import {DaemonManager} from './daemon.js';
import {FallbackMenu} from './fallbackMenu.js';
import {NativeMenu, hasBarMenus} from './nativeMenu.js';
import {ShortcutMenu} from './shortcutMenu.js';
import {ShortcutStore} from './shortcutStore.js';
import {WindowActions, cancelPendingActions} from './windowActions.js';
import * as KeySynth from './keySynth.js';

const BUS_NAME = 'space.unmade.GlobalMenu';
const BUS_PATH = '/space/unmade/GlobalMenu';

// mutter refuses transient for loops so bound the walk
const MAX_TRANSIENT_STEPS = 8;

class MenuTreeCache {
	constructor(size = 10) {
		this._size = size;
		this._lru = [];
		this._entries = new Map();
	}

	get(appId) {
		return this._entries.get(appId);
	}

	store(key, items) {
		if (this._entries.has(key))
			this._lru.splice(this._lru.indexOf(key), 1);
		this._lru.push(key);
		this._entries.set(key, items);

		if (this._lru.length > this._size)
			this._entries.delete(this._lru.shift());
	}
}

class MenuBar {
	constructor(fallbackMenu, uuid, store, settings) {
		this._winTracker = Shell.WindowTracker.get_default();
		this._fallback = fallbackMenu ?? null;
		this._store = store;
		this._settings = settings;
		this._shortcutMapping = null;
		this._cache = new MenuTreeCache();
		// drop trees whose request id is stale
		this._request = 0;
		this._requestApp = null;

		this._proxy = new DaemonProxy({
			onMenuTree: (items, request) => {
				if (request !== undefined && request !== String(this._request))
					return;
				if (items.length > 0)
					this._cache.store(this._requestApp, items);
				this.setMenuTree(items);
			},
			onDaemonAppeared: () => this.refresh(),
		});
		this._native = new NativeMenu(this._proxy, uuid, source => this._fallback?.setAppItems(source));
		this._shortcuts = new ShortcutMenu(uuid);

		this._shellHandlers = [
			[global.display, global.display.connect('notify::focus-window', () => this.refresh())],
			[Main.overview, Main.overview.connect('showing', () => this._closeAllMenus())],
			// at shell shutdown the panel dies before windows close
			// so run first
			[Main.panel, Main.panel.connect('destroy', () => this._disconnectInputs())],
		];

		this.refresh();
	}

	setFallback(fallbackMenu) {
		this._fallback = fallbackMenu;
		this._fallback?.setAppItems(this._native.appMenuSource());
		this._fallback?.setNativeMenusPresent(this._native.hasMenus() || this._shortcuts.hasMenus());
	}

	setMenuTree(items) {
		if (this._blank)
			return;
		this._native.setItems(items);
		if (hasBarMenus(items)) {
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

	refresh() {
		this._fallback?.updateAppName();
		this._shortcutMapping = null;
		this._blank = false;

		const focusApp = this._winTracker.focus_app;
		const win = focusApp ? this._menuWindow(focusApp) : null;
		if (!win) {
			this._request++;
			this._fallback?.setBlank(false);
			this._showNothing();
			return;
		}

		const candidates = this._shortcutCandidates(focusApp, win);
		const mapping = this._store.resolveMapping(candidates);
		this._shortcutMapping = mapping && this._shortcutsEnabledForApp(mapping) ? mapping : null;
		this._blank = this._shortcutMapping?.blank === true;
		this._fallback?.setBlank(this._blank);
		if (this._blank) {
			this._native.clear();
			this._shortcuts.setMapping(null);
			return;
		}
		if (this._settings.get_boolean('debug-shortcut-menus')) {
			console.log(`[global-menu-shortcuts] resolution: candidates=[${candidates}] ` +
				`matched ${this._shortcutMapping?.app ?? 'nothing'}`);
		}

		const appId = focusApp.get_id();
		const cached = this._cache.get(appId);
		if (cached) {
			this.setMenuTree(cached);
		} else if (this._shortcutMapping) {
			this._native.clear();
			this._shortcuts.setMapping(this._shortcutMapping);
			this._fallback?.setNativeMenusPresent(true);
		} else {
			this._showNothing();
		}

		this._request++;
		this._requestApp = appId;
		this._proxy.WindowSwitched({...this._windowData(win), request: String(this._request)});
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

	// x11 id comes from the hex prefix of the mutter description
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

	<signal name="MenuTreeRequest">
	  <arg name="request" type="s"/>
	</signal>
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

const DAEMON_GONE_ERRORS = [
	Gio.DBusError.SERVICE_UNKNOWN,
	Gio.DBusError.NAME_HAS_NO_OWNER,
	Gio.DBusError.NO_REPLY,
];

class DaemonProxy {
	constructor({onMenuTree, onDaemonAppeared}) {
		this._onMenuTree = onMenuTree;
		this._onDaemonAppeared = onDaemonAppeared;
		this._signalIds = [];
		this._ownerChangedId = 0;
		this._currentWindow = null;
		this._treeRequest = undefined;
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

	// gjs logs every failed call made without a callback
	_call(method, ...args) {
		if (!this._proxy.g_name_owner)
			return;
		this._proxy[`${method}Remote`](...args, (result, error) => {
			if (error && !DAEMON_GONE_ERRORS.some(code => error.matches(Gio.DBusError, code)))
				console.warn(`[global-menu] ${method} failed: ${error.message}`);
		});
	}

	_onProxyReady(error) {
		// destroy cancels the async constructor
		// a late proxy would leave signals connected
		if (this._cancellable.is_cancelled())
			return;
		if (error) {
			console.warn(`[global-menu] no proxy for ${BUS_NAME}: ${error.message}`);
			return;
		}

		this._signalIds.push(
			this._proxy.connectSignal('MenuTreeRequest', (proxy, nameOwner, [request]) => {
				this._treeRequest = request;
			}),
			this._proxy.connectSignal('SendMenuTree', this._onSendMenuTree.bind(this)),
			this._proxy.connectSignal('RequestWindowActionsSignal', this._onRequestWindowActions.bind(this)),
			this._proxy.connectSignal('ActivateWindowActionSignal', this._onActivateWindowAction.bind(this))
		);
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
		const request = this._treeRequest;
		this._treeRequest = undefined;
		this._onMenuTree(items, request);
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

		// start before the menu bar proxy so the name is claimed
		// when the proxy binds
		this._daemon = new DaemonManager();
		this._daemon.start();

		KeySynth.setDebug(this._settings.get_boolean('debug-shortcut-menus'));
		this._store = new ShortcutStore(
			this.dir.get_child('shortcuts'),
			Gio.File.new_for_path(GLib.build_filenamev(
				[GLib.get_user_config_dir(), 'global-menu', 'shortcuts']))
		);
		this._reloadStore();

		this._fallback = this._settings.get_boolean('enable-fallback-menu')
			? new FallbackMenu(this.uuid) : null;
		this._menubar = new MenuBar(this._fallback, this.uuid, this._store, this._settings);
		this._appearance = createAppearanceManager(this._settings);

		this._watch('enable-fallback-menu', () => this._toggleFallback());
		this._watch('shortcuts-revision', () => this._reloadStore());
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
		KeySynth.cancelPendingShortcuts();
		// appearance manager goes first so blur my shell
		// gets its effects back before the actors die
		this._appearance?.destroy();
		this._appearance = null;
		this._menubar?.destroy();
		this._menubar = null;
		this._fallback?.destroy();
		this._fallback = null;
		this._storeLoad?.cancel();
		this._storeLoad = null;
		this._store = null;
		KeySynth.setDebug(false);
		this._daemon?.destroy();
		this._daemon = null;
		this._settings = null;
	}

	_watch(key, callback) {
		this._settingsHandlerIds.push(this._settings.connect(`changed::${key}`, callback));
	}

	_reloadStore() {
		this._storeLoad?.cancel();
		const cancellable = new Gio.Cancellable();
		this._storeLoad = cancellable;
		this._store.loadAsync(cancellable).then(() => {
			this._logStoreWarnings();
			this._menubar.refresh();
		}).catch(e => {
			if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
				console.error(`[global-menu-shortcuts] could not read the mappings: ${e.message}`);
		});
	}

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
