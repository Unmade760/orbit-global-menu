#!/usr/bin/env python3
"""Run every app in tests/apps/apps.json, one at a time, each in its own
private session, and write one JSON per app plus a summary table.

    tools/apps-runner.py                     all apps
    tools/apps-runner.py --only gedit,kate   a subset
    tools/apps-runner.py --summary-only      rebuild the table from the JSON files

Per app the runner
    makes a private XDG_RUNTIME_DIR and HOME under /tmp, so nothing reaches
      the user's display, session bus, profiles or single-instance locks
    writes a session bus config that listens on unix:path=<runtime>/bus
      (xdg-dbus-proxy, which flatpak uses, cannot follow an abstract socket)
    starts tools/apps-session.py under setsid dbus-run-session
    kills the whole process group on a hard timeout, then sweeps any process
      whose environment still names the runtime directory, then removes it

Output: /home/ravi/fildem-work/apps/<id>.json, SUMMARY.md and summary.json in
the same directory, logs in /home/ravi/fildem-work/logs/apps/<id>/.
GM_APPS_JSON, GM_APPS_SESSION_SCRIPT, GM_APPS_PROBE_BUDGET and GM_APPS_OUT
override the app list, the session script, the probe time allowance and the
output directory; tests/apps/negative-test.sh uses them.
Exit status: 0 when every selected app produced a result file with a status
other than timeout, harness-error or missing; 1 otherwise.
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS_JSON = os.environ.get('GM_APPS_JSON', os.path.join(REPO, 'tests', 'apps', 'apps.json'))
OUT_DIR = os.environ.get('GM_APPS_OUT', '/home/ravi/fildem-work/apps')
LOG_DIR = os.path.join(os.environ.get('GM_LOG_DIR', '/home/ravi/fildem-work/logs'), 'apps')
SESSION = os.environ.get('GM_APPS_SESSION_SCRIPT', os.path.join(REPO, 'tools', 'apps-session.py'))
BAD_STATUS = {'timeout', 'harness-error', 'missing', 'skipped'}
DEFAULT_TIMEOUT = 40
PROBE_BUDGET = int(os.environ.get('GM_APPS_PROBE_BUDGET', '90'))


def log(msg):
	print(msg, flush=True)


def mem_available_mb():
	with open('/proc/meminfo') as handle:
		for line in handle:
			if line.startswith('MemAvailable:'):
				return int(line.split()[1]) // 1024
	return 0


def session_env(runtime):
	keep = ('PATH', 'LANG', 'LC_ALL', 'USER', 'LOGNAME', 'SHELL', 'JAVA_HOME')
	env = {k: v for k, v in os.environ.items() if k in keep}
	env['XDG_RUNTIME_DIR'] = runtime
	env['TMPDIR'] = runtime
	env['FLATPAK_USER_DIR'] = os.environ.get('FLATPAK_USER_DIR', os.path.expanduser('~/.local/share/flatpak'))
	env['GM_APPS_SESSION'] = runtime
	return env


def bus_config(runtime):
	"""The distro's session.conf with a listen address on a path."""
	with open('/usr/share/dbus-1/session.conf') as handle:
		text = handle.read()
	text = re.sub(r'<listen>.*?</listen>', '<listen>unix:path=%s/bus</listen>' % runtime, text)
	path = os.path.join(runtime, 'session.conf')
	with open(path, 'w') as handle:
		handle.write(text)
	return path


def kill_group(pgid):
	for sig, wait in ((signal.SIGTERM, 2.0), (signal.SIGKILL, 0.5)):
		try:
			os.killpg(pgid, sig)
		except ProcessLookupError:
			return
		except PermissionError:
			return
		time.sleep(wait)


def sweep(runtime):
	"""Kill processes of this uid whose environment names the runtime dir."""
	marker = ('GM_APPS_SESSION=' + runtime).encode()
	killed = []
	me = os.getpid()
	for entry in os.listdir('/proc'):
		if not entry.isdigit() or int(entry) == me:
			continue
		try:
			with open('/proc/%s/environ' % entry, 'rb') as handle:
				env = handle.read()
		except OSError:
			continue
		if marker in env.split(b'\0'):
			try:
				os.kill(int(entry), signal.SIGKILL)
				killed.append(int(entry))
			except OSError:
				pass
	return killed


