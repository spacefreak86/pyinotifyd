# pyinotifyd
A daemon for monitoring filesystem events with inotify on Linux and run tasks like filesystem operations (copy, move or delete), a shell command or custom async python methods.  

It is possible to schedule tasks with a delay, which can then be canceled again in case a canceling event occurs. A useful example for this is to run tasks only if a file has not changed within a certain amount of time.  

pyinotifyd offers great flexibility through its dev-op configuration approach, which enables you to do almost anything you want.

# Requirements
* [pyinotify](https://github.com/seb-m/pyinotify)

# Installation
```sh
# install pyinotifyd with pip
pip install pyinotifyd

# install service files and config
pyinotifyd --install

# uninstall service files and unmodified config
pyinotifyd --uninstall
```

## Autostart
The following init systems are supported.

### systemd
```sh
# start the daemon at boot time
systemctl enable pyinotifyd.service

# start the daemon immediately
systemctl start pyinotifyd.service
```

### OpenRC (Gentoo)
```sh
# start the daemon at boot time
rc-update add pyinotifyd default

# start the daemon immediately
rc-service pyinotifyd start 
```

# Configuration
The config file **/etc/pyinotifyd/config.py** is written in python syntax. pyinotifyd reads and executes its content, that means you can write your custom async python methods directly into the config file.  
The basic idea is to instantiate one or multiple schedulers and map specific inotify events to schedulers with the help of event maps. Then, watch the given paths for events and run tasks as defined in the event maps.

## Schedulers
pyinotifyd has different schedulers to schedule tasks with an optional delay. The advantages of using a scheduler are consistent logging and the possibility to cancel delayed tasks. Furthermore, schedulers have the ability to differentiate between files and directories.

### TaskScheduler
Schedule a custom python method *job* with an optional *delay* in seconds. Skip scheduling of tasks for files and/or directories according to *files* and *dirs* arguments. If there already is a scheduled task, re-schedule it with *delay*. Use *logname* in log messages. All additional modules, functions and variables that are defined in the config file and are needed within the *job*, need to be passed as dictionary to the TaskManager through *global_vars*. If you want to limit the scheduler to run only one job at a time, set *singlejob* to True.  
All arguments except for *job* are optional.
```python
# Please note that pyinotifyd uses pythons asyncio for asynchronous task execution.
# Do not run anything inside the custom python method that blocks the daemon.
#
# Bad:  time.sleep(10)
# Good: await asyncio.sleep(10)

import asyncio
import logging

async def custom_job(event, task_id):
    await asyncio.sleep(10)
    logging.info(f"{task_id}: execute example task: {event}")

task_sched = TaskScheduler(
    job=custom_job,
    files=True,
    dirs=False,
    delay=0,
    logname="sched",
    global_vars=globals(),
    singlejob=False)
```

### ShellScheduler
Schedule a shell command *cmd*. Replace  **{maskname}**, **{pathname}** and **{src_pathname}** in *cmd* with the actual values of occuring events. This scheduler is based on TaskScheduler and has the same optional arguments.
```python
# Please note that **{src_pathname}** is only present for IN_MOVED_TO events and only
# in the case where the IN_MOVED_FROM events are watched too.
# If it is not present, the command line argument will be an empty string.
shell_sched = ShellScheduler(
    cmd="/usr/local/bin/task.sh {maskname} {pathname} {src_pathname}")
```

### FileManagerScheduler
Move, copy or delete files and/or directories following the list of *rules*, the first matching rule is executed.  
This scheduler is based on TaskScheduler and has the same optional arguments.  

A rule holds an *action* (move, copy or delete) and a regular expression *src_re*. The *action* will be executed if *src_re* matches the path of an event. In case where *action* is copy or move, use *dst_re* as destination path. Subgroups and/or named-subgroups may be used in *src_re* and *dst_re*.  
Automatically create possibly missing sub-directories if *auto_create* is set to True. Set the mode and ownership of moved or copied files/directories and newly created sub-directories to *filemode* and *dirmode*. Override destination files if *override* is set to True.  
If *action* is delete, delete non-empty directories if *rec* is set to True.  
```python
move_rule = FileManagerRule(
    action="move",
    src_re="^/src_path/(?P<path>.*).to_move$",
    dst_re="/dst_path/\g<path>",
    auto_create=False,
    rec=False,
    filemode=None,
    dirmode=None,
    user=None,
    group=None,
    override=False)

delete_rule = FileManagerRule(
    action="delete",
    src_re="^/src_path/(?P<path>.*).to_delete$",
    rec=False)

file_sched = FileManagerScheduler(
    rules=[move_rule, delete_rule])
```

## Event maps
Map specific events to one or multiple schedulers. Ignore the event if the scheduler is set to None. Use **Cancel** to cancel a scheduled task within a scheduler.  
This is an example which schedules tasks for newly created files if they are not modified, moved or deleted within the delay time of the scheduler.
```python
event_map = {
    "IN_ACCESS": None,
    "IN_ATTRIB": None,
    "IN_CLOSE_NOWRITE": None,
    "IN_CLOSE_WRITE": task_sched,
    "IN_CREATE": task_sched,
    "IN_DELETE": Cancel(task_sched),
    "IN_DELETE_SELF": Cancel(task_sched),
    "IN_IGNORED": None,
    "IN_MODIFY": Cancel(task_sched),
    "IN_MOVE_SELF": None,
    "IN_MOVED_FROM": Cancel(task_sched),
    "IN_MOVED_TO": task_sched,
    "IN_OPEN": None,
    "IN_Q_OVERFLOW": None,
    "IN_UNMOUNT": Cancel(task_sched)}

# It is possible to instantiate an event map with a default scheduler set for every event
event_map = EventMap(default_sched=task_sched)
```
The following events are available:
* **IN_ACCESS**: a file was accessed
* **IN_ATTRIB**: a metadata changed
* **IN_CLOSE_NOWRITE**: an unwritable file was closed
* **IN_CLOSE_WRITE**: a writable file was closed
* **IN_CREATE**: a file/directory was created
* **IN_DELETE**: a file/directory was deleted
* **IN_DELETE_SELF**: a watched item itself was deleted
* **IN_IGNORED**: raised when a watch is removed, probably useless for you
* **IN_MODIFY**: a file was modified
* **IN_MOVE_SELF**: a watched item was moved, currently its full pathname destination can only be known if its source and destination directories were both watched. Otherwise, the file is still being watched but you cannot rely anymore on the given path attribute *event.path*
* **IN_MOVED_FROM**: a file/directory in a watched directory was moved from another specified watched directory. Can trace the full move of an item when IN_MOVED_TO is available too, in this case if the moved item is itself watched, its path will be updated (see IN_MOVE_SELF)
* **IN_MOVED_TO**: a file/directory was moved to another specified watched directory (see IN_MOVE_FROM)
* **IN_OPEN**: a file was opened
* **IN_Q_OVERFLOW**: the event queue overflown. This event is not associated with any watch descriptor
* **IN_UNMOUNT**: when backing filesystem was unmounted. Notified to each watch of this filesystem

## Pyinotifyd
pyinotifyd requires you to define a variable called **pyinotifyd** within the config file, which contains an instance of the Pyinotifyd class. Set the optional list of *watches* and the *shutdown_timeout*. Pyinotifyd will wait *shutdown_timeout* seconds for pending tasks to complete before shutdown. Use *logname* in log messages.  
```python
pyinotifyd = Pyinotifyd(
    watches=[],
    shutdown_timeout=30,
    logname="daemon")
```

### Watches
A watch connects the *path* to an *event_map*. Automatically add a watch on each sub-directories in *path* if *rec* is set to True. If *auto_add* is True, a watch will be added automatically on newly created sub-directories in *path*. All events for paths matching one of the regular expressions in *exclude_filter* are ignored. If the value of *exclude_filter* is a string, it is assumed to be a path to a file from which the list of regular expressions will be read.
```python
# Add a watch directly to Pyinotifyd.
pyinotifyd.add_watch(
    path="/src_path",
    event_map=event_map,
    rec=False,
    auto_add=False,
    exclude_filter=["^/src_path/subpath$"])

# Or instantiate and add it
w = Watch(
    path="/src_path",
    event_map=event_map,
    rec=False,
    auto_add=False,
    exclude_filter=["^/src_path/subpath$"])

pyinotifyd.add_watch(watch=w)
```

## Logging
Pythons [logging](https://docs.python.org/3/howto/logging.html) framework is used to log messages (see https://docs.python.org/3/howto/logging.html).  
The following loglevels are available:
* DEBUG
* INFO
* WARNING
* ERROR
* CRITICAL
```python
# Configure global loglevel
setLoglevel(INFO)

# Configure loglevel per logname.
setLoglevel(INFO, logname="daemon")
```

### Syslog
Send log messages to the local syslog server.
```python
# Enable logging to local syslog server (/dev/log).
# Use *address* to specify a different target.
enableSyslog(loglevel=INFO, address="/dev/log")

# Enable syslog per logname
enableSyslog(lglevel=INFO, name="daemon")
```

# Examples

## Schedule python method for all events on files and directories
```python
import logging

async def custom_job(event, task_id):
    logging.info(f"{task_id}: execute example task: {event}")

task_sched = TaskScheduler(
    job=custom_job,
    files=True,
    dirs=True)

event_map = EventMap(
    default_sched=task_sched)

pyinotifyd = Pyinotifyd()
pyinotifyd.add_watch(
	path="/src_path",
	event_map=event_map,
	rec=True,
	auto_add=True)
```

## Schedule shell commands for specific events on files
```python
shell_sched = ShellScheduler(
    cmd="/usr/local/sbin/task.sh {pathname}",
    files=True,
    dirs=False)

event_map = {
    "IN_WRITE_CLOSE": shell_sched}

pyinotifyd = Pyinotifyd()
pyinotifyd.add_watch(
	path="/src_path",
	event_map=event_map,
	rec=True,
	auto_add=True)
```

## Move, copy or delete newly created files after a delay
```python
move_rule = FileManagerRule(
    action="move",
    src_re="^/src_path/(?P<path>.*)\.to_move$",
    dst_re="/dst_path/\g<path>",
    auto_create=True,
    filemode=0o644,
    dirmode=0o755)

copy_rule = FileManagerRule(
    action="copy",
    src_re="^/src_path/(?P<path>.*)\.to_copy$",
    dst_re="/dst_path/\g<path>",
    auto_create=True,
    filemode=0o644,
    dirmode=0o755)

delete_rule = FileManagerRule(
    action="delete",
    src_re="^/src_path/(?P<path>.*)\.to_delete$",
    rec=False)

file_sched = FileManagerScheduler(
    rules=[move_rule, copy_rule, delete_rule],
    delay=60,
    files=True,
    dirs=False)

event_map = {
    "IN_CLOSE_WRITE": file_sched,
    "IN_CREATE": file_sched,
    "IN_DELETE": Cancel(file_sched),
    "IN_DELETE_SELF": Cancel(file_sched),
    "IN_MODIFY": Cancel(file_sched),
    "IN_MOVED_FROM": Cancel(file_sched),
    "IN_MOVED_TO": file_sched,
    "IN_UNMOUNT": Cancel(file_sched)}

# Please note that the shutdown timeout should be greater than the greatest scheduler delay,
# otherwise pending tasks may get cancelled during shutdown.
pyinotifyd = Pyinotifyd(shutdown_timeout=35)
pyinotifyd.add_watch(
	path="/src_path",
	event_map=event_map,
	rec=True,
	auto_add=True)
```
