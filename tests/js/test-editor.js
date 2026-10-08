// The mapping editor's save output (prefsPages/editorPage.js). Adw is not
// installed where the unit tests run, so the module is loaded with it
// replaced by an empty object; only the pure helper is exercised.

import GLib from 'gi://GLib';

import {test, run, assert} from './lib/testlib.js';
import {importWithStubs, EXT_DIR} from './lib/stubbed.js';

const source = new TextDecoder().decode(
    GLib.file_get_contents(`${EXT_DIR}/prefsPages/editorPage.js`)[1])
    .replace("import Adw from 'gi://Adw';", 'const Adw = {};');
const {buildRawMapping} = await importWithStubs('prefsPages/editorPage.js', {
    locals: {
        'prefsPages/editorPage.js': source,
        'prefsPages/shortcutCapture.js': 'export function captureShortcut() {}\n',
    },
});

const parts = {appId: 'vicinae', name: 'Vicinae', identifiers: ['vicinae'], menus: []};

test('a blank mapping keeps its blank flag when saved', () => {
    assert.deepEqual(buildRawMapping({...parts, blank: true}),
        {format: 1, app: 'vicinae', name: 'Vicinae', identifiers: ['vicinae'], menus: [], blank: true});
});

test('a mapping that was not blank gets no blank key', () => {
    assert.deepEqual(buildRawMapping({...parts, blank: false}),
        {format: 1, app: 'vicinae', name: 'Vicinae', identifiers: ['vicinae'], menus: []});
});

await run();
