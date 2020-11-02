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
    def __init__(self, event, delay, task_id, job, callback=None,
                 logname="Task"):
        self._event = event
        self._path = event.pathname
        self._delay = delay
        self.task_id = task_id
        self._task = None
        self._job = job
        self._callback = callback
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


class TaskScheduler:
    def __init__(self, job, delay=0, files=True, dirs=False,
                 logname="TaskScheduler"):
        assert callable(job), f"job: expected callable, got {type(job)}"
        self._job = job
        assert isinstance(delay, int), f"delay: expected {type(int)}, got {type(delay)}"
        self._delay = delay
        assert isinstance(files, bool), f"files: expected {type(bool)}, got {type(files)}"
        self._files = files
        assert isinstance(dirs, bool), f"dirs: expected {type(bool)}, got {type(dirs)}"
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
                event, self._delay, task_id=task_id, job=self._job,
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
    def __init__(self, cmd, job=None, logname="ShellScheduler",
                 *args, **kwargs):
        assert isinstance(cmd, str), f"cmd: expected {type('')}, got {type(cmd)}"
        self._cmd = cmd
        super().__init__(*args, job=self.job, logname=logname, **kwargs)

    async def job(self, event, task_id):
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


class FileManager:
    def __init__(self, rules, auto_create=True, rec=False,
                 logname="FileManager"):
        self._rules = []
        if not isinstance(rules, list):
            rules = [rules]

        for rule in rules:
            if rule["action"] in ["copy", "move"]:
                self._rules.append((rule["action"],
                                    re.compile(rule["src_re"]),
                                    rule["dst_re"]))
            elif rule["action"] == "delete":
                self._rules.append(
                    (rule["action"], re.compile(rule["src_re"])))
            else:
                raise ValueError(f"invalid action type: {rule['action']}")

        self._auto_create = auto_create
        self._rec = rec
        self._log = logging.getLogger(logname)

    async def job(self, event, task_id):
        path = event.pathname
        match = None
        for rule in self._rules:
            src_re = rule[1]
            match = src_re.match(path)
            if match:
                break

        if match is not None:
            action = rule[0]
            try:
                if action in ["copy", "move"]:
                    dst_re = rule[2]
                    dest = src_re.sub(dst_re, path)
                    dest_dir = os.path.dirname(dest)
                    if not os.path.isdir(dest_dir) and self._auto_create:
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

                elif action == "delete":
                    self._log.info(
                        f"{task_id}: {action} '{path}'")
                    if os.path.isdir(path):
                        if self._rec:
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


class ExecList:
    def __init__(self):
        self._list = []

    def add(self, func):
        self._list.append(func)

    def remove(self, func):
        self._list.remove(func)

    def run(self, event):
        for func in self._list:
            func(event)


def add_mask(new_mask, current_mask=False):
    if not current_mask:
        return new_mask
    else:
        return current_mask | new_mask


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

    cfg = {"watches": [],
           "loglevel": logging.INFO,
           "shutdown_timeout": 30}

    try:
        cfg_vars = {"pyinotifyd_config": cfg}
        with open(args.config, "r") as c:
            exec(c.read(), globals(), cfg_vars)

        cfg.update(cfg_vars["pyinotifyd_config"])
    except Exception as e:
        print(f"error in config file: {e}")
        sys.exit(1)

    console = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console.setFormatter(formatter)

    if args.debug:
        cfg["loglevel"] = logging.DEBUG

    root_logger = logging.getLogger()
    root_logger.setLevel(cfg["loglevel"])
    root_logger.addHandler(console)

    watchable_flags = pyinotify.EventsCodes.OP_FLAGS
    watchable_flags.update(pyinotify.EventsCodes.EVENT_FLAGS)

    wm = pyinotify.WatchManager()
    loop = asyncio.get_event_loop()
    notifiers = []
    for watchcfg in cfg["watches"]:
        watch = {"path": "",
                 "rec": False,
                 "auto_add": False,
                 "event_map": {}}
        watch.update(watchcfg)
        if not watch["path"]:
            continue

        mask = False
        handler = pyinotify.ProcessEvent()
        for flag, values in watch["event_map"].items():
            if flag not in watchable_flags or values is None:
                continue

            if not isinstance(values, list):
                values = [values]

            mask = add_mask(pyinotify.EventsCodes.ALL_FLAGS[flag], mask)
            exec_list = ExecList()
            for value in values:
                assert callable(value), \
                    f"event_map['{flag}']: expected callable, " \
                    f"got {type(value)}"
                exec_list.add(value)

            setattr(handler, f"process_{flag}", exec_list.run)

        logging.info(f"start watching {watch['path']}")
        wm.add_watch(
            watch["path"], mask, rec=watch["rec"], auto_add=watch["auto_add"],
            do_glob=True)
        notifiers.append(pyinotify.AsyncioNotifier(
            wm, loop, default_proc_fun=handler))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    for notifier in notifiers:
        notifier.stop()

    loop.run_until_complete(shutdown(timeout=cfg["shutdown_timeout"]))
    loop.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
