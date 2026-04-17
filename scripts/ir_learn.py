#!/usr/bin/env python3
"""
IR Transceiver – Anlern- und Verwaltungsskript
===============================================
Kommuniziert mit dem Arduino ir_transceiver.ino über Serial.

Installation:
    pip install pyserial

Verwendung:
    python3 ir_learn.py                              # interaktives Menü
    python3 ir_learn.py --port /dev/ttyACM0         # Port manuell angeben
    python3 ir_learn.py --learn KEY_F13 KEY_F14     # direkt anlernen
    python3 ir_learn.py --send KEY_F13              # IR-Code senden
    python3 ir_learn.py --dump                      # alle Mappings anzeigen
    python3 ir_learn.py --clear                     # alle Mappings löschen
    python3 ir_learn.py --list-keys                 # verfügbare Keynamen
"""

import serial
import serial.tools.list_ports
import argparse
import time
import sys


# ── Serielle Verbindung ───────────────────────────────────────────────────

def find_port() -> str | None:
    """Sucht automatisch nach dem Arduino."""
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        mfr  = (p.manufacturer or "").lower()
        if any(x in desc + mfr for x in ["arduino", "leonardo", "atmega32u4",
                                           "pro micro", "sparkfun"]):
            return p.device
    # Fallback: ersten verfügbaren Port nehmen
    ports = list(serial.tools.list_ports.comports())
    return ports[0].device if ports else None


def open_serial(port: str | None, baud: int = 9600) -> serial.Serial:
    if port is None:
        port = find_port()
    if port is None:
        print("FEHLER: Kein serieller Port gefunden.")
        sys.exit(1)
    print(f"  Verbinde: {port} @ {baud} Baud ...")
    ser = serial.Serial(port, baud, timeout=15)
    time.sleep(1.8)          # Arduino Reset abwarten
    ser.reset_input_buffer()
    return ser


def readline(ser: serial.Serial, timeout: float = 12.0) -> str:
    ser.timeout = timeout
    line = ser.readline().decode("utf-8", errors="replace").strip()
    if not line:
        raise TimeoutError("Keine Antwort vom Arduino")
    return line


def send(ser: serial.Serial, cmd: str):
    ser.write((cmd + "\n").encode())
    ser.flush()


# ── Befehle ───────────────────────────────────────────────────────────────

def cmd_ready(ser: serial.Serial):
    try:
        line = readline(ser, timeout=5.0)
        if line.startswith("READY"):
            parts = line.split(":")
            print(f"  Arduino bereit – {parts[1]}/{parts[2]} Slots belegt\n")
        else:
            print(f"  Arduino: {line}\n")
    except TimeoutError:
        print("  (Kein READY – Arduino evtl. schon aktiv)\n")


def cmd_dump(ser: serial.Serial):
    send(ser, "DUMP")
    entries = []
    while True:
        line = readline(ser, timeout=3.0)
        if line == "DUMP_END":
            break
        if line.startswith("DUMP:"):
            p = line.split(":")
            if len(p) >= 4:
                entries.append((p[1], p[2], p[3]))
    if not entries:
        print("  Keine Mappings gespeichert.")
        return
    print(f"  {'#':<4} {'Taste':<16} {'IR-Code'}")
    print("  " + "─" * 36)
    for idx, key, code in entries:
        print(f"  {idx:<4} {key:<16} {code}")


def cmd_clear(ser: serial.Serial):
    if input("  Wirklich alle löschen? [j/N] ").strip().lower() != "j":
        print("  Abgebrochen.")
        return
    send(ser, "CLEAR")
    print(f"  {readline(ser, 3.0)}")


def cmd_list_keys(ser: serial.Serial):
    send(ser, "LIST")
    keys = []
    while True:
        line = readline(ser, 3.0)
        if line == "LIST_END":
            break
        keys.append(line)
    col = 4
    for i in range(0, len(keys), col):
        print("  " + "  ".join(f"{k:<16}" for k in keys[i:i+col]))


def cmd_learn_one(ser: serial.Serial, keyname: str) -> bool:
    send(ser, f"LEARN:{keyname}")
    line = readline(ser, 3.0)
    if line.startswith("ERROR"):
        print(f"  ✗ {line}")
        return False
    if line != "WAITING":
        print(f"  Unerwartete Antwort: {line}")
        return False
    print(f"  → Fernbedienung auf Empfänger richten und Taste drücken ...",
          end="", flush=True)
    try:
        resp = readline(ser, 13.0)
    except TimeoutError:
        print("\n  ✗ Timeout")
        return False
    if resp.startswith("LEARNED:"):
        parts = resp.split(":")
        print(f"\n  ✓ {parts[1]} = {parts[2]}")
        return True
    print(f"\n  ✗ {resp}")
    return False


def cmd_learn_list(ser: serial.Serial, keynames: list[str]):
    print(f"\n  {len(keynames)} Taste(n) werden angelernt:\n")
    for i, kn in enumerate(keynames, 1):
        print(f"  [{i}/{len(keynames)}] {kn}")
        cmd_learn_one(ser, kn)
        time.sleep(0.3)
    print()


def cmd_send(ser: serial.Serial, keyname: str):
    send(ser, f"SEND:{keyname}")
    resp = readline(ser, 3.0)
    if resp.startswith("SENT:"):
        print(f"  ✓ Gesendet: {keyname}")
    else:
        print(f"  ✗ {resp}")


def cmd_interactive(ser: serial.Serial):
    print("╔══════════════════════════════════════╗")
    print("║     IR Transceiver – Anlern-Tool     ║")
    print("╚══════════════════════════════════════╝\n")
    while True:
        print("  1  Taste anlernen")
        print("  2  IR-Code senden")
        print("  3  Alle Mappings anzeigen")
        print("  4  Alle Mappings löschen")
        print("  5  Verfügbare Keynamen anzeigen")
        print("  0  Beenden\n")
        c = input("  Auswahl: ").strip()
        print()
        if c == "1":
            cmd_list_keys(ser)
            print()
            kn = input("  Keyname: ").strip().upper()
            cmd_learn_one(ser, kn)
        elif c == "2":
            kn = input("  Keyname senden: ").strip().upper()
            cmd_send(ser, kn)
        elif c == "3":
            cmd_dump(ser)
        elif c == "4":
            cmd_clear(ser)
        elif c == "5":
            cmd_list_keys(ser)
        elif c == "0":
            print("  Auf Wiedersehen!")
            break
        else:
            print("  Ungültige Auswahl.")
        print()


# ── Einstiegspunkt ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="IR Transceiver Anlern-Tool")
    parser.add_argument("--port",      type=str)
    parser.add_argument("--baud",      type=int, default=9600)
    parser.add_argument("--learn",     nargs="+", metavar="KEY")
    parser.add_argument("--send",      type=str,  metavar="KEY")
    parser.add_argument("--dump",      action="store_true")
    parser.add_argument("--clear",     action="store_true")
    parser.add_argument("--list-keys", action="store_true")
    args = parser.parse_args()

    ser = open_serial(args.port, args.baud)
    cmd_ready(ser)

    try:
        if args.learn:
            cmd_learn_list(ser, [k.upper() for k in args.learn])
        elif args.send:
            cmd_send(ser, args.send.upper())
        elif args.dump:
            cmd_dump(ser)
        elif args.clear:
            cmd_clear(ser)
        elif args.list_keys:
            cmd_list_keys(ser)
        else:
            cmd_interactive(ser)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
