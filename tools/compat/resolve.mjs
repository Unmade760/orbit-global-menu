#!/usr/bin/env node
// Static half of `tools/check.sh compat`: which GNOME Shell, mutter, St,
// Clutter, GLib/Gio, GTK, libadwaita and gjs APIs the extension touches,
// and whether each exists in every supported version.
//
//   resolve.mjs analyze --ext DIR --target ID:MAJOR:SHELL_JS_DIR:GIR_JSON ...
//                       --out ANALYSIS.json --probe PROBE.json
//   resolve.mjs report  --analysis ANALYSIS.json --results DIR
//                       --out COMPAT.json --summary SUMMARY.md
//
// analyze parses every extension module and, per target, the gnome-shell JS
// of that version (espree, the parser eslint uses), and follows types
// through the code: gi:// namespaces, the GIR of each distro image (dumped
// by tools/compat/in-container.sh, condensed by gir2json.py) for return,
// property and field types, and gnome-shell's own classes for everything
// imported from resource:///. Each member access, constructor property,
// signal name and call it can type becomes a "use", with the runtime guard
// (if any) around it. It writes the uses and a probe list for
// tools/compat/probe.js, which checks every GI symbol under each image's
// real gjs.
//
// report merges the static uses with the probe results and the in-container
// parse results into one table, symbol x version, and exits 1 when a used
// symbol is missing (or called with an argument count gjs rejects) in a
// supported version and no runtime guard covers it.

import fs from 'node:fs';
import path from 'node:path';
import * as espree from 'espree';
import * as eslintScope from 'eslint-scope';

// Section: types

const U = Object.freeze({k: 'unknown'});
const known = t => t && t.k !== 'unknown';
const T = {
	gns: ns => ({k: 'gns', ns}),
	gcls: (ns, name, extra = {}) => ({k: 'gcls', ns, name, ...extra}),
	gobj: (ns, name, extra = {}) => ({k: 'gobj', ns, name, ...extra}),
	gpath: (ns, p) => ({k: 'gpath', ns, path: p}),
	callable: ret => ({k: 'callable', ret}),
	fn: (mod, node) => ({k: 'fn', mod, node}),
	cls: (mod, node) => ({k: 'cls', mod, node}),
	inst: (mod, node) => ({k: 'inst', mod, node}),
	mod: mod => ({k: 'mod', mod}),
	arr: elem => ({k: 'arr', elem}),
	obj: (mod, node, valuesAreClasses = false) => ({k: 'obj', mod, node, valuesAreClasses}),
	// A value that can be one of several types, in source order (a field
	// assigned in more than one place)
	union: types => ({k: 'union', types}),
	// console, TextDecoder and other globals of the JS runtime
	jsglobal: name => ({k: 'jsglobal', name}),
};

function unionOf(types) {
	const out = [];
	for (const t of types) {
		if (!known(t))
			continue;
		for (const x of t.k === 'union' ? t.types : [t]) {
			if (!out.some(o => sameType(o, x)))
				out.push(x);
		}
	}
	if (out.length === 0)
		return U;
	return out.length === 1 ? out[0] : T.union(out);
}

function sameType(a, b) {
	if (a.k !== b.k)
		return false;
	switch (a.k) {
	case 'gns': return a.ns === b.ns;
	case 'gcls':
	case 'gobj': return a.ns === b.ns && a.name === b.name;
	case 'inst':
	case 'cls':
	case 'fn':
	case 'obj': return a.node === b.node;
	case 'mod': return a.mod === b.mod;
	case 'arr': return sameType(a.elem, b.elem);
	default: return a === b;
	}
}

// Methods gjs's imports.signals.addSignalMethods() puts on a prototype
const SIGNAL_METHODS = ['connect', 'connectAfter', 'disconnect', 'emit', 'signalHandlerIsConnected', 'disconnectAll'];

// Namespaces each process may load, per the EGO review guidelines: GTK,
// GDK and libadwaita never in the shell, Clutter, Meta, St and Shell never
// in the preferences window.
const SHELL_ONLY_NS = new Set(['Meta', 'Clutter', 'Cogl', 'Mtk', 'St', 'Shell', 'Gvc']);
const PREFS_ONLY_NS = new Set(['Gtk', 'Gdk', 'Gsk', 'Adw']);

// gjs adds these in its overrides (gjs/modules/core/overrides/*.js), so no
// GIR has them. Presence still comes from the runtime probe; this only
// gives the analyzer the type of what they return.
const OVERRIDE_VALUES = {
	'Gio.DBus': () => T.gpath('Gio', ['DBus']),
	'Gio.DBus.session': () => T.gobj('Gio', 'DBusConnection'),
	'Gio.DBus.system': () => T.gobj('Gio', 'DBusConnection'),
	// The class it returns gets one method per interface member, named
	// <Member>Remote and <Member>Sync; those come from our own XML.
	'Gio.DBusProxy.makeProxyWrapper': () => T.callable(T.gcls('Gio', 'DBusProxy', {generated: /(?:Remote|Sync)$/})),
};

// Types the source cannot tell the analyzer, each checked by hand against
// every gnome-shell worktree (48.8, 49.10, 50.5, 51.0):
//   ExtensionBase.dir is `this.metadata.dir`, a Gio.File the extension
//     manager puts in the metadata (misc/extensionUtils.js).
//   ExtensionPreferences.fillPreferencesWindow gets the extensions app's
//     Adw.PreferencesWindow (extensions-app js/extensionPrefsDialog.js).
//   Panel.statusArea maps a role to the indicator built from
//     PANEL_ITEM_IMPLEMENTATIONS (ui/panel.js _ensureIndicator).
//   SessionMode copies every key of the _modes definitions onto itself
//     (ui/sessionMode.js _sync), so hasWorkspaces and friends are fields.
const MEMBER_HINTS = {
	'extensions/sharedInternals.js:ExtensionBase#dir': () => T.gobj('Gio', 'File'),
};
const PARAM_HINTS = {
	'extensions/prefs.js:ExtensionPreferences#fillPreferencesWindow': [() => T.gobj('Adw', 'PreferencesWindow')],
};
const DICT_FIELDS = {
	'ui/panel.js:Panel#statusArea': 'PANEL_ITEM_IMPLEMENTATIONS',
};
const DYNAMIC_FIELDS = {
	'ui/sessionMode.js:SessionMode': '_modes',
};

// Array methods whose callback's first argument is an element.
const ELEMENT_CALLBACKS = new Set(['forEach', 'filter', 'map', 'find', 'findIndex', 'findLast',
	'findLastIndex', 'some', 'every', 'flatMap', 'sort', 'toSorted']);
const ELEMENT_RETURNING = new Set(['filter', 'slice', 'toSorted', 'sort', 'reverse', 'toReversed', 'concat']);
const ELEMENT_OF = new Set(['find', 'findLast', 'at', 'pop', 'shift']);

// Section: language features newer than the oldest supported gjs
//
// gjs 1.82 (Debian 13) embeds SpiderMonkey 128. Each entry is a test
// expression the probe evaluates under every image's gjs; `detect` says
// how the analyzer spots a use in the extension.
const FEATURES = [
	...['findLast', 'findLastIndex', 'toSorted', 'toReversed', 'toSpliced'].map(m => ({
		id: `Array.prototype.${m}`, method: m, test: `typeof [].${m} === 'function'`,
	})),
	{id: 'Array.prototype.with', method: 'with', test: "typeof [].with === 'function'"},
	{id: 'String.prototype.isWellFormed', method: 'isWellFormed', test: "typeof ''.isWellFormed === 'function'"},
	{id: 'String.prototype.toWellFormed', method: 'toWellFormed', test: "typeof ''.toWellFormed === 'function'"},
	...['union', 'intersection', 'difference', 'symmetricDifference', 'isSubsetOf', 'isSupersetOf',
		'isDisjointFrom'].map(m => ({
		id: `Set.prototype.${m}`, method: m, test: `typeof new Set().${m} === 'function'`,
	})),
	{id: 'Map.prototype.getOrInsert', method: 'getOrInsert', test: "typeof new Map().getOrInsert === 'function'"},
	{id: 'Map.prototype.getOrInsertComputed', method: 'getOrInsertComputed',
		test: "typeof new Map().getOrInsertComputed === 'function'"},
	{id: 'Uint8Array.prototype.toBase64', method: 'toBase64', test: "typeof new Uint8Array().toBase64 === 'function'"},
	{id: 'Uint8Array.prototype.toHex', method: 'toHex', test: "typeof new Uint8Array().toHex === 'function'"},
	{id: 'ArrayBuffer.prototype.transfer', method: 'transfer', test: "typeof new ArrayBuffer(1).transfer === 'function'"},
	...[['Object', 'groupBy'], ['Map', 'groupBy'], ['Object', 'hasOwn'], ['Array', 'fromAsync'],
		['Promise', 'withResolvers'], ['Promise', 'try'], ['RegExp', 'escape'], ['Math', 'sumPrecise'],
		['Math', 'f16round'], ['Error', 'isError'], ['Uint8Array', 'fromBase64'], ['Uint8Array', 'fromHex'],
		['Iterator', 'from'], ['JSON', 'rawJSON'], ['JSON', 'isRawJSON'], ['Atomics', 'pause'],
		['Intl', 'DurationFormat']].map(([o, m]) => ({
		id: `${o}.${m}`, stat: [o, m], test: `typeof ${o} !== 'undefined' && typeof ${o}.${m} !== 'undefined'`,
	})),
	{id: 'Iterator.prototype helpers', iterator: true,
		test: "typeof [].values().map === 'function' && typeof [].values().toArray === 'function'"},
	{id: 'Temporal', global: 'Temporal', test: "typeof Temporal !== 'undefined'"},
	{id: 'Float16Array', global: 'Float16Array', test: "typeof Float16Array !== 'undefined'"},
	{id: 'structuredClone', global: 'structuredClone', test: "typeof structuredClone === 'function'"},
];
const ITERATOR_SOURCES = new Set(['values', 'keys', 'entries', 'matchAll']);
const ITERATOR_HELPERS = new Set(['map', 'filter', 'take', 'drop', 'flatMap', 'reduce', 'toArray',
	'forEach', 'some', 'every', 'find']);

// Names that belong to JS itself, never to a GNOME API, for untyped
// receivers.
const BUILTIN_NAMES = new Set();
for (const proto of [Object.prototype, Array.prototype, String.prototype, Number.prototype,
	Map.prototype, Set.prototype, WeakMap.prototype, Promise.prototype, Function.prototype,
	RegExp.prototype, Date.prototype, Symbol.prototype, Error.prototype, Uint8Array.prototype,
	Object.getPrototypeOf(Uint8Array.prototype), Object, Array, String, Number, Promise, JSON, Math,
	Reflect, Date])
	Object.getOwnPropertyNames(proto).forEach(n => BUILTIN_NAMES.add(n));
for (const n of ['length', 'name', 'message', 'stack', 'default', 'prototype', 'constructor', 'then'])
	BUILTIN_NAMES.add(n);

// Section: parsing

function setParents(node, parent) {
	Object.defineProperty(node, 'parent', {value: parent, writable: true, enumerable: false});
	for (const key of Object.keys(node)) {
		const v = node[key];
		if (Array.isArray(v)) {
			for (const c of v) {
				if (c && typeof c.type === 'string')
					setParents(c, node);
			}
		} else if (v && typeof v.type === 'string' && key !== 'loc') {
			setParents(v, node);
		}
	}
}

function* walk(node) {
	yield node;
	for (const key of Object.keys(node)) {
		if (key === 'loc' || key === 'range')
			continue;
		const v = node[key];
		if (Array.isArray(v)) {
			for (const c of v) {
				if (c && typeof c.type === 'string')
					yield* walk(c);
			}
		} else if (v && typeof v.type === 'string') {
			yield* walk(v);
		}
	}
}

