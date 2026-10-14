#!/usr/bin/env python3
"""APRS Beacon - sends APRS position reports to APRS-IS from one or more fixed positions.

For each beacon the following is asked:
    callsign, GPS position, comment, symbol, interval (minutes),
    start date (default today), start time (default now),
    end date (default infinite), end time (default infinite)

After each beacon you are asked whether another beacon should be prepared
(default: no). On 'no', a separate browser tab https://aprs.fi/<callsign>
is opened for each beacon and all beacons start at their own start time.
Each beacon stops at its own end time; for infinite beacons, stop with Ctrl+C.
"""

import datetime
import os
import re
import sys
import time
import webbrowser

import aprslib


APRS_CODES_FILE = "APRS_Codes.txt"
APRS_SERVER_PORT = 14580          # same as in aprs.py (aprslib default server)
TAB_OPEN_DELAY = 0.7              # seconds between opening browser tabs

# Default symbol: scout ("/," = Boy Scouts, primary table)
DEFAULT_SYMBOL = "/,"

# Commonly used symbols (primary table '/'), shown with '?' at the prompt
COMMON_SYMBOLS = [
    (",", "scout"),
    ("-", "house / fixed station"),
    ("r", "antenna"),
    ("#", "digipeater"),
    ("_", "weather station"),
    (">", "car"),
    ("b", "bicycle"),
    ("[", "walker / jogger"),
    ("<", "motorcycle"),
    ("k", "truck"),
]

MAX_COMMENT_LEN = 43              # APRS limit for the comment in a position report
MIN_CALL_LEN = 3                  # shortest callsign (without SSID)
MAX_CALL_LEN = 9                  # longest callsign (without SSID), e.g. PA007JOTA
DEFAULT_INTERVAL_MIN = 10         # minutes
MIN_INTERVAL_MIN = 1              # minutes
RECOMMENDED_INTERVAL_MIN = 10     # shorter intervals are undesirable for fixed stations

# Recognizes e.g. "49.98172°N 6.08968°E" or "50.39012°N -0.02114°E"
COORD_RE = re.compile(
    r"(-?[\d.]+)\s*°?\s*([NS])\s+(-?[\d.]+)\s*°?\s*([EW])",
    re.IGNORECASE,
)
# Recognizes e.g. "52.0705, 4.3007" or "52.0705 -4.3007"
DECIMAL_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$")


# ---------------------------------------------------------------------------
# Passcode (same approach as in aprs.py)
# ---------------------------------------------------------------------------

def read_aprs_codes(path=APRS_CODES_FILE):
    """Reads 'callsign passcode' lines from APRS_Codes.txt (SSID ignored)."""
    codes = {}

    if not os.path.isfile(path):
        return codes

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            parts = line.split()

            if len(parts) < 2:
                continue

            codes[parts[0].upper().split("-")[0]] = parts[1].strip()

    return codes


_PASSCODE_CACHE = {}


def get_aprs_passcode(call):
    """Looks up the passcode in APRS_Codes.txt, otherwise asks the user.

    Once a passcode is known it is remembered, so that for multiple beacons
    with the same callsign it is not asked for again.
    """
    base_call = call.split("-")[0].upper()

    if base_call in _PASSCODE_CACHE:
        return _PASSCODE_CACHE[base_call]

    codes = read_aprs_codes()

    if base_call in codes:
        print(f"Passcode for {call} found in {APRS_CODES_FILE}.\n")
        code = codes[base_call]
    else:
        print(f"Callsign {base_call} is not in {APRS_CODES_FILE}.")
        code = input(
            f"Go to https://www.iz3mez.it/aprs-passcode/ for passcode. "
            f"Passcode for {call}: "
        ).strip()

    _PASSCODE_CACHE[base_call] = code
    return code


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def parse_position(text):
    """
    Accepts:
        52.0705, 4.3007
        52.0705°N 4.3007°E
        50.39012°N -0.02114°E
    and returns (lat, lon) as floats.
    """
    m = COORD_RE.search(text)

    if m:
        lat = float(m.group(1))
        if lat >= 0 and m.group(2).upper() == "S":
            lat = -lat

        lon = float(m.group(3))
        if lon >= 0 and m.group(4).upper() == "W":
            lon = -lon
    else:
        m = DECIMAL_RE.match(text)
        if not m:
            raise ValueError(
                "Invalid position. Use e.g. '52.0705, 4.3007' "
                "or '52.0705°N 4.3007°E'."
            )
        lat, lon = float(m.group(1)), float(m.group(2))

    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"Invalid latitude: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"Invalid longitude: {lon}")

    return lat, lon


