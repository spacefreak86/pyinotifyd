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

import asyncio
import logging
import os
import re
import shutil

from shlex import quote as shell_quote
from uuid import uuid4


class _Task:
    def __init__(self, event, delay, task_id, task, callback=None,
                 logname="task"):
        self._event = event
        self._path = event.pathname
        self._delay = delay
        self._task_id = task_id
        self._job = task
        self._callback = callback

        self._task = None
        self._log = logging.getLogger((logname or __name__))

    async def _start(self):
        if self._delay > 0:
            try:
                await asyncio.sleep(self._delay)
            except asyncio.CancelledError:
                return

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

    def task_id(self):
        return self._task_id


class TaskScheduler:
    def __init__(self, task, files, dirs, delay=0, logname="sched"):
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
        self._logname = (logname or __name__)
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
            task_id = task.task_id()
            self._log.info(
                f"received event {maskname} on '{path}', "
                f"re-schedule task {task_id} (delay={self._delay}s)")
            task.restart()
        else:
            task_id = str(uuid4())
            self._log.info(
                f"received event {maskname} on '{path}', "
                f"schedule task {task_id} (delay={self._delay}s)")
            task = _Task(
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
            task_id = task.task_id()
            self._log.info(
                f"received event {maskname} on '{path}', "
                f"cancel scheduled task {task_id}")
            task.cancel()
            del self._tasks[path]

    def log(self, event):
        self._log.info(f"LOG: received {event}")


class ShellScheduler(TaskScheduler):
    def __init__(self, cmd, task=None, *args, **kwargs):
        assert isinstance(cmd, str), \
            f"cmd: expected {type('')}, got {type(cmd)}"
        self._cmd = cmd

        super().__init__(*args, task=self.task, **kwargs)

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
        proc = await asyncio.shield(asyncio.create_subprocess_shell(cmd))
        await asyncio.shield(proc.communicate())


class FileManagerRule:
    valid_actions = ["copy", "move", "delete"]

    def __init__(self, action, src_re, dst_re="", auto_create=False,
                 dirmode=None, filemode=None, user=None, group=None,
                 rec=False):
        valid = f"{', '.join(FileManagerRule.valid_actions)}"
        assert action in self.valid_actions, \
            f"action: expected [{valid}], got{action}"
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


class FileManagerScheduler(TaskScheduler):
    def __init__(self, rules, task=None, *args, **kwargs):
        if not isinstance(rules, list):
            rules = [rules]

        for rule in rules:
            assert isinstance(rule, FileManagerRule), \
                f"rules: expected {type(FileManagerRule)}, got {type(rule)}"
        self._rules = rules

        super().__init__(*args, task=self.task, **kwargs)

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

        if os.path.isidr(path):
            mode = rule.dirmode
        else:
            mode = rule.filemode

        await asyncio.shield(
            self._chmod_and_chown(path, mode, chown, task_id))

        if not os.path.isdir(path):
            return

        work_on_dirs = not (rule.dirmode is chown is None)
        work_on_files = not (rule.filemode is chown is None)

        if work_on_dirs or work_on_files:
            for root, dirs, files in os.walk(path):
                if work_on_dirs:
                    for p in [os.path.join(root, d) for d in dirs]:
                        await asyncio.shield(
                            self._chmod_and_chown(
                                p, rule.dirmode, chown, task_id))

                if work_on_files:
                    for p in [os.path.join(root, f) for f in files]:
                        await asyncio.shield(
                            self._chmod_and_chown(
                                p, rule.filemode, chown, task_id))

    def _get_rule_by_event(self, event):
        rule = None
        for r in self._rules:
            if r.src_re.match(event.pathname):
                rule = r
                break

        return rule

    def schedule(self, event):
        if self._get_rule_by_event(event):
            super().schedule(event)
        else:
            self._log.debug(
                f"no rule in ruleset matches path '{event.pathname}'")

    async def task(self, event, task_id):
        path = event.pathname
        rule = self._get_rule_by_event(event)

        if not rule:
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
                    await asyncio.shield(
                        self._set_mode_and_owner(first_subdir, rule, task_id))

                self._log.info(
                    f"{task_id}: {rule.action} '{path}' to '{dst}'")
                if rule.action == "copy":
                    if os.path.isdir(path):
                        shutil.copytree(path, dst)
                    else:
                        shutil.copy2(path, dst)

                else:
                    os.rename(path, dst)

                await asyncio.shield(
                    self._set_mode_and_owner(dst, rule, task_id))

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
