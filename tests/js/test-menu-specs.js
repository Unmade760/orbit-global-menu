// Menu spec building: what ShortcutMenu (mappings) and NativeMenu (the
// daemon's JSON tree) hand to MenuBarButton. The panel is replaced by
// recording doubles, so this tests the conversion and nothing drawn.

import {test, run, assert} from './lib/testlib.js';
import {importWithStubs} from './lib/stubbed.js';

// PopupMenu.Ornament, copied from gnome-shell js/ui/popupMenu.js. The same
// values in 48.8 and 51.0 (/home/ravi/src/gnome/versions/gnome-shell-*).
const POPUP_MENU_STUB = 'export const Ornament = {NONE: 0, DOT: 1, CHECK: 2, HIDDEN: 3, NO_DOT: 4};\n';
const Ornament = {NONE: 0, DOT: 1, CHECK: 2};

const MENU_BAR_BUTTON_STUB = `
export class MenuBarButton {
    constructor(label, params = {}) {
        this.label = label;
        this.params = params;
        this.items = null;
        this.destroyed = false;
        this.menu = {isOpen: false, close() {}, _getMenuItems: () => []};
        globalThis.gmTest.buttons.push(this);
    }
    setItems(items) { this.items = items; }
    setLabel(label) { this.label = label; }
    destroy() { this.destroyed = true; }
}
`;
const PANEL_BAR_STUB = `
export function addBarButton(id, button, position) {
    globalThis.gmTest.added.push({id, label: button.label, position});
}
`;

const stubs = {
    resources: {'resource:///org/gnome/shell/ui/popupMenu.js': POPUP_MENU_STUB},
    locals: {'menuBarButton.js': MENU_BAR_BUTTON_STUB, 'panelBar.js': PANEL_BAR_STUB},
};
const {ShortcutMenu} = await importWithStubs('shortcutMenu.js', stubs);
const {NativeMenu} = await importWithStubs('nativeMenu.js', stubs);

function reset() {
    globalThis.gmTest = {buttons: [], added: []};
    return globalThis.gmTest;
}

// Specs with functions replaced by a marker, so they compare as JSON
const plain = specs => JSON.parse(JSON.stringify(specs, (k, v) => typeof v === 'function' ? `fn:${k}` : v));

const MAPPING = {
    app: 'demo',
    menus: [
        {
            label: 'File', items: [
                {label: 'Save', shortcut: '<Ctrl>S'},
                {separator: true},
                {label: 'Only by Mouse'},
            ],
        },
        {
            label: 'View', items: [
                {label: 'Zoom', items: [{label: 'Zoom In', shortcut: '<Ctrl>plus'}]},
            ],
        },
    ],
};

test('ShortcutMenu: one bar button per menu, after the app-name button', () => {
    const rec = reset();
    const menu = new ShortcutMenu('uuid');
    menu.setMapping(MAPPING);
    assert.deepEqual(rec.added, [
        {id: 'uuid-shortcut-0', label: 'File', position: 1},
        {id: 'uuid-shortcut-1', label: 'View', position: 2},
    ]);
    assert.ok(menu.hasMenus());
});

test('ShortcutMenu: shortcut, separator, placeholder and submenu specs; the shortcut is the accel', () => {
    const rec = reset();
    new ShortcutMenu('uuid').setMapping(MAPPING);
    assert.deepEqual(plain(rec.buttons[0].items), [
        {label: 'Save', accel: '<Ctrl>S', onActivate: 'fn:onActivate'},
        {separator: true},
        {label: 'Only by Mouse', enabled: false},
    ]);
    assert.deepEqual(plain(rec.buttons[1].items), [
        {label: 'Zoom', children: [{label: 'Zoom In', accel: '<Ctrl>plus', onActivate: 'fn:onActivate'}]},
    ]);
});

test('ShortcutMenu: the same mapping again does not rebuild, null clears', () => {
    const rec = reset();
    const menu = new ShortcutMenu('uuid');
    menu.setMapping(MAPPING);
    menu.setMapping(MAPPING);
    assert.equal(rec.buttons.length, 2, 'no second set of buttons');
    menu.setMapping(null);
    assert.ok(rec.buttons.every(b => b.destroyed), 'all buttons destroyed');
    assert.ok(!menu.hasMenus());
});

function makeProxy() {
    const calls = [];
    return {
        calls,
        RequestMenuTree: () => calls.push(['RequestMenuTree']),
        ActivateMenuItem: key => calls.push(['ActivateMenuItem', key]),
    };
}

