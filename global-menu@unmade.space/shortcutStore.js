// Loads, validates and indexes the shortcut mapping files. A user file
// overrides a built-in with the same "app" id.
// Imported by the shell and the preferences process, so it sticks to GLib and
// Gio. Format: docs/shortcut-mappings.md

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {parseAccelerator} from './accelerator.js';

const decodeJson = bytes => JSON.parse(new TextDecoder().decode(bytes));

function unreadable(file, e, warnings) {
	warnings.push({file: file.get_basename(), message: `Cannot read/parse: ${e.message}`});
}

function readJson(file, warnings) {
	try {
		const [ok, bytes] = file.load_contents(null);
		if (!ok)
			return null;
		return decodeJson(bytes);
	} catch (e) {
		unreadable(file, e, warnings);
		return null;
	}
}

// The Gio async calls as promises; a cancelled call rejects with
// G_IO_ERROR_CANCELLED.
function loadBytes(file, cancellable) {
	return new Promise((resolve, reject) => {
		file.load_contents_async(cancellable, (_o, res) => {
			try {
				resolve(file.load_contents_finish(res)[1]);
			} catch (e) {
				reject(e);
			}
		});
	});
}

async function readJsonAsync(file, warnings, cancellable) {
	try {
		return decodeJson(await loadBytes(file, cancellable));
	} catch (e) {
		if (cancellable?.is_cancelled())
			throw e;
		unreadable(file, e, warnings);
		return null;
	}
}

// Directory entries read per round trip
const ENUMERATE_BATCH_SIZE = 100;

function listNamesAsync(dir, cancellable) {
	return new Promise((resolve, reject) => {
		dir.enumerate_children_async('standard::name', Gio.FileQueryInfoFlags.NONE,
			GLib.PRIORITY_DEFAULT, cancellable, (_o, res) => {
				let enumerator;
				try {
					enumerator = dir.enumerate_children_finish(res);
				} catch (e) {
					reject(e);
					return;
				}
				collectNames(enumerator, [], cancellable, resolve, reject);
			});
	});
}

function collectNames(enumerator, names, cancellable, resolve, reject) {
	enumerator.next_files_async(ENUMERATE_BATCH_SIZE, GLib.PRIORITY_DEFAULT, cancellable, (_o, res) => {
		let infos;
		try {
			infos = enumerator.next_files_finish(res);
		} catch (e) {
			enumerator.close_async(GLib.PRIORITY_DEFAULT, null, () => {});
			reject(e);
			return;
		}
		if (infos.length > 0) {
			names.push(...infos.map(info => info.get_name()));
			collectNames(enumerator, names, cancellable, resolve, reject);
			return;
		}
		enumerator.close_async(GLib.PRIORITY_DEFAULT, null, () => {});
		resolve(names);
	});
}

const jsonNames = names => names.filter(name => name.endsWith('.json')).sort();

/**
 * Validate a raw parsed mapping and return a sanitized copy, or null if
 * unusable. Bad items are dropped with a warning.
 * Exported so the preferences editor can apply the same rules.
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
		// The app gets no menu at all, not even the app name
		blank: raw.blank === true,
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

// Duplicates in one mapping are not an error: an app can reach one action from
// two menus. Logged at info level.
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

// The file names listed by a parsed index.json, or none if it is unusable
function builtinNames(index, warnings) {
	if (!index)
		return [];
	if (index.format !== 1 || !Array.isArray(index.apps)) {
		warnings.push({file: 'index.json', message: 'Malformed index (need {format: 1, apps: [...]})'});
		return [];
	}
	return index.apps.filter(name => {
		if (typeof name === 'string' && name.endsWith('.json'))
			return true;
		warnings.push({file: 'index.json', message: `Bad apps entry ${JSON.stringify(name)} skipped`});
		return false;
	});
}

function buildMapping(raw, name, builtin, warnings) {
	if (!raw)
		return null;
	const mapping = validateMapping(raw, name.slice(0, -'.json'.length), warnings);
	if (mapping)
		mapping.builtin = builtin;
	return mapping;
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
		this._commit(builtins, users, warnings);
	}

	/**
	 * load() without blocking: files are read with async Gio calls and the
	 * store keeps its old data until the new set is complete.
	 *
	 * @param {Gio.Cancellable|null} cancellable - a cancelled load rejects with
	 *     G_IO_ERROR_CANCELLED and leaves the store as it was
	 * @returns {Promise<void>}
	 */
	async loadAsync(cancellable = null) {
		const warnings = [];
		const builtins = [];
		const index = await readJsonAsync(this._builtinDir.get_child('index.json'), warnings, cancellable);
		const builtinApps = this._builtinDir.get_child('apps');
		for (const name of builtinNames(index, warnings)) {
			// One file at a time keeps the warnings in file order
			// eslint-disable-next-line no-await-in-loop
			const raw = await readJsonAsync(builtinApps.get_child(name), warnings, cancellable);
			const mapping = buildMapping(raw, name, true, warnings);
			if (mapping)
				builtins.push(mapping);
		}

		const users = [];
		const userApps = this._userDir.get_child('apps');
		let names = [];
		try {
			names = jsonNames(await listNamesAsync(userApps, cancellable));
		} catch (e) {
			// No user directory, which is the normal case
			if (cancellable?.is_cancelled())
				throw e;
		}
		for (const name of names) {
			// eslint-disable-next-line no-await-in-loop
			const raw = await readJsonAsync(userApps.get_child(name), warnings, cancellable);
			const mapping = buildMapping(raw, name, false, warnings);
			if (mapping)
				users.push(mapping);
		}
		this._commit(builtins, users, warnings);
	}

	_commit(builtins, users, warnings) {
		// A user file with the same "app" id replaces the built-in outright
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

	/** Findings from the last load(), as [{file, message, level}]; level is 'info' for notes, absent for problems. */
	get warnings() {
		return this._warnings;
	}

	/**
	 * Match lowercased identifier candidates (desktop id, WM class, app name)
	 * to a mapping, or null.
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
	 * Every app id on disk, valid or not, as [{app, hasBuiltin, hasUser}]
	 * sorted by app id.
	 * Broken ones are included so preferences can show an error for them.
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
		const index = readJson(this._builtinDir.get_child('index.json'), warnings);
		const appsDir = this._builtinDir.get_child('apps');
		for (const name of builtinNames(index, warnings)) {
			const mapping = buildMapping(readJson(appsDir.get_child(name), warnings), name, true, warnings);
			if (mapping)
				out.push(mapping);
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
		while ((info = enumerator.next_file(null)))
			names.push(info.get_name());
		enumerator.close(null);
		for (const name of jsonNames(names)) {
			const mapping = buildMapping(readJson(appsDir.get_child(name), warnings), name, false, warnings);
			if (mapping)
				out.push(mapping);
		}
		return out;
	}
}
