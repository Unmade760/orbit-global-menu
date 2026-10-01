// accelerator.parseAccelerator: the one parser for every shortcut the extension
// sends, checked against the syntax in docs/shortcut-mappings.md.

import GLib from 'gi://GLib';

import {test, run, assert} from './lib/testlib.js';
import {EXT_DIR} from './lib/stubbed.js';

const {parseAccelerator} = await import(`file://${EXT_DIR}/accelerator.js`);

// X11 keysyms, the values accelerator.js uses (same as Clutter.KEY_*)
const CTRL = 0xffe3, SHIFT = 0xffe1, ALT = 0xffe9, SUPER = 0xffeb;

const chord = (modifiers, keyval) => ({modifiers, keyval});

test('single key with one modifier', () => {
    assert.deepEqual(parseAccelerator('<Ctrl>N'), [chord([CTRL], 0x6e)]);
});

test('Ctrl, Control and Primary are the same modifier', () => {
    const want = [chord([CTRL], 0x73)];
    assert.deepEqual(parseAccelerator('<Ctrl>s'), want);
    assert.deepEqual(parseAccelerator('<Control>s'), want);
    assert.deepEqual(parseAccelerator('<Primary>s'), want);
    assert.deepEqual(parseAccelerator('<ctrl>s'), want, 'modifier names are case-insensitive');
});

test('modifiers keep their written order and repeats collapse', () => {
    assert.deepEqual(parseAccelerator('<Ctrl><Shift>P'), [chord([CTRL, SHIFT], 0x70)]);
    assert.deepEqual(parseAccelerator('<Shift><Ctrl>P'), [chord([SHIFT, CTRL], 0x70)]);
    assert.deepEqual(parseAccelerator('<Ctrl><Primary>P'), [chord([CTRL], 0x70)]);
    assert.deepEqual(parseAccelerator('<Super><Alt>x'), [chord([SUPER, ALT], 0x78)]);
});

test('Meta and unknown modifiers are rejected', () => {
    assert.equal(parseAccelerator('<Meta>N'), null);
    assert.equal(parseAccelerator('<Hyper>N'), null);
    assert.equal(parseAccelerator('<Ctrl'), null);
});

test('a capital letter is not Shift', () => {
    assert.deepEqual(parseAccelerator('A'), [chord([], 0x61)]);
    assert.deepEqual(parseAccelerator('<Shift>a'), [chord([SHIFT], 0x61)]);
});

test('named keys from the documented list', () => {
    const cases = {
        F1: 0xffbe, F4: 0xffc1, F11: 0xffc8, F12: 0xffc9, Return: 0xff0d, Escape: 0xff1b,
        Tab: 0xff09, BackSpace: 0xff08, Delete: 0xffff, Home: 0xff50, End: 0xff57,
        Page_Up: 0xff55, Page_Down: 0xff56, Left: 0xff51, Up: 0xff52, Right: 0xff53,
        Down: 0xff54, Print: 0xff61, Insert: 0xff63, Menu: 0xff67, KP_0: 0xffb0,
        KP_9: 0xffb9, KP_Add: 0xffab, KP_Enter: 0xff8d, space: 0x20,
    };
    for (const [name, keyval] of Object.entries(cases))
        assert.deepEqual(parseAccelerator(name), [chord([], keyval)], name);
    assert.deepEqual(parseAccelerator('page_up'), [chord([], 0xff55)], 'keysym names are case-insensitive');
});

test('punctuation by character and by X11 name is the same shortcut', () => {
    const pairs = [['/', 'slash'], [',', 'comma'], ['?', 'question'], ['+', 'plus'], ['-', 'minus'],
        ['=', 'equal'], ['.', 'period'], ['[', 'bracketleft'], [']', 'bracketright'],
        ['\\', 'backslash'], ['`', 'grave'], [';', 'semicolon'], ["'", 'apostrophe'], ['~', 'asciitilde']];
    for (const [ch, name] of pairs)
        assert.deepEqual(parseAccelerator(`<Ctrl>${ch}`), parseAccelerator(`<Ctrl>${name}`), `${ch} vs ${name}`);
});

test('chord sequences split on a space', () => {
    assert.deepEqual(parseAccelerator('<Ctrl>x <Ctrl>s'), [chord([CTRL], 0x78), chord([CTRL], 0x73)]);
    assert.deepEqual(parseAccelerator(': w Return'), [chord([], 0x3a), chord([], 0x77), chord([], 0xff0d)]);
    assert.deepEqual(parseAccelerator('g g'), [chord([], 0x67), chord([], 0x67)]);
});

test('malformed strings are rejected', () => {
    for (const bad of ['', ' ', 'a  b', 'a ', ' a', '<Ctrl>', 'NotAKey', '<Ctrl>NotAKey', 'é', 'F13', null, undefined, 42])
        assert.equal(parseAccelerator(bad), null, JSON.stringify(bad));
});

// Modules both the shell process and the preferences process load. Best
// practices on gjs.guide: they must not import St, Clutter, Gtk, Gdk or Adw.
function resolve(fromRel, spec) {
    const parts = GLib.path_get_dirname(fromRel).split('/').filter(p => p && p !== '.');
    for (const part of spec.split('/')) {
        if (part === '..')
            parts.pop();
        else if (part !== '.')
            parts.push(part);
    }
    return parts.join('/');
}

function importsOf(rel) {
    const [, bytes] = GLib.file_get_contents(`${EXT_DIR}/${rel}`);
    const text = new TextDecoder().decode(bytes);
    const local = [], gi = [];
    for (const m of text.matchAll(/(?:from|import\()\s*'([^']+)'/g)) {
        if (m[1].startsWith('gi://'))
            gi.push(m[1].replace('gi://', '').replace(/\?.*/, ''));
        else if (m[1].startsWith('.'))
            local.push(resolve(rel, m[1]));
    }
    return {local, gi};
}

function reachable(entry) {
    const seen = new Map();
    const walk = rel => {
        if (seen.has(rel))
            return;
        const {local, gi} = importsOf(rel);
        seen.set(rel, gi);
        local.forEach(walk);
    };
    walk(entry);
    return seen;
}

test('modules shared by extension.js and prefs.js import no shell-only or GTK library', () => {
    const shell = reachable('extension.js');
    const prefs = reachable('prefs.js');
    const shared = [...prefs.keys()].filter(rel => shell.has(rel));
    assert.ok(shared.includes('accelerator.js'), 'accelerator.js is reached from both entry points');
    for (const rel of shared) {
        for (const lib of prefs.get(rel))
            assert.ok(!['Clutter', 'St', 'Gtk', 'Gdk', 'Adw'].includes(lib), `${rel} imports gi://${lib}`);
    }
});

test('the preferences process never loads keySynth.js', () => {
    assert.ok(!reachable('prefs.js').has('keySynth.js'), 'prefs.js reaches keySynth.js');
});

test('accelerator.js imports no library', () => {
    assert.deepEqual(importsOf('accelerator.js').gi, []);
});

await run();
