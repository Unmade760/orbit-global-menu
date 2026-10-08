// The generic menu shown for apps with no menu and no mapping (fallbackMenu.js)
// and the placement of every menu-bar button (panelBar.js). The shell's
// classes are replaced by recording doubles.

import GLib from 'gi://GLib';

import {test, skip, run, assert} from './lib/testlib.js';
import {importWithStubs, EXT_DIR} from './lib/stubbed.js';

const MENU_BAR_BUTTON_STUB = `
export class MenuBarButton {
    constructor(label, params = {}) {
        this.label = label;
        this.params = params;
        this.items = null;
        this.destroyed = false;
        this.menu = {close() {}};
        globalThis.gmTest.buttons.push(this);
    }
    setItems(items) { this.items = items; }
    setLabel(text) { this.label = text; }
    show() {}
    hide() {}
    destroy() { this.destroyed = true; }
}
`;
const PANEL_BAR_STUB = `
export function addBarButton(id, button, rank) {
    globalThis.gmTest.added.push({id, label: button.label, rank});
}
`;
const WINDOW_ACTIONS_STUB = `
export class WindowActions { getActions() { return []; } doAction() {} }
export const actionLabel = action => action;
`;
const SYSTEM_ACTIONS_STUB = 'export const getDefault = () => ({});\n';
const MODAL_DIALOG_STUB = `
export class ModalDialog {
    constructor() {
        this.state = 'closed';
        this.buttons = [];
        this.contentLayout = {add_child() {}};
        this._handlers = [];
        globalThis.gmTest.dialogs.push(this);
    }
    setButtons(buttons) { this.buttons = buttons; }
    connect(signal, fn) { this._handlers.push([signal, fn]); }
    open() { this.state = 'open'; return true; }
    close() {
        if (this.state === 'closed')
            return;
        this.state = 'closed';
        this._handlers.filter(([s]) => s === 'closed').forEach(([, fn]) => fn());
    }
}
`;
const DIALOG_STUB = 'export class MessageDialogContent { constructor(params) { Object.assign(this, params); } }\n';
const SHELL_STUB = 'export default {WindowTracker: {get_default: () => ({focus_app: globalThis.gmTest.focusApp})}, AppSystem: {get_default: () => ({lookup_app: () => null})}};\n';
const CLUTTER_STUB = 'export default {KEY_Escape: 0xff1b};\n';
const KEY_SYNTH_STUB = `
export function sendShortcut(accel) { globalThis.gmTest.sent.push('now ' + accel); return true; }
export function sendShortcutAfterMenu(accel) { globalThis.gmTest.sent.push('after menu ' + accel); }
export function setDebug() {}
`;

const decoder = new TextDecoder();
const readSource = name => decoder.decode(GLib.file_get_contents(`${EXT_DIR}/${name}`)[1]);
const fallbackSource = readSource('fallbackMenu.js');

const {FallbackMenu} = await importWithStubs('fallbackMenu.js', {
    resources: {
        'resource:///gm-test/Shell.js': SHELL_STUB,
        'resource:///gm-test/Clutter.js': CLUTTER_STUB,
        'resource:///org/gnome/shell/misc/systemActions.js': SYSTEM_ACTIONS_STUB,
        'resource:///org/gnome/shell/ui/modalDialog.js': MODAL_DIALOG_STUB,
        'resource:///org/gnome/shell/ui/dialog.js': DIALOG_STUB,
    },
    locals: {
        'fallbackMenu.js': fallbackSource
            .replace("'gi://Shell'", "'resource:///gm-test/Shell.js'")
            .replace("'gi://Clutter'", "'resource:///gm-test/Clutter.js'"),
        'menuBarButton.js': MENU_BAR_BUTTON_STUB,
        'panelBar.js': PANEL_BAR_STUB,
        'windowActions.js': WINDOW_ACTIONS_STUB,
        'keySynth.js': KEY_SYNTH_STUB,
    },
});
const {acceleratorLabel} = await importWithStubs('accelerator.js');

function reset(focusApp = null) {
    globalThis.gmTest = {buttons: [], added: [], dialogs: [], focusApp, panel: null, sent: []};
    return globalThis.gmTest;
}

