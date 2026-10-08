// The compiled zh_CN catalog loads through the gettext domain metadata.json
// names, and i18n.js reads it the way the shell and preferences do once
// they have bound that domain.

import Gettext from 'gettext';
import GLib from 'gi://GLib';

import {test, run, assert} from './lib/testlib.js';
import {EXT_DIR} from './lib/stubbed.js';

const metadata = JSON.parse(new TextDecoder().decode(
    GLib.file_get_contents(`${EXT_DIR}/metadata.json`)[1]));
Gettext.bindtextdomain(metadata['gettext-domain'], `${EXT_DIR}/locale`);
const {_, ngettext, N_} = await import(`file://${EXT_DIR}/i18n.js`);

test('metadata names the domain the catalog is compiled for', () => {
    assert.equal(metadata['gettext-domain'], 'global-menu');
    assert.ok(GLib.file_test(`${EXT_DIR}/locale/zh_CN/LC_MESSAGES/global-menu.mo`, GLib.FileTest.EXISTS));
});

test('zh_CN strings come back translated, untranslated ones unchanged', () => {
    GLib.setenv('LANGUAGE', 'zh_CN', true);
    try {
        assert.equal(_('Copy'), '复制');
        assert.equal(_('Move to Workspace Left'), '移到左侧工作区');
        assert.equal(ngettext('Saved, but %d item had a problem: %s', 'Saved, but %d items had problems: %s', 2),
            '已保存，但有 %d 个菜单项存在问题：%s');
        assert.equal(_('not a msgid'), 'not a msgid');
    } finally {
        GLib.setenv('LANGUAGE', 'en_US:en', true);
    }
});

test('N_ only marks the string', () => {
    assert.equal(N_('Copy'), 'Copy');
});

await run();
