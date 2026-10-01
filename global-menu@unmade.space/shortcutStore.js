// Loads, validates and indexes the shortcut-menu mapping files. Built-ins
// come from <extension>/shortcuts and must be listed in its index.json; user
// mappings are whatever is in ~/.config/global-menu/shortcuts/apps. A
// user file whose "app" id matches a built-in replaces it entirely.
//
// Imported by both the shell process and the preferences process, so this
// module sticks to GLib and Gio.

// Mapping file format: docs/shortcut-mappings.md

import Gio from 'gi://Gio';

import {parseAccelerator} from './accelerator.js';

function readJson(file, warnings) {
	try {
		const [ok, bytes] = file.load_contents(null);
		if (!ok)
			return null;
		return JSON.parse(new TextDecoder().decode(bytes));
	} catch (e) {
		warnings.push({file: file.get_basename(), message: `Cannot read/parse: ${e.message}`});
		return null;
	}
}

/**
 * Validate a raw parsed mapping. Returns a sanitized mapping, or null if it
 * is unusable. A bad item or an unparseable shortcut only drops that item and
 * adds a warning.
 *
 * Exported so the preferences editor can check a mapping before writing it,
 * against the same rules the running extension loads with.
 *
 * @param {object} raw - the parsed JSON
 * @param {string} stem - the file name without .json
 * @param {object[]} warnings - collects what was dropped
 * @returns {object|null}
 */
export function validateMapping(raw, stem, warnings) {
	const file = `${stem}.json`;
	const warn = message => warnings.push({file, message});

	if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
		warn('Not a JSON object');
		return null;
	}
	if (raw.format !== 1) {
		warn(`Unsupported format ${JSON.stringify(raw.format)} (expected 1)`);
		return null;
	}
	if (raw.app !== stem) {
		warn(`"app" (${JSON.stringify(raw.app)}) must equal the filename stem ("${stem}")`);
		return null;
	}
	const identifiers = (Array.isArray(raw.identifiers) ? raw.identifiers : [])
		.filter(id => typeof id === 'string' && id.trim() !== '')
		.map(id => id.toLowerCase());
	if (identifiers.length === 0) {
		warn('No usable identifiers');
		return null;
	}
	if (!Array.isArray(raw.menus)) {
		warn('"menus" missing or not an array');
		return null;
	}
	const menus = [];
	for (const menu of raw.menus) {
		if (!menu || typeof menu.label !== 'string' || menu.label === '' || !Array.isArray(menu.items)) {
			warn('Malformed top-level menu dropped (need {label, items})');
			continue;
		}
		menus.push({label: menu.label, items: sanitizeItems(menu.items, menu.label, warn)});
	}
	return {
		format: 1,
		app: raw.app,
		name: typeof raw.name === 'string' && raw.name !== '' ? raw.name : raw.app,
		identifiers,
		menus,
	};
}

function sanitizeItems(items, path, warn) {
	const out = [];
	for (const item of items) {
		if (!item || typeof item !== 'object') {
			warn(`${path}: non-object item dropped`);
			continue;
		}
		if (item.separator === true) {
			out.push({separator: true});
			continue;
		}
		if (typeof item.label !== 'string' || item.label === '') {
			warn(`${path}: item without label dropped`);
			continue;
		}
		if (Array.isArray(item.items)) {
			out.push({label: item.label, items: sanitizeItems(item.items, `${path} » ${item.label}`, warn)});
		} else if (item.shortcut !== undefined) {
			if (typeof item.shortcut !== 'string' || !parseAccelerator(item.shortcut)) {
				warn(`${path} » ${item.label}: unparseable shortcut ${JSON.stringify(item.shortcut)}, item dropped`);
				continue;
			}
			out.push({label: item.label, shortcut: item.shortcut});
		} else {
			// No shortcut and no children: a placeholder, rendered greyed out
			out.push({label: item.label});
		}
	}
	return out;
}

// Duplicates within one mapping are worth reporting but are not an error: an
// app can legitimately reach one action from two menus. Reported at info
// level so a built-in's dozens of them stay out of the journal.
function collectDuplicateShortcuts(mapping, warnings) {
	const byAccel = new Map();
	const walk = (items, path) => {
		for (const item of items) {
			if (item.separator)
				continue;
			const itemPath = `${path} » ${item.label}`;
			if (item.items) {
				walk(item.items, itemPath);
			} else if (item.shortcut) {
				const normalized = parseAccelerator(item.shortcut)
					.map(chord => [...chord.modifiers].sort().concat(chord.keyval).join('+'))
					.join(' ');
				if (!byAccel.has(normalized))
					byAccel.set(normalized, []);
				byAccel.get(normalized).push(itemPath);
			}
		}
	};
	for (const menu of mapping.menus)
		walk(menu.items, menu.label);
	for (const paths of byAccel.values()) {
		if (paths.length > 1) {
			warnings.push({
				file: `${mapping.app}.json`,
				level: 'info',
				message: `Duplicate shortcut on: ${paths.join(', ')}`,
			});
		}
	}
}

export class ShortcutStore {
	constructor(builtinDir /* Gio.File: <ext>/shortcuts */,
	            userDir /* Gio.File: ~/.config/global-menu/shortcuts */) {
		this._builtinDir = builtinDir;
		this._userDir = userDir;
		this._mappings = new Map();
		this._ordered = [];
		this._warnings = [];
	}

