/*
 * IR ↔ USB-HID Transceiver
 * ========================
 * Hardware : ATmega32U4 Board (Pro Micro / Leonardo-kompatibel)
 * IR-Board  : Adafruit 5990 IR Transceiver
 *
 * Verdrahtung (JST PH 4-Pin Kabel):
 *   Schwarz (GND)  → GND
 *   Rot    (VIN)   → VCC / 5V
 *   Weiß   (IRin)  → Pin 9   ← Arduino sendet hierhin (zu den IR-LEDs)
 *   Grün   (IRout) → Pin 2   ← Arduino empfängt hiervon (vom IR-Sensor)
 *
 * Arduino IDE:
 *   Board  : Arduino Leonardo
 *   Port   : COMx / /dev/ttyACM0
 *   Library: IRremote >= 4.x  (Bibliotheken-Manager: "IRremote" by shirriff)
 *
 * Serielles Protokoll (9600 Baud, Zeilenende \n):
 *
 *   Pi → Arduino:
 *     LEARN:<keyname>        Lernmodus starten (wartet auf IR-Signal)
 *     SEND:<keyname>         Gespeicherten IR-Code senden
 *     DUMP                   Alle Mappings ausgeben
 *     CLEAR                  Alle Mappings löschen
 *     LIST                   Verfügbare Keynamen ausgeben
 *     SCAN                   Scan-Modus: rohe IR-Codes ausgeben (kein HID)
 *     NORMAL                 Normalmodus: IR → HID-Tastendruck
 *
 *   Arduino → Pi:
 *     READY:<belegt>/<max>:slots
 *     WAITING                Bereit für IR-Signal im Lernmodus
 *     LEARNED:<key>:<hex>    Erfolgreich angelernt
 *     KEY:<keyname>          Taste erkannt und HID-Tastendruck gesendet
 *     SENT:<keyname>         IR-Code erfolgreich gesendet
 *     SCAN:<protokoll>:<hex>:<adresse>  Roher IR-Code empfangen (Scan-Modus)
 *     DUMP:<idx>:<key>:<hex> Mapping-Eintrag
 *     DUMP_END
 *     LIST_END
 *     OK:<meldung>
 *     ERROR:<meldung>
 */

#include <IRremote.hpp>
#include <EEPROM.h>
#include <Keyboard.h>

// ── Pins ──────────────────────────────────────────────────────────────────
#define IR_RECEIVE_PIN    2    // Grünes Kabel vom Adafruit 5990 (IRout)
#define IR_SEND_PIN       9    // Weißes Kabel zum Adafruit 5990 (IRin)
#define LED_PIN          17    // Onboard RX-LED (active low auf Pro Micro)

// ── EEPROM Layout ─────────────────────────────────────────────────────────
// Byte 0      : Anzahl gespeicherter Einträge
// Ab Byte 2   : Einträge à 7 Byte
//   0–3  : IR-Code      (uint32_t)
//   4    : IR-Protokoll (uint8_t, IRremote protocol enum)
//   5    : HID-Keycode  (uint8_t)
//   6    : Modifier     (uint8_t)
#define EEPROM_COUNT_ADDR  0
#define EEPROM_DATA_START  2
#define ENTRY_SIZE         7
#define MAX_ENTRIES        ((EEPROM.length() - EEPROM_DATA_START) / ENTRY_SIZE)

// ── Timing ────────────────────────────────────────────────────────────────
#define REPEAT_SUPPRESS_MS   400
#define LEARN_TIMEOUT_MS   12000

// ── Betriebsmodi ──────────────────────────────────────────────────────────
enum Mode { NORMAL_MODE, LEARN_MODE, SCAN_MODE };
Mode currentMode = NORMAL_MODE;

// ── HID Keymap ────────────────────────────────────────────────────────────
struct KeyDef {
  const char* name;
  uint8_t     keycode;
  uint8_t     modifier;
};

