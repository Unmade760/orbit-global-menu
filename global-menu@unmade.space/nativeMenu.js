
import GLib from 'gi://GLib';

import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {MenuBarButton} from './menuBarButton.js';
import {addBarButton} from './panelBar.js';

// cjk labels append the mnemonic in brackets so strip it
function stripMnemonic(label) {
	return (label ?? '')
		.replace(/\s*\([_&][^_&)]\)(…|\.\.\.)?$/u, '$1')
		.replace(/_(.?)/gu, '$1');
}

const barNodes = nodes => nodes.filter(n => !n.separator && !n.appMenu && stripMnemonic(n.label));

export function hasBarMenus(nodes) {
	return barNodes(nodes).length > 0;
}

function toOrnament(toggleType, toggleState) {
	if (toggleType === 'checkmark')
		return toggleState ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE;
	if (toggleType === 'radio')
		return toggleState ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE;
	return undefined;
}

export class NativeMenu {
	constructor(proxy, uuid, onAppMenu) {
		this._proxy = proxy;
		this._uuid = uuid;
		this._onAppMenu = onAppMenu;
		this._appMenuSource = null;
		this._buttons = [];
		this._shownJson = null;
		this._pendingNodes = null;
		this._rebuildIdleId = 0;
	}

	hasMenus() {
		return this._buttons.length > 0;
	}

	setItems(nodes) {
		const json = JSON.stringify(nodes);
		if (json === this._shownJson) {
			if (this._pendingNodes)
				this._applyState(nodes);
			this._pendingNodes = null;
			return;
		}
		// rebuilding would destroy a menu the user is navigating
		// so wait until all menus are closed
		if (this._anyOpen()) {
			this._pendingNodes = nodes;
			this._applyState(nodes);
			return;
		}
		this._rebuild(nodes, json);
	}

	closeAllMenus() {
		this._buttons.forEach(btn => btn.menu.close());
	}

	appMenuSource() {
		return this._appMenuSource;
	}

	clear() {
		this._shownJson = null;
		this._pendingNodes = null;
		this._buttons.forEach(btn => btn.destroy());
		this._buttons = [];
		this._setAppMenu(null);
	}

	destroy() {
		if (this._rebuildIdleId) {
			GLib.source_remove(this._rebuildIdleId);
			this._rebuildIdleId = 0;
		}
		this.clear();
	}

	_anyOpen() {
		return this._buttons.some(btn => btn.menu.isOpen);
	}

	_rebuild(nodes, json = JSON.stringify(nodes)) {
		this._pendingNodes = null;
		const topLevel = barNodes(nodes);
		while (this._buttons.length > topLevel.length)
			this._buttons.pop().destroy();
		topLevel.forEach((node, index) => {
			let btn = this._buttons[index];
			if (btn) {
				btn.setLabel(stripMnemonic(node.label));
			} else {
				btn = new MenuBarButton(stripMnemonic(node.label), {
					onOpen: () => this._proxy.RequestMenuTree(),
					onClose: () => this._scheduleRebuildIfPending(),
				});
				addBarButton(`${this._uuid}-native-${index}`, btn, 1 + index);
				this._buttons.push(btn);
			}
			btn.setItems(() => this._toSpecs(node.children ?? []));
		});
		const appNode = nodes.find(n => n.appMenu);
		this._setAppMenu(appNode ? () => this._toSpecs(appNode.children ?? []) : null);
		this._shownJson = json;
	}

	_setAppMenu(source) {
		if (source === this._appMenuSource)
			return;
		this._appMenuSource = source;
		this._onAppMenu?.(source);
	}

	_toSpecs(nodes) {
		const specs = [];
		for (const node of nodes) {
			if (node.separator) {
				specs.push({separator: true});
				continue;
			}
			const spec = {
				label: stripMnemonic(node.label),
				enabled: node.enabled !== false,
				key: node.key,
				accel: node.accel,
				ornament: toOrnament(node.toggleType, node.toggleState),
			};
			if (node.children)
				spec.children = this._toSpecs(node.children);
			else if (node.key)
				spec.onActivate = () => this._proxy.ActivateMenuItem(node.key);
			specs.push(spec);
		}
		return specs;
	}

	_scheduleRebuildIfPending() {
		if (!this._pendingNodes || this._rebuildIdleId)
			return;
		// deferred because this runs from the close signal
		// and the button must not die mid emission
		this._rebuildIdleId = GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
			this._rebuildIdleId = 0;
			if (this._pendingNodes && !this._anyOpen())
				this._rebuild(this._pendingNodes);
			return GLib.SOURCE_REMOVE;
		});
	}

	_applyState(nodes) {
		const stateByKey = new Map();
		const collect = list => {
			for (const node of list) {
				if (node.separator)
					continue;
				if (node.key) {
					stateByKey.set(node.key, {
						enabled: node.enabled !== false,
						ornament: toOrnament(node.toggleType, node.toggleState),
					});
				}
				if (node.children)
					collect(node.children);
			}
		};
		collect(nodes);

		for (const btn of this._buttons)
			this._applyToMenu(btn.itemsMenu, stateByKey);
	}

	_applyToMenu(menu, stateByKey) {
		for (const item of menu._getMenuItems()) {
			const state = item._globalMenuKey ? stateByKey.get(item._globalMenuKey) : null;
			if (state) {
				item.setSensitive(state.enabled);
				if (state.ornament !== undefined && item.setOrnament)
					item.setOrnament(state.ornament);
			}
			if (item.menu)
				this._applyToMenu(item.menu, stateByKey);
		}
	}
}
