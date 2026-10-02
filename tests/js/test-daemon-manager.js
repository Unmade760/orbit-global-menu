// DaemonManager in daemon.js, driven against fake `global-menu` programs on a
// temporary PATH and a temporary HOME. The fakes have the real layout
// (globalmenu/command.py): the program that gets spawned owns no bus name,
// it runs a child that owns space.unmade.GlobalMenu and exits when the child
// does. Every test runs on the private bus of tools/checks/unit.sh's
// dbus-run-session. The restart timings are the real ones (1 s, 2 s), so this
// file takes about 15 s.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {test, run, assert} from './lib/testlib.js';
import {EXT_DIR} from './lib/stubbed.js';

const BUS_NAME = 'space.unmade.GlobalMenu';
const REAL_PATH = GLib.getenv('PATH');

// console.warn is read-only in gjs; the writer sees console.* and log()
const lines = [];
GLib.log_set_writer_func((level, fields) => {
    const message = fields['MESSAGE'];
    if (message !== undefined)
        lines.push(new TextDecoder().decode(message));
    return GLib.LogWriterOutput.HANDLED;
});

const {DaemonManager} = await import(`file://${EXT_DIR}/daemon.js`);

const CHILD_JS = `
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import System from 'system';
const loop = new GLib.MainLoop(null, false);
Gio.bus_own_name(Gio.BusType.SESSION, '${BUS_NAME}', Gio.BusNameOwnerFlags.NONE,
    () => {}, () => {
        if (GLib.getenv('FAKE_MODE') === 'crash')
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => System.exit(1));
    }, () => {});
loop.run();
`;

const TOP_SH = `#!/bin/bash
echo start >> "$FAKE_DIR/starts"
gjs -m "$FAKE_DIR/child.js" &
child=$!
echo $child > "$FAKE_DIR/child.pid"
trap 'kill $child 2>/dev/null' TERM
wait $child
wait $child
`;

const sleep = ms => new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
    resolve();
    return GLib.SOURCE_REMOVE;
}));

async function waitFor(condition, ms, what) {
    const end = GLib.get_monotonic_time() + ms * 1000;
    while (!condition()) {
        if (GLib.get_monotonic_time() > end)
            throw new Error(`timed out after ${ms} ms waiting for ${what}`);
        // eslint-disable-next-line no-await-in-loop
        await sleep(50);
    }
}

function readText(path) {
    try {
        return new TextDecoder().decode(GLib.file_get_contents(path)[1]);
    } catch {
        return '';
    }
}

function install(path) {
    GLib.mkdir_with_parents(GLib.path_get_dirname(path), 0o755);
    GLib.file_set_contents(path, new TextEncoder().encode(TOP_SH));
    GLib.chmod(path, 0o755);
}

/**
 * A scratch HOME with a fake daemon in $dir/bin and, unless told otherwise, on
 * PATH. FAKE_MODE is 'stay' (own the name until killed) or 'crash' (own it,
 * then exit after 150 ms).
 *
 * @param {object} options
 * @param {string} options.mode
 * @param {string} options.placed - 'path', 'local' (in ~/.local/bin) or 'none'
 * @returns {object} the scratch paths and helpers
 */
function setup({mode, placed = 'path'}) {
    const dir = GLib.dir_make_tmp('gm-daemon-XXXXXX');
    GLib.file_set_contents(`${dir}/child.js`, new TextEncoder().encode(CHILD_JS));
    GLib.setenv('FAKE_DIR', dir, true);
    GLib.setenv('FAKE_MODE', mode, true);
    GLib.setenv('HOME', dir, true);
    if (placed === 'path') {
        install(`${dir}/bin/global-menu`);
        GLib.setenv('PATH', `${dir}/bin:${REAL_PATH}`, true);
    } else {
        GLib.setenv('PATH', REAL_PATH, true);
        if (placed === 'local')
            install(`${dir}/.local/bin/global-menu`);
    }
    lines.length = 0;
    return {
        dir,
        starts: () => readText(`${dir}/starts`).split('\n').filter(Boolean).length,
        childPid: () => Number.parseInt(readText(`${dir}/child.pid`), 10) || 0,
        gaveUp: () => lines.filter(l => l.includes('[global-menu]') && l.includes('giving up')),
    };
}

function nameOwned() {
    try {
        Gio.DBus.session.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
            'org.freedesktop.DBus', 'GetNameOwner', new GLib.Variant('(s)', [BUS_NAME]),
            null, Gio.DBusCallFlags.NONE, -1, null);
        return true;
    } catch {
        return false;
    }
}

function kill(pid) {
    Gio.Subprocess.new(['kill', '-9', String(pid)], Gio.SubprocessFlags.NONE).wait(null);
}

