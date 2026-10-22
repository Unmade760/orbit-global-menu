
import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

import {validateMapping} from '../shortcutStore.js';
import {parseAccelerator} from '../accelerator.js';
import {captureShortcut} from './shortcutCapture.js';
import {_, ngettext} from '../i18n.js';

const MODIFIER_LABELS = {
	0xffe3: 'Ctrl',
	0xffe1: 'Shift',
	0xffe9: 'Alt',
	0xffeb: 'Super',
};

function prettyAccel(shortcut) {
	const chords = parseAccelerator(shortcut);
	if (!chords)
		return shortcut;
	return chords.map(chord => {
		const parts = chord.modifiers.map(m => MODIFIER_LABELS[m] ?? '?');
		const keyLabel = Gtk.accelerator_get_label(chord.keyval, 0) ||
			String.fromCharCode(chord.keyval).toUpperCase();
		parts.push(keyLabel);
		return parts.join('+');
	}).join(' ');
}

export function buildRawMapping({appId, name, identifiers, menus, blank}) {
	const raw = {format: 1, app: appId, name, identifiers, menus};
	if (blank)
		raw.blank = true;
	return raw;
}

function isSimpleLeaf(item) {
	return !item.separator && !item.items && !item.gsettings;
}

export class EditorPage {
	constructor({window, appId, mapping, hasBuiltin, hasUserFile, userAppsDir, bumpRevision, onChanged}) {
		this._window = window;
		this._appId = appId;
		this._hasBuiltin = hasBuiltin;
		this._userAppsDir = userAppsDir;
		this._bumpRevision = bumpRevision;
		this._onChanged = onChanged;
		this._blank = mapping?.blank === true;
		this._menus = JSON.parse(JSON.stringify(mapping?.menus ?? []));
		this._menuRows = [];

		this._toastOverlay = new Adw.ToastOverlay();
		const prefsPage = new Adw.PreferencesPage();
		this._toastOverlay.set_child(prefsPage);

		this.page = new Adw.NavigationPage({
			title: mapping?.name ?? appId,
			tag: `editor-${appId}`,
			child: this._toastOverlay,
		});

		const actionsGroup = new Adw.PreferencesGroup();
		prefsPage.add(actionsGroup);

		const saveRow = new Adw.ButtonRow({title: _('Save')});
		saveRow.add_css_class('suggested-action');
		saveRow.connect('activated', () => this._save());
		actionsGroup.add(saveRow);

		if (hasUserFile) {
			const dangerRow = new Adw.ButtonRow({
				title: hasBuiltin ? _('Reset to Built-in Default') : _('Delete This Mapping'),
			});
			dangerRow.add_css_class('destructive-action');
			dangerRow.connect('activated', () => this._deleteUserFile());
			actionsGroup.add(dangerRow);
		}

		const metaGroup = new Adw.PreferencesGroup({title: _('Application')});
		prefsPage.add(metaGroup);

		this._nameRow = new Adw.EntryRow({title: _('Display Name')});
		this._nameRow.set_text(mapping?.name ?? appId);
		metaGroup.add(this._nameRow);

		const idRow = new Adw.EntryRow({title: _('App ID (file name, fixed)')});
		idRow.set_text(appId);
		idRow.set_sensitive(false);
		metaGroup.add(idRow);

		this._identifiersRow = new Adw.EntryRow({title: _('Identifiers (comma-separated)')});
		this._identifiersRow.set_text((mapping?.identifiers ?? []).join(', '));
		metaGroup.add(this._identifiersRow);

		if (hasBuiltin && !hasUserFile) {
			metaGroup.set_description(
				_('This is a built-in mapping. Saving creates a user override in ~/.config/global-menu/shortcuts/apps. The built-in file itself is never modified.'));
		}

		this._menusGroup = new Adw.PreferencesGroup({
			title: _('Menus'),
			description: _('Click the shortcut button on an item to set it, exactly like GNOME Settings\' Keyboard Shortcuts panel.'),
		});
		prefsPage.add(this._menusGroup);

		this._rebuildMenusUI();
	}

	_rebuildMenusUI() {
		for (const row of this._menuRows)
			this._menusGroup.remove(row);
		this._menuRows = [];

		this._menus.forEach((menu, menuIndex) => {
			const expander = new Adw.ExpanderRow({title: menu.label || _('(untitled menu)'), expanded: true});

			const renameButton = new Gtk.Button({icon_name: 'document-edit-symbolic', valign: Gtk.Align.CENTER, css_classes: ['flat']});
			renameButton.connect('clicked', () => this._renameMenu(menu, expander));
			expander.add_suffix(renameButton);

			const deleteButton = new Gtk.Button({icon_name: 'user-trash-symbolic', valign: Gtk.Align.CENTER, css_classes: ['flat']});
			deleteButton.connect('clicked', () => {
				this._menus.splice(menuIndex, 1);
				this._rebuildMenusUI();
			});
			expander.add_suffix(deleteButton);

			menu.items.forEach((item, itemIndex) => {
				expander.add_row(this._buildItemRow(menu, item, itemIndex));
			});

			const addItemRow = new Adw.ButtonRow({title: _('Add Item')});
			addItemRow.connect('activated', () => {
				menu.items.push({label: _('New Item')});
				this._rebuildMenusUI();
			});
			expander.add_row(addItemRow);

			const addSeparatorRow = new Adw.ButtonRow({title: _('Add Separator')});
			addSeparatorRow.connect('activated', () => {
				menu.items.push({separator: true});
				this._rebuildMenusUI();
			});
			expander.add_row(addSeparatorRow);

			this._menusGroup.add(expander);
			this._menuRows.push(expander);
		});

		const addMenuRow = new Adw.ButtonRow({title: _('Add Menu…')});
		addMenuRow.connect('activated', () => {
			this._menus.push({label: _('New Menu'), items: []});
			this._rebuildMenusUI();
		});
		this._menusGroup.add(addMenuRow);
		this._menuRows.push(addMenuRow);
	}

