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

## Global configuration
The config file is written in Python syntax. pyinotifyd reads config options from a dictionary named **pyinotifyd_config**. 
This is the default configuration:
```python
pyinotifyd_config = {
    # List of watches, description below
    "watches": [],
    # Set the loglevel (see https://docs.python.org/3/library/logging.html#levels)
    "loglevel": logging.INFO,
    # Set the timeout to wait for pending tasks to complete during shutdown
    "shutdown_timeout": 30
}
```
## Watch configuration
A Watch is defined as a dictionary which contains the config options:
```python
{
    "path": "/tmp",
    "rec": True,
    "auto_add": True,
    "event_map": {}
}
```
