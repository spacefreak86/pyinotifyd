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

SYSTEMD_PATH = "/usr/lib/systemd/system"


def _check_root():
    if os.getuid() != 0:
        logging.error("you need to have root privileges, please try again")
        return False

    return True


def _check_systemd():
    return os.path.isdir(SYSTEMD_PATH)


def install(name):
    if not _check_root():
        sys.exit(2)

    pkg_dir = os.path.dirname(__file__)

    if not _check_systemd():
        logging.warning(
            "systemd service file will not be installed,"
            "because systemd is not installed")
    else:
        dst = f"{SYSTEMD_PATH}/{name}.service"
        src = f"{pkg_dir}/misc/{name}.service"
        try:
            shutil.copy2(src, dst)
        except Exception as e:
            logging.error(f"unable to copy systemd service file: {e}")
        else:
            logging.info("systemd service file installed")

    config_dir = f"/etc/{name}"
    if os.path.isdir(config_dir):
        logging.info(f"config dir {config_dir} exists")
    else:
        try:
            os.mkdir(config_dir)
        except Exception as e:
            logging.error(f"unable to create config dir {config_dir}: {e}")
            sys.exit(3)
        else:
            logging.info(f"config dir {config_dir} created")

    dst = f"{config_dir}/config.py"
    src = f"{pkg_dir}/docs/config.py.example"
    if os.path.exists(dst):
        logging.info(f"config file {dst} exists")
    else:
        try:
            shutil.copy2(src, dst)
        except Exception as e:
            logging.error(f"unable to copy config file to {dst}: {e}")
            sys.exit(4)
        else:
            logging.info("example config file copied to {dst}")

    logging.info("{name} successfully installed")


def uninstall(name):
    if not _check_root():
        sys.exit(2)

    if _check_systemd():
        path = f"{SYSTEMD_PATH}/{name}.service"

        if not os.path.exists(path):
            logging.info("systemd service is not installed")
        else:
            try:
                os.remove(path)
            except Exception as e:
                logging.error(f"unable to delete: {e}")
                sys.exit(3)
            else:
                logging.info("systemd service file uninstalled")

    config_dir = f"/etc/{name}"
    if os.path.isdir(config_dir):
        logging.warning(
            f"config dir {config_dir} still exists, please delete manually")

    logging.info("{name} successfully uninstalled")
