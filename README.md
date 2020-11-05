# pyinotifyd
A daemon to monitore filesystems events with inotify on Linux and execute tasks (Python methods or Shell commands) with an optional delay. It is also possible to cancel delayed tasks.

## Requirements
* [pyinotify](https://github.com/seb-m/pyinotify)

## Installation
```sh
# install pyinotifyd with pip
pip install pyinotifyd

# install systemd service and create config directory
pyinotifyd --install

# uninstall systemd service
pyinotifyd --uninstall
```

### Autostart
The following init systems are supported.

#### systemd
```sh
# start the daemon at boot time
systemctl enable pyinotifyd.service

# start the daemon immediately
systemctl start pyinotifyd.service
```

#### OpenRC (Gentoo)
```sh
# start the daemon at boot time
rc-update add pyinotifyd default

# start the daemon immediately
rc-service pyinotifyd start 
```

## Configuration
The config file **/etc/pyinotifyd/config.py** is written in Python syntax. pyinotifyd reads and executes its content, that means you can add your custom Python code to the config file.

### Tasks
Tasks are Python methods that are called in case an event occurs. They can be bound directly to an event type in an event map. Although this is the easiest and quickest way, it is usually better to add a task to a scheduler and bind the scheduler to event types.

#### Simple
This is a very basic example task that just logs each event and task_id:
```python
async def task(event, task_id):
    logging.info(f"{task_id}: execute example task: {event}")
```

#### FileManager
FileManager moves, copy or deletes files and/or directories following a list of *rules*. 

A rule holds an *action* (move, copy or delete) and a regular expression *src_re*. The FileManager task will be executed if *src_re* matches the path of an event. 
If the action is copy or move, the destination path *dst_re* is mandatory and if *action* is delete and *rec* is set to True, non-empty directories will be deleted recursively.  
With *auto_create* set to True, possibly missing subdirectories in *dst_re* are created automatically. Regex subgroups or named-subgroups may be used in *src_re* and *dst_re*.  
Set the mode of moved/copied files/directories with *filemode* and *dirmode*. Ownership of moved/copied files/directories is set with *user* and *group*. Mode and ownership is also set to automatically created subdirectories.  
Log messages with *logname*.  
```python
rule = Rule(
    action="move",
    src_re="^/src_path/(?P<path>.*).to_move$",
    dst_re="/dst_path/\g<path>",
    auto_create=False,
    rec=False,
    filemode=None,
    dirmode=None,
    user=None,
    group=None)

fm = FileManager(
    rules=[rule],
    logname="filemgr")
```
FileManager provides a task **fm.task**.

### Schedulers
pyinotifyd has different schedulers to schedule tasks with an optional delay. The advantages of using a scheduler are consistent logging and the possibility to cancel delayed tasks. Furthermore, schedulers have the ability to differentiate between files and directories.

#### TaskScheduler
TaskScheduler schedules *task* with an optional *delay* in seconds. Use the *files* and *dirs* arguments to schedule tasks only for files and/or directories. 
Log messages with *logname*. All arguments except for *task* are optional.
```python
s = TaskScheduler(
    task=task,
    files=True,
    dirs=False,
    delay=0,
    logname="sched")
```
TaskScheduler provides two tasks which can be bound to an event in an event map.
* **s.schedule** 
  Schedule a task. If there is already a scheduled task, it will be canceled first.
* **s.cancel** 
  Cancel a scheduled task.

#### ShellScheduler
ShellScheduler schedules Shell command *cmd*. The placeholders **{maskname}**, **{pathname}** and **{src_pathname}** are replaced with the actual values of the event. ShellScheduler has the same optional arguments as TaskScheduler and provides the same tasks.
```python
s1 = ShellScheduler(
    cmd="/usr/local/bin/task.sh {maskname} {pathname} {src_pathname}")
```
### Event maps
EventMap maps event types to tasks. It is possible to set a list of tasks to run multiple tasks on a single event. If the task of an event type is set to None, it is ignored. 
This is an example:
```python
event_map = EventMap({
        "IN_CLOSE_NOWRITE": [s.schedule, s1.schedule],
        "IN_CLOSE_WRITE": s.schedule})
```
The following event types are available:
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

### Watches
Watch watches *path* for event types in *event_map* and execute the corresponding task(s). If *rec* is True, a watch will be added on each subdirectory in *path*. If *auto_add* is True, a watch will be added automatically on newly created subdirectories in *path*.
```python
watch = Watch(
    path="/tmp",
    event_map=event_map,
    rec=False,
    auto_add=False)
```

### Pyinotifyd
pyinotifyd expects an instance of Pyinotifyd named **pyinotifyd** defined in the config file. The options are a list of *watches* and the *shutdown_timeout*. pyinotifyd will wait *shutdown_timeout* seconds for pending tasks to complete during shutdown. Log messages with *logname*.
```python
pyinotifyd = Pyinotifyd(
    watches=[watch],
    shutdown_timeout=30,
    logname="daemon")
```

### Logging
Pythons [logging](https://docs.python.org/3/howto/logging.html) framework is used to log messages (see https://docs.python.org/3/howto/logging.html).  

Configure the global loglevel. This is the default:
```python
logging.getLogger().setLevel(logging.WARNING)
```
It is possible to configure the loglevel per log name. This is an example for logname **TaskScheduler**:
```python
logging.getLogger("TaskScheduler").setLevel(logging.INFO)
```

#### Syslog
Add this to your config file to send log messages to a local syslog server.
```python
# send log messages to the Unix socket of the syslog server.
syslog = logging.handlers.SysLogHandler(
    address="/dev/log")

# set the log format of syslog messages
log_format = "pyinotifyd/%(name)s: %(message)s"
syslog.setFormatter(
    logging.Formatter(formatter)

# set the log level for syslog messages
syslog.setLevel(logging.INFO)

# enable syslog
logging.getLogger().addHandler(syslog)

# or enable syslog just for TaskScheduler
logging.getLogger("TaskManager").addHandler(syslog)
```

## Examples

### Schedule Python task for all events
```python
async def task(event, task_id):
    logging.info(f"{task_id}: execute example task: {event}")

s = TaskScheduler(
    task=task,
    files=True,
    dirs=True)

event_map = EventMap(
    default_task=s.schedule)

watch = Watch(
    path="/tmp",
    event_map=event_map,
    rec=True,
    auto_add=True)

pyinotifyd_config = PyinotifydConfig(
    watches=[watch],
    shutdown_timeout=5)
```

### Schedule Shell commands for specific events on files
```python
s = ShellScheduler(
    cmd="/usr/local/sbin/task.sh {pathname}",
    files=True,
    dirs=False)

event_map = EventMap(
    {"IN_WRITE_CLOSE": s.schedule})

watch = Watch(
    path="/tmp",
    event_map=event_map,
    rec=True,
    auto_add=True)

pyinotifyd_config = PyinotifydConfig(
    watches=[watch],
    shutdown_timeout=5)
```

### Move, copy or delete newly created files after a delay
```python
move_rule = Rule(
    action="move",
    src_re="^/src_path/(?P<path>.*)\.to_move$",
    dst_re="/dst_path/\g<path>",
    auto_create=True,
    filemode=0o644,
    dirmode=0o755)

copy_rule = Rule(
    action="copy",
    src_re="^/src_path/(?P<path>.*)\.to_copy$",
    dst_re="/dst_path/\g<path>",
    auto_create=True,
    filemode=0o644,
    dirmode=0o755)

delete_rule = Rule(
    action="delete",
    src_re="^/src_path/(?P<path>.*)\.to_delete$",
    rec=False)

fm = FileManager(
    rules=[move_rule, copy_rule, delete_rule])

s = TaskScheduler(
    task=fm.task,
    delay=30,
    files=True,
    dirs=False)

event_map = EventMap({
        "IN_CLOSE_WRITE": s.schedule,
        "IN_DELETE": s.cancel,
        "IN_DELETE_SELF": s.cancel,
        "IN_MODIFY": s.cancel,
        "IN_MOVED_TO": s.schedule,
        "IN_UNMOUNT": s.cancel})

watch = Watch(
    path="/src_path",
    event_map=event_map,
    rec=True,
    auto_add=True)

# note that shutdown_timeout should be greater than the greatest scheduler delay,
# otherwise pending tasks may get cancelled during shutdown.
pyinotifyd_config = PyinotifydConfig(
    watches=[watch],
    shutdown_timeout=35)
```
