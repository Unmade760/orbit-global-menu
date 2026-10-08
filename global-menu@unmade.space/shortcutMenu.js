// Renders a curated shortcut mapping from shortcutStore.js. Same
// presentation as the other two menu sources, but activating an item
// synthesizes the application's real keyboard shortcut through keySynth.js.

import {MenuBarButton} from './menuBarButton.js';
import {addBarButton} from './panelBar.js';
import {sendShortcutAfterMenu} from './keySynth.js';

export class ShortcutMenu {
	constructor(uuid) {
		this._uuid = uuid;
		this._buttons = [];
		this._mapping = null;
	}

	/**
	 * Build buttons for the mapping, or clear with null.
	 *
	 * @param {object|null} mapping
	 */
	setMapping(mapping) {
		// The daemon re-sends empty trees periodically. Rebuilding for the
		// mapping already shown would close a menu the user is navigating.
		if (mapping === this._mapping && (mapping === null || this._buttons.length > 0))
			return;
		this._mapping = mapping;
		const menus = mapping?.menus ?? [];
		// Relabel the buttons already in the panel and add or remove only the
		// difference, for the reason given in NativeMenu._rebuild()
		while (this._buttons.length > menus.length)
			this._buttons.pop().destroy();
		menus.forEach((menu, index) => {
			let btn = this._buttons[index];
			if (btn) {
				btn.setLabel(menu.label);
			} else {
				btn = new MenuBarButton(menu.label);
				addBarButton(`${this._uuid}-shortcut-${index}`, btn, 1 + index);
				this._buttons.push(btn);
			}
			btn.setItems(this._toSpecs(menu.items));
		});
	}

	hasMenus() {
		return this._buttons.length > 0;
	}

	closeAllMenus() {
		this._buttons.forEach(btn => btn.menu.close());
	}

	clear() {
		this._mapping = null;
		this._buttons.forEach(btn => btn.destroy());
		this._buttons = [];
	}

	destroy() {
		this.clear();
	}

	_toSpecs(items) {
		return items.map(item => {
			if (item.separator)
				return {separator: true};
			if (item.items)
				return {label: item.label, children: this._toSpecs(item.items)};
			if (item.shortcut)
				return {label: item.label, accel: item.shortcut, onActivate: () => sendShortcutAfterMenu(item.shortcut)};
			// Placeholder: the mapping records the item but no usable
			// accelerator for it, so show it greyed out rather than lie
			return {label: item.label, enabled: false};
		});
	}
}
