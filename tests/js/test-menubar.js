// MenuBar and DaemonProxy in extension.js, driven through enable() and
// disable(). The shell is replaced by recording doubles; the daemon is a real
// D-Bus object on the test's own session bus (tools/checks/unit.sh runs every
// test under dbus-run-session), so proxy init, name ownership and error
// replies are GDBus's own.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {test, run, assert} from './lib/testlib.js';
import {importWithStubs, EXT_DIR} from './lib/stubbed.js';

const BUS_NAME = 'space.unmade.GlobalMenu';
const BUS_PATH = '/space/unmade/GlobalMenu';

// The daemon's side of the interface extension.js declares
const DAEMON_XML = `
<node>
  <interface name="space.unmade.GlobalMenu">
    <method name="WindowSwitched"><arg name="win_data" type="a{ss}" direction="in"/></method>
    <signal name="SendMenuTree"><arg name="tree_json" type="s"/></signal>
    <method name="ActivateMenuItem"><arg name="item_path" type="s" direction="in"/></method>
    <method name="RequestMenuTree"/>
    <signal name="RequestWindowActionsSignal"/>
    <method name="ListWindowActions"><arg name="actions" type="as" direction="in"/></method>
    <signal name="ActivateWindowActionSignal"><arg name="action" type="s"/></signal>
  </interface>
</node>`;

// Meta.WindowClientType, copied from mutter src/meta/window.h. The same
// values in 48.8 and 51.0 (/home/ravi/src/gnome/versions/mutter-*).
const CLIENT_WAYLAND = 0;
const CLIENT_X11 = 1;

// Everything the shell would call back into, plus a record of what the
// extension did to its menus
class Emitter {
    constructor() {
        this._handlers = new Map();
        this._nextId = 1;
    }

    connect(signal, fn) {
        const id = this._nextId++;
        this._handlers.set(id, {signal, fn});
        return id;
    }

    disconnect(id) {
        // GObject prints a critical for this
        if (!this._handlers.delete(id))
            throw new Error(`no handler with id ${id}`);
    }

    emit(signal, ...args) {
        for (const {signal: s, fn} of [...this._handlers.values()]) {
            if (s === signal)
                fn(this, ...args);
        }
    }

    get handlerCount() {
        return this._handlers.size;
    }
}

class FakeSettings extends Emitter {
    constructor() {
        super();
        this.values = {
            'enable-fallback-menu': true,
            'shortcut-menus-enabled': true,
            'debug-shortcut-menus': false,
            'shortcut-disabled-apps': [],
        };
    }

    get_boolean(key) {
        return this.values[key];
    }

    get_strv(key) {
        return this.values[key];
    }
}

const t = globalThis.gmTest = {
    display: new Emitter(),
    overview: new Emitter(),
    panel: new Emitter(),
    settings: new FakeSettings(),
    tracker: {
        focus_app: null,
        get_window_app: win => win.app,
    },
    mapping: null,
    nativeProxy: null,
    events: [],
    inputsAtDestroy: [],
    event(name) {
        this.events.push(name);
        if (name.endsWith('.destroy'))
            this.inputsAtDestroy.push([name, liveInputs()]);
    },
};
globalThis.global = {display: t.display};

function liveInputs() {
    return t.display.handlerCount + t.overview.handlerCount + t.panel.handlerCount;
}

const FALLBACK_STUB = `
export class FallbackMenu {
    constructor() { globalThis.gmTest.event('fallback.new'); }
    updateAppName() { globalThis.gmTest.event('fallback.updateAppName'); }
    setNativeMenusPresent(present) { globalThis.gmTest.event('fallback.present ' + present); }
    setBlank(blank) { if (blank) globalThis.gmTest.event('fallback.blank'); }
    closeAllMenus() {}
    destroy() { globalThis.gmTest.event('fallback.destroy'); }
}
`;
const NATIVE_STUB = `
export class NativeMenu {
    constructor(proxy) {
        this._items = [];
        globalThis.gmTest.nativeProxy = proxy;
        globalThis.gmTest.event('native.new');
    }
    setItems(items) {
        this._items = items;
        globalThis.gmTest.event('native.setItems ' + items.map(i => i.label).join(','));
    }
    clear() { this._items = []; globalThis.gmTest.event('native.clear'); }
    hasMenus() { return this._items.length > 0; }
    closeAllMenus() {}
    destroy() { globalThis.gmTest.event('native.destroy'); }
}
`;
const SHORTCUT_STUB = `
export class ShortcutMenu {
    constructor() { this._mapping = null; globalThis.gmTest.event('shortcuts.new'); }
    setMapping(mapping) {
        this._mapping = mapping;
        globalThis.gmTest.event('shortcuts.setMapping ' + (mapping ? mapping.app : null));
    }
    hasMenus() { return !!this._mapping; }
    closeAllMenus() {}
    destroy() { globalThis.gmTest.event('shortcuts.destroy'); }
}
`;
const APPEARANCE_STUB = `
export function createManager() {
    globalThis.gmTest.event('appearance.new');
    return {destroy() { globalThis.gmTest.event('appearance.destroy'); }};
}
`;
const DAEMON_STUB = `
export class DaemonManager {
    start() { globalThis.gmTest.event('daemon.start'); }
    destroy() { globalThis.gmTest.event('daemon.destroy'); }
}
`;
const STORE_STUB = `
export class ShortcutStore {
    constructor() { this.warnings = []; }
    load() {}
    resolveMapping() { return globalThis.gmTest.mapping; }
}
`;
const WINDOW_ACTIONS_STUB = `
export class WindowActions { getActions() { return []; } doAction() {} }
export function cancelPendingActions() {}
`;

