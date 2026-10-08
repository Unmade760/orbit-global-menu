// Popup geometry and the app-name switch in appearance.js: where a popup
// sits under its title, which button hides, and the submenu well radius.
// The shell's classes are replaced by recording doubles. The BoxPointer
// placement formula is copied from gnome-shell's boxpointer.js (_reposition,
// the TOP side branch, identical in 48.8 and 51.0) so the tests can check
// where the first item's text lands.

import GLib from 'gi://GLib';

import {test, run, assert} from './lib/testlib.js';
import {importWithStubs, EXT_DIR} from './lib/stubbed.js';

const MAIN_STUB = `
export const sessionMode = {connect: () => 1, disconnect() {}};
export const extensionManager = {connect: () => 1, disconnect() {}};
export const panel = {statusArea: {}};
`;
const CLUTTER_STUB = `
export default {
    TextDirection: {LTR: 1, RTL: 2},
    OffscreenRedirect: {ALWAYS: 0, AUTOMATIC_FOR_OPACITY: 1},
};
`;
const ST_STUB = `
export default {
    Side: {TOP: 0, RIGHT: 1, BOTTOM: 2, LEFT: 3},
    ThemeContext: {get_for_stage: () => ({scale_factor: globalThis.gmTest.scale})},
};
`;

const decoder = new TextDecoder();
const readSource = name => decoder.decode(GLib.file_get_contents(`${EXT_DIR}/${name}`)[1]);

globalThis.gmTest = {scale: 1};
globalThis.global = {stage: {}};

const {createManager, registerButton, onMenuOpened} = await importWithStubs('appearance.js', {
    resources: {
        'resource:///org/gnome/shell/ui/main.js': MAIN_STUB,
        'resource:///gm-test/Clutter.js': CLUTTER_STUB,
        'resource:///gm-test/St.js': ST_STUB,
    },
    locals: {
        'appearance.js': readSource('appearance.js')
            .replace("'gi://Clutter'", "'resource:///gm-test/Clutter.js'")
            .replace("'gi://St'", "'resource:///gm-test/St.js'"),
    },
});

const LTR = 1, RTL = 2;

function fakeSettings(values = {}) {
    const v = {
        'blur-popups': false, 'popup-blur-sigma': 30, 'popup-blur-brightness': 1.0,
        'popup-opacity': 65, 'popup-corner-radius': 12, 'hide-popup-arrow': true,
        'button-spacing': 8, 'menu-font-size': 10, 'bold-app-name': true,
        'hide-workspace-indicator': false, 'hide-app-name': false, ...values,
    };
    return {
        values: v,
        get_boolean: k => v[k],
        get_int: k => v[k],
        get_double: k => v[k],
        connect: () => 1,
        disconnect() {},
    };
}

// A theme node reporting the same padding and border on both sides
function node({padding = 0, border = 0, lengths = {}} = {}) {
    return {
        get_padding: () => padding,
        get_border_width: () => border,
        get_length: name => lengths[name] ?? 0,
        get_background_color: () => ({red: 40, green: 40, blue: 40}),
    };
}

