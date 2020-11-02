#!/usr/bin/env python3

####################################
#  Example usage of TaskScheduler  #
####################################

#def custom_job(event, task_id):
#    logging.info(f"{task_id}: execute task for {event}")
#
#s = TaskScheduler(delay=10, job=custom_job)


#####################################################
#  Example usage of TaskScheduler with FileManager  #
#####################################################

#fm = FileManager(
#    rules=[
#        {"action": "move",
#         "src_re": r"^(?P<path>.*)",
#         "dst_re": r"\g<path>.processed"}
#    ]
#)
#
#s = TaskScheduler(delay=10, job=fm.job)


#####################################
#  Example usage of ShellScheduler  #
#####################################

#s = ShellScheduler(cmd="/usr/local/bin/task.sh {maskname} {pathname} {src_pathname}")


###############################
#  Example pyinotifyd config  #
###############################

#pyinotifyd_config = {
#    "watches": [
#        {"path": "/tmp",
#         "rec": True,
#         "auto_add": True,
#         "event_map": {
#             "IN_ACCESS": None,
#             "IN_ATTRIB": None,
#             "IN_CLOSE_NOWRITE": None,
#             "IN_CLOSE_WRITE": s.schedule,
#             "IN_CREATE": None,
#             "IN_DELETE": s.cancel,
#             "IN_DELETE_SELF": s.cancel,
#             "IN_IGNORED": None,
#             "IN_MODIFY": s.cancel,
#             "IN_MOVE_SELF": None,
#             "IN_MOVED_FROM": s.cancel,
#             "IN_MOVED_TO": s.schedule,
#             "IN_OPEN": None,
#             "IN_Q_OVERFLOW": None,
#             "IN_UNMOUNT": s.cancel}
#        }
#    ],
#    "loglevel": logging.INFO,
#    "shutdown_timeout":  15}
