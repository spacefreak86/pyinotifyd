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

import logging
import os
import re
import shutil


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
    def __init__(self, rules, logname="filemgr"):
        if not isinstance(rules, list):
            rules = [rules]

        for rule in rules:
            assert isinstance(rule, Rule), \
                f"rules: expected {type(Rule)}, got {type(rule)}"

        self._rules = rules
        self._log = logging.getLogger((logname or __name__))

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
