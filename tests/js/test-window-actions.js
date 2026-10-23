// The Window menu's actions on the Meta API of GNOME 48 and of 49 and later
// (windowActions.js). The doubles follow the signatures in mutter 48.8 and
// 51.0 src/meta/window.h: 48 has get_maximized(), maximize(flags),
// unmaximize(flags) and begin_grab_op(op, device, sequence, time, hint); 49 and
// later have is_maximized(), maximize(), unmaximize() and
// begin_grab_op(op, sprite, time, hint) with the sprite from the backend.

import GLib from 'gi://GLib';

import {test, run, assert} from './lib/testlib.js';
import {importWithStubs, EXT_DIR} from './lib/stubbed.js';

const decoder = new TextDecoder();
const source = decoder.decode(GLib.file_get_contents(`${EXT_DIR}/windowActions.js`)[1]);

const GLIB_STUB = `
export default {
    PRIORITY_DEFAULT: 0,
    SOURCE_REMOVE: false,
    timeout_add(_priority, _ms, fn) {
        const id = globalThis.gmTest.timeouts.length + 1;
        globalThis.gmTest.timeouts.push({id, fn});
        return id;
    },
    source_remove(id) {
        globalThis.gmTest.removed.push(id);
        return true;
    },
};
`;
const META_STUB = `
export default {
    WindowType: {NORMAL: 0, DOCK: 1, DESKTOP: 2, SPLASHSCREEN: 3},
    MaximizeFlags: {HORIZONTAL: 1, VERTICAL: 2, BOTH: 3},
    GrabOp: {KEYBOARD_MOVING: 100, KEYBOARD_RESIZING_UNKNOWN: 101},
    MotionDirection: {LEFT: 0, RIGHT: 1, UP: 2, DOWN: 3},
    DisplayDirection: {UP: 0, DOWN: 1, LEFT: 2, RIGHT: 3},
    prefs_get_workspaces_only_on_primary: () => false,
};
`;
const MAIN_STUB = 'export const sessionMode = {hasWorkspaces: false};\n';

const {WindowActions, cancelPendingActions} = await importWithStubs('windowActions.js', {
    resources: {
        'resource:///gm-test/GLib.js': GLIB_STUB,
        'resource:///gm-test/Meta.js': META_STUB,
        'resource:///org/gnome/shell/ui/main.js': MAIN_STUB,
    },
    locals: {
        'windowActions.js': source
            .replace("'gi://GLib'", "'resource:///gm-test/GLib.js'")
            .replace("'gi://Meta'", "'resource:///gm-test/Meta.js'"),
    },
});

const BOTH = 3;

// A window as mutter 48 exposes it
function window48(t, maximized) {
    return {
        get_window_type: () => 0,
        can_minimize: () => true,
        can_maximize: () => true,
        allows_move: () => true,
        allows_resize: () => true,
        can_close: () => true,
        is_above: () => false,
        is_on_all_workspaces: () => false,
        get_monitor: () => 0,
        get_maximized: () => maximized === true ? BOTH : maximized || 0,
        maximize(flags) {
            if (flags !== BOTH)
                throw new TypeError('At least 1 argument required');
            t.calls.push(['maximize', flags]);
        },
        unmaximize(flags) {
            if (flags !== BOTH)
                throw new TypeError('At least 1 argument required');
            t.calls.push(['unmaximize', flags]);
        },
        begin_grab_op(op, device, sequence, time, hint) {
            if (arguments.length !== 5)
                throw new TypeError('begin_grab_op needs 5 arguments');
            t.calls.push(['begin_grab_op', op, device, sequence, time, hint]);
            return true;
        },
    };
}

// A window as mutter 49 and later expose it
function window49(t, maximized) {
    const win = window48(t, maximized);
    delete win.get_maximized;
    win.is_maximized = () => maximized;
    win.maximize = function () {
        if (arguments.length !== 0)
            throw new TypeError('maximize takes no arguments');
        t.calls.push(['maximize']);
    };
    win.unmaximize = function () {
        if (arguments.length !== 0)
            throw new TypeError('unmaximize takes no arguments');
        t.calls.push(['unmaximize']);
    };
    win.begin_grab_op = function (op, sprite, time, hint) {
        if (arguments.length !== 4)
            throw new TypeError('begin_grab_op needs 4 arguments');
        t.calls.push(['begin_grab_op', op, sprite, time, hint]);
        return true;
    };
    return win;
}