// The shape utils/menu.py sends (see DbusMenu._node_to_dict)
const TREE = [
    {
        label: '_File', key: 'File', enabled: true, toggleType: '', toggleState: false, children: [
            {label: '_New', key: 'File  »  New', enabled: true, toggleType: '', toggleState: false},
            {separator: true},
            {label: 'Word Wrap', key: 'File  »  Word Wrap', enabled: true, toggleType: 'checkmark', toggleState: true},
            {label: 'Line Numbers', key: 'File  »  Line Numbers', enabled: true, toggleType: 'checkmark', toggleState: false},
            {label: 'Small', key: 'File  »  Small', enabled: true, toggleType: 'radio', toggleState: true},
            {label: 'Large', key: 'File  »  Large', enabled: false, toggleType: 'radio', toggleState: false},
            {
                label: 'Recent', key: 'File  »  Recent', enabled: true, toggleType: '', toggleState: false, children: [
                    {label: 'a.txt', key: 'File  »  Recent  »  a.txt', enabled: true, toggleType: '', toggleState: false},
                ],
            },
        ],
    },
    {separator: true},
    {label: '', key: '', enabled: true, toggleType: '', toggleState: false, children: []},
    {label: '_Help', key: 'Help', enabled: true, toggleType: '', toggleState: false, children: []},
];

test('NativeMenu: top-level buttons skip separators and empty labels, mnemonics stripped', () => {
    const rec = reset();
    new NativeMenu(makeProxy(), 'uuid').setItems(TREE);
    assert.deepEqual(rec.added, [
        {id: 'uuid-native-0', label: 'File', position: 1},
        {id: 'uuid-native-1', label: 'Help', position: 2},
    ]);
});

test('NativeMenu: items are built lazily from a function source', () => {
    const rec = reset();
    new NativeMenu(makeProxy(), 'uuid').setItems(TREE);
    assert.equal(typeof rec.buttons[0].items, 'function');
});

test('NativeMenu: ornaments, enabled state, submenus and activation keys', () => {
    const rec = reset();
    const proxy = makeProxy();
    new NativeMenu(proxy, 'uuid').setItems(TREE);
    const specs = rec.buttons[0].items();
    assert.deepEqual(plain(specs), [
        {label: 'New', enabled: true, key: 'File  »  New', onActivate: 'fn:onActivate'},
        {separator: true},
        {label: 'Word Wrap', enabled: true, key: 'File  »  Word Wrap', ornament: Ornament.CHECK, onActivate: 'fn:onActivate'},
        {label: 'Line Numbers', enabled: true, key: 'File  »  Line Numbers', ornament: Ornament.NONE, onActivate: 'fn:onActivate'},
        {label: 'Small', enabled: true, key: 'File  »  Small', ornament: Ornament.DOT, onActivate: 'fn:onActivate'},
        {label: 'Large', enabled: false, key: 'File  »  Large', ornament: Ornament.NONE, onActivate: 'fn:onActivate'},
        {
            label: 'Recent', enabled: true, key: 'File  »  Recent', children: [
                {label: 'a.txt', enabled: true, key: 'File  »  Recent  »  a.txt', onActivate: 'fn:onActivate'},
            ],
        },
    ]);
    specs[0].onActivate();
    specs[6].children[0].onActivate();
    assert.deepEqual(proxy.calls, [['ActivateMenuItem', 'File  »  New'], ['ActivateMenuItem', 'File  »  Recent  »  a.txt']]);
});

test('NativeMenu: a node accel becomes the spec accel, at any depth', () => {
    const rec = reset();
    new NativeMenu(makeProxy(), 'uuid').setItems([
        {
            label: '_File', key: 'File', children: [
                {label: '_Save', key: 'File  »  Save', accel: '<Primary>s'},
                {label: 'Print', key: 'File  »  Print', accel: ''},
                {
                    label: 'Recent', key: 'File  »  Recent', children: [
                        {label: 'Clear', key: 'File  »  Recent  »  Clear', accel: '<Control><Shift>Delete'},
                    ],
                },
            ],
        },
    ]);
    const specs = rec.buttons[0].items();
    assert.equal(specs[0].accel, '<Primary>s');
    assert.equal(specs[1].accel, '');
    assert.equal(specs[2].children[0].accel, '<Control><Shift>Delete');
});

test('NativeMenu: a top-level app menu node gets no bar button', () => {
    const rec = reset();
    new NativeMenu(makeProxy(), 'uuid').setItems([
        {label: 'Application', key: 'app', appMenu: true, children: [{label: 'About', key: 'app  »  About'}]},
        {label: '_File', key: 'File', children: [{label: '_New', key: 'File  »  New'}]},
    ]);
    assert.deepEqual(rec.added, [{id: 'uuid-native-0', label: 'File', position: 1}]);
});

