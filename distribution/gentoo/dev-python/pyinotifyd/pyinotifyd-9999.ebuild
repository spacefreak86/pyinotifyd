# Copyright 2020 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=7
PYTHON_COMPAT=( python3_{8..11} )
DISTUTILS_USE_SETUPTOOLS=rdepend

SCM=""
if [ "${PV#9999}" != "${PV}" ] ; then
	SCM="git-r3"
	EGIT_REPO_URI="https://github.com/spacefreak86/${PN}"
fi

inherit ${SCM} distutils-r1 systemd

DESCRIPTION="Monitore filesystems events and execute Python methods or Shell commands."
HOMEPAGE="https://github.com/spacefreak86/pymodmilter"
if [ "${PV#9999}" != "${PV}" ] ; then
	SRC_URI=""
	KEYWORDS=""
	# Needed for tests
	S="${WORKDIR}/${PN}"
	EGIT_CHECKOUT_DIR="${S}"
else
	SRC_URI="https://github.com/spacefreak86/${PN}/archive/${PV}.tar.gz -> ${P}.tar.gz"
	KEYWORDS="amd64 x86"
fi

LICENSE="GPL-3"
SLOT="0"

IUSE="systemd"

RDEPEND="dev-python/pyinotify[${PYTHON_USEDEP}]"

python_install_all() {
	distutils-r1_python_install_all

	dodir /etc/${PN}
	insinto /etc/${PN}
	newins ${PN}/misc/config.py.default config.py

	use systemd && systemd_dounit ${PN}/misc/${PN}.service

	newinitd ${PN}/misc/openrc/${PN}.initd ${PN}
	newconfd ${PN}/misc/openrc/${PN}.confd ${PN}
}