const isFunction = n => n && ['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'].includes(n.type);
const isClass = n => n && (n.type === 'ClassDeclaration' || n.type === 'ClassExpression');

function loadModule(file, key, rel, isExt) {
	const src = fs.readFileSync(file, 'utf8');
	const ast = espree.parse(src, {ecmaVersion: 'latest', sourceType: 'module', loc: true, range: true});
	setParents(ast, null);
	const scopeManager = eslintScope.analyze(ast, {ecmaVersion: 2022, sourceType: 'module', fallback: 'iteration'});
	const refVar = new Map();
	for (const scope of scopeManager.scopes) {
		for (const ref of scope.references) {
			if (ref.resolved)
				refVar.set(ref.identifier, ref.resolved);
		}
		for (const v of scope.variables) {
			for (const id of v.identifiers)
				refVar.set(id, v);
		}
	}
	const moduleScope = scopeManager.globalScope.childScopes.find(s => s.type === 'module');
	const globals = new Map();
	for (const ref of scopeManager.globalScope.through) {
		const name = ref.identifier.name;
		if (!globals.has(name))
			globals.set(name, ref.identifier);
	}

	const exports = new Map();
	const imports = [];
	const dynamicGi = new Set();
	for (const stmt of ast.body) {
		if (stmt.type === 'ImportDeclaration') {
			imports.push(stmt);
		} else if (stmt.type === 'ExportNamedDeclaration') {
			const d = stmt.declaration;
			if (d && (d.type === 'FunctionDeclaration' || d.type === 'ClassDeclaration')) {
				exports.set(d.id.name, {local: d.id.name});
			} else if (d && d.type === 'VariableDeclaration') {
				for (const decl of d.declarations) {
					if (decl.id.type === 'Identifier')
						exports.set(decl.id.name, {local: decl.id.name});
				}
			}
			for (const s of stmt.specifiers ?? []) {
				const exported = s.exported.name ?? s.exported.value;
				exports.set(exported, stmt.source
					? {reexport: stmt.source.value, imported: s.local.name ?? s.local.value}
					: {local: s.local.name});
			}
		} else if (stmt.type === 'ExportDefaultDeclaration') {
			exports.set('default', {node: stmt.declaration});
		}
	}
	for (const n of walk(ast)) {
		if (n.type === 'ImportExpression' && n.source.type === 'Literal') {
			const m = String(n.source.value).match(/^gi:\/\/(\w+)/);
			if (m)
				dynamicGi.add(m[1]);
		}
	}
	return {key, rel, file, src, ast, refVar, moduleScope, globals, exports, imports, dynamicGi, isExt,
		label: rel};
}

function listJs(dir, prefix = '') {
	const out = [];
	for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
		const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
		if (entry.isDirectory())
			out.push(...listJs(path.join(dir, entry.name), rel));
		else if (entry.name.endsWith('.js'))
			out.push(rel);
	}
	return out.sort();
}

class ModuleSet {
	constructor(root, kind) {
		this.root = root;
		this.kind = kind;
		this.cache = new Map();
	}

	get(rel) {
		rel = path.posix.normalize(rel);
		if (this.cache.has(rel))
			return this.cache.get(rel);
		const file = path.join(this.root, rel);
		let mod = null;
		if (fs.existsSync(file)) {
			try {
				mod = loadModule(file, `${this.kind}:${rel}`, rel, this.kind === 'ext');
			} catch (e) {
				process.stderr.write(`resolve: cannot parse ${file}: ${e.message}\n`);
			}
		}
		this.cache.set(rel, mod);
		return mod;
	}
}

const shellSetCache = new Map();
function shellSetFor(jsDir) {
	if (!shellSetCache.has(jsDir))
		shellSetCache.set(jsDir, new ModuleSet(jsDir, 'shell'));
	return shellSetCache.get(jsDir);
}

function propNames(member, mod) {
	if (!member.computed) {
		if (member.property.type === 'Identifier')
			return [member.property.name];
		if (member.property.type === 'PrivateIdentifier')
			return [];
		return [];
	}
	if (member.property.type === 'Literal' && typeof member.property.value === 'string')
		return [member.property.value];
	// win[prop] inside `for (const prop of LIST)` over a const array of
	// string literals
	if (member.property.type === 'Identifier') {
		const v = mod.refVar.get(member.property);
		const def = v?.defs[0];
		const forOf = def?.node?.parent?.parent;
		if (forOf?.type === 'ForOfStatement' && forOf.right.type === 'Identifier') {
			const listVar = mod.refVar.get(forOf.right);
			const init = listVar?.defs[0]?.node?.init;
			if (init?.type === 'ArrayExpression' && init.elements.every(e => e?.type === 'Literal' && typeof e.value === 'string'))
				return init.elements.map(e => e.value);
		}
	}
	return [];
}

function isEmptyContainer(init) {
	if (!init)
		return false;
	if (init.type === 'ArrayExpression')
		return init.elements.length === 0;
	return init.type === 'NewExpression' && init.callee.type === 'Identifier' &&
		['Set', 'Array'].includes(init.callee.name) && init.arguments.length === 0;
}

// For `x.push(v)`, `x.add(v)` or `x.unshift(v)` where `ref` is x: v.
function addedValue(ref) {
	const m = ref.parent;
	if (m?.type !== 'MemberExpression' || m.object !== ref || m.computed ||
		!['push', 'add', 'unshift'].includes(m.property.name))
		return null;
	const call = m.parent;
	if (call?.type !== 'CallExpression' || call.callee !== m)
		return null;
	return call.arguments[0]?.type === 'SpreadElement' ? null : call.arguments[0] ?? null;
}

function enclosingClass(node) {
	for (let n = node.parent; n; n = n.parent) {
		if (n.type === 'ArrowFunctionExpression')
			continue;
		if (n.type === 'FunctionExpression' || n.type === 'FunctionDeclaration') {
			const p = n.parent;
			if (p?.type === 'MethodDefinition')
				return p.parent.parent;
			return null;
		}
		if (n.type === 'PropertyDefinition' || n.type === 'StaticBlock')
			return n.parent.parent;
	}
	return null;
}

function enclosingFunction(node) {
	for (let n = node.parent; n; n = n.parent) {
		if (isFunction(n))
			return n;
	}
	return null;
}

function className(node) {
	if (node.id?.name)
		return node.id.name;
	const p = node.parent;
	if (p?.type === 'VariableDeclarator')
		return p.id.name;
	if (p?.type === 'CallExpression' && p.parent?.type === 'VariableDeclarator')
		return p.parent.id.name;
	return '<anonymous>';
}

// Section: the per-target program

class Program {
	constructor(target, extSet) {
		this.target = target;
		this.gir = JSON.parse(fs.readFileSync(target.gir, 'utf8'));
		this.shell = shellSetFor(target.shellJs);
		this.ext = extSet;
		this.paramTypes = new Map();
		this.classInfos = new Map();
		this.resetPass();
	}

	resetPass() {
		this.memo = new Map();
		this.varMemo = new Map();
		this.retMemo = new Map();
		this.stack = new Set();
	}

	// GI lookups

	giType(q) {
		if (typeof q !== 'string' || !q.includes('.'))
			return null;
		const dot = q.indexOf('.');
		return this.gir[q.slice(0, dot)]?.types[q.slice(dot + 1)] ?? null;
	}

	giChain(q, fnFound, seen = new Set()) {
		if (!q || seen.has(q))
			return null;
		seen.add(q);
		const t = this.giType(q);
		if (!t)
			return null;
		const hit = fnFound(t, q);
		if (hit)
			return hit;
		for (const p of [t.parent, ...(t.implements ?? []), ...(t.prerequisites ?? [])]) {
			const r = this.giChain(p, fnFound, seen);
			if (r)
				return r;
		}
		return null;
	}

	giMember(q, name) {
		return this.giChain(q, (t, owner) => {
			if (t.methods?.[name])
				return {what: 'method', owner, info: t.methods[name]};
			if (t.props?.[name])
				return {what: 'prop', owner, info: t.props[name]};
			if (t.fields && name in t.fields)
				return {what: 'field', owner, info: {type: t.fields[name]}};
			return null;
		});
	}

	giProp(q, name) {
		return this.giChain(q, (t, owner) => (t.props?.[name] ? {what: 'prop', owner} : null));
	}

	giSignal(q, name) {
		return this.giChain(q, (t, owner) => (t.signals?.[name] ? {what: 'signal', owner, info: t.signals[name]} : null));
	}

	giStatic(q, name) {
		return this.giChain(q, (t, owner) => (t.statics?.[name] ? {what: 'static', owner, info: t.statics[name]} : null));
	}

	fromGi(ref) {
		if (!ref)
			return U;
		if (typeof ref === 'object' && 'array' in ref)
			return T.arr(this.fromGi(ref.array));
		const t = this.giType(ref);
		if (!t || t.kind === 'enum')
			return U;
		return T.gobj(ref.slice(0, ref.indexOf('.')), ref.slice(ref.indexOf('.') + 1));
	}

	// Return type as gjs hands it back: a void function with one out
	// argument returns that argument.
	giReturn(info) {
		if (!info)
			return U;
		const outs = (info.params ?? []).filter(p => p.dir === 'out');
		if ((info.ret === 'none' || !info.ret) && outs.length === 1)
			return this.fromGi(outs[0].type);
		if (outs.length > 0 && info.ret !== 'none')
			return U;
		return this.fromGi(info.ret);
	}

	// Module resolution

	resolveImport(mod, src) {
		const gi = src.match(/^gi:\/\/(\w+)/);
		if (gi)
			return {kind: 'gi', ns: gi[1]};
		for (const prefix of ['resource:///org/gnome/shell/', 'resource:///org/gnome/Shell/Extensions/js/']) {
			if (src.startsWith(prefix))
				return {kind: 'module', mod: this.shell.get(src.slice(prefix.length)), rel: src.slice(prefix.length), shell: true};
		}
		if (src.startsWith('./') || src.startsWith('../')) {
			const rel = path.posix.normalize(path.posix.join(path.posix.dirname(mod.rel), src));
			const set = mod.isExt ? this.ext : this.shell;
			return {kind: 'module', mod: set.get(rel), rel, shell: !mod.isExt};
		}
		return {kind: 'builtin', name: src};
	}

	exportType(mod, name, depth = 0) {
		if (!mod || depth > 8)
			return {found: false, type: U};
		const e = mod.exports.get(name);
		if (!e)
			return {found: false, type: U};
		if (e.reexport) {
			const target = this.resolveImport(mod, e.reexport);
			return target.kind === 'module' ? this.exportType(target.mod, e.imported, depth + 1) : {found: true, type: U};
		}
		if (e.node) {
			if (isClass(e.node))
				return {found: true, type: T.cls(mod, e.node)};
			if (isFunction(e.node))
				return {found: true, type: T.fn(mod, e.node)};
			return {found: true, type: this.typeOf(e.node, mod)};
		}
		const v = mod.moduleScope?.set.get(e.local);
		return {found: true, type: v ? this.varType(v, mod) : U};
	}

	importType(def, mod) {
		const decl = def.parent;
		const target = this.resolveImport(mod, decl.source.value);
		if (target.kind === 'gi')
			return T.gns(target.ns);
		if (target.kind !== 'module' || !target.mod)
			return U;
		const spec = def.node;
		if (spec.type === 'ImportNamespaceSpecifier')
			return T.mod(target.mod);
		const name = spec.type === 'ImportDefaultSpecifier' ? 'default' : spec.imported.name ?? spec.imported.value;
		return this.exportType(target.mod, name).type;
	}

