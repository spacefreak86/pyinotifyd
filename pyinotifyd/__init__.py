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
    "setLoglevel",
    "enableSyslog",
    "EventMap",
    "Watch",
    "Pyinotifyd",
    "DaemonInstance",
    "scheduler"]

import argparse
import asyncio
import logging
import logging.handlers
import pyinotify
import signal
import sys

from pyinotify import ProcessEvent, ExcludeFilter

from pyinotifyd._install import install, uninstall
from pyinotifyd.scheduler import TaskScheduler, Cancel

__version__ = "0.0.9"


def setLoglevel(loglevel, logname=None):
    logger = logging.getLogger(logname)
    logger.setLevel(loglevel)


def enableSyslog(loglevel=None, address="/dev/log", logname=None):
    logger = logging.getLogger(logname)
    syslog = logging.handlers.SysLogHandler(address=address)
    syslog.setFormatter(
        logging.Formatter(f"{Pyinotifyd.name}/%(name)s: %(message)s"))
    if loglevel:
        syslog.setLevel(loglevel)

        logger.addHandler(syslog)


class _SchedulerList:
    def __init__(self, schedulers=[]):
        if not isinstance(schedulers, list):
            schedulers = [schedulers]

        self._schedulers = schedulers

    def process_event(self, event):
        for scheduler in self._schedulers:
            asyncio.create_task(scheduler.process_event(event))

    def schedulers(self):
        return self._schedulers


class EventMap(ProcessEvent):
    flags = {
        **pyinotify.EventsCodes.OP_FLAGS,
        **pyinotify.EventsCodes.EVENT_FLAGS}

    def my_init(self, event_map=None, default_sched=None, exclude_filter=None,
                logname="eventmap"):
        self._map = {}
        self._exclude_filter = None

        if default_sched is not None:
            for flag in EventMap.flags:
                self.set(flag, default_sched)

        if event_map is not None:
            assert isinstance(event_map, dict), \
                f"event_map: expected {type(dict)}, got {type(event_map)}"
            for flag, schedulers in event_map.items():
                self.set_scheduler(flag, schedulers)

        self.set_exclude_filter(exclude_filter)
        self._log = logging.getLogger((logname or __name__))

    def set_scheduler(self, flag, schedulers):
        assert flag in EventMap.flags, \
            f"event_map: invalid flag: {flag}"
        if schedulers is not None:
            if not isinstance(schedulers, list):
                schedulers = [schedulers]

            instances = []
            for scheduler in schedulers:
                if issubclass(type(scheduler), TaskScheduler) or \
                        isinstance(scheduler, Cancel):
                    instances.append(scheduler)
                else:
                    instances.append(TaskScheduler(scheduler))

            self._map[flag] = _SchedulerList(instances)

        elif flag in self._map:
            del self._map[flag]

    def set_exclude_filter(self, exclude_filter):
        if exclude_filter is None:
            self._exclude_filter = None
            return

        if not isinstance(exclude_filter, ExcludeFilter):
            self._exclude_filter = ExcludeFilter(exclude_filter)
        else:
            self._exclude_filter = exclude_filter

    def process_default(self, event):
        attrs = ""
        for attr in [
                "dir", "mask", "maskname", "pathname", "src_pathname", "wd"]:
            value = getattr(event, attr, None)
            if attr == "mask":
                value = hex(value)
            if value:
                attrs += f", {attr}={value}"

        self._log.debug(f"received event{attrs}")
        maskname = event.maskname.split("|")[0]

        if maskname not in self._map:
            return

        if self._exclude_filter and self._exclude_filter(event.pathname):
            self._log.debug(f"pathname {event.pathname} is excluded")
            return

        self._map[maskname].process_event(event)

    def schedulers(self):
        schedulers = []
        for scheduler_list in self._map.values():
            schedulers.extend(
                scheduler_list.schedulers())

        return list(set(schedulers))


class Watch:
    def __init__(self, path, event_map=None, default_sched=None,
                 rec=False, auto_add=False, exclude_filter=None,
                 logname="watch"):
        assert (isinstance(path, str) or isinstance(path, list)), \
            f"path: expected {type('')} or {type([])}, got {type(path)}"

        if isinstance(event_map, EventMap):
            self._event_map = event_map
        else:
            self._event_map = EventMap(
                event_map=event_map, default_sched=default_sched,
                exclude_filter=exclude_filter)

        assert isinstance(rec, bool), \
            f"rec: expected {type(bool)}, got {type(rec)}"
        assert isinstance(auto_add, bool), \
            f"auto_add: expected {type(bool)}, got {type(auto_add)}"

        self._exclude_filter = None
        if exclude_filter:
            if not isinstance(exclude_filter, ExcludeFilter):
                self._exclude_filter = ExcludeFilter(exclude_filter)
            else:
                self._exclude_filter = exclude_filter

        logname = (logname or __name__)

        self._path = path
        self._rec = rec
        self._auto_add = auto_add

        self._watch_manager = pyinotify.WatchManager()
        self._notifier = None
        self._log = logging.getLogger(logname)

    def path(self):
        return self._path

    def event_map(self):
        return self._event_map

    def start(self):
        self._watch_manager.add_watch(self._path, pyinotify.ALL_EVENTS,
                                      rec=self._rec, auto_add=self._auto_add,
                                      exclude_filter=self._exclude_filter,
                                      do_glob=True)

        self._notifier = pyinotify.AsyncioNotifier(
            self._watch_manager, asyncio.get_event_loop(), default_proc_fun=self._event_map)

    def stop(self):
        self._notifier.stop()

        self._notifier = None


