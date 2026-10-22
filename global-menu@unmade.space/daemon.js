
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const BUS_NAME = 'space.unmade.GlobalMenu';
const PROGRAM = 'global-menu';

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

		// sigterm not force_exit because the daemon traps it
		// to stop its children
		this._proc?.send_signal(15);
		this._proc = null;
	}

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
			if (this._proc !== proc)
				return;
			try {
				p.wait_finish(res);
			} catch {
				return;
			}
			this._proc = null;
			// the name vanishing may come first
			// while this process is still winding down
			if (!this._nameOwned)
				this._respawn();
		});
	}

	// a stock session path has no local bin
	// where pip install user puts the program
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