	// Type evaluation

	typeOf(node, mod) {
		if (!node)
			return U;
		const key = node;
		if (this.memo.has(key))
			return this.memo.get(key);
		if (this.stack.has(key))
			return U;
		this.stack.add(key);
		let t;
		try {
			t = this._typeOf(node, mod);
		} finally {
			this.stack.delete(key);
		}
		this.memo.set(key, t ?? U);
		return t ?? U;
	}

	_typeOf(node, mod) {
		switch (node.type) {
		case 'Identifier': {
			const v = mod.refVar.get(node);
			if (v)
				return this.varType(v, mod);
			if (node.name === 'global')
				return T.gobj('Shell', 'Global');
			return T.jsglobal(node.name);
		}
		case 'ThisExpression': {
			const cls = enclosingClass(node);
			return cls ? T.inst(mod, cls) : U;
		}
		case 'Super': {
			const cls = enclosingClass(node);
			return cls ? this.classToInst(this.superOf(mod, cls)) : U;
		}
		case 'MemberExpression': {
			const names = propNames(node, mod);
			const objT = this.typeOf(node.object, mod);
			if (names.length !== 1) {
				if (node.computed && objT.k === 'arr')
					return objT.elem;
				return U;
			}
			return this.member(objT, names[0]).type;
		}
		case 'ChainExpression':
			return this.typeOf(node.expression, mod);
		case 'CallExpression': {
			const callee = node.callee;
			if (callee.type === 'MemberExpression' && !callee.computed && callee.property.name === 'registerClass')
				return this.typeOf(node.arguments[node.arguments.length - 1], mod);
			if (callee.type === 'MemberExpression' && !callee.computed) {
				const objT = this.typeOf(callee.object, mod);
				const name = callee.property.name;
				if (objT.k === 'arr') {
					if (ELEMENT_RETURNING.has(name))
						return objT;
					if (ELEMENT_OF.has(name))
						return objT.elem;
					return U;
				}
			}
			return this.returnOf(this.typeOf(callee, mod));
		}
		case 'NewExpression':
			return this.classToInst(this.typeOf(node.callee, mod));
		case 'ClassDeclaration':
		case 'ClassExpression':
			return T.cls(mod, node);
		case 'FunctionDeclaration':
		case 'FunctionExpression':
		case 'ArrowFunctionExpression':
			return T.fn(mod, node);
		case 'ObjectExpression':
			return T.obj(mod, node);
		case 'LogicalExpression': {
			if (node.operator === '&&')
				return this.typeOf(node.right, mod);
			const l = this.typeOf(node.left, mod);
			return known(l) ? l : this.typeOf(node.right, mod);
		}
		case 'ConditionalExpression': {
			const c = this.typeOf(node.consequent, mod);
			return known(c) ? c : this.typeOf(node.alternate, mod);
		}
		case 'AssignmentExpression':
			return this.typeOf(node.right, mod);
		case 'SequenceExpression':
			return this.typeOf(node.expressions[node.expressions.length - 1], mod);
		default:
			return U;
		}
	}

	varType(v, mod) {
		if (this.paramTypes.has(v))
			return this.paramTypes.get(v);
		if (this.varMemo.has(v))
			return this.varMemo.get(v);
		if (this.stack.has(v))
			return U;
		this.stack.add(v);
		let t = U;
		try {
			t = this._varType(v, mod);
		} finally {
			this.stack.delete(v);
		}
		this.varMemo.set(v, t);
		return t;
	}

	_varType(v, mod) {
		const def = v.defs[0];
		if (!def)
			return U;
		switch (def.type) {
		case 'ImportBinding':
			return this.importType(def, mod);
		case 'ClassName':
			return T.cls(mod, def.node);
		case 'FunctionName':
			return T.fn(mod, def.node);
		case 'Parameter':
			if (mod.dynamicGi.has(v.name))
				return T.gns(v.name);
			return this.paramFromThisCalls(v, def, mod);
		case 'Variable': {
			const decl = def.node;
			const forOf = decl.parent?.parent;
			if (forOf?.type === 'ForOfStatement' && forOf.left === decl.parent) {
				const listT = this.typeOf(forOf.right, mod);
				return listT.k === 'arr' ? listT.elem : U;
			}
			if (decl.id.type !== 'Identifier')
				return U;
			let t = decl.init ? this.typeOf(decl.init, mod) : U;
			if (known(t) && t.k !== 'jsbuiltin')
				return t;
			for (const ref of v.references) {
				if (ref.writeExpr && ref.writeExpr !== decl.init) {
					const w = this.typeOf(ref.writeExpr, mod);
					if (known(w) && w.k !== 'jsbuiltin')
						return w;
				}
			}
			if (isEmptyContainer(decl.init)) {
				const added = v.references.map(ref => addedValue(ref.identifier)).filter(Boolean);
				const elem = unionOf(added.map(a => this.typeOf(a, mod)));
				if (known(elem))
					return T.arr(elem);
			}
			return known(t) ? t : U;
		}
		default:
			return U;
		}
	}

