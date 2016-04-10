from Tribler.Test.Community.Search.test_search_base import AbstractTestSearchCommunity
from Tribler.community.search.community import ChannelCastDBStub
from Tribler.dispersy.util import blocking_call_on_reactor_thread


class TestChannelcastDbStub(AbstractTestSearchCommunity):

    def setUp(self):
        super(TestChannelcastDbStub, self).setUp()
        self.stub = ChannelCastDBStub(self.dispersy)
        self.torrent_meta = self.search_community.get_meta_message(u"torrent")

    @blocking_call_on_reactor_thread
    def test_new_torrent(self):
        msg = self.torrent_meta.impl(authentication=(self.member,), distribution=(1234,),
                            payload=('a' * 20, 1234, u'test', ((u'/tmp', 1337),), ()))
        self.stub.newTorrent(msg)
        self.assertTrue(self.stub.cachedTorrents[msg.payload.infohash])

    @blocking_call_on_reactor_thread
    def test_has_torrent(self):
        self.stub._cachedTorrents[1] = 42
        self.stub._cachedTorrents[3] = 43
        self.assertEqual(self.stub.hasTorrents(1, [1, 2, 3]), [True, False, True])

    @blocking_call_on_reactor_thread
    def test_get_torrent_from_channel_id(self):
        msg = self.torrent_meta.impl(authentication=(self.member,), distribution=(1234,),
                            payload=('a' * 20, 1234, u'test', ((u'/tmp', 1337),), ()))
        self.stub.newTorrent(msg)
        self.assertIsNone(self.stub.getTorrentFromChannelId(5, 'b' * 20, None))
        self.assertEqual(self.stub.getTorrentFromChannelId(5, 'a' * 20, None), 0)

    @blocking_call_on_reactor_thread
    def test_on_dynamic_settings(self):
        self.assertIsNone(self.stub.on_dynamic_settings(3))
