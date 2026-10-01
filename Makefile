version = `python3 -c "import globalmenu; print(globalmenu.__version__)"`

.PHONY: build clean

build:
	python3 setup.py install --root=debian --install-layout=deb --no-compile
	cd debian && find . -type f ! -regex '.*.hg.*' ! -regex '.*?debian-binary.*' ! -regex '.*?DEBIAN.*' -printf '%P ' | xargs md5sum > DEBIAN/md5sums && cd -
	sed -i "s/Version: .*/Version: $(version)/" "debian/DEBIAN/control"
	dpkg -b debian/ global-menu_$(version)_all.deb

clean:
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info/
	rm -rf debian/usr/
	rm -f debian/DEBIAN/md5sums
	rm -f global-menu_*.deb