function setup(makeWindow, backend, maximized = false) {
    const t = {calls: [], timeouts: [], removed: []};
    globalThis.gmTest = t;
    const win = makeWindow(t, maximized);
    globalThis.global = {
        display: {
            get_focus_window: () => win,
            get_n_monitors: () => 1,
        },
        stage: {context: {get_backend: () => backend}},
        get_current_time: () => 4242,
    };
    return t;
}

const backend48 = {
    get_default_seat: () => ({get_pointer: () => 'pointer-device'}),
};
const backend49 = {
    get_default_seat: () => ({}),
    get_pointer_sprite: stage => `sprite-of-${stage === globalThis.global.stage}`,
};

function fireGrabs(t) {
    for (const {fn} of t.timeouts.splice(0))
        fn();
}

test('48: the menu offers Maximize for an unmaximized window', () => {
    setup(window48, backend48, false);
    const actions = new WindowActions().getActions();
    assert.ok(actions.includes('Maximize'), actions.join(', '));
    assert.ok(actions.includes('Always on Top'), actions.join(', '));
});

test('48: a maximized window offers Unmaximize and no Always on Top', () => {
    setup(window48, backend48, true);
    const actions = new WindowActions().getActions();
    assert.ok(actions.includes('Unmaximize'), actions.join(', '));
    assert.ok(!actions.includes('Always on Top'), actions.join(', '));
});

test('48: a window maximized on one axis offers Unmaximize, as the shell menu does', () => {
    const VERTICAL = 2;
    setup(window48, backend48, VERTICAL);
    const actions = new WindowActions().getActions();
    assert.ok(actions.includes('Unmaximize'), actions.join(', '));
    assert.ok(actions.includes('Always on Top'), actions.join(', '));
});

test('49: a maximized window offers Unmaximize and no Always on Top', () => {
    setup(window49, backend49, true);
    const actions = new WindowActions().getActions();
    assert.ok(actions.includes('Unmaximize'), actions.join(', '));
    assert.ok(!actions.includes('Always on Top'), actions.join(', '));
});

test('49: an unmaximized window offers Maximize', () => {
    setup(window49, backend49, false);
    assert.ok(new WindowActions().getActions().includes('Maximize'));
});

test('48: Maximize and Unmaximize pass both directions', () => {
    const t = setup(window48, backend48);
    const actions = new WindowActions();
    actions.doAction('Maximize');
    actions.doAction('Unmaximize');
    assert.deepEqual(t.calls, [['maximize', BOTH], ['unmaximize', BOTH]]);
});

test('49: Maximize and Unmaximize pass no argument', () => {
    const t = setup(window49, backend49);
    const actions = new WindowActions();
    actions.doAction('Maximize');
    actions.doAction('Unmaximize');
    assert.deepEqual(t.calls, [['maximize'], ['unmaximize']]);
});

test('48: Move grabs with the seat pointer and no sequence', () => {
    const t = setup(window48, backend48);
    new WindowActions().doAction('Move');
    fireGrabs(t);
    assert.deepEqual(t.calls, [['begin_grab_op', 100, 'pointer-device', null, 4242, null]]);
});

test('49: Resize grabs with the backend pointer sprite', () => {
    const t = setup(window49, backend49);
    new WindowActions().doAction('Resize');
    fireGrabs(t);
    assert.deepEqual(t.calls, [['begin_grab_op', 101, 'sprite-of-true', 4242, null]]);
});

test('a grab waiting on its timeout is cancelled on disable', () => {
    const t = setup(window49, backend49);
    new WindowActions().doAction('Move');
    cancelPendingActions();
    assert.deepEqual(t.removed, [1]);
});

await run();
