#!/usr/bin/env python

# Invoke esptool, but replace the serial module with a wrapper that
# uses RTS/CTS instead of RTS/DTR via bitbang mode.  This only works
# on FTDI devices, and requires libftdi1 and libusb-1.0.

from __future__ import print_function
def printf(str, *args):
    print(str % args, end='')

import sys
import os
import ctypes
import ctypes.util
import functools
import time

class ftdi_context_partial(ctypes.Structure):
    # This is for libftdi 1.0+
    _fields_ = [('libusb_context', ctypes.c_void_p),
                ('libusb_device_handle', ctypes.c_void_p),
                ('usb_read_timeout', ctypes.c_int),
                ('usb_write_timeout', ctypes.c_int)]

class FTDIError(Exception):
    pass

class serial_via_libftdi(object):
    @staticmethod
    def serial_for_url(port):
        return serial_via_libftdi(port)

    @property
    def ftdi_fn(self):
        class FtdiForwarder(object):
            def __getattr__(iself, fn):
                return functools.partial(getattr(self.ftdi, fn),
                                         ctypes.byref(self.ctx))
        return FtdiForwarder()

    def _ftdi_error(self, message):
        errstr = self.ftdi_fn.ftdi_get_error_string()
        raise FTDIError("%s: %s" % (message, errstr))

    def _ftdi_close(self):
        if getattr(self, 'cleanup_close', False):
            #printf("reattaching and closing\n")
            context = ctypes.cast(ctypes.byref(self.ctx),
                                  ctypes.POINTER(ftdi_context_partial)).contents
            pdev = ctypes.c_void_p(context.libusb_device_handle)
            if pdev:
                self.usb.libusb_release_interface(pdev, self.interface)
                self.usb.libusb_attach_kernel_driver(pdev, self.interface)

            self.ftdi_fn.ftdi_usb_close()

        if getattr(self, 'cleanup_deinit', False):
            self.ftdi_fn.ftdi_deinit()

    def _find_port(self, port):
        # Find the port
        s = os.stat(port)
        path = "/sys/dev/char/%d:%d" % (
            os.major(s.st_rdev), os.minor(s.st_rdev))
        path = os.path.realpath(path)

        # Walk up the tree until we find interface, busnum, and devnum files
        def try_read(path, filename, converter):
            p = os.path.join(path, filename)
            try:
                with open(p) as f:
                    return converter(f.read())
            except IOError:
                return None

        (busnum, devnum, interface) = (None, None, None)
        while path != "/":
            if busnum is None:
                busnum = try_read(path, "busnum", int)
            if devnum is None:
                devnum = try_read(path, "devnum", int)
            if interface is None:
                interface = try_read(path, "bInterfaceNumber",
                                     lambda x: int(x, 16))
            if None not in (busnum, devnum, interface):
                break
            path = os.path.realpath(os.path.join(path, ".."))
        else:
            raise Exception("can't find bus/device/interface for that port")
        printf("%s is at bus %d dev %d interface %d\n", port, busnum,
               devnum, interface)
        return (busnum, devnum, interface)

    def __del__(self):
        self._ftdi_close()

    def __init__(self, port):
        self.port = port
        self._baudrate = 9600
        self._timeout = 5.0
        self.dtr = False
        self.rts = False
        self.bitmode = False

        # Load libftdi and libusb
        def load_lib(name):
            libname = ctypes.util.find_library(name)
            if not libname:
                raise Exception("Can't find library " + name)
            return ctypes.CDLL(libname)
        self.usb = load_lib('usb-1.0')
        self.ftdi = load_lib('ftdi1')
        self.ftdi.ftdi_get_error_string.restype = ctypes.c_char_p

        # Find port
        (busnum, devnum, self.interface) = self._find_port(port)

        # Open it via libftdi
        try:
            self.ctx = ctypes.create_string_buffer(1024)
            if self.ftdi_fn.ftdi_init() != 0:
                raise FTDIError("ftdi_init")
            self.cleanup_deinit = True
            if self.ftdi_fn.ftdi_set_interface(self.interface) != 0:
                raise FTDIError("ftdi_set_interface")
            if self.ftdi_fn.ftdi_usb_open_bus_addr(busnum, devnum) != 0:
                raise FTDIError("usb_open_bus_addr")
            self.cleanup_close = True
            self.ftdi_fn.ftdi_set_bitmode(0, 0)
            self.ftdi_fn.ftdi_setrts(0)
        except FTDIError as e:
            self._ftdi_error(e.message)

    def _ftdi_update_control(self):
        # Set control lines.  This is where we make CTS behave as if
        # it were DTR, by going in and out of bitbang mode:
        #  self.dtr self.rts mode     cts=   rts=
        #  False    False    normal   float  1
        #  False    True     bitbang  1      1
        #  True     False    bitbang  0      1
        #  True     True     bitbang  0      0
        #printf("EN %d BOOT %d\n", self.rts == False, self.dtr == False);

        val = 0
        if self.dtr == False:
            val |= 0x08  # CTS high
        if self.rts == False:
            val |= 0x04  # RTS high

        if (self.dtr, self.rts) == (False, False):
            # Normal mode
            if self.bitmode:
                self.write("%c" % val)
                self.flushOutput()
                self.ftdi_fn.ftdi_set_bitmode(0, 0)
                self.ftdi_fn.ftdi_setflowctrl(0)
                self.ftdi_fn.ftdi_setrts(0)
            self.bitmode = False
            return

        # Bitbang mode
        if not self.bitmode:
            self.ftdi_fn.ftdi_set_bitmode(0x0d, 0x01)
        self.bitmode = True
        self.write("%c" % val)

    def setDTR(self, active):
        self.dtr = active
        self._ftdi_update_control()

    def setRTS(self, active):
        self.rts = active
        self._ftdi_update_control()

    def flushInput(self):
        self.ftdi_fn.ftdi_usb_purge_rx_buffer()

    def flushOutput(self):
        self.ftdi_fn.ftdi_usb_purge_tx_buffer()

    @property
    def timeout(self):
        context = ctypes.cast(ctypes.byref(self.ctx),
                              ctypes.POINTER(ftdi_context_partial))
        return context[0].usb_read_timeout / 1000.0

    @timeout.setter
    def timeout(self, new_timeout):
        context = ctypes.cast(ctypes.byref(self.ctx),
                              ctypes.POINTER(ftdi_context_partial))
        context[0].usb_read_timeout = int(new_timeout * 1000)
        context[0].usb_write_timeout = int(new_timeout * 1000)
        self._timeout = new_timeout

    @property
    def baudrate(self):
        return self._baudrate

    @baudrate.setter
    def baudrate(self, val):
        if self.ftdi_fn.ftdi_set_baudrate(val) != 0:
            self._ftdi_error("ftdi_set_baudrate")
        self._baudrate = val;

    def write(self, buf):
        try:
            bytesbuf = bytes(buf)
        except TypeError:
            bytesbuf = buf.encode('latin1')
        data = ctypes.create_string_buffer(bytesbuf)
        written = self.ftdi_fn.ftdi_write_data(ctypes.byref(data), len(buf))
        if written < 0:
            self._ftdi_error("ftdi_write_data")
        #printf("> %d %d '%02x'\n", len(buf), written, ord(buf[0]))
        return written

    def inWaiting(self):
        # If we always return 0, esptool will just read 1 byte at a time
        return 0

    def _read(self, count):
        buf = ctypes.create_string_buffer(count)
        rlen = self.ftdi_fn.ftdi_read_data(ctypes.byref(buf), count)
        if rlen < 0:
            self._ftdi_error("ftdi_read_data")
        return buf.raw[0:rlen]

    def read(self, count):
        start = time.time()
        ret = b''
        while True:
            ret += self._read(count - len(ret))
            if len(ret) >= count:
                return ret
            if time.time() - start > self._timeout:
                return b''

# Old esptool compares serial objects against this
serial_via_libftdi.Serial = serial_via_libftdi

def import_from_path(path, name="esptool"):
    if not os.path.isfile(path):
        raise Exception("No such file: %s" % path)

    # Import esptool from the provided location
    if sys.version_info >= (3,5):
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    elif sys.version_info >= (3,3):
        from importlib.machinery import SourceFileLoader
        module = SourceFileLoader(name, path).load_module()
    else:
        import imp
        module = imp.load_source(name, path)
    return module

if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: %s <path-to-esptool.py> [args...]"
                         % sys.argv[0])

    printf("esptool-ftdi.py wrapper\n")

    esptool = import_from_path(sys.argv[1])
    esptool.serial = serial_via_libftdi
    sys.argv[1:] = sys.argv[2:]
    esptool.main()
