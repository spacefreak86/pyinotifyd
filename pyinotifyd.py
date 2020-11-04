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
import os
import pyinotify
import re
import shutil
import signal
import sys

from shlex import quote as shell_quote
from uuid import uuid4

__version__ = "0.0.1"


class Task:
    def __init__(self, event, delay, task_id, task, callback=None,
                 logname=None):
        self._event = event
        self._path = event.pathname
        self._delay = delay
        self._task_id = task_id
        self._job = task
        self._callback = callback

        self._task = None
        self._log = logging.getLogger((logname or self.__class__.__name__))

    async def _start(self):
        if self._delay > 0:
            await asyncio.sleep(self._delay)

        if self._callback is not None:
            self._callback(self._event)

        self._task = None

        self._log.info(f"execute task {self._task_id}")
        await asyncio.shield(self._job(self._event, self._task_id))
        self._log.info(f"task {self._task_id} finished")

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._start())

    def cancel(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def restart(self):
        self.cancel()
        self.start()


class TaskList:
    def __init__(self, tasks=[]):
        if not isinstance(tasks, list):
            tasks = [tasks]

        self._tasks = tasks

    def add(self, task):
        self._tasks.append(task)

    def remove(self, task):
        self._tasks.remove(task)

    def execute(self, event):
        for task in self._tasks:
            task(event)


class TaskScheduler:
    def __init__(self, task, files, dirs, delay=0, logname=None):
        assert callable(task), \
            f"task: expected callable, got {type(task)}"
        self._task = task

        assert isinstance(delay, int), \
            f"delay: expected {type(int)}, got {type(delay)}"
        self._delay = delay

        assert isinstance(files, bool), \
            f"files: expected {type(bool)}, got {type(files)}"
        self._files = files

        assert isinstance(dirs, bool), \
            f"dirs: expected {type(bool)}, got {type(dirs)}"
        self._dirs = dirs

        self._tasks = {}
        self._logname = (logname or self.__class__.__name__)
        self._log = logging.getLogger(self._logname)

    def _task_started(self, event):
        path = event.pathname
        if path in self._tasks:
            del self._tasks[path]

    def schedule(self, event):
        self._log.debug(f"received {event}")

        if (not event.dir and not self._files) or \
                (event.dir and not self._dirs):
            return

        path = event.pathname
        maskname = event.maskname.split("|", 1)[0]

        if path in self._tasks:
            task = self._tasks[path]
            self._log.info(
                f"received event {maskname} on '{path}', "
                f"re-schedule task {task.task_id} (delay={self._delay}s)")
            task.restart()
        else:
            task_id = str(uuid4())
            self._log.info(
                f"received event {maskname} on '{path}', "
                f"schedule task {task_id} (delay={self._delay}s)")
            task = Task(
                event, self._delay, task_id, self._task,
                callback=self._task_started, logname=self._logname)
            self._tasks[path] = task
            task.start()

    def cancel(self, event):
        self._log.debug(f"received {event}")

        path = event.pathname
        maskname = event.maskname.split("|", 1)[0]
        if path in self._tasks:
            task = self._tasks[path]
            self._log.info(
                f"received event {maskname} on '{path}', "
                f"cancel scheduled task {task.task_id}")
            task.cancel()
            del self._tasks[path]


class ShellScheduler(TaskScheduler):
    def __init__(self, cmd, task=None, logname=None, *args, **kwargs):
        assert isinstance(cmd, str), \
            f"cmd: expected {type('')}, got {type(cmd)}"
        self._cmd = cmd

        logname = (logname or self.__class__.__name__)
        super().__init__(*args, task=self.task, logname=logname, **kwargs)

    async def task(self, event, task_id):
        maskname = event.maskname.split("|", 1)[0]

        if hasattr(event, "src_pathname"):
            src_pathname = event.src_pathname
        else:
            src_pathname = ""

        cmd = self._cmd.replace("{maskname}", shell_quote(maskname)).replace(
            "{pathname}", shell_quote(event.pathname)).replace(
                "{src_pathname}", shell_quote(src_pathname))

        self._log.info(f"{task_id}: execute shell command: {cmd}")
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()


class EventMap:
    flags = {
        **pyinotify.EventsCodes.OP_FLAGS,
        **pyinotify.EventsCodes.EVENT_FLAGS}

    def __init__(self, event_map=None, default_task=None):
        self._map = {}

        if default_task is not None:
            assert callable(default_task), \
                f"default_task: expected callable, got {type(default_task)}"
            for flag in EventMap.flags:
                self.set(flag, default_task)

        if event_map is not None:
            assert isinstance(event_map, dict), \
                f"event_map: expected {type(dict)}, got {type(event_map)}"
            for flag, task in event_map.items():
                self.set(flag, task)

    def items(self):
        return self._map.items()

    def set(self, flag, values):
        assert flag in EventMap.flags, \
            f"event_map: invalid flag: {flag}"
        if values is not None:
            if not isinstance(values, list):
                values = [values]

            for value in values:
                assert callable(value), \
                    f"event_map: {flag}: expected callable, got {type(value)}"

            self._map[flag] = values
        elif flag in self._map:
            del self._map[flag]


class Watch:
    def __init__(self, path, event_map, rec=False, auto_add=False):
        assert isinstance(path, str), \
            f"path: expected {type('')}, got {type(path)}"
        self.path = path

        if isinstance(event_map, EventMap):
            self.event_map = event_map
        elif isinstance(event_map, dict):
            self.event_map = EventMap(event_map)
        else:
            raise AssertionError(
                f"event_map: expected {type(EventMap)} or {type(dict)}, "
                f"got {type(event_map)}")

        assert isinstance(rec, bool), \
            f"rec: expected {type(bool)}, got {type(rec)}"
        self.rec = rec

        assert isinstance(auto_add, bool), \
            f"auto_add: expected {type(bool)}, got {type(auto_add)}"
        self.auto_add = auto_add

    def event_notifier(self, wm, loop):
        handler = pyinotify.ProcessEvent()
        mask = False
        for flag, values in self.event_map.items():
            setattr(handler, f"process_{flag}", TaskList(values).execute)
            if mask:
                mask = mask | EventMap.flags[flag]
            else:
                mask = EventMap.flags[flag]

        wm.add_watch(
            self.path, mask, rec=self.rec, auto_add=self.auto_add,
            do_glob=True)

        return pyinotify.AsyncioNotifier(wm, loop, default_proc_fun=handler)


class Rule:
    valid_actions = ["copy", "move", "delete"]

    def __init__(self, action, src_re, dst_re="", auto_create=False,
                 dirmode=None, filemode=None, user=None, group=None,
                 rec=False):
        assert action in self.valid_actions, \
            f"action: expected [{Rule.valid_actions.join(', ')}], got{action}"
        self.action = action

        self.src_re = re.compile(src_re)

        assert isinstance(dst_re, str), \
            f"dst_re: expected {type('')}, got {type(dst_re)}"
        self.dst_re = dst_re

        assert isinstance(auto_create, bool), \
            f"auto_create: expected {type(bool)}, got {type(auto_create)}"
        self.auto_create = auto_create

        if dirmode is not None:
            assert isinstance(dirmode, int), \
                f"dirmode: expected {type(int)}, got {type(dirmode)}"
        self.dirmode = dirmode

        if filemode is not None:
            assert isinstance(filemode, int), \
                f"filemode: expected {type(int)}, got {type(filemode)}"
        self.filemode = filemode

        if user is not None:
            assert isinstance(user, str), \
                f"user: expected {type('')}, got {type(user)}"
        self.user = user

        if group is not None:
            assert isinstance(group, str), \
                f"group: expected {type('')}, got {type(group)}"
        self.group = group

        assert isinstance(rec, bool), \
            f"rec: expected {type(bool)}, got {type(rec)}"
        self.rec = rec


class FileManager:
    def __init__(self, rules, logname=None):
        if not isinstance(rules, list):
            rules = [rules]

        for rule in rules:
            assert isinstance(rule, Rule), \
                f"rules: expected {type(Rule)}, got {type(rule)}"

        self._rules = rules
        self._log = logging.getLogger((logname or self.__class__.__name__))

    def add_rule(self, *args, **kwargs):
        self._rules.append(Rule(*args, **kwargs))

    async def _chmod_and_chown(self, path, mode, chown, task_id):
        if mode is not None:
            self._log.debug(f"{task_id}: chmod {oct(mode)} '{path}'")
            os.chmod(path, mode)

        if chown is not None:
            changes = ""
            if chown[0] is not None:
                changes = chown[0]

            if chown[1] is not None:
                changes = f"{changes}:{chown[1]}"

            self._log.debug(f"{task_id}: chown {changes} '{path}'")
            shutil.chown(path, *chown)

    async def _set_mode_and_owner(self, path, rule, task_id):
        if (rule.user is rule.group is None):
            chown = None
        else:
            chown = (rule.user, rule.group)

        work_on_dirs = not (rule.dirmode is chown is None)
        work_on_files = not (rule.filemode is chown is None)

        if os.path.isdir(path):
            await self._chmod_and_chown(path, rule.dirmode, chown, task_id)
            if work_on_dirs or work_on_files:
                for root, dirs, files in os.walk(path):
                    if work_on_dirs:
                        for p in [os.path.join(root, d) for d in dirs]:
                            await self._chmod_and_chown(
                                p, rule.dirmode, chown, task_id)

                    if work_on_files:
                        for p in [os.path.join(root, f) for f in files]:
                            await self._chmod_and_chown(
                                p, rule.filemode, chown, task_id)
        else:
            await self._chmod_and_chown(path, rule.filemode, chown, task_id)

    async def task(self, event, task_id):
        path = event.pathname
        match = None
        for rule in self._rules:
            match = rule.src_re.match(path)
            if match:
                break

        if not match:
            self._log.debug(
                f"{task_id}: path '{path}' matches no rule in ruleset")
            return

        try:
            if rule.action in ["copy", "move"]:
                dst = rule.src_re.sub(rule.dst_re, path)
                if not dst:
                    raise RuntimeError(
                        f"{task_id}: unable to {rule.action} '{path}', "
                        f"resulting destination path is empty")

                if os.path.exists(dst):
                    raise RuntimeError(
                        f"{task_id}: unable to move file from '{path} "
                        f"to '{dst}', dstination path exists already")

                dst_dir = os.path.dirname(dst)
                if not os.path.isdir(dst_dir) and rule.auto_create:
                    self._log.info(
                        f"{task_id}: create directory '{dst_dir}'")
                    first_subdir = dst_dir
                    while not os.path.isdir(first_subdir):
                        parent = os.path.dirname(first_subdir)
                        if not os.path.isdir(parent):
                            first_subdir = parent
                        else:
                            break
                    os.makedirs(dst_dir)
                    await self._set_mode_and_owner(first_subdir, rule, task_id)

                self._log.info(
                    f"{task_id}: {rule.action} '{path}' to '{dst}'")
                if rule.action == "copy":
                    if os.path.isdir(path):
                        shutil.copytree(path, dst)
                    else:
                        shutil.copy2(path, dst)

                else:
                    os.rename(path, dst)

                await self._set_mode_and_owner(dst, rule, task_id)

            elif rule.action == "delete":
                self._log.info(
                    f"{task_id}: {rule.action} '{path}'")
                if os.path.isdir(path):
                    if rule.rec:
                        shutil.rmtree(path)
                    else:
                        shutil.rmdir(path)

                else:
                    os.remove(path)

        except RuntimeError as e:
            self._log.error(f"{task_id}: {e}")

        except Exception as e:
            self._log.exception(f"{task_id}: {e}")


class PyinotifydConfig:
    def __init__(self, watches=[], loglevel=logging.INFO, shutdown_timeout=30):
        if not isinstance(watches, list):
            watches = [watches]

        self.set_watches(watches)

        assert isinstance(loglevel, int), \
            f"loglevel: expected {type(int)}, got {type(loglevel)}"
        self.loglevel = loglevel

        assert isinstance(shutdown_timeout, int), \
            f"shutdown_timeout: expected {type(int)}, " \
            f"got {type(shutdown_timeout)}"
        self.shutdown_timeout = shutdown_timeout

    def add_watch(self, *args, **kwargs):
        self.watches.append(Watch(*args, **kwargs))

    def set_watches(self, watches):
        self.watches = []
        for watch in watches:
            assert isinstance(watch, Watch), \
                f"watches: expected {type(Watch)}, got {type(watch)}"


async def shutdown(signame, notifiers, logname, timeout=30):
    log = logging.getLogger(logname)

    log.info(f"got signal {signame}, shutdown ...")
    for notifier in notifiers:
        notifier.stop()

    pending = [t for t in asyncio.all_tasks()
               if t is not asyncio.current_task()]
    if len(pending) > 0:
        log.info(
            f"graceful shutdown, waiting {timeout}s "
            f"for remaining tasks to complete")
        try:
            future = asyncio.gather(*pending)
            await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            log.warning(
                "forcefully terminate remaining tasks")
            future.cancel()
            future.exception()

    log.info("shutdown")
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
        help=f"path to config file (defaults to /etc/{myname}/config.py)",
        default=f"/etc/{myname}/config.py")
    parser.add_argument(
        "-d",
        "--debug",
        help="log debugging messages",
        action="store_true")
    parser.add_argument(
        "-e",
        "--events",
        help="show event types and exit",
        action="store_true")
    parser.add_argument(
        "-v",
        "--version",
        help="show version and exit",
        action="store_true")
    args = parser.parse_args()

    if args.version:
        print(f"{myname} ({__version__})")
        sys.exit(0)
    elif args.events:
        types = "\n".join(EventMap.flags.keys())
        print(types)
        sys.exit(0)

    log = logging.getLogger(myname)

    try:
        cfg = {}
        with open(args.config, "r") as c:
            exec(c.read(), globals(), cfg)
        cfg = cfg[f"{myname}_config"]
        assert isinstance(cfg, PyinotifydConfig), \
            f"{myname}_config: expected {type(PyinotifydConfig)}, " \
            f"got {type(cfg)}"
    except Exception as e:
        log.exception(f"error in config file: {e}")
        sys.exit(1)

    console = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console.setFormatter(formatter)

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = cfg.loglevel

    root_logger = logging.getLogger()
    root_logger.setLevel(loglevel)
    root_logger.addHandler(console)

    wm = pyinotify.WatchManager()
    loop = asyncio.get_event_loop()
    notifiers = []
    for watch in cfg.watches:
        log.info(f"start watching '{watch.path}'")
        notifiers.append(watch.event_notifier(wm, loop))

    for signame in ["SIGINT", "SIGTERM"]:
        loop.add_signal_handler(
            getattr(signal, signame),
            lambda: asyncio.ensure_future(
                shutdown(
                    signame, notifiers, myname, timeout=cfg.shutdown_timeout)))

    loop.run_forever()
    loop.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
