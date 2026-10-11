// A top-level menu-bar button in the panel with a shell PopupMenu, shared by
// all three menu sources so they render and behave identically.
//
// Menus are described by item specs:
//   {separator: true}
// | {label, enabled?, ornament?, key?, accel?, onActivate?, children?: spec[]}
// accel is a GTK accelerator string ("<Primary>s"), shown as the shortcut.
// setItems() also accepts a function returning specs, re-evaluated every time
// the menu opens. The dynamic Window menu uses that.

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {ensureActorVisibleInScrollView} from 'resource:///org/gnome/shell/misc/animationUtils.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {acceleratorLabel} from './accelerator.js';
import * as Appearance from './appearance.js';

// The item's own text colour at 55 %, as GTK 4 draws accelerators in its
// popover menus. St has no CSS opacity, so it is the actor's.
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

		// The popup box is a plain BoxLayout, so past the shell's max-height
		// cap its items are clipped with no way to reach them. The items
		// live in a section inside a scroll view instead, the way a
		// PopupSubMenu holds its own. The section's actor is the scroll
		// view so the menu treats the pair as one child.
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
			// Building now would pay for a menu that may never open, since
			// it is rebuilt on open anyway. But PopupMenu.open() refuses to
			// open an empty menu, and it refuses before emitting
			// open-state-changed where the real items get built, so keep a
			// placeholder in it. The rebuild replaces it in the same frame,
			// before anything is painted.
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