function fakeButton({appName = false, rtl = false, firstItem = true, nodes = {}} = {}) {
    const handlers = new Map();
    let nextId = 1;
    const sub = {
        menu: {
            actor: {
                style: undefined, set_style(s) {
                    this.style = s;
                },
            }, box: {get_children: () => []},
        },
    };
    const btn = {
        _globalMenuAppName: appName,
        container: {visible: true},
        rtl,
        style: undefined,
        sourceAlignments: [],
        handlers,
        sub,
        get_text_direction() {
            return this.rtl ? RTL : LTR;
        },
        set_style(s) {
            this.style = s;
        },
        get_theme_node: () => nodes.bar ?? node({border: 3, lengths: {'-natural-hpadding': 8}}),
        connect(signal, fn) {
            handlers.set(nextId, {signal, fn});
            return nextId++;
        },
        disconnect(id) {
            handlers.delete(id);
        },
        emit(signal) {
            for (const h of [...handlers.values()].filter(x => x.signal === signal))
                h.fn();
        },
        menu: {
            isOpen: false,
            setSourceAlignment(a) {
                btn.sourceAlignments.push(a);
            },
            firstMenuItem: firstItem ? {get_theme_node: () => nodes.item ?? node({padding: 12})} : null,
            actor: {
                style: undefined,
                classes: new Set(),
                set_style(s) {
                    this.style = s;
                },
                add_style_class_name(c) {
                    this.classes.add(c);
                },
                remove_style_class_name(c) {
                    this.classes.delete(c);
                },
                set_offscreen_redirect() {},
                get_theme_node: () => nodes.actor ?? node(),
            },
            box: {
                style: undefined,
                set_style(s) {
                    this.style = s;
                },
                get_stage: () => ({}),
                get_theme_node: () => nodes.box ?? node({padding: 6, border: 1}),
                get_children: () => [sub],
            },
        },
    };
    return btn;
}

function setup(values, btnParams) {
    const settings = fakeSettings(values);
    const manager = createManager(settings);
    const btn = fakeButton(btnParams);
    registerButton(btn);
    return {settings, manager, btn};
}

// Where BoxPointer puts the popup's left edge and where the first item's
// text then starts, for a title content box [left, left + width]. Mirrors
// _reposition for the arrow-on-top case with the menu's arrow alignment 0.0
// that PanelMenu.Button passes. Lengths are in scaled pixels.
function itemTextX(btn, {left, width, natWidth, scale, rtl, bodyInset}) {
    const match = /-arrow-border-radius: ([\d.]+)px/.exec(btn.menu.actor.style ?? '');
    const radius = (match ? Number(match[1]) : 0) * scale;
    const margin = 4 * radius;
    const sourceAlignment = btn.sourceAlignments.at(-1);
    const source = left + width * sourceAlignment;
    const alignment = rtl ? 1.0 : 0.0;
    const popupLeft = source - (margin / 2 + (natWidth - margin) * alignment);
    return rtl ? popupLeft + natWidth - bodyInset : popupLeft + bodyInset;
}

test('source alignment is the left edge in LTR', () => {
    const {manager, btn} = setup();
    assert.equal(btn.sourceAlignments.at(-1), 0.0);
    manager.destroy();
});

test('source alignment is the right edge in RTL', () => {
    const {manager, btn} = setup({}, {rtl: true});
    assert.equal(btn.sourceAlignments.at(-1), 1.0);
    manager.destroy();
});

test('a text direction change moves the source alignment', () => {
    const {manager, btn} = setup();
    btn.rtl = true;
    btn.emit('notify::text-direction');
    assert.equal(btn.sourceAlignments.at(-1), 1.0);
    btn.rtl = false;
    btn.emit('notify::text-direction');
    assert.equal(btn.sourceAlignments.at(-1), 0.0);
    manager.destroy();
});

test('applying twice connects one direction handler and revert removes it', () => {
    const {manager, btn} = setup();
    manager.applyAll();
    manager.applyAll();
    const count = () => [...btn.handlers.values()].filter(h => h.signal === 'notify::text-direction').length;
    assert.equal(count(), 1);
    manager.destroy();
    assert.equal(count(), 0);
    const before = btn.sourceAlignments.length;
    btn.emit('notify::text-direction');
    assert.equal(btn.sourceAlignments.length, before, 'handler ran after revert');
});

test('hide-app-name hides only the app-name button container', () => {
    const settings = fakeSettings({'hide-app-name': true});
    const manager = createManager(settings);
    const app = fakeButton({appName: true});
    const menu = fakeButton();
    registerButton(app);
    registerButton(menu);
    assert.equal(app.container.visible, false);
    assert.equal(menu.container.visible, true);
    settings.values['hide-app-name'] = false;
    manager.applyAll();
    assert.equal(app.container.visible, true);
    settings.values['hide-app-name'] = true;
    manager.applyAll();
    manager.destroy();
    assert.equal(app.container.visible, true, 'disable restores the button');
});