// gi://Shell and gi://Meta load only inside a running shell, so they are
// pointed at stubs the same way resource:/// imports are
const [, bytes] = GLib.file_get_contents(`${EXT_DIR}/extension.js`);
const extensionSource = new TextDecoder().decode(bytes)
    .replace("'gi://Shell'", "'resource:///gm-test/Shell.js'")
    .replace("'gi://Meta'", "'resource:///gm-test/Meta.js'");

const {default: GlobalMenuExtension} = await importWithStubs('extension.js', {
    resources: {
        'resource:///gm-test/Shell.js':
            'export default {WindowTracker: {get_default: () => globalThis.gmTest.tracker}};\n',
        'resource:///gm-test/Meta.js':
            `export default {WindowClientType: {WAYLAND: ${CLIENT_WAYLAND}, X11: ${CLIENT_X11}}};\n`,
        'resource:///org/gnome/shell/extensions/extension.js': `
export class Extension {
    constructor() { this.uuid = 'test@uuid'; this.dir = {get_child: () => null}; }
    getSettings() { return globalThis.gmTest.settings; }
}
`,
        'resource:///org/gnome/shell/ui/main.js':
            'export const overview = globalThis.gmTest.overview;\nexport const panel = globalThis.gmTest.panel;\n',
    },
    locals: {
        'extension.js': extensionSource,
        'appearance.js': APPEARANCE_STUB,
        'daemon.js': DAEMON_STUB,
        'fallbackMenu.js': FALLBACK_STUB,
        'nativeMenu.js': NATIVE_STUB,
        'shortcutMenu.js': SHORTCUT_STUB,
        'shortcutStore.js': STORE_STUB,
        'windowActions.js': WINDOW_ACTIONS_STUB,
    },
});

// Every log line the process writes. A writer can be set once per process.
const logged = [];
const fieldText = v => {
    const value = v instanceof GLib.Variant ? v.deepUnpack() : v;
    return typeof value === 'string' ? value : new TextDecoder().decode(value);
};
GLib.log_set_writer_func((level, fields) => {
    logged.push(fieldText(fields.MESSAGE));
    return GLib.LogWriterOutput.HANDLED;
});

/** The daemon's bus side: records calls, can answer with a D-Bus error. */
class FakeDaemon {
    constructor() {
        this.calls = [];
        this.errorName = null;
        this._object = null;
        this._ownId = 0;
    }

    start() {
        this._object = Gio.DBusExportedObject.wrapJSObject(DAEMON_XML, this);
        this._object.export(Gio.DBus.session, BUS_PATH);
        this._ownId = Gio.bus_own_name_on_connection(Gio.DBus.session, BUS_NAME,
            Gio.BusNameOwnerFlags.NONE, null, null);
        return this;
    }

    stop() {
        if (this._ownId)
            Gio.bus_unown_name(this._ownId);
        this._ownId = 0;
        this._object?.unexport();
        this._object = null;
    }

    sendTree(tree) {
        this._object.emit_signal('SendMenuTree', new GLib.Variant('(s)', [JSON.stringify(tree)]));
    }

    count(method) {
        return this.calls.filter(([m]) => m === method).length;
    }

    lastWindowData() {
        return this.calls.filter(([m]) => m === 'WindowSwitched').at(-1)?.[1];
    }

