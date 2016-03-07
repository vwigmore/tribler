import os
from tempfile import mkdtemp

import shutil

from Tribler.Core import defaults
from Tribler.Core.Session import Session
from Tribler.Core.SessionConfig import SessionStartupConfig
from Tribler.Test.test_as_server import BaseTestCase


class TriblerCoreTest(BaseTestCase):
    pass


class TriblerCoreSessionTest(TriblerCoreTest):

    TESTS_DIR = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))

    def setUp(self):
        self.session_base_dir = mkdtemp(suffix="_tribler_test_session")
        self.state_dir = os.path.join(self.session_base_dir, u"dot.Tribler")
        self.dest_dir = os.path.join(self.session_base_dir, u"TriblerDownloads")

        defaults.sessdefaults['general']['state_dir'] = self.state_dir
        defaults.dldefaults["downloadconfig"]["saveas"] = self.dest_dir

        self.cleanup()
        os.makedirs(self.session_base_dir)

    def tearDown(self):
        Session.del_instance()
        self.cleanup()

    def cleanup(self):
        # Change to an existing dir before cleaning up.
        os.chdir(self.TESTS_DIR)
        shutil.rmtree(unicode(self.session_base_dir), ignore_errors=True)

    def get_config(self):
        config = SessionStartupConfig()
        config.set_state_dir(self.get_state_dir())
        config.set_torrent_checking(False)
        config.set_multicast_local_peer_discovery(False)
        config.set_megacache(False)
        config.set_dispersy(False)
        config.set_mainline_dht(False)
        config.set_torrent_store(False)
        config.set_enable_torrent_search(False)
        config.set_enable_channel_search(False)
        config.set_torrent_collecting(False)
        config.set_libtorrent(False)
        config.set_dht_torrent_collecting(False)
        config.set_videoplayer(False)
        config.set_enable_metadata(False)
        config.set_upgrader_enabled(False)
        return config

    def get_state_dir(self, nr=0):
        state_dir = self.state_dir + (str(nr) if nr else '')
        if not os.path.exists(state_dir):
            os.mkdir(state_dir)
        return state_dir
