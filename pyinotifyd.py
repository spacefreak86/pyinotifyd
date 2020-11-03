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
import sys

from shlex import quote as shell_quote
from uuid import uuid4

__version__ = "0.0.1"


class Task:
    def __init__(self, event, delay, task_id, task, callback=None,
                 logname="Task"):
        self._event = event
        self._path = event.pathname
        self._delay = delay
        self.task_id = task_id
        self._job = task
        self._callback = callback
        self._task = None
        self._log = logging.getLogger(logname)

    async def _start(self):
        if self._delay > 0:
            await asyncio.sleep(self._delay)

        if self._callback is not None:
            self._callback(self._event)
        self._task = None
        self._log.info(f"execute task {self.task_id}")
        await asyncio.shield(self._job(self._event, self.task_id))
        self._log.info(f"task {self.task_id} finished")

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
    def __init__(self, task, files, dirs, delay=0,
                 logname="TaskScheduler"):
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
        self._log = logging.getLogger(logname)

    def _task_started(self, event):
        path = event.pathname
        if path in self._tasks:
            del self._tasks[path]

    def schedule(self, event):
        self._log.debug(f"received {event}")
        path = event.pathname
        maskname = event.maskname.split("|", 1)[0]
        if (not event.dir and not self._files) or \
                (event.dir and not self._dirs):
            return

        if path in self._tasks:
            task = self._tasks[path]
            self._log.info(f"received event {maskname} on '{path}', "
                           f"re-schedule task {task.task_id} "
                           f"(delay={self._delay}s)")
            task.restart()
        else:
            task_id = str(uuid4())
            self._log.info(
                f"received event {maskname} on '{path}', "
                f"schedule task {task_id} (delay={self._delay}s)")
            task = Task(
                event, self._delay, task_id, self._task,
                callback=self._task_started)
            self._tasks[path] = task
            task.start()

    def cancel(self, event):
        self._log.debug(f"received {event}")
        path = event.pathname
        maskname = event.maskname.split("|", 1)[0]
        if path in self._tasks:
            task = self._tasks[path]
            self._log.info(f"received event {maskname} on '{path}', "
                           f"cancel scheduled task {task.task_id}")
            task.cancel()
            del self._tasks[path]


class ShellScheduler(TaskScheduler):
    def __init__(self, cmd, task=None, logname="ShellScheduler",
                 *args, **kwargs):
        assert isinstance(cmd, str), \
            f"cmd: expected {type('')}, got {type(cmd)}"
        self._cmd = cmd
        super().__init__(*args, task=self.task, logname=logname, **kwargs)

    async def task(self, event, task_id):
        maskname = event.maskname.split("|", 1)[0]
        cmd = self._cmd
        cmd = cmd.replace("{maskname}", shell_quote(maskname))
        cmd = cmd.replace("{pathname}", shell_quote(event.pathname))
        if hasattr(event, "src_pathname"):
            src_pathname = event.src_pathname
        else:
            src_pathname = ""

        cmd = cmd.replace(
            "{src_pathname}", shell_quote(src_pathname))
        self._log.info(f"{task_id}: execute shell command: {cmd}")
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()