    _answer(method, args, invocation) {
        this.calls.push([method, ...args]);
        if (this.errorName)
            invocation.return_dbus_error(this.errorName, 'test error');
        else
            invocation.return_value(null);
    }

    WindowSwitchedAsync(args, invocation) {
        this._answer('WindowSwitched', args, invocation);
    }

    ActivateMenuItemAsync(args, invocation) {
        this._answer('ActivateMenuItem', args, invocation);
    }

    RequestMenuTreeAsync(args, invocation) {
        this._answer('RequestMenuTree', args, invocation);
    }

    ListWindowActionsAsync(args, invocation) {
        this._answer('ListWindowActions', args, invocation);
    }
}

function wait(ms) {
    return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
        resolve();
        return GLib.SOURCE_REMOVE;
    }));
}

async function until(cond, what, ms = 3000) {
    const end = GLib.get_monotonic_time() + ms * 1000;
    while (!cond()) {
        if (GLib.get_monotonic_time() > end)
            throw new Error(`timed out waiting for ${what}`);
        // eslint-disable-next-line no-await-in-loop
        await wait(10);
    }
}

function makeApp(id) {
    const app = {
        windows: [],
        get_id: () => `${id}.desktop`,
        get_name: () => id,
        get_windows: () => app.windows,
    };
    return app;
}

/**
 * A MetaWindow double. `menubar` gives it the gtk_* properties a GTK app sets
 * on a window that exports a menubar; `xid` makes it an X11 window.
 */
function makeWindow(app, {title = 'Main', transientFor = null, attached = false, xid = null, menubar = false} = {}) {
    const win = {
        app,
        get_transient_for: () => transientFor,
        is_attached_dialog: () => attached,
        get_client_type: () => (xid ? CLIENT_X11 : CLIENT_WAYLAND),
        // What mutter's window.c writes for each kind
        get_description: () => (xid ? `${xid} (${title})` : `W7 (${title})`),
        get_wm_class: () => app.get_id(),
        get_wm_class_instance: () => null,
    };
    if (menubar) {
        win.gtk_unique_bus_name = `:1.${app.get_id().length}`;
        win.gtk_menubar_object_path = `/org/example/${title}/menubar`;
    }
    app.windows.push(win);
    return win;
}

/** What the shell does on a focus change: MRU order, focus app, the signal. */
function focus(win) {
    t.display.focus_window = win;
    t.tracker.focus_app = win?.app ?? null;
    if (win)
        win.app.windows = [win, ...win.app.windows.filter(w => w !== win)];
    t.display.emit('notify::focus-window');
}

/** A focused GTK main window, set before the extension is enabled. */
function focusedMainWindow() {
    const app = makeApp('org.example.Editor');
    const main = makeWindow(app, {title: 'Main', menubar: true});
    t.display.focus_window = main;
    t.tracker.focus_app = app;
    return {app, main};
}

function reset() {
    for (const emitter of [t.display, t.overview, t.panel, t.settings])
        emitter._handlers.clear();
    t.display.focus_window = null;
    t.tracker.focus_app = null;
    t.mapping = null;
    t.nativeProxy = null;
    t.events = [];
    t.inputsAtDestroy = [];
    logged.length = 0;
}

/**
 * Enable, run `body`, then disable and stop the daemon, whatever happened.
 *
 * @param {Function} body - receives the extension and the daemon
 * @param {object} options
 * @param {boolean} options.daemonFirst - the daemon owns its name before enable
 */
async function session(body, {daemonFirst = true} = {}) {
    const daemon = new FakeDaemon();
    if (daemonFirst)
        daemon.start();
    const ext = new GlobalMenuExtension();
    let enabled = false;
    try {
        ext.enable();
        enabled = true;
        await body(ext, daemon);
    } finally {
        if (enabled)
            ext.disable();
        daemon.stop();
        // Let the name release reach every proxy before the next test
        await wait(50);
    }
}

const trees = () => t.events.filter(e => e.startsWith('native.setItems'));

/** Focus `win` and wait for the WindowSwitched that reports it. */
async function focusAndReport(daemon, win) {
    const n = daemon.count('WindowSwitched');
    focus(win);
    await until(() => daemon.count('WindowSwitched') > n, 'WindowSwitched');
}

/** Wait for the proxy to come up, then report `win` through a focus change. */
async function connected(daemon, win) {
    await wait(150);
    await focusAndReport(daemon, win);
}
const TREE = [{label: 'File', key: 'File', children: []}];