def parse_date(text):
    """Accepts DD-MM-YYYY, DD/MM/YYYY or YYYY-MM-DD."""
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError("Invalid date. Use DD-MM-YYYY, e.g. 24-12-2026.")


def parse_time(text):
    """Accepts HH:MM or HH:MM:SS."""
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    raise ValueError("Invalid time. Use HH:MM, e.g. 21:30.")


def ask(prompt, parser=None):
    """Keeps asking until the input is valid."""
    while True:
        raw = input(prompt).strip()
        try:
            return parser(raw) if parser else raw
        except ValueError as e:
            print(f"  ! {e}")


def parse_interval_minutes(text):
    """Interval in whole minutes; empty = default, minimum 1 minute."""
    if not text:
        return DEFAULT_INTERVAL_MIN
    try:
        minutes = int(text)
    except ValueError:
        raise ValueError("Enter a whole number of minutes, e.g. 10.")
    if minutes < MIN_INTERVAL_MIN:
        raise ValueError(f"The interval must be at least {MIN_INTERVAL_MIN} minute.")
    return minutes


def parse_symbol(text):
    """
    Accepts:
        ''    -> default (scout)
        ','   -> 1 character: symbol from the primary table ('/')
        '/,'  -> 2 characters: table + symbol
        '\\,' -> alternate table (second character is the symbol)
        '?'   -> shows a list of commonly used symbols
    Returns (table, symbol).
    """
    if not text:
        text = DEFAULT_SYMBOL

    if text == "?":
        print("  Commonly used symbols (primary table, enter only the character):")
        for ch, name in COMMON_SYMBOLS:
            print(f"    {ch}  {name}")
        print("  Full list: http://www.aprs.org/symbols/symbolsX.txt")
        print("  Two-character input = table + symbol, e.g. '/,' or '\\,' (alternate table).")
        raise ValueError("Now enter a symbol.")

    if len(text) == 1:
        table, code = "/", text
    elif len(text) == 2:
        table, code = text[0], text[1]
    else:
        raise ValueError("Enter 1 character (primary table) or 2 characters (table + symbol).")

    if table not in ("/", "\\") and not table.isalnum():
        raise ValueError("The table character must be '/' or '\\' (or 0-9/A-Z as an overlay).")
    if table not in ("/", "\\") and not (table.isdigit() or table.isupper()):
        raise ValueError("An overlay must be a digit or an uppercase letter.")
    if not ("!" <= code <= "~"):
        raise ValueError("The symbol must be a visible ASCII character ('!' through '~').")

    return table, code


def parse_callsign(text):
    """
    Validates the callsign: 3 to 9 letters/digits (with at least one letter
    and one digit), optionally followed by an SSID (-0 to -99).
    Examples: PA3EFR, PA24DWL, PA007JOTA, PA3EFR-5.
    """
    call = text.strip().upper()
    if not re.fullmatch(rf"[A-Z0-9]{{{MIN_CALL_LEN},{MAX_CALL_LEN}}}(-\d{{1,2}})?", call):
        raise ValueError(
            f"Invalid callsign: {MIN_CALL_LEN} to {MAX_CALL_LEN} letters/digits, "
            "optionally with SSID (e.g. PA3EFR, PA24DWL, PA007JOTA or PA3EFR-5)."
        )
    base = call.split("-")[0]
    if not (any(c.isalpha() for c in base) and any(c.isdigit() for c in base)):
        raise ValueError("A callsign contains at least one letter and one digit.")
    return call



