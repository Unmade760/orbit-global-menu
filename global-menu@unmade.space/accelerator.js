// Parsing and labelling of GTK-style accelerator strings ("<Ctrl><Shift>N").
// Shared by the shell process (keySynth.js) and the preferences process
// (shortcutStore.js, shortcutCapture.js), so it imports no library at all.
// The keyvals are numeric literals, the same values as Clutter.KEY_*, which
// are X11 keysyms.

// Modifier token (lowercased, without <>) to left-modifier keyval. <Meta> is
// deliberately not accepted: it means different things on different setups.
const MODIFIER_KEYVALS = {
	'ctrl': 0xffe3,    // Control_L
	'control': 0xffe3,
	'primary': 0xffe3,
	'shift': 0xffe1,   // Shift_L
	'alt': 0xffe9,     // Alt_L
	'super': 0xffeb,   // Super_L
};

const NAMED_KEYVALS = {
	'f1': 0xffbe, 'f2': 0xffbf, 'f3': 0xffc0, 'f4': 0xffc1,
	'f5': 0xffc2, 'f6': 0xffc3, 'f7': 0xffc4, 'f8': 0xffc5,
	'f9': 0xffc6, 'f10': 0xffc7, 'f11': 0xffc8, 'f12': 0xffc9,
	'return': 0xff0d,
	'escape': 0xff1b,
	'tab': 0xff09,
	'backspace': 0xff08,
	'delete': 0xffff,
	'home': 0xff50,
	'end': 0xff57,
	'page_up': 0xff55,
	'page_down': 0xff56,
	'left': 0xff51,
	'up': 0xff52,
	'right': 0xff53,
	'down': 0xff54,
	'space': 0x020,
	'exclam': 0x021,
	'quotedbl': 0x022,
	'numbersign': 0x023,
	'dollar': 0x024,
	'percent': 0x025,
	'ampersand': 0x026,
	'apostrophe': 0x027,
	'parenleft': 0x028,
	'parenright': 0x029,
	'asterisk': 0x02a,
	'plus': 0x02b,
	'comma': 0x02c,
	'minus': 0x02d,
	'period': 0x02e,
	'slash': 0x02f,
	'colon': 0x03a,
	'semicolon': 0x03b,
	'less': 0x03c,
	'equal': 0x03d,
	'greater': 0x03e,
	'question': 0x03f,
	'at': 0x040,
	'bracketleft': 0x05b,
	'backslash': 0x05c,
	'bracketright': 0x05d,
	'asciicircum': 0x05e,
	'underscore': 0x05f,
	'grave': 0x060,
	'braceleft': 0x07b,
	'bar': 0x07c,
	'braceright': 0x07d,
	'asciitilde': 0x07e,
	'print': 0xff61,
	'insert': 0xff63,
	'menu': 0xff67,
	'kp_0': 0xffb0, 'kp_1': 0xffb1, 'kp_2': 0xffb2, 'kp_3': 0xffb3,
	'kp_4': 0xffb4, 'kp_5': 0xffb5, 'kp_6': 0xffb6, 'kp_7': 0xffb7,
	'kp_8': 0xffb8, 'kp_9': 0xffb9,
	'kp_decimal': 0xffae, 'kp_add': 0xffab, 'kp_subtract': 0xffad,
	'kp_multiply': 0xffaa, 'kp_divide': 0xffaf, 'kp_enter': 0xff8d,
};

/**
 * "<Ctrl><Shift>N" to [{modifiers: [keyval, ...], keyval}], or null if the
 * string is not a valid accelerator.
 *
 * Space-separated chords are a sequence: "<Ctrl>x s" is Emacs' C-x s and
 * ": w Return" is Vim's :w, for apps whose menus live behind a prefix key
 * rather than a single accelerator. The usual one-chord accelerator is just a
 * one-element sequence.
 *
 * @param {string} accel
 * @returns {object[]|null}
 */
