# coding=utf-8
from __future__ import absolute_import

import hashlib
import math
import pprint
import re
import threading
import time
from typing import List, Tuple, Optional

import octoprint.events
import octoprint.filemanager
import octoprint.plugin
from octoprint.filemanager import FileDestinations
from octoprint.settings import settings
from octoprint.util import RepeatedTimer

# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "Octoprint_autoselect_on_connect Plugin"

# Set the Python version your plugin is compatible with below. Recommended is Python 3 only for all new plugins.
# OctoPrint 1.4.0 - 1.7.x run under both Python 3 and the end-of-life Python 2.
# OctoPrint 1.8.0 onwards only supports Python 3.
__plugin_pythoncompat__ = ">=3,<4"  # Only Python 3


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = AutoConnectAndSelectFilePlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.action": __plugin_implementation__.hook_actioncommands,
    }


def filter_machinecode(node):
    return node["type"] == "machinecode"


SYNC_IDLE = "Idle"
SYNC_NEEDED = "Needed"
SYNC_LAUNCHING = "Launching"
SYNC_ACTIVE = "Active"
SYNC_COMPLETE = "Complete"


class AutoConnectAndSelectFilePlugin(octoprint.plugin.EventHandlerPlugin):
    """
    TODO
    - bind to files added/deleted/moved event
    - if during printing, mark
    - when connected, print finished & mark or files achanged and not printing,
    -- get files listing octoprint.util.comm.MachineCom.getSdFiles
    -- delete files from <HOST> directory octoprint.util.comm.MachineCom.deleteSdFile
    --- if no directory (open failed, File: XXX. ?) skip the rest, log error, inform user?
    -- get lates <N> local files
    -- read defined headers, thumbnails etc
    -- write to SD with M118 command <START_COMMAND> <FILENAME>
    --- can't use xx but look at octoprint.util.comm.MachineCom.startFileTransfer and octoprint.printer.standard.Printer._add_sd_file and
    - bind to _printer_action_hooks
    -- when action <START_COMMAND> <FILENAME> received, start print with <FILENAME>
    """

    def __init__(self):
        self.timer = None
        self._file_cache = {}
        self._file_cache_mutex = threading.RLock()
        self._settings = settings()
        self._connect_attempt = 0
        self._connect_max_time = 40
        self._max_connect_attempts = 2

        self._action_command = "start_file"
        self._host_sd_directory = "HOST/"
        self._max_host_files = 5
        self._waiting_for_sync = False
        self._sync_state = SYNC_IDLE
        self._max_sync_attempts = 20

        self._pp = pprint.PrettyPrinter(indent=2, sort_dicts=False)

    def hook_actioncommands(self, comm, line, action, *args, **kwargs):
        """
        Handle //action:<self._action_command> <file> to start printing local file <file>
        """
        self._logger.info(f"Command received: '{action}' with params {args}")

        # it seems that line and args are empty, and everything is packed in action?
        candidate = action.strip()
        if not candidate.startswith(self._action_command):
            return

        file_name = candidate[len(self._action_command):].strip()

        files = self.get_latest_local_files(None)
        is_started = False
        if files:
            for file in files:
                _, path, _, _ = file
                # local path is not important,
                # though if there are files with same names in multiple directories,
                # we can't be sure *which* will be printed.
                # Starting from newest should help :)
                if file_name in path:
                    # select that file and start printing
                    self._logger.info(f"Selecting and starting {path}")
                    self._printer.select_file(path, False, False)
                    self._logger.info(f"STARTING PRINT '{file_name}' :)")
                    self._printer.start_print()
                    is_started = True

        if not is_started:
            self._logger.info(f"Did not find '{file_name}' to print :/")

        # # get all local gcode files
        # files = self._file_manager.list_files(FileDestinations.LOCAL, filter=filter_machinecode, recursive=True)
        # files = files["local"] if "local" in files else dict()
        #
        # if files:
        #     for key in files:
        #         file = files[key]
        #         path = file["path"]
        #         # local path is not important,
        #         # though if there are files with same names in multiple directories,
        #         # we can't be sure *which* will be printed
        #         if file_name in path:
        #             # select that file and start printing
        #             self._logger.info(f"Selecting and starting {path}")
        #             self._printer.select_file(path, False, False)
        #             self._printer.start_print()
        # else:
        #     self._logger.info(f"Did not find '{file_name}' to print :/")

    def sync_sd_with_local(self):
        """
        Update host file "links" on printer SD card.
        Reads file lists from host (local) and printer host directory.
        Updates "links" to latest/newest host files by deleting and adding necessary files.
        "Links" contain M118 command to launch host printing using hook_actioncommands
        """
        if not self._printer.is_operational() or self._printer.is_printing():
            return
        if self._sync_state != SYNC_LAUNCHING:
            self._logger.info(f"Trying to sync when '{self._sync_state}'")
            return
        self._move_to_state(SYNC_ACTIVE, message="Activating sync")
        self._printer.commands([f"M117 Updating host files"])
        try:
            # get all printer SD files
            printer_files = self._printer.get_sd_files(refresh=True)
            printer_host_files = [x for x in printer_files if x["name"].startswith(self._host_sd_directory)]

            # get latest local gcode files
            newest_host_files = self.get_latest_local_files(self._max_host_files)

            # compare
            names_of_newest_host_files = [x[2] for x in newest_host_files]
            printer_host_files_to_delete = [x for x in printer_host_files if
                                            x["display"] not in names_of_newest_host_files]
            self._logger.info(
                f"deleting old host files from sd: ----------------\n{self._pp.pformat([x['name'] for x in printer_host_files_to_delete])}")
            for f in printer_host_files_to_delete:
                self._printer.delete_sd_file(f["name"])

            printer_host_files = [x for x in printer_host_files if x not in printer_host_files_to_delete]
            names_of_printer_host_files = [x["display"] for x in printer_host_files]

            # self._logger.info(
            #     f"Newest local files are ------------------\n{self._pp.pformat([x[2] for x in newest_host_files])}")
            # self._logger.info(
            #     f"Remaining SD files are ------------------\n{self._pp.pformat(names_of_printer_host_files)}")

            host_files_to_copy = [x for x in newest_host_files if x[2] not in names_of_printer_host_files]
            self._logger.info(
                f"copying new host files to sd: -------------------\n{self._pp.pformat([x[2] for x in host_files_to_copy])}")

            try:
                commands = []
                for file in host_files_to_copy:
                    _, path, _, name = file
                    short_name = self._short_filename(name)
                    commands.append(f"M28 /{self._host_sd_directory}{short_name}")
                    self._logger.info(f"writing file: /{self._host_sd_directory}{short_name}")

                    commands.extend([
                        f"M117 Starting host print...",
                        f"M118 A1 action: {self._action_command} {path}",
                        f"M29"
                    ])

                if commands:
                    self._printer.commands(commands)
                    self._logger.info("Waiting for commands to run")
                    time.sleep(10)
                    self._printer.commands([f"M117 {len(host_files_to_copy)} host files updated"])
                else:
                    self._printer.commands([f"M117 Host files were OK"])
            except:
                pass

        finally:
            # self._printer.commands(["M117 Host files updated"])
            self._move_to_state(SYNC_COMPLETE, message="Completed sync")

    def _short_filename(self, original_name):
        """
        Create unique(ish) short-ish file names without knowing names of other files
        """
        base = re.sub(r'\.gcode$', '', original_name.lower())
        base = re.sub(r'[^a-z0-9]+', '_', base)  # Keep alphanum + underscore
        base = base.strip('_')

        # Hash the base name
        hash_part = hashlib.sha1(base.encode()).hexdigest()[:6]

        # Use first 8 chars of the cleaned name as prefix
        prefix = base[:12].strip('_')

        return f"{prefix}_{hash_part}.gcode"

    def on_event(self, event, payload):
        # self._logger.info(f"Event '{event}' has payload {self._pp.pformat(payload)}")
        # self._logger.info(f"Printer is operational: {self._printer.is_operational()}\nPrinter SD is ready: {self._printer.is_sd_ready()}\nPrinter is printing: {self._printer.is_printing()}")
        # self._logger.info(f"Sync state is '{self._sync_state}'")
        if event == octoprint.events.Events.CONNECTIONS_AUTOREFRESHED:
            if not self._settings.getBoolean(["serial", "autoconnect"]):
                self._logger.info("Autoconnect on startup is not configured")
                return

            new_ports = payload["ports"] if payload is not None else None
            if not new_ports:
                self._logger.info("No connected ports")
                return

            try:
                (port, baudrate) = (
                    self._settings.get(["serial", "port"]),
                    self._settings.getInt(["serial", "baudrate"]),
                )
                connection_options = self._printer.get_connection_options()
                if new_ports and (
                    (port in connection_options["ports"] and port in new_ports) or port == "AUTO"):
                    self._logger.info(f"Trying to connect to configured serial port {port}")

                    def condition():
                        return self._connect_attempt <= self._max_connect_attempts

                    def try_connect():
                        self._logger.info(
                            f"Connection attempt {self._connect_attempt + 1}/{self._max_connect_attempts}")
                        if not self._printer.is_operational():
                            self._printer.connect()
                        self._connect_attempt += 1

                    period = self._settings.getFloat(["serial", "timeout", "detectionFirst"])
                    # reserve long enough time to wait for connection
                    self._max_connect_attempts = math.ceil(self._connect_max_time / period)
                    self._connect_attempt = 0

                    self._logger.info(f"Try connection for {self._max_connect_attempts} x {period} seconds")
                    self.timer = RepeatedTimer(period, try_connect, run_first=False, condition=condition)
                    self.timer.start()

                else:
                    self._logger.info(
                        f"Could not find configured serial port {port} in the system, cannot automatically connect to a non existing printer. Is it plugged in and booted up yet?"
                    )
            except Exception:
                self._logger.exception(
                    "Something went wrong while attempting to automatically connect to the printer"
                )

        elif event == octoprint.events.Events.CONNECTED:
            if self.timer is not None:
                self.timer.cancel()  # connected, don't try again :)
                self.timer = None
            self._move_to_state(SYNC_NEEDED, start_sync=True, message="Connected")

            # get all local gcode files
            files = self._file_manager.list_files(FileDestinations.LOCAL, filter=filter_machinecode, recursive=True)
            files = files["local"] if "local" in files else dict()

            # extract dates and paths, other attributes not needed
            if files:
                date_files: List[Tuple] = []
                for key in files:
                    file = files[key]
                    if "gcode" in file["typePath"]:  # filter out directories
                        date = file["date"]
                        path = file["path"]
                        date_files.append((date, path))

                # sort files to latest (youngest) first
                # self._logger.info("Local files before sorting:\n{}".format(date_files))
                date_files.sort(reverse=True, key=lambda f: f[0])
                # self._logger.info("Local files after sorting:\n{}".format(date_files))

                # at this time only top 1 interests us ;)
                date, path = date_files[0]

                # select that file
                self._logger.info("Selecting {} on {} that was just uploaded".format(path, FileDestinations.LOCAL))
                self._printer.select_file(path, False, False)
            else:
                self._logger.info("No local files to select from")

        elif event == octoprint.events.Events.PRINT_DONE:
            self._logger.info("Print finished, checking is file sync should and can be done")
            if self._sync_state == SYNC_NEEDED and self._printer.is_operational() and self._printer.is_sd_ready() and not self._printer.is_printing():
                self._move_to_state(SYNC_NEEDED, start_sync=True, message="after print done")

        elif event == octoprint.events.Events.UPDATED_FILES:
            # this may originate from changes from local files or from reading SD card file list
            if self._sync_state == SYNC_COMPLETE:
                # updating SD content after sync
                self._move_to_state(SYNC_IDLE, message="Sync has been completed")

            elif (
                self._sync_state == SYNC_IDLE or self._sync_state == SYNC_NEEDED) and self._printer.is_operational() and self._printer.is_sd_ready() and not self._printer.is_printing():
                self._move_to_state(SYNC_NEEDED, start_sync=True, message="after update")

            elif self._sync_state == SYNC_IDLE:
                self._move_to_state(SYNC_NEEDED, message="after update")

        elif event == octoprint.events.Events.UPLOAD or event == octoprint.events.Events.FILE_ADDED or event == octoprint.events.Events.FILE_REMOVED or event == octoprint.events.Events.FILE_MOVED:
            if (
                self._sync_state == SYNC_IDLE or self._sync_state == SYNC_NEEDED) and self._printer.is_operational() and self._printer.is_sd_ready() and not self._printer.is_printing():
                self._move_to_state(SYNC_NEEDED, start_sync=True, message="after upload/add/remove")

            elif self._sync_state == SYNC_IDLE:
                self._move_to_state(SYNC_NEEDED, message="after upload/add/remove")

    def _move_to_state(self, new_state: str, start_sync: bool = False, message: str = ""):
        self._logger.info(f"{self._sync_state} -> {new_state} {'START' if start_sync else ''} : {message}")
        self._sync_state = new_state
        if start_sync:
            self._start_sync()

    def _start_sync(self):
        if self._sync_state != SYNC_NEEDED:
            self._logger.info(f"Sync state is '{self._sync_state}' - not starting")
            return
        if self.timer is not None:
            self.timer.cancel()  # connected, don't try again :)
            self.timer = None

        def condition():
            return self._max_sync_attempts > 0 and self._waiting_for_sync

        def do_sync():
            self._max_sync_attempts -= 1
            if self._printer.is_sd_ready():
                self._waiting_for_sync = False
                self.sync_sd_with_local()

        # launch link file sync in separate thread, SD content is not available right now
        self.timer = RepeatedTimer(2, do_sync, run_first=True, condition=condition)
        self._waiting_for_sync = True
        self._max_sync_attempts = 20
        self._move_to_state(SYNC_LAUNCHING, message="Launching")
        self.timer.start()
        t = threading.Timer(2, do_sync)
        t.start()

    def get_latest_local_files(self, number_of_files: Optional[int]) -> List[Tuple]:
        # get all local gcode files
        host_files = self._file_manager.list_files(FileDestinations.LOCAL, filter=filter_machinecode, recursive=True)
        host_files = host_files["local"] if "local" in host_files else dict()

        # extract dates and paths, other attributes not needed
        if host_files:
            newest_host_files: List[Tuple] = []
            for key in host_files:
                file = host_files[key]
                if "gcode" in file["typePath"]:  # filter out directories
                    date = file["date"]
                    path = file["path"]
                    # display name is most useful, just make short version for comparison
                    display_raw = file["display"]
                    display_raw = display_raw[1:] if display_raw.startswith("/") else display_raw
                    display = "/" + self._short_filename(display_raw)  # match with /XXX theme
                    name = file["name"]
                    newest_host_files.append((date, path, display, name))

            # sort files to latest (youngest) first
            newest_host_files.sort(reverse=True, key=lambda f: f[0])
            if number_of_files is not None:
                newest_host_files = newest_host_files[:number_of_files]  # x newest
        else:
            newest_host_files = list()

        return newest_host_files

    ##~~ Softwareupdate hook

    def get_update_information(self):
        # Define the configuration for your plugin to use with the Software Update
        # Plugin here. See https://docs.octoprint.org/en/master/bundledplugins/softwareupdate.html
        # for details.
        return {
            "octoprint_autoselect_on_connect": {
                "displayName": "Octoprint_autoselect_on_connect Plugin",
                "displayVersion": self._plugin_version,

                # version check: github repository
                "type": "github_release",
                "user": "KimmoHop",
                "repo": "Octoprint-AutoselectOnConnect",
                "current": self._plugin_version,

                # update method: pip
                "pip": "https://github.com/KimmoHop/Octoprint-AutoselectOnConnect/archive/{target_version}.zip",
            }
        }