	/** (Re)reads everything; safe to call repeatedly. */
	load() {
		const warnings = [];
		const builtins = this._loadBuiltins(warnings);
		const users = this._loadUserMappings(warnings);

		// A user file with the same "app" id replaces the built-in outright,
		// rather than merging into it
		const mappings = new Map();
		for (const mapping of builtins)
			mappings.set(mapping.app, mapping);
		for (const mapping of users)
			mappings.set(mapping.app, mapping);

		// User tier beats built-in tier; within a tier, first listed wins
		const ordered = [...users, ...builtins.filter(m => mappings.get(m.app) === m)];

		// Identifier claimed by two different apps: first listed wins
		const identifierIndex = new Map();
		for (const mapping of ordered) {
			for (const id of mapping.identifiers) {
				const owner = identifierIndex.get(id);
				if (owner === undefined) {
					identifierIndex.set(id, mapping.app);
				} else if (owner !== mapping.app) {
					warnings.push({
						file: `${mapping.app}.json`,
						message: `Identifier "${id}" already claimed by "${owner}", which wins`,
					});
				}
			}
		}

		for (const mapping of ordered)
			collectDuplicateShortcuts(mapping, warnings);

		this._mappings = mappings;
		this._ordered = ordered;
		this._warnings = warnings;
	}

	/** Map of app id to mapping, with user overrides already applied. */
	get mappings() {
		return this._mappings;
	}

	/**
	 * Findings from the last load(), as [{file, message, level}]. Level is
	 * 'info' for things that are only worth knowing, absent for problems.
	 */
	get warnings() {
		return this._warnings;
	}

	/**
	 * candidates: lowercased identifier candidates for the focused app
	 * (desktop id, WM class, app name). Returns the matching mapping or null.
	 *
	 * @param {string[]} candidates
	 * @returns {object|null}
	 */
	resolveMapping(candidates) {
		for (const mapping of this._ordered) {
			if (mapping.identifiers.some(id => candidates.includes(id)))
				return mapping;
		}
		return null;
	}

	/**
	 * Every app id on disk, whether or not it currently validates, as
	 * [{app, hasBuiltin, hasUser}] sorted by app id. The preferences list
	 * needs the broken ones too, so it can show an error instead of letting
	 * them vanish.
	 */
	listKnownAppIds() {
		const builtinIds = new Set();
		try {
			const [ok, bytes] = this._builtinDir.get_child('index.json').load_contents(null);
			if (ok) {
				const index = JSON.parse(new TextDecoder().decode(bytes));
				for (const name of index.apps ?? []) {
					if (typeof name === 'string' && name.endsWith('.json'))
						builtinIds.add(name.slice(0, -'.json'.length));
				}
			}
		} catch { /* index missing or unreadable; load() already warns */ }

		const userIds = new Set();
		try {
			const enumerator = this._userDir.get_child('apps')
				.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
			let info;
			while ((info = enumerator.next_file(null))) {
				const name = info.get_name();
				if (name.endsWith('.json'))
					userIds.add(name.slice(0, -'.json'.length));
			}
			enumerator.close(null);
		} catch { /* no user directory, which is the normal case */ }

		return [...new Set([...builtinIds, ...userIds])]
			.map(app => ({app, hasBuiltin: builtinIds.has(app), hasUser: userIds.has(app)}))
			.sort((a, b) => a.app.localeCompare(b.app));
	}

	_loadBuiltins(warnings) {
		const out = [];
		const indexFile = this._builtinDir.get_child('index.json');
		const index = readJson(indexFile, warnings);
		if (!index)
			return out;
		if (index.format !== 1 || !Array.isArray(index.apps)) {
			warnings.push({file: 'index.json', message: 'Malformed index (need {format: 1, apps: [...]})'});
			return out;
		}
		const appsDir = this._builtinDir.get_child('apps');
		for (const name of index.apps) {
			if (typeof name !== 'string' || !name.endsWith('.json')) {
				warnings.push({file: 'index.json', message: `Bad apps entry ${JSON.stringify(name)} skipped`});
				continue;
			}
			const raw = readJson(appsDir.get_child(name), warnings);
			if (!raw)
				continue;
			const mapping = validateMapping(raw, name.slice(0, -'.json'.length), warnings);
			if (mapping) {
				mapping.builtin = true;
				out.push(mapping);
			}
		}
		return out;
	}

	_loadUserMappings(warnings) {
		const out = [];
		const appsDir = this._userDir.get_child('apps');
		let enumerator;
		try {
			enumerator = appsDir.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
		} catch {
			// No user directory, which is the normal case
			return out;
		}
		const names = [];
		let info;
		while ((info = enumerator.next_file(null))) {
			if (info.get_name().endsWith('.json'))
				names.push(info.get_name());
		}
		enumerator.close(null);
		names.sort();
		for (const name of names) {
			const raw = readJson(appsDir.get_child(name), warnings);
			if (!raw)
				continue;
			const mapping = validateMapping(raw, name.slice(0, -'.json'.length), warnings);
			if (mapping) {
				mapping.builtin = false;
				out.push(mapping);
			}
		}
		return out;
	}
}
