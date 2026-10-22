// Lifecycle for the global-menu daemon, which reads an app's exported menu off
// the bus and returns a JSON tree.
// It ships separately and is only launched, never bundled. enable() is the only
// starter; if another process owns the name, nothing is spawned.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const BUS_NAME = 'space.unmade.GlobalMenu';
const PROGRAM = 'global-menu';

// A daemon that crashes MAX_STARTS times within START_WINDOW_US is not
// started again. Each restart waits twice as long as the one before.
const MAX_STARTS = 3;
const START_WINDOW_US = 60 * 1000 * 1000;
const FIRST_RETRY_MS = 1000;

export class DaemonManager {
	constructor() {
		this._proc = null;
		this._cancellable = null;
		this._nameWatchId = 0;
		this._retryId = 0;
		this._nameOwned = false;
		this._starts = [];
		this._warned = false;
	}

	start() {
		if (this._nameWatchId)
			return;

		this._cancellable = new Gio.Cancellable();
		// Fires vanished() at once when nobody owns the name, covering both the
		// first start and a later crash.
		this._nameWatchId = Gio.bus_watch_name(
			Gio.BusType.SESSION,
			BUS_NAME,
			Gio.BusNameWatcherFlags.NONE,
			() => {
				this._nameOwned = true;
			},
			() => {
				this._nameOwned = false;
				this._respawn();
			}
		);
	}

	destroy() {
		if (this._nameWatchId) {
			Gio.bus_unwatch_name(this._nameWatchId);
			this._nameWatchId = 0;
		}
		if (this._retryId) {
			GLib.source_remove(this._retryId);
			this._retryId = 0;
		}
		this._cancellable?.cancel();
		this._cancellable = null;
		this._nameOwned = false;
		this._starts = [];

		// SIGTERM, not force_exit: the daemon traps it to take its children
		// down. Only our own process; a daemon the user started is left alone.
		this._proc?.send_signal(15);
		this._proc = null;
	}

	// Start the daemon unless one is running, one is already queued, or it
	// has crashed too often to be worth another try
	_respawn() {
		if (this._proc || this._retryId)
			return;

		const now = GLib.get_monotonic_time();
		this._starts = this._starts.filter(t => now - t < START_WINDOW_US);
		if (this._starts.length >= MAX_STARTS) {
			this._warnOnce(`${PROGRAM} keeps exiting; giving up. ` +
				'Run it in a terminal to see why.');
			return;
		}

		if (this._starts.length === 0) {
			this._launch();
			return;
		}
		const delay = FIRST_RETRY_MS * 2 ** (this._starts.length - 1);
		this._retryId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delay, () => {
			this._retryId = 0;
			if (!this._proc && !this._nameOwned)
				this._launch();
			return GLib.SOURCE_REMOVE;
		});
	}

	_launch() {
		const path = this._findProgram();
		if (!path) {
			this._warnOnce(`${PROGRAM} is not on PATH or in ~/.local/bin. ` +
				'Menus exported by applications need it; install the global-menu package.');
			return;
		}

		this._starts.push(GLib.get_monotonic_time());
		let proc;
		try {
			proc = Gio.Subprocess.new([path], Gio.SubprocessFlags.NONE);
		} catch (e) {
			console.warn(`[global-menu] could not start ${PROGRAM}: ${e.message}`);
			return;
		}

		this._proc = proc;
		proc.wait_async(this._cancellable, (p, res) => {
			// Superseded by destroy() or by a later start
			if (this._proc !== proc)
				return;
			try {
				p.wait_finish(res);
			} catch {
				// Cancelled on disable
				return;
			}
			this._proc = null;
			// The name vanishing may have come first, while this process was
			// still winding down
			if (!this._nameOwned)
				this._respawn();
		});
	}

	// A stock session PATH has no ~/.local/bin, which is where
	// `pip install --user` puts the program
	_findProgram() {
		const onPath = GLib.find_program_in_path(PROGRAM);
		if (onPath)
			return onPath;
		const local = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', PROGRAM]);
		return GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE) ? local : null;
	}

	_warnOnce(message) {
		if (this._warned)
			return;
		this._warned = true;
		console.warn(`[global-menu] ${message}`);
	}
}
