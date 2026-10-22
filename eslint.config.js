// eslint config based on the gnome shell one

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
            'jsdoc/require-jsdoc': 'off',
        },
    },
    {
        // tabs instead of spaces as in every file here
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
            // gjs globals the gnome config does not declare
            globals: {
                global: 'readonly',
            },
        },
    },
]);