	// A method parameter typed from the calls `this.method(...)` make in
	// the same class: panelMenu.js Button passes a PopupMenu to setMenu().
	paramFromThisCalls(v, def, mod) {
		const fnNode = def.node;
		const method = fnNode?.parent;
		if (method?.type !== 'MethodDefinition' || method.key.type !== 'Identifier')
			return U;
		const cls = method.parent.parent;
		const index = fnNode.params.findIndex(p => p === def.name || (p.type === 'AssignmentPattern' && p.left === def.name));
		if (index < 0)
			return U;
		const types = [];
		for (const n of walk(cls.body)) {
			if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression' && !n.callee.computed &&
				n.callee.object.type === 'ThisExpression' && n.callee.property.name === method.key.name &&
				n.arguments[index] && enclosingClass(n.callee.object) === cls)
				types.push(this.typeOf(n.arguments[index], mod));
		}
		return unionOf(types);
	}

	returnOf(calleeT) {
		if (calleeT.k === 'callable')
			return calleeT.ret ?? U;
		if (calleeT.k === 'fn')
			return this.fnReturn(calleeT.mod, calleeT.node);
		return U;
	}

	fnReturn(mod, fnNode) {
		if (this.retMemo.has(fnNode))
			return this.retMemo.get(fnNode);
		if (this.stack.has(fnNode))
			return U;
		this.stack.add(fnNode);
		let t = U;
		try {
			if (fnNode.type === 'ArrowFunctionExpression' && fnNode.expression) {
				t = this.typeOf(fnNode.body, mod);
			} else {
				for (const n of walk(fnNode.body)) {
					if (n.type === 'ReturnStatement' && n.argument && enclosingFunction(n) === fnNode) {
						t = this.typeOf(n.argument, mod);
						if (known(t))
							break;
					}
				}
			}
		} finally {
			this.stack.delete(fnNode);
		}
		this.retMemo.set(fnNode, t);
		return t;
	}

	classToInst(t) {
		if (t.k === 'jsglobal')
			return {k: 'jsbuiltin', name: t.name};
		if (t.k === 'union')
			return unionOf(t.types.map(x => this.classToInst(x)));
		if (t.k === 'cls')
			return T.inst(t.mod, t.node);
		if (t.k === 'gcls') {
			const td = this.giType(`${t.ns}.${t.name}`);
			if (td && td.kind !== 'enum')
				return T.gobj(t.ns, t.name, t.generated ? {generated: t.generated} : {});
		}
		return U;
	}

	// Classes written in JS (the extension's and gnome-shell's)

	classInfo(mod, node) {
		if (this.classInfos.has(node))
			return this.classInfos.get(node);
		const info = {
			name: className(node), methods: new Map(), statics: new Map(), getters: new Map(),
			fields: new Map(), emits: new Set(), gsignals: new Set(), gprops: new Set(),
		};
		for (const el of node.body.body) {
			if (el.type === 'MethodDefinition' && !el.computed && el.key.type === 'Identifier') {
				const name = el.key.name;
				if (el.static)
					info.statics.set(name, el.value);
				else if (el.kind === 'get')
					info.getters.set(name, el.value);
				else if (el.kind === 'method' || el.kind === 'constructor')
					info.methods.set(name, el.value);
			} else if (el.type === 'PropertyDefinition' && !el.computed && el.key.type === 'Identifier' && !el.static) {
				info.fields.set(el.key.name, el.value ? [el.value] : []);
			}
		}
		for (const n of walk(node.body)) {
			if (n.type === 'AssignmentExpression' && n.left.type === 'MemberExpression' &&
				n.left.object.type === 'ThisExpression' && !n.left.computed &&
				n.left.property.type === 'Identifier' && enclosingClass(n.left.object) === node) {
				const name = n.left.property.name;
				if (!info.fields.has(name))
					info.fields.set(name, []);
				info.fields.get(name).push(n.right);
			}
			if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression' && !n.callee.computed &&
				n.callee.property.name === 'emit' && n.arguments[0]) {
				if (n.arguments[0].type === 'Literal')
					info.emits.add(String(n.arguments[0].value));
				else
					info.dynamicEmit = true;
			}
		}
		// Signals emitted through a lookup table (overview.js emits
		// OVERVIEW_SHOWN_TRANSITIONS[state].signal)
		if (info.dynamicEmit) {
			for (const n of walk(mod.ast)) {
				if (n.type === 'Property' && !n.computed && (n.key.name ?? n.key.value) === 'signal' &&
					n.value.type === 'Literal' && typeof n.value.value === 'string')
					info.emits.add(n.value.value);
			}
		}
		// Signals.addSignalMethods(Class.prototype)
		for (const n of walk(mod.ast)) {
			if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression' && !n.callee.computed &&
				n.callee.property.name === 'addSignalMethods' && n.arguments[0]?.type === 'MemberExpression' &&
				n.arguments[0].object.type === 'Identifier' && n.arguments[0].object.name === info.name &&
				n.arguments[0].property.name === 'prototype')
				info.signalMethods = true;
		}
		const reg = node.parent;
		if (reg?.type === 'CallExpression' && reg.arguments.length === 2 && reg.arguments[0].type === 'ObjectExpression') {
			for (const p of reg.arguments[0].properties) {
				const key = p.key?.name ?? p.key?.value;
				if ((key === 'Signals' || key === 'Properties') && p.value.type === 'ObjectExpression') {
					for (const q of p.value.properties) {
						const k = String(q.key?.name ?? q.key?.value);
						(key === 'Signals' ? info.gsignals : info.gprops).add(k.replace(/-/g, '_'));
						if (key === 'Signals')
							info.gsignals.add(k);
					}
				}
			}
		}
		this.classInfos.set(node, info);
		return info;
	}

	classLabel(mod, node) {
		return `${mod.label}:${this.classInfo(mod, node).name}`;
	}

	superOf(mod, node) {
		return node.superClass ? this.typeOf(node.superClass, mod) : U;
	}

	ownMember(mod, node, name) {
		const ci = this.classInfo(mod, node);
		const hint = MEMBER_HINTS[`${this.classLabel(mod, node)}#${name}`];
		if (hint)
			return {what: 'hint', type: () => hint()};
		if (ci.methods.has(name))
			return {what: 'method', type: () => T.fn(mod, ci.methods.get(name)), fn: ci.methods.get(name)};
		if (ci.getters.has(name))
			return {what: 'getter', type: () => this.fnReturn(mod, ci.getters.get(name))};
		const dict = DICT_FIELDS[`${this.classLabel(mod, node)}#${name}`];
		if (dict) {
			const v = mod.moduleScope?.set.get(dict);
			const init = v?.defs[0]?.node?.init;
			return {what: 'field', type: () => (init ? T.obj(mod, init, true) : U)};
		}
		if (ci.fields.has(name)) {
			return {what: 'field', type: () => {
				const rhs = ci.fields.get(name);
				const t = unionOf(rhs.map(r => this.typeOf(r, mod)).filter(x => x.k !== 'jsbuiltin'));
				if (known(t) || !rhs.some(isEmptyContainer))
					return t;
				// this._buttons = [] plus this._buttons.push(btn)
				const added = [];
				for (const n of walk(node.body)) {
					if (n.type === 'MemberExpression' && !n.computed && n.object.type === 'MemberExpression' &&
						n.object.object.type === 'ThisExpression' && !n.object.computed &&
						n.object.property.name === name && enclosingClass(n.object.object) === node) {
						const a = addedValue(n.object);
						if (a)
							added.push(a);
					}
				}
				const elem = unionOf(added.map(a => this.typeOf(a, mod)));
				return known(elem) ? T.arr(elem) : U;
			}};
		}
		if (ci.signalMethods && SIGNAL_METHODS.includes(name))
			return {what: 'method', type: () => U};
		if (ci.gprops.has(name))
			return {what: 'gprop', type: () => U};
		const dyn = DYNAMIC_FIELDS[this.classLabel(mod, node)];
		if (dyn && this.dynamicKeys(mod, dyn).has(name))
			return {what: 'dynamic', type: () => U};
		return null;
	}

	dynamicKeys(mod, constName) {
		const keys = new Set();
		const v = mod.moduleScope?.set.get(constName);
		const init = v?.defs[0]?.node?.init;
		if (init?.type === 'ObjectExpression') {
			for (const mode of init.properties) {
				if (mode.value?.type === 'ObjectExpression') {
					for (const p of mode.value.properties)
						keys.add(String(p.key?.name ?? p.key?.value));
				}
			}
		}
		return keys;
	}

	// Walks a JS class chain. Returns the first hit, and the GI class the
	// chain ends on (for the runtime probe) when it ends on one.
	jsChain(mod, node, name, seen = new Set()) {
		if (seen.has(node))
			return {hit: null, gi: null, first: null};
		seen.add(node);
		const own = this.ownMember(mod, node, name);
		if (own)
			return {hit: {...own, owner: this.classLabel(mod, node), mod, node}, gi: null};
		const sup = this.superOf(mod, node);
		if (sup.k === 'cls')
			return this.jsChain(sup.mod, sup.node, name, seen);
		if (sup.k === 'gcls')
			return {hit: null, gi: {ns: sup.ns, name: sup.name}};
		return {hit: null, gi: null};
	}

	// Member access

	member(objT, name) {
		switch (objT.k) {
		case 'gns':
			return this.memberOfNamespace(objT.ns, name);
		case 'gcls':
			return this.memberOfGiClass(objT, name);
		case 'gobj':
			return this.memberOfGiObject(objT, name);
		case 'gpath': {
			const full = `${objT.ns}.${objT.path.join('.')}.${name}`;
			const ov = OVERRIDE_VALUES[full];
			return {
				type: ov ? ov() : T.gpath(objT.ns, [...objT.path, name]),
				use: {label: `${objT.ns}.${objT.path.join('.')}`, name, kind: 'path', sep: '.',
					probe: {kind: 'path', ns: objT.ns, path: objT.path, name}},
			};
		}
		case 'mod': {
			const e = this.exportType(objT.mod, name);
			if (objT.mod.isExt)
				return {type: e.type, use: null};
			return {type: e.type, use: {label: objT.mod.label, name, kind: 'js-export', sep: '.',
				js: {found: e.found, what: 'export'}}};
		}
		case 'cls':
			return this.memberOfClass(objT, name);
		case 'inst':
			return this.memberOfInstance(objT, name);
		case 'obj':
			return this.memberOfObject(objT, name);
		case 'union': {
			// The use is reported against the first alternative that has
			// the member; the value can be any of the found ones' types.
			const results = objT.types.map(alt => this.member(alt, name));
			const found = results.filter(isFound);
			if (found.length === 0)
				return results[0];
			return {...found[0], type: unionOf(found.map(r => r.type))};
		}
		case 'jsglobal':
		case 'jsbuiltin':
		case 'arr':
			return {type: U, use: null, internal: true};
		case 'fn':
		case 'callable':
			return {type: U, use: null, internal: true};
		default:
			return {type: U, use: null, untyped: true};
		}
	}

	memberOfNamespace(ns, name) {
		const nsd = this.gir[ns];
		const probe = {kind: 'ns', ns, name};
		const base = {label: ns, name, kind: 'ns', sep: '.', probe};
		if (!nsd)
			return {type: U, use: {...base, gi: {found: false, why: 'namespace not in this image'}}};
		const td = nsd.types[name];
		if (td)
			return {type: T.gcls(ns, name), use: {...base, gi: {found: true, what: td.kind}}};
		const fn = nsd.functions[name];
		if (fn)
			return {type: T.callable(this.giReturn(fn)), use: {...base, gi: {found: true, what: 'function'}, call: true}};
		if (nsd.constants.includes(name))
			return {type: U, use: {...base, gi: {found: true, what: 'constant'}}};
		const ov = OVERRIDE_VALUES[`${ns}.${name}`];
		return {type: ov ? ov() : T.gpath(ns, [name]),
			use: {...base, gi: {found: false, partial: Boolean(nsd.partial)}}};
	}

	memberOfGiClass(t, name) {
		const q = `${t.ns}.${t.name}`;
		const td = this.giType(q);
		if (name === '$gtype' || name === 'prototype' || name === 'name')
			return {type: U, use: null, internal: true};
		if (td?.kind === 'enum') {
			const found = td.members.includes(name) || Boolean(td.statics?.[name]);
			return {type: U, use: {label: q, name, kind: 'enum', sep: '.', gi: {found, what: 'member'},
				probe: {kind: 'enum', ns: t.ns, cls: t.name, name}}};
		}
		const hit = this.giStatic(q, name);
		const ov = OVERRIDE_VALUES[`${q}.${name}`];
		const type = ov ? ov() : hit ? T.callable(this.giReturn(hit.info)) : U;
		return {type, use: {label: q, name, kind: 'static', sep: '.', call: true,
			gi: {found: Boolean(hit), what: 'static', owner: hit?.owner, partial: this.partial(t.ns)},
			probe: {kind: 'static', ns: t.ns, cls: t.name, name}}};
	}

	memberOfGiObject(t, name) {
		if (t.generated?.test(name))
			return {type: U, use: null, internal: true};
		const q = `${t.ns}.${t.name}`;
		const hit = this.giMember(q, name);
		let type = U;
		if (hit?.what === 'method')
			type = T.callable(this.giReturn(hit.info));
		else if (hit)
			type = this.fromGi(hit.info.type);
		return {type, use: {label: q, name, kind: 'proto', sep: '#', call: hit?.what === 'method',
			gi: {found: Boolean(hit), what: hit?.what, owner: hit?.owner, partial: this.partial(t.ns)},
			probe: {kind: 'proto', ns: t.ns, cls: t.name, name}}};
	}

	memberOfClass(t, name) {
		const ci = this.classInfo(t.mod, t.node);
		if (ci.statics.has(name)) {
			const type = T.fn(t.mod, ci.statics.get(name));
			return {type, use: t.mod.isExt ? null : {label: this.classLabel(t.mod, t.node), name, kind: 'js-static',
				sep: '.', js: {found: true, what: 'static'}}};
		}
		if (t.mod.isExt)
			return {type: U, use: null, internal: true};
		return {type: U, use: {label: this.classLabel(t.mod, t.node), name, kind: 'js-static', sep: '.',
			js: {found: false}}};
	}

	memberOfInstance(t, name) {
		let {mod, node} = t;
		// The extension's own classes: internal until the chain reaches a
		// gnome-shell class or a GI class.
		const seen = new Set();
		while (mod.isExt) {
			if (seen.has(node))
				return {type: U, use: null, internal: true};
			seen.add(node);
			const own = this.ownMember(mod, node, name);
			if (own)
				return {type: own.type(), use: null, internal: true, fn: own.fn, fnMod: mod};
			const sup = this.superOf(mod, node);
			if (sup.k === 'cls') {
				({mod, node} = sup);
				continue;
			}
			if (sup.k === 'gcls')
				return this.memberOfGiObject(T.gobj(sup.ns, sup.name), name);
			return {type: U, use: null, internal: true, unresolvedOwn: true};
		}
		const label = this.classLabel(mod, node);
		const {hit, gi} = this.jsChain(mod, node, name);
		if (hit) {
			const params = hit.fn ? hit.fn.params.map(p => (p.type === 'Identifier' ? p.name
				: p.type === 'AssignmentPattern' && p.left.type === 'Identifier' ? `${p.left.name}?` : '...')) : undefined;
			return {type: hit.type(), fn: hit.fn, fnMod: hit.mod,
				use: {label, name, kind: 'js-member', sep: '#', call: hit.what === 'method',
					js: {found: true, what: hit.what, owner: hit.owner, params}}};
		}
		if (gi) {
			const r = this.memberOfGiObject(T.gobj(gi.ns, gi.name), name);
			if (r.use) {
				r.use.label = label;
				r.use.via = `${gi.ns}.${gi.name}`;
			}
			return r;
		}
		return {type: U, use: {label, name, kind: 'js-member', sep: '#', js: {found: false}}};
	}

	memberOfObject(t, name) {
		const prop = t.node.properties.find(p => p.type === 'Property' && !p.computed &&
			(p.key.name ?? p.key.value) === name);
		let type = U;
		if (prop) {
			type = this.typeOf(prop.value, t.mod);
			if (t.valuesAreClasses)
				type = this.classToInst(type);
		}
		if (t.mod.isExt)
			return {type, use: null, internal: true};
		const owner = t.node.parent?.type === 'VariableDeclarator' ? t.node.parent.id.name : '<object>';
		return {type, use: {label: `${t.mod.label}:${owner}`, name, kind: 'js-member', sep: '.',
			js: {found: Boolean(prop), what: 'key'}}};
	}

	partial(ns) {
		return Boolean(this.gir[ns]?.partial);
	}

	// Signals

	signalUse(recvT, signal) {
		if (recvT.k === 'union') {
			let first = null;
			for (const alt of recvT.types) {
				const r = this.signalUse(alt, signal);
				if (r === null)
					return null;
				first ??= r;
				if (r.gi?.found || r.js?.found)
					return r;
			}
			return first;
		}
		const [base, detail] = signal.split('::');
		const giSignal = (ns, cls, label, via) => {
			const q = `${ns}.${cls}`;
			if (base === 'notify' && detail) {
				const prop = detail.replace(/-/g, '_');
				const hit = this.giProp(q, prop);
				return {label, name: signal, kind: 'signal', sep: '::', via,
					gi: {found: Boolean(hit), what: 'prop', owner: hit?.owner, partial: this.partial(ns)},
					probe: {kind: 'proto', ns, cls, name: prop}};
			}
			const hit = this.giSignal(q, base);
			return {label, name: signal, kind: 'signal', sep: '::', via,
				gi: {found: Boolean(hit), what: 'signal', owner: hit?.owner, partial: this.partial(ns)},
				probe: {kind: 'signal', ns, cls, name: base}};
		};
		if (recvT.k === 'gobj')
			return giSignal(recvT.ns, recvT.name, `${recvT.ns}.${recvT.name}`);
		if (recvT.k !== 'inst')
			return recvT.k === 'unknown' ? {label: '<untyped>', name: signal, kind: 'signal', sep: '::', untyped: true} : null;
		let {mod, node} = recvT;
		const seen = new Set();
		while (mod.isExt) {
			if (seen.has(node))
				return null;
			seen.add(node);
			const ci = this.classInfo(mod, node);
			if (ci.emits.has(signal) || ci.gsignals.has(base))
				return null;
			const sup = this.superOf(mod, node);
			if (sup.k === 'cls') {
				({mod, node} = sup);
				continue;
			}
			if (sup.k === 'gcls')
				return giSignal(sup.ns, sup.name, `${sup.ns}.${sup.name}`);
			return null;
		}
		const label = this.classLabel(mod, node);
		for (let cur = {mod, node}, guard = 0; cur && guard < 20; guard++) {
			const ci = this.classInfo(cur.mod, cur.node);
			if (ci.emits.has(base) || ci.gsignals.has(base))
				return {label, name: signal, kind: 'signal', sep: '::', js: {found: true, owner: this.classLabel(cur.mod, cur.node)}};
			if (base === 'notify' && detail && ci.gprops.has(detail.replace(/-/g, '_')))
				return {label, name: signal, kind: 'signal', sep: '::', js: {found: true, owner: this.classLabel(cur.mod, cur.node)}};
			const sup = this.superOf(cur.mod, cur.node);
			if (sup.k === 'cls') {
				cur = {mod: sup.mod, node: sup.node};
				continue;
			}
			if (sup.k === 'gcls') {
				const r = giSignal(sup.ns, sup.name, label, `${sup.ns}.${sup.name}`);
				return r;
			}
			break;
		}
		return {label, name: signal, kind: 'signal', sep: '::', js: {found: false}};
	}
}

