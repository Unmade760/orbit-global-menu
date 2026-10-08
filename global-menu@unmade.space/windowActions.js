// Window management actions for the focused window, mirroring gnome-shell's
// own window menu. Used by the fallback Window menu and by the daemon, which
// asks for the same list over D-Bus.

import GLib from 'gi://GLib';
import Meta from 'gi://Meta';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// A move or resize grab cannot start while the shell still holds the input
// grab from the menu that requested it.
const GRAB_DELAY_MS = 100;

// Pending grab timeouts. WindowActions instances are created ad hoc and never
// held onto, so the module owns their sources and extension.js clears them on
// disable.
const pendingGrabs = new Set();

/** Called from the extension's disable(). */
export function cancelPendingActions() {
	for (const id of pendingGrabs)
		GLib.source_remove(id);
	pendingGrabs.clear();
}

export class WindowActions {
	constructor() {
		this._win = global.display.get_focus_window();
		this.actions = [];
	}

	getActions() {
		const win = this._win;
		if (!win)
			return this.actions;
		const type = win.get_window_type();

		if (win.can_minimize())
			this.actions.push('Minimize');

		if (win.can_maximize())
			this.actions.push(this._isMaximized() ? 'Unmaximize' : 'Maximize');

		if (win.allows_move())
			this.actions.push('Move');

		if (win.allows_resize())
			this.actions.push('Resize');

		if (!(this._isMaximized() ||
			type === Meta.WindowType.DOCK ||
			type === Meta.WindowType.DESKTOP ||
			type === Meta.WindowType.SPLASHSCREEN))
			this.actions.push(`Always on Top${win.is_above() ? ' ✓' : ''}`);

		if (Main.sessionMode.hasWorkspaces &&
			(!Meta.prefs_get_workspaces_only_on_primary() || win.is_on_primary_monitor())) {
			const isSticky = win.is_on_all_workspaces();

			if (!win.is_always_on_all_workspaces())
				this.actions.push(`Always on Visible Workspace${isSticky ? ' ✓' : ''}`);

			if (!isSticky) {
				const workspace = win.get_workspace();
				const neighbours = {
					Left: Meta.MotionDirection.LEFT,
					Right: Meta.MotionDirection.RIGHT,
					Up: Meta.MotionDirection.UP,
					Down: Meta.MotionDirection.DOWN,
				};
				for (const [name, dir] of Object.entries(neighbours)) {
					if (workspace !== workspace.get_neighbor(dir))
						this.actions.push(`Move to Workspace ${name}`);
				}
			}
		}

		const display = global.display;
		const monitorIndex = win.get_monitor();
		if (display.get_n_monitors() > 1 && monitorIndex >= 0) {
			const neighbours = {
				Up: Meta.DisplayDirection.UP,
				Down: Meta.DisplayDirection.DOWN,
				Left: Meta.DisplayDirection.LEFT,
				Right: Meta.DisplayDirection.RIGHT,
			};
			for (const [name, dir] of Object.entries(neighbours)) {
				if (display.get_monitor_neighbor_index(monitorIndex, dir) !== -1)
					this.actions.push(`Move to Monitor ${name}`);
			}
		}

		if (win.can_close())
			this.actions.push('Close');

		return this.actions;
	}

	// mutter 49 dropped the direction argument and added is_maximized()
	_isMaximized() {
		const win = this._win;
		if (typeof win.is_maximized === 'function')
			return win.is_maximized();
		return win.get_maximized() === Meta.MaximizeFlags.BOTH;
	}

	// The argument count gjs enforces: 48 needs the directions, 49 and later take none
	_maximizeArgs(fn) {
		return fn.length === 1 ? [Meta.MaximizeFlags.BOTH] : [];
	}

	doAction(action) {
		// State-carrying labels arrive with their tick still attached
		if (action.endsWith(' ✓'))
			action = action.slice(0, -2);

		const win = this._win;
		if (!win)
			return;

		switch (action) {
		case 'Minimize':
			win.minimize();
			break;
		case 'Unmaximize':
			win.unmaximize(...this._maximizeArgs(win.unmaximize));
			break;
		case 'Maximize':
			win.maximize(...this._maximizeArgs(win.maximize));
			break;
		case 'Move':
			this._beginGrab(Meta.GrabOp.KEYBOARD_MOVING);
			break;
		case 'Resize':
			this._beginGrab(Meta.GrabOp.KEYBOARD_RESIZING_UNKNOWN);
			break;
		case 'Always on Top':
			if (win.is_above())
				win.unmake_above();
			else
				win.make_above();
			break;
		case 'Always on Visible Workspace':
			if (win.is_on_all_workspaces())
				win.unstick();
			else
				win.stick();
			break;
		case 'Move to Workspace Left':
			this._moveToWorkspace(Meta.MotionDirection.LEFT);
			break;
		case 'Move to Workspace Right':
			this._moveToWorkspace(Meta.MotionDirection.RIGHT);
			break;
		case 'Move to Workspace Up':
			this._moveToWorkspace(Meta.MotionDirection.UP);
			break;
		case 'Move to Workspace Down':
			this._moveToWorkspace(Meta.MotionDirection.DOWN);
			break;
		case 'Move to Monitor Up':
			this._moveToMonitor(Meta.DisplayDirection.UP);
			break;
		case 'Move to Monitor Down':
			this._moveToMonitor(Meta.DisplayDirection.DOWN);
			break;
		case 'Move to Monitor Left':
			this._moveToMonitor(Meta.DisplayDirection.LEFT);
			break;
		case 'Move to Monitor Right':
			this._moveToMonitor(Meta.DisplayDirection.RIGHT);
			break;
		case 'Close':
			win.delete(global.get_current_time());
			break;
		}
	}

	_beginGrab(op) {
		const win = this._win;
		const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, GRAB_DELAY_MS, () => {
			pendingGrabs.delete(id);
			const backend = global.stage.get_context().get_backend();
			const sprite = backend.get_pointer_sprite(global.stage);
			win.begin_grab_op(op, sprite, global.get_current_time(), null);
			return GLib.SOURCE_REMOVE;
		});
		pendingGrabs.add(id);
	}

	_moveToWorkspace(dir) {
		const workspace = this._win.get_workspace();
		this._win.change_workspace(workspace.get_neighbor(dir));
	}

	_moveToMonitor(dir) {
		const monitorIndex = this._win.get_monitor();
		const target = global.display.get_monitor_neighbor_index(monitorIndex, dir);
		if (target !== -1)
			this._win.move_to_monitor(target);
	}
}
