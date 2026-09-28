// Load an extension module whose import graph reaches gnome-shell's own JS
// (resource:///org/gnome/shell/...), which exists only inside a running
// shell. Same idea as tools/lib/imports-driver.js, but the modules run:
//
//   const mod = await importWithStubs('nativeMenu.js', {
//       resources: {'resource:///org/gnome/shell/ui/popupMenu.js': 'export const Ornament = {...};'},
//       locals: {'menuBarButton.js': 'export class MenuBarButton {...}'},
//   });
//
// The extension's .js files are copied to a fresh directory under $TMPDIR
// (tools/checks/unit.sh points TMPDIR at a directory it deletes). Every
// resource:/// specifier is pointed at the stub source given for it, and
// each file named in `locals` is replaced by the given source. A resource
// the test gave no stub for throws on import, naming the specifier, so a
// test never runs against an accidental stand-in.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export const EXT_DIR = GLib.build_filenamev([
    GLib.path_get_dirname(GLib.path_get_dirname(GLib.path_get_dirname(
        GLib.path_get_dirname(Gio.File.new_for_uri(import.meta.url).get_path())))),
    'global-menu@unmade.space',
]);

const decoder = new TextDecoder();
const encoder = new TextEncoder();

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
    return out;
}

function write(path, text) {
    GLib.mkdir_with_parents(GLib.path_get_dirname(path), 0o755);
    GLib.file_set_contents(path, encoder.encode(text));
}

const stubFile = spec => `${spec.replace('resource:///', '').replace(/[^\w]/g, '_')}.js`;

/**
 * Import `rel` from a stubbed copy of the extension.
 *
 * @param {string} rel - module path relative to the extension directory
 * @param {object} stubs
 * @param {object} stubs.resources - resource:/// specifier to stub source
 * @param {object} stubs.locals - extension-relative path to replacement source
 * @returns {Promise<object>} the module namespace
 */
export function importWithStubs(rel, {resources = {}, locals = {}} = {}) {
    const dir = GLib.dir_make_tmp('gm-unit-XXXXXX');
    const wanted = new Set();
    for (const mod of listModules(EXT_DIR)) {
        let text = locals[mod];
        if (text === undefined) {
            const [, bytes] = GLib.file_get_contents(`${EXT_DIR}/${mod}`);
            text = decoder.decode(bytes);
        }
        text = text.replace(/(['"])(resource:\/\/\/[^'"]+)\1/g, (_m, q, spec) => {
            wanted.add(spec);
            return `${q}file://${dir}/__stubs__/${stubFile(spec)}${q}`;
        });
        write(`${dir}/${mod}`, text);
    }
    for (const spec of wanted) {
        write(`${dir}/__stubs__/${stubFile(spec)}`,
            resources[spec] ?? `throw new Error('no stub given for ${spec}');\n`);
    }
    return import(Gio.File.new_for_path(`${dir}/${rel}`).get_uri());
}
