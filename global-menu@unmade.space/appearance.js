// Styling for the menu bar and its popups: translucency, rounding, button
// spacing, font size, and optional blur behind the popups.
//
// Every MenuBarButton registers itself here from menuBarButton.js, so the
// three menu sources get styled without knowing that this module exists.
// Nothing here touches shared shell UI: styling is applied as inline styles
// and global-menu-* CSS classes on our own actors. The one exception is the
// workspace indicator, which we hide on request and restore on disable.
//
// Blur goes through Blur My Shell, which publishes itself as
// global.blur_my_shell for exactly this. We take one of its native dynamic
// gaussian blur effects per popup (a BACKGROUND-mode Shell.BlurEffect,
// re-blurred every frame) from its EffectsManager. Without Blur My Shell
// there is no blur and everything else still works.

import Clutter from 'gi://Clutter';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const BMS_UUID = 'blur-my-shell@aunetx';

const APPEARANCE_KEYS = [
	'blur-popups',
	'popup-blur-sigma',
	'popup-blur-brightness',
	'popup-opacity',
	'popup-corner-radius',
	'hide-popup-arrow',
	'hide-app-name',
	'button-spacing',
	'menu-font-size',
	'bold-app-name',
	'hide-workspace-indicator',
	'shortcut-labels',
	'shortcut-hold-key',
];

// Keys that can reveal shortcut labels, with the modifier bit that says the
// key is already down when a menu opens
const HOLD_KEYS = {
	alt: {keyvals: [Clutter.KEY_Alt_L, Clutter.KEY_Alt_R], mask: Clutter.ModifierType.MOD1_MASK},
	ctrl: {keyvals: [Clutter.KEY_Control_L, Clutter.KEY_Control_R], mask: Clutter.ModifierType.CONTROL_MASK},
	shift: {keyvals: [Clutter.KEY_Shift_L, Clutter.KEY_Shift_R], mask: Clutter.ModifierType.SHIFT_MASK},
	super: {keyvals: [Clutter.KEY_Super_L, Clutter.KEY_Super_R], mask: Clutter.ModifierType.MOD4_MASK},
};

// Buttons register even while no manager exists, so a manager created later
// can still style them.
const buttons = new Set();
let manager = null;

/**
 * Called by MenuBarButton._init. Unregisters itself when the actor dies.
 *
 * @param {MenuBarButton} btn - the button to style
 */
export function registerButton(btn) {
	buttons.add(btn);
	btn.connect('destroy', () => buttons.delete(btn));
	// The open popup has key focus, so the hold key arrives here
	btn.menu.actor.connect('key-press-event', (_actor, event) => {
		manager?.onHoldKey(btn, event.get_key_symbol(), true);
		return Clutter.EVENT_PROPAGATE;
	});
	btn.menu.actor.connect('key-release-event', (_actor, event) => {
		manager?.onHoldKey(btn, event.get_key_symbol(), false);
		return Clutter.EVENT_PROPAGATE;
	});
	manager?.applyToButton(btn);
}

/**
 * Called by MenuBarButton when its menu opens. The popup's theme background
 * color can only be read once the actor is on stage, so translucency is
 * reapplied here. The blur effect is created here too rather than at button
 * creation: buttons are rebuilt on every menu-tree change, and taking an
 * effect out of Blur My Shell's pool for each short-lived button leaks
 * handler connections inside it.
 *
 * @param {MenuBarButton} btn - the button whose menu opened
 */
export function onMenuOpened(btn) {
	manager?.applyShortcutLabels(btn);
	manager?.applyPopupBackground(btn);
	manager?.alignPopupText(btn);
	manager?.applyBlur(btn);
}

/**
 * GNOME's Activities button doubles as the workspace pill at the far left of
 * the panel.
 *
 * Hiding it is not a one-off. Panel._updatePanel() re-adds every indicator
 * and shows its container again, and it runs after extensions are enabled at
 * login, so a lone hide() in enable() is undone before the panel is ever
 * painted. That is why the pill used to reappear until the extension was
 * toggled by hand. Tracking the container's visibility, and the session mode
 * that rebuilds the panel, makes the hide stick from the first enable.
 */
