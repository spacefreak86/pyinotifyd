# pyinotifyd
A daemon to monitore filesystems events with inotify on Linux and execute tasks (Python methods or Shell commands) with an optional delay. It is also possible to cancel delayed tasks.

## Requirements
* [pyinotify](https://github.com/seb-m/pyinotify)

## Installation
```sh
pip install pyinotifyd
```

# Configuration
The config file **/etc/pyinotifyd/config.py** is written in Python syntax. pyinotifyd reads and executes its content, that means you can add your custom Python code to the config file.

## Tasks
Tasks are Python methods that are called in case an event occurs. They can be bound directly to an event type in an event map. Although this is the easiest and quickest way, it is usually better to use a scheduler to schedule the task execution.

### Simple
This is a very basic example task that just logs each event and task_id:
```python
async def task(event, task_id):
    logging.info(f"{task_id}: execute example task: {event}")
```

### FileManager
FileManager moves, copy or deletes files and/or directories following a list of *rules*. 

A rule holds an *action* (move, copy or delete) and a regular expression *src_re*. The FileManager task will be executed if *src_re* matches the path of an event. If the action is copy or move, the destination path *dst_re* is mandatory. If *auto_create* is True, possibly missing subdirectories in *dst_re* are automatically created. If *action* is delete and *rec* is True, non-empty directories will be deleted recursively. It is possible to use Regex subgroups or named-subgroups in *src_re* and *dst_re*.
```python
rule = Rule(
    action="move", src_re="^/src_path/(?P<path>.*).to_move$",
    dst_re="/dst_path/\g<path>", auto_create=False, rec=False)

fm = FileManager(rules=[rule])
```
FileManager provides a task **fm.task**.

## Schedulers
pyinotifyd has different schedulers to schedule tasks with an optional delay. The advantages of using a scheduler are consistent logging and the possibility to cancel delayed tasks. Furthermore, schedulers have the ability to differentiate between files and directories.

### TaskScheduler
TaskScheduler schedules *task* with an optional *delay* in seconds. Use the *files* and *dirs* arguments to schedule tasks only for files and/or directories. 
The *logname* argument is used to set a custom name for log messages. All arguments except for *task* are optional.
```python
s = TaskScheduler(task=task, files=True, dirs=False, delay=0, logname="TaskScheduler")
```
TaskScheduler provides two tasks which can be bound to an event in an event map.
* **s.schedule** 
  Schedule a task. If there is already a scheduled task, it will be canceled first.
* **s.cancel** 
  Cancel a scheduled task.

### ShellScheduler
ShellScheduler schedules Shell command *cmd*. The placeholders **{maskname}**, **{pathname}** and **{src_pathname}** are replaced with the actual values of the event. ShellScheduler has the same optional arguments as TaskScheduler and provides the same tasks.
```python
s1 = ShellScheduler(cmd="/usr/local/bin/task.sh {maskname} {pathname} {src_pathname}")
```
## Event maps
EventMap maps event types to tasks. It is possible to set a list of tasks to run multiple tasks on a single event. If the task of an event type is set to None, it is ignored. 
This is an example:
```python
event_map = EventMap({"IN_CLOSE_NOWRITE": [s.schedule, s1.schedule],
                      "IN_CLOSE_WRITE": s.schedule})
```

## Watches
Watch watches *path* for event types in *event_map* and execute the corresponding task(s). If *rec* is True, a watch will be added on each subdirectory in *path*. If *auto_add* is True, a watch will be added automatically on newly created subdirectories in *path*.
```python
watch = Watch(path="/tmp", event_map=event_map, rec=False, auto_add=False)
```

## PyinotifydConfig
pyinotifyd expects an instance of PyinotifydConfig named **pyinotifyd_config** that holds its config options. The options are a list of *watches*, the *loglevel* (see https://docs.python.org/3/library/logging.html#levels) and the *shutdown_timeout*. pyinotifyd will wait *shutdown_timeout* seconds for pending tasks to complete during shutdown.
```python
pyinotifyd_config = PyinotifydConfig(watches=[watch], loglevel=logging.INFO, shutdown_timeout=30)
```

# Examples

## Schedule Python task for all events
```python
async def task(event, task_id):
    logging.info(f"{task_id}: execute example task: {event}")

s = TaskScheduler(task=task, files=True, dirs=True)

event_map = EventMap(default_task=task)
watch = Watch(path="/tmp", event_map=event_map, rec=True, auto_add=True)

pyinotifyd_config = PyinotifydConfig(
    watches=[watch], loglevel=logging.INFO, shutdown_timeout=5)
```

## Schedule Shell commands for specific events on files
```python
s = ShellScheduler(
    cmd="/usr/local/sbin/task.sh {pathname}", files=True, dirs=False)

event_map = EventMap({"IN_WRITE_CLOSE": s.schedule,
                      "IN_DELETE": s.schedule})
watch = Watch(path="/tmp", event_map=event_map, rec=True, auto_add=True)

pyinotifyd_config = PyinotifydConfig(
    watches=[watch], loglevel=logging.INFO, shutdown_timeout=5)
```

## Move, copy or delete newly created files after a delay
```python
move_rule = Rule(action="move",
    src_re="^/src_path/(?P<path>.*)\.to_move$",
    dst_re="/dst_path/\g<path>",
    auto_create=True)

copy_rule = Rule(action="copy",
    src_re="^/src_path/(?P<path>.*)\.to_copy$",
    dst_re="/dst_path/\g<path>",
    auto_create=True)

delete_rule = Rule(action="delete",
    src_re="^/src_path/(?P<path>.*)\.to_delete$",
    rec=False)

fm = FileManager(rules=[move_rule, copy_rule, delete_rule])

s = TaskScheduler(task=fm.task, delay=30, files=True, dirs=False)

event_map = EventMap({"IN_CLOSE_WRITE": s.schedule,
                      "IN_DELETE": s.cancel,
                      "IN_DELETE_SELF": s.cancel,
                      "IN_MODIFY": s.cancel,
                      "IN_MOVED_TO": s.schedule,
                      "IN_UNMOUNT": s.cancel})
watch = Watch(path="/src_path", event_map=event_map, rec=True, auto_add=True)

# note that shutdown_timeout should be greater than the greatest scheduler delay,
# otherwise pending tasks may get cancelled during shutdown.
pyinotifyd_config = PyinotifydConfig(
    watches=[watch], loglevel=logging.INFO, shutdown_timeout=35)
```

# Autostart
pyinotifyd provides a systemd service file.
```sh
# start pyinotifyd at boot time
systemctl enable pyinotifyd.service

# start the daemon immediately
systemctl start pyinotifyd.service
```
