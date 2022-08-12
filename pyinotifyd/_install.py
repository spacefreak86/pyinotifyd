#!/usr/bin/env python3

# pyinotifyd is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyinotifyd is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyinotifyd.  If not, see <http://www.gnu.org/licenses/>.
#

import filecmp
import logging
import os
import shutil
import sys


SYSTEMD_PATHS = ["/lib/systemd/system", "/usr/lib/systemd/system"]

OPENRC = "/sbin/openrc"


def _systemd_files(pkg_dir, name):
    for path in SYSTEMD_PATHS:
        if os.path.isdir(path):
            break

    return [
        (f"{pkg_dir}/misc/systemd/{name}.service",
            f"{path}/{name}.service", True)]


def _openrc_files(pkg_dir, name):
    return [
        (f"{pkg_dir}/misc/openrc/{name}.initd", f"/etc/init.d/{name}", True),
        (f"{pkg_dir}/misc/openrc/{name}.confd", f"/etc/conf.d/{name}", False)]


def _config_files(pkg_dir, name):
    return [
        (f"{pkg_dir}/misc/config.py.default", f"/etc/{name}/config.py", False)]


def _install_files(files):
    for src, dst, force in files:
        if os.path.exists(dst):
            if os.path.isdir(dst):
                logging.error(
                    " => unable to copy file, destination path is a directory")
                continue
            elif not force:
                logging.info(f" => file {dst} already exists")
                continue

        try:
            logging.info(f" => install file {dst}")
            shutil.copy2(src, dst)
        except Exception as e:
            logging.error(f" => unable to install file {dst}: {e}")


def _uninstall_files(files):
    for src, dst, force in files:
        if not os.path.isfile(dst):
            continue

        if not force and not filecmp.cmp(src, dst, shallow=True):
            logging.warning(
                f" => keep modified file {dst}, "
                f"you have to remove it manually")
            continue

        try:
            logging.info(f" => uninstall file {dst}")
            os.remove(dst)
        except Exception as e:
            logging.error(f" => unable to uninstall file {dst}: {e}")


def _create_dir(path):
    if os.path.isdir(path):
        logging.info(f" => directory {path} already exists")
    else:
        try:
            logging.info(f" => create directory {path}")
            os.mkdir(path)
        except Exception as e:
            logging.error(f" => unable to create directory {path}: {e}")
            return False

    return True


def _delete_dir(path):
    if os.path.isdir(path):
        if not os.listdir(path):
            try:
                logging.info(f" => delete directory {path}")
                os.rmdir(path)
            except Exception as e:
                logging.error(f" => unable to delete directory {path}: {e}")
        else:
            logging.warning(f" => keep non-empty directory {path}")


def _check_root():
    if os.getuid() != 0:
        logging.error("you need to have root privileges, please try again")
        return False

    return True


def _check_systemd():
    for path in SYSTEMD_PATHS:
        systemd = os.path.isdir(path)
        if systemd:
            break

    if systemd:
        logging.info("systemd detected")

    return systemd


def _check_openrc():
    openrc = os.path.isfile(OPENRC) and os.access(OPENRC, os.X_OK)
    if openrc:
        logging.info("openrc detected")

    return openrc


def install(name):
    if not _check_root():
        sys.exit(2)

    pkg_dir = os.path.dirname(__file__)

    if _check_systemd():
        _install_files(_systemd_files(pkg_dir, name))

    if _check_openrc():
        _install_files(_openrc_files(pkg_dir, name))

    if not _create_dir(f"/etc/{name}"):
        logging.error(" => unable to create config dir, giving up ...")
        sys.exit(3)

    _install_files(_config_files(pkg_dir, name))

    logging.info(f"{name} successfully installed")


def uninstall(name):
    if not _check_root():
        sys.exit(2)

    pkg_dir = os.path.dirname(__file__)

    _uninstall_files(_systemd_files(pkg_dir, name))
    _uninstall_files(_openrc_files(pkg_dir, name))
    _uninstall_files(_config_files(pkg_dir, name))

    _delete_dir(f"/etc/{name}")

    logging.info(f"{name} successfully uninstalled")
