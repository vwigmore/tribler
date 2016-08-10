import sys
from Tribler.Core.Utilities.win32regchecker import Win32RegChecker
from Tribler.Test.Core.base_test import TriblerCoreTest


class TriblerCoreTestInstallDir(TriblerCoreTest):

    def test_win32regchecker(self):
        if sys.platform != 'win32':
            self.assertIsNone(Win32RegChecker().read_root_key(".wmv"))
        else:
            self.assertTrue(Win32RegChecker().read_root_key(".wmv"))
            self.assertIsNone(Win32RegChecker().read_root_key("fdkaslfjsdakfdffdsakls"))
