#!/usr/bin/env python3
"""APRS Baken - zendt vanaf een of meer vaste posities APRS-positieberichten naar APRS-IS.

Per baken wordt gevraagd:
    callsign, GPS-positie, comment, symbool, intervaltijd (minuten),
    startdatum (default vandaag), starttijd (default nu),
    einddatum (default oneindig), eindtijd (default oneindig)

Na elk baken wordt gevraagd of er nog een baken voorbereid moet worden
(default: nee). Bij 'nee' wordt voor elk baken een eigen tabblad
https://aprs.fi/<callsign> in de browser geopend en starten alle bakens
op hun eigen starttijdstip. Elk baken stopt op zijn eigen eindtijdstip;
bij oneindige bakens stop je met Ctrl+C.
"""

import datetime
import os
import re
import sys
import time
import webbrowser

import aprslib


APRS_CODES_FILE = "APRS_Codes.txt"
APRS_SERVER_PORT = 14580          # zelfde als in aprs.py (aprslib-standaardserver)
TAB_OPEN_DELAY = 0.7              # seconden tussen het openen van browsertabs

# Standaardsymbool: scout ("/," = Boy Scouts, primaire tabel)
DEFAULT_SYMBOL = "/,"

# Veelgebruikte symbolen (primaire tabel '/'), te tonen met '?' bij de invoer
COMMON_SYMBOLS = [
    (",", "scout"),
    ("-", "huis / vast station"),
    ("r", "antenne"),
    ("#", "digipeater"),
    ("_", "weerstation"),
    (">", "auto"),
    ("b", "fiets"),
    ("[", "wandelaar / jogger"),
    ("<", "motor"),
    ("k", "vrachtwagen"),
]

MAX_COMMENT_LEN = 43              # APRS-limiet voor comment bij een positiebericht
MIN_CALL_LEN = 3                  # kortste callsign (zonder SSID)
MAX_CALL_LEN = 9                  # langste callsign (zonder SSID), bv. PA007JOTA
DEFAULT_INTERVAL_MIN = 10         # minuten
MIN_INTERVAL_MIN = 1              # minuten
RECOMMENDED_INTERVAL_MIN = 10     # kortere intervallen zijn onwenselijk voor vaste stations

# Herkent bv. "49.98172°N 6.08968°E" of "50.39012°N -0.02114°E"
COORD_RE = re.compile(
    r"(-?[\d.]+)\s*°?\s*([NS])\s+(-?[\d.]+)\s*°?\s*([EW])",
    re.IGNORECASE,
)
# Herkent bv. "52.0705, 4.3007" of "52.0705 -4.3007"
DECIMAL_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$")


# ---------------------------------------------------------------------------
# Passcode (zelfde werkwijze als in aprs.py)
# ---------------------------------------------------------------------------

def read_aprs_codes(path=APRS_CODES_FILE):
    """Leest 'callsign passcode'-regels uit APRS_Codes.txt (SSID genegeerd)."""
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
    """Zoekt de passcode in APRS_Codes.txt, anders vragen aan de gebruiker.

    Een eenmaal bekende passcode wordt onthouden, zodat bij meerdere bakens
    met dezelfde callsign niet opnieuw gevraagd wordt.
    """
    base_call = call.split("-")[0].upper()

    if base_call in _PASSCODE_CACHE:
        return _PASSCODE_CACHE[base_call]

    codes = read_aprs_codes()

    if base_call in codes:
        print(f"Passcode voor {call} gevonden in {APRS_CODES_FILE}.\n")
        code = codes[base_call]
    else:
        print(f"Callsign {base_call} staat niet in {APRS_CODES_FILE}.")
        code = input(
            f"Go to https://www.iz3mez.it/aprs-passcode/ for passcode. "
            f"Passcode voor {call}: "
        ).strip()

    _PASSCODE_CACHE[base_call] = code
    return code


# ---------------------------------------------------------------------------
# Invoer
# ---------------------------------------------------------------------------

