#!/usr/bin/env python3
"""Scans the logs of one distros container run and writes its verdict.

Run by tools/distros/in-container.sh as the last step, with the JSON pieces
the earlier steps wrote in --dir. Writes --dir/result.json:

    image, gnome_shell, gjs, python     versions read inside the image
    deps                                the daemon's imports, present or not
    install                             each install method tried, its exit
                                        status and last lines, the one used
    daemon                              the standalone start
    shell                               per pass: flags, state per cycle,
                                        daemon per cycle, memory, and what
                                        the log scan found
    problems                            why the image fails, empty on pass

The baseline pass runs the same session without ever enabling the
extension. A log line is blamed on the extension or the daemon when its message or the
stack trace under it names global-menu@unmade.space, a [global-menu...]
module tag, the globalmenu package, or comes from the daemon's own process.
Errors and warnings that name neither and appear after the first enable are
listed as unattributed; the ones whose text the baseline log never shows
fail the image as new_with_extension.
"""

import argparse
import json
import os
import re
import sys

UUID = 'global-menu@unmade.space'

HEAD = re.compile(
	r'JS ERROR|JS WARNING|-CRITICAL \*\*|-WARNING \*\*|-ERROR \*\*'
	r'|^Traceback \(most recent call last\)'
	r'|Extension \S+ had error|^\S*Extension ' + re.escape(UUID)
	+ r'|^(ERROR|WARNING|CRITICAL):[\w.]+:')
PROC = re.compile(r'^\((?P<proc>[^:()]+):\d+\):')
FRAME = re.compile(r'^\s*(\S*@\S+:\d+(:\d+)?|Stack trace:|File "|\s{2,}\S)')
NEW_LINE = re.compile(r'^(\(|libmutter-|GNOME Shell-|\*\* |dbus-daemon\[|Gjs-|\S+-Message|\S+-WARNING|\S+-CRITICAL)')
DAEMON_PROCS = ('global-menu', 'python3')


def blocks(lines):
	"""Yields (index, level, text, proc) for each error or warning block."""
	i = 0
	n = len(lines)
	while i < n:
		line = lines[i]
		if not HEAD.search(line):
			i += 1
			continue
		start = i
		body = [line]
		python_tb = line.startswith('Traceback')
		i += 1
		while i < n:
			nxt = lines[i]
			if HEAD.search(nxt) and not python_tb:
				break
			if python_tb:
				body.append(nxt)
				i += 1
				# The exception line closes a Python traceback
				if nxt and not nxt[0].isspace() and not nxt.startswith(('File', 'Traceback')):
					break
				continue
			if not nxt.strip() or FRAME.match(nxt):
				body.append(nxt)
				i += 1
				continue
			if NEW_LINE.match(nxt):
				break
			# Continuation of a multi-line message
			body.append(nxt)
			i += 1
		text = '\n'.join(body).rstrip()
		if 'JS ERROR' in line or 'CRITICAL' in line or '-ERROR **' in line \
				or line.startswith(('Traceback', 'ERROR:')) or 'had error' in line \
				or line.lstrip().startswith('Extension '):
			level = 'error'
		else:
			level = 'warning'
		m = PROC.match(line)
		proc = m.group('proc') if m else ''
		yield start, level, text, proc


def blamed(text, proc):
	if UUID in text or '[global-menu' in text or 'globalmenu' in text:
		return True
	if proc.startswith(DAEMON_PROCS):
		return True
	# dbus-python's logger: only the daemon uses dbus-python in the session
	return bool(re.match(r'^(ERROR|WARNING|CRITICAL):dbus', text))


def normalize(text):
	first = text.splitlines()[0] if text else ''
	first = re.sub(r'0x[0-9a-fA-F]+', '0xN', first)
	return re.sub(r'\d+', 'N', first)[:200]