def get_beacon_input(number):
    """Asks for all details of one beacon and returns a config dict."""
    print("\n" + "-" * 60)
    print(f"Beacon {number}")
    print("-" * 60)

    call = ask("Callsign: ", parse_callsign)
    code = get_aprs_passcode(call)

    lat, lon = ask("GPS position (e.g. 52.0705, 4.3007): ", parse_position)

    comment = input("Comment: ").strip()
    if len(comment) > MAX_COMMENT_LEN:
        print(f"  ! Comment is longer than {MAX_COMMENT_LEN} characters and will be truncated.")
        comment = comment[:MAX_COMMENT_LEN]

    sym_table, sym_code = ask(
        f"Symbol (character from APRS symbol list, '?' for help) [{DEFAULT_SYMBOL} scout]: ",
        parse_symbol,
    )

    interval_min = ask(
        f"Interval in minutes (min. {MIN_INTERVAL_MIN}) [{DEFAULT_INTERVAL_MIN}]: ",
        parse_interval_minutes,
    )
    if interval_min < RECOMMENDED_INTERVAL_MIN:
        print(
            f"  ! Note: for a fixed beacon an interval of at least "
            f"{RECOMMENDED_INTERVAL_MIN} minutes is recommended."
        )
    interval = interval_min * 60  # seconds

    now = datetime.datetime.now().replace(microsecond=0)

    # --- Start ---
    start_date = ask("Start date (DD-MM-YYYY) [today]: ", lambda t: parse_date(t) if t else now.date())
    start_time = ask("Start time (HH:MM) [now]: ", lambda t: parse_time(t) if t else None)

    if start_time is None:
        # No start time: now if the date is today, otherwise 00:00 on that date.
        start = now if start_date == now.date() else datetime.datetime.combine(start_date, datetime.time(0, 0))
    else:
        start = datetime.datetime.combine(start_date, start_time)

    # --- End ---
    while True:
        end_date = ask("End date (DD-MM-YYYY) [infinite]: ", lambda t: parse_date(t) if t else None)
        end_time = ask("End time (HH:MM) [infinite]: ", lambda t: parse_time(t) if t else None)

        if end_date is None and end_time is None:
            end = None
            break

        if end_date is None:
            end_date = start.date()           # end time only: on the start date
        if end_time is None:
            end_time = datetime.time(23, 59, 59)  # end date only: end of that day

        end = datetime.datetime.combine(end_date, end_time)

        if end <= max(start, now):
            print("  ! The end must be after the start (and after the current moment). Try again.")
            continue
        break

    return {
        "call": call,
        "code": code,
        "lat": lat,
        "lon": lon,
        "comment": comment,
        "sym_table": sym_table,
        "sym_code": sym_code,
        "interval_min": interval_min,
        "interval": interval,
        "start": start,
        "end": end,
    }


def parse_yes_no(text):
    """y/yes -> True; n/no or empty -> False (default: no)."""
    t = text.strip().lower()
    if t in ("", "n", "no"):
        return False
    if t in ("y", "yes"):
        return True
    raise ValueError("Answer with y (yes) or n (no).")


def collect_beacons():
    """Asks for beacons until the user answers 'no' to 'another beacon?'."""
    beacons = []

    while True:
        beacons.append(get_beacon_input(len(beacons) + 1))

        if not ask(
            f"\nPrepare another beacon? (y/N) [{len(beacons)} prepared]: ",
            parse_yes_no,
        ):
            return beacons


# ---------------------------------------------------------------------------
# APRS
# ---------------------------------------------------------------------------

def aprs_pos(call, lat, lon, sym_table, sym_code, comment):
    """
    APRS uncompressed position without timestamp:
        CALL>APRS,TCPIP*:!DDMM.mmN<table>DDDMM.mmE<symbol><comment>
    """
    lat_abs = abs(lat)
    lat_deg = int(lat_abs)
    lat_min = (lat_abs - lat_deg) * 60.0
    lat_dir = "N" if lat >= 0 else "S"

    lon_abs = abs(lon)
    lon_deg = int(lon_abs)
    lon_min = (lon_abs - lon_deg) * 60.0
    lon_dir = "E" if lon >= 0 else "W"

    lat_text = f"{lat_deg:02d}{lat_min:05.2f}{lat_dir}"
    lon_text = f"{lon_deg:03d}{lon_min:05.2f}{lon_dir}"

    # table: '/' = primary, '\\' = alternate (or overlay character 0-9/A-Z)
    info = f"!{lat_text}{sym_table}{lon_text}{sym_code}{comment}"
    packet = f"{call}>APRS,TCPIP*:{info}"

    return packet, info


def upload(call, code, pkt):
    ais = None
    try:
        ais = aprslib.IS(call, passwd=code, port=APRS_SERVER_PORT)
        ais.connect()
        ais.sendall(pkt)
        return True, "OK"
    except Exception as e:
        return False, str(e)
    finally:
        if ais is not None:
            try:
                ais.close()
            except Exception:
                pass



