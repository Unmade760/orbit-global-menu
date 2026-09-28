// Runtime half of `tools/check.sh compat`. Runs inside a distro image
// (tools/compat/in-container.sh probe) under that distro's gjs, with
// GI_TYPELIB_PATH at mutter's and gnome-shell's private typelib directories.
//
//   gjs -m probe.js <shell|prefs> <probe.json> <out.json>
//
// probe.json is written by resolve.mjs analyze. Every check names a symbol
// the extension uses; this reports whether this gjs and these typelibs have
// it, without calling anything: presence is tested with `in` and property
// descriptors, so no getter runs (Gio.DBus.session would open a bus).
// For an introspected function it also reports gjs's own arity (the
// Function length getter returns the number of JS arguments gjs requires).
//
// The shell and preferences processes load different libraries (St and
// Meta against GTK 4 and libadwaita), so each mode imports only its own
// namespaces, the way the real processes do.

import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import System from 'system';

const [mode, listPath, outPath] = ARGV;
if (!['shell', 'prefs'].includes(mode) || !listPath || !outPath) {
    printerr('usage: gjs -m probe.js <shell|prefs> <probe.json> <out.json>');
    System.exit(2);
}

const decoder = new TextDecoder();
const list = JSON.parse(decoder.decode(GLib.file_get_contents(listPath)[1]));

// Versions the preferences process asks for. The shell process loads
// whatever single version of its namespaces is installed.
const PREFS_VERSIONS = {Gtk: '4.0', Gdk: '4.0', Gsk: '4.0', Adw: '1'};
const SHELL_ONLY = new Set(['Meta', 'Clutter', 'Cogl', 'Mtk', 'St', 'Shell', 'Gvc']);
const PREFS_ONLY = new Set(['Gtk', 'Gdk', 'Gsk', 'Adw']);

function wanted(check) {
    return check.proc === 'both' || check.proc === mode;
}

const namespaces = {};
async function loadNamespace(ns) {
    if (ns in namespaces)
        return namespaces[ns].module;
    if ((mode === 'shell' && PREFS_ONLY.has(ns)) || (mode === 'prefs' && SHELL_ONLY.has(ns))) {
        namespaces[ns] = {ok: false, error: `not loaded in the ${mode} process`, module: null};
        return null;
    }
    const version = mode === 'prefs' ? PREFS_VERSIONS[ns] : undefined;
    const spec = version ? `gi://${ns}?version=${version}` : `gi://${ns}`;
    try {
        const module = (await import(spec)).default;
        namespaces[ns] = {ok: true, spec, module};
    } catch (e) {
        namespaces[ns] = {ok: false, spec, error: String(e.message ?? e), module: null};
    }
    return namespaces[ns].module;
}

// Walks the prototype chain for an own descriptor, so a getter is described
// rather than invoked.
function describe(obj, name) {
    for (let o = obj; o; o = Object.getPrototypeOf(o)) {
        let desc;
        try {
            desc = Object.getOwnPropertyDescriptor(o, name);
        } catch (e) {
            return {present: true, type: 'unknown'};
        }
        if (!desc)
            continue;
        if (!('value' in desc))
            return {present: true, type: 'accessor'};
        const value = desc.value;
        const info = {present: true, type: typeof value};
        if (typeof value === 'function') {
            // Introspected functions are gjs Function objects: their own
            // toString names the C symbol, Function.prototype.toString
            // throws on them, and length is the argument count gjs
            // enforces.
            try {
                info.length = value.length;
                const text = String(value);
                info.native = /wrapper for native symbol/.test(text);
                const sym = text.match(/native symbol (\w+)\(\)/);
                if (sym)
                    info.symbol = sym[1];
            } catch (e) {
                info.describeError = String(e.message ?? e);
            }
        }
        return info;
    }
    return {present: false};
}

function probeIn(obj, name) {
    if (obj === null || obj === undefined)
        return {present: false, error: 'owner missing'};
    let present;
    try {
        present = name in Object(obj);
    } catch (e) {
        return {present: false, error: String(e.message ?? e)};
    }
    if (!present)
        return {present: false};
    return describe(obj, name);
}

// A static path such as Gio.DBus: own data properties only, never a getter.
function walkPath(root, path) {
    let obj = root;
    for (const step of path) {
        if (obj === null || obj === undefined)
            return undefined;
        const desc = describe(obj, step);
        if (!desc.present || desc.type === 'accessor' || desc.type === 'unknown')
            return undefined;
        obj = obj[step];
    }
    return obj;
}

async function runCheck(check) {
    const NS = await loadNamespace(check.ns);
    if (!NS)
        return {present: false, error: namespaces[check.ns].error ?? 'namespace missing'};
    switch (check.kind) {
    case 'namespace':
        return {present: true};
    case 'ns':
        return probeIn(NS, check.name);
    case 'static':
    case 'enum':
        return probeIn(walkPath(NS, [check.cls]), check.name);
    case 'proto': {
        const cls = walkPath(NS, [check.cls]);
        if (!cls)
            return {present: false, error: `${check.ns}.${check.cls} missing`};
        return probeIn(cls.prototype, check.name);
    }
    case 'path':
        return probeIn(walkPath(NS, check.path), check.name);
    case 'signal': {
        const cls = walkPath(NS, [check.cls]);
        if (!cls?.$gtype)
            return {present: false, error: `${check.ns}.${check.cls} missing`};
        const id = GObject.signal_lookup(check.name, cls.$gtype);
        return {present: id > 0};
    }
    default:
        return {present: false, error: `unknown check kind ${check.kind}`};
    }
}

function evaluate(test) {
    try {
        // eslint-disable-next-line no-new-func
        return {ok: Boolean(new Function(`return (${test});`)())};
    } catch (e) {
        return {ok: false, error: String(e.message ?? e)};
    }
}

const out = {
    mode,
    gjs: System.version,
    results: {},
    features: {},
    globals: {},
    namespaces: {},
};

for (const check of list.checks ?? []) {
    if (!wanted(check))
        continue;
    try {
        // eslint-disable-next-line no-await-in-loop
        out.results[check.id] = await runCheck(check);
    } catch (e) {
        out.results[check.id] = {present: false, error: String(e.message ?? e)};
    }
}
for (const feature of list.features ?? [])
    out.features[feature.id] = evaluate(feature.test);
for (const name of list.globals ?? [])
    out.globals[name] = name in globalThis;
for (const [ns, info] of Object.entries(namespaces)) {
    out.namespaces[ns] = {ok: info.ok, spec: info.spec, error: info.error};
    if (info.module) {
        // Version of the typelib actually loaded, from its own constants
        const v = info.module.MAJOR_VERSION ?? info.module.major_version;
        if (v !== undefined)
            out.namespaces[ns].major = v;
    }
}

GLib.file_set_contents(outPath, new TextEncoder().encode(JSON.stringify(out, null, 1)));
print(`probe ${mode}: ${Object.keys(out.results).length} symbols, ` +
    `${Object.keys(out.features).length} features, gjs ${System.version}`);
