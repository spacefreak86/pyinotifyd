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

__all__ = [
    "Pyinotifyd",
    "daemon_from_config",
]

import argparse
import asyncio
import logging
import logging.handlers
import signal
import sys

from pyinotifyd.watch import Watch, EventMap
from pyinotifyd._install import install, uninstall

__version__ = "0.0.2"


class Pyinotifyd:
    name = "pyinotifyd"

    def __init__(self, watches=[], shutdown_timeout=30, logname="daemon"):
        self.set_watches(watches)
        self.set_shutdown_timeout(shutdown_timeout)
        logname = (logname or __name__)
        self._log = logging.getLogger(logname)
        self._loop = asyncio.get_event_loop()

    @staticmethod
    def from_cfg_file(config_file):
        config = {}
        name = Pyinotifyd.name
        exec(f"from {name} import Pyinotifyd", {}, config)
        exec(f"from {name}.scheduler import *", {}, config)
        exec(f"from {name}.watch import EventMap, Watch", {}, config)
        with open(config_file, "r") as fh:
            exec(fh.read(), {}, config)
        instance = config[f"{name}"]
        assert isinstance(instance, Pyinotifyd), \
            f"{name}: expected {type(Pyinotifyd)}, " \
            f"got {type(instance)}"
        return instance

    def set_watches(self, watches):
        if not isinstance(watches, list):
            watches = [watches]

        for watch in watches:
            assert isinstance(watch, Watch), \
                f"watches: expected {type(Watch)}, got {type(watch)}"

        self._watches = []
        self._watches.extend(watches)

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

        if len(self._watches) == 0:
            self._log.warning(
                "no watches configured, the daemon will not do anything")

        for watch in self._watches:
            self._log.info(
                f"start listening for inotify events on '{watch.path()}'")
            watch.start(loop)

    def stop(self):
        for watch in self._watches:
            self._log.info(
                f"stop listening for inotify events on '{watch.path()}'")
            watch.stop()

        return self._shutdown_timeout


class DaemonInstance:
    def __init__(self, instance, logname="daemon"):
        self._instance = instance
        self._shutdown = False
        self._log = logging.getLogger(logname)

    def start(self):
        self._instance.start()

    def stop(self):
        return self._instance.stop()

    def _get_pending_tasks(self):
        return [t for t in asyncio.all_tasks()
                if t is not asyncio.current_task()]

    async def shutdown(self, signame):
        if self._shutdown:
            self._log.warning(
                f"got signal {signame}, but shutdown already in progress")
            return

        self._shutdown = True
        self._log.info(f"got signal {signame}, shutdown")
        timeout = self.stop()

        pending = self._get_pending_tasks()
        if pending:
            if timeout:
                future = asyncio.gather(*pending)
                self._log.info(
                    f"wait {timeout} seconds for {len(pending)} "
                    f"remaining task(s) to complete")
                try:
                    await asyncio.wait_for(future, timeout)
                    pending = []
                except asyncio.TimeoutError:
                    future.cancel()
                    future.exception()
                    self._log.warning(
                        "shutdown timeout exceeded, remaining task(s) killed")
            else:
                self._log.warning(
                    f"cancel {len(pending)} remaining task(s)")

                for task in pending:
                    task.cancel()

                try:
                    await asyncio.gather(*pending)
                except asyncio.CancelledError:
                    pass

        asyncio.get_event_loop().stop()
        self._shutdown = False
        self._log.info("shutdown complete")

    async def reload(self, signame, config_file, debug=False):
        if self._shutdown:
            self._log.info(
                f"got signal {signame}, but shutdown already in progress")
            return

        self._log.info(f"got signal {signame}, reload config file")
        try:
            instance = Pyinotifyd.from_cfg_file(config_file)
        except Exception as e:
            logging.exception(
                f"unable to reload config file '{config_file}': {e}")
        else:
            if debug:
                logging.getLogger().setLevel(logging.DEBUG)
            self.stop()
            self._instance = instance
            self.start()


def main():
    myname = Pyinotifyd.name

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
        print(f"{myname} ({__version__})")
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
        pyinotifyd = Pyinotifyd.from_cfg_file(args.config)
        daemon = DaemonInstance(pyinotifyd)
    except Exception as e:
        if args.debug:
            logging.exception(f"config file: {e}")
        else:
            logging.error(f"config file: {e}")

        sys.exit(1)

    if args.configtest:
        logging.info("config file ok")
        sys.exit(0)

    if args.debug:
        root_logger.setLevel(loglevel)

    formatter = logging.Formatter(
        f"%(asctime)s - {myname}/%(name)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)

    loop = asyncio.get_event_loop()
    for signame in ["SIGINT", "SIGTERM"]:
        loop.add_signal_handler(
            getattr(signal, signame),
            lambda: asyncio.ensure_future(
                daemon.shutdown(signame)))

    loop.add_signal_handler(
        getattr(signal, "SIGHUP"),
        lambda: asyncio.ensure_future(
            daemon.reload("SIGHUP", myname, args.config, args.debug)))

    daemon.start()
    loop.run_forever()
    loop.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
