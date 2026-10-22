// A top-level menu-bar button with a shell PopupMenu, shared by all three menu
// sources.
// Item spec: {separator: true} | {label, enabled?, ornament?, key?, accel?,
// onActivate?, children?}; setItems() also takes a function returning specs.

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {ensureActorVisibleInScrollView} from 'resource:///org/gnome/shell/misc/animationUtils.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {acceleratorLabel} from './accelerator.js';
import * as Appearance from './appearance.js';

// The item's text colour at 55 %, as GTK 4 draws accelerators. St has no CSS
// opacity, so it is set on the actor.
const ACCEL_OPACITY = 140;

function addAccelLabel(item, text) {
	const label = new St.Label({
		text,
		style_class: 'global-menu-accel',
		x_expand: true,
		x_align: Clutter.ActorAlign.END,
		y_align: Clutter.ActorAlign.CENTER,
	});
	item.add_child(label);
	// St gives an item that is not reactive the theme's :insensitive style,
	// which greys its label and shortcut together
	const sync = () => {
		label.opacity = item.reactive ? ACCEL_OPACITY : 255;
	};
	item.connect('notify::reactive', sync);
	sync();
}

export const MenuBarButton = GObject.registerClass(
class MenuBarButton extends PanelMenu.Button {
	_init(label, params = {}) {
		super._init(0.0, label);

		this._titleLabel = new St.Label({
			text: label,
			y_align: Clutter.ActorAlign.CENTER,
			style_class: 'panel-button-label',
		});
		this.add_child(this._titleLabel);

		// Marks our buttons for panelBar.js and, among them, the app-name
		// button for appearance.js
		this._globalMenuButton = true;
		this._globalMenuAppName = !!params.appName;
		this.menu.actor.add_style_class_name('global-menu-popup');

		// The popup box clips items past the shell's max-height cap, so items
		// live in a section inside a scroll view, as PopupSubMenu does.
		this._itemsScroll = new St.ScrollView({
			hscrollbar_policy: St.PolicyType.NEVER,
			vscrollbar_policy: St.PolicyType.AUTOMATIC,
			overlay_scrollbars: true,
			clip_to_allocation: true,
		});
		this.itemsMenu = new PopupMenu.PopupMenuSection();
		this._itemsScroll.add_child(this.itemsMenu.box);
		this._itemsScroll._delegate = this.itemsMenu;
		this.itemsMenu.actor = this._itemsScroll;
		this.menu.addMenuItem(this.itemsMenu);

		this._itemsSource = null;
		this.menu.connect('open-state-changed', (menu, open) => {
			if (open) {
				if (typeof this._itemsSource === 'function')
					this._rebuild(this._itemsSource());
				Appearance.onMenuOpened(this);
				params.onOpen?.(this);
			} else {
				params.onClose?.(this);
			}
		});

		Appearance.registerButton(this);
	}

	setLabel(text) {
		this._titleLabel.text = text;
		this.accessible_name = text;
	}

	setItems(items) {
		this._itemsSource = items;
		if (typeof items === 'function') {
			// Building now would pay for a menu that may never open.
			// PopupMenu.open() refuses an empty menu before
			// open-state-changed fires, so keep a placeholder; the rebuild
			// replaces it before paint.
			this.itemsMenu.removeAll();
			this.itemsMenu.addMenuItem(new PopupMenu.PopupMenuItem(''));
		} else {
			this._rebuild(items);
		}
	}

	_rebuild(specs) {
		this.itemsMenu.removeAll();
		this._buildInto(specs, this.itemsMenu);
	}

	_buildInto(specs, parentMenu) {
		for (const spec of specs) {
			if (spec.separator) {
				parentMenu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
			} else if (spec.children) {
				const subMenu = new PopupMenu.PopupSubMenuMenuItem(spec.label);
				if (spec.enabled === false)
					subMenu.setSensitive(false);
				if (spec.key)
					subMenu._globalMenuKey = spec.key;
				this._buildInto(spec.children, subMenu.menu);
				subMenu.connect('key-focus-in', () => this._scrollTo(subMenu));
				// An inline submenu grows downward, possibly past the
				// visible part of the scroll view
				subMenu.menu.actor.connect('notify::height', () => {
					if (subMenu.menu.isOpen)
						this._scrollTo(subMenu.menu.actor);
				});
				parentMenu.addMenuItem(subMenu);
			} else {
				const item = new PopupMenu.PopupMenuItem(spec.label);
				const accel = acceleratorLabel(spec.accel);
				if (accel)
					addAccelLabel(item, accel);
				if (spec.enabled === false)
					item.setSensitive(false);
				if (spec.ornament !== undefined)
					item.setOrnament(spec.ornament);
				if (spec.key)
					item._globalMenuKey = spec.key;
				if (spec.onActivate)
					item.connect('activate', spec.onActivate);
				// Arrow keys move the focus; bring the item into view
				item.connect('key-focus-in', () => this._scrollTo(item));
				parentMenu.addMenuItem(item);
			}
		}
	}

	_scrollTo(actor) {
		if (actor.get_stage())
			ensureActorVisibleInScrollView(this._itemsScroll, actor);
	}
});
