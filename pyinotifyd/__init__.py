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

import argparse
import asyncio
import logging
import logging.handlers
import pyinotify
import signal
import sys

from pyinotifyd.watch import Watch, EventMap
from pyinotifyd._install import install, uninstall

__version__ = "0.0.1"


class Pyinotifyd:
    def __init__(self, watches=[], shutdown_timeout=30, logname="daemon"):
        self.set_watches(watches)
        self.set_shutdown_timeout(shutdown_timeout)
        logname = (logname or __name__)
        self._log = logging.getLogger(logname)
        self._loop = asyncio.get_event_loop()
        self._notifiers = []
        self._wm = pyinotify.WatchManager()

    def set_watches(self, watches):
        if not isinstance(watches, list):
            watches = [watches]

        for watch in watches:
            assert isinstance(watch, Watch), \
                f"watches: expected {type(Watch)}, got {type(watch)}"

        self._watches = watches

    def add_watch(self, *args, **kwargs):
        self._watches.append(Watch(*args, **kwargs))

    def set_shutdown_timeout(self, timeout):
        assert isinstance(timeout, int), \
            f"timeout: expected {type(int)}, " \
            f"got {type(timeout)}"
        self._shutdown_timeout = timeout

    def start(self, loop=None):
        if not loop:
            loop = self._loop

        self._log.info("starting")
        if len(self._watches) == 0:
            self._log.warning("no watches configured, the daemon will not do anything")
        for watch in self._watches:
            self._log.info(f"start watching '{watch.path}' for inotify events")
            self._notifiers.append(watch.event_notifier(self._wm, loop))

    def stop(self):
        self._log.info("stop watching for inotify events")
        for notifier in self._notifiers:
            notifier.stop()

        self._notifiers = []
        return self._shutdown_timeout


async def _shutdown(signame, daemon, log):
    log.info(f"got signal {signame}, graceful shutdown")
    timeout = daemon.stop()
    pending = [t for t in asyncio.all_tasks()
               if t is not asyncio.current_task()]
    if len(pending) > 0:
        log.info(
            f"waiting {timeout}s for remaining tasks to complete")
        try:
            future = asyncio.gather(*pending)
            await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            log.warning("forcefully terminate remaining tasks")
            future.cancel()
            future.exception()

    log.info("shutdown complete")
    asyncio.get_event_loop().stop()


def main():
    myname = "pyinotifyd"

    parser = argparse.ArgumentParser(
        description=myname,
        formatter_class=lambda prog: argparse.HelpFormatter(
            prog, max_help_position=45, width=140))
    parser.add_argument(
        "-c",
        "--config",
        help=f"path to config file (default: /etc/{myname}/config.py)",
        default=f"/etc/{myname}/config.py")
    parser.add_argument(
        "-d",
        "--debug",
        help="log debugging messages",
        action="store_true")

    exclusive = parser.add_mutually_exclusive_group()
    exclusive.add_argument(
        "-l",
        "--list",
        help="show all usable event types and exit",
        action="store_true")
    exclusive.add_argument(
        "-v",
        "--version",
        help="show version and exit",
        action="store_true")
    exclusive.add_argument(
        "-i",
        "--install",
        help="install systemd service file",
        action="store_true")
    exclusive.add_argument(
        "-u",
        "--uninstall",
        help="uninstall systemd service file",
        action="store_true")
    exclusive.add_argument(
        "-t",
        "--configtest",
        help="test config and exit",
        action="store_true")

    args = parser.parse_args()

    if args.version:
        print(f"{myname} ({version})")
        sys.exit(0)

    if args.list:
        types = "\n".join(EventMap.flags.keys())
        print(types)
        sys.exit(0)

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(loglevel)

    ch = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    ch.setFormatter(formatter)
    root_logger.addHandler(ch)

    if args.install:
        sys.exit(install(myname))

    if args.uninstall:
        sys.exit(uninstall(myname))

    try:
        config = {}
        exec(f"from {myname}.scheduler import *", config)
        exec(f"from {myname}.filemanager import *", config)
        with open(args.config, "r") as c:
            exec(c.read(), globals(), config)
        daemon = config[f"{myname}"]
        assert isinstance(daemon, Pyinotifyd), \
            f"{myname}: expected {type(Pyinotifyd)}, " \
            f"got {type(daemon)}"
    except Exception as e:
        logging.exception(f"config file '{args.config}': {e}")
        sys.exit(1)

    if args.configtest:
        logging.info("config file ok")
        sys.exit(0)

    if args.debug:
        root_logger.setLevel(loglevel)
    formatter = logging.Formatter(
        f"%(asctime)s - {myname}/%(name)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)

    log = logging.getLogger(myname)
    loop = asyncio.get_event_loop()
    for signame in ["SIGINT", "SIGTERM"]:
        loop.add_signal_handler(
            getattr(signal, signame),
            lambda: asyncio.ensure_future(
                _shutdown(signame, daemon, log)))

    daemon.start()
    loop.run_forever()
    loop.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
