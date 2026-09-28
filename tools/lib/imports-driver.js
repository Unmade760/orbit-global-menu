// Driver for `tools/check.sh imports`. Run with `gjs -m`.
//
//   gjs -m imports-driver.js classify <extdir>
//       Prints "<mode> <relative path>" for every .js module under <extdir>.
//       mode is "load" when no module in the file's local import graph
//       imports resource:///, else "parse".
//
//   gjs -m imports-driver.js stub <extdir> <copydir>
//       Copies the extension tree into <copydir>, points every resource:///
//       specifier at a generated stub module under <copydir>/__stubs__, and
//       puts a sentinel `throw` on line 1 of every copied module.
//
//   gjs -m imports-driver.js load <file>
//       Imports the real module and lets its top level run.
//
//   gjs -m imports-driver.js parse <copied file>
//       Imports the stubbed copy. ES module linking parses and resolves the
//       whole graph (every file, every import binding, every gi:// typelib)
//       before any module body runs, so the sentinel error can only reach us
//       once the graph has parsed and linked. A SyntaxError or a missing
//       binding surfaces as some other error.
//
// Each subcommand prints one line starting with OK or ERR and exits 0 or 1.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import System from 'system';

const SENTINEL = 'GM_PARSE_OK';
const IMPORT_RE = /\b(?:import|export)\s*(?:([\w$*{}\s,]+?)\s*from\s*)?['"]([^'"]+)['"]/g;
const DYNAMIC_RE = /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g;

const decoder = new TextDecoder();
const encoder = new TextEncoder();

function readText(path) {
    const [, bytes] = GLib.file_get_contents(path);
    return decoder.decode(bytes);
}

function writeText(path, text) {
    GLib.mkdir_with_parents(GLib.path_get_dirname(path), 0o755);
    GLib.file_set_contents(path, encoder.encode(text));
}

function listModules(dir, prefix = '') {
    const out = [];
    const enumerator = Gio.File.new_for_path(dir).enumerate_children(
        'standard::name,standard::type', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
    let info;
    while ((info = enumerator.next_file(null))) {
        const name = info.get_name();
        const rel = prefix ? `${prefix}/${name}` : name;
        if (info.get_file_type() === Gio.FileType.DIRECTORY)
            out.push(...listModules(`${dir}/${name}`, rel));
        else if (name.endsWith('.js'))
            out.push(rel);
    }
    return out.sort();
}

function specifiers(text) {
    const specs = [];
    for (const m of text.matchAll(IMPORT_RE))
        specs.push({clause: m[1] ?? '', spec: m[2]});
    for (const m of text.matchAll(DYNAMIC_RE))
        specs.push({clause: '', spec: m[1]});
    return specs;
}

function resolveLocal(fromRel, spec) {
    const base = GLib.path_get_dirname(fromRel);
    const joined = base === '.' ? spec : `${base}/${spec}`;
    const parts = [];
    for (const p of joined.split('/')) {
        if (p === '.' || p === '')
            continue;
        if (p === '..')
            parts.pop();
        else
            parts.push(p);
    }
    return parts.join('/');
}

function classify(extdir) {
    const modules = listModules(extdir);
    const graph = new Map();
    for (const rel of modules) {
        const specs = specifiers(readText(`${extdir}/${rel}`));
        graph.set(rel, {
            resource: specs.some(s => s.spec.startsWith('resource:///')),
            local: specs.filter(s => s.spec.startsWith('.')).map(s => resolveLocal(rel, s.spec)),
        });
    }
    const touchesResource = (rel, seen = new Set()) => {
        if (seen.has(rel))
            return false;
        seen.add(rel);
        const node = graph.get(rel);
        if (!node)
            return false;
        return node.resource || node.local.some(dep => touchesResource(dep, seen));
    };
    for (const rel of modules)
        print(`${touchesResource(rel) ? 'parse' : 'load'} ${rel}`);
}

// Names a module imports from one resource:/// specifier.
function importedNames(clause) {
    const names = {named: new Set(), wantsDefault: false};
    const trimmed = clause.trim();
    if (!trimmed || trimmed.startsWith('*'))
        return names;
    const brace = trimmed.indexOf('{');
    const head = brace === -1 ? trimmed : trimmed.slice(0, brace);
    if (head.replace(',', '').trim())
        names.wantsDefault = true;
    if (brace !== -1) {
        const inner = trimmed.slice(brace + 1, trimmed.indexOf('}'));
        for (const part of inner.split(',')) {
            const name = part.trim().split(/\s+as\s+/)[0].trim();
            if (name)
                names.named.add(name);
        }
    }
    return names;
}

function stubName(spec) {
    return `${spec.replace('resource:///', '').replace(/[^\w]/g, '_')}.js`;
}

function stub(extdir, copydir) {
    const modules = listModules(extdir);
    const wanted = new Map();
    for (const rel of modules) {
        let text = readText(`${extdir}/${rel}`);
        for (const {clause, spec} of specifiers(text)) {
            if (!spec.startsWith('resource:///'))
                continue;
            const entry = wanted.get(spec) ?? {named: new Set(), wantsDefault: false};
            const names = importedNames(clause);
            names.named.forEach(n => entry.named.add(n));
            entry.wantsDefault ||= names.wantsDefault;
            wanted.set(spec, entry);
        }
        text = text.replace(/(['"])(resource:\/\/\/[^'"]+)\1/g,
            (_m, q, spec) => `${q}file://${copydir}/__stubs__/${stubName(spec)}${q}`);
        // Same line as the original line 1, so reported line numbers match.
        writeText(`${copydir}/${rel}`, `throw new Error('${SENTINEL}');${text}`);
    }
    for (const [spec, entry] of wanted) {
        const lines = [
            `// Stub for ${spec}, generated by tools/lib/imports-driver.js.`,
            'const stub = new Proxy(function () {}, {get: () => stub, apply: () => stub, construct: () => stub});',
        ];
        for (const name of entry.named)
            lines.push(`export const ${name} = stub;`);
        if (entry.wantsDefault)
            lines.push('export default stub;');
        writeText(`${copydir}/__stubs__/${stubName(spec)}`, `${lines.join('\n')}\n`);
    }
    print(`OK stubbed ${modules.length} modules, ${wanted.size} resource specifiers`);
}

function describe(e) {
    const where = e?.fileName ? ` (${e.fileName.replace(/^file:\/\//, '')}:${e.lineNumber})` : '';
    return `${e?.name ?? 'Error'}: ${e?.message ?? e}${where}`;
}

async function importFile(path, expectSentinel) {
    const uri = Gio.File.new_for_path(path).get_uri();
    try {
        await import(uri);
    } catch (e) {
        if (expectSentinel && e?.message === SENTINEL) {
            print(`OK parsed and linked ${path}`);
            return 0;
        }
        print(`ERR ${describe(e)}`);
        return 1;
    }
    if (expectSentinel) {
        print(`ERR ${path} evaluated without reaching the sentinel`);
        return 1;
    }
    print(`OK loaded ${path}`);
    return 0;
}

const [cmd, ...args] = ARGV;
let status = 0;
switch (cmd) {
case 'classify':
    classify(args[0]);
    break;
case 'stub':
    stub(args[0], args[1]);
    break;
case 'load':
    status = await importFile(args[0], false);
    break;
case 'parse':
    status = await importFile(args[0], true);
    break;
default:
    print(`ERR unknown subcommand ${cmd}`);
    status = 2;
}
System.exit(status);