test('a blank mapping shows nothing and ignores a tree from the daemon', async () => {
    reset();
    focusedMainWindow();
    t.mapping = {app: 'launcher', identifiers: ['org.example.editor'], menus: [], blank: true};
    await session(async (ext, daemon) => {
        await wait(150);
        focus(t.display.focus_window);
        assert.ok(t.events.includes('fallback.blank'), 'fallback hidden, app name included');
        daemon.sendTree(TREE);
        await wait(150);
        assert.deepEqual(trees(), [], 'no native menu');
        assert.equal(daemon.count('WindowSwitched'), 0, 'the daemon is not asked');
    });
});

// R1-43: the proxy's lifecycle, kept the same through the rewrite

test('a tree the daemon sends reaches the native menu', async () => {
    reset();
    focusedMainWindow();
    await session(async (ext, daemon) => {
        await wait(100);
        daemon.sendTree(TREE);
        await until(() => trees().length > 0, 'the tree');
        assert.deepEqual(trees(), ['native.setItems File']);
    });
});

test('disabled before the proxy is ready: nothing stays connected', async () => {
    reset();
    focusedMainWindow();
    const daemon = new FakeDaemon();
    const ext = new GlobalMenuExtension();
    ext.enable();
    ext.disable();
    t.events = [];
    daemon.start();
    try {
        await wait(150);
        daemon.sendTree(TREE);
        await wait(150);
        assert.deepEqual(t.events, [], 'nothing reaches the menus');
        assert.equal(daemon.count('WindowSwitched'), 0, 'nothing sent');
        assert.equal(liveInputs() + t.settings.handlerCount, 0, 'every handler disconnected');
        assert.deepEqual(logged, [], 'log');
    } finally {
        daemon.stop();
        await wait(50);
    }
});

// R1-34: an absent or crashed daemon is reported once, by daemon.js

test('no daemon: focus changes and menu opens send nothing and log nothing', async () => {
    reset();
    const {app} = focusedMainWindow();
    await session(async (ext, daemon) => {
        await wait(150);
        focus(makeWindow(app, {title: 'Second', menubar: true}));
        t.nativeProxy.RequestMenuTree();
        t.nativeProxy.ActivateMenuItem('File');
        await wait(200);
        assert.equal(daemon.calls.length, 0, 'calls');
        assert.deepEqual(logged, [], 'log');
    }, {daemonFirst: false});
});

// NoReply is what the bus answers when the daemon exits before replying
test('ServiceUnknown, NameHasNoOwner and NoReply answers are not logged', async () => {
    for (const errorName of ['org.freedesktop.DBus.Error.ServiceUnknown',
        'org.freedesktop.DBus.Error.NameHasNoOwner', 'org.freedesktop.DBus.Error.NoReply']) {
        reset();
        const {app} = focusedMainWindow();
        // eslint-disable-next-line no-await-in-loop
        await session(async (ext, daemon) => {
            daemon.errorName = errorName;
            await wait(150);
            focus(makeWindow(app, {title: 'Second', menubar: true}));
            t.nativeProxy.RequestMenuTree();
            t.nativeProxy.ActivateMenuItem('File');
            await until(() => daemon.count('ActivateMenuItem') > 0, 'the calls');
            await wait(100);
            assert.deepEqual(logged, [], errorName);
        });
    }
});

test('any other error is logged once, naming the method', async () => {
    reset();
    focusedMainWindow();
    await session(async (ext, daemon) => {
        await wait(150);
        daemon.errorName = 'org.freedesktop.DBus.Error.Failed';
        logged.length = 0;
        t.nativeProxy.RequestMenuTree();
        await until(() => daemon.count('RequestMenuTree') > 0, 'the call');
        await wait(100);
        assert.equal(logged.length, 1, `one line: ${JSON.stringify(logged)}`);
        assert.ok(logged[0].includes('RequestMenuTree'), `names the method: ${logged[0]}`);
    });
});

// H-17: enabling, and every unlock, starts with a window already focused

test('enable builds the menu for the focused window without a focus change', async () => {
    reset();
    focusedMainWindow();
    t.mapping = {app: 'editor'};
    await session(() => {
        assert.ok(t.events.includes('shortcuts.setMapping editor'), JSON.stringify(t.events));
    }, {daemonFirst: false});
});

test('enable reports the focused window once the daemon takes its name', async () => {
    reset();
    focusedMainWindow();
    await session(async (ext, daemon) => {
        await wait(150);
        daemon.start();
        await until(() => daemon.count('WindowSwitched') > 0, 'WindowSwitched');
        assert.equal(daemon.lastWindowData().gtk_menubar_object_path, '/org/example/Main/menubar');
    }, {daemonFirst: false});
});

