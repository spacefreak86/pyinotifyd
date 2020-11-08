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
    "TaskScheduler",
    "Cancel",
    "ShellScheduler",
    "FileManagerRule",
    "FileManagerScheduler"]

import asyncio
import logging
import os
import re
import shutil

from dataclasses import dataclass
from inspect import iscoroutinefunction
from shlex import quote as shell_quote
from uuid import uuid4


def _event_to_str(event):
    return f"maskname={event.maskname}, pathname={event.pathname}"


class TaskScheduler:

    @dataclass
    class TaskState:
        id: str = str(uuid4())
        task: asyncio.Task = None
        cancelable: bool = True


    def __init__(self, job, files=True, dirs=False, delay=0, logname="sched"):
        assert iscoroutinefunction(job), \
            f"job: expected coroutine, got {type(job)}"
        assert isinstance(files, bool), \
            f"files: expected {type(bool)}, got {type(files)}"
        assert isinstance(dirs, bool), \
            f"dirs: expected {type(bool)}, got {type(dirs)}"
        assert isinstance(delay, int), \
            f"delay: expected {type(int)}, got {type(delay)}"

        self._job = job
        self._files = files
        self._dirs = dirs
        self._delay = delay
        self._log = logging.getLogger((logname or __name__))

        self._tasks = {}

    def cancel(self, event):
        try:
            task_state = self._tasks[event.pathname]
        except KeyError:
            return

        if task_state.cancelable:
            task_state.task.cancel()
            self._log.info(
                f"scheduled task cancelled ({_event_to_str(event)}, "
                f"task_id={task_state.id})")
            task_state.task = None
            del self._tasks[event.pathname]
        else:
            self.log.warning(
                f"skip ({_event_to_str(event)}) due to an ongoing task "
                f"(task_id={task_state.id})")

    async def start(self, event):
        if not ((not event.dir and self._files) or
                (event.dir and self._dirs)):
            return

        prefix = ""
        try:
            task_state = self._tasks[event.pathname]
            if task_state.cancelable:
                task_state.task.cancel()
                prefix = "re"
            else:
                self.log.warning(
                    f"skip ({_event_to_str(event)}) due to an ongoing task "
                    f"(task_id={task_state.id})")
                return

        except KeyError:
            task_state = TaskScheduler.TaskState()
            self._tasks[event.pathname] = task_state

        if self._delay > 0:
            task_state.task = asyncio.create_task(
                asyncio.sleep(self._delay))

            try:
                self._log.info(
                    f"{prefix}schedule task ({_event_to_str(event)}, "
                    f"task_id={task_state.id}, delay={self._delay})")
                await task_state.task
            except asyncio.CancelledError:
                return

        task_state.task = asyncio.create_task(
            self._job(event, task_state.id))

        self._log.info(
            f"start task ({_event_to_str(event)}, task_id={task_state.id})")

        try:
            task_state.cancelable = False
            await task_state.task
        except asyncio.CancelledError:
            self._log.warning(
                f"ongoing task cancelled ({_event_to_str(event)}, "
                f"task_id={task_state.id})")
        else:
            self._log.info(
                f"task finished ({_event_to_str(event)}, "
                f"task_id={task_state.id})")
        finally:
            del self._tasks[event.pathname]


class Cancel(TaskScheduler):
    def __init__(self, task):
        assert issubclass(type(task), TaskScheduler), \
            f"task: expected {type(TaskScheduler)}, got {type(task)}"
        self._task = task

    async def start(self, event):
        self._task.cancel(event)


class ShellScheduler(TaskScheduler):
    def __init__(self, cmd, job=None, *args, **kwargs):
        super().__init__(*args, **kwargs, job=self._shell_job)

        assert isinstance(cmd, str), \
            f"cmd: expected {type('')}, got {type(cmd)}"

        self._cmd = cmd

    async def _shell_job(self, event, task_id):
        maskname = event.maskname.split("|", 1)[0]
        if hasattr(event, "src_pathname"):
            src_pathname = event.src_pathname
        else:
            src_pathname = ""

        cmd = self._cmd.replace("{maskname}", shell_quote(maskname)).replace(
            "{pathname}", shell_quote(event.pathname)).replace(
                "{src_pathname}", shell_quote(src_pathname))

        self._log.info(f"{task_id}: execute shell command: {cmd}")
        try:
            proc = await asyncio.create_subprocess_shell(cmd)
            await proc.communicate()
        except Exception as e:
            self._log.error(f"{task_id}: {e}")