	_buildItemRow(menu, item, itemIndex) {
		if (item.separator) {
			const row = new Adw.ActionRow({title: _('── Separator ──')});
			row.add_suffix(this._buildRemoveButton(() => {
				menu.items.splice(itemIndex, 1);
				this._rebuildMenusUI();
			}));
			return row;
		}

		if (!isSimpleLeaf(item)) {
			const row = new Adw.ActionRow({
				title: item.label ?? _('(complex item)'),
				subtitle: _('Submenu or advanced item. Not editable here, kept as it is on save.'),
			});
			row.add_suffix(this._buildRemoveButton(() => {
				menu.items.splice(itemIndex, 1);
				this._rebuildMenusUI();
			}));
			return row;
		}

		const row = new Adw.EntryRow({title: _('Label')});
		row.set_text(item.label ?? '');
		row.connect('changed', () => {
			item.label = row.get_text();
		});

		const shortcutButton = new Gtk.Button({valign: Gtk.Align.CENTER, css_classes: ['flat']});
		const refreshShortcutButton = () => {
			const content = new Gtk.Box({spacing: 6});
			content.append(new Gtk.Label({label: item.shortcut ? prettyAccel(item.shortcut) : _('Disabled')}));
			content.append(new Gtk.Image({icon_name: 'document-edit-symbolic'}));
			shortcutButton.set_child(content);
		};
		refreshShortcutButton();
		shortcutButton.connect('clicked', () => {
			captureShortcut({
				parentWindow: this._window,
				itemLabel: item.label || _('(unnamed item)'),
				onCaptured: result => {
					if (result === undefined)
						return;
					if (result === null)
						delete item.shortcut;
					else
						item.shortcut = result;
					refreshShortcutButton();
				},
			});
		});
		row.add_suffix(shortcutButton);

		row.add_suffix(this._buildRemoveButton(() => {
			menu.items.splice(itemIndex, 1);
			this._rebuildMenusUI();
		}));

		return row;
	}

	_buildRemoveButton(onClick) {
		const button = new Gtk.Button({icon_name: 'user-trash-symbolic', valign: Gtk.Align.CENTER, css_classes: ['flat']});
		button.connect('clicked', onClick);
		return button;
	}

	_renameMenu(menu, expander) {
		const dialog = new Adw.AlertDialog({heading: _('Rename Menu')});
		const entry = new Gtk.Entry({text: menu.label});
		dialog.set_extra_child(entry);
		dialog.add_response('cancel', _('Cancel'));
		dialog.add_response('rename', _('Rename'));
		dialog.set_response_appearance('rename', Adw.ResponseAppearance.SUGGESTED);
		dialog.set_default_response('rename');
		dialog.connect('response', (_d, response) => {
			if (response === 'rename') {
				menu.label = entry.get_text().trim() || menu.label;
				expander.set_title(menu.label);
			}
		});
		dialog.present(this._window);
	}

	_toast(title) {
		this._toastOverlay.add_toast(new Adw.Toast({title, timeout: 5}));
	}

	_save() {
		const name = this._nameRow.get_text().trim() || this._appId;
		const identifiers = this._identifiersRow.get_text()
			.split(',').map(s => s.trim()).filter(s => s !== '');

		const raw = buildRawMapping({appId: this._appId, name, identifiers, menus: this._menus, blank: this._blank});

		const warnings = [];
		validateMapping(raw, this._appId, warnings);

		try {
			this._userAppsDir.make_directory_with_parents(null);
		} catch (e) {
			if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.EXISTS))
				throw e;
		}
		const file = this._userAppsDir.get_child(`${this._appId}.json`);
		const bytes = new TextEncoder().encode(JSON.stringify(raw, null, 2));
		file.replace_contents(bytes, null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);

		this._bumpRevision();
		this._onChanged?.();

		if (warnings.length > 0) {
			const text = ngettext('Saved, but %d item had a problem: %s', 'Saved, but %d items had problems: %s', warnings.length);
			this._toast(text.replace('%d', warnings.length).replace('%s', warnings[0].message));
		} else {
			this._toast(_('Saved'));
		}
	}

	_deleteUserFile() {
		const file = this._userAppsDir.get_child(`${this._appId}.json`);
		try {
			file.delete(null);
		} catch (e) {
			this._toast(_('Could not delete: %s').replace('%s', e.message));
			return;
		}
		this._bumpRevision();
		this._onChanged?.();
		this._window.pop_subpage();
	}
}