// The items of a button, whether it holds specs or a function that makes them
const specsOf = btn => typeof btn.items === 'function' ? btn.items() : btn.items;
const labelsOf = btn => specsOf(btn).filter(s => !s.separator).map(s => s.label);

test('the app-name button is Desktop with no window focused and holds no items', () => {
    const t = reset();
    new FallbackMenu('uuid');
    assert.equal(t.buttons[0].label, 'Desktop');
    assert.equal(t.buttons[0].params.appName, true);
    assert.deepEqual(specsOf(t.buttons[0]), []);
});

function fakeApp({newWindow = true} = {}) {
    const calls = [];
    const win = {minimized: false, can_minimize: () => true, minimize() {
        this.minimized = true;
    }};
    return {
        calls, win,
        get_name: () => 'Text Editor',
        can_open_new_window: () => newWindow,
        open_new_window: ws => calls.push(`new ${ws}`),
        get_windows: () => [win],
        request_quit: () => calls.push('quit'),
    };
}

test('the app-name menu offers New Window, Hide and Quit for the focused app', () => {
    const app = fakeApp();
    const t = reset(app);
    new FallbackMenu('uuid');
    assert.equal(t.buttons[0].label, 'Text Editor');
    const specs = specsOf(t.buttons[0]);
    assert.deepEqual(specs.map(s => s.separator ? '---' : s.label),
        ['New Window', 'Hide Text Editor', '---', 'Quit Text Editor']);
    specs[0].onActivate();
    specs[1].onActivate();
    specs[3].onActivate();
    assert.deepEqual(app.calls, ['new -1', 'quit']);
    assert.ok(app.win.minimized, 'Hide minimizes the app window');
});

test('the app-name menu has no New Window for an app that cannot open one, and the GTK app menu goes first', () => {
    const t = reset(fakeApp({newWindow: false}));
    const menu = new FallbackMenu('uuid');
    menu.setAppItems(() => [{label: 'About'}]);
    assert.deepEqual(specsOf(t.buttons[0]).map(s => s.separator ? '---' : s.label),
        ['About', '---', 'Hide Text Editor', '---', 'Quit Text Editor']);
});

test('Open Files, Settings and Empty Trash are in the System menu, nowhere else', () => {
    const t = reset(fakeApp());
    new FallbackMenu('uuid');
    const desktopItems = ['Open Files', 'Settings', 'Empty Trash'];
    const system = t.buttons.find(b => b.label === 'System');
    const systemLabels = labelsOf(system);
    for (const label of desktopItems) {
        assert.ok(systemLabels.some(l => l.startsWith(label)), `${label} in System`);
        const elsewhere = t.buttons.filter(b => b !== system && labelsOf(b).some(l => l.startsWith(label)));
        assert.equal(elsewhere.length, 0, `${label} outside System`);
    }
    const at = label => systemLabels.findIndex(l => l.startsWith(label));
    assert.ok(at('Open Files') > at('Show Notifications'), 'after Show Notifications');
});

test('File has no New Window, which only ever opened a Files window', () => {
    const t = reset();
    new FallbackMenu('uuid');
    const file = t.buttons.find(b => b.label === 'File');
    assert.ok(!labelsOf(file).includes('New Window'));
});

test('the fallback buttons take ranks 0 to 5 in order', () => {
    const t = reset();
    new FallbackMenu('uuid');
    assert.deepEqual(t.added.map(a => a.rank), [0, 1, 2, 3, 4, 5]);
    assert.equal(t.added[0].label, 'Desktop');
});

test('items with a fixed shortcut carry an accel that has a label', () => {
    const t = reset();
    new FallbackMenu('uuid');
    const edit = specsOf(t.buttons.find(b => b.label === 'Edit'));
    const copy = edit.find(s => s.label === 'Copy');
    assert.equal(copy.accel, '<Ctrl>C');
    assert.equal(acceleratorLabel(copy.accel), 'Ctrl+C');
    const withAccel = t.buttons.flatMap(specsOf).filter(s => s.accel);
    assert.ok(withAccel.length >= 20, `${withAccel.length} items with an accel`);
    for (const spec of withAccel)
        assert.ok(acceleratorLabel(spec.accel), `${spec.label}: ${spec.accel} has no label`);
    const windowMenu = specsOf(t.buttons.find(b => b.label === 'Window'));
    assert.equal(windowMenu.find(s => s.label === 'Snap Window Left').accel, '<Super>Left');
});

