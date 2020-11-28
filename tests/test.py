#!/usr/bin/python3
# -*- coding: utf-8 -*-
# key-mapper - GUI for device specific keyboard mappings
# Copyright (C) 2020 sezanzeb <proxima@hip70890b.de>
#
# This file is part of key-mapper.
#
# key-mapper is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# key-mapper is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with key-mapper.  If not, see <https://www.gnu.org/licenses/>.


"""Sets up key-mapper for the tests and runs them."""


import sys
import time
import unittest
import multiprocessing
import asyncio

import evdev

from keymapper.logger import update_verbosity


tmp = '/tmp/key-mapper-test'
uinput_write_history = []
# for tests that makes the injector create its processes
uinput_write_history_pipe = multiprocessing.Pipe()
pending_events = {}

# key-mapper is only interested in devices that have EV_KEY, add some
# random other stuff to test that they are ignored.
fixtures = {
    # device 1
    '/dev/input/event11': {
        'capabilities': {evdev.ecodes.EV_KEY: [], evdev.ecodes.EV_ABS: []},
        'phys': 'usb-0000:03:00.0-1/input2',
        'name': 'device 1 foo'
    },
    '/dev/input/event10': {
        'capabilities': {evdev.ecodes.EV_KEY: list(evdev.ecodes.keys.keys())},
        'phys': 'usb-0000:03:00.0-1/input3',
        'name': 'device 1'
    },
    '/dev/input/event13': {
        'capabilities': {evdev.ecodes.EV_KEY: [], evdev.ecodes.EV_SYN: []},
        'phys': 'usb-0000:03:00.0-1/input1',
        'name': 'device 1'
    },
    '/dev/input/event14': {
        'capabilities': {evdev.ecodes.EV_SYN: []},
        'phys': 'usb-0000:03:00.0-1/input0',
        'name': 'device 1 qux'
    },

    # device 2
    '/dev/input/event20': {
        'capabilities': {evdev.ecodes.EV_KEY: list(evdev.ecodes.keys.keys())},
        'phys': 'usb-0000:03:00.0-2/input1',
        'name': 'device 2'
    },

    # devices that are completely ignored
    '/dev/input/event30': {
        'capabilities': {evdev.ecodes.EV_SYN: []},
        'phys': 'usb-0000:03:00.0-3/input1',
        'name': 'device 3'
    },
    '/dev/input/event31': {
        'capabilities': {evdev.ecodes.EV_SYN: []},
        'phys': 'usb-0000:03:00.0-4/input1',
        'name': 'Power Button'
    },

    # key-mapper devices are not displayed in the ui, some instance
    # of key-mapper started injecting apparently.
    '/dev/input/event40': {
        'capabilities': {evdev.ecodes.EV_KEY: list(evdev.ecodes.keys.keys())},
        'phys': 'key-mapper/input1',
        'name': 'key-mapper device 2'
    },
}


def get_events():
    """Get all events written by the injector."""
    return uinput_write_history


def push_event(device, event):
    """Emit a fake event for a device.

    Parameters
    ----------
    device : string
        For example 'device 1'
    event : Event
    """
    if pending_events.get(device) is None:
        pending_events[device] = []
    pending_events[device].append(event)


class Event:
    """Event to put into the injector for tests."""
    def __init__(self, type, code, value):
        """
        Paramaters
        ----------
        type : int
            one of evdev.ecodes.EV_*
        code : int
            keyboard event code as known to linux. E.g. 2 for the '1' button,
            which would be 10 in xkb
        value : int
            1 for down, 0 for up, 2 for hold
        """
        self.type = type
        self.code = code
        self.value = value


def patch_paths():
    from keymapper import paths
    paths.CONFIG = '/tmp/key-mapper-test/'


def patch_evdev():
    def list_devices():
        return fixtures.keys()

    class InputDevice:
        def __init__(self, path):
            self.path = path
            self.phys = fixtures[path]['phys']
            self.name = fixtures[path]['name']

        def grab(self):
            pass

        def read_one(self):
            if pending_events.get(self.name) is None:
                return None

            if len(pending_events[self.name]) == 0:
                return None

            event = pending_events[self.name].pop(0)
            return event

        def read_loop(self):
            """Read all prepared events at once."""
            if pending_events.get(self.name) is None:
                return

            while len(pending_events[self.name]) > 0:
                yield pending_events[self.name].pop(0)
                # give tests some time to test stuff while the process
                # is still running
                time.sleep(0.01)

        async def async_read_loop(self):
            """Read all prepared events at once."""
            if pending_events.get(self.name) is None:
                return

            while len(pending_events[self.name]) > 0:
                yield pending_events[self.name].pop(0)
                await asyncio.sleep(0.01)

        def capabilities(self, absinfo=True):
            return fixtures[self.path]['capabilities']

    class UInput:
        def __init__(self, *args, **kwargs):
            self.fd = 0
            self.device = InputDevice('/dev/input/event40')
            pass

        def write(self, type, code, value):
            event = Event(type, code, value)
            uinput_write_history.append(event)
            uinput_write_history_pipe[1].send(event)

        def syn(self):
            pass

    evdev.list_devices = list_devices
    evdev.InputDevice = InputDevice
    evdev.UInput = UInput


def patch_unsaved():
    # don't block tests
    from keymapper.gtk import unsaved
    unsaved.unsaved_changes_dialog = lambda: unsaved.CONTINUE


def patch_dbus():
    """Make sure that the dbus interface is just an instance of Daemon.

    Don't talk to an actual daemon if one is running.
    """
    import dbus
    from keymapper.daemon import Daemon
    dbus.Interface = lambda *args: Daemon()


def clear_write_history():
    """Empty the history in preparation for the next test."""
    while len(uinput_write_history) > 0:
        uinput_write_history.pop()
    while uinput_write_history_pipe[0].poll():
        uinput_write_history_pipe[0].recv()


# quickly fake some stuff before any other file gets a chance to import
# the original versions
patch_paths()
patch_evdev()
patch_unsaved()
patch_dbus()


def main():
    update_verbosity(True)

    modules = sys.argv[1:]
    # discoverer is really convenient, but it can't find a specific test
    # in all of the available tests like unittest.main() does...,
    # so provide both options.
    if len(modules) > 0:
        # for example `tests/test.py integration.Integration.test_can_start`
        # or `tests/test.py integration daemon`
        testsuite = unittest.defaultTestLoader.loadTestsFromNames(
            [f'testcases.{module}' for module in modules]
        )
    else:
        # run all tests by default
        testsuite = unittest.defaultTestLoader.discover(
            'testcases', pattern='*.py'
        )

    # add a newline to each "qux (foo.bar)..." output, because the logs
    # will be on the same line otherwise
    originalStartTest = unittest.TextTestResult.startTest
    def startTest(self, test):
        originalStartTest(self, test)
        print()
    unittest.TextTestResult.startTest = startTest

    testrunner = unittest.TextTestRunner(verbosity=2).run(testsuite)


if __name__ == "__main__":
    main()
