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

import logging
import os
import shutil
import sys

SYSTEMD_PATH = "/lib/systemd/system"
OPENRC = "/sbin/openrc"


def _check_root():
    if os.getuid() != 0:
        logging.error("you need to have root privileges, please try again")
        return False

    return True


def _check_systemd():
    systemd = os.path.isdir(SYSTEMD_PATH)
    if systemd:
        logging.info("systemd detected")

    return systemd


def _check_openrc():
    openrc = os.path.isfile(OPENRC) and os.access(OPENRC, os.X_OK)
    if openrc:
        logging.info("openrc detected")

    return openrc


def _copy_missing_file(src, dst):
    if os.path.exists(dst):
        logging.info(f" => file {dst} already installed")
    else:
        try:
            logging.info(f" => install file {dst}")
            shutil.copy2(src, dst)
        except Exception as e:
            logging.error(f" => unable to install file {dst}: {e}")


def _delete_present_file(f):
    if os.path.isfile(f):
        try:
            logging.info(f" => uninstall file {f}")
            os.remove(f)
        except Exception as e:
            logging.error(f" => unable to uninstall file {f}: {e}")


def _warn_exists(path):
    if os.path.isdir(path):
        logging.warning(
            f" => directory {path} is still present, "
            f"you have to remove it manually")
    else:
        logging.warning(
            f" => file {path} is still present, "
            f"you have to remove it manually")


def install(name):
    if not _check_root():
        sys.exit(2)

    pkg_dir = os.path.dirname(__file__)

    if _check_systemd():
        dst = f"{SYSTEMD_PATH}/{name}.service"
        src = f"{pkg_dir}/misc/systemd/{name}.service"
        _copy_missing_file(src, dst)

    if _check_openrc():
        files = [
            (f"{pkg_dir}/misc/openrc/{name}.initd", f"/etc/init.d/{name}"),
            (f"{pkg_dir}/misc/openrc/{name}.confd", f"/etc/conf.d/{name}")]
        for src, dst in files:
            _copy_missing_file(src, dst)

    logging.info("install configuration file")
    config_dir = f"/etc/{name}"
    if os.path.isdir(config_dir):
        logging.info(f" => directory {config_dir} exists already")
    else:
        try:
            logging.info(f" => create directory {config_dir}")
            os.mkdir(config_dir)
        except Exception as e:
            logging.error(f" => unable to create directory {config_dir}: {e}")
            sys.exit(3)

    files = [
        (f"{pkg_dir}/docs/config.py.example", f"{config_dir}/config.py")]
    for src, dst in files:
        _copy_missing_file(src, dst)

    logging.info(f"{name} successfully installed")


def uninstall(name):
    if not _check_root():
        sys.exit(2)

    if _check_systemd():
        _delete_present_file(f"{SYSTEMD_PATH}/{name}.service")

    if _check_openrc():
        _delete_present_file(f"/etc/init.d/{name}")
        _warn_exists(f"/etc/conf.d/{name}")

    _warn_exists(f"/etc/{name}")

    logging.info(f"{name} successfully uninstalled")