function isFound(r) {
	if (!r)
		return false;
	if (r.use)
		return Boolean(r.use.gi?.found || r.use.js?.found);
	return !r.untyped && !r.unresolvedOwn;
}

// Section: guards

function sourceOf(mod, node) {
	return mod.src.slice(node.range[0], node.range[1]);
}

// Polarity of `text` inside a test: +1 when the test is true only if the
// symbol exists, -1 when true only if it is missing, 0 when absent.
function testPolarity(test, text, name, objText, mod) {
	let polarity = 0;
	for (const n of walk(test)) {
		if (n.type === 'BinaryExpression' && n.operator === 'in' && n.left.type === 'Literal' &&
			n.left.value === name && sourceOf(mod, n.right) === objText) {
			polarity = n.parent?.type === 'UnaryExpression' && n.parent.operator === '!' ? -1 : 1;
			break;
		}
		const isTarget = (n.type === 'MemberExpression' || n.type === 'ChainExpression') &&
			sourceOf(mod, n).replace(/\?\./g, '.') === text.replace(/\?\./g, '.');
		if (!isTarget)
			continue;
		// Calling it is a use, not a test: `win.is_maximized() ? a : b`
		// throws when the method is missing.
		if (n.parent?.type === 'CallExpression' && n.parent.callee === n && !n.parent.optional)
			continue;
		polarity = 1;
		const p = n.parent;
		if (p?.type === 'UnaryExpression' && p.operator === '!') {
			polarity = -1;
		} else if (p?.type === 'UnaryExpression' && p.operator === 'typeof') {
			const cmp = p.parent;
			if (cmp?.type === 'BinaryExpression') {
				const other = cmp.left === p ? cmp.right : cmp.left;
				const eq = cmp.operator === '===' || cmp.operator === '==';
				const isUndefined = other.value === 'undefined';
				polarity = (eq === isUndefined) ? -1 : 1;
			}
		} else if (p?.type === 'BinaryExpression' && ['===', '==', '!==', '!='].includes(p.operator)) {
			const other = p.left === n ? p.right : p.left;
			const nullish = (other.type === 'Literal' && other.value === null) ||
				(other.type === 'Identifier' && other.name === 'undefined');
			if (nullish)
				polarity = p.operator.startsWith('!') ? 1 : -1;
		}
		break;
	}
	return polarity;
}

const exits = stmt => stmt && (stmt.type === 'ReturnStatement' || stmt.type === 'ThrowStatement' ||
	(stmt.type === 'BlockStatement' && stmt.body.some(s => s.type === 'ReturnStatement' || s.type === 'ThrowStatement')));

// What protects a use: optional chaining on it, a fallback after it, or a
// feature test (typeof, `in`, comparison, truthiness) around or before it.
// A try block is reported, but it is not a guard: the feature still breaks.
function guardOf(mod, member, name) {
	const text = sourceOf(mod, member);
	const objText = member.object ? sourceOf(mod, member.object) : '';
	const p = member.parent;
	let guard = null;
	if ((p?.type === 'MemberExpression' && p.object === member && p.optional) ||
		(p?.type === 'CallExpression' && p.callee === member && p.optional))
		guard = 'optional chaining';
	else if (p?.type === 'LogicalExpression' && p.left === member && (p.operator === '??' || p.operator === '||'))
		guard = `${p.operator} fallback`;

	let inTry = false;
	for (let child = member, n = member.parent; n && !guard; child = n, n = n.parent) {
		if (n.type === 'TryStatement' && n.block === child)
			inTry = true;
		// The use is itself the feature test
		if ((n.type === 'IfStatement' || n.type === 'ConditionalExpression') && n.test === child &&
			testPolarity(n.test, text, name, objText, mod) !== 0)
			guard = 'feature test';
		if (n.type === 'LogicalExpression' && n.left === child && testPolarity(n.left, text, name, objText, mod) !== 0 &&
			n.operator === '&&')
			guard = 'feature test';
		if ((n.type === 'IfStatement' || n.type === 'ConditionalExpression') && n.test !== child) {
			const pol = testPolarity(n.test, text, name, objText, mod);
			if ((pol > 0 && n.consequent === child) || (pol < 0 && n.alternate === child))
				guard = 'feature test';
		}
		if (n.type === 'LogicalExpression' && n.right === child) {
			const pol = testPolarity(n.left, text, name, objText, mod);
			if ((n.operator === '&&' && pol > 0) || ((n.operator === '||' || n.operator === '??') && pol < 0))
				guard = 'feature test';
		}
		if ((n.type === 'BlockStatement' || n.type === 'Program') && !guard) {
			const idx = n.body.indexOf(child);
			for (let i = 0; i < idx; i++) {
				const s = n.body[i];
				if (s.type === 'IfStatement' && exits(s.consequent) &&
					testPolarity(s.test, text, name, objText, mod) < 0) {
					guard = 'early return';
					break;
				}
			}
		}
		if (isFunction(n))
			break;
	}
	if (!guard) {
		for (let child = member, n = member.parent; n; child = n, n = n.parent) {
			if (n.type === 'TryStatement' && n.block === child) {
				inTry = true;
				break;
			}
		}
	}
	return {guard, inTry};
}

// Section: analyze

function parseArgs(argv) {
	const out = {_: []};
	for (let i = 0; i < argv.length; i++) {
		const a = argv[i];
		if (a.startsWith('--')) {
			const key = a.slice(2);
			const val = argv[++i];
			if (key === 'target')
				(out.target ??= []).push(val);
			else
				out[key] = val;
		} else {
			out._.push(a);
		}
	}
	return out;
}

function moduleGraph(extSet, program, entry) {
	const seen = new Set();
	const todo = [entry];
	while (todo.length) {
		const rel = todo.pop();
		if (seen.has(rel))
			continue;
		const mod = extSet.get(rel);
		if (!mod)
			continue;
		seen.add(rel);
		for (const imp of mod.imports) {
			const r = program.resolveImport(mod, imp.source.value);
			if (r.kind === 'module' && !r.shell)
				todo.push(r.rel);
		}
		for (const stmt of mod.ast.body) {
			if ((stmt.type === 'ExportNamedDeclaration' || stmt.type === 'ExportAllDeclaration') && stmt.source) {
				const r = program.resolveImport(mod, stmt.source.value);
				if (r.kind === 'module' && !r.shell)
					todo.push(r.rel);
			}
		}
	}
	return seen;
}