static const KeyDef KEY_MAP[] = {
  // F-Tasten (empfohlen – keine Konflikte)
  {"KEY_F1",  KEY_F1,  0}, {"KEY_F2",  KEY_F2,  0},
  {"KEY_F3",  KEY_F3,  0}, {"KEY_F4",  KEY_F4,  0},
  {"KEY_F5",  KEY_F5,  0}, {"KEY_F6",  KEY_F6,  0},
  {"KEY_F7",  KEY_F7,  0}, {"KEY_F8",  KEY_F8,  0},
  {"KEY_F9",  KEY_F9,  0}, {"KEY_F10", KEY_F10, 0},
  {"KEY_F11", KEY_F11, 0}, {"KEY_F12", KEY_F12, 0},
  // F13–F24 (ideal für Fernbedienungen, keine App-Konflikte)
  {"KEY_F13", 0xF0, 0}, {"KEY_F14", 0xF1, 0},
  {"KEY_F15", 0xF2, 0}, {"KEY_F16", 0xF3, 0},
  {"KEY_F17", 0xF4, 0}, {"KEY_F18", 0xF5, 0},
  {"KEY_F19", 0xF6, 0}, {"KEY_F20", 0xF7, 0},
  {"KEY_F21", 0xF8, 0}, {"KEY_F22", 0xF9, 0},
  {"KEY_F23", 0xFA, 0}, {"KEY_F24", 0xFB, 0},
  // Navigation
  {"KEY_UP",    KEY_UP_ARROW,    0},
  {"KEY_DOWN",  KEY_DOWN_ARROW,  0},
  {"KEY_LEFT",  KEY_LEFT_ARROW,  0},
  {"KEY_RIGHT", KEY_RIGHT_ARROW, 0},
  {"KEY_ENTER", KEY_RETURN,      0},
  {"KEY_ESC",   KEY_ESC,         0},
  {"KEY_SPACE", ' ',             0},
  {"KEY_TAB",   KEY_TAB,         0},
  {"KEY_BKSP",  KEY_BACKSPACE,   0},
  {"KEY_DEL",   KEY_DELETE,      0},
  {"KEY_HOME",  KEY_HOME,        0},
  {"KEY_END",   KEY_END,         0},
  {"KEY_PGUP",  KEY_PAGE_UP,     0},
  {"KEY_PGDN",  KEY_PAGE_DOWN,   0},
  // Ziffern
  {"KEY_0",'0',0},{"KEY_1",'1',0},{"KEY_2",'2',0},{"KEY_3",'3',0},
  {"KEY_4",'4',0},{"KEY_5",'5',0},{"KEY_6",'6',0},{"KEY_7",'7',0},
  {"KEY_8",'8',0},{"KEY_9",'9',0},
};
static const uint8_t KEY_MAP_SIZE = sizeof(KEY_MAP) / sizeof(KeyDef);

// ── Lernmodus-State ───────────────────────────────────────────────────────
char    learnKeyName[16];
uint8_t learnKeycode  = 0;
uint8_t learnModifier = 0;
uint32_t learnStartMs = 0;

// ── Repeat-Unterdrückung ──────────────────────────────────────────────────
uint32_t lastCode     = 0;
uint32_t lastCodeTime = 0;

// ── EEPROM Hilfsfunktionen ────────────────────────────────────────────────

uint8_t eepromCount() {
  uint8_t n;
  EEPROM.get(EEPROM_COUNT_ADDR, n);
  return (n > MAX_ENTRIES) ? 0 : n;
}

void eepromSetCount(uint8_t n) {
  EEPROM.put(EEPROM_COUNT_ADDR, n);
}

void eepromWrite(uint8_t idx, uint32_t code, uint8_t proto,
                 uint8_t kc, uint8_t mod) {
  int a = EEPROM_DATA_START + idx * ENTRY_SIZE;
  EEPROM.put(a,     code);
  EEPROM.put(a + 4, proto);
  EEPROM.put(a + 5, kc);
  EEPROM.put(a + 6, mod);
}

bool eepromRead(uint8_t idx, uint32_t &code, uint8_t &proto,
                uint8_t &kc, uint8_t &mod) {
  if (idx >= eepromCount()) return false;
  int a = EEPROM_DATA_START + idx * ENTRY_SIZE;
  EEPROM.get(a,     code);
  EEPROM.get(a + 4, proto);
  EEPROM.get(a + 5, kc);
  EEPROM.get(a + 6, mod);
  return true;
}