test('a visible app-name button is left alone', () => {
    const {manager, btn} = setup({'hide-app-name': false}, {appName: true});
    btn.container.visible = false;
    manager.destroy();
    assert.equal(btn.container.visible, false, 'hidden by someone else, not restored');
});

for (const scale of [1, 2]) {
    test(`first item text lines up with the title text at scale ${scale}, LTR`, () => {
        globalThis.gmTest.scale = scale;
        const nodes = {
            bar: node({border: 3 * scale, lengths: {'-natural-hpadding': 8 * scale}}),
            box: node({padding: 6 * scale, border: scale}),
            item: node({padding: 12 * scale}),
        };
        const {manager, btn} = setup({}, {nodes});
        onMenuOpened(btn);
        const left = 100 * scale, width = 40 * scale;
        // The source content box starts after the 3 px border, the text 8 px in
        const titleText = left + 8 * scale;
        const text = itemTextX(btn, {
            left: left + 3 * scale, width, natWidth: 200 * scale, scale, rtl: false,
            bodyInset: 19 * scale,
        });
        assert.ok(Math.abs(text - titleText) <= 1, `item text at ${text}, title text at ${titleText}`);
        manager.destroy();
        globalThis.gmTest.scale = 1;
    });
}

test('first item text lines up with the title text, RTL mirrored', () => {
    const {manager, btn} = setup({}, {rtl: true});
    onMenuOpened(btn);
    // Title content box [103, 143] in a button [100, 146]; text ends 8 px in
    const titleTextRight = 146 - 8;
    const textRight = itemTextX(btn, {
        left: 103, width: 40, natWidth: 200, scale: 1, rtl: true, bodyInset: 19,
    });
    assert.ok(Math.abs(textRight - titleTextRight) <= 1, `item text at ${textRight}, title text at ${titleTextRight}`);
    manager.destroy();
});

test('no shift when the item inset is not larger than the title inset', () => {
    const nodes = {bar: node({border: 0, lengths: {'-natural-hpadding': 30}})};
    const {manager, btn} = setup({}, {nodes});
    onMenuOpened(btn);
    assert.equal(btn.menu.actor.style, null);
    manager.destroy();
});

test('an empty menu gets no shift', () => {
    const {manager, btn} = setup({}, {firstItem: false});
    onMenuOpened(btn);
    assert.ok(!btn.menu.actor.style);
    manager.destroy();
});

test('the shift is cleared on revert', () => {
    const {manager, btn} = setup();
    onMenuOpened(btn);
    assert.ok(btn.menu.actor.style !== null);
    manager.destroy();
    assert.equal(btn.menu.actor.style, null);
});

test('submenu well radius is the popup radius minus padding and border', () => {
    const {manager, btn} = setup({'popup-corner-radius': 12});
    onMenuOpened(btn);
    assert.equal(btn.sub.menu.actor.style, 'border-radius: 0 0 5px 5px;');
    manager.destroy();
    assert.equal(btn.sub.menu.actor.style, null);
});

test('submenu well radius never goes below 0', () => {
    const {manager, btn} = setup({'popup-corner-radius': 4});
    onMenuOpened(btn);
    assert.equal(btn.sub.menu.actor.style, 'border-radius: 0 0 0px 0px;');
    manager.destroy();
});

test('hide-popup-arrow defaults to true in the schema', () => {
    const xml = readSource('schemas/org.gnome.shell.extensions.global-menu.gschema.xml');
    const key = /<key type="b" name="hide-popup-arrow">\s*<default>(\w+)<\/default>/.exec(xml);
    assert.equal(key?.[1], 'true');
});

test('hide-app-name is a boolean off by default in the schema', () => {
    const xml = readSource('schemas/org.gnome.shell.extensions.global-menu.gschema.xml');
    const key = /<key type="b" name="hide-app-name">\s*<default>(\w+)<\/default>/.exec(xml);
    assert.equal(key?.[1], 'false');
});

await run();