def scan(path, offset, baseline=None):
	"""baseline: normalized first lines of every block in the baseline log."""
	out = {'blamed': [], 'unattributed_after_enable': [], 'new_with_extension': [],
		'tag_info': 0, 'lines': 0}
	if not os.path.exists(path):
		out['missing'] = True
		return out
	with open(path, 'rb') as f:
		raw = f.read()
	lines = raw.decode('utf-8', 'replace').splitlines()
	out['lines'] = len(lines)
	offset_line = raw[:offset].count(b'\n') if offset else 0
	seen = set()
	for start, level, text, proc in blocks(lines):
		if blamed(text, proc):
			out['blamed'].append({'line': start + 1, 'level': level, 'text': text[:2000]})
		elif start >= offset_line:
			key = normalize(text)
			if key not in seen:
				seen.add(key)
				item = {'line': start + 1, 'level': level, 'text': text[:600]}
				out['unattributed_after_enable'].append(item)
				if baseline is not None and key not in baseline:
					out['new_with_extension'].append(item)
	for line in lines:
		if '[global-menu' in line and '-Message' in line:
			out['tag_info'] += 1
	return out


def read_lines(path):
	try:
		with open(path, 'rb') as f:
			return f.read().decode('utf-8', 'replace').splitlines()
	except OSError:
		return []


def load(path):
	try:
		with open(path) as f:
			return json.load(f)
	except (OSError, ValueError) as e:
		return {'error': 'no result (%s)' % e}


