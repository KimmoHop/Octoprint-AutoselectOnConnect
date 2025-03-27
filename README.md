# Octoprint-AutoselectOnConnect

This plugin connects printer automatically, when serial port is connected.
After that, last file uploaded to OctoPrint is selected, enabling printer to use //action:start to begin printing.

Why? If file is uploaded before the printer is on, it would require another visit to computer to connect, select a file and start print.

With this plugin everything after loading is done on printer (if it has start action implemented, that is).

## Sources

Auto-connection became mandatory as [PortLister plugin](https://github.com/markwal/OctoPrint-PortLister/tree/master) does not seem to work. So it was easier to combine similar functionality here.

Auto-connection part is heavily _loaned_ from server auto connect.

Simplicity to connect to the printer was found from [Connect and print plugin](https://github.com/Maxinger15/connectandprint)

Auto selection got inspiration from [OctoPrint-Autoselect plugin](https://github.com/OctoPrint/OctoPrint-Autoselect)

## Setup

Install via the bundled [Plugin Manager](https://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL:

    https://github.com/KimmoHop/Octoprint-AutoselectOnConnect/archive/master.zip

**TODO:** Currently there are no archives.

## Configuration

There is no configuration for this plugin.

However, to be able to connect to the printer automatically,
`Auto-connect on server startup` option must be selected
(in Connection or in OctoPrint settings -> Serial Connection -> General, they are the same)

Also printer Serial port must be saved.

This plugin uses `Autodetection timeout` `First handshake attempt` (default: 10 seconds) as waiting time before attempting to connect to the printer.'
Attempts are retried until at least 30 seconds has elapsed.
