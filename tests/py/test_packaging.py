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


def test_deb_depends_name_the_gtk3_typelib():
	assert 'gir1.2-gtk-3.0' in _control_field('Depends')


def test_deb_recommends_name_the_x11_typelibs():
	rec = _control_field('Recommends')
	assert {'gir1.2-bamf-3', 'gir1.2-keybinder-3.0'} <= rec
	assert 'libkeybinder-3.0-0' not in rec


def test_pkgbuild_depends_name_gtk3():
	with open(os.path.join(ROOT, 'PKGBUILD')) as f:
		text = f.read()
	depends = re.search(r'^depends=\((.*?)\)', text, re.M | re.S).group(1)
	assert "'gtk3'" in depends


def test_makefile_targets_are_phony():
	# "make build" leaves a build/ directory behind, and without .PHONY the
	# next run answers "'build' is up to date" and builds nothing.
	with open(os.path.join(ROOT, 'Makefile')) as f:
		text = f.read()
	m = re.search(r'^\.PHONY:(.*)$', text, re.M)
	assert m and {'build', 'clean'} <= set(m.group(1).split())


def test_pkgbuild_cd_matches_the_source_checkout_directory():
	# makepkg checks a git source out to "name" for "name::git+URL", else to
	# the URL's basename without .git.
	with open(os.path.join(ROOT, 'PKGBUILD')) as f:
		text = f.read()
	source = re.search(r"^source=\(\s*'([^']+)'", text, re.M).group(1)
	if '::' in source:
		checkout = source.split('::', 1)[0]
	else:
		checkout = re.sub(r'\.git$', '', source.split('#')[0].rstrip('/').rsplit('/', 1)[-1])
	dirs = re.findall(r'^\s*cd "\$srcdir/([^"]+)"', text, re.M)
	assert dirs
	assert set(dirs) == {checkout}