def parse_position(text):
    """
    Accepteert:
        52.0705, 4.3007
        52.0705°N 4.3007°E
        50.39012°N -0.02114°E
    en geeft (lat, lon) als floats terug.
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
                "Ongeldige positie. Gebruik bv. '52.0705, 4.3007' "
                "of '52.0705°N 4.3007°E'."
            )
        lat, lon = float(m.group(1)), float(m.group(2))

    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"Ongeldige latitude: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"Ongeldige longitude: {lon}")

    return lat, lon


def parse_date(text):
    """Accepteert DD-MM-YYYY, DD/MM/YYYY of YYYY-MM-DD."""
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError("Ongeldige datum. Gebruik DD-MM-YYYY, bv. 24-12-2026.")


def parse_time(text):
    """Accepteert HH:MM of HH:MM:SS."""
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    raise ValueError("Ongeldige tijd. Gebruik HH:MM, bv. 21:30.")


def ask(prompt, parser=None):
    """Vraagt net zo lang tot de invoer geldig is."""
    while True:
        raw = input(prompt).strip()
        try:
            return parser(raw) if parser else raw
        except ValueError as e:
            print(f"  ! {e}")


def parse_interval_minutes(text):
    """Intervaltijd in hele minuten; leeg = default, minimaal 1 minuut."""
    if not text:
        return DEFAULT_INTERVAL_MIN
    try:
        minutes = int(text)
    except ValueError:
        raise ValueError("Geef een geheel aantal minuten op, bv. 10.")
    if minutes < MIN_INTERVAL_MIN:
        raise ValueError(f"Intervaltijd moet minstens {MIN_INTERVAL_MIN} minuut zijn.")
    return minutes


def parse_symbol(text):
    """
    Accepteert:
        ''    -> default (scout)
        ','   -> 1 teken: symbool uit de primaire tabel ('/')
        '/,'  -> 2 tekens: tabel + symbool
        '\\,' -> alternatieve tabel (tweede teken is het symbool)
        '?'   -> toont een lijst met veelgebruikte symbolen
    Geeft (tabel, symbool) terug.
    """
    if not text:
        text = DEFAULT_SYMBOL

    if text == "?":
        print("  Veelgebruikte symbolen (primaire tabel, vul alleen het teken in):")
        for ch, name in COMMON_SYMBOLS:
            print(f"    {ch}  {name}")
        print("  Volledige lijst: http://www.aprs.org/symbols/symbolsX.txt")
        print("  Tweetekens-invoer = tabel + symbool, bv. '/,' of '\\,' (alternatieve tabel).")
        raise ValueError("Geef nu een symbool op.")

    if len(text) == 1:
        table, code = "/", text
    elif len(text) == 2:
        table, code = text[0], text[1]
    else:
        raise ValueError("Geef 1 teken (primaire tabel) of 2 tekens (tabel + symbool) op.")

    if table not in ("/", "\\") and not table.isalnum():
        raise ValueError("Het tabelteken moet '/' of '\\' zijn (of 0-9/A-Z als overlay).")
    if table not in ("/", "\\") and not (table.isdigit() or table.isupper()):
        raise ValueError("Een overlay moet een cijfer of hoofdletter zijn.")
    if not ("!" <= code <= "~"):
        raise ValueError("Het symbool moet een zichtbaar ASCII-teken zijn ('!' t/m '~').")

    return table, code


def parse_callsign(text):
    """
    Controleert de callsign: 3 t/m 9 letters/cijfers (met minstens één letter
    en één cijfer), optioneel gevolgd door een SSID (-0 t/m -99).
    Voorbeelden: PA3EFR, PA24DWL, PA007JOTA, PA3EFR-5.
    """
    call = text.strip().upper()
    if not re.fullmatch(rf"[A-Z0-9]{{{MIN_CALL_LEN},{MAX_CALL_LEN}}}(-\d{{1,2}})?", call):
        raise ValueError(
            f"Ongeldige callsign: {MIN_CALL_LEN} t/m {MAX_CALL_LEN} letters/cijfers, "
            "optioneel met SSID (bv. PA3EFR, PA24DWL, PA007JOTA of PA3EFR-5)."
        )
    base = call.split("-")[0]
    if not (any(c.isalpha() for c in base) and any(c.isdigit() for c in base)):
        raise ValueError("Een callsign bevat minstens één letter en één cijfer.")
    return call



def get_beacon_input(number):
    """Vraagt alle gegevens voor één baken en geeft een config-dict terug."""
    print("\n" + "-" * 60)
    print(f"Baken {number}")
    print("-" * 60)

    call = ask("Callsign: ", parse_callsign)
    code = get_aprs_passcode(call)

    lat, lon = ask("GPS positie (bv. 52.0705, 4.3007): ", parse_position)

    comment = input("Comment: ").strip()
    if len(comment) > MAX_COMMENT_LEN:
        print(f"  ! Comment is langer dan {MAX_COMMENT_LEN} tekens en wordt ingekort.")
        comment = comment[:MAX_COMMENT_LEN]

    sym_table, sym_code = ask(
        f"Symbool (teken uit APRS-symbolenlijst, '?' voor hulp) [{DEFAULT_SYMBOL} scout]: ",
        parse_symbol,
    )

    interval_min = ask(
        f"Intervaltijd in minuten (min. {MIN_INTERVAL_MIN}) [{DEFAULT_INTERVAL_MIN}]: ",
        parse_interval_minutes,
    )
    if interval_min < RECOMMENDED_INTERVAL_MIN:
        print(
            f"  ! Let op: voor een vast baken wordt een intervaltijd van minstens "
            f"{RECOMMENDED_INTERVAL_MIN} minuten aangeraden."
        )
    interval = interval_min * 60  # seconden

    now = datetime.datetime.now().replace(microsecond=0)

    # --- Start ---
    start_date = ask("Startdatum (DD-MM-YYYY) [vandaag]: ", lambda t: parse_date(t) if t else now.date())
    start_time = ask("Starttijd (HH:MM) [nu]: ", lambda t: parse_time(t) if t else None)

    if start_time is None:
        # Geen starttijd: nu als de datum vandaag is, anders 00:00 op die datum.
        start = now if start_date == now.date() else datetime.datetime.combine(start_date, datetime.time(0, 0))
    else:
        start = datetime.datetime.combine(start_date, start_time)

    # --- Einde ---
    while True:
        end_date = ask("Einddatum (DD-MM-YYYY) [oneindig]: ", lambda t: parse_date(t) if t else None)
        end_time = ask("Eindtijd (HH:MM) [oneindig]: ", lambda t: parse_time(t) if t else None)

        if end_date is None and end_time is None:
            end = None
            break

        if end_date is None:
            end_date = start.date()           # alleen eindtijd: op de startdatum
        if end_time is None:
            end_time = datetime.time(23, 59, 59)  # alleen einddatum: einde van die dag

        end = datetime.datetime.combine(end_date, end_time)

        if end <= max(start, now):
            print("  ! Het einde moet na het begin (en na het huidige moment) liggen. Probeer opnieuw.")
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
    """j/ja/y/yes -> True; n/nee/no of leeg -> False (default: nee)."""
    t = text.strip().lower()
    if t in ("", "n", "nee", "no"):
        return False
    if t in ("j", "ja", "y", "yes"):
        return True
    raise ValueError("Antwoord met j (ja) of n (nee).")


def collect_beacons():
    """Vraagt bakens op tot de gebruiker 'nee' antwoordt op 'nog een baken?'."""
    beacons = []

    while True:
        beacons.append(get_beacon_input(len(beacons) + 1))

        if not ask(
            f"\nNog een baken voorbereiden? (j/N) [{len(beacons)} voorbereid]: ",
            parse_yes_no,
        ):
            return beacons


# ---------------------------------------------------------------------------
# APRS
# ---------------------------------------------------------------------------

def aprs_pos(call, lat, lon, sym_table, sym_code, comment):
    """
    APRS ongecomprimeerde positie zonder timestamp:
        CALL>APRS,TCPIP*:!DDMM.mmN<tabel>DDDMM.mmE<symbool><comment>
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

    # tabel: '/' = primair, '\\' = alternatief (of overlay-teken 0-9/A-Z)
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
# Uitvoering van meerdere bakens
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class Beacon:
    """Runtime-status van één baken."""

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
        self.next_tx = None   # wordt gezet bij het starten van de planning

    @property
    def label(self):
        return f"#{self.number} {self.call}"

    def stop(self, reason):
        self.done = True
        print(f"[{fmt_dt(datetime.datetime.now())}] [{self.label}] {reason}")


