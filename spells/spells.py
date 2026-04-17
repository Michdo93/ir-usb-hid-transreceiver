#!/usr/bin/env python3
"""
Sequence Engine
===============
Listens for keyboard events from the USB IR transceiver and matches
sequences of key presses against defined patterns. When a pattern matches,
the corresponding action is executed.

This runs on the Raspberry Pi (or any host). The USB IR transceiver
device itself does not need to be modified.

Installation:
    pip install pynput pyyaml requests  # requests only if using Home Assistant

Usage:
    python3 spells.py                          # load spells.yaml from same directory
    python3 spells.py --config my_config.yaml  # custom config file
    python3 spells.py --device evdev           # Linux headless / no desktop
    python3 spells.py --window 3.0             # 3 second sequence window
    python3 spells.py --debug                  # verbose output
    python3 spells.py --list                   # print all defined sequences and exit
"""

import time
import threading
import argparse
import logging
import sys
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sequence_engine")


# ── Key constants ─────────────────────────────────────────────────────────
# These match the key names used in ir_learn.py and spells.yaml.
# The engine maps them to pynput Key objects at runtime.
class K:
    F1  = "KEY_F1";  F2  = "KEY_F2";  F3  = "KEY_F3";  F4  = "KEY_F4"
    F5  = "KEY_F5";  F6  = "KEY_F6";  F7  = "KEY_F7";  F8  = "KEY_F8"
    F9  = "KEY_F9";  F10 = "KEY_F10"; F11 = "KEY_F11"; F12 = "KEY_F12"
    F13 = "KEY_F13"; F14 = "KEY_F14"; F15 = "KEY_F15"; F16 = "KEY_F16"
    F17 = "KEY_F17"; F18 = "KEY_F18"; F19 = "KEY_F19"; F20 = "KEY_F20"
    F21 = "KEY_F21"; F22 = "KEY_F22"; F23 = "KEY_F23"; F24 = "KEY_F24"
    UP    = "KEY_UP";    DOWN  = "KEY_DOWN"
    LEFT  = "KEY_LEFT";  RIGHT = "KEY_RIGHT"
    ENTER = "KEY_ENTER"; ESC   = "KEY_ESC"
    SPACE = "KEY_SPACE"


# ── Sequence dataclass ────────────────────────────────────────────────────

@dataclass
class Sequence:
    name:        str
    keys:        list[str]        # ordered list of key names, e.g. ["KEY_F13", "KEY_F14"]
    action:      str              # action identifier, matched against ActionHandler registry
    description: str = ""
    params:      dict = field(default_factory=dict)  # optional extra params passed to handler


# ── Action handler registry ───────────────────────────────────────────────

class ActionHandler:
    """
    Registry of action handlers. Register your own with @ActionHandler.register().

    Each handler receives the matched Sequence object so it has access
    to sequence.name, sequence.action, sequence.params, and sequence.description.
    """
    _registry: dict[str, Callable] = {}

    @classmethod
    def register(cls, action_name: str):
        """Decorator to register an action handler function."""
        def decorator(fn: Callable):
            cls._registry[action_name] = fn
            return fn
        return decorator

    @classmethod
    def execute(cls, sequence: Sequence):
        handler = cls._registry.get(sequence.action)
        if handler:
            try:
                handler(sequence)
            except Exception as e:
                log.error(f"Handler '{sequence.action}' raised: {e}")
        else:
            log.warning(
                f"No handler registered for action '{sequence.action}'. "
                f"Add @ActionHandler.register('{sequence.action}') to your code."
            )


# ── Built-in example handlers ─────────────────────────────────────────────
# Replace these with real implementations for your setup.
# You can also define handlers in a separate file and import them.

@ActionHandler.register("print")
def _(seq: Sequence):
    """Simple debug handler — just prints the sequence name."""
    msg = seq.params.get("message", seq.description or seq.name)
    print(f"  ▶  {msg}")


@ActionHandler.register("shell")
def _(seq: Sequence):
    """Run a shell command. Params: command (str)"""
    import subprocess
    cmd = seq.params.get("command")
    if cmd:
        subprocess.Popen(cmd, shell=True)
    else:
        log.error("'shell' action requires a 'command' param")


@ActionHandler.register("http_get")
def _(seq: Sequence):
    """HTTP GET request. Params: url (str)"""
    import urllib.request
    url = seq.params.get("url")
    if url:
        try:
            urllib.request.urlopen(url, timeout=5)
            log.debug(f"GET {url} OK")
        except Exception as e:
            log.error(f"GET {url} failed: {e}")
    else:
        log.error("'http_get' action requires a 'url' param")


@ActionHandler.register("http_post")
def _(seq: Sequence):
    """
    HTTP POST request (JSON body).
    Params: url (str), body (dict), headers (dict, optional)
    """
    import urllib.request, urllib.error, json
    url     = seq.params.get("url")
    body    = seq.params.get("body", {})
    headers = seq.params.get("headers", {"Content-Type": "application/json"})
    if not url:
        log.error("'http_post' action requires a 'url' param")
        return
    try:
        data = json.dumps(body).encode()
        req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=5)
        log.debug(f"POST {url} OK")
    except Exception as e:
        log.error(f"POST {url} failed: {e}")