// ── Keymap Hilfsfunktionen ────────────────────────────────────────────────

const KeyDef* findKeyDef(const char* name) {
  for (uint8_t i = 0; i < KEY_MAP_SIZE; i++)
    if (strcmp(KEY_MAP[i].name, name) == 0) return &KEY_MAP[i];
  return nullptr;
}

const char* findKeyName(uint8_t kc, uint8_t mod) {
  for (uint8_t i = 0; i < KEY_MAP_SIZE; i++)
    if (KEY_MAP[i].keycode == kc && KEY_MAP[i].modifier == mod)
      return KEY_MAP[i].name;
  return "UNKNOWN";
}

// ── IR-Code nachschlagen ──────────────────────────────────────────────────

bool lookupCode(uint32_t code, uint8_t &kc, uint8_t &mod) {
  uint8_t n = eepromCount();
  for (uint8_t i = 0; i < n; i++) {
    uint32_t sc; uint8_t sp, sk, sm;
    eepromRead(i, sc, sp, sk, sm);
    if (sc == code) { kc = sk; mod = sm; return true; }
  }
  return false;
}

// ── HID Tastendruck senden ────────────────────────────────────────────────

void sendKey(uint8_t kc, uint8_t mod) {
  if (mod) Keyboard.press(mod);
  Keyboard.press(kc);
  delay(10);
  Keyboard.releaseAll();
}

// ── LED Blinken ───────────────────────────────────────────────────────────

void blinkLed(int times = 1, int ms = 30) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, LOW);
    delay(ms);
    digitalWrite(LED_PIN, HIGH);
    delay(ms);
  }
}

// ── Serielles Kommando verarbeiten ────────────────────────────────────────

void handleCommand(String cmd) {
  cmd.trim();

  // LEARN:<keyname>
  if (cmd.startsWith("LEARN:")) {
    String kn = cmd.substring(6); kn.trim();
    const KeyDef* kd = findKeyDef(kn.c_str());
    if (!kd)           { Serial.println("ERROR:Unbekannter Keyname"); return; }
    if (eepromCount() >= MAX_ENTRIES) { Serial.println("ERROR:EEPROM voll"); return; }
    currentMode   = LEARN_MODE;
    learnKeycode  = kd->keycode;
    learnModifier = kd->modifier;
    learnStartMs  = millis();
    strncpy(learnKeyName, kn.c_str(), sizeof(learnKeyName) - 1);
    learnKeyName[sizeof(learnKeyName) - 1] = '\0';
    digitalWrite(LED_PIN, LOW);   // LED an = warte auf Signal
    Serial.println("WAITING");
    return;
  }

  // SEND:<keyname>
  if (cmd.startsWith("SEND:")) {
    String kn = cmd.substring(5); kn.trim();
    uint8_t n = eepromCount();
    for (uint8_t i = 0; i < n; i++) {
      uint32_t sc; uint8_t sp, sk, sm;
      eepromRead(i, sc, sp, sk, sm);
      if (strcmp(findKeyName(sk, sm), kn.c_str()) == 0) {
        IrSender.sendNEC(sc, 32, 0);   // NEC ist Standard; sp ignorieren für Einfachheit
        Serial.print("SENT:"); Serial.println(kn);
        blinkLed(2);
        return;
      }
    }
    Serial.println("ERROR:Keyname nicht gefunden");
    return;
  }

  // DUMP
  if (cmd == "DUMP") {
    uint8_t n = eepromCount();
    for (uint8_t i = 0; i < n; i++) {
      uint32_t sc; uint8_t sp, sk, sm;
      eepromRead(i, sc, sp, sk, sm);
      Serial.print("DUMP:"); Serial.print(i);
      Serial.print(":"); Serial.print(findKeyName(sk, sm));
      Serial.print(":0x"); Serial.println(sc, HEX);
    }
    Serial.println("DUMP_END");
    return;
  }

  // CLEAR
  if (cmd == "CLEAR") {
    eepromSetCount(0);
    Serial.println("OK:CLEARED");
    return;
  }

  // LIST
  if (cmd == "LIST") {
    for (uint8_t i = 0; i < KEY_MAP_SIZE; i++)
      Serial.println(KEY_MAP[i].name);
    Serial.println("LIST_END");
    return;
  }

  // SCAN – rohe IR-Codes ausgeben, kein HID
  if (cmd == "SCAN") {
    currentMode = SCAN_MODE;
    Serial.println("OK:SCAN_MODE");
    return;
  }

  // NORMAL – zurück zum normalen Betrieb
  if (cmd == "NORMAL") {
    currentMode = NORMAL_MODE;
    digitalWrite(LED_PIN, HIGH);
    Serial.println("OK:NORMAL_MODE");
    return;
  }

  Serial.print("ERROR:Unbekanntes Kommando: "); Serial.println(cmd);
}