test('a keystroke item waits for the menu to release its grab', () => {
    const t = reset();
    new FallbackMenu('uuid');
    specsOf(t.buttons.find(b => b.label === 'Edit')).find(s => s.label === 'Copy').onActivate();
    assert.deepEqual(t.sent, ['after menu <Ctrl>C']);
});

test('items that act through an API, not a keystroke, carry no accel', () => {
    const t = reset();
    new FallbackMenu('uuid');
    const system = specsOf(t.buttons.find(b => b.label === 'System'));
    assert.equal(system.find(s => s.label === 'Lock Screen').accel, undefined);
    assert.equal(system.find(s => s.label === 'Show Applications').accel, '<Super>A');
});

test('fallbackMenu.js makes no synchronous file call', () => {
    const syncCalls = fallbackSource.match(
        /\.(?:next_file|entries\.close|delete|make_directory|make_directory_with_parents|enumerate_children|query_info|load_contents|replace_contents|read|query_exists)\(/g);
    assert.equal(syncCalls, null, `synchronous calls: ${syncCalls}`);
    assert.equal(fallbackSource.match(/\(null\)/g), null, 'a call with only a null cancellable');
});

const systemItem = (t, label) => specsOf(t.buttons.find(b => b.label === 'System')).find(s => s.label === label);

test('Empty Trash asks first and does not touch the trash until it is confirmed', () => {
    const t = reset();
    new FallbackMenu('uuid');
    const item = systemItem(t, 'Empty Trash…');
    assert.ok(item, 'the label ends with an ellipsis because it opens a dialog');
    item.onActivate();
    assert.equal(t.dialogs.length, 1);
    assert.equal(t.dialogs[0].state, 'open');
    assert.deepEqual(t.dialogs[0].buttons.map(b => b.label), ['Cancel', 'Empty Trash']);
    // a second activation while the dialog is up does not stack another
    item.onActivate();
    assert.equal(t.dialogs.length, 1);
    t.dialogs[0].buttons[0].action();
    assert.equal(t.dialogs[0].state, 'closed');
    item.onActivate();
    assert.equal(t.dialogs.length, 2, 'a closed dialog can be asked again');
    t.dialogs[1].close();
});

test('destroy() closes a dialog that is still open', () => {
    const t = reset();
    const menu = new FallbackMenu('uuid');
    systemItem(t, 'Empty Trash…').onActivate();
    menu.destroy();
    assert.equal(t.dialogs[0].state, 'closed');
    assert.ok(t.buttons.every(b => b.destroyed));
});

// New Folder on Desktop, with the desktop folder pointed at a scratch
// directory. GLib reads the user directories once, so the test is skipped
// when they were already cached somewhere else, rather than risk making a
// folder in the real home.
function spinUntil(condition, ms = 5000) {
    const context = GLib.MainContext.default();
    const end = GLib.get_monotonic_time() + ms * 1000;
    while (!condition() && GLib.get_monotonic_time() < end)
        context.iteration(false);
    return condition();
}
const scratch = GLib.dir_make_tmp('gm-fallback-XXXXXX');
GLib.mkdir_with_parents(`${scratch}/config`, 0o755);
GLib.file_set_contents(`${scratch}/config/user-dirs.dirs`, `XDG_DESKTOP_DIR="${scratch}/Desk"\n`);
GLib.setenv('XDG_CONFIG_HOME', `${scratch}/config`, true);
GLib.reload_user_special_dirs_cache();
const desktopIsScratch = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP) === `${scratch}/Desk`;