function analyze(opts) {
	const extDir = path.resolve(opts.ext);
	const extSet = new ModuleSet(extDir, 'ext');
	const rels = listJs(extDir);
	const mods = rels.map(r => extSet.get(r)).filter(Boolean);
	const targets = (opts.target ?? []).map(spec => {
		const [id, major, shellJs, gir] = spec.split(':');
		return {id, major: Number(major), shellJs, gir};
	});
	if (targets.length === 0)
		throw new Error('no --target given');

	const programs = targets.map(t => new Program(t, extSet));

	// Which process each module runs in
	const shellGraph = moduleGraph(extSet, programs[0], 'extension.js');
	const prefsGraph = moduleGraph(extSet, programs[0], 'prefs.js');
	const procOf = rel => (shellGraph.has(rel) && prefsGraph.has(rel) ? 'both'
		: prefsGraph.has(rel) ? 'prefs' : 'shell');

	// Type inference: parameters from call sites and callbacks, to a fixed
	// point. Four passes settle every chain in the extension today; a fifth
	// changes nothing.
	for (const prog of programs) {
		for (let pass = 0; pass < 5; pass++) {
			prog.resetPass();
			let changed = false;
			const bind = (v, t) => {
				if (v && known(t) && !known(prog.paramTypes.get(v) ?? U)) {
					prog.paramTypes.set(v, t);
					changed = true;
				}
			};
			const bindParams = (fnNode, fnMod, args, mod, thisArgs = []) => {
				fnNode.params.forEach((param, i) => {
					const arg = args[i];
					if (!arg)
						return;
					let target = param;
					if (target.type === 'AssignmentPattern')
						target = target.left;
					if (target.type === 'Identifier') {
						bind(fnMod.refVar.get(target), thisArgs[i] ?? prog.typeOf(arg, mod));
					} else if (target.type === 'ObjectPattern' && arg.type === 'ObjectExpression') {
						for (const prop of target.properties) {
							if (prop.type !== 'Property')
								continue;
							const key = prop.key.name ?? prop.key.value;
							let value = prop.value;
							if (value.type === 'AssignmentPattern')
								value = value.left;
							const src = arg.properties.find(q => q.type === 'Property' && (q.key.name ?? q.key.value) === key);
							if (src && value.type === 'Identifier')
								bind(fnMod.refVar.get(value), prog.typeOf(src.value, mod));
						}
					}
				});
			};
			const bindCallbackParams = (fnNode, fnMod, types) => {
				fnNode.params.forEach((param, i) => {
					if (param.type === 'Identifier' && types[i])
						bind(fnMod.refVar.get(param), types[i]);
				});
			};
			for (const mod of mods) {
				// Hinted parameters of overridden shell methods
				for (const n of walk(mod.ast)) {
					if (isClass(n)) {
						for (const el of n.body.body) {
							if (el.type !== 'MethodDefinition' || el.key.type !== 'Identifier')
								continue;
							const sup = prog.superOf(mod, n);
							if (sup.k !== 'cls' || sup.mod.isExt)
								continue;
							const {hit} = prog.jsChain(sup.mod, sup.node, el.key.name);
							const hint = hit && PARAM_HINTS[`${hit.owner}#${el.key.name}`];
							if (hint)
								bindCallbackParams(el.value, mod, hint.map(h => h()));
						}
					}
				}
				for (const n of walk(mod.ast)) {
					if (n.type !== 'CallExpression' && n.type !== 'NewExpression')
						continue;
					const args = n.arguments;
					if (n.type === 'NewExpression') {
						const ct = prog.typeOf(n.callee, mod);
						if (ct.k === 'cls' && ct.mod.isExt) {
							// The constructor, or _init for GObject.registerClass
							let cur = ct;
							for (let depth = 0; cur.k === 'cls' && cur.mod.isExt && depth < 10; depth++) {
								const ci = prog.classInfo(cur.mod, cur.node);
								const ctor = ci.methods.get('constructor') ?? ci.methods.get('_init');
								if (ctor) {
									bindParams(ctor, cur.mod, args, mod);
									break;
								}
								cur = prog.superOf(cur.mod, cur.node);
							}
						}
						continue;
					}
					const callee = n.callee.type === 'ChainExpression' ? n.callee.expression : n.callee;
					let fnTarget = null;
					if (callee.type === 'Identifier' || callee.type === 'MemberExpression') {
						const ct = prog.typeOf(callee, mod);
						if (ct.k === 'fn' && ct.mod.isExt)
							fnTarget = ct;
					}
					if (fnTarget)
						bindParams(fnTarget.node, fnTarget.mod, args, mod);

					if (callee.type !== 'MemberExpression' || callee.computed)
						continue;
					const method = callee.property.name;
					const recvT = prog.typeOf(callee.object, mod);
					const fnArgs = args.filter(a => isFunction(a));
					if (fnArgs.length === 0)
						continue;
					if (recvT.k === 'arr' && ELEMENT_CALLBACKS.has(method)) {
						const types = method === 'sort' || method === 'toSorted' ? [recvT.elem, recvT.elem] : [recvT.elem];
						bindCallbackParams(fnArgs[0], mod, types);
					} else if ((method === 'connect' || method === 'connect_after') && args[0]?.type === 'Literal') {
						const types = [recvT];
						if (recvT.k === 'gobj') {
							const sig = prog.giSignal(`${recvT.ns}.${recvT.name}`, String(args[0].value).split('::')[0]);
							for (const p of sig?.info.params ?? [])
								types.push(prog.fromGi(p.type));
						}
						bindCallbackParams(fnArgs[fnArgs.length - 1], mod, types);
					} else if (recvT.k === 'gobj') {
						// Async callbacks get the source object first
						bindCallbackParams(fnArgs[fnArgs.length - 1], mod, [recvT]);
					}
				}
			}
			if (!changed && pass > 0)
				break;
		}
		prog.resetPass();
	}

	// Collect uses
	const uses = new Map();
	const expandos = new Set();
	const extNames = new Set();
	const useKey = (mod, node, name, kind) => `${mod.rel}:${node.range[0]}:${node.range[1]}:${kind}:${name}`;
	const recordUse = (prog, mod, node, name, kind, r, extra = {}) => {
		const key = useKey(mod, node, name, kind);
		if (!uses.has(key)) {
			const {guard, inTry} = guardOf(mod, node, name);
			uses.set(key, {
				file: mod.rel, line: node.loc.start.line, col: node.loc.start.column + 1,
				code: sourceOf(mod, node).split('\n')[0].slice(0, 120),
				name, kind, proc: procOf(mod.rel), guard, inTry, perTarget: {}, ...extra,
			});
		}
		uses.get(key).perTarget[prog.target.id] = r;
	};

	for (const mod of mods) {
		for (const n of walk(mod.ast)) {
			if (isClass(n)) {
				for (const el of n.body.body) {
					if (el.key?.type === 'Identifier')
						extNames.add(el.key.name);
				}
			}
			if (n.type === 'Property' && !n.computed && n.key)
				extNames.add(n.key.name ?? String(n.key.value));
			if (n.type === 'AssignmentExpression' && n.left.type === 'MemberExpression' && !n.left.computed &&
				n.left.object.type !== 'ThisExpression' && n.left.property.type === 'Identifier')
				expandos.add(n.left.property.name);
			if (n.type === 'AssignmentExpression' && n.left.type === 'MemberExpression' && !n.left.computed &&
				n.left.object.type === 'ThisExpression' && n.left.property.type === 'Identifier')
				extNames.add(n.left.property.name);
		}
	}

	for (const prog of programs) {
		for (const mod of mods) {
			for (const n of walk(mod.ast)) {
				if (n.type === 'ImportDeclaration') {
					const r = prog.resolveImport(mod, n.source.value);
					if (r.kind === 'gi') {
						recordUse(prog, mod, n.source, r.ns, 'namespace', {label: 'gi://', name: r.ns, kind: 'namespace', sep: '',
							gi: {found: Boolean(prog.gir[r.ns])}, probe: {kind: 'namespace', ns: r.ns}});
					} else if (r.kind === 'module' && r.shell) {
						const names = n.specifiers.map(s => (s.type === 'ImportNamespaceSpecifier' ? '*'
							: s.type === 'ImportDefaultSpecifier' ? 'default' : s.imported.name ?? s.imported.value));
						for (const name of names) {
							const found = Boolean(r.mod) && (name === '*' || prog.exportType(r.mod, name).found);
							recordUse(prog, mod, n.source, name, 'import', {label: r.rel, name, kind: 'import', sep: ' import ',
								js: {found, what: r.mod ? 'export' : 'module'}});
						}
					}
					continue;
				}
				if (n.type === 'MemberExpression') {
					const names = propNames(n, mod);
					const isWrite = n.parent?.type === 'AssignmentExpression' && n.parent.left === n;
					const callNode = n.parent?.type === 'CallExpression' && n.parent.callee === n ? n.parent
						: n.parent?.type === 'ChainExpression' && n.parent.parent?.type === 'CallExpression' &&
							n.parent.parent.callee === n.parent ? n.parent.parent : null;
					const argc = callNode && !callNode.arguments.some(a => a.type === 'SpreadElement')
						? callNode.arguments.length : null;
					for (const name of names) {
						const objT = prog.typeOf(n.object, mod);
						const r = prog.member(objT, name);
						if (r.use) {
							recordUse(prog, mod, n, name, 'member', {...r.use, argc: callNode ? argc : undefined,
								write: isWrite || undefined});
						} else if (r.untyped && !BUILTIN_NAMES.has(name)) {
							recordUse(prog, mod, n, name, 'member', {label: '<untyped>', name, kind: 'untyped', sep: '#',
								untyped: true, argc: callNode ? argc : undefined, write: isWrite || undefined});
						}
					}
				}
				if (n.type === 'NewExpression') {
					const ct = prog.typeOf(n.callee, mod);
					const arg = n.arguments[0];
					if (ct.k === 'gcls' && arg?.type === 'ObjectExpression') {
						const q = `${ct.ns}.${ct.name}`;
						const td = prog.giType(q);
						if (td && (td.kind === 'class' || td.kind === 'interface')) {
							for (const p of arg.properties) {
								if (p.type !== 'Property' || p.computed)
									continue;
								const key = String(p.key.name ?? p.key.value).replace(/-/g, '_');
								const hit = prog.giProp(q, key);
								recordUse(prog, mod, p.key, key, 'ctor-prop', {label: q, name: key, kind: 'ctor-prop', sep: ' ctor ',
									gi: {found: Boolean(hit), what: 'prop', owner: hit?.owner, partial: prog.partial(ct.ns)},
									probe: {kind: 'proto', ns: ct.ns, cls: ct.name, name: key}});
							}
						}
					}
				}
				if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression' && !n.callee.computed) {
					const method = n.callee.property.name;
					const a0 = n.arguments[0];
					if ((method === 'connect' || method === 'connect_after') && a0?.type === 'Literal' && typeof a0.value === 'string') {
						const r = prog.signalUse(prog.typeOf(n.callee.object, mod), a0.value);
						if (r)
							recordUse(prog, mod, a0, a0.value, 'signal', r);
					}
					// settings.bind(key, object, 'property', flags)
					if (method === 'bind' && n.arguments.length === 4 && n.arguments[2]?.type === 'Literal') {
						const recvT = prog.typeOf(n.callee.object, mod);
						if (recvT.k === 'gobj' && recvT.ns === 'Gio' && recvT.name === 'Settings') {
							const objT = prog.typeOf(n.arguments[1], mod);
							const prop = String(n.arguments[2].value).replace(/-/g, '_');
							if (objT.k === 'gobj') {
								const q = `${objT.ns}.${objT.name}`;
								const hit = prog.giProp(q, prop);
								recordUse(prog, mod, n.arguments[2], prop, 'bound-prop', {label: q, name: prop, kind: 'bound-prop',
									sep: ' bind ', gi: {found: Boolean(hit), what: 'prop', owner: hit?.owner, partial: prog.partial(objT.ns)},
									probe: {kind: 'proto', ns: objT.ns, cls: objT.name, name: prop}});
							}
						}
					}
				}
			}
		}
	}

	// Language features, globals, regular expressions, process separation
	const featureUses = [];
	const globals = new Map();
	const regexes = [];
	const violations = [];
	const featureById = new Map(FEATURES.map(f => [f.id, f]));
	for (const mod of mods) {
		const proc = procOf(mod.rel);
		for (const [name, id] of mod.globals) {
			if (!globals.has(name))
				globals.set(name, []);
			globals.get(name).push({file: mod.rel, line: id.loc.start.line, proc});
			if (name === 'global' && proc !== 'shell') {
				violations.push({file: mod.rel, line: id.loc.start.line,
					what: '`global` is only defined in the shell process, and this module is loaded by the preferences window too'});
			}
		}
		for (const imp of mod.imports) {
			const src = imp.source.value;
			const gi = src.match(/^gi:\/\/(\w+)/)?.[1];
			if (proc !== 'shell' && ((gi && SHELL_ONLY_NS.has(gi)) || src.startsWith('resource:///org/gnome/shell/'))) {
				violations.push({file: mod.rel, line: imp.loc.start.line,
					what: `imports ${src}, which the preferences window must not load (EGO review guidelines)`});
			}
			if (proc !== 'prefs' && ((gi && PREFS_ONLY_NS.has(gi)) || src.startsWith('resource:///org/gnome/Shell/Extensions/'))) {
				violations.push({file: mod.rel, line: imp.loc.start.line,
					what: `imports ${src}, which the shell process must not load (EGO review guidelines)`});
			}
		}
		for (const n of walk(mod.ast)) {
			if (n.type === 'Literal' && n.regex) {
				regexes.push({file: mod.rel, line: n.loc.start.line, pattern: n.regex.pattern, flags: n.regex.flags,
					id: `regex ${mod.rel}:${n.loc.start.line} /${n.regex.pattern}/${n.regex.flags}`});
			}
			if (n.type === 'ImportDeclaration' && n.attributes?.length) {
				featureUses.push({id: 'import attributes', file: mod.rel, line: n.loc.start.line,
					test: null, syntax: true});
			}
			if (n.type !== 'MemberExpression' || n.computed || n.property.type !== 'Identifier')
				continue;
			const name = n.property.name;
			for (const f of FEATURES) {
				if (f.stat && n.object.type === 'Identifier' && n.object.name === f.stat[0] && name === f.stat[1] &&
					!mod.refVar.get(n.object))
					featureUses.push({id: f.id, file: mod.rel, line: n.loc.start.line, proc});
				if (f.method && name === f.method && n.parent?.type === 'CallExpression' && n.parent.callee === n) {
					// A typed GNOME receiver means an API method, not the builtin
					const typedExternal = programs.some(prog => {
						const t = prog.typeOf(n.object, mod);
						return ['gobj', 'inst', 'gns', 'gcls', 'mod'].includes(t.k);
					});
					if (!typedExternal)
						featureUses.push({id: f.id, file: mod.rel, line: n.loc.start.line, proc});
				}
			}
			if (ITERATOR_HELPERS.has(name) && n.object.type === 'CallExpression' &&
				n.object.callee.type === 'MemberExpression' && !n.object.callee.computed &&
				ITERATOR_SOURCES.has(n.object.callee.property.name) &&
				!(n.object.callee.object.type === 'Identifier' && n.object.callee.object.name === 'Object'))
				featureUses.push({id: 'Iterator.prototype helpers', file: mod.rel, line: n.loc.start.line, proc});
		}
		for (const [name] of mod.globals) {
			const f = FEATURES.find(x => x.global === name);
			if (f)
				featureUses.push({id: f.id, file: mod.rel, line: mod.globals.get(name).loc.start.line, proc});
		}
	}

	// Name index for untyped receivers: does a GNOME API anywhere carry this
	// name, per target?
	const untypedNames = new Set();
	for (const u of uses.values()) {
		for (const r of Object.values(u.perTarget)) {
			if (r.untyped)
				untypedNames.add(u.name);
		}
	}
	const nameIndex = {};
	for (const prog of programs) {
		const idx = {};
		const giNames = new Set();
		const partialNs = [];
		for (const [ns, nsd] of Object.entries(prog.gir)) {
			if (nsd.partial)
				partialNs.push(ns);
			for (const td of Object.values(nsd.types)) {
				for (const key of ['methods', 'props', 'fields', 'statics', 'signals'])
					Object.keys(td[key] ?? {}).forEach(k => giNames.add(k));
			}
		}
		const jsNames = new Set();
		for (const rel of listJs(prog.target.shellJs)) {
			const m = prog.shell.get(rel);
			if (!m)
				continue;
			for (const n of walk(m.ast)) {
				if (isClass(n)) {
					const ci = prog.classInfo(m, n);
					for (const map of [ci.methods, ci.getters, ci.fields, ci.statics])
						map.forEach((_v, k) => jsNames.add(k));
				}
			}
		}
		for (const name of untypedNames)
			idx[name] = {gi: giNames.has(name), js: jsNames.has(name)};
		nameIndex[prog.target.id] = {names: idx, partialNs};
	}

	// Probe list: every GI symbol any target asked about, deduplicated.
	const checks = new Map();
	const probeId = p => [p.kind, p.ns, p.cls ?? '', (p.path ?? []).join('.'), p.name ?? ''].join('|');
	for (const u of uses.values()) {
		for (const r of Object.values(u.perTarget)) {
			if (!r.probe)
				continue;
			const id = probeId(r.probe);
			r.probeId = id;
			const prev = checks.get(id);
			const proc = prev && prev.proc !== u.proc ? 'both' : u.proc;
			checks.set(id, {id, ...r.probe, proc});
		}
	}
	const probeFeatures = [
		...FEATURES.map(f => ({id: f.id, test: f.test})),
		...regexes.map(r => ({id: r.id,
			test: `(() => { try { new RegExp(${JSON.stringify(r.pattern)}, ${JSON.stringify(r.flags)}); return true; } catch (e) { return false; } })()`})),
	];

	const analysis = {
		generated: new Date().toISOString(),
		ext: extDir,
		targets: targets.map(t => ({id: t.id, major: t.major, shellJs: t.shellJs})),
		modules: rels.map(r => ({file: r, proc: procOf(r)})),
		uses: [...uses.values()],
		expandos: [...expandos].filter(n => !BUILTIN_NAMES.has(n)),
		extNames: [...extNames],
		nameIndex,
		featureUses,
		regexes,
		globals: Object.fromEntries(globals),
		violations,
		dynamicImports: mods.flatMap(m => [...m.dynamicGi].map(ns => ({file: m.rel, ns, proc: procOf(m.rel)}))),
	};
	fs.writeFileSync(opts.out, JSON.stringify(analysis, null, 1));
	fs.writeFileSync(opts.probe, JSON.stringify({
		checks: [...checks.values()],
		features: probeFeatures,
		globals: [...globals.keys()].filter(g => g !== 'global'),
	}, null, 1));
	const typed = analysis.uses.filter(u => Object.values(u.perTarget).some(r => !r.untyped)).length;
	console.log(`analyze: ${mods.length} modules, ${analysis.uses.length} uses (${typed} typed), ` +
		`${checks.size} runtime checks, ${targets.length} targets`);
	return 0;
}