test('enable reports the focused window to a daemon that already runs', async () => {
    reset();
    focusedMainWindow();
    await session(async (ext, daemon) => {
        await until(() => daemon.count('WindowSwitched') > 0, 'WindowSwitched');
        await wait(100);
        assert.equal(daemon.count('WindowSwitched'), 1, 'sent once');
    });
});

// H-16: at shell shutdown the panel goes, our buttons with it, while the
// extension stays enabled and windows are still closing

test('after the panel is destroyed, focus changes and trees reach no menu', async () => {
    reset();
    const {app, main} = focusedMainWindow();
    await session(async (ext, daemon) => {
        await connected(daemon, main);
        t.panel.emit('destroy');
        t.events = [];
        const sent = daemon.count('WindowSwitched');
        focus(makeWindow(app, {title: 'Second', menubar: true}));
        focus(null);
        daemon.sendTree(TREE);
        await wait(150);
        assert.deepEqual(t.events, [], 'menus untouched');
        assert.equal(daemon.count('WindowSwitched'), sent, 'nothing sent');
        assert.deepEqual(logged, [], 'log');
    });
});

test('disable disconnects every input before it destroys a menu, in reverse order', async () => {
    reset();
    focusedMainWindow();
    await session(() => {});
    const lifecycle = t.events.filter(e => /\.(new|start|destroy)$/.test(e));
    const built = lifecycle.filter(e => !e.endsWith('.destroy')).map(e => e.replace(/\.(new|start)$/, ''));
    const torn = lifecycle.filter(e => e.endsWith('.destroy')).map(e => e.replace(/\.destroy$/, ''));
    assert.deepEqual(torn, built.reverse(), 'destroy order');
    const menus = ['fallback.destroy', 'native.destroy', 'shortcuts.destroy'];
    assert.deepEqual(t.inputsAtDestroy.filter(([name, live]) => menus.includes(name) && live > 0), [],
        'inputs still connected');
    assert.equal(liveInputs() + t.settings.handlerCount, 0, 'every handler disconnected');
});

// R1-33: dialogs and other transient windows

test('a dialog reports the window it is transient for', async () => {
    reset();
    const {app, main} = focusedMainWindow();
    await session(async (ext, daemon) => {
        await connected(daemon, main);
        const chooser = makeWindow(app, {title: 'Open', transientFor: main});
        await focusAndReport(daemon, makeWindow(app, {title: 'Confirm', transientFor: chooser, attached: true}));
        assert.equal(daemon.lastWindowData().gtk_menubar_object_path, '/org/example/Main/menubar');
    });
});

test('a parent window of another app is not used', async () => {
    reset();
    const {main} = focusedMainWindow();
    const portal = makeApp('org.example.Portal');
    await session(async (ext, daemon) => {
        await connected(daemon, main);
        await focusAndReport(daemon, makeWindow(portal, {title: 'Open', transientFor: main}));
        assert.deepEqual(daemon.lastWindowData(), {xid: '0', appName: 'org.example.Portal'});
    });
});

test('an empty tree is not cached in place of the app menu', async () => {
    reset();
    const {app, main} = focusedMainWindow();
    const other = makeWindow(app, {title: 'Preferences'});
    await session(async (ext, daemon) => {
        await connected(daemon, main);
        daemon.sendTree(TREE);
        await until(() => trees().length === 1, 'the tree');
        focus(other);
        daemon.sendTree([]);
        await until(() => trees().length === 3, 'the empty tree');
        focus(main);
        // Straight from the cache, before the daemon answers
        assert.equal(trees().at(-1), 'native.setItems File');
    });
});

// R1-45: the X11 window id

test('a Wayland window with a hex number in its title is sent with xid 0', async () => {
    reset();
    const {app, main} = focusedMainWindow();
    await session(async (ext, daemon) => {
        await connected(daemon, main);
        await focusAndReport(daemon, makeWindow(app, {title: '0x1f40.bin - GHex'}));
        assert.equal(daemon.lastWindowData().xid, '0');
    });
});

test('an X11 window sends the id from the start of its description', async () => {
    reset();
    const {app, main} = focusedMainWindow();
    await session(async (ext, daemon) => {
        await connected(daemon, main);
        await focusAndReport(daemon, makeWindow(app, {title: 'Notes 0x10', xid: '0x1e00003'}));
        assert.equal(daemon.lastWindowData().xid, String(0x1e00003));
    });
});

await run();
