# pyinotifyd
A daemon to monitore filesystems events with inotify on Linux and execute tasks, which can be Python functions or shell commands.

## Dependencies
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
    "watches": [],
    "loglevel": logging.INFO,
    "shutdown_timeout": 30
}
```

Global options:
* **watches**
  List of Watches, description below.
* **loglevel**
  Set the loglevel, you may use every available loglevel of the Python logging framework.
* **shutdown_timeout**
  Timeout to wait for pending tasks to complete when shutdown.