def cleanup_runtime(runtime):
	for mount in (os.path.join(runtime, 'doc'), os.path.join(runtime, 'gvfs')):
		if os.path.ismount(mount) or os.path.exists(mount):
			subprocess.run(['fusermount3', '-uz', mount], capture_output=True, check=False)
	shutil.rmtree(runtime, ignore_errors=True)


def launcher_present(app):
	if app.get('packaging') == 'flatpak':
		res = subprocess.run(['flatpak', 'info', app['flatpak_id']], capture_output=True, check=False)
		return res.returncode == 0
	for word in app['launch']:
		if word in ('env', 'flatpak', 'run') or word.startswith('-') or '=' in word:
			continue
		return shutil.which(word) is not None or os.path.exists(word)
	return False


def run_app(app, index, total):
	app_id = app['id']
	out = os.path.join(OUT_DIR, app_id + '.json')
	logdir = os.path.join(LOG_DIR, app_id)
	shutil.rmtree(logdir, ignore_errors=True)
	os.makedirs(logdir, exist_ok=True)
	if os.path.exists(out):
		os.remove(out)
	started = time.time()
	log('[%d/%d] %s (%s, %s) ...' % (index, total, app_id, app.get('toolkit'), app.get('packaging')))

	if not launcher_present(app):
		write_stub(app, out, 'missing', 'launcher not found: %s' % app['launch'][0])
		return 'missing'
	need = 2500 if app.get('heavy') else 900
	waited = 0
	while mem_available_mb() < need and waited < 90:
		time.sleep(5)
		waited += 5
	if mem_available_mb() < 500:
		write_stub(app, out, 'skipped', 'MemAvailable %d MB, under 500 MB' % mem_available_mb())
		return 'skipped'

	runtime = tempfile.mkdtemp(prefix='gm-apps.')
	os.chmod(runtime, 0o700)
	app_json = os.path.join(runtime, 'app.json')
	with open(app_json, 'w') as handle:
		json.dump(app, handle)
	conf = bus_config(runtime)
	argv = ['dbus-run-session', '--config-file=' + conf, '--', sys.executable, SESSION,
		'--app-json', app_json, '--out', out, '--logdir', logdir]
	hard = app.get('timeout', DEFAULT_TIMEOUT) + app.get('settle', 5) + PROBE_BUDGET
	proc = subprocess.Popen(argv, env=session_env(runtime), cwd=REPO, start_new_session=True,
		stdout=open(os.path.join(logdir, 'session.log'), 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
	pgid = proc.pid
	timed_out = False
	try:
		proc.wait(hard)
	except subprocess.TimeoutExpired:
		timed_out = True
	kill_group(pgid)
	swept = sweep(runtime)
	cleanup_runtime(runtime)

	if timed_out or not os.path.exists(out):
		reason = 'hard timeout after %ds' % hard if timed_out else 'session ended without a result file (exit %s)' % proc.returncode
		write_stub(app, out, 'timeout' if timed_out else 'harness-error', reason)
		status = 'timeout' if timed_out else 'harness-error'
	else:
		try:
			with open(out) as handle:
				status = json.load(handle).get('status', 'harness-error')
		except (OSError, ValueError):
			status = 'harness-error'
	log('    -> %s in %.0fs%s' % (status, time.time() - started,
		(', swept %d stray processes' % len(swept)) if swept else ''))
	return status


def write_stub(app, out, status, reason):
	os.makedirs(os.path.dirname(out), exist_ok=True)
	data = {'id': app['id'], 'name': app.get('name'), 'toolkit': app.get('toolkit'), 'packaging': app.get('packaging'),
		'mode': app.get('mode', 'wayland'), 'launch': app.get('launch'), 'status': status, 'error': reason,
		'summary': {'export': 'none', 'bus_names': [], 'top_level': [], 'items': 0, 'submenus': 0, 'with_accel': 0,
			'disabled': 0, 'check': 0, 'radio': 0, 'actions': 0, 'shortcuts_window': False,
			'registrar_registrations': 0, 'x11_gtk_menubar_property': False, 'x11_kde_appmenu_property': False}}
	with open(out, 'w') as handle:
		json.dump(data, handle, indent=1)


def load_apps():
	with open(APPS_JSON) as handle:
		return json.load(handle)['apps']


def summarize(apps):
	rows = []
	for app in apps:
		path = os.path.join(OUT_DIR, app['id'] + '.json')
		try:
			with open(path) as handle:
				data = json.load(handle)
		except (OSError, ValueError):
			data = {'status': 'missing', 'summary': {}}
		rows.append((app, data))
	lines = ['| id | toolkit | pkg | mode | status | window | export | top-level menus | items | accels | check/radio | disabled | shortcuts window |',
		'| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
	counts = {}
	for app, data in rows:
		s = data.get('summary') or {}
		counts[s.get('export', 'none')] = counts.get(s.get('export', 'none'), 0) + 1
		top = ', '.join((t or '').replace('_', '').replace('&', '') for t in (s.get('top_level') or [])[:8])
		if len(s.get('top_level') or []) > 8:
			top += ', ...'
		lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s/%s | %s | %s |' % (
			app['id'], app.get('toolkit'), app.get('packaging'), data.get('mode', app.get('mode', 'wayland')),
			data.get('status'), 'yes' if data.get('window_seen') else 'no', s.get('export', 'none'), top or '-',
			s.get('items', 0), s.get('with_accel', 0), s.get('check', 0), s.get('radio', 0), s.get('disabled', 0),
			'yes' if s.get('shortcuts_window') else 'no'))
	exporting = sum(1 for _a, d in rows if (d.get('summary') or {}).get('items', 0) > 0)
	statuses = {}
	for _a, d in rows:
		statuses[d.get('status')] = statuses.get(d.get('status'), 0) + 1
	lines.append('')
	lines.append('%d apps, %d export a menu with at least one item (%.0f%%). Status: %s. Export kinds: %s.' % (
		len(rows), exporting, 100.0 * exporting / max(1, len(rows)),
		', '.join('%s %d' % kv for kv in sorted(statuses.items())),
		', '.join('%s %d' % kv for kv in sorted(counts.items()))))
	text = '\n'.join(lines) + '\n'
	os.makedirs(OUT_DIR, exist_ok=True)
	with open(os.path.join(OUT_DIR, 'SUMMARY.md'), 'w') as handle:
		handle.write(text)
	with open(os.path.join(OUT_DIR, 'summary.json'), 'w') as handle:
		json.dump({'apps': len(rows), 'exporting': exporting, 'statuses': statuses, 'export_kinds': counts,
			'rows': [{'id': a['id'], 'status': d.get('status'), 'summary': d.get('summary')} for a, d in rows]}, handle, indent=1)
	bad = [a['id'] for a, d in rows if d.get('status') in BAD_STATUS]
	return text, bad, rows


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--only', help='comma-separated app ids')
	parser.add_argument('--summary-only', action='store_true')
	args = parser.parse_args()
	apps = load_apps()
	if args.only:
		want = set(args.only.split(','))
		unknown = want - {a['id'] for a in apps}
		if unknown:
			log('unknown app ids: %s' % ', '.join(sorted(unknown)))
			return 2
		apps = [a for a in apps if a['id'] in want]
	os.makedirs(OUT_DIR, exist_ok=True)
	if not args.summary_only:
		for i, app in enumerate(apps, 1):
			run_app(app, i, len(apps))
	text, bad, _rows = summarize(apps)
	print(text)
	if bad:
		log('summary: not run cleanly: %s' % ', '.join(bad))
		return 1
	return 0


if __name__ == '__main__':
	sys.exit(main())