class FileManagerRule:
    valid_actions = ["copy", "move", "delete"]

    def __init__(self, action, src_re, dst_re="", auto_create=False,
                 dirmode=None, filemode=None, user=None, group=None,
                 rec=False):
        valid = f"{', '.join(FileManagerRule.valid_actions)}"
        assert action in self.valid_actions, \
            f"action: expected [{valid}], got{action}"
        assert isinstance(src_re, str), \
            f"src_re: expected {type('')}, got {type(src_re)}"
        assert isinstance(dst_re, str), \
            f"dst_re: expected {type('')}, got {type(dst_re)}"
        assert isinstance(auto_create, bool), \
            f"auto_create: expected {type(bool)}, got {type(auto_create)}"
        assert dirmode is None or isinstance(dirmode, int), \
            f"dirmode: expected {type(int)}, got {type(dirmode)}"
        assert filemode is None or isinstance(filemode, int), \
            f"filemode: expected {type(int)}, got {type(filemode)}"
        assert user is None or isinstance(user, str), \
            f"user: expected {type('')}, got {type(user)}"
        assert group is None or isinstance(group, str), \
            f"group: expected {type('')}, got {type(group)}"
        assert isinstance(rec, bool), \
            f"rec: expected {type(bool)}, got {type(rec)}"

        self.action = action
        self.src_re = re.compile(src_re)
        self.dst_re = dst_re
        self.auto_create = auto_create
        self.dirmode = dirmode
        self.filemode = filemode
        self.user = user
        self.group = group
        self.rec = rec


class FileManagerScheduler(TaskScheduler):
    def __init__(self, rules, job=None, *args, **kwargs):
        super().__init__(*args, **kwargs, job=self._manager_job)

        if not isinstance(rules, list):
            rules = [rules]

        for rule in rules:
            assert isinstance(rule, FileManagerRule), \
                f"rules: expected {type(FileManagerRule)}, got {type(rule)}"

        self._rules = rules

    def _get_rule_by_event(self, event):
        rule = None
        for r in self._rules:
            if r.src_re.match(event.pathname):
                rule = r
                break

        return rule

    async def start(self, event):
        if self._get_rule_by_event(event):
            await super().start(event)
        else:
            self._log.debug(
                f"no rule in ruleset matches path '{event.pathname}'")

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

        if os.path.isdir(path):
            mode = rule.dirmode
        else:
            mode = rule.filemode

        await self._chmod_and_chown(path, mode, chown, task_id)

        if not os.path.isdir(path):
            return

        work_on_dirs = not (rule.dirmode is chown is None)
        work_on_files = not (rule.filemode is chown is None)

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

    async def _manager_job(self, event, task_id):
        rule = self._get_rule_by_event(event)
        if not rule:
            return

        try:
            path = event.pathname
            if rule.action in ["copy", "move"]:
                dst = rule.src_re.sub(rule.dst_re, path)
                if not dst:
                    raise RuntimeError(
                        f"unable to {rule.action} '{path}', "
                        f"resulting destination path is empty")

                if os.path.exists(dst):
                    raise RuntimeError(
                        f"unable to move file from '{path} "
                        f"to '{dst}', destination path exists already")

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

                    try:
                        os.makedirs(dst_dir)
                        await self._set_mode_and_owner(
                            first_subdir, rule, task_id)
                    except Exception as e:
                        raise RuntimeError(e)

                self._log.info(
                    f"{task_id}: {rule.action} '{path}' to '{dst}'")

                try:
                    if rule.action == "copy":
                        if os.path.isdir(path):
                            shutil.copytree(path, dst)
                        else:
                            shutil.copy2(path, dst)

                    else:
                        os.rename(path, dst)

                    await self._set_mode_and_owner(dst, rule, task_id)
                except Exception as e:
                    raise RuntimeError(e)

            elif rule.action == "delete":
                self._log.info(
                    f"{task_id}: {rule.action} '{path}'")
                try:
                    if os.path.isdir(path):
                        if rule.rec:
                            shutil.rmtree(path)
                        else:
                            shutil.rmdir(path)

                    else:
                        os.remove(path)
                except Exception as e:
                    raise RuntimeError(e)

        except RuntimeError as e:
            self._log.error(f"{task_id}: {e}")

        except Exception as e:
            self._log.exception(f"{task_id}: {e}")
