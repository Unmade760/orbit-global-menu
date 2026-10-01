// How MenuBarButton draws a spec's accel: a second label after the item's
// own, right-aligned, faint, and not faint on an insensitive item. St,
// Clutter and the shell's popup classes exist only inside a running shell,
// so they are replaced by recording doubles; acceleratorLabel() is the real
// one.

import GLib from 'gi://GLib';

import {test, run, assert} from './lib/testlib.js';
import {importWithStubs, EXT_DIR} from './lib/stubbed.js';

const ActorAlign = {FILL: 0, START: 1, CENTER: 2, END: 3};

globalThis.gmGi = {
    GObject: {registerClass: klass => klass},
    Clutter: {ActorAlign},
    St: {
        Label: class {
            constructor(params) {
                Object.assign(this, params);
                this.opacity = 255;
            }
        },
    },
};

const POPUP_MENU_STUB = `
export const Ornament = {NONE: 0, DOT: 1, CHECK: 2, HIDDEN: 3, NO_DOT: 4};
class Menu {
    constructor() { this.items = []; }
    addMenuItem(item) { this.items.push(item); }
    removeAll() { this.items = []; }
}
class Item {
    constructor(text) {
        this.label = {text};
        this.children = [this.label];
        this._sensitive = true;
        this._reactive = true;
        this._handlers = [];
    }
    add_child(child) { this.children.push(child); }
    connect(signal, fn) { this._handlers.push([signal, fn]); }
    _emit(signal) {
        for (const [s, fn] of this._handlers) {
            if (s === signal)
                fn(this);
        }
    }
    get reactive() { return this._reactive; }
    set reactive(reactive) {
        this._reactive = reactive;
        this._emit('notify::reactive');
    }
    get sensitive() { return this._sensitive; }
    // As PopupBaseMenuItem.syncSensitive(): reactive follows sensitive
    // (St draws :insensitive from it), then notify::sensitive
    setSensitive(sensitive) {
        this._sensitive = sensitive;
        this.reactive = sensitive;
        this._emit('notify::sensitive');
    }
    setOrnament(ornament) { this.ornament = ornament; }
}
export class PopupMenuItem extends Item {}
export class PopupSeparatorMenuItem extends Item {}
export class PopupSubMenuMenuItem extends Item {
    constructor(text) {
        super(text);
        this.menu = new Menu();
    }
}
`;

const PANEL_MENU_STUB = `
export class Button {
    constructor(...args) { this._init(...args); }
    _init() {
        this.menu = {
            items: [],
            actor: {add_style_class_name() {}},
            connect() {},
            addMenuItem(item) { this.items.push(item); },
            removeAll() { this.items = []; },
        };
    }
    add_child() {}
}
`;

// menuBarButton.js with its gi:// imports pointed at gmGi above
const [, source] = GLib.file_get_contents(`${EXT_DIR}/menuBarButton.js`);
const menuBarButtonSource = new TextDecoder().decode(source).replace(
    /^import (\w+) from 'gi:\/\/(\w+)';$/gm, 'const $1 = globalThis.gmGi.$2;');

const {MenuBarButton} = await importWithStubs('menuBarButton.js', {
    resources: {
        'resource:///org/gnome/shell/ui/panelMenu.js': PANEL_MENU_STUB,
        'resource:///org/gnome/shell/ui/popupMenu.js': POPUP_MENU_STUB,
    },
    locals: {
        'menuBarButton.js': menuBarButtonSource,
        'appearance.js': 'export function registerButton() {}\nexport function onMenuOpened() {}\n',
    },
});

function build(specs) {
    const btn = new MenuBarButton('File');
    btn.setItems(specs);
    return btn.menu.items;
}

const accelLabels = item => item.children.filter(c => c.style_class === 'global-menu-accel');

test('an item with an accel gets one shortcut label after its own text', () => {
    const [item] = build([{label: 'Save As…', accel: '<Primary><Shift>s'}]);
    assert.equal(item.children.length, 2);
    assert.equal(item.children[0], item.label, 'item text first');
    const accel = item.children[1];
    assert.equal(accel.style_class, 'global-menu-accel');
    assert.equal(accel.text, 'Shift+Ctrl+S');
    assert.equal(accel.x_expand, true);
    assert.equal(accel.x_align, ActorAlign.END);
    assert.equal(accel.y_align, ActorAlign.CENTER);
});

test('no shortcut label without an accel, or with one that does not parse', () => {
    const items = build([{label: 'A'}, {label: 'B', accel: ''}, {label: 'C', accel: '<Hyper>q'}]);
    assert.deepEqual(items.map(i => accelLabels(i).length), [0, 0, 0]);
});

test('a submenu title gets no shortcut label, its items do', () => {
    const [sub] = build([{label: 'Recent', accel: '<Primary>r', children: [{label: 'Clear', accel: '<Primary>Delete'}]}]);
    assert.equal(accelLabels(sub).length, 0, 'submenu title');
    assert.equal(accelLabels(sub.menu.items[0])[0]?.text, 'Ctrl+Delete', 'submenu item');
});

test('the shortcut is faint on a sensitive item and left to the theme on an insensitive one', () => {
    const [on, off] = build([
        {label: 'Undo', accel: '<Primary>z'},
        {label: 'Redo', accel: '<Primary><Shift>z', enabled: false},
    ]);
    assert.equal(accelLabels(on)[0].opacity, 140, 'sensitive');
    assert.equal(accelLabels(off)[0].opacity, 255, 'insensitive');
    on.setSensitive(false);
    off.setSensitive(true);
    assert.equal(accelLabels(on)[0].opacity, 255, 'made insensitive later');
    assert.equal(accelLabels(off)[0].opacity, 140, 'made sensitive later');
});

await run();