def print_overview(beacons):
    print("\n" + "=" * 60)
    print(f"Overzicht: {len(beacons)} baken(s)")
    print("=" * 60)

    for b in beacons:
        c = b.cfg
        print(f"\nBaken {b.number}: {b.call}")
        print(f"  Positie     : {c['lat']:.6f}, {c['lon']:.6f}")
        print(f"  APRS        : {b.info}")
        print(f"  Symbool     : {c['sym_table']}{c['sym_code']}")
        print(f"  Intervaltijd: {c['interval_min']} min")
        print(f"  Start       : {fmt_dt(b.start)}")
        print(f"  Einde       : {fmt_dt(b.end) if b.end else 'oneindig (stop met Ctrl+C)'}")

    print("\n" + "=" * 60)


def open_browser_tabs(beacons):
    """Opent voor elk baken een eigen tabblad op aprs.fi."""
    print("\nBrowsertabs openen:")
    for b in beacons:
        print(f"  {b.label}: {b.url}")
        webbrowser.open_new_tab(b.url)
        time.sleep(TAB_OPEN_DELAY)   # browsers slikken anders soms snelle opeenvolgende tabs
    print()


def run_beacons(beacons):
    print_overview(beacons)
    open_browser_tabs(beacons)

    now = datetime.datetime.now()
    for b in beacons:
        # Starttijd in het verleden: meteen beginnen
        b.next_tx = b.start if b.start > now else now
        if b.start > now:
            print(f"[{b.label}] wacht tot starttijd {fmt_dt(b.start)}")

    try:
        while not all(b.done for b in beacons):
            for b in beacons:
                if b.done:
                    continue

                now = datetime.datetime.now()

                if b.end is not None and now >= b.end:
                    b.stop("Eindtijd bereikt. Baken gestopt.")
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

                # Vast interval, gecorrigeerd voor de tijd die het uploaden kostte
                b.next_tx += b.interval
                if b.next_tx <= datetime.datetime.now():
                    b.next_tx = datetime.datetime.now() + b.interval

                if b.end is not None and b.next_tx >= b.end:
                    b.stop("Volgende zending valt na de eindtijd. Baken gestopt.")

            time.sleep(1.0)   # korte slaap: Ctrl+C reageert direct, tijden blijven nauwkeurig

    except KeyboardInterrupt:
        print("\n\nGestopt door gebruiker.")

    finally:
        print("\n" + "=" * 60)
        print("Samenvatting")
        for b in beacons:
            print(f"  {b.label}: {b.ok}/{b.tot} OK | {b.url}")
        print("=" * 60)


def main():
    print("=" * 60)
    print("APRS Baken (vaste posities)")
    print("=" * 60)

    try:
        cfgs = collect_beacons()
    except KeyboardInterrupt:
        print("\n\nGestopt door gebruiker.")
        sys.exit(0)

    beacons = [Beacon(i, cfg) for i, cfg in enumerate(cfgs, start=1)]
    run_beacons(beacons)


if __name__ == "__main__":
    main()