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
            self._log.info(
                f"received event {maskname} on '{path}', "
                f"re-schedule task {task.task_id} (delay={self._delay}s)")
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
            self._log.info(
                f"received event {maskname} on '{path}', "
                f"cancel scheduled task {task.task_id}")
            task.cancel()
            del self._tasks[path]


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
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()