function cleanup(env, manager) {
    manager?.destroy();
    const pid = env.childPid();
    if (pid)
        GLib.spawn_command_line_sync(`kill -9 ${pid}`);
    GLib.spawn_command_line_sync(`pkill -f ${env.dir}/child.js`);
    GLib.spawn_command_line_sync(`rm -rf ${env.dir}`);
}

test('restarts when the daemon child that owns the name dies', async () => {
    const env = setup({mode: 'stay'});
    const manager = new DaemonManager();
    try {
        manager.start();
        await waitFor(nameOwned, 10000, 'the first daemon to take the name');
        assert.equal(env.starts(), 1, 'starts before the crash');

        kill(env.childPid());
        await waitFor(() => env.starts() === 2, 6000, 'a second start');
        await waitFor(nameOwned, 10000, 'the second daemon to take the name');
    } finally {
        cleanup(env, manager);
    }
});

test('a crash loop stops at three starts with one log line', async () => {
    const env = setup({mode: 'crash'});
    const manager = new DaemonManager();
    try {
        manager.start();
        await waitFor(() => env.gaveUp().length > 0, 12000, 'the give-up line');
        assert.equal(env.starts(), 3, 'starts when giving up');
        // The next backoff would be 4 s
        await sleep(4500);
        assert.equal(env.starts(), 3, 'starts after the backoff');
        assert.equal(env.gaveUp().length, 1, 'give-up lines');
    } finally {
        cleanup(env, manager);
    }
});

test('destroy() cancels a pending restart and starts nothing later', async () => {
    const env = setup({mode: 'crash'});
    const manager = new DaemonManager();
    try {
        manager.start();
        await waitFor(nameOwned, 10000, 'the first daemon to take the name');
        // It crashes 150 ms later; the restart is then 1 s away
        await waitFor(() => !nameOwned(), 5000, 'the crash');
        manager.destroy();
        await sleep(2500);
        assert.equal(env.starts(), 1, 'starts after destroy');
        assert.equal(env.gaveUp().length, 0, 'give-up lines');
    } finally {
        cleanup(env, manager);
    }
});

test('destroy() stops the daemon it started', async () => {
    const env = setup({mode: 'stay'});
    const manager = new DaemonManager();
    try {
        manager.start();
        await waitFor(nameOwned, 10000, 'the daemon to take the name');
        manager.destroy();
        await waitFor(() => !nameOwned(), 5000, 'the name to be released');
        await sleep(500);
        assert.equal(env.starts(), 1, 'starts after destroy');
    } finally {
        cleanup(env, manager);
    }
});

test('uses ~/.local/bin/global-menu when PATH has none', async () => {
    const env = setup({mode: 'stay', placed: 'local'});
    const manager = new DaemonManager();
    try {
        manager.start();
        await waitFor(nameOwned, 10000, 'the daemon from ~/.local/bin');
        assert.equal(env.starts(), 1, 'starts');
    } finally {
        cleanup(env, manager);
    }
});

test('PATH wins over ~/.local/bin', async () => {
    const env = setup({mode: 'stay'});
    install(`${env.dir}/.local/bin/global-menu`);
    GLib.file_set_contents(`${env.dir}/.local/bin/global-menu`, new TextEncoder().encode('#!/bin/sh\ntouch "$FAKE_DIR/wrong"\n'));
    const manager = new DaemonManager();
    try {
        manager.start();
        await waitFor(nameOwned, 10000, 'the daemon from PATH');
        assert.ok(!GLib.file_test(`${env.dir}/wrong`, GLib.FileTest.EXISTS), 'the ~/.local/bin copy ran');
    } finally {
        cleanup(env, manager);
    }
});

test('a missing program is reported once, naming PATH and ~/.local/bin', async () => {
    const env = setup({mode: 'stay', placed: 'none'});
    const manager = new DaemonManager();
    try {
        manager.start();
        await waitFor(() => lines.some(l => l.includes('[global-menu]')), 3000, 'the warning');
        await sleep(300);
        const warnings = lines.filter(l => l.includes('[global-menu]'));
        assert.equal(warnings.length, 1, 'warnings');
        assert.ok(warnings[0].includes('PATH'), `warning names PATH: ${warnings[0]}`);
        assert.ok(warnings[0].includes('.local/bin'), `warning names ~/.local/bin: ${warnings[0]}`);
        assert.equal(env.starts(), 0, 'starts');
    } finally {
        cleanup(env, manager);
    }
});

test('spawns nothing while another process owns the name', async () => {
    const env = setup({mode: 'stay'});
    let owned = false;
    const id = Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
        null, () => {
            owned = true;
        }, null);
    const manager = new DaemonManager();
    try {
        await waitFor(() => owned, 5000, 'the test to take the name');
        manager.start();
        await sleep(1500);
        assert.equal(env.starts(), 0, 'starts');
    } finally {
        Gio.bus_unown_name(id);
        cleanup(env, manager);
    }
});

await run();
