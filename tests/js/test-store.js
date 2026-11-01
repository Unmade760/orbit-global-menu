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
 * @param {boolean} load - read the files with loadAsync() or leave the store empty when false
 * @returns {Promise<ShortcutStore>} the store
 */
async function makeStore(builtins, users = [], index = null, load = true) {
    const root = GLib.dir_make_tmp('gm-store-XXXXXX');
    for (const [name, content] of builtins)
        writeJson(`${root}/builtin/apps/${name}`, content);
    writeJson(`${root}/builtin/index.json`, index ?? {format: 1, apps: builtins.map(([n]) => n)});
    for (const [name, content] of users)
        writeJson(`${root}/user/apps/${name}`, content);
    const store = new ShortcutStore(Gio.File.new_for_path(`${root}/builtin`), Gio.File.new_for_path(`${root}/user`));
    if (load)
        await store.loadAsync();
    return store;
}

const problems = store => store.warnings.filter(w => w.level !== 'info');

test('resolves by any identifier, lowercased', async () => {
    const store = await makeStore([['text.json', mapping('text', ['org.gnome.TextEditor.desktop', 'org.gnome.TextEditor', 'Text Editor'])]]);
    assert.deepEqual(problems(store), []);
    assert.equal(store.resolveMapping(['org.gnome.texteditor'])?.app, 'text');
    assert.equal(store.resolveMapping(['org.gnome.texteditor.desktop'])?.app, 'text');
    assert.equal(store.resolveMapping(['text editor'])?.app, 'text');
    assert.equal(store.resolveMapping(['nothing', 'else']), null);
});

test('matches when any candidate matches', async () => {
    const store = await makeStore([['a.json', mapping('a', ['a-class'])]]);
    assert.equal(store.resolveMapping(['a.desktop', 'a-class', 'A'])?.app, 'a');
});

test('identifier claimed twice: first in index order wins, with a warning', async () => {
    const store = await makeStore([['one.json', mapping('one', ['shared', 'one'])], ['two.json', mapping('two', ['SHARED', 'two'])]]);
    assert.equal(store.resolveMapping(['shared'])?.app, 'one');
    assert.equal(store.resolveMapping(['two'])?.app, 'two');
    const w = problems(store);
    assert.equal(w.length, 1);
    assert.ok(w[0].message.includes('"shared" already claimed by "one"'), w[0].message);
});

test('a user file replaces the built-in with the same app id', async () => {
    const user = mapping('ed', ['ed'], [{label: 'Mine', items: [{label: 'Save', shortcut: '<Ctrl>S'}]}]);
    const store = await makeStore([['ed.json', mapping('ed', ['ed'])]], [['ed.json', user]]);
    const hit = store.resolveMapping(['ed']);
    assert.equal(hit.builtin, false);
    assert.equal(hit.menus[0].label, 'Mine');
    assert.equal(store.mappings.size, 1);
});

test('a user file beats a built-in that claims the same identifier', async () => {
    const store = await makeStore([['a.json', mapping('a', ['shared'])]], [['b.json', mapping('b', ['shared'])]]);
    assert.equal(store.resolveMapping(['shared'])?.app, 'b');
});

test('a file missing from index.json is not loaded', async () => {
    const store = await makeStore([['a.json', mapping('a', ['a'])], ['b.json', mapping('b', ['b'])]], [], {format: 1, apps: ['a.json']});
    assert.equal(store.resolveMapping(['b']), null);
    assert.equal(store.mappings.size, 1);
});

test('a broken built-in is reported and the rest still load', async () => {
    const store = await makeStore([['bad.json', '{"format": 1,'], ['good.json', mapping('good', ['good'])]]);
    assert.equal(store.resolveMapping(['good'])?.app, 'good');
    assert.ok(problems(store).some(w => w.file === 'bad.json'), 'warning for bad.json');
});

test('listKnownAppIds lists built-ins and user files, sorted', async () => {
    const store = await makeStore([['b.json', mapping('b', ['b'])], ['a.json', mapping('a', ['a'])]], [['c.json', mapping('c', ['c'])]]);
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

// loadAsync(): the same files, read without blocking

// Each fixture is a directory of its own, and one warning names it
const snapshot = store => JSON.stringify({
    mappings: [...store.mappings.entries()],
    resolved: ['shared', 'a', 'b', 'c', 'u'].map(id => store.resolveMapping([id])?.app ?? null),
    warnings: store.warnings,
}).replace(/gm-store-\w+/g, 'gm-store');

function mixedFixture(load) {
    return makeStore([
        ['a.json', mapping('a', ['shared', 'a'])],
        ['b.json', mapping('b', ['shared', 'b'], [{label: 'File', items: [{label: 'Bad', shortcut: '<Meta>Z'}]}])],
        ['broken.json', '{not json'],
        ['c.json', mapping('wrong-id', ['c'])],
        ['d.json', mapping('d', ['d'])],
    ], [
        ['u.json', mapping('u', ['u'])],
        ['d.json', mapping('d', ['d2'], [{label: 'Mine', items: []}])],
        ['skipped.txt', 'not a mapping'],
        ['bad.json', '[]'],
    ], {format: 1, apps: ['a.json', 'b.json', 'broken.json', 'c.json', 'd.json', 5, 'gone.json']}, load);
}

test('loadAsync() keeps good files, reports bad ones and lists every known app', async () => {
    const store = await mixedFixture(false);
    assert.equal(store.mappings.size, 0, 'nothing is read before loadAsync');
    await store.loadAsync();
    assert.deepEqual([...store.mappings.keys()].sort(), ['a', 'b', 'd', 'u']);
    assert.equal(store.mappings.get('d').builtin, false, 'user d.json replaces the built-in');
    assert.equal(store.resolveMapping(['shared'])?.app, 'a');
    for (const file of ['broken.json', 'c.json', 'gone.json', 'bad.json', 'index.json'])
        assert.ok(problems(store).some(w => w.file === file), `warning for ${file}`);
    assert.deepEqual(store.listKnownAppIds().map(e => e.app),
        ['a', 'b', 'bad', 'broken', 'c', 'd', 'gone', 'u']);
});

test('loadAsync() reads a user directory larger than one enumeration batch', async () => {
    const users = Array.from({length: 230}, (_v, i) => [`app${i}.json`, mapping(`app${i}`, [`id${i}`])]);
    const store = await makeStore([], users, null, false);
    await store.loadAsync();
    assert.equal(store.mappings.size, 230);
    assert.equal(store.resolveMapping(['id229'])?.app, 'app229');
});

test('loadAsync() with no user directory loads the built-ins', async () => {
    const root = GLib.dir_make_tmp('gm-store-XXXXXX');
    writeJson(`${root}/builtin/apps/a.json`, mapping('a', ['a']));
    writeJson(`${root}/builtin/index.json`, {format: 1, apps: ['a.json']});
    const store = new ShortcutStore(Gio.File.new_for_path(`${root}/builtin`), Gio.File.new_for_path(`${root}/missing`));
    await store.loadAsync();
    assert.equal(store.resolveMapping(['a'])?.app, 'a');
    assert.deepEqual(store.warnings, []);
});

test('a cancelled loadAsync() rejects as cancelled and keeps what the store had', async () => {
    const store = await makeStore([['a.json', mapping('a', ['a'])]]);
    const before = snapshot(store);
    const cancellable = new Gio.Cancellable();
    const done = store.loadAsync(cancellable);
    cancellable.cancel();
    let error = null;
    try {
        await done;
    } catch (e) {
        error = e;
    }
    assert.ok(error?.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED), `rejected with ${error}`);
    assert.equal(snapshot(store), before);
});

await run();