class WorkspaceIndicator {
	constructor(settings) {
		this._settings = settings;
		this._indicator = null;
		this._visibleId = 0;
		this._destroyId = 0;
		this._hiddenByUs = false;
		this._sessionModeId = Main.sessionMode.connect('updated', () => this.sync());
		this.sync();
	}

	sync() {
		this._track(Main.panel.statusArea.activities ?? null);
		const container = this._indicator?.container;
		if (!container)
			return;

		if (this._settings.get_boolean('hide-workspace-indicator')) {
			container.hide();
			this._hiddenByUs = true;
		} else if (this._hiddenByUs) {
			container.show();
			this._hiddenByUs = false;
		}
	}

	destroy() {
		Main.sessionMode.disconnect(this._sessionModeId);
		this._sessionModeId = 0;

		const container = this._indicator?.container;
		const restore = this._hiddenByUs;
		// Disconnect before showing. show() emits notify::visible, and the
		// handler below would read a setting that is still true and hide the
		// pill straight back again.
		this._untrack();
		if (restore)
			container?.show();

		this._hiddenByUs = false;
		this._settings = null;
	}

	_track(indicator) {
		if (indicator === this._indicator)
			return;
		this._untrack();
		this._indicator = indicator;
		if (!indicator)
			return;

		const container = indicator.container;
		// A panel rebuild shows the container again without any signal of
		// its own to hang off, so re-hide whenever it comes back.
		this._visibleId = container.connect('notify::visible', () => {
			if (container.visible && this._settings.get_boolean('hide-workspace-indicator'))
				container.hide();
		});
		this._destroyId = container.connect('destroy', () => this._untrack());
	}

	_untrack() {
		const container = this._indicator?.container;
		if (container) {
			if (this._visibleId)
				container.disconnect(this._visibleId);
			if (this._destroyId)
				container.disconnect(this._destroyId);
		}
		this._visibleId = 0;
		this._destroyId = 0;
		this._indicator = null;
	}
}

export class AppearanceManager {
	constructor(settings) {
		this._settings = settings;
		this._settingsIds = APPEARANCE_KEYS.map(key =>
			settings.connect(`changed::${key}`, () => this.applyAll()));

		// Blur My Shell does not detach effects it made for foreign actors,
		// so follow its enabled state and detach them ourselves.
		this._extStateId = Main.extensionManager.connect(
			'extension-state-changed', (_mgr, extension) => {
				if (extension.uuid === BMS_UUID)
					this.applyAll();
			});

		this._workspaceIndicator = new WorkspaceIndicator(settings);
		this.applyAll();
	}

	applyAll() {
		for (const btn of buttons)
			this.applyToButton(btn);
		this._workspaceIndicator?.sync();
	}

	applyToButton(btn) {
		const s = this._settings;

		// panelMenu reads -natural/-minimum-hpadding off the button's theme
		// node and the label inherits the font, so both are set inline here.
		// The shell theme bolds every panel button, which would drown the
		// app name it is meant to distinguish, so weight is forced to normal
		// and only the app-name button gets bold back.
		const spacing = s.get_int('button-spacing');
		const fontSize = s.get_int('menu-font-size');
		const bold = btn._globalMenuAppName && s.get_boolean('bold-app-name');
		let style = `-natural-hpadding: ${spacing}px; ` +
			`-minimum-hpadding: ${Math.min(spacing, 6)}px; ` +
			`font-weight: ${bold ? 'bold' : 'normal'};`;
		if (fontSize > 0)
			style += ` font-size: ${fontSize}pt;`;
		btn.set_style(style);

		if (s.get_boolean('hide-popup-arrow'))
			btn.menu.actor.add_style_class_name('global-menu-no-arrow');
		else
			btn.menu.actor.remove_style_class_name('global-menu-no-arrow');

		// The button is hidden through its container, not itself: panelBar.js
		// anchors the run of menus on the app-name button's slot, and
		// fallbackMenu.js shows and hides the button for its own reasons.
		if (btn._globalMenuAppName) {
			const hide = s.get_boolean('hide-app-name');
			const wasHidden = btn._globalMenuHidden;
			btn._globalMenuHidden = hide;
			if (hide || wasHidden)
				btn.container.visible = !hide;
			this._trackContainer(btn);
		}

		this.applyShortcutLabels(btn);
		this._trackDirection(btn);
		this._alignSource(btn);
		this.applyPopupBackground(btn);
		this.applyBlur(btn);
	}