// ── Setup ─────────────────────────────────────────────────────────────────

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // LED aus (active low)

  Serial.begin(9600);
  Keyboard.begin();

  IrReceiver.begin(IR_RECEIVE_PIN, DISABLE_LED_FEEDBACK);
  IrSender.begin(IR_SEND_PIN);

  delay(500);
  Serial.print("READY:");
  Serial.print(eepromCount());
  Serial.print("/");
  Serial.print((int)MAX_ENTRIES);
  Serial.println(":slots");
}

// ── Loop ──────────────────────────────────────────────────────────────────

void loop() {
  // Serielles Kommando lesen
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    handleCommand(cmd);
  }

  // Lernmodus-Timeout prüfen
  if (currentMode == LEARN_MODE &&
      (millis() - learnStartMs) > LEARN_TIMEOUT_MS) {
    currentMode = NORMAL_MODE;
    digitalWrite(LED_PIN, HIGH);
    Serial.println("ERROR:Timeout – kein Signal empfangen");
  }

  // IR empfangen
  if (!IrReceiver.decode()) return;

  uint32_t code  = IrReceiver.decodedIRData.decodedRawData;
  uint8_t  proto = IrReceiver.decodedIRData.protocol;
  uint16_t addr  = IrReceiver.decodedIRData.address;
  bool     rep   = IrReceiver.decodedIRData.flags & IRDATA_FLAGS_IS_REPEAT;

  IrReceiver.resume();

  if (code == 0) return;

  // ── Scan-Modus: alles ausgeben, kein HID ────────────────────────────
  if (currentMode == SCAN_MODE) {
    if (!rep) {
      Serial.print("SCAN:");
      Serial.print(getProtocolString(proto));
      Serial.print(":0x");
      Serial.print(code, HEX);
      Serial.print(":0x");
      Serial.println(addr, HEX);
      blinkLed(1, 20);
    }
    return;
  }

  // Repeat und Doppel-Trigger unterdrücken
  if (rep) return;
  uint32_t now = millis();
  if (code == lastCode && (now - lastCodeTime) < REPEAT_SUPPRESS_MS) return;
  lastCode     = code;
  lastCodeTime = now;

  // ── Lernmodus: Code speichern ────────────────────────────────────────
  if (currentMode == LEARN_MODE) {
    currentMode = NORMAL_MODE;
    digitalWrite(LED_PIN, HIGH);

    uint8_t n = eepromCount();
    // Vorhandenen Eintrag für diesen Key überschreiben
    bool updated = false;
    for (uint8_t i = 0; i < n; i++) {
      uint32_t sc; uint8_t sp, sk, sm;
      eepromRead(i, sc, sp, sk, sm);
      if (sk == learnKeycode && sm == learnModifier) {
        eepromWrite(i, code, proto, learnKeycode, learnModifier);
        updated = true;
        break;
      }
    }
    if (!updated) {
      eepromWrite(n, code, proto, learnKeycode, learnModifier);
      eepromSetCount(n + 1);
    }

    Serial.print("LEARNED:");
    Serial.print(learnKeyName);
    Serial.print(":0x");
    Serial.println(code, HEX);
    blinkLed(3, 50);
    return;
  }

  // ── Normalmodus: HID senden ──────────────────────────────────────────
  uint8_t kc, mod;
  if (lookupCode(code, kc, mod)) {
    sendKey(kc, mod);
    Serial.print("KEY:");
    Serial.println(findKeyName(kc, mod));
    blinkLed(1, 30);
  }
}
