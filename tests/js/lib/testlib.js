// Minimal test runner for the gjs unit tests. No framework, plain asserts.
//
//   import {test, skip, run, assert} from './lib/testlib.js';
//   test('name', () => { assert.equal(a, b); });
//   skip('name', 'why it is skipped');
//   await run();   // last line of every test file
//
// run() prints one "ok", "not ok" or "skip" line per test, then
// "RESULT <file>: <passed> passed, <failed> failed, <skipped> skipped",
// and exits 1 when anything failed. tools/checks/unit.sh runs each
// tests/js/test-*.js in its own gjs process and adds up the RESULT lines.

import System from 'system';

const tests = [];

/**
 * Register a test.
 *
 * @param {string} name
 * @param {Function} fn - throws (or rejects) to fail
 */
export function test(name, fn) {
    tests.push({name, fn});
}

/**
 * Register a skipped test, printed with its reason.
 *
 * @param {string} name
 * @param {string} reason
 */
export function skip(name, reason) {
    tests.push({name, skip: reason});
}

const show = v => {
    try {
        return JSON.stringify(v);
    } catch {
        return String(v);
    }
};

class AssertionError extends Error {}

export const assert = {
    ok(value, message = 'expected a truthy value') {
        if (!value)
            throw new AssertionError(`${message}: got ${show(value)}`);
    },
    equal(actual, expected, message = '') {
        if (actual !== expected)
            throw new AssertionError(`${message ? `${message}: ` : ''}expected ${show(expected)}, got ${show(actual)}`);
    },
    deepEqual(actual, expected, message = '') {
        const a = show(actual), e = show(expected);
        if (a !== e)
            throw new AssertionError(`${message ? `${message}: ` : ''}expected ${e}, got ${a}`);
    },
    throws(fn, message = 'expected an exception') {
        try {
            fn();
        } catch {
            return;
        }
        throw new AssertionError(message);
    },
};

/**
 * Run every registered test, print the results and exit.
 */
export async function run() {
    const file = System.programInvocationName.split('/').pop();
    let passed = 0, failed = 0, skipped = 0;
    for (const t of tests) {
        if (t.skip !== undefined) {
            print(`skip ${t.name}: ${t.skip}`);
            skipped++;
            continue;
        }
        try {
            // eslint-disable-next-line no-await-in-loop
            await t.fn();
            print(`ok ${t.name}`);
            passed++;
        } catch (e) {
            print(`not ok ${t.name}: ${e.message}`);
            if (!(e instanceof AssertionError) && e.stack)
                print(e.stack.split('\n').map(l => `    ${l}`).join('\n'));
            failed++;
        }
    }
    print(`RESULT ${file}: ${passed} passed, ${failed} failed, ${skipped} skipped`);
    System.exit(failed ? 1 : 0);
}