// Section: report

function readJson(file, fallback = null) {
	try {
		return JSON.parse(fs.readFileSync(file, 'utf8'));
	} catch (_e) {
		return fallback;
	}
}

function report(opts) {
	const analysis = readJson(opts.analysis);
	if (!analysis)
		throw new Error(`cannot read ${opts.analysis}`);
	const resultsDir = opts.results;
	const targets = analysis.targets.map(t => {
		const dir = path.join(resultsDir, t.id);
		const versions = {};
		const vtext = fs.existsSync(path.join(dir, 'versions.txt')) ? fs.readFileSync(path.join(dir, 'versions.txt'), 'utf8') : '';
		for (const line of vtext.split('\n')) {
			const m = line.match(/^(\S+) (.*)$/);
			if (!m)
				continue;
			if (m[1] === 'pkg') {
				const [pkg, ...rest] = m[2].split(' ');
				versions[`pkg:${pkg}`] = rest.join(' ');
			} else {
				versions[m[1]] = m[2];
			}
		}
		const probe = {
			shell: readJson(path.join(dir, 'probe-shell.json')),
			prefs: readJson(path.join(dir, 'probe-prefs.json')),
		};
		const parse = fs.existsSync(path.join(dir, 'parse.txt'))
			? fs.readFileSync(path.join(dir, 'parse.txt'), 'utf8').split('\n').filter(Boolean).map(l => {
				const [file, status, result] = l.split('\t');
				return {file, status: Number(status), result};
			}) : null;
		const infra = fs.existsSync(path.join(dir, 'error.txt')) ? fs.readFileSync(path.join(dir, 'error.txt'), 'utf8').trim() : null;
		return {...t, versions, probe, parse, infra};
	});

	const expandos = new Set(analysis.expandos);
	const extNames = new Set(analysis.extNames);
	const failures = [];
	const notes = [];

	const runtimeOf = (t, r, proc) => {
		if (!r.probeId)
			return null;
		const modes = proc === 'both' ? ['shell', 'prefs'] : [proc];
		let res = null;
		for (const m of modes) {
			const x = t.probe[m]?.results?.[r.probeId];
			if (x) {
				res = x;
				if (!x.present)
					return x;
			}
		}
		return res;
	};

	// Per use, per target status
	const statusOf = (u, t) => {
		const r = u.perTarget[t.id];
		if (!r)
			return {status: 'n/a'};
		if (r.untyped) {
			const idx = analysis.nameIndex[t.id]?.names[u.name];
			if (extNames.has(u.name) || expandos.has(u.name))
				return {status: 'internal'};
			return {status: idx && (idx.gi || idx.js) ? 'present' : 'absent', byName: true};
		}
		if (r.js) {
			return {status: r.js.found ? 'present' : 'missing', source: 'gnome-shell source',
				params: r.js.params, what: r.js.what, owner: r.js.owner};
		}
		if (r.gi || r.probe) {
			const rt = runtimeOf(t, r, u.proc);
			const girFound = Boolean(r.gi?.found);
			let status;
			let source;
			if (rt && !rt.error?.includes('not loaded')) {
				status = rt.present ? 'present' : 'missing';
				source = rt.present && !girFound ? 'gjs runtime (not in GIR: override or partial dump)' : 'gjs runtime';
			} else {
				status = girFound ? 'present' : 'missing';
				source = 'GIR';
			}
			const out = {status, source, owner: r.gi?.owner};
			if (status === 'present' && rt?.native && typeof rt.length === 'number' && typeof r.argc === 'number') {
				out.jsArity = rt.length;
				if (r.argc < rt.length)
					out.status = 'too few arguments';
				else if (r.argc > rt.length)
					out.status = 'too many arguments';
			}
			if (rt?.symbol)
				out.symbol = rt.symbol;
			return out;
		}
		return {status: 'unknown'};
	};

	// Group uses into symbols
	const symbols = new Map();
	for (const u of analysis.uses) {
		const first = analysis.targets.map(t => u.perTarget[t.id]).find(r => r && !r.untyped) ??
			Object.values(u.perTarget)[0];
		const label = first?.label ?? '<untyped>';
		const sep = first?.sep ?? '#';
		const key = first?.kind === 'ctor-prop' ? `new ${label}({${u.name}})`
			: first?.kind === 'import' ? `import {${u.name}} from ${label}`
			: first?.kind === 'namespace' ? `gi://${u.name}`
			: `${label}${sep}${u.name}${Object.values(u.perTarget).some(r => r.call || typeof r.argc === 'number') ? '()' : ''}`;
		if (!symbols.has(key))
			symbols.set(key, {key, kind: first?.kind ?? 'untyped', via: first?.via, uses: [], perTarget: {}});
		const sym = symbols.get(key);
		sym.uses.push(u);
	}

	const BAD = new Set(['missing', 'too few arguments', 'too many arguments']);
	for (const sym of symbols.values()) {
		for (const t of targets) {
			const states = sym.uses.map(u => ({u, s: statusOf(u, t)}));
			const bad = states.filter(x => BAD.has(x.s.status));
			const worst = bad[0]?.s ?? states.find(x => x.s.status === 'present')?.s ?? states[0].s;
			sym.perTarget[t.id] = {...worst, unguarded: bad.filter(x => !x.u.guard).length,
				guarded: bad.filter(x => x.u.guard).length};
		}
		// An expando the extension sets itself on a GNOME object, or an
		// untyped name no GNOME API has anywhere, is our own data.
		const anyPresent = targets.some(t => sym.perTarget[t.id].status === 'present');
		const untyped = sym.kind === 'untyped';
		// Also a field the extension sets on its own subclass of a GNOME
		// class (this._globalMenuButton in MenuBarButton), read elsewhere
		// through the GNOME type.
		const memberAccess = ['proto', 'js-member', 'untyped'].includes(sym.kind);
		if (!anyPresent && memberAccess && (expandos.has(sym.uses[0].name) || extNames.has(sym.uses[0].name) || untyped)) {
			sym.internal = true;
			continue;
		}
		if (untyped && targets.every(t => ['present', 'internal'].includes(sym.perTarget[t.id].status))) {
			sym.byNameOnly = true;
		}
		if (targets.every(t => sym.perTarget[t.id].status === 'internal'))
			sym.internal = true;
	}

	const shown = [...symbols.values()].filter(s => !s.internal);
	for (const sym of shown) {
		for (const t of targets) {
			const c = sym.perTarget[t.id];
			const byName = sym.kind === 'untyped';
			const missing = BAD.has(c.status) || (byName && c.status === 'absent' &&
				targets.some(o => sym.perTarget[o.id].status === 'present'));
			if (!missing)
				continue;
			// Only the uses that break in this target
			const badUses = byName ? sym.uses : sym.uses.filter(u => BAD.has(statusOf(u, t).status));
			const where = badUses.filter(u => !u.guard).map(u => `${u.file}:${u.line}`);
			const guardedAt = badUses.filter(u => u.guard).map(u => `${u.file}:${u.line} (${u.guard})`);
			const tries = badUses.filter(u => !u.guard && u.inTry).map(u => `${u.file}:${u.line}`);
			const status = byName ? 'no GNOME API of this name (receiver untyped)' : c.status;
			if (where.length > 0) {
				failures.push({symbol: sym.key, target: t.id, major: t.major, status,
					detail: c.jsArity !== undefined ? `gjs wants ${c.jsArity} argument(s)` : c.source,
					at: where, inTry: tries});
			} else {
				notes.push({symbol: sym.key, target: t.id, major: t.major, status, guardedAt});
			}
		}
	}

	// JS signature changes across versions (informational)
	for (const sym of shown) {
		const sigs = new Set(targets.map(t => JSON.stringify(sym.perTarget[t.id].params ?? null)));
		if (sigs.size > 1)
			sym.signatureChanged = Object.fromEntries(targets.map(t => [t.id, sym.perTarget[t.id].params ?? null]));
	}

	// Language features
	const featureRows = [];
	const usedFeatures = new Map();
	for (const fu of analysis.featureUses) {
		if (!usedFeatures.has(fu.id))
			usedFeatures.set(fu.id, []);
		usedFeatures.get(fu.id).push(fu);
	}
	for (const [id, list] of usedFeatures) {
		const row = {id, at: list.map(x => `${x.file}:${x.line}`), perTarget: {}};
		for (const t of targets) {
			const modes = new Set(list.map(x => (x.proc === 'both' ? ['shell', 'prefs'] : [x.proc])).flat());
			const ok = [...modes].every(m => t.probe[m]?.features?.[id]?.ok);
			row.perTarget[t.id] = ok ? 'present' : 'missing';
			if (!ok)
				failures.push({symbol: `JS ${id}`, target: t.id, major: t.major, status: 'missing in this gjs', at: row.at});
		}
		featureRows.push(row);
	}
	for (const r of analysis.regexes) {
		for (const t of targets) {
			const ok = ['shell', 'prefs'].some(m => t.probe[m]?.features?.[r.id]?.ok);
			if (!ok)
				failures.push({symbol: r.id, target: t.id, major: t.major, status: 'does not compile in this gjs', at: [`${r.file}:${r.line}`]});
		}
	}
	const globalRows = [];
	for (const [name, list] of Object.entries(analysis.globals)) {
		if (name === 'global')
			continue;
		const row = {name, at: list.map(x => `${x.file}:${x.line}`), perTarget: {}};
		for (const t of targets) {
			const modes = new Set(list.map(x => (x.proc === 'both' ? ['shell', 'prefs'] : [x.proc])).flat());
			const ok = [...modes].every(m => t.probe[m]?.globals?.[name]);
			row.perTarget[t.id] = ok ? 'present' : 'missing';
			if (!ok)
				failures.push({symbol: `global ${name}`, target: t.id, major: t.major, status: 'not defined in this gjs', at: row.at});
		}
		globalRows.push(row);
	}

	// All features, used or not, per gjs (a reference for future code)
	const featureMatrix = {};
	for (const t of targets) {
		for (const [id, res] of Object.entries(t.probe.shell?.features ?? {})) {
			if (id.startsWith('regex '))
				continue;
			(featureMatrix[id] ??= {})[t.id] = res.ok;
		}
	}

	for (const v of analysis.violations)
		failures.push({symbol: 'process separation', target: 'all', status: v.what, at: [`${v.file}:${v.line}`]});

	// In-container parse and link of every module
	for (const t of targets) {
		if (t.infra) {
			failures.push({symbol: 'image', target: t.id, major: t.major, status: t.infra, at: []});
			continue;
		}
		if (!t.probe.shell || !t.probe.prefs)
			failures.push({symbol: 'runtime probe', target: t.id, major: t.major, status: 'probe produced no result', at: []});
		for (const p of t.parse ?? []) {
			if (p.status !== 0 || !p.result?.startsWith('OK'))
				failures.push({symbol: `parse ${p.file}`, target: t.id, major: t.major, status: p.result || `exit ${p.status}`, at: [p.file]});
		}
		if (!t.parse)
			failures.push({symbol: 'parse', target: t.id, major: t.major, status: 'no parse results', at: []});
	}

	// Output
	const cell = c => {
		switch (c.status) {
		case 'present': return 'ok';
		case 'internal': return '-';
		case 'n/a': return 'n/a';
		case 'absent': return 'absent';
		case 'missing': return c.unguarded ? 'MISSING' : 'missing (guarded)';
		case 'too few arguments': return c.unguarded ? `ARGS<${c.jsArity}` : `args<${c.jsArity} (guarded)`;
		case 'too many arguments': return c.unguarded ? `ARGS>${c.jsArity}` : `args>${c.jsArity} (guarded)`;
		default: return c.status;
		}
	};
	const compat = {
		generated: new Date().toISOString(),
		targets: targets.map(t => ({id: t.id, gnome: t.major, versions: t.versions, shellJs: t.shellJs,
			namespaces: {...t.probe.shell?.namespaces, ...t.probe.prefs?.namespaces}, infra: t.infra,
			partialGir: analysis.nameIndex[t.id]?.partialNs ?? []})),
		modules: analysis.modules,
		symbols: shown.map(s => ({
			symbol: s.key, kind: s.kind, via: s.via, byNameOnly: s.byNameOnly || undefined,
			signatureChanged: s.signatureChanged,
			perTarget: Object.fromEntries(targets.map(t => [t.id, {cell: cell(s.perTarget[t.id]), ...s.perTarget[t.id]}])),
			uses: s.uses.map(u => ({at: `${u.file}:${u.line}:${u.col}`, code: u.code, proc: u.proc, guard: u.guard ?? undefined,
				inTry: u.inTry || undefined, argc: Object.values(u.perTarget).find(r => r.argc !== undefined)?.argc})),
		})),
		languageFeatures: featureRows,
		globals: globalRows,
		featureMatrix,
		dynamicImports: analysis.dynamicImports,
		processSeparation: analysis.violations,
		parse: Object.fromEntries(targets.map(t => [t.id, t.parse])),
		failures,
		notes,
	};
	fs.writeFileSync(opts.out, JSON.stringify(compat, null, 1));

	// Readable summary
	const header = targets.map(t => `${t.id} (${t.major})`);
	const lines = [];
	lines.push('# GNOME API compatibility', '');
	lines.push(`Generated ${compat.generated} by tools/check.sh compat. Full data: compat.json.`, '');
	lines.push('## Images', '');
	lines.push('| Image | GNOME | gnome-shell | gjs | mutter | GTK 4 | libadwaita | shell JS read from |');
	lines.push('| --- | --- | --- | --- | --- | --- | --- | --- |');
	for (const t of targets) {
		const v = t.versions;
		const pick = (...keys) => keys.map(k => v[k]).find(Boolean) ?? '?';
		lines.push(`| ${t.id} | ${t.major} | ${pick('gnome-shell')} | ${pick('gjs')} | ${pick('pkg:mutter', 'pkg:mutter-common')} | ` +
			`${pick('pkg:gtk4', 'pkg:libgtk-4-1')} | ${pick('pkg:libadwaita', 'pkg:libadwaita-1-0')} | ${path.basename(path.dirname(t.shellJs))} |`);
	}
	lines.push('');
	lines.push(`## Result: ${failures.length === 0 ? 'PASS' : `FAIL, ${failures.length} problem(s)`}`, '');
	for (const f of failures) {
		lines.push(`- ${f.target}${f.major ? ` (GNOME ${f.major})` : ''}: \`${f.symbol}\` ${f.status}` +
			`${f.detail ? ` [${f.detail}]` : ''}${f.at?.length ? ` at ${f.at.join(', ')}` : ''}` +
			`${f.inTry?.length ? `; inside try at ${f.inTry.join(', ')}, which hides the error but not the breakage` : ''}`);
	}
	lines.push('');
	if (notes.length) {
		lines.push('## Guarded (not failures)', '');
		for (const n of notes)
			lines.push(`- ${n.target}: \`${n.symbol}\` ${n.status}, guarded at ${n.guardedAt.join(', ')}`);
		lines.push('');
	}
	const changed = shown.filter(s => s.signatureChanged);
	if (changed.length) {
		lines.push('## gnome-shell JS signatures that differ between versions', '');
		for (const s of changed) {
			lines.push(`- \`${s.key}\`: ${targets.map(t => `${t.id} (${(s.signatureChanged[t.id] ?? ['?']).join(', ')})`).join('; ')}`);
		}
		lines.push('');
	}
	const privates = shown.filter(s => /[#.]_[A-Za-z]/.test(s.key) && !s.key.includes('#_init'));
	if (privates.length) {
		lines.push('## Private gnome-shell members the extension reads', '');
		lines.push('Present today, but gnome-shell may rename them without notice.', '');
		for (const s of privates)
			lines.push(`- \`${s.key}\` at ${s.uses.map(u => `${u.file}:${u.line}`).join(', ')}`);
		lines.push('');
	}
	lines.push('## Symbol x version', '');
	lines.push(`| Symbol | ${header.join(' | ')} | Used at |`);
	lines.push(`| --- | ${header.map(() => '---').join(' | ')} | --- |`);
	const sorted = [...shown].sort((a, b) => a.key.localeCompare(b.key));
	for (const s of sorted) {
		const at = s.uses.map(u => `${u.file}:${u.line}${u.guard ? ` (${u.guard})` : ''}`);
		lines.push(`| \`${s.key.replace(/\|/g, '\\|')}\`${s.byNameOnly ? ' (by name)' : ''} | ` +
			`${targets.map(t => cell(s.perTarget[t.id])).join(' | ')} | ${at.slice(0, 4).join(', ')}${at.length > 4 ? `, +${at.length - 4}` : ''} |`);
	}
	lines.push('');
	lines.push('## JS language features and globals the extension uses', '');
	lines.push(`| Feature | ${header.join(' | ')} | Used at |`);
	lines.push(`| --- | ${header.map(() => '---').join(' | ')} | --- |`);
	for (const r of featureRows)
		lines.push(`| ${r.id} | ${targets.map(t => r.perTarget[t.id]).join(' | ')} | ${r.at.join(', ')} |`);
	for (const r of globalRows)
		lines.push(`| global \`${r.name}\` | ${targets.map(t => r.perTarget[t.id]).join(' | ')} | ${r.at.slice(0, 3).join(', ')} |`);
	lines.push('');
	lines.push(`Regular expressions compiled under each gjs: ${analysis.regexes.length}. ` +
		`Dynamic imports: ${analysis.dynamicImports.map(d => `${d.ns} in ${d.file}`).join(', ') || 'none'}.`, '');
	fs.writeFileSync(opts.summary, `${lines.join('\n')}\n`);

	// Console: the table and the verdict, for compat.log
	const colW = Math.max(...sorted.map(s => s.key.length), 20);
	const cw = 14;
	console.log(`${'symbol'.padEnd(colW)}  ${header.map(h => h.padEnd(cw)).join(' ')}`);
	for (const s of sorted)
		console.log(`${s.key.padEnd(colW)}  ${targets.map(t => cell(s.perTarget[t.id]).padEnd(cw)).join(' ')}`);
	console.log('');
	for (const n of notes)
		console.log(`guarded: ${n.target}: ${n.symbol} ${n.status} at ${n.guardedAt.join(', ')}`);
	for (const f of failures) {
		console.log(`FAIL: ${f.target}: ${f.symbol} ${f.status}${f.detail ? ` [${f.detail}]` : ''}` +
			`${f.at?.length ? ` at ${f.at.join(', ')}` : ''}`);
	}
	const bySym = new Map();
	for (const f of failures) {
		if (!bySym.has(f.symbol))
			bySym.set(f.symbol, []);
		bySym.get(f.symbol).push(f.major ?? f.target);
	}
	const parts = [...bySym].map(([s, where]) => `${s} (${[...new Set(where)].join(', ')})`);
	const total = shown.length;
	if (failures.length === 0) {
		console.log(`summary: ${total} symbols present in all ${targets.length} images ` +
			`(GNOME ${[...new Set(targets.map(t => t.major))].join(', ')}), ${notes.length} guarded gaps`);
		return 0;
	}
	console.log(`summary: ${bySym.size} of ${total} symbols missing or mis-called unguarded: ${parts.join('; ')}`);
	return 1;
}

// Section: main

const [cmd, ...rest] = process.argv.slice(2);
const opts = parseArgs(rest);
try {
	if (cmd === 'analyze')
		process.exit(analyze(opts));
	else if (cmd === 'report')
		process.exit(report(opts));
	console.error('usage: resolve.mjs analyze|report ...');
	process.exit(2);
} catch (e) {
	console.error(`resolve: ${e.stack}`);
	console.log(`summary: resolve.mjs ${cmd} crashed: ${e.message}`);
	process.exit(1);
}
