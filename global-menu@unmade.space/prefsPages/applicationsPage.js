
import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

import {EditorPage} from './editorPage.js';
import {_} from '../i18n.js';

function sanitizeAppId(text) {
	return text
		.toLowerCase()
		.replace(/\.desktop$/, '')
		.replace(/[^a-z0-9-]+/g, '-')
		.replace(/^-+|-+$/g, '')
		.replace(/-{2,}/g, '-') || 'app';
}

export class ApplicationsPage {
	constructor({window, settings, store, userAppsDir}) {
		this._window = window;
		this._settings = settings;
		this._store = store;
		this._userAppsDir = userAppsDir;

		this.page = new Adw.PreferencesPage({
			title: _('Applications'),
			icon_name: 'view-list-symbolic',
		});

		this._group = new Adw.PreferencesGroup({
			title: _('Shortcut Menus'),
			description: _('Per-app curated menus that synthesize the app\'s real keyboard shortcuts. Editing a built-in creates a user override; built-in files are never modified.'),
		});
		this.page.add(this._group);
		this._rows = [];

		this._refresh();
	}

	_bumpRevision() {
		this._settings.set_int('shortcuts-revision', this._settings.get_int('shortcuts-revision') + 1);
	}

	_refresh() {
		this._store.load();

		// preferences group hides added rows from get_first_child
		// so track and remove them by hand
		for (const row of this._rows)
			this._group.remove(row);
		this._rows = [];

		for (const entry of this._store.listKnownAppIds()) {
			const row = this._buildRow(entry);
			this._group.add(row);
			this._rows.push(row);
		}

		const addRow = new Adw.ButtonRow({title: _('Add Application…')});
		addRow.connect('activated', () => this._showAddDialog());
		this._group.add(addRow);
		this._rows.push(addRow);
	}

	_buildRow(entry) {
		const mapping = this._store.mappings.get(entry.app);
		const row = new Adw.ActionRow({
			title: mapping?.name ?? entry.app,
			activatable: true,
		});

		if (!mapping) {
			const warning = this._store.warnings.find(
				w => w.file === `${entry.app}.json` && w.level !== 'info');
			row.set_subtitle(_('Error: %s').replace('%s', warning?.message ?? _('failed to load')));
			row.add_css_class('error');
		} else if (entry.hasUser && entry.hasBuiltin) {
			row.set_subtitle(`${entry.app} · ${_('Built-in, overridden')}`);
		} else if (entry.hasUser) {
			row.set_subtitle(`${entry.app} · ${_('Custom')}`);
		} else {
			row.set_subtitle(`${entry.app} · ${_('Built-in')}`);
		}

		if (mapping) {
			const sw = new Gtk.Switch({valign: Gtk.Align.CENTER});
			const disabledApps = new Set(this._settings.get_strv('shortcut-disabled-apps'));
			sw.set_active(!disabledApps.has(entry.app));
			sw.connect('notify::active', () => {
				const list = new Set(this._settings.get_strv('shortcut-disabled-apps'));
				if (sw.get_active())
					list.delete(entry.app);
				else
					list.add(entry.app);
				this._settings.set_strv('shortcut-disabled-apps', [...list]);
			});
			row.add_suffix(sw);
		}

		row.add_suffix(new Gtk.Image({icon_name: 'go-next-symbolic'}));
		row.connect('activated', () => this._openEditor(entry.app, mapping, entry.hasBuiltin, entry.hasUser));
		return row;
	}

	_openEditor(appId, mapping, hasBuiltin, hasUserFile) {
		const editor = new EditorPage({
			window: this._window,
			appId,
			mapping,
			hasBuiltin,
			hasUserFile,
			userAppsDir: this._userAppsDir,
			bumpRevision: () => this._bumpRevision(),
			onChanged: () => this._refresh(),
		});
		this._window.push_subpage(editor.page);
	}

	_showAddDialog() {
		const dialog = new Adw.Dialog({title: _('Add Application'), content_width: 480, content_height: 560});

		const toolbarView = new Adw.ToolbarView();
		dialog.set_child(toolbarView);
		toolbarView.add_top_bar(new Adw.HeaderBar({show_end_title_buttons: false}));

		const box = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 8, margin_top: 8, margin_start: 8, margin_end: 8, margin_bottom: 8});
		toolbarView.set_content(box);

		const manualRow = new Adw.EntryRow({title: _('Or type an app id / identifier manually')});
		box.append(manualRow);
		const manualButton = new Gtk.Button({label: _('Create Blank Mapping'), halign: Gtk.Align.START});
		manualButton.connect('clicked', () => {
			const text = manualRow.get_text().trim();
			if (text === '')
				return;
			dialog.close();
			this._createOrOpen(sanitizeAppId(text), [text]);
		});
		box.append(manualButton);

		const search = new Gtk.SearchEntry({placeholder_text: _('Search installed applications')});
		box.append(search);

		const scrolled = new Gtk.ScrolledWindow({vexpand: true});
		box.append(scrolled);

		const listBox = new Gtk.ListBox({css_classes: ['boxed-list']});
		scrolled.set_child(listBox);

		const apps = Gio.AppInfo.get_all()
			.filter(a => a.should_show())
			.sort((a, b) => a.get_name().localeCompare(b.get_name()));

		for (const app of apps) {
			const row = new Adw.ActionRow({title: app.get_name(), subtitle: app.get_id(), activatable: true});
			const icon = app.get_icon();
			if (icon)
				row.add_prefix(new Gtk.Image({gicon: icon, pixel_size: 32}));
			row.connect('activated', () => {
				dialog.close();
				const id = app.get_id();
				const stem = id.endsWith('.desktop') ? id.slice(0, -'.desktop'.length) : id;
				this._createOrOpen(sanitizeAppId(stem), [id, stem, app.get_name()]);
			});
			listBox.append(row);
			row._searchText = `${app.get_name()} ${app.get_id()}`.toLowerCase();
		}

		search.connect('search-changed', () => {
			const query = search.get_text().toLowerCase();
			let child = listBox.get_first_child();
			while (child) {
				child.set_visible(query === '' || (child._searchText ?? '').includes(query));
				child = child.get_next_sibling();
			}
		});

		dialog.present(this._window);
	}

	_createOrOpen(appId, suggestedIdentifiers) {
		this._store.load();
		const existing = this._store.mappings.get(appId);
		if (existing) {
			const known = this._store.listKnownAppIds().find(e => e.app === appId);
			this._openEditor(appId, existing, known?.hasBuiltin ?? false, known?.hasUser ?? false);
			return;
		}
		const draft = {
			format: 1,
			app: appId,
			name: appId,
			identifiers: [...new Set(suggestedIdentifiers.map(s => s.toLowerCase()))],
			menus: [{label: 'File', items: [{label: 'Example Item', shortcut: '<Ctrl>N'}]}],
		};
		this._openEditor(appId, draft, false, false);
	}
}
