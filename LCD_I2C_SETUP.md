# Minimal I2C LCD Setup

This is the minimum wiring and firmware setup to get a `16x2 LiquidCrystal_I2C` display working with the ultrasonic Arduino in `main_1.ino`.

## Wiring

For an Arduino Uno / Nano:

- `LCD VCC` -> `5V`
- `LCD GND` -> `GND`
- `LCD SDA` -> `A4`
- `LCD SCL` -> `A5`

If you are using an Arduino Mega instead:

- `LCD SDA` -> `20`
- `LCD SCL` -> `21`

## What The LCD Shows

The LCD now works like a small machine-status screen.

- Line 1: current system banner
- Line 2: live sensor state

Examples:

- `SYSTEM READY`
- `OBJECT DETECTED`
- `WF PickDrop`
- `1 MOVE to-pick`
- `2 WAIT 1.0s`
- `AUTO IN 1.5s`
- `MOTOR STOPPED`

The second line stays focused on the ultrasonic state, for example:

```text
D:4cm DETECTED
```

or

```text
D:14cm CLEAR
```

## Library Needed

Install this Arduino library:

- `LiquidCrystal_I2C`

Most common LCD I2C backpack addresses are:

- `0x27`
- `0x3F`

The code currently uses:

```cpp
LiquidCrystal_I2C lcd(0x27, 16, 2);
```

If the screen powers on but shows nothing useful, change `0x27` to `0x3F` in `main_1.ino` and upload again.

## Files Updated

- `main_1.ino`
- `app.py`

## Notes

- This LCD is attached to the same Arduino that reads the ultrasonic sensor.
- The backend now sends short LCD status messages over serial to Arduino 1 during workflow and automation execution.
- LCD messages are intentionally short because the display is only `16x2`.