def judge_pass(label, shell, problems, want_cycles):
	cycles = shell.get('cycles', [])
	if shell.get('error'):
		problems.append('%s: %s' % (label, shell['error']))
	if not shell.get('started'):
		return
	bad_state = [c['cycle'] for c in cycles
		if c.get('enabled_state') != 'ACTIVE' or c.get('disabled_state') != 'INACTIVE']
	if len(cycles) < want_cycles or bad_state:
		first = cycles[bad_state[0] - 1] if bad_state else {}
		problems.append('%s: %d of %d cycles clean%s' % (label,
			len(cycles) - len(bad_state), want_cycles,
			'; cycle %d ended %s/%s%s' % (first['cycle'], first.get('enabled_state'),
				first.get('disabled_state'),
				(' (%s)' % first['error'][:120]) if first.get('error') else '')
			if first else ''))
	app = shell.get('app')
	if app is not None and not app.get('focused'):
		problems.append('%s: harness: the GTK test window never took focus %s' % (label, app))
	active = [c for c in cycles if c.get('enabled_state') == 'ACTIVE']
	if app and app.get('focused') and active:
		for key, what in (
				('window_switched_on_enable',
					'extension sent no WindowSwitched for the focused window on enable'),
				('window_switched_on_focus',
					'extension sent no WindowSwitched when focus returned to the window')):
			silent = [c['cycle'] for c in active if key in c and not c[key]]
			if silent:
				problems.append('%s: %s in %d of %d cycles' % (label, what, len(silent),
					len(active)))
		empty = [c['cycle'] for c in active if c.get('window_switched_on_focus')
			and not c.get('menu_trees_non_empty_on_focus')]
		if empty:
			problems.append('%s: no non-empty menu tree reached the bus for the GTK test app '
				'after a focus change in %d of %d cycles' % (label, len(empty), len(active)))
		lost = [c['cycle'] for c in active if c.get('app_refocused') is False
			or c.get('helper_focused') is False]
		if lost:
			problems.append('%s: harness: focus did not move to the helper window and back in cycles %s'
				% (label, ','.join(map(str, lost[:5]))))
	no_daemon = [c['cycle'] for c in cycles if c.get('enabled_state') == 'ACTIVE'
		and not c.get('daemon_owned')]
	if no_daemon:
		problems.append('%s: daemon did not own %s after enable in cycles %s' % (
			label, 'space.unmade.GlobalMenu', ','.join(map(str, no_daemon[:5]))))
	left = [c['cycle'] for c in cycles if c.get('daemon_pids_disabled')
		or c.get('daemon_released') is False]
	if left:
		problems.append('%s: daemon still running after disable in cycles %s' % (
			label, ','.join(map(str, left[:5]))))
	# daemon_pids_after_shell is recorded, not judged: a real session stops
	# the shell's cgroup with it, which a container without systemd does not
	scan_res = shell.get('scan', {})
	errs = scan_res.get('blamed', [])
	if errs:
		first = errs[0]['text'].splitlines()[0][:160]
		problems.append('%s: %d error/warning blocks from the extension or daemon in the '
			'shell log, first: %s' % (label, len(errs), first))
	new = scan_res.get('new_with_extension', [])
	if new:
		problems.append('%s: %d error/warning lines that the baseline session without the '
			'extension does not print, first: %s' % (label, len(new),
				new[0]['text'].splitlines()[0][:160]))


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--dir', required=True)
	parser.add_argument('--image', required=True)
	parser.add_argument('--cycles', type=int, default=20)
	args = parser.parse_args()
	d = args.dir

	res = {'image': args.image}
	res.update(load(os.path.join(d, 'env.json')))
	res['deps'] = load(os.path.join(d, 'deps.json'))
	res['install'] = load(os.path.join(d, 'install.json'))
	res['daemon'] = load(os.path.join(d, 'daemon.json'))
	res['shell'] = {}
	problems = []

	inst = res['install']
	for method in inst.get('methods', []):
		if method.get('documented') and method.get('exit') != 0:
			problems.append('install "%s" failed: %s' % (method['name'],
				method.get('reason', 'exit %s' % method.get('exit'))))
	if not inst.get('used'):
		problems.append('no install method gave a working global-menu')
	for miss in inst.get('depends_closure_missing', []):
		problems.append('deb Depends do not pull in %s' % miss)

	missing_required = [k for k, v in res['deps'].get('required', {}).items() if not v]
	if missing_required:
		problems.append('required imports missing: %s' % ', '.join(missing_required))

	dm = res['daemon']
	if inst.get('used'):
		if dm.get('error'):
			problems.append('daemon start: %s' % dm['error'])
		else:
			for name, ok in dm.get('owned', {}).items():
				if not ok:
					problems.append('daemon did not own %s within 15 s' % name)
			if dm.get('left_after_term'):
				problems.append('%d daemon processes left after SIGTERM' % dm['left_after_term'])

	baseline = None
	for label in ('baseline', 'as_shipped', 'validation_off'):
		path = os.path.join(d, 'shell-%s.json' % label)
		if not os.path.exists(path):
			continue
		shell = load(path)
		log = os.path.join(d, 'shell-%s.log' % label)
		if label == 'baseline':
			shell['scan'] = scan(log, 0)
			baseline = {normalize(b[2]) for b in blocks(read_lines(log))}
		else:
			shell['scan'] = scan(log, shell.get('log_offset_before_enable', 0), baseline)
		res['shell'][label] = shell
	if baseline is None:
		problems.append('the baseline shell pass did not run')
	elif not res['shell']['baseline'].get('started'):
		problems.append('baseline: %s' % res['shell']['baseline'].get('error', 'shell did not start'))
	shipped = res['shell'].get('as_shipped', {})
	if not shipped:
		problems.append('the shell pass did not run')
	elif shipped.get('first_state') == 'OUT_OF_DATE':
		problems.append('extension OUT_OF_DATE as shipped: metadata.json shell-version '
			'does not list GNOME %s' % res.get('gnome_major', '?'))
		off = res['shell'].get('validation_off')
		if off:
			judge_pass('validation off', off, problems, args.cycles)
			judge_pass('as shipped', {k: v for k, v in shipped.items() if k != 'cycles'},
				problems, 0)
	else:
		judge_pass('as shipped', shipped, problems, args.cycles)

	res['problems'] = problems
	res['pass'] = not problems
	with open(os.path.join(d, 'result.json'), 'w') as f:
		json.dump(res, f, indent=1)
	return 0


if __name__ == '__main__':
	sys.exit(main())
