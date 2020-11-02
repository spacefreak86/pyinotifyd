# pyinotifyd
A daemon to monitore filesystems events with inotify on Linux and execute tasks, which can be Python functions or shell commands. It is build on top of the pyinotify library.

## Requirements
* [pyinotify](https://github.com/seb-m/pyinotify)

## Installation
* Install pyinotifyd with pip.
```sh
pip install pyinotifyd
```
* Modify /etc/pyinotifyd/config.py according to your needs.

# Configuration
The config file is written in Python syntax. pyinotifyd reads and executes its content, which means you can add custom Python code to the config file. 

To pass config options to pyinotifyd, define a dictionary named **pyinotifyd_config**. 
This is the default:
```python
pyinotifyd_config = {
    # List of watches, see description below
    "watches": [],

    # Loglevel (see https://docs.python.org/3/library/logging.html#levels)
    "loglevel": logging.INFO,

    # Timeout to wait for pending tasks to complete during shutdown
    "shutdown_timeout": 30
}
```

## Schedulers
pyinotifyd comes with different schedulers to schedule tasks with an optional delay. The advantages of using a scheduler are consistent logging and the possibility to cancel delayed tasks.

### TaskScheduler
This scheduler is used to run Python functions. 

class **TaskScheduler**(*job, delay=0, files=True, dirs=False, logname="TaskScheduler"*) 

Return a **TaskScheduler** object configured to call the Python function *job* with a delay of *delay* seconds. Use *files* and *dirs* to define if *job* is called for events on files and/or directories. Log messages with *logname*.

### ShellScheduler

## Watches
A Watch is defined as a dictionary. 
This is the default:
```python
{
    # path to watch, globbing is allowed
    "path": "",

    # set to True to add a watch on each subdirectory
    "rec": False,

    # set to True to automatically  add watches on newly created directories in watched parent path
    "auto_add": False,

    # dictionary which contains the event map, see description below
    "event_map": {}
}
```

### Event maps
An event map is defined as a dictionary. It is used to map different event types to Python functions. Those functions are called with the event-object a task-id as positional arguments if an event is received. It is possible to set a list of functions to run multiple tasks on a single event. If an event type is not present in the map or None is given, the event type is ignored.
This is an example:
```python
{
    "IN_CLOSE_NOWRITE": [s1.schedule, s2.schedule],
    "IN_CLOSE_WRITE": s1.schedule
}
```