export function parseAccelerator(accel) {
	if (typeof accel !== 'string' || accel === '')
		return null;

	const chords = [];
	for (const part of accel.split(' ')) {
		const chord = parseChord(part);
		if (!chord)
			return null;
		chords.push(chord);
	}
	return chords;
}

function parseChord(accel) {
	if (accel === '')
		return null;

	const modifiers = [];
	let rest = accel;
	let match;
	while ((match = rest.match(/^<([^<>]+)>/))) {
		const keyval = MODIFIER_KEYVALS[match[1].toLowerCase()];
		if (keyval === undefined)
			return null;
		if (!modifiers.includes(keyval))
			modifiers.push(keyval);
		rest = rest.slice(match[0].length);
	}

	let keyval;
	if (rest.length === 1) {
		// Shift is expressed by the <Shift> modifier, never by an uppercase
		// keyval, so a printable character is always lowercased here
		const code = rest.toLowerCase().charCodeAt(0);
		if (code < 0x21 || code > 0x7e)
			return null;
		keyval = code;
	} else {
		keyval = NAMED_KEYVALS[rest.toLowerCase()];
		if (keyval === undefined)
			return null;
	}
	return {modifiers, keyval};
}

// Key labels as GTK 4 writes them in English. Printable ASCII keys are their
// own character, upper case for letters; these are the exceptions. GTK 4
// puts a thin space (U+2009) after "KP".
const KEY_LABELS = new Map(Object.entries({
	'return': 'Return', 'escape': 'Escape', 'tab': 'Tab', 'backspace': 'Backspace',
	'delete': 'Delete', 'home': 'Home', 'end': 'End', 'page_up': 'Page Up',
	'page_down': 'Page Down', 'left': 'Left', 'up': 'Up', 'right': 'Right',
	'down': 'Down', 'space': 'Space', 'backslash': 'Backslash', 'print': 'Print',
	'insert': 'Insert', 'menu': 'Menu', 'kp_enter': 'Enter (keypad)',
	'kp_decimal': 'KP\u2009.', 'kp_add': 'KP\u2009+', 'kp_subtract': 'KP\u2009-',
	'kp_multiply': 'KP\u2009*', 'kp_divide': 'KP\u2009/',
}).map(([name, label]) => [NAMED_KEYVALS[name], label]));
for (let i = 1; i <= 12; i++)
	KEY_LABELS.set(NAMED_KEYVALS[`f${i}`], `F${i}`);
for (let i = 0; i <= 9; i++)
	KEY_LABELS.set(NAMED_KEYVALS[`kp_${i}`], `KP\u2009${i}`);

// GTK 4 writes modifiers in this order whatever order the string had.
const MODIFIER_LABELS = [
	[MODIFIER_KEYVALS['shift'], 'Shift'],
	[MODIFIER_KEYVALS['ctrl'], 'Ctrl'],
	[MODIFIER_KEYVALS['alt'], 'Alt'],
	[MODIFIER_KEYVALS['super'], 'Super'],
];

function chordLabel({modifiers, keyval}) {
	const parts = MODIFIER_LABELS.filter(([mod]) => modifiers.includes(mod)).map(([, label]) => label);
	parts.push(KEY_LABELS.get(keyval) ?? String.fromCharCode(keyval).toUpperCase());
	return parts.join('+');
}

/**
 * "<Ctrl><Shift>S" to "Shift+Ctrl+S", the way GTK 4 labels an accelerator
 * (Design Language, Type rule 4). A chord sequence is joined with a space
 * ("Ctrl+K Ctrl+S"). Returns null if the string is not a valid accelerator.
 * The words come from the tables above, so the result does not depend on the
 * locale.
 *
 * @param {string} accel
 * @returns {string|null}
 */
export function acceleratorLabel(accel) {
	const chords = parseAccelerator(accel);
	return chords ? chords.map(chordLabel).join(' ') : null;
}
