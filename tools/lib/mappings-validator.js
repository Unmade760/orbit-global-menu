// Validator for `tools/check.sh mappings`. Run with `gjs -m`.
//
//   gjs -m mappings-validator.js <extdir> <summary.json>
//
// Checks every built-in shortcut mapping under <extdir>/shortcuts against
// docs/shortcut-mappings.md, using the extension's own code wherever the
// extension has code for it:
//   - parseAccelerator() from accelerator.js decides whether a shortcut parses
//   - validateMapping() from shortcutStore.js must accept the file without
//     dropping anything
//   - ShortcutStore.load() must load every file with no warning, and
//     resolveMapping() must send each identifier back to its own file
// On top of that it checks what the extension does not: strict JSON, the
// exact key set of each object, identifiers claimed by two files, and
// index.json listing exactly the files present.
//
// Prints one line per file with its counts, one "ERROR <file>: <reason>"
// line per problem, and writes a JSON summary for the coverage auditors.
// Exits 0 when there are no errors, 1 otherwise.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import System from 'system';

const [extdir, summaryPath] = ARGV;
if (!extdir || !summaryPath) {
    print('usage: gjs -m mappings-validator.js <extdir> <summary.json>');
    System.exit(2);
}

const uriOf = path => Gio.File.new_for_path(path).get_uri();
const {parseAccelerator} = await import(uriOf(`${extdir}/accelerator.js`));
const {validateMapping, ShortcutStore} = await import(uriOf(`${extdir}/shortcutStore.js`));

const shortcutsDir = `${extdir}/shortcuts`;
const appsDir = `${shortcutsDir}/apps`;
const strictDecoder = new TextDecoder('utf-8', {fatal: true});

const errors = [];
const files = {};

function error(file, message) {
    errors.push({file, message});
    if (files[file.replace(/\.json$/, '')])
        files[file.replace(/\.json$/, '')].errors.push(message);
}

function readStrictJson(path) {
    const [, bytes] = GLib.file_get_contents(path);
    return JSON.parse(strictDecoder.decode(bytes));
}

