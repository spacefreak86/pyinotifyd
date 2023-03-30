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

from inspect import iscoroutinefunction
from shlex import quote as shell_quote
from uuid import uuid4


class SchedulerLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        if "event" in self.extra:
            event = self.extra["event"]
            msg = f"{msg}, mask={event.maskname}, path={event.pathname}"

        if "id" in self.extra:
            task_id = self.extra["id"]
            msg = f"{msg}, task_id={task_id}"

        return msg, kwargs


class TaskScheduler:

    class TaskState:
        def __init__(self, task_id=None, task=None, cancelable=True):
            self.id = task_id or str(uuid4())
            self.task = task
            self.cancelable = cancelable

    def __init__(self, job, files=True, dirs=False, delay=0, logname="sched",
                 global_vars={}, singlejob=False):
        assert iscoroutinefunction(job), \
            f"job: expected coroutine, got {type(job)}"
        assert isinstance(files, bool), \
            f"files: expected {type(bool)}, got {type(files)}"
        assert isinstance(dirs, bool), \
            f"dirs: expected {type(bool)}, got {type(dirs)}"
        assert isinstance(delay, int), \
            f"delay: expected {type(int)}, got {type(delay)}"
        assert isinstance(global_vars, dict), \
            f"global_vars: expected {type(dict)}, got {type(global_vars)}"

        self._job = job
        self._files = files
        self._dirs = dirs
        self._delay = delay
        self._log = logging.getLogger((logname or __name__))
        self._globals = global_vars
        self._singlejob = singlejob
        self._tasks = {}
        self._pause = False

    def pause(self):
        self._log.info("pause scheduler")
        self._pause = True

    async def shutdown(self, timeout=None):
        self._pause = True
        pending = [t.task for t in self._tasks.values()]
        if pending:
            if timeout is None:
                self._log.info(
                    f"wait for {len(pending)} "
                    f"remaining task(s) to complete")
            else:
                self._log.info(
                    f"wait {timeout} seconds for {len(pending)} "
                    f"remaining task(s) to complete")
            done, pending = await asyncio.wait([*pending], timeout=timeout)
            if pending:
                self._log.warning(
                    f"shutdown timeout exceeded, "
                    f"cancel {len(pending)} remaining task(s)")
                for task in pending:
                    task.cancel()
                try:
                    await asyncio.gather(*pending)
                except asyncio.CancelledError:
                    pass
            else:
                self._log.info("all remainig tasks completed")

    def taskindex(self, event):
        return "singlejob" if self._singlejob else event.pathname

    async def _run_job(self, event, task_state, restart=False):
        logger = SchedulerLogger(self._log, {
            "event": event,
            "id": task_state.id})

        if self._delay > 0:
            task_state.task = asyncio.create_task(
                asyncio.sleep(self._delay))
            try:
                if restart:
                    prefix = "re-"
                else:
                    prefix = ""

                logger.info(f"{prefix}schedule task, delay={self._delay}")

                await task_state.task
            except asyncio.CancelledError:
                return

        logger.info("start task")
        if self._globals:
            local_vars = {"self": self,
                          "event": event,
                          "task_id": task_state.id}
            task_state.task = asyncio.create_task(
                eval("self._job(event, task_id)", self._globals, local_vars))

        else:
            task_state.task = asyncio.create_task(
                self._job(event, task_state.id))

        try:
            task_state.cancelable = False
            await task_state.task
        except asyncio.CancelledError:
            logger.warning("ongoing task cancelled")
        else:
            logger.info("task finished")
        finally:
            task_index = self.taskindex(event)
            del self._tasks[task_index]

    async def process_event(self, event):
        if not ((not event.dir and self._files) or
                (event.dir and self._dirs)):
            return

        restart = False
        task_index = self.taskindex(event)
        try:
            task_state = self._tasks[task_index]
        except KeyError:
            task_state = TaskScheduler.TaskState()
            self._tasks[task_index] = task_state
        else:
            logger = SchedulerLogger(self._log, {
                "event": event,
                "id": task_state.id})

            if task_state.cancelable:
                task_state.task.cancel()
                if not self._pause:
                    restart = True
                else:
                    logger.info("scheduled task cancelled")

            else:
                logger.warning("skip event due to ongoing task")
                return

        if not self._pause:
            await self._run_job(event, task_state, restart)

    async def process_cancel_event(self, event):
        try:
            task_index = self.taskindex(event)
            task_state = self._tasks[task_index]
        except KeyError:
            return

        logger = SchedulerLogger(self._log, {
            "event": event,
            "id": task_state.id})

        if task_state.cancelable:
            task_state.task.cancel()
            logger.info("scheduled task cancelled")
            task_state.task = None
            logger.info(f"{task_index}")
            del self._tasks[task_index]
        else:
            logger.warning("skip event due to ongoing task")


