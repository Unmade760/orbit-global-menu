
// meta is not accepted because it means different things
// on different setups
const MODIFIER_KEYVALS = {
	'ctrl': 0xffe3,
	'control': 0xffe3,
	'primary': 0xffe3,
	'shift': 0xffe1,
	'alt': 0xffe9,
	'super': 0xffeb,
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
		// shift is written as a modifier so printable keyvals
		// are lowercased
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

// gtk 4 puts a thin space after kp in key labels
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

export function acceleratorLabel(accel) {
	const chords = parseAccelerator(accel);
	return chords ? chords.map(chordLabel).join(' ') : null;
}