if (desktopIsScratch) {
    test('New Folder on Desktop numbers its folders and makes the desktop folder if it is missing', () => {
        const t = reset();
        new FallbackMenu('uuid');
        const make = specsOf(t.buttons.find(b => b.label === 'File')).find(s => s.label === 'New Folder on Desktop');
        const exists = name => GLib.file_test(`${scratch}/Desk/${name}`, GLib.FileTest.IS_DIR);
        make.onActivate();
        assert.ok(spinUntil(() => exists('Untitled Folder')), 'first folder');
        make.onActivate();
        assert.ok(spinUntil(() => exists('Untitled Folder 2')), 'second folder');
        make.onActivate();
        assert.ok(spinUntil(() => exists('Untitled Folder 3')), 'third folder');
    });
} else {
    skip('New Folder on Desktop numbers its folders', 'the desktop folder could not be pointed at a scratch directory');
}

// panelBar.js: where addBarButton() puts a button. The fake panel keeps a
// list of containers and does what Panel.addToStatusArea() does with it.

function fakePanel(initial) {
    const children = [];
    const named = name => ({name, first_child: {}});
    const panel = {
        children,
        _leftBox: {get_children: () => children.slice()},
        statusArea: {activities: {container: named('activities')}},
        addToStatusArea(role, btn, position) {
            const container = {name: role, first_child: btn};
            children.splice(position, 0, container);
        },
        names: () => children.map(c => c.name),
    };
    children.push(panel.statusArea.activities.container);
    for (const name of initial)
        children.push(named(name));
    globalThis.gmTest.panel = panel;
    return panel;
}
const appNameButton = {_globalMenuButton: true, _globalMenuAppName: true};
const menuButton = {_globalMenuButton: true, _globalMenuAppName: false};

// Panel is read through a module-level import, so each case needs the stub
// to see its own panel
async function barFor(panel) {
    const mod = await importWithStubs('panelBar.js', {
        resources: {'resource:///org/gnome/shell/ui/main.js': 'export const panel = globalThis.gmTest.panel;\n'},
    });
    globalThis.gmTest.panel = panel;
    return mod.addBarButton;
}

test('without an app-name button the first menu sits right after the workspace indicator', async () => {
    reset();
    const panel = fakePanel(['other-extension']);
    const add = await barFor(panel);
    ['native-0', 'native-1', 'native-2'].forEach((role, i) => add(role, menuButton, 1 + i));
    assert.deepEqual(panel.names(), ['activities', 'native-0', 'native-1', 'native-2', 'other-extension']);
});

test('without an app-name button a rebuild keeps the run in order', async () => {
    reset();
    const panel = fakePanel(['other-extension']);
    const add = await barFor(panel);
    ['a', 'b'].forEach((role, i) => add(role, menuButton, 1 + i));
    // the three menus of the next tree replace the two of the last
    panel.children.splice(1, 2);
    ['c', 'd', 'e'].forEach((role, i) => add(role, menuButton, 1 + i));
    assert.deepEqual(panel.names(), ['activities', 'c', 'd', 'e', 'other-extension']);
});

test('with an app-name button the first menu follows it', async () => {
    reset();
    const panel = fakePanel(['other-extension']);
    const add = await barFor(panel);
    add('app', appNameButton, 0);
    ['native-0', 'native-1'].forEach((role, i) => add(role, menuButton, 1 + i));
    assert.deepEqual(panel.names(), ['activities', 'app', 'native-0', 'native-1', 'other-extension']);
});

test('the run follows its app-name button when another extension moves it', async () => {
    reset();
    const panel = fakePanel([]);
    const add = await barFor(panel);
    add('app', appNameButton, 0);
    panel.children.unshift({name: 'late-extension', first_child: {}});
    ['native-0', 'native-1'].forEach((role, i) => add(role, menuButton, 1 + i));
    assert.deepEqual(panel.names(), ['late-extension', 'activities', 'app', 'native-0', 'native-1']);
});

test('the app-name button goes ahead of menus that are already there', async () => {
    reset();
    const panel = fakePanel([]);
    const add = await barFor(panel);
    add('native-0', menuButton, 1);
    add('app', appNameButton, 0);
    assert.deepEqual(panel.names(), ['activities', 'app', 'native-0']);
});

test('the panel is not touched when it has no workspace indicator', async () => {
    reset();
    const panel = fakePanel([]);
    panel.children.length = 0;
    panel.statusArea.activities = undefined;
    const add = await barFor(panel);
    add('native-0', menuButton, 1);
    assert.deepEqual(panel.names(), ['native-0']);
});

await run();