# ---------------------------------------------------------------------------
# Running multiple beacons
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class Beacon:
    """Runtime state of one beacon."""

    def __init__(self, number, cfg):
        self.number = number
        self.cfg = cfg
        self.call = cfg["call"]
        self.interval = datetime.timedelta(seconds=cfg["interval"])
        self.start = cfg["start"]
        self.end = cfg["end"]
        self.pkt, self.info = aprs_pos(
            cfg["call"], cfg["lat"], cfg["lon"],
            cfg["sym_table"], cfg["sym_code"], cfg["comment"],
        )
        self.url = f"https://aprs.fi/{self.call}"
        self.ok = 0
        self.tot = 0
        self.done = False
        self.next_tx = None   # set when the schedule is started

    @property
    def label(self):
        return f"#{self.number} {self.call}"

    def stop(self, reason):
        self.done = True
        print(f"[{fmt_dt(datetime.datetime.now())}] [{self.label}] {reason}")


def print_overview(beacons):
    print("\n" + "=" * 60)
    print(f"Overview: {len(beacons)} beacon(s)")
    print("=" * 60)

    for b in beacons:
        c = b.cfg
        print(f"\nBeacon {b.number}: {b.call}")
        print(f"  Position : {c['lat']:.6f}, {c['lon']:.6f}")
        print(f"  APRS     : {b.info}")
        print(f"  Symbol   : {c['sym_table']}{c['sym_code']}")
        print(f"  Interval : {c['interval_min']} min")
        print(f"  Start    : {fmt_dt(b.start)}")
        print(f"  End      : {fmt_dt(b.end) if b.end else 'infinite (stop with Ctrl+C)'}")

    print("\n" + "=" * 60)


def open_browser_tabs(beacons):
    """Opens a separate aprs.fi tab for each beacon."""
    print("\nOpening browser tabs:")
    for b in beacons:
        print(f"  {b.label}: {b.url}")
        webbrowser.open_new_tab(b.url)
        time.sleep(TAB_OPEN_DELAY)   # browsers sometimes swallow rapid consecutive tabs
    print()


def run_beacons(beacons):
    print_overview(beacons)
    open_browser_tabs(beacons)

    now = datetime.datetime.now()
    for b in beacons:
        # Start time in the past: begin immediately
        b.next_tx = b.start if b.start > now else now
        if b.start > now:
            print(f"[{b.label}] waiting until start time {fmt_dt(b.start)}")

    try:
        while not all(b.done for b in beacons):
            for b in beacons:
                if b.done:
                    continue

                now = datetime.datetime.now()

                if b.end is not None and now >= b.end:
                    b.stop("End time reached. Beacon stopped.")
                    continue

                if now < b.next_tx:
                    continue

                success, msg = upload(b.call, b.cfg["code"], b.pkt)
                b.tot += 1
                b.ok += success
                print(
                    f"[{fmt_dt(datetime.datetime.now())}] [{b.label}] "
                    f"{'✓ OK' if success else '✗ ' + msg}  ({b.ok}/{b.tot})"
                )

                # Fixed interval, corrected for the time the upload took
                b.next_tx += b.interval
                if b.next_tx <= datetime.datetime.now():
                    b.next_tx = datetime.datetime.now() + b.interval

                if b.end is not None and b.next_tx >= b.end:
                    b.stop("Next transmission falls after the end time. Beacon stopped.")

            time.sleep(1.0)   # short sleep: Ctrl+C responds immediately, timing stays accurate

    except KeyboardInterrupt:
        print("\n\nStopped by user.")

    finally:
        print("\n" + "=" * 60)
        print("Summary")
        for b in beacons:
            print(f"  {b.label}: {b.ok}/{b.tot} OK | {b.url}")
        print("=" * 60)


def main():
    print("=" * 60)
    print("APRS Beacon (fixed positions)")
    print("=" * 60)

    try:
        cfgs = collect_beacons()
    except KeyboardInterrupt:
        print("\n\nStopped by user.")
        sys.exit(0)

    beacons = [Beacon(i, cfg) for i, cfg in enumerate(cfgs, start=1)]
    run_beacons(beacons)


if __name__ == "__main__":
    main()