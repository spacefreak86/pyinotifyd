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
Tasks are Python methods that are called in case an event occurs. 
This is a very simple example task that just logs the task_id and the event:
```python
async def custom_task(event, task_id):
    logging.info(f"{task_id}: execute example task: {event}")
```
This task can be directly bound to an event in an event map. Although this is the easiest and quickest way, it is usually better to use a scheduler to schedule the task execution.

## Schedulers
pyinotifyd has different schedulers to schedule tasks with an optional delay. The advantages of using a scheduler are consistent logging and the possibility to cancel delayed tasks. Furthermore, schedulers have the ability to differentiate between files and directories.

### TaskScheduler
TaskScheduler to schedule *task* with an optional *delay* in seconds. Use the *files* and *dirs* arguments to schedule tasks only for files and/or directories. 
The *logname* argument is used to set a custom name for log messages. All arguments except for *task* are optional.
```python
s = TaskScheduler(task=custom_task, files=True, dirs=False, delay=0, logname="TaskScheduler")
```
TaskScheduler provides two tasks which can be bound to an event in an event map.
* **s.schedule** 
  Schedule a task. If there is already a scheduled task, it will be canceled first.
* **s.cancel** 
  Cancel a scheduled task.

### ShellScheduler
ShellScheduler to schedule Shell command *cmd*. The placeholders **{maskname}**, **{pathname}** and **{src_pathname}** are replaced with the actual values of the event. ShellScheduler has the same optional arguments as TaskScheduler and provides the same tasks.
```python
s1 = ShellScheduler(cmd="/usr/local/bin/task.sh {maskname} {pathname} {src_pathname}")
```
## Event maps
Event maps are used to map event types to tasks. It is possible to set a list of tasks to run multiple tasks on a single event. If the task of an event type is set to None, it is ignored. 
This is an example:
```python
event_map = EventMap({"IN_CLOSE_NOWRITE": [s.schedule, s1.schedule],
                      "IN_CLOSE_WRITE": s.schedule})
```

## Watches
Watches *path* for event types in *event_map* and execute the corresponding task(s). If *rec* is True, a watch will be added on each subdirectory in *path*. If *auto_add* is True, a watch will be added automatically on newly created subdirectories in *path*.
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
async def custom_task(event, task_id):
    logging.info(f"{task_id}: execute example task: {event}")

s = TaskScheduler(task=custom_task, files=True, dirs=True)

event_map = EventMap(default_task=custom_task)
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
rules = [{"action": "move",
          "src_re": "^/src_path/(?P<path>.*)\.to_move$",
          "dst_re": "/dst_path/\g<path"},
         {"action": "copy",
          "src_re": "^/src_path/(?P<path>.*)\.to_copy$",
          "dst_re": "/dst_path/\g<path"},
         {"action": "delete",
          "src_re": "^/src_path/(?P<path>.*)\.to_delete$"}]
fm = FileManager(rules=rules, auto_create=True)

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
# start the daemon during boot
systemctl enable pyinotifyd.service

# start the daemon
systemctl start pyinotifyd.service
```