	/**
	 * Show, hide or hold back the popup's shortcut labels. Runs when the
	 * menu opens, after its items are built.
	 *
	 * @param {MenuBarButton} btn - the button whose menu opened
	 * @param {boolean} [held] - whether the hold key is down; read from the
	 *   pointer's modifier state when not given
	 */
	applyShortcutLabels(btn, held) {
		const mode = this._settings.get_string('shortcut-labels');
		const hold = HOLD_KEYS[this._settings.get_string('shortcut-hold-key')] ?? HOLD_KEYS.alt;
		if (held === undefined)
			held = (global.get_pointer()[2] & hold.mask) !== 0;

		const show = mode !== 'never';
		for (const label of accelLabels(btn.menu.box))
			label.visible = show;
		if (mode === 'hold' && !held)
			btn.menu.actor.add_style_class_name('global-menu-accels-held');
		else
			btn.menu.actor.remove_style_class_name('global-menu-accels-held');
	}

	onHoldKey(btn, keyval, pressed) {
		if (!btn.menu.isOpen || this._settings.get_string('shortcut-labels') !== 'hold')
			return;
		const hold = HOLD_KEYS[this._settings.get_string('shortcut-hold-key')] ?? HOLD_KEYS.alt;
		if (hold.keyvals.includes(keyval))
			this.applyShortcutLabels(btn, pressed);
	}

	applyPopupBackground(btn) {
		const s = this._settings;
		const radius = s.get_int('popup-corner-radius');
		const opacity = s.get_int('popup-opacity');
		const fontSize = s.get_int('menu-font-size');

		let style = `border-radius: ${radius}px;`;
		if (fontSize > 0)
			style += ` font-size: ${fontSize}pt;`;
		const base = this._popupBaseColor(btn);
		if (base !== null) {
			const alpha = (opacity / 100).toFixed(2);
			style += ` background-color: rgba(${base.red}, ${base.green}, ${base.blue}, ${alpha});`;
		}
		btn.menu.box.set_style(style);
		this._styleWells(btn, radius);
	}

	/**
	 * Slide the popup left (right in RTL) until the first item's text starts
	 * where the title's text does. The popup's own inset is the box padding
	 * plus the item padding and the title's is the bar button's padding. The
	 * popup's is the larger, so the popup has to start before the title.
	 *
	 * BoxPointer places the popup at its source point minus half of
	 * 4 * -arrow-border-radius + -arrow-border-width + -arrow-base, and that
	 * radius only feeds the pointer outline, which the theme leaves
	 * transparent. Setting it on our own popup actor is the one lever that
	 * moves a popup past the edge of its source: translation is reset by the
	 * open animation. A theme that gives the pointer a base wider than twice
	 * the shift makes BoxPointer pull the popup back, which leaves it flush
	 * with the title's edge.
	 *
	 * @param {MenuBarButton} btn - the button whose menu is opening
	 */
	alignPopupText(btn) {
		const shift = this._textShift(btn);
		const actor = btn.menu.actor;
		if (shift === null)
			return;
		// This style replaces the one the shell set when the menu opened,
		// so it has to carry the shell's height cap too. Without the cap a
		// long menu runs off the screen with no scrollbar.
		let style = this._maxHeightStyle(btn);
		if (shift > 0) {
			const node = actor.get_theme_node();
			const fixed = node.get_length('-arrow-border-width') + node.get_length('-arrow-base');
			const radius = Math.max(0, (2 * shift - fixed) / 4) / this._scale();
			style += ` -arrow-border-radius: ${radius.toFixed(2)}px;`;
		}
		actor.set_style(style);
	}

