#!/usr/bin/env python3
"""
IR Scanner – zeigt alle empfangenen IR-Signale
===============================================
Versetzt den Arduino in den SCAN-Modus und gibt alle empfangenen
IR-Codes aus – unabhängig davon ob sie angelernt wurden oder nicht.

Nützlich um:
  - zu prüfen ob ein Gerät überhaupt IR sendet
  - IR-Protokoll und Codes unbekannter Fernbedienungen zu ermitteln
  - die Reichweite und Empfangsqualität zu testen
  - Störquellen (Sonnenlicht, Leuchtstofflampen) zu erkennen

Installation:
    pip install pyserial

Verwendung:
    python3 ir_scan.py                        # einfacher Live-Scan
    python3 ir_scan.py --port /dev/ttyACM0   # Port manuell
    python3 ir_scan.py --log scan.csv         # zusätzlich in Datei speichern
    python3 ir_scan.py --filter NEC           # nur NEC-Protokoll anzeigen
    python3 ir_scan.py --unique               # jeden Code nur einmal anzeigen
"""

import serial
import serial.tools.list_ports
import argparse
import time
import sys
import csv
from datetime import datetime
from collections import defaultdict


# ── Bekannte IR-Protokolle (zur Anzeige) ─────────────────────────────────
PROTOCOL_INFO = {
    "NEC":       "Standard (TV, Hifi, viele Geräte)",
    "NECext":    "NEC Extended (32-bit Adresse)",
    "RC5":       "Philips RC5 (ältere Philips-Geräte)",
    "RC6":       "Philips RC6 (neuere Philips, Sky)",
    "SONY":      "Sony SIRC (Sony TV, Audio)",
    "SAMSUNG":   "Samsung",
    "LG":        "LG",
    "PANASONIC": "Panasonic",
    "DENON":     "Denon / Sharp",
    "JVC":       "JVC",
    "KASEIKYO":  "Kaseikyo / Panasonic variant",
    "UNKNOWN":   "Unbekannt / Rohdaten",
}


# ── Serielle Verbindung ───────────────────────────────────────────────────

def find_port() -> str | None:
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        mfr  = (p.manufacturer or "").lower()
        if any(x in desc + mfr for x in ["arduino", "leonardo", "atmega32u4",
                                           "pro micro", "sparkfun"]):
            return p.device
    ports = list(serial.tools.list_ports.comports())
    return ports[0].device if ports else None


def open_serial(port: str | None, baud: int = 9600) -> serial.Serial:
    if port is None:
        port = find_port()
    if port is None:
        print("FEHLER: Kein Arduino gefunden.")
        sys.exit(1)
    print(f"  Verbinde: {port}")
    ser = serial.Serial(port, baud, timeout=2)
    time.sleep(1.8)
    ser.reset_input_buffer()
    return ser


def send(ser: serial.Serial, cmd: str):
    ser.write((cmd + "\n").encode())
    ser.flush()


# ── Scan ──────────────────────────────────────────────────────────────────

def run_scan(ser: serial.Serial,
             logfile:    str | None = None,
             proto_filter: str | None = None,
             unique_only: bool = False):

    # Arduino in Scan-Modus versetzen
    send(ser, "SCAN")
    time.sleep(0.2)
    # READY oder OK:SCAN_MODE lesen
    ser.timeout = 3.0
    while ser.in_waiting or True:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            break
        if "SCAN_MODE" in line or "READY" in line:
            break

    # CSV-Writer vorbereiten
    csvwriter = None
    csvfile   = None
    if logfile:
        csvfile   = open(logfile, "w", newline="", encoding="utf-8")
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(["Zeitstempel", "Protokoll", "Code (hex)",
                            "Adresse (hex)", "Bekannt als"])

    seen_codes: set[str] = set()
    stats: dict[str, int] = defaultdict(int)
    total = 0

    print()
    print("══════════════════════════════════════════════════════════════")
    print("  IR Scanner – Live-Empfang")
    print("  Fernbedienung/Gerät auf den Empfänger richten")
    print("  CTRL+C zum Beenden")
    if proto_filter:
        print(f"  Filter: nur {proto_filter}")
    if unique_only:
        print("  Modus: jeden Code nur einmal")
    print("══════════════════════════════════════════════════════════════\n")
    print(f"  {'Zeit':<10} {'Protokoll':<12} {'Code':<14} {'Adresse':<12} Info")
    print("  " + "─" * 64)

    ser.timeout = 0.5   # kurzes Timeout für live-Ausgabe

    try:
        while True:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            # Nur SCAN-Zeilen verarbeiten
            if not line.startswith("SCAN:"):
                continue

            # Format: SCAN:<protokoll>:<hex-code>:<hex-adresse>
            parts = line.split(":")
            if len(parts) < 4:
                continue

            proto   = parts[1]
            code    = parts[2]
            address = parts[3]
            ts      = datetime.now().strftime("%H:%M:%S")

            # Filter
            if proto_filter and proto_filter.upper() not in proto.upper():
                continue

            # Unique-Filter
            unique_key = f"{proto}:{code}"
            if unique_only and unique_key in seen_codes:
                continue
            seen_codes.add(unique_key)

            # Protokoll-Info
            info = ""
            for k, v in PROTOCOL_INFO.items():
                if k.upper() in proto.upper():
                    info = v
                    break

            # Ausgabe
            print(f"  {ts:<10} {proto:<12} {code:<14} {address:<12} {info}")

            # Statistik
            stats[proto] += 1
            total += 1

            # CSV
            if csvwriter:
                csvwriter.writerow([ts, proto, code, address, info])
                csvfile.flush()

    except KeyboardInterrupt:
        pass
    finally:
        # Zurück in Normalmodus
        send(ser, "NORMAL")
        if csvfile:
            csvfile.close()

    # Zusammenfassung
    print(f"\n  {'─' * 64}")
    print(f"  Empfangen: {total} Signal(e)")
    if stats:
        print(f"  Protokolle:")
        for proto, count in sorted(stats.items(), key=lambda x: -x[1]):
            info = next((v for k, v in PROTOCOL_INFO.items()
                         if k.upper() in proto.upper()), "")
            print(f"    {proto:<14} {count:>4}×   {info}")
    if logfile:
        print(f"\n  Gespeichert in: {logfile}")


# ── Einstiegspunkt ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="IR Scanner – zeigt alle empfangenen IR-Signale"
    )
    parser.add_argument("--port",    type=str,
                        help="Serieller Port (z.B. /dev/ttyACM0)")
    parser.add_argument("--baud",    type=int, default=9600)
    parser.add_argument("--log",     type=str, metavar="DATEI",
                        help="Ausgabe zusätzlich in CSV-Datei speichern")
    parser.add_argument("--filter",  type=str, metavar="PROTOKOLL",
                        help="Nur bestimmtes Protokoll anzeigen (z.B. NEC)")
    parser.add_argument("--unique",  action="store_true",
                        help="Jeden Code nur einmal anzeigen")
    args = parser.parse_args()

    ser = open_serial(args.port, args.baud)

    try:
        run_scan(ser,
                 logfile=args.log,
                 proto_filter=args.filter,
                 unique_only=args.unique)
    finally:
        ser.close()
        print("\n  Scanner beendet.")


if __name__ == "__main__":
    main()
