// shortcutStore.js: validateMapping and mapping resolution by identifier,
// on fixture trees built in $TMPDIR.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {test, run, assert} from './lib/testlib.js';
import {EXT_DIR} from './lib/stubbed.js';

const {ShortcutStore, validateMapping} = await import(`file://${EXT_DIR}/shortcutStore.js`);

const encoder = new TextEncoder();

function writeJson(path, value) {
    GLib.mkdir_with_parents(GLib.path_get_dirname(path), 0o755);
    GLib.file_set_contents(path, encoder.encode(typeof value === 'string' ? value : JSON.stringify(value)));
}

function mapping(app, identifiers, menus = [{label: 'File', items: [{label: 'Quit', shortcut: '<Ctrl>Q'}]}]) {
    return {format: 1, app, name: app, identifiers, menus};
}

/**
 * Build a builtin and a user tree under $TMPDIR and load a store on them.
 *
 * @param {Array} builtins - [[fileName, content]] in index order
 * @param {Array} users - [[fileName, content]], any order
 * @param {object|null} index - index.json content, default lists builtins
 * @returns {ShortcutStore} the loaded store
 */
function makeStore(builtins, users = [], index = null) {
    const root = GLib.dir_make_tmp('gm-store-XXXXXX');
    for (const [name, content] of builtins)
        writeJson(`${root}/builtin/apps/${name}`, content);
    writeJson(`${root}/builtin/index.json`, index ?? {format: 1, apps: builtins.map(([n]) => n)});
    for (const [name, content] of users)
        writeJson(`${root}/user/apps/${name}`, content);
    const store = new ShortcutStore(Gio.File.new_for_path(`${root}/builtin`), Gio.File.new_for_path(`${root}/user`));
    store.load();
    return store;
}

const problems = store => store.warnings.filter(w => w.level !== 'info');

test('resolves by any identifier, lowercased', () => {
    const store = makeStore([['text.json', mapping('text', ['org.gnome.TextEditor.desktop', 'org.gnome.TextEditor', 'Text Editor'])]]);
    assert.deepEqual(problems(store), []);
    assert.equal(store.resolveMapping(['org.gnome.texteditor'])?.app, 'text');
    assert.equal(store.resolveMapping(['org.gnome.texteditor.desktop'])?.app, 'text');
    assert.equal(store.resolveMapping(['text editor'])?.app, 'text');
    assert.equal(store.resolveMapping(['nothing', 'else']), null);
});

test('matches when any candidate matches', () => {
    const store = makeStore([['a.json', mapping('a', ['a-class'])]]);
    assert.equal(store.resolveMapping(['a.desktop', 'a-class', 'A'])?.app, 'a');
});

test('identifier claimed twice: first in index order wins, with a warning', () => {
    const store = makeStore([['one.json', mapping('one', ['shared', 'one'])], ['two.json', mapping('two', ['SHARED', 'two'])]]);
    assert.equal(store.resolveMapping(['shared'])?.app, 'one');
    assert.equal(store.resolveMapping(['two'])?.app, 'two');
    const w = problems(store);
    assert.equal(w.length, 1);
    assert.ok(w[0].message.includes('"shared" already claimed by "one"'), w[0].message);
});

test('a user file replaces the built-in with the same app id', () => {
    const user = mapping('ed', ['ed'], [{label: 'Mine', items: [{label: 'Save', shortcut: '<Ctrl>S'}]}]);
    const store = makeStore([['ed.json', mapping('ed', ['ed'])]], [['ed.json', user]]);
    const hit = store.resolveMapping(['ed']);
    assert.equal(hit.builtin, false);
    assert.equal(hit.menus[0].label, 'Mine');
    assert.equal(store.mappings.size, 1);
});

test('a user file beats a built-in that claims the same identifier', () => {
    const store = makeStore([['a.json', mapping('a', ['shared'])]], [['b.json', mapping('b', ['shared'])]]);
    assert.equal(store.resolveMapping(['shared'])?.app, 'b');
});

test('a file missing from index.json is not loaded', () => {
    const store = makeStore([['a.json', mapping('a', ['a'])], ['b.json', mapping('b', ['b'])]], [], {format: 1, apps: ['a.json']});
    assert.equal(store.resolveMapping(['b']), null);
    assert.equal(store.mappings.size, 1);
});

test('a broken built-in is reported and the rest still load', () => {
    const store = makeStore([['bad.json', '{"format": 1,'], ['good.json', mapping('good', ['good'])]]);
    assert.equal(store.resolveMapping(['good'])?.app, 'good');
    assert.ok(problems(store).some(w => w.file === 'bad.json'), 'warning for bad.json');
});

test('listKnownAppIds lists built-ins and user files, sorted', () => {
    const store = makeStore([['b.json', mapping('b', ['b'])], ['a.json', mapping('a', ['a'])]], [['c.json', mapping('c', ['c'])]]);
    assert.deepEqual(store.listKnownAppIds(), [
        {app: 'a', hasBuiltin: true, hasUser: false},
        {app: 'b', hasBuiltin: true, hasUser: false},
        {app: 'c', hasBuiltin: false, hasUser: true},
    ]);
});

test('validateMapping keeps separators, placeholders and submenus, drops bad shortcuts', () => {
    const warnings = [];
    const out = validateMapping(mapping('x', ['X'], [{
        label: 'Edit',
        items: [
            {label: 'Undo', shortcut: '<Ctrl>Z'},
            {separator: true},
            {label: 'Only by Mouse'},
            {label: 'Broken', shortcut: '<Meta>Z'},
            {label: 'More', items: [{label: 'Deep', shortcut: 'F5'}]},
        ],
    }]), 'x', warnings);
    assert.deepEqual(out.identifiers, ['x']);
    assert.deepEqual(out.menus[0].items, [
        {label: 'Undo', shortcut: '<Ctrl>Z'},
        {separator: true},
        {label: 'Only by Mouse'},
        {label: 'More', items: [{label: 'Deep', shortcut: 'F5'}]},
    ]);
    assert.equal(warnings.length, 1);
    assert.ok(warnings[0].message.includes('unparseable shortcut "<Meta>Z"'), warnings[0].message);
});

test('validateMapping rejects a wrong format, app id or empty identifiers', () => {
    for (const [raw, why] of [
        [{...mapping('x', ['x']), format: 2}, 'format'],
        [mapping('y', ['x']), 'app id'],
        [mapping('x', []), 'identifiers'],
        [mapping('x', ['  ']), 'blank identifier'],
        [[], 'array'],
    ]) {
        const warnings = [];
        assert.equal(validateMapping(raw, 'x', warnings), null, why);
        assert.equal(warnings.length, 1, why);
    }
});

test('validateMapping keeps a blank mapping with no menus', () => {
    const warnings = [];
    const out = validateMapping({...mapping('x', ['X'], []), blank: true}, 'x', warnings);
    assert.equal(out.blank, true);
    assert.deepEqual(out.menus, []);
    assert.equal(validateMapping(mapping('x', ['X']), 'x', []).blank, false);
});

await run();
