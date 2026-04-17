# ir-usb-hid-transreceiver

A DIY USB IR transceiver that works like a generic keyboard — receive signals from any infrared remote control and send IR commands to any device. Built around an ATmega32U4 microcontroller and the Adafruit IR Transceiver breakout (product #5990).

Plug it into a Raspberry Pi (or any computer), pair your remote once using the included Python learn script, and from that point on every button press arrives as a standard keyboard keystroke — no drivers, no daemons, no configuration on the host side. A second script lets you scan and inspect raw IR signals from any device without pairing first.

```
Remote Control  ──IR──▶  Adafruit 5990  ──▶  ATmega32U4  ──USB──▶  Raspberry Pi
                                                                     (sees a keyboard)

Raspberry Pi  ──USB──▶  ATmega32U4  ──▶  Adafruit 5990  ──IR──▶  TV / Beamer / etc.
```

---

## Features

- **Universal receiver** — learns any IR remote regardless of brand or protocol (NEC, RC5, RC6, Sony, Samsung, LG, Panasonic, and more)
- **USB HID keyboard** — no drivers needed, works on Windows, macOS, Linux, and Raspberry Pi OS out of the box
- **IR blaster** — send stored IR codes back out to control TVs, beamers, sound systems, and other IR-controlled devices
- **IR scanner** — inspect raw signals from any device without pairing; useful for diagnosing unknown remotes
- **Persistent storage** — up to ~145 key mappings survive power cycles via EEPROM
- **Simple serial protocol** — control everything from Python over the USB serial connection
- **No firmware changes needed** — once flashed, configure entirely from the host via Python scripts

---

## Hardware

### Bill of materials (per device)

| Part | Specification | Source | Approx. cost |
|---|---|---|---|
| ATmega32U4 board | Pro Micro compatible, 5V/16MHz, USB-C | Amazon / DigiKey | €5–8 |
| Adafruit IR Transceiver | Product #5990, 940nm, 38kHz, STEMMA JST PH | Mouser / DigiKey | €6–7 |
| JST PH 4-pin cable | 2mm pitch, 4-pin, ~200mm | Mouser (485-3950) | €1 |
| USB cable | USB-A to USB-C, **data cable** (not charge-only) | — | €1–2 |
| Perfboard | ~4×3cm | — | €0.30 |
| Wire | 0.5mm² solid core, ~15cm | — | €0.10 |
| Solder | Lead-free, 0.5–1mm | — | — |

**Total: approx. €14–18 per device**

> ⚠️ Make sure your USB cable carries data lines. Many cheap USB-C cables are charge-only. If the Pi does not detect the device, try a different cable.

### Why the Adafruit 5990?

The Adafruit IR Transceiver combines a 38kHz IR receiver and two high-power IR emitter LEDs (with onboard N-channel FET driver) on a single board. The emitter side delivers 100–200mA pulse current per LED for up to 10 metres of range. The receiver side demodulates 38kHz IR signals and outputs a clean digital signal. There is no need for external transistors, current-limiting resistors, or decoupling capacitors — all that is handled on the board.

---

## Wiring

Connect the Adafruit 5990 to the ATmega32U4 board using the JST PH 4-pin cable:

| Cable colour | 5990 label | ATmega32U4 pin |
|---|---|---|
| Black | GND | GND |
| Red | VIN | VCC (5V) |
| White | IRin | **Pin 9** (send) |
| Green | IRout | **Pin 2** (receive) |

```
Adafruit 5990                ATmega32U4
─────────────                ──────────
GND   (black)  ──────────▶  GND
VIN   (red)    ──────────▶  VCC / 5V
IRin  (white)  ──────────▶  Pin 9   ← Arduino sends IR via this pin
IRout (green)  ──────────▶  Pin 2   ← Arduino reads IR via this pin
```

Point both the receiver and the emitter LEDs towards the device you want to control. A small physical gap between the two is sufficient — the 5990 board already handles this internally.

---

## Flashing the firmware

### Prerequisites

- [Arduino IDE](https://www.arduino.cc/en/software) 2.x
- Board package: **Arduino AVR Boards** (included by default)
- Library: **IRremote** by shirriff, version 4.x or later

Install the IRremote library via the Arduino IDE library manager:
`Sketch → Include Library → Manage Libraries → search "IRremote" → Install`

### Steps

1. Connect the ATmega32U4 board to your computer via USB-C.
2. Open `ir_transceiver.ino` in the Arduino IDE.
3. Select **Tools → Board → Arduino AVR Boards → Arduino Leonardo**.
4. Select **Tools → Port → (the port that appeared when you connected the board)**.
5. Click **Upload** (the arrow button).
6. Wait for "Upload complete". The onboard LED will blink briefly.

> **Important:** Always select **Arduino Leonardo** as the board, not "Pro Micro" or "Arduino Micro". The Leonardo uses the same ATmega32U4 with native USB and has the correct bootloader settings.

Once flashed, the firmware never needs to be changed again. All configuration happens from the host via Python.

---

## Python scripts

Install the only dependency:

```bash
pip install pyserial
```

### ir_learn.py — pair remote buttons to keyboard keys

This script communicates with the firmware over the USB serial connection to store IR code → keyboard key mappings in the device's EEPROM.

#### Interactive mode

```bash
python3 ir_learn.py
```

A menu guides you through all operations.

#### Pair multiple keys in one go (recommended)

```bash
python3 ir_learn.py --learn KEY_F13 KEY_F14 KEY_F15 KEY_F16 KEY_F17 KEY_F18 KEY_F19 KEY_F20 KEY_F21
```

The script will prompt you one key at a time. Point your remote at the transceiver and press the button you want to assign. Once the signal is received, the next key is automatically requested.

```
[1/9] KEY_F13
  → Point remote at receiver and press a button ...
  ✓ KEY_F13 = 0xA1B2C3D4

[2/9] KEY_F14
  → Point remote at receiver and press a button ...
  ✓ KEY_F14 = 0xE5F60718
...
```

#### Re-pair a single key

Run the same command with only the key you want to update. The firmware overwrites the existing mapping for that key:

```bash
python3 ir_learn.py --learn KEY_F15
```

#### Send a stored IR code

```bash
python3 ir_learn.py --send KEY_F13
```

The device will emit the IR signal stored for `KEY_F13` — useful for testing the emitter side or triggering IR devices from a script.

#### Show all stored mappings

```bash
python3 ir_learn.py --dump
```

```
  #    Key              IR code
  ────────────────────────────────────
  0    KEY_F13          0xA1B2C3D4
  1    KEY_F14          0xE5F60718
  2    KEY_F15          0x1234ABCD
```

#### List all available key names

```bash
python3 ir_learn.py --list-keys
```

#### Clear all mappings

```bash
python3 ir_learn.py --clear
```

#### Specify the serial port manually

```bash
python3 ir_learn.py --port /dev/ttyACM0 --learn KEY_F13 KEY_F14
```

The port is detected automatically on most systems. On Linux it is typically `/dev/ttyACM0`, on Windows `COM3` or similar, on macOS `/dev/cu.usbmodem*`.

---

### ir_scan.py — inspect raw IR signals

The scanner puts the device into a passive mode where it reports every received IR signal as raw data — without triggering any keyboard key. This is useful for:

- Checking whether a device emits IR at all
- Discovering the protocol and codes used by an unknown remote
- Testing reception range and angle
- Identifying interference from sunlight or fluorescent lights

```bash
python3 ir_scan.py
```

```
══════════════════════════════════════════════════════════════
  IR Scanner – Live capture
  Point any remote or IR device at the receiver
  CTRL+C to stop
══════════════════════════════════════════════════════════════

  Time       Protocol     Code            Address      Info
  ────────────────────────────────────────────────────────────────
  14:22:01   NEC          0xA1B2C3D4      0x0410       Standard (TV, Hifi)
  14:22:01   NEC          0xA1B2C3D4      0x0410       Standard (TV, Hifi)
  14:22:04   NEC          0xE5F60718      0x0410       Standard (TV, Hifi)
  14:22:09   RC5          0x00000C0C      0x0001       Philips RC5

  ────────────────────────────────────────────────────────────────
  Received: 4 signal(s)
  Protocols:
    NEC            3×   Standard (TV, Hifi, many devices)
    RC5            1×   Philips RC5 (older Philips devices)
```

After CTRL+C the device automatically returns to normal HID keyboard mode.

#### Show each unique code only once

```bash
python3 ir_scan.py --unique
```

#### Filter by protocol

```bash
python3 ir_scan.py --filter NEC
```

#### Save to CSV

```bash
python3 ir_scan.py --log session.csv
```

The CSV file contains columns for timestamp, protocol, code, address, and a human-readable protocol description. Useful for documenting all codes from a device before pairing.

---

## Writing your own Python code

After pairing, the device behaves as a standard USB keyboard. You can use any keyboard input library to react to button presses. The recommended approach is [pynput](https://pypi.org/project/pynput/).

```bash
pip install pynput
```

### Minimal example

```python
from pynput import keyboard
from pynput.keyboard import Key

# Map the keys you assigned during pairing to actions
KEY_MAP = {
    Key.f13: "power_toggle",
    Key.f14: "volume_up",
    Key.f15: "volume_down",
    Key.f16: "mute",
    Key.f17: "input_hdmi1",
    Key.f18: "input_hdmi2",
}

def on_press(key):
    action = KEY_MAP.get(key)
    if action:
        dispatch(action)
    elif key == Key.esc:
        return False  # stop listener

def dispatch(action: str):
    print(f"Action: {action}")
    # Add your logic here:
    # - HTTP request to Home Assistant
    # - MQTT publish
    # - subprocess call
    # - anything else

print("Listening for IR input — press ESC to quit")
with keyboard.Listener(on_press=on_press) as listener:
    listener.join()
```

### Sequence / spell detection

If you want to detect multi-gesture sequences (e.g. two quick presses in a row = different action), use a timed buffer. The included `spells.py` script from this repository implements this pattern fully — see the `spells/` directory.

### Sending IR from Python

To trigger the IR emitter from your own script, open the serial port alongside the HID interface:

```python
import serial
import time

ser = serial.Serial('/dev/ttyACM0', 9600, timeout=3)
time.sleep(1.8)  # wait for Arduino reset

def send_ir(key_name: str):
    """Emit the IR code stored for key_name."""
    ser.write(f"SEND:{key_name}\n".encode())
    response = ser.readline().decode().strip()
    return response.startswith("SENT:")

# Example: switch the beamer to HDMI 2
if send_ir("KEY_F18"):
    print("Beamer switched to HDMI 2")
```

This lets you trigger IR commands from any Python script — a Home Assistant automation, a cron job, a voice assistant callback, or anything else that can run a Python function.

### Available key names

All key names that can be used during pairing and in your own code:

| Range | Names | Recommended use |
|---|---|---|
| `KEY_F1`–`KEY_F12` | Standard function keys | General purpose |
| `KEY_F13`–`KEY_F24` | Extended function keys | **Preferred for remotes** — no conflicts with applications |
| `KEY_UP` `KEY_DOWN` `KEY_LEFT` `KEY_RIGHT` | Arrow keys | Navigation |
| `KEY_ENTER` `KEY_ESC` `KEY_SPACE` `KEY_TAB` | Control keys | Menus, confirm, back |
| `KEY_HOME` `KEY_END` `KEY_PGUP` `KEY_PGDN` | Page keys | Scrolling |
| `KEY_0`–`KEY_9` | Digit keys | Channel numbers, direct input |

Run `python3 ir_learn.py --list-keys` for the complete list.

---

## Serial protocol reference

The firmware communicates over the USB serial connection at 9600 baud with `\n` line endings. You can use any serial terminal or the Python `serial` library directly.

### Commands (host → device)

| Command | Description |
|---|---|
| `LEARN:<keyname>` | Enter learn mode for the given key. Device waits up to 12 seconds for an IR signal. |
| `SEND:<keyname>` | Emit the IR code stored for the given key. |
| `DUMP` | Print all stored mappings, one per line, followed by `DUMP_END`. |
| `CLEAR` | Erase all stored mappings from EEPROM. |
| `LIST` | Print all valid key names, followed by `LIST_END`. |
| `SCAN` | Switch to scan mode: report every received IR signal as raw data, send no HID events. |
| `NORMAL` | Return to normal HID keyboard mode. |

### Responses (device → host)

| Response | Description |
|---|---|
| `READY:<used>/<max>:slots` | Sent on power-up. Reports EEPROM slot usage. |
| `WAITING` | Device is in learn mode and waiting for an IR signal. |
| `LEARNED:<key>:<hex>` | IR signal received and stored successfully. |
| `KEY:<keyname>` | Normal mode: IR signal matched, HID keystroke sent. |
| `SENT:<keyname>` | IR code emitted successfully. |
| `SCAN:<protocol>:<hex_code>:<hex_address>` | Scan mode: raw IR signal received. |
| `DUMP:<index>:<key>:<hex>` | One mapping entry from a DUMP response. |
| `DUMP_END` | End of DUMP response. |
| `LIST_END` | End of LIST response. |
| `OK:<message>` | Generic success confirmation. |
| `ERROR:<message>` | Error message. |

---

## Troubleshooting

**The Arduino IDE does not find a port after connecting the board.**
Some ATmega32U4 clones require a double-press of the reset button to enter bootloader mode before uploading. With the board connected, double-press reset quickly and select the port that appears within 8 seconds.

**The device is detected but no key presses arrive on the Pi.**
Verify that you selected `Arduino Leonardo` as the board in the IDE, not `Pro Micro` or another variant. The wrong board selection produces a binary that breaks USB enumeration.

**The scanner shows `UNKNOWN` protocol for my remote.**
The IRremote library covers the most common protocols but not every proprietary variant. The raw hex code is still captured and can be stored. Pairing will work even if the protocol is listed as `UNKNOWN`.

**The IR emitter does not control the device.**
Check line of sight between the emitter LEDs and the device's IR sensor. Bright sunlight or strong fluorescent lighting can saturate the receiver on the target device. The range is up to 10 metres in normal indoor conditions.

**Mappings disappear after a power cycle.**
This should not happen under normal operation as mappings are written to EEPROM immediately after pairing. If it occurs repeatedly, the EEPROM may be worn (rated for ~100,000 write cycles). Replacing the board resolves this.

---

## Repository structure

```
ir-usb-hid-transreceiver/
├── firmware/
│   └── ir_transceiver.ino   # Arduino sketch (flash once, never touch again)
├── scripts/
│   ├── ir_learn.py          # Pair remote buttons, send IR codes, manage mappings
│   └── ir_scan.py           # Inspect raw IR signals from any device
├── spells/
│   ├── spells.py            # Multi-gesture sequence detection (Remote Controller example)
│   └── spells.yaml          # Spell definitions and Smart Home action mapping
└── README.md
```

---

## License

MIT License. See `LICENSE` for details.
