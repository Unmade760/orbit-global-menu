// Shortcut labels, Design Language "Type" rule 4: labels are written the way
// GTK 4 writes accelerator labels (Ctrl+S, Shift+Ctrl+S, Ctrl+,), and a chord
// sequence is joined with a space (Ctrl+K Ctrl+S).
//
// Two parts:
//   1. The expected table is pinned against Gtk.accelerator_get_label from
//      GTK 4 itself, so the table is GTK's wording and not ours.
//   2. The extension's own label formatter must produce the same table. The
//      extension has no shell-side formatter yet (feature F2), so part 2
//      skips until one of the export names below appears in keySynth.js.

import Gtk from 'gi://Gtk?version=4.0';

import {test, skip, run, assert} from './lib/testlib.js';
import {EXT_DIR} from './lib/stubbed.js';

// Names the formatter may be exported under from keySynth.js. When F2 lands
// under another name, add it here.
const FORMATTER_NAMES = ['acceleratorLabel', 'formatAccelerator', 'shortcutLabel', 'accelLabel'];

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

test('expected labels are what GTK 4 prints (Gtk.accelerator_get_label)', () => {
    for (const [accel, want] of [...SINGLE, ...SEQUENCES])
        assert.equal(gtkLabel(accel), want, accel);
});

const keySynth = await import(`file://${EXT_DIR}/keySynth.js`);
const formatterName = FORMATTER_NAMES.find(n => typeof keySynth[n] === 'function');

if (formatterName) {
    const format = keySynth[formatterName];
    test(`keySynth.${formatterName} matches GTK 4 for single chords`, () => {
        for (const [accel, want] of SINGLE)
            assert.equal(format(accel), want, accel);
    });
    test(`keySynth.${formatterName} joins chord sequences with a space`, () => {
        for (const [accel, want] of SEQUENCES)
            assert.equal(format(accel), want, accel);
    });
    test(`keySynth.${formatterName} returns null for an unparseable shortcut`, () => {
        assert.equal(format('<Meta>x') ?? null, null);
    });
} else {
    const why = `no label formatter exported from keySynth.js yet (looked for ${FORMATTER_NAMES.join(', ')}); ` +
        'shortcut labels are feature F2, not built';
    skip('extension formats single chords like GTK 4', why);
    skip('extension joins chord sequences with a space', why);
    skip('extension returns null for an unparseable shortcut', why);
}

await run();
