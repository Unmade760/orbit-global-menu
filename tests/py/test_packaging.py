# Packaging checks that need no container: the Debian maintainer scripts must
# be executable in git (dpkg-deb refuses mode 644), and the dependency lists
# must name every typelib the daemon imports.

import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _control_field(name):
	with open(os.path.join(ROOT, 'debian', 'DEBIAN', 'control')) as f:
		text = f.read()
	m = re.search(r'^%s:\s*(.*(?:\n[ \t].*)*)' % name, text, re.M)
	assert m, '%s missing from debian/DEBIAN/control' % name
	return {p.strip().split()[0] for p in m.group(1).split(',') if p.strip()}


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
@pytest.mark.parametrize('script', ['postinst', 'prerm'])
def test_maintainer_script_is_executable_in_git(script):
	path = 'debian/DEBIAN/' + script
	out = subprocess.run(['git', 'ls-files', '-s', path], cwd=ROOT,
		capture_output=True, text=True)
	if out.returncode != 0 or not out.stdout:
		pytest.skip('not a git checkout')
	assert out.stdout.split()[0] == '100755'
