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


def check_root():
    if os.getuid() != 0:
        logging.error("you need to have root privileges to install "
                      "the systemd service file, please try again")
        return False

    return True


def check_systemd():
    if not check_root():
        return False

    if not os.path.isdir("/usr/lib/systemd/system"):
        logging.error("systemd is not running on your system")
        return False

    return True


def install_systemd_service(name):
    if not check_systemd():
        return 1

    dst_path = "/usr/lib/systemd/system/{name}.service"

    if os.path.exists(dst_path):
        logging.error("systemd service file is already installed")
        return 1

    pkg_dir = os.path.dirname(__file__)
    src_path = f"{pkg_dir}/docs/{name}.service"

    try:
        shutil.copy2(src_path, dst_path)
    except Exception as e:
        logging.error(f"unable to copy: {e}")
        return 1

    logging.info("systemd service file successfully installed")

    return 0


def uninstall_systemd_service(name):
    if not check_systemd():
        return 1

    path = "/usr/lib/systemd/system/{name}.service"

    if not os.path.exists(path):
        logging.info("systemd service is not installed")
        return 0

    try:
        os.remove(path)
    except Exception as e:
        logging.error(f"unable to delete: {e}")
        return 1

    return 0