@ActionHandler.register("mqtt_publish")
def _(seq: Sequence):
    """
    Publish an MQTT message.
    Params: topic (str), payload (str), broker (str), port (int, default 1883)
    Requires: pip install paho-mqtt
    """
    try:
        import paho.mqtt.publish as publish
        topic   = seq.params.get("topic")
        payload = str(seq.params.get("payload", ""))
        broker  = seq.params.get("broker", "localhost")
        port    = seq.params.get("port", 1883)
        if topic:
            publish.single(topic, payload, hostname=broker, port=port)
            log.debug(f"MQTT {broker}:{port} {topic}={payload}")
        else:
            log.error("'mqtt_publish' action requires a 'topic' param")
    except ImportError:
        log.error("paho-mqtt not installed. Run: pip install paho-mqtt")


# ── Sequence engine ───────────────────────────────────────────────────────

class SequenceEngine:
    """
    Collects incoming key events and matches them against defined sequences.
    Longer sequences take priority over shorter ones.
    A configurable time window defines the maximum gap between key presses.
    """

    def __init__(
        self,
        sequences:      list[Sequence],
        window_seconds: float = 2.0,
        max_length:     int   = 6,
    ):
        # Sort longest first so a 3-key sequence beats a 2-key prefix
        self.sequences      = sorted(sequences, key=lambda s: -len(s.keys))
        self.window         = window_seconds
        self.max_length     = max_length
        self._buffer:       deque[tuple[str, float]] = deque(maxlen=max_length)
        self._lock          = threading.Lock()
        self._timer:        threading.Timer | None = None

    def on_key(self, key_name: str):
        """Call this whenever a key is received from the transceiver."""
        now = time.monotonic()
        with self._lock:
            self._cancel_timer()
            self._buffer.append((key_name, now))
            self._prune(now)
            matched = self._match()

        if matched:
            log.info(f"▶  {matched.name}  [{' → '.join(matched.keys)}]")
            ActionHandler.execute(matched)
        else:
            self._start_timer()

    def load_yaml(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        cfg = data.get("settings", {})
        if "window_seconds" in cfg:
            self.window = float(cfg["window_seconds"])
        if "max_length" in cfg:
            self.max_length = int(cfg["max_length"])
        self.sequences = sorted(
            [Sequence(**s) for s in data.get("sequences", [])],
            key=lambda s: -len(s.keys),
        )
        log.info(f"Loaded {len(self.sequences)} sequence(s) from '{path}'")

    def list_sequences(self):
        print(f"\n  {'Name':<28} {'Keys':<32} {'Action'}")
        print("  " + "─" * 72)
        for s in sorted(self.sequences, key=lambda x: (len(x.keys), x.name)):
            keys = " → ".join(s.keys)
            print(f"  {s.name:<28} {keys:<32} {s.action}")
        print()

    # ── internals ─────────────────────────────────────────────────────────

    def _prune(self, now: float):
        cutoff = now - self.window
        while self._buffer and self._buffer[0][1] < cutoff:
            self._buffer.popleft()

    def _match(self) -> Sequence | None:
        current = [k for k, _ in self._buffer]
        for seq in self.sequences:
            n = len(seq.keys)
            if len(current) >= n and current[-n:] == seq.keys:
                return seq
        return None

    def _fire_timeout(self):
        with self._lock:
            if self._buffer:
                log.debug(f"Window expired, no match: {[k for k,_ in self._buffer]}")
            self._buffer.clear()

    def _start_timer(self):
        self._timer = threading.Timer(self.window, self._fire_timeout)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None


# ── Key name → pynput mapping ─────────────────────────────────────────────

def build_key_map():
    from pynput.keyboard import Key, KeyCode
    m = {}
    for attr in dir(Key):
        m[f"KEY_{attr.upper()}"] = getattr(Key, attr)
    for i in range(10):
        m[f"KEY_{i}"] = KeyCode.from_char(str(i))
    for c in "abcdefghijklmnopqrstuvwxyz":
        m[f"KEY_{c.upper()}"] = KeyCode.from_char(c)
    # F13–F24 (extended function keys, sent as raw keycodes)
    extended = {
        "KEY_F13": 0xF0, "KEY_F14": 0xF1, "KEY_F15": 0xF2, "KEY_F16": 0xF3,
        "KEY_F17": 0xF4, "KEY_F18": 0xF5, "KEY_F19": 0xF6, "KEY_F20": 0xF7,
        "KEY_F21": 0xF8, "KEY_F22": 0xF9, "KEY_F23": 0xFA, "KEY_F24": 0xFB,
    }
    for name, code in extended.items():
        m[name] = KeyCode.from_vk(code)
    return m


# ── Listeners ─────────────────────────────────────────────────────────────

def run_pynput(engine: SequenceEngine):
    from pynput import keyboard
    from pynput.keyboard import Key

    key_map    = build_key_map()
    rev_map    = {v: k for k, v in key_map.items()}

    def on_press(key):
        key_name = rev_map.get(key)
        if key_name:
            log.debug(f"Key: {key_name}")
            engine.on_key(key_name)
        elif key == Key.esc:
            return False

    log.info("Listener started (pynput) — press ESC to quit")
    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


def run_evdev(engine: SequenceEngine):
    """Linux headless mode — reads directly from /dev/input/eventX."""
    try:
        import evdev
        from evdev import InputDevice, ecodes
    except ImportError:
        log.error("evdev not installed. Run: pip install evdev")
        sys.exit(1)

    devices = [InputDevice(p) for p in evdev.list_devices()]
    device  = next(
        (d for d in devices if "flirc" in d.name.lower()
         or "leonardo" in d.name.lower()
         or "atmega" in d.name.lower()), None
    )
    if device is None:
        print("Available devices:")
        for i, d in enumerate(devices):
            print(f"  [{i}] {d.path}  {d.name}")
        device = devices[int(input("Select device number: "))]

    # Map evdev keycodes to key names
    EVDEV_MAP = {
        ecodes.KEY_F1:  "KEY_F1",  ecodes.KEY_F2:  "KEY_F2",
        ecodes.KEY_F3:  "KEY_F3",  ecodes.KEY_F4:  "KEY_F4",
        ecodes.KEY_F5:  "KEY_F5",  ecodes.KEY_F6:  "KEY_F6",
        ecodes.KEY_F7:  "KEY_F7",  ecodes.KEY_F8:  "KEY_F8",
        ecodes.KEY_F9:  "KEY_F9",  ecodes.KEY_F10: "KEY_F10",
        ecodes.KEY_F11: "KEY_F11", ecodes.KEY_F12: "KEY_F12",
        ecodes.KEY_F13: "KEY_F13", ecodes.KEY_F14: "KEY_F14",
        ecodes.KEY_F15: "KEY_F15", ecodes.KEY_F16: "KEY_F16",
        ecodes.KEY_F17: "KEY_F17", ecodes.KEY_F18: "KEY_F18",
        ecodes.KEY_F19: "KEY_F19", ecodes.KEY_F20: "KEY_F20",
        ecodes.KEY_F21: "KEY_F21", ecodes.KEY_F22: "KEY_F22",
        ecodes.KEY_F23: "KEY_F23", ecodes.KEY_F24: "KEY_F24",
        ecodes.KEY_UP:    "KEY_UP",    ecodes.KEY_DOWN:  "KEY_DOWN",
        ecodes.KEY_LEFT:  "KEY_LEFT",  ecodes.KEY_RIGHT: "KEY_RIGHT",
        ecodes.KEY_ENTER: "KEY_ENTER", ecodes.KEY_ESC:   "KEY_ESC",
        ecodes.KEY_SPACE: "KEY_SPACE",
    }

    log.info(f"Listener started (evdev): {device.name} — CTRL+C to quit")
    try:
        for event in device.read_loop():
            if event.type == ecodes.EV_KEY and event.value == 1:
                key_name = EVDEV_MAP.get(event.code)
                if key_name:
                    log.debug(f"Key: {key_name}")
                    engine.on_key(key_name)
    except KeyboardInterrupt:
        pass


# ── Entry point ───────────────────────────────────────────────────────────

def main():
    default_config = Path(__file__).parent / "spells.yaml"

    parser = argparse.ArgumentParser(
        description="USB IR Transceiver — Sequence Engine"
    )
    parser.add_argument("--config",  type=str,
                        default=str(default_config),
                        help="Path to YAML config file")
    parser.add_argument("--device",  choices=["pynput", "evdev"],
                        default="pynput",
                        help="Input method (default: pynput)")
    parser.add_argument("--window",  type=float, default=None,
                        help="Sequence window in seconds (overrides config)")
    parser.add_argument("--list",    action="store_true",
                        help="Print all defined sequences and exit")
    parser.add_argument("--debug",   action="store_true",
                        help="Enable debug output")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    engine = SequenceEngine(sequences=[], window_seconds=2.0)

    if Path(args.config).exists():
        engine.load_yaml(args.config)
    else:
        log.warning(f"Config file not found: {args.config}")
        log.warning("Running with no sequences defined. Use --config to specify one.")

    if args.window is not None:
        engine.window = args.window

    if args.list:
        engine.list_sequences()
        return

    print()
    print("═" * 56)
    print("  USB IR Transceiver — Sequence Engine")
    print("═" * 56)
    print(f"  Config  : {args.config}")
    print(f"  Window  : {engine.window}s between key presses")
    print(f"  Sequences: {len(engine.sequences)} defined")
    print()
    engine.list_sequences()

    try:
        if args.device == "evdev":
            run_evdev(engine)
        else:
            run_pynput(engine)
    except KeyboardInterrupt:
        pass

    print("\nStopped.")


if __name__ == "__main__":
    main()
