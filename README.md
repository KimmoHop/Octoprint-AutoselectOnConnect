# Octoprint-AutoselectOnConnect

This plugin connects printer automatically, when serial port is connected.
After that, last file uploaded to OctoPrint is selected, enabling printer to use //action:start to begin printing.

Then, starting in version 0.2, this plugin writes "links" to 5 newest files in local storage.
The "links" are files with M118 A1 actions to initiate printing host files via action hook.
Just select a file in printer and print it -> magically OctoPrint starts printing the file ;)

What could be better? Well, thumbnails. Unfortunately OctoPrint really ~~hates~~ doesn't write comments to commands. So no thumbnails (for now) :/

Why? If file is uploaded before the printer is on, it would require another visit to computer to connect, select a file and start print.

With this plugin everything after loading is done on printer (if it has start action implemented, that is).

## Sources

Auto-connection became mandatory as [PortLister plugin](https://github.com/markwal/OctoPrint-PortLister/tree/master) does not seem to work. So it was easier to combine similar functionality here.

Auto-connection part is heavily _loaned_ from server auto connect.

Simplicity to connect to the printer was found from [Connect and print plugin](https://github.com/Maxinger15/connectandprint)

Auto selection got inspiration from [OctoPrint-Autoselect plugin](https://github.com/OctoPrint/OctoPrint-Autoselect)

Not sure where action hook got working example, thanks anyway.

There were no good serial port examples, which means there are no thumbnails. Any directions welcome ;)

## Setup

Install via the bundled [Plugin Manager](https://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL:

    https://github.com/KimmoHop/Octoprint-AutoselectOnConnect/archive/master.zip

For file "links" to work, printer SD card must have directory HOST. Old and unnecessary files will be deleted from it.
SD file naming is a bit on the short side, so try to name the gcode-files so that they can be recognized from the beginning.

## Configuration

There is no configuration for this plugin.

However, to be able to connect to the printer automatically,
`Auto-connect on server startup` option must be selected
(in Connection or in OctoPrint settings -> Serial Connection -> General, they are the same)

Also printer Serial port must be saved.

This plugin uses `Autodetection timeout` `First handshake attempt` (default: 10 seconds) as waiting time before attempting to connect to the printer.'
Attempts are retried until at least 30 seconds has elapsed.

## Details

File "links" arewritten with `M28` and `M29` commands. They may make the printer thing it has printed something, just OK it.

There may be some faults in when printer file "links" are updated, and when not.