function listJsonFiles(dir) {
    const out = [];
    const enumerator = Gio.File.new_for_path(dir).enumerate_children(
        'standard::name,standard::type', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
    let info;
    while ((info = enumerator.next_file(null))) {
        if (info.get_name().endsWith('.json'))
            out.push(info.get_name());
    }
    enumerator.close(null);
    return out.sort();
}

const isObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const nonEmptyString = v => typeof v === 'string' && v !== '';

function exactKeys(obj, allowed) {
    const extra = Object.keys(obj).filter(k => !allowed.includes(k));
    return extra.length ? `unknown key(s) ${extra.map(k => JSON.stringify(k)).join(', ')}` : null;
}

// The four item shapes of docs/shortcut-mappings.md, and nothing else.
function checkItems(items, path, counts, report) {
    if (!Array.isArray(items)) {
        report(`${path}: "items" is not an array`);
        return;
    }
    if (items.length === 0)
        report(`${path}: empty "items"`);
    items.forEach((item, i) => {
        const where = `${path} [${i}]`;
        if (!isObject(item)) {
            report(`${where}: item is not an object`);
            return;
        }
        if ('separator' in item) {
            if (item.separator !== true)
                report(`${where}: "separator" must be true`);
            const extra = exactKeys(item, ['separator']);
            if (extra)
                report(`${where}: separator with ${extra}`);
            counts.separators++;
            return;
        }
        if (!nonEmptyString(item.label)) {
            report(`${where}: missing or empty "label"`);
            return;
        }
        const itemPath = `${path} » ${item.label}`;
        if ('items' in item) {
            const extra = exactKeys(item, ['label', 'items']);
            if (extra)
                report(`${itemPath}: submenu with ${extra}`);
            counts.submenus++;
            checkItems(item.items, itemPath, counts, report);
            return;
        }
        const extra = exactKeys(item, ['label', 'shortcut']);
        if (extra)
            report(`${itemPath}: ${extra}`);
        counts.items++;
        if (!('shortcut' in item)) {
            counts.placeholders++;
            return;
        }
        if (typeof item.shortcut !== 'string') {
            report(`${itemPath}: "shortcut" is not a string`);
            return;
        }
        const chords = parseAccelerator(item.shortcut);
        if (!chords) {
            report(`${itemPath}: shortcut ${JSON.stringify(item.shortcut)} does not parse with accelerator.parseAccelerator`);
            return;
        }
        counts.withShortcut++;
        if (chords.length > 1)
            counts.chordSequences++;
    });
}

function checkFile(name) {
    const stem = name.slice(0, -'.json'.length);
    const entry = {
        file: name, name: null, identifiers: [],
        menus: 0, items: 0, withShortcut: 0, placeholders: 0,
        submenus: 0, separators: 0, chordSequences: 0, duplicateShortcuts: 0,
        errors: [],
    };
    files[stem] = entry;
    const report = message => error(name, message);

    let raw;
    try {
        raw = readStrictJson(`${appsDir}/${name}`);
    } catch (e) {
        report(`not valid JSON: ${e.message}`);
        return null;
    }
    if (!isObject(raw)) {
        report('top level is not a JSON object');
        return null;
    }
    const extra = exactKeys(raw, ['format', 'app', 'name', 'identifiers', 'menus', 'blank']);
    if (extra)
        report(`top level has ${extra}`);
    if (raw.format !== 1)
        report(`"format" is ${JSON.stringify(raw.format)}, expected 1`);
    if (raw.app !== stem)
        report(`"app" is ${JSON.stringify(raw.app)}, must equal the file name stem "${stem}"`);
    if (!nonEmptyString(raw.name))
        report('"name" missing or empty');
    entry.name = raw.name ?? null;
    if (!Array.isArray(raw.identifiers) || raw.identifiers.length === 0) {
        report('"identifiers" missing or empty');
    } else {
        raw.identifiers.forEach((id, i) => {
            if (!nonEmptyString(id) || id.trim() !== id)
                report(`identifiers[${i}] ${JSON.stringify(id)} is not a trimmed non-empty string`);
        });
        entry.identifiers = raw.identifiers.filter(nonEmptyString);
    }
    if (raw.blank !== undefined && raw.blank !== true)
        report('"blank" may only be true');
    if (raw.blank === true) {
        if (!Array.isArray(raw.menus) || raw.menus.length !== 0)
            report('a blank mapping needs "menus": []');
    } else if (!Array.isArray(raw.menus) || raw.menus.length === 0) {
        report('"menus" missing or empty');
    } else {
        raw.menus.forEach((menu, i) => {
            if (!isObject(menu) || !nonEmptyString(menu.label)) {
                report(`menus[${i}]: need {label, items}`);
                return;
            }
            const menuExtra = exactKeys(menu, ['label', 'items']);
            if (menuExtra)
                report(`menu "${menu.label}" has ${menuExtra}`);
            entry.menus++;
            checkItems(menu.items, menu.label, entry, report);
        });
    }

    // The extension's own validator must take the file as it is: any
    // warning from it means the running extension drops part of the file.
    const warnings = [];
    const mapping = validateMapping(raw, stem, warnings);
    for (const w of warnings)
        report(`shortcutStore.validateMapping: ${w.message}`);
    if (!mapping)
        report('shortcutStore.validateMapping rejects the file');
    return mapping;
}

// Files on disk
const onDisk = listJsonFiles(appsDir);
for (const name of onDisk)
    checkFile(name);

// index.json lists exactly the files present, once each
let index = null;
try {
    index = readStrictJson(`${shortcutsDir}/index.json`);
} catch (e) {
    error('index.json', `not valid JSON: ${e.message}`);
}
if (index) {
    const extra = isObject(index) ? exactKeys(index, ['format', 'apps']) : 'not an object';
    if (extra)
        error('index.json', extra);
    if (index.format !== 1)
        error('index.json', `"format" is ${JSON.stringify(index.format)}, expected 1`);
    const listed = Array.isArray(index.apps) ? index.apps : [];
    if (!Array.isArray(index.apps))
        error('index.json', '"apps" is not an array');
    const seen = new Set();
    for (const name of listed) {
        if (typeof name !== 'string' || !name.endsWith('.json')) {
            error('index.json', `entry ${JSON.stringify(name)} is not a "<app>.json" file name`);
            continue;
        }
        if (seen.has(name))
            error('index.json', `lists ${name} twice`);
        seen.add(name);
        if (!onDisk.includes(name))
            error('index.json', `lists ${name}, which is not in shortcuts/apps`);
    }
    for (const name of onDisk) {
        if (!seen.has(name))
            error('index.json', `does not list ${name}, so the extension never loads it`);
    }
}

// Identifiers are matched lowercased, so two files must not claim the same
// lowercased identifier
const owners = new Map();
for (const [stem, entry] of Object.entries(files)) {
    for (const id of new Set(entry.identifiers.map(i => i.toLowerCase()))) {
        if (!owners.has(id))
            owners.set(id, []);
        owners.get(id).push(stem);
    }
}
for (const [id, stems] of owners) {
    if (stems.length > 1) {
        for (const stem of stems)
            error(`${stem}.json`, `identifier "${id}" is also claimed by ${stems.filter(s => s !== stem).join(', ')}`);
    }
}

// The real store, end to end, with an empty user directory
const emptyUserDir = GLib.dir_make_tmp('gm-mappings-XXXXXX');
const store = new ShortcutStore(Gio.File.new_for_path(shortcutsDir), Gio.File.new_for_path(emptyUserDir));
store.load();
GLib.rmdir(emptyUserDir);
for (const w of store.warnings) {
    if (w.level === 'info') {
        const stem = w.file.replace(/\.json$/, '');
        if (files[stem] && w.message.startsWith('Duplicate shortcut'))
            files[stem].duplicateShortcuts++;
        continue;
    }
    error(w.file, `ShortcutStore.load: ${w.message}`);
}
if (store.mappings.size !== onDisk.length)
    error('index.json', `ShortcutStore loaded ${store.mappings.size} mappings, ${onDisk.length} files are on disk`);
for (const [stem, entry] of Object.entries(files)) {
    for (const id of entry.identifiers) {
        const hit = store.resolveMapping([id.toLowerCase()]);
        if (hit?.app !== stem && owners.get(id.toLowerCase())?.length === 1)
            error(`${stem}.json`, `resolveMapping(["${id.toLowerCase()}"]) returns ${hit ? hit.app : 'null'}`);
    }
}

// Report
const totals = {
    files: onDisk.length, menus: 0, items: 0, withShortcut: 0, placeholders: 0,
    submenus: 0, separators: 0, chordSequences: 0, duplicateShortcuts: 0, identifiers: owners.size,
};
for (const entry of Object.values(files)) {
    for (const k of ['menus', 'items', 'withShortcut', 'placeholders', 'submenus', 'separators', 'chordSequences', 'duplicateShortcuts'])
        totals[k] += entry[k];
    print(`${entry.file}: menus ${entry.menus}, items ${entry.items}, with shortcut ${entry.withShortcut}, ` +
        `placeholders ${entry.placeholders}, submenus ${entry.submenus}, chords ${entry.chordSequences}, ` +
        `duplicate shortcuts ${entry.duplicateShortcuts}${entry.errors.length ? `, ERRORS ${entry.errors.length}` : ''}`);
}
for (const e of errors)
    print(`ERROR ${e.file}: ${e.message}`);

const summary = {
    generated: new Date().toISOString(),
    extdir,
    counting: 'items = leaf entries with a label (shortcut or placeholder); submenus and separators counted apart; ' +
        'chordSequences = shortcuts with more than one chord; duplicateShortcuts = info findings from ShortcutStore',
    ok: errors.length === 0,
    totals,
    errors,
    files,
};
GLib.file_set_contents(summaryPath, new TextEncoder().encode(`${JSON.stringify(summary, null, 2)}\n`));

print(`TOTAL files ${totals.files}, menus ${totals.menus}, items ${totals.items}, with shortcut ${totals.withShortcut}, ` +
    `placeholders ${totals.placeholders}, submenus ${totals.submenus}, identifiers ${totals.identifiers}, errors ${errors.length}`);
System.exit(errors.length ? 1 : 0);
