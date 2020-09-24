# esptool-ftdi.py

## Overview

This `esptool.py` wrapper lets you use RTS/CTS for ESP8266/ESP32
chip resets instead of the usual RTS/DTR.  It only works with
FTDI-based USB to serial adapters.

Normally, CTS is an input.  On FTDI chips, CTS can be reconfigured as
an output by entering bitbang mode.  This wrapper replaces all of the
internal `esptool.py` serial routines with direct calls into
`libftdi1` and `libusb-1.0` to dynamically switch between normal and
bitbang modes as needed to make the typical reset-into-bootloader
sequence work.

## Hardware connections

| FTDI  | ESP32            |
|-------|------------------|
| `GND` | `GND`            |
| `VIO` | `3V3`            |
| `RX`  | `U0TXD`          |
| `TX`  | `U0RXD`          |
| `RTS` | `EN` (`CHP_PU`)  |
| `CTS` | `BOOT` (`GPIO0`) |

## Requirements

* [libftdi1 1.4](https://www.intra2net.com/en/developer/libftdi/index.php)
* [libusb 1.0](https://libusb.info/)

This was tested on Linux only.  Some of the `ctypes` library loading
probably needs to be tweaked for other OSes.

## Usage

    $ ./esptool-ftdi.py
    usage: ./esptool-ftdi.py <path-to-esptool.py> [args...]

Simply prepend `esptool-ftdi.py` to your existing esptool command
line.  For example, instead of:

    $ esptool.py chip_id
    esptool.py v2.3.1
    Connecting........_____....._____....._____....._____....._____....._____....._____....._____....._____....._____
    
    A fatal error occurred: Failed to connect to Espressif device: Timed out waiting for packet header
    $

run this and be much happier:

    $ ./esptool-ftdi.py esptool.py chip_id
    esptool-ftdi.py wrapper
    esptool.py v2.3.1
    /dev/ttyUSB0 is at bus 3 dev 78 interface 0
    Connecting.....
    Detecting chip type... ESP32
    Chip is ESP32D0WDQ6 (revision (unknown 0xa))
    Features: WiFi, BT, Dual Core, VRef calibration in efuse
    Uploading stub...
    Running stub...
    Stub running...
    Chip ID: 0xe2b4e62dac76
    Hard resetting via RTS pin...
    $

## Integrating with ESP-IDF

In your Makefile, after the line

    include $(IDF_PATH)/make/project.mk

add

    ESPTOOL_FTDI := /path/to/esptool-ftdi.py
    ESPTOOLPY_SERIAL := $(PYTHON) $(ESPTOOL_FTDI) $(ESPTOOLPY_SRC) --chip esp32 --port $(ESPPORT) --baud $(ESPBAUD) --before $(CONFIG_ESPTOOLPY_BEFORE) --after $(CONFIG_ESPTOOLPY_AFTER)

This could be simplified with some changes in ESP-IDF.
