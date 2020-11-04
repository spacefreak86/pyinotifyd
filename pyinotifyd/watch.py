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

import asyncio
import pyinotify


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


class _TaskList:
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

    def event_notifier(self, wm, loop=asyncio.get_event_loop()):
        handler = pyinotify.ProcessEvent()
        mask = False
        for flag, values in self.event_map.items():
            setattr(handler, f"process_{flag}", _TaskList(values).execute)
            if mask:
                mask = mask | EventMap.flags[flag]
            else:
                mask = EventMap.flags[flag]

        wm.add_watch(
            self.path, mask, rec=self.rec, auto_add=self.auto_add,
            do_glob=True)

        return pyinotify.AsyncioNotifier(wm, loop, default_proc_fun=handler)