	// What PanelMenu.Button caps the popup at each time it opens: the work
	// area, less the popup's margins, in CSS pixels. The cap is taken from
	// the monitor the button is on, where the shell uses the primary one.
	_maxHeightStyle(btn) {
		const layout = Main.layoutManager;
		let monitor = layout.findIndexForActor(btn);
		if (monitor < 0)
			monitor = layout.primaryIndex;
		const workArea = layout.getWorkAreaForMonitor(monitor);
		const actor = btn.menu.actor;
		const margins = actor.margin_top + actor.margin_bottom;
		return `max-height: ${Math.round((workArea.height - margins) / this._scale())}px;`;
	}

	applyBlur(btn) {
		const s = this._settings;
		const effects = this._bmsEffects();
		const wanted = s.get_boolean('blur-popups') && effects !== null;

		if (!wanted) {
			this._removeBlur(btn);
			return;
		}

		const radius = 2 * s.get_int('popup-blur-sigma');
		const brightness = s.get_double('popup-blur-brightness');
		const cornerRadius = s.get_int('popup-corner-radius');

		if (btn._globalMenuBlur) {
			btn._globalMenuBlur.unscaled_radius = radius;
			btn._globalMenuBlur.brightness = brightness;
			if (btn._globalMenuBlur.corner_radius !== undefined)
				btn._globalMenuBlur.corner_radius = cornerRadius;
			return;
		}

		// Deferred to the first open, see onMenuOpened
		if (!btn.menu.isOpen)
			return;

		btn._globalMenuBlur = effects.new_native_dynamic_gaussian_blur_effect({
			unscaled_radius: radius,
			brightness,
			corner_radius: cornerRadius,
		});
		btn.menu.box.add_effect(btn._globalMenuBlur);

		// BoxPointer always forces offscreen redirect, which makes a
		// BACKGROUND blur sample the popup's own empty offscreen buffer
		// instead of the screen: translucent, never blurred. Relaxing it to
		// the stock actor default only flattens the popup during its
		// open/close fade, where the blur cannot be seen anyway.
		btn.menu.actor.set_offscreen_redirect(Clutter.OffscreenRedirect.AUTOMATIC_FOR_OPACITY);
	}

	destroy() {
		for (const id of this._settingsIds)
			this._settings.disconnect(id);
		this._settingsIds = [];
		Main.extensionManager.disconnect(this._extStateId);
		this._extStateId = 0;
		this._workspaceIndicator.destroy();
		this._workspaceIndicator = null;
		for (const btn of buttons)
			this._resetButton(btn);
		this._settings = null;
		manager = null;
	}

	_scale() {
		return St.ThemeContext.get_for_stage(global.stage).scale_factor;
	}

	_isRtl(btn) {
		return btn.get_text_direction() === Clutter.TextDirection.RTL;
	}

	// BoxPointer mirrors the arrow alignment in RTL but not the source
	// alignment, so the popup would hang off the title's centre instead of
	// its right edge.
	_alignSource(btn) {
		btn.menu.setSourceAlignment(this._isRtl(btn) ? 1.0 : 0.0);
	}

	_trackDirection(btn) {
		if (btn._globalMenuDirectionId)
			return;
		btn._globalMenuDirectionId = btn.connect('notify::text-direction',
			() => this._alignSource(btn));
	}

	// Panel.addToStatusArea() shows the container once the button is in the
	// panel, so a button created while hide-app-name is on has to be hidden
	// again then.
	_trackContainer(btn) {
		if (btn._globalMenuVisibleId)
			return;
		btn._globalMenuVisibleId = btn.container.connect('notify::visible', () => {
			if (btn._globalMenuHidden && btn.container.visible)
				btn.container.visible = false;
		});
	}

