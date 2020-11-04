#!/usr/bin/env python3

####################################
#  Example usage of TaskScheduler  #
####################################

#async def custom_task(event, task_id):
#    logging.info(f"{task_id}: execute example task: {event}")
#
#s = TaskScheduler(
#    task=custom_task,
#    files=True,
#    dirs=False)


#####################################################
#  Example usage of TaskScheduler with FileManager  #
#####################################################

#rules=[{
#    "action": "move",
#    "src_re": r"^(?P<path>.*)",
#    "dst_re": r"\g<path>.processed",
#    "auto_create": True,
#    "filemode": 0o755,
#    "dirmode": 0o644,
#    "user": "root",
#    "goup": "root"}]
#
#fm = FileManager(
#    rules=rules)
#
#s = TaskScheduler(
#    task=fm.task,
#    delay=10,
#    files=True,
#    dirs=False)


#####################################
#  Example usage of ShellScheduler  #
#####################################

#cmd = "/usr/local/bin/task.sh {maskname} {pathname} {src_pathname}"
#s = ShellScheduler(
#    cmd=cmd)


###################
#  Example watch  #
###################

#event_map = EventMap({
#    "IN_ACCESS": None,
#    "IN_ATTRIB": None,
#    "IN_CLOSE_NOWRITE": None,
#    "IN_CLOSE_WRITE": s.schedule,
#    "IN_CREATE": None,
#    "IN_DELETE": s.cancel,
#    "IN_DELETE_SELF": s.cancel,
#    "IN_IGNORED": None,
#    "IN_MODIFY": s.cancel,
#    "IN_MOVE_SELF": None,
#    "IN_MOVED_FROM": s.cancel,
#    "IN_MOVED_TO": s.schedule,
#    "IN_OPEN": None,
#    "IN_Q_OVERFLOW": None,
#    "IN_UNMOUNT": s.cancel})
#
#watch = Watch(
#    path="/tmp",
#    event_map=event_map,
#    rec=True,
#    auto_add=True)


###############################
#  Example pyinotifyd config  #
###############################

#pyinotifyd_config = PyinotifydConfig(
#    watches=[watch],
#    loglevel=logging.INFO,
#    shutdown_timeout=30)