class EventMap:
    flags = {**pyinotify.EventsCodes.OP_FLAGS,
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

    def get(self):
        return self._map

    def set(self, flag, values):
        assert flag in EventMap.flags, \
            f"event_map: invalid flag: {flag}"
        if values is None:
            if flag in self._map:
                del self._map[flag]
        else:
            if not isinstance(values, list):
                values = [values]

            for value in values:
                assert callable(value), \
                    f"event_map: {flag}: expected callable, got {type(value)}"

            self._map[flag] = values


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
        for flag, values in self.event_map.get().items():
            setattr(handler, f"process_{flag}", TaskList(values).execute)
            if not mask:
                mask = EventMap.flags[flag]
            else:
                mask = mask | EventMap.flags[flag]

        wm.add_watch(self.path, mask, rec=self.rec, auto_add=self.auto_add,
                     do_glob=True)
        return pyinotify.AsyncioNotifier(wm, loop, default_proc_fun=handler)


class Rule:
    valid_actions = ["copy", "move", "delete"]

    def __init__(self, action, src_re, dst_re="", auto_create=False,
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
        assert isinstance(rec, bool), \
            f"rec: expected {type(bool)}, got {type(rec)}"
        self.rec = rec


class FileManager:
    def __init__(self, rules, logname="FileManager"):
        if not isinstance(rules, list):
            rules = [rules]

        for rule in rules:
            assert isinstance(rule, Rule), \
                f"rules: expected {type(Rule)}, got {type(rule)}"

        self._rules = rules
        self._log = logging.getLogger(logname)

    def add_rule(self, *args, **kwargs):
        self._rules.append(Rule(*args, **kwargs))

    async def task(self, event, task_id):
        path = event.pathname
        match = None
        for rule in self._rules:
            match = rule.src_re.match(path)
            if match:
                break

        if match is not None:
            try:
                if rule.action in ["copy", "move"]:
                    dest = src_re.sub(rule.dst_re, path)
                    dest_dir = os.path.dirname(dest)
                    if not os.path.isdir(dest_dir) and rule.auto_create:
                        self._log.info(
                            f"{task_id}: create directory '{dest_dir}'")
                        os.makedirs(dest_dir)
                    elif os.path.exists(dest):
                        raise RuntimeError(
                            f"unable to move file from '{path} to '{dest}', "
                            f"destination path exists already")

                    self._log.info(
                        f"{task_id}: {action} '{path}' to '{dest}'")
                    if action == "copy":
                        if os.path.isdir(path):
                            shutil.copytree(path, dest)
                        else:
                            shutil.copy2(path, dest)
                    else:
                        os.rename(path, dest)

                elif rule.action == "delete":
                    self._log.info(
                        f"{task_id}: delete '{path}'")
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

        else:
            self._log.warning(f"{task_id}: no rule matches path '{path}'")


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


async def shutdown(timeout=30):
    pending = [t for t in asyncio.all_tasks()
               if t is not asyncio.current_task()]
    if len(pending) > 0:
        logging.info(
            f"graceful shutdown, waiting {timeout}s "
            f"for remaining tasks to complete")
        try:
            future = asyncio.gather(*pending)
            await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            logging.warning(
                "forcefully terminate remaining tasks")
            future.cancel()
            future.exception()

    logging.info("shutdown")


def main():
    parser = argparse.ArgumentParser(
        description="pyinotifyd",
        formatter_class=lambda prog: argparse.HelpFormatter(
            prog, max_help_position=45, width=140))
    parser.add_argument(
        "-c",
        "--config",
        help="path to config file (defaults to /etc/pyinotifyd/config.py)",
        default="/etc/pyinotifyd/config.py")
    parser.add_argument(
        "-d",
        "--debug",
        help="log debugging messages",
        action="store_true")
    parser.add_argument(
        "-v",
        "--version",
        help="show version and exit",
        action="store_true")
    args = parser.parse_args()

    if args.version:
        print(f"pyinotifyd ({__version__})")
        sys.exit(0)

    try:
        cfg = {}
        with open(args.config, "r") as c:
            exec(c.read(), globals(), cfg)
        cfg = cfg["pyinotifyd_config"]
        assert isinstance(cfg, PyinotifydConfig), \
            f"pyinotifyd_config: expected {type(PyinotifydConfig)}, " \
            f"got {type(cfg)}"
    except Exception as e:
        logging.exception(f"error in config file: {e}")
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
        logging.info(f"start watching '{watch.path}'")
        notifiers.append(watch.event_notifier(wm, loop))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    for notifier in notifiers:
        notifier.stop()

    loop.run_until_complete(shutdown(timeout=cfg.shutdown_timeout))
    loop.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
