// Shortcut labels, Design Language "Type" rule 4: labels are written the way
// GTK 4 writes accelerator labels (Ctrl+S, Shift+Ctrl+S, Ctrl+,), and a chord
// sequence is joined with a space (Ctrl+K Ctrl+S).
//
// Two parts:
//   1. The expected table is pinned against Gtk.accelerator_get_label from
//      GTK 4 itself, so the table is GTK's wording and not ours.
//   2. acceleratorLabel() from accelerator.js must produce the same table,
//      from its own word list, whatever the locale. GTK translates its key
//      names, so part 1 runs only under an English locale (tools/checks/unit.sh
//      sets one when it exists) and is skipped otherwise.

import Gtk from 'gi://Gtk?version=4.0';

import {test, skip, run, assert} from './lib/testlib.js';
import {EXT_DIR} from './lib/stubbed.js';

const {acceleratorLabel} = await import(`file://${EXT_DIR}/accelerator.js`);

// [accelerator string as written in a mapping, label GTK 4 gives it]
const SINGLE = [
    ['<Ctrl>S', 'Ctrl+S'],
    ['<Ctrl><Shift>S', 'Shift+Ctrl+S'],
    ['<Shift><Ctrl>S', 'Shift+Ctrl+S'],
    ['<Alt>F4', 'Alt+F4'],
    ['<Ctrl>comma', 'Ctrl+,'],
    ['<Ctrl>,', 'Ctrl+,'],
    ['<Super>Left', 'Super+Left'],
    ['<Primary>question', 'Ctrl+?'],
    ['<Ctrl>plus', 'Ctrl++'],
    ['<Ctrl>space', 'Ctrl+Space'],
    ['<Shift><Ctrl><Alt><Super>a', 'Shift+Ctrl+Alt+Super+A'],
    ['F11', 'F11'],
    ['Delete', 'Delete'],
    ['Page_Up', 'Page Up'],
    ['BackSpace', 'Backspace'],
    ['<Ctrl>Tab', 'Ctrl+Tab'],
    ['<Shift>a', 'Shift+A'],
    ['<Control>S', 'Ctrl+S'],
    ['<Control><Shift>S', 'Shift+Ctrl+S'],
    ['<Primary>s', 'Ctrl+S'],
    ['<Ctrl>backslash', 'Ctrl+Backslash'],
    ['<Ctrl>KP_Enter', 'Ctrl+Enter (keypad)'],
    ['<Ctrl>KP_Add', 'Ctrl+KP\u2009+'],
    ['KP_5', 'KP\u20095'],
    ['Return', 'Return'],
    ['Escape', 'Escape'],
    ['<Alt>Down', 'Alt+Down'],
    ['<Ctrl>Page_Down', 'Ctrl+Page Down'],
    ['<Ctrl><Alt>Delete', 'Ctrl+Alt+Delete'],
    ['<Super>Print', 'Super+Print'],
];
// Every key name the parser knows, for the comparison with GTK
const NAMED_KEYS = [
    ...Array.from({length: 12}, (_v, i) => `F${i + 1}`),
    'Return', 'Escape', 'Tab', 'BackSpace', 'Delete', 'Home', 'End', 'Page_Up', 'Page_Down',
    'Left', 'Up', 'Right', 'Down', 'space', 'Print', 'Insert', 'Menu',
    ...Array.from({length: 10}, (_v, i) => `KP_${i}`),
    'KP_Decimal', 'KP_Add', 'KP_Subtract', 'KP_Multiply', 'KP_Divide', 'KP_Enter',
    'exclam', 'quotedbl', 'numbersign', 'dollar', 'percent', 'ampersand', 'apostrophe',
    'parenleft', 'parenright', 'asterisk', 'plus', 'comma', 'minus', 'period', 'slash',
    'colon', 'semicolon', 'less', 'equal', 'greater', 'question', 'at', 'bracketleft',
    'backslash', 'bracketright', 'asciicircum', 'underscore', 'grave', 'braceleft', 'bar',
    'braceright', 'asciitilde',
];

const SEQUENCES = [
    ['<Ctrl>k <Ctrl>s', 'Ctrl+K Ctrl+S'],
    ['<Ctrl>x <Ctrl>s', 'Ctrl+X Ctrl+S'],
    ['g g', 'G G'],
];

// GTK does not know <Ctrl>, only <Control> and <Primary>, and it wants the
// X11 name for punctuation.
const PUNCT = {',': 'comma', '/': 'slash', '?': 'question', '+': 'plus'};
function toGtkSyntax(accel) {
    return accel.replace(/<Ctrl>/gi, '<Control>').replace(/>([,/?+])$/, (_m, c) => `>${PUNCT[c]}`);
}

function gtkLabel(accel) {
    return accel.split(' ').map(chord => {
        const [ok, keyval, mods] = Gtk.accelerator_parse(toGtkSyntax(chord));
        if (!ok)
            throw new Error(`GTK cannot parse ${chord}`);
        return Gtk.accelerator_get_label(keyval, mods);
    }).join(' ');
}

const englishGtk = Gtk.accelerator_get_label(Gtk.accelerator_parse('BackSpace')[1], 0) === 'Backspace';

if (englishGtk) {
    test('expected labels are what GTK 4 prints (Gtk.accelerator_get_label)', () => {
        for (const [accel, want] of [...SINGLE, ...SEQUENCES])
            assert.equal(gtkLabel(accel), want, accel);
    });
    test('every named key is labelled as GTK 4 labels it', () => {
        for (const name of NAMED_KEYS)
            assert.equal(acceleratorLabel(name), gtkLabel(name), name);
    });
} else {
    const why = 'GTK is not running under an English locale, so its key names are not the pinned wording';
    skip('expected labels are what GTK 4 prints (Gtk.accelerator_get_label)', why);
    skip('every named key is labelled as GTK 4 labels it', why);
}

test('acceleratorLabel gives the pinned label for single chords', () => {
    for (const [accel, want] of SINGLE)
        assert.equal(acceleratorLabel(accel), want, accel);
});

test('acceleratorLabel joins chord sequences with a space', () => {
    for (const [accel, want] of SEQUENCES)
        assert.equal(acceleratorLabel(accel), want, accel);
});

test('acceleratorLabel returns null for a shortcut that does not parse', () => {
    for (const bad of ['<Meta>x', '', 'NotAKey', '<Ctrl>', 'a  b', null, undefined, 42])
        assert.equal(acceleratorLabel(bad), null, JSON.stringify(bad));
});

await run();