class Cancel:
    def __init__(self, task, *args, **kwargs):
        assert issubclass(type(task), TaskScheduler), \
            f"task: expected {type(TaskScheduler)}, got {type(task)}"

        setattr(self, "process_event", task.process_cancel_event)

    def pause(self):
        pass

    async def shutdown(self, timeout=None):
        pass


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

        logger = SchedulerLogger(self._log, {
            "event": event,
            "id": task_id})

        logger.info(f"execute shell command, cmd={cmd}")
        try:
            proc = await asyncio.create_subprocess_shell(cmd)
            await proc.communicate()
        except Exception as e:
            logger.error(e)


class FileManagerRule:
    valid_actions = ["copy", "move", "delete"]

    def __init__(self, action, src_re, dst_re="", auto_create=False,
                 overwrite=False, dirmode=None, filemode=None, user=None,
                 group=None, rec=False):
        valid = f"{', '.join(FileManagerRule.valid_actions)}"
        assert action in self.valid_actions, \
            f"action: expected [{valid}], got{action}"
        assert isinstance(src_re, str), \
            f"src_re: expected {type('')}, got {type(src_re)}"
        assert isinstance(dst_re, str), \
            f"dst_re: expected {type('')}, got {type(dst_re)}"
        assert isinstance(auto_create, bool), \
            f"auto_create: expected {type(bool)}, got {type(auto_create)}"
        assert isinstance(overwrite, bool), \
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
        self.overwrite = overwrite
        self.dirmode = dirmode
        self.filemode = filemode
        self.user = user
        self.group = group
        self.rec = rec


class FileManagerScheduler(TaskScheduler):
    def __init__(self, rules, job=None, *args, **kwargs):
        super().__init__(
            *args, **kwargs, job=self._manager_job, singlejob=False)

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

    async def process_event(self, event):
        if not ((not event.dir and self._files) or
                (event.dir and self._dirs)):
            return

        if self._get_rule_by_event(event):
            await super().process_event(event)
        else:
            logger = SchedulerLogger(self._log, {"event": event})
            logger.debug("no rule in ruleset matches")

    async def _chmod_and_chown(self, path, mode, chown, logger=None):
        logger = (logger or self._log)

        if mode is not None:
            logger.debug(f"chmod {oct(mode)}")
            os.chmod(path, mode)

        if chown is not None:
            changes = ""
            if chown[0] is not None:
                changes = chown[0]

            if chown[1] is not None:
                changes = f"{changes}:{chown[1]}"

            logger.debug(f"chown {changes}")
            shutil.chown(path, *chown)

    async def _set_mode_and_owner(self, path, rule, logger=None):
        logger = (logger or self._log)

        if (rule.user is rule.group is None):
            chown = None
        else:
            chown = (rule.user, rule.group)

        if os.path.isdir(path):
            mode = rule.dirmode
        else:
            mode = rule.filemode

        await self._chmod_and_chown(path, mode, chown, logger)

        if not os.path.isdir(path):
            return

        work_on_dirs = not (rule.dirmode is chown is None)
        work_on_files = not (rule.filemode is chown is None)

        if work_on_dirs or work_on_files:
            for root, dirs, files in os.walk(path):
                if work_on_dirs:
                    for p in [os.path.join(root, d) for d in dirs]:
                        await self._chmod_and_chown(
                            p, rule.dirmode, chown, logger)

                if work_on_files:
                    for p in [os.path.join(root, f) for f in files]:
                        await self._chmod_and_chown(
                            p, rule.filemode, chown, logger)

    async def _manager_job(self, event, task_id):
        rule = self._get_rule_by_event(event)
        if not rule:
            return

        logger = SchedulerLogger(self._log, {"id": task_id})

        try:
            path = event.pathname
            if rule.action in ["copy", "move"]:
                dst = rule.src_re.sub(rule.dst_re, path)
                if not dst:
                    raise RuntimeError(
                        f"unable to {rule.action} '{path}', "
                        f"resulting destination path is empty")

                if os.path.exists(dst) and not rule.overwrite:
                    raise RuntimeError(
                        f"unable to {rule.action} file from '{path} "
                        f"to '{dst}', path already exists")

                dst_dir = os.path.dirname(dst)
                if not os.path.isdir(dst_dir) and rule.auto_create:
                    logger.info(f"create directory '{dst_dir}'")
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
                            first_subdir, rule, logger)
                    except Exception as e:
                        raise RuntimeError(e)

                logger.info(f"{rule.action} '{path}' to '{dst}'")

                try:
                    if rule.action == "copy":
                        if os.path.isdir(path):
                            shutil.copytree(path, dst)
                        else:
                            shutil.copy2(path, dst)

                    else:
                        os.rename(path, dst)

                    await self._set_mode_and_owner(dst, rule, logger)
                except Exception as e:
                    raise RuntimeError(e)

            elif rule.action == "delete":
                logger.info(f"{rule.action} '{path}'")
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
            logger.error(e)

        except Exception as e:
            logger.exception(e)