class Pyinotifyd:
    name = "pyinotifyd"

    def __init__(self, watches=[], shutdown_timeout=30, logname="daemon"):
        self.set_watches(watches)
        self.set_shutdown_timeout(shutdown_timeout)
        logname = (logname or __name__)

        self._log = logging.getLogger(logname)

    @staticmethod
    def from_cfg_file(config_file):
        config = {}
        name = Pyinotifyd.name
        exec("from logging import DEBUG, INFO, WARNING, ERROR, CRITICAL",
            config)
        exec(f"from {name} import Pyinotifyd, Watch", config)
        exec(f"from {name} import setLoglevel, enableSyslog", config)
        exec(f"from {name}.scheduler import *", config)
        with open(config_file, "r") as fh:
            exec(fh.read(), config)
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

    def add_watch(self, *args, watch=None, **kwargs):
        if watch:
            assert isinstance(watch, Watch), \
                f"watch: expected {type(Watch)}, got {type(watch)}"
            self._watches.append(watch)
        else:
            self._watches.append(Watch(*args, **kwargs))

    def set_shutdown_timeout(self, timeout):
        assert isinstance(timeout, int), \
            f"timeout: expected {type(int)}, " \
            f"got {type(timeout)}"
        self._shutdown_timeout = timeout

    def schedulers(self):
        schedulers = []
        for w in self._watches:
            schedulers.extend(w.event_map().schedulers())
        return list(set(schedulers))

    def start(self):
        if len(self._watches) == 0:
            self._log.warning(
                "no watches configured, the daemon will not do anything")

        for watch in self._watches:
            self._log.info(
                f"start listening for inotify events on '{watch.path()}'")
            watch.start()

    def pause(self):
        for scheduler in self.schedulers():
            scheduler.pause()

    async def shutdown(self):
        schedulers = self.schedulers()

        tasks = [s.shutdown(self._shutdown_timeout) for s in set(schedulers)]
        if tasks:
            await asyncio.gather(*tasks)

        for watch in self._watches:
            self._log.debug(
                f"stop listening for inotify events on '{watch.path()}'")
            watch.stop()


class DaemonInstance:
    def __init__(self, instance, logname="daemon"):
        self._instance = instance
        self._shutdown = False
        self._log = logging.getLogger(logname)

    def start(self):
        self._instance.start()

    async def shutdown(self, signame):
        if self._shutdown:
            self._log.warning(
                f"got signal {signame}, but shutdown already in progress")
            return

        self._log.info(f"got signal {signame}, shutdown")
        self._shutdown = True

        try:
            await self._instance.shutdown()

            pending = [t for t in asyncio.all_tasks()
                       if t is not asyncio.current_task()]

            for task in pending:
                task.cancel()

            try:
                await asyncio.gather(*pending)
            except asyncio.CancelledError:
                pass
        except Exception as e:
            self._log.exception(f"error during shutdown: {e}")

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

            old_instance = self._instance

            old_instance.pause()
            instance.start()
            asyncio.create_task(old_instance.shutdown())

            self._instance = instance


def main():
    name = Pyinotifyd.name

    parser = argparse.ArgumentParser(
        description=name,
        formatter_class=lambda prog: argparse.HelpFormatter(
            prog, max_help_position=45, width=140))
    parser.add_argument(
        "-c",
        "--config",
        help=f"path to config file (default: /etc/{name}/config.py)",
        default=f"/etc/{name}/config.py")
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
        help="install service files and config",
        action="store_true")
    exclusive.add_argument(
        "-u",
        "--uninstall",
        help="uninstall service files and unmodified config",
        action="store_true")
    exclusive.add_argument(
        "-t",
        "--configtest",
        help="test config and exit",
        action="store_true")

    args = parser.parse_args()

    if args.version:
        print(f"{name} ({__version__})")
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
        sys.exit(install(name))

    if args.uninstall:
        sys.exit(uninstall(name))

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
        f"%(asctime)s - {name}/%(name)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(
        signal.SIGTERM, lambda: loop.create_task(
            daemon.shutdown("SIGTERM")))
    loop.add_signal_handler(
        signal.SIGINT, lambda: loop.create_task(
            daemon.shutdown("SIGINT")))
    loop.add_signal_handler(
        signal.SIGHUP, lambda: loop.create_task(
            daemon.reload("SIGHUP", args.config, args.debug)))

    daemon.start()
    loop.run_forever()
    loop.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
