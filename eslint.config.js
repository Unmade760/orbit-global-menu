// ESLint 9 flat config for the Global Menu extension.
//
// Based on GNOME Shell's own config (gnome-shell tools/eslint.config.js and
// gnome-shell-extensions tools/eslint.config.js, both at eslint-config-gnome
// commit c479d059). The packages live in tools/node_modules (see
// tools/package.json), so they are imported by path. Run through
// `tools/check.sh lint`.

import {defineConfig} from './tools/node_modules/@eslint/config-helpers/dist/esm/index.js';
import gnome from './tools/node_modules/eslint-config-gnome/src/index.js';

export default defineConfig([
    {
        ignores: [
            '**/node_modules/**',
            'build/**',
            'debian/usr/**',
        ],
    },
    gnome.configs.recommended,
    gnome.configs.jsdoc,
    {
        // Project rules shared with gnome-shell and gnome-shell-extensions.
        rules: {
            camelcase: ['error', {
                properties: 'never',
            }],
            'consistent-return': 'error',
            'eqeqeq': ['error', 'smart'],
            'key-spacing': ['error', {
                mode: 'minimum',
                beforeColon: false,
                afterColon: true,
            }],
            'prefer-arrow-callback': 'error',
            'prefer-const': ['error', {
                destructuring: 'all',
            }],
            'jsdoc/require-param-description': 'off',
            'jsdoc/require-jsdoc': ['error', {
                exemptEmptyFunctions: true,
                publicOnly: {
                    esm: true,
                },
            }],
        },
    },
    {
        // The one deviation from GNOME's rules: this codebase indents with
        // tabs, consistently, in every file. Same options as GNOME's indent
        // rule, with a tab as the unit; no-tabs is off for the same reason.
        files: ['global-menu@unmade.space/**/*.js'],
        rules: {
            'indent': ['error', 'tab', {
                ignoredNodes: [
                    'CallExpression[callee.object.name=GObject][callee.property.name=registerClass] > ClassExpression:first-child',
                ],
                MemberExpression: 'off',
            }],
            'no-tabs': 'off',
        },
    },
    {
        languageOptions: {
            // GJS globals beyond the ones eslint-config-gnome already
            // declares (imports, log, logError, print, printerr, console,
            // TextEncoder, TextDecoder, timers).
            globals: {
                global: 'readonly',
            },
        },
    },
]);
