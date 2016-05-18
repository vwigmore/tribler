import os

from binascii import hexlify

from nose.tools import raises

from Tribler.Core.Session import Session
from Tribler.Core.SessionConfig import SessionStartupConfig
from Tribler.Core.exceptions import OperationNotEnabledByConfigurationException
from Tribler.Core.leveldbstore import LevelDbStore
from Tribler.Core.simpledefs import NTFY_CHANNELCAST
from Tribler.Core.TorrentDef import TorrentDef
from Tribler.Test.Core.base_test import TriblerCoreTest
from Tribler.Test.test_as_server import TestAsServer, TESTS_DATA_DIR
from Tribler.dispersy.dispersy import Dispersy
from Tribler.dispersy.endpoint import ManualEnpoint
from Tribler.dispersy.util import blocking_call_on_reactor_thread


class testSession(TriblerCoreTest):

    @raises(OperationNotEnabledByConfigurationException)
    def test_torrent_store_not_enabled(self):
        config = SessionStartupConfig()
        config.set_torrent_store(False)
        session = Session(config, ignore_singleton=True)
        session.delete_collected_torrent(None)

    def test_torrent_store_delete(self):
        config = SessionStartupConfig()
        config.set_torrent_store(True)
        session = Session(config, ignore_singleton=True)
        # Manually set the torrent store as we don't want to start the session.
        session.lm.torrent_store = LevelDbStore(session.get_torrent_store_dir())
        session.lm.torrent_store[hexlify("fakehash")] = "Something"
        self.assertEqual("Something", session.lm.torrent_store[hexlify("fakehash")])
        session.delete_collected_torrent("fakehash")

        raised_key_error = False
        # This structure is needed because if we add a @raises above the test, we cannot close the DB
        # resulting in a dirty reactor.
        try:
            self.assertRaises(KeyError,session.lm.torrent_store[hexlify("fakehash")])
        except KeyError:
            raised_key_error = True
        finally:
            session.lm.torrent_store.close()

        self.assertTrue(raised_key_error)

    def test_create_channel(self):
        """
        Test the pass through function of Session.create_channel to the ChannelManager.
        """

        class LmMock(object):
            class ChannelManager(object):
                def create_channel(self, name, description, mode=u"closed"):
                    pass

            channel_manager = ChannelManager()

        config = SessionStartupConfig()
        session = Session(config, ignore_singleton=True)
        session.lm = LmMock
        session.create_channel("name", "description", "open")


class testSessionAsServer(TestAsServer):

    def setUpPreSession(self):
        super(testSessionAsServer, self).setUpPreSession()
        self.config.set_torrent_collecting(True)
        self.config.set_megacache(True)

    def setUp(self, autoload_discovery=True):
        super(testSessionAsServer, self).setUp(autoload_discovery)
        self.channel_db_handler = self.session.open_dbhandler(NTFY_CHANNELCAST)
        # Mock DisPerSy
        self.dispersy = Dispersy(ManualEnpoint(0), self.getStateDir())
        self.dispersy._database.open()
        self.session.get_dispersy_instance = lambda: self.dispersy

    @blocking_call_on_reactor_thread
    def test_add_torrent_def_to_channel(self):
        """
        Test the thing
        """

        torrent_name = u"ubuntu-15.04-desktop-amd64.iso.torrent"
        torrent_path = os.path.join(TESTS_DATA_DIR, torrent_name)

        channel_id = self.channel_db_handler.getMyChannelId()
        torrent_def = TorrentDef.load(torrent_path)
        extra_info = {"description": "iso"}

        self.session.add_torrent_def_to_channel(channel_id, torrent_def, extra_info, forward=False)
