# PySerialMonitor

**PySerialMonitor** is a Python-based TUI (Text User Interface) Serial Monitor application designed for interacting with serial devices (e.g., microcontrollers like Teensy, Arduino) in a clean, keyboard-driven terminal interface.

With Python **Textual** framework, you can even use mouse!

## Screenshot

![screenshot](docs/Screenshot_20250525_202637.png)

## Features

- Real-time serial data display with timestamps (coming soon).
- Auto reconnection on disconnection.
- Simple, responsive interface with keyboard shortcuts.
- Serial port selection from available devices.
- Adjustable baud rate support.
- Input box to send data to the serial device.
- Supports `LF`, `CR`, or `CRLF` line endings.
- Capturing output to a file.

## Requirements

- Python >= 3.10
- Can be installed with pip

## Installation

You can install via `pip`:

```bash
pip install git+https://gitlab.com/vtneil/pyserialmonitor.git
```
Or you can install with you favorite package manager, e.g., `uv`.

## Running

You can launch the TUI via command:

```bash
pyserialmonitor
```