test('NativeMenu: the app menu node goes to the app-name button, and clears with the tree', () => {
    reset();
    const sources = [];
    const native = new NativeMenu(makeProxy(), 'uuid', source => sources.push(source));
    native.setItems([
        {label: 'Application', key: 'app', appMenu: true, children: [{label: 'About', key: 'app  »  About'}]},
        {label: '_File', key: 'File', children: [{label: '_New', key: 'File  »  New'}]},
    ]);
    const source = sources.at(-1);
    assert.equal(typeof source, 'function');
    assert.equal(native.appMenuSource(), source);
    assert.deepEqual(source().map(s => s.label), ['About']);
    native.setItems([{label: '_File', key: 'File', children: [{label: '_New', key: 'File  »  New'}]}]);
    assert.equal(sources.at(-1), null);
    assert.equal(native.appMenuSource(), null);
});

test('NativeMenu: mnemonics are stripped the way GTK and dbusmenu draw them', () => {
    const cases = [
        ['文件(_F)', '文件'],
        ['편집(&E)', '편집'],
        ['另存为(_A)…', '另存为…'],
        ['_File', 'File'],
        ['Save__As', 'Save_As'],
        ['Open _Recent', 'Open Recent'],
        ['Find & Replace', 'Find & Replace'],
    ];
    const rec = reset();
    new NativeMenu(makeProxy(), 'uuid').setItems(cases.map(([label], i) => ({
        label, key: `k${i}`, children: [{label, key: `k${i}  »  item`}],
    })));
    assert.deepEqual(rec.added.map(a => a.label), cases.map(([, want]) => want), 'bar titles');
    assert.deepEqual(rec.buttons.map(b => b.items()[0].label), cases.map(([, want]) => want), 'item labels');
});

test('NativeMenu: opening a menu asks the daemon for a fresh tree', () => {
    const rec = reset();
    const proxy = makeProxy();
    new NativeMenu(proxy, 'uuid').setItems(TREE);
    rec.buttons[0].params.onOpen(rec.buttons[0]);
    assert.deepEqual(proxy.calls, [['RequestMenuTree']]);
});

test('NativeMenu: an unchanged tree does not rebuild, a changed one does', () => {
    const rec = reset();
    const menu = new NativeMenu(makeProxy(), 'uuid');
    menu.setItems(TREE);
    menu.setItems(JSON.parse(JSON.stringify(TREE)));
    assert.equal(rec.buttons.length, 2, 'unchanged tree kept');
    menu.setItems(TREE.slice(0, 1));
    assert.equal(rec.buttons.length, 2, 'no button created for a shorter tree');
    assert.deepEqual(rec.buttons.map(b => b.destroyed), [false, true], 'only the extra button removed');
});

test('NativeMenu: a changed tree reuses the panel buttons and adds only new ones', () => {
    // Every panel insert is a child-added that other extensions react to,
    // such as one that moves the date menu (issue #3)
    const rec = reset();
    const menu = new NativeMenu(makeProxy(), 'uuid');
    menu.setItems([{label: '_File', key: 'File', children: [{label: '_New', key: 'File  »  New'}]}]);
    menu.setItems([
        {label: '_Edit', key: 'Edit', children: [{label: '_Copy', key: 'Edit  »  Copy'}]},
        {label: '_View', key: 'View', children: [{label: '_Zoom', key: 'View  »  Zoom'}]},
    ]);
    assert.equal(rec.added.length, 2, 'one insert for the new second menu');
    assert.deepEqual(rec.buttons.map(b => [b.label, b.destroyed]), [['Edit', false], ['View', false]]);
    assert.deepEqual(rec.buttons[0].items().map(s => s.label), ['Copy']);
});

test('ShortcutMenu: another mapping reuses the panel buttons', () => {
    const rec = reset();
    const menu = new ShortcutMenu('uuid');
    menu.setMapping(MAPPING);
    const before = rec.added.length;
    menu.setMapping({...MAPPING, menus: [{label: 'Tools', items: [{label: 'Run', shortcut: '<Ctrl>r'}]}]});
    assert.equal(rec.added.length, before, 'no new panel insert');
    assert.equal(rec.buttons[0].label, 'Tools');
    assert.ok(rec.buttons.slice(1).every(b => b.destroyed), 'extra buttons removed');
    menu.setMapping(null);
    assert.ok(rec.buttons.every(b => b.destroyed), 'null clears');
});

test('NativeMenu: a tree arriving while a menu is open waits for close', () => {
    const rec = reset();
    const menu = new NativeMenu(makeProxy(), 'uuid');
    menu.setItems(TREE);
    rec.buttons[0].menu.isOpen = true;
    menu.setItems(TREE.slice(0, 1));
    assert.equal(rec.buttons.length, 2, 'no rebuild while open');
    assert.ok(!rec.buttons[0].destroyed, 'open button kept');
    menu.destroy();
});

await run();
