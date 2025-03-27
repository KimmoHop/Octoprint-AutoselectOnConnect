# coding=utf-8
from __future__ import absolute_import

import math
import threading
from typing import List, Tuple

import octoprint.events
import octoprint.filemanager
import octoprint.plugin
from octoprint.filemanager import FileDestinations
from octoprint.settings import settings
from octoprint.util import RepeatedTimer



class AutoConnectAndSelectFilePlugin(octoprint.plugin.EventHandlerPlugin):

    def __init__(self):
        self.timer = None
        self._event_connected = octoprint.events.Events.CONNECTED
        self._event_ports_changed = octoprint.events.Events.CONNECTIONS_AUTOREFRESHED
        self._file_cache = {}
        self._file_cache_mutex = threading.RLock()
        self._settings = settings()
        self._connect_attempt = 0
        self._max_connect_attempts = 2

    def on_event(self, event, payload):
        if event not in [self._event_connected, self._event_ports_changed]:
            return

        if event == self._event_ports_changed:
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
                        self._logger.info(f"Connection attempt {self._connect_attempt + 1}")
                        if not self._printer.is_operational():
                            self._printer.connect()
                        self._connect_attempt += 1

                    period = self._settings.getFloat(["serial", "timeout", "detectionFirst"])
                    # aim to roughly 30 seconds max
                    self._max_connect_attempts = math.ceil(30 / period)
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

        else:
            if self.timer is not None:
                self.timer.cancel()  # connected, don't try again :)
                self.timer = None

            def filter_machinecode(node):
                return node["type"] == "machinecode"

            # get all local gcode files
            files = self._file_manager.list_files(FileDestinations.LOCAL, filter=filter_machinecode, recursive=True)
            files = files["local"] if "local" in files else dict()
            # self._logger.info("Local files from filemanager:\n{}".format(files))

            # extract dates and paths, other attributes not needed
            if files:
                date_files: List[Tuple] = []
                for key in files:
                    file = files[key]
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
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
