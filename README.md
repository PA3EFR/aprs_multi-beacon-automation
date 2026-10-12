APRS Beacon User Guide
Script: aprs_baken.py · October 2026
1. What does the script do?
With aprs_baken.py you periodically send an APRS position report to the APRS-IS network from one or more fixed positions. The script is intended for beacons that do not move, for example a clubhouse, a scout location or a fixed station. For each beacon you set the callsign, position, comment, symbol, interval and an optional time window, and you can prepare as many beacons as you like. Once the input is complete, the script opens a separate tab on aprs.fi for each beacon, so you can immediately check whether the beacon becomes visible.
2. Preparation
You will need:
•	Python 3 on your computer, with the aprslib library (install with pip install aprslib).
•	An internet connection. The script connects to APRS-IS on port 14580.
•	A valid callsign and the matching APRS passcode. Put the passcode in the file APRS_Codes.txt in the same folder as the script, with one line per callsign, for example pa3efr 12345. Lines starting with # are ignored, and any SSID (such as -5) is left out when looking up the callsign. If your callsign is not in the file, the script asks for the passcode and refers you to https://www.iz3mez.it/aprs-passcode/.
Only use a callsign you are licensed to use. The passcode is personal: do not share it.
3. Starting
Open a terminal in the folder containing the script and run: python3 aprs_baken.py. The script then asks the questions from the next chapter one by one, first for beacon 1. After each beacon it asks whether you want to prepare another beacon (see chapter 5). If the input is invalid, a message appears and the same question is asked again. With Ctrl+C you stop all beacons at any time.
4. The input fields
These questions are asked again for each beacon. (The script itself shows them in Dutch; the Dutch field names are given in brackets.)
•	Callsign: for example PA3EFR or PA3EFR-5. Lowercase letters are automatically converted to uppercase.
•	GPS position (GPS-positie): decimal degrees, for example 52.0705, 4.3007, or the notation 52.0705°N 4.3007°E. South and west are processed as negative values.
•	Comment: free text that is shown with the beacon, maximum 43 characters. Longer text is automatically shortened.
•	Symbol (Symbool): the icon on the map. Leaving it empty gives the scout symbol. You can enter one character (a symbol from the primary table, for example - for a house, r for an antenna or # for a digipeater) or two characters (table plus symbol, for example /, or \, for the alternate table). Type ? for a list of commonly used symbols. The complete APRS symbol list can be found at aprs.org.
•	Interval time (Intervaltijd): the number of minutes between two transmissions. Default is 10 minutes, minimum 1 minute, whole minutes only. Below 10 minutes you get a warning, because a shorter interval is unnecessarily burdensome for the network for a fixed station.
•	Start date and start time (Startdatum en starttijd): empty means today and now. Date as DD-MM-YYYY (YYYY-MM-DD also works), time as HH:MM.
•	End date and end time (Einddatum en eindtijd): empty means infinite, so the beacon keeps running until you stop it yourself.
5. Preparing multiple beacons
After the details of a beacon, the script asks: Nog een baken voorbereiden? (j/N) (“Prepare another beacon?”). Leaving it empty or n means no, j means you enter the details of a next beacon, after which the same question comes back. You can do this as often as you like. Only when you answer no do the beacons go on the air.
Each beacon has its own settings: position, comment, symbol, interval time, start and end. So beacon 1 can transmit indefinitely, while beacon 2 is only active on Saturday from 08:00 to 18:00. The script asks for the passcode only once per callsign.
If you use the same callsign twice (including SSID), aprs.fi only shows the most recently received position. Therefore give beacons at different locations their own SSID, for example PA3EFR-1 and PA3EFR-2.
6. How the time window works
All times are the local time of your computer. A few rules to remember, which apply per beacon:
•	If you enter only a start date without a time, the beacon starts on that date at 00:00 (if that is today, it starts immediately).
•	A start time that has already passed means: start immediately.
•	An end time only, without an end date, applies to the start date.
•	An end date only, without an end time, means the end of that day (23:59:59).
•	The end must be after the start and after the current moment. Otherwise the script asks for the end date and end time again.
Examples: if you leave everything empty, the beacon transmits immediately and without limit. For an event on a Saturday, enter that date as the start date with start time 08:00, and the same date as the end date with end time 18:00.
7. What happens after the input?
The script first shows an overview of all beacons with callsign, position, the APRS message, symbol, interval time and start and end moment. Then it opens a separate tab for each beacon at https://aprs.fi/<callsign>, with a short pause between the tabs because some browsers ignore tabs opened in rapid succession.
Then each beacon runs according to its own schedule. If the start time has not yet been reached, that beacon waits (the tab on aprs.fi then shows nothing yet). From the start, the script sends the same message every interval, corrected for the time the upload takes. Each transmission gets a log line with the time, beacon (for example #2 PA1ABC) and result (✓ OK or ✗ with an error message), plus a counter of successful transmissions. A beacon stops as soon as its end time is reached, or if the next transmission would fall after that end time. The script stops when all beacons are finished and then shows a summary per beacon.
The message has the form CALL>APRS,TCPIP*:!5204.23N/00418.04E,Comment: position in degrees and minutes, followed by the symbol and your comment. It is a message without a timestamp, so aprs.fi shows the time of reception.
8. Tips and troubleshooting
•	Keep the computer on: the script runs for as long as the window stays open. Sleep mode, shutting down or closing the terminal stops all beacons.
•	Not showing up on aprs.fi? Wait a few minutes after the first transmission and refresh the page. Report the error line if a ✗ is shown.
•	Error when uploading: check the passcode (which belongs to the callsign without SSID), the internet connection and whether port 14580 is blocked by a firewall.
•	Wrong symbol? Check whether you entered one character or a table plus a character. A single character always uses the primary table.
•	Multiple beacons: one script handles all beacons, so separate terminals are not needed. If a tab is missing, open that beacon's link yourself or increase TAB_OPEN_DELAY at the top of the script.
9. Limitations
Each beacon sends one fixed position and no movement, track or waypoints. The beacon is a simple position report: there are no messages, weather data or telemetry. For each transmission a new connection to APRS-IS is set up and closed again, and transmissions from different beacons go one after the other. With many beacons using the same interval, a transmission may therefore leave a few seconds late. So keep the interval reasonable and use the beacon responsibly.

