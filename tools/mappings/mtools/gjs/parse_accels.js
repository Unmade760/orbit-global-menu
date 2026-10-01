// Runs the extension's own parseAccelerator() over a batch of strings.
// Usage: gjs -m parse_accels.js KEYSYNTH_JS INPUT_JSON
// INPUT_JSON: {"accels": [...], "names": [...]}. Prints
// {"parsed": [null | [{modifiers, keyval}]], "keyvals": {name: keyval}},
// keyvals taken from GDK's keysym table for the given names.

import GLib from 'gi://GLib';
import Gdk from 'gi://Gdk?version=4.0';
import System from 'system';

const [keysynthPath, inputPath] = System.programArgs;
const {parseAccelerator} = await import(GLib.filename_to_uri(keysynthPath, null));
const [, bytes] = GLib.file_get_contents(inputPath);
const input = JSON.parse(new TextDecoder().decode(bytes));

const parsed = (input.accels ?? []).map(accel => parseAccelerator(accel));
const keyvals = {};
for (const name of input.names ?? [])
    keyvals[name] = Gdk.keyval_from_name(name);

print(JSON.stringify({parsed, keyvals}));