	// Pixels between where the first item's text would start and where the
	// title's text starts, or null while the popup is off stage. Theme node
	// lengths are in scaled pixels throughout.
	_textShift(btn) {
		const box = btn.menu.box;
		const item = btn.itemsMenu.firstMenuItem;
		if (!item || !box.get_stage())
			return null;

		const side = this._isRtl(btn) ? St.Side.RIGHT : St.Side.LEFT;
		const inset = node => node.get_padding(side) + node.get_border_width(side);
		const bar = btn.get_theme_node();
		// The source point sits inside the button's border and padding, the
		// text a button padding further in
		const title = bar.get_length('-natural-hpadding') - inset(bar);
		return inset(box.get_theme_node()) + inset(item.get_theme_node()) - title;
	}

	// The submenu well sits one popup padding and border inside the popup,
	// so its bottom corners are concentric with the popup's.
	_styleWells(btn, radius) {
		const box = btn.menu.box;
		if (!box.get_stage())
			return;
		const node = box.get_theme_node();
		const inner = (node.get_padding(St.Side.TOP) + node.get_border_width(St.Side.TOP)) / this._scale();
		const well = Math.max(0, radius - inner);
		this._eachWell(btn.itemsMenu, `border-radius: 0 0 ${well}px ${well}px;`);
	}

	_eachWell(menu, style) {
		for (const child of menu.box.get_children()) {
			if (!child.menu)
				continue;
			child.menu.actor.set_style(style);
			this._eachWell(child.menu, style);
		}
	}

	_bmsEffects() {
		return global.blur_my_shell?._effects_manager ?? null;
	}

	// The popup's theme background color, captured once per button before our
	// translucent inline style overrides it. An off-stage theme node yields a
	// bogus color, so return null and let the next menu open retry.
	_popupBaseColor(btn) {
		if (btn._globalMenuBaseBg !== undefined)
			return btn._globalMenuBaseBg;
		if (!btn.menu.box.get_stage())
			return null;
		try {
			const color = btn.menu.box.get_theme_node().get_background_color();
			btn._globalMenuBaseBg = {red: color.red, green: color.green, blue: color.blue};
		} catch {
			return null;
		}
		return btn._globalMenuBaseBg;
	}

	_removeBlur(btn) {
		if (btn.menu?.actor)
			btn.menu.actor.set_offscreen_redirect(Clutter.OffscreenRedirect.ALWAYS);
		if (!btn._globalMenuBlur)
			return;
		const effects = this._bmsEffects();
		if (effects)
			effects.remove(btn._globalMenuBlur);
		else
			btn.menu.box.remove_effect(btn._globalMenuBlur);
		btn._globalMenuBlur = null;
	}

	_resetButton(btn) {
		btn.set_style(null);
		btn.menu.actor.remove_style_class_name('global-menu-no-arrow');
		btn.menu.actor.remove_style_class_name('global-menu-accels-held');
		btn.menu.actor.set_style(null);
		btn.menu.box.set_style(null);
		this._eachWell(btn.itemsMenu, null);
		if (btn._globalMenuDirectionId) {
			btn.disconnect(btn._globalMenuDirectionId);
			btn._globalMenuDirectionId = 0;
		}
		if (btn._globalMenuVisibleId) {
			btn.container.disconnect(btn._globalMenuVisibleId);
			btn._globalMenuVisibleId = 0;
		}
		if (btn._globalMenuHidden) {
			btn.container.visible = true;
			btn._globalMenuHidden = false;
		}
		this._removeBlur(btn);
	}
}

/**
 * Every shortcut label menuBarButton.js put under `actor`, submenus included.
 *
 * @param {Clutter.Actor} actor - a popup's box
 * @yields {St.Label}
 */
function* accelLabels(actor) {
	for (const child of actor.get_children()) {
		if (child.has_style_class_name?.('global-menu-accel'))
			yield child;
		else
			yield* accelLabels(child);
	}
}

/**
 * @param {Gio.Settings} settings - the extension's settings
 * @returns {AppearanceManager} the manager now styling every registered button
 */
export function createManager(settings) {
	manager = new AppearanceManager(settings);
	return manager;
}
