pkgname=python-global-menu
pkgver=1.0.0
pkgrel=1
pkgdesc="Companion daemon for the Global Menu GNOME Shell extension"
arch=('i686' 'x86_64')
url="https://github.com/Unmade760/orbit-global-menu"
license=('GPL3')
depends=('python-gobject'
         'python-dbus'
         'gtk3'
         'appmenu-gtk-module')
optdepends=('bamf: window matching on X11'
            'libkeybinder3: Alt+Space menu search on X11'
            'libdbusmenu-glib: lets Electron and Firefox export their menus')
makedepends=('git' 'python-setuptools')
provides=("python-global-menu=$pkgver")
source=('git+https://github.com/Unmade760/orbit-global-menu.git')
md5sums=('SKIP')

pkgver() {
    cd "$srcdir/global-menu"
    python3 -c "import globalmenu; print(globalmenu.__version__)"
}

build() {
    cd "$srcdir/global-menu"
    python3 setup.py bdist_wheel
}

package() {
    cd "$srcdir/global-menu"
    python3 setup.py install --skip-build --root=$pkgdir --optimize=1
}
