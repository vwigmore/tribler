from binascii import unhexlify

from Tribler.Core.CacheDB.basic_db_handler import VoteCastDBHandler
from Tribler.Core.CacheDB.channelcast_db_handler import ChannelCastDBHandler
from Tribler.Core.CacheDB.torrent_db_handler import TorrentDBHandler
from Tribler.Core.CacheDB.sqlitecachedb import str2bin
from Tribler.Test.Core.CacheDB.dbhandlers.test_sqlitecachedbhandler import AbstractDB


class TestChannelDBHandler(AbstractDB):

    def setUp(self):
        super(TestChannelDBHandler, self).setUp()

        self.cdb = ChannelCastDBHandler(self.session)
        self.tdb = TorrentDBHandler(self.session)
        self.vdb = VoteCastDBHandler(self.session)
        self.cdb.votecast_db = self.vdb
        self.cdb.torrent_db = self.tdb

    def test_get_metadata_torrents(self):
        self.assertEqual(len(self.cdb.get_metadata_torrents()), 2)
        self.assertEqual(len(self.cdb.get_metadata_torrents(is_collected=False)), 1)

    def test_get_torrent_metadata(self):
        result = self.cdb.get_torrent_metadata(1)
        self.assertEqual(result, {"thumb_hash": unhexlify("1234")})
        self.assertIsNone(self.cdb.get_torrent_metadata(200))

    def test_get_dispersy_cid_from_channel_id(self):
        self.assertEqual(self.cdb.get_dispersy_cid_from_cid(1), "1")
        self.assertEqual(self.cdb.get_dispersy_cid_from_cid(3), "3")

    def test_get_channel_id_from_dispersy_cid(self):
        self.assertEqual(self.cdb.get_channel_id_from_dispersy_cid(1), 1)
        self.assertEqual(self.cdb.get_channel_id_from_dispersy_cid(3), 3)

    def test_get_count_max_from_channel_id(self):
        self.assertEqual(self.cdb.get_count_max_from_cid(1), (2, 1457809687))
        self.assertEqual(self.cdb.get_count_max_from_cid(2), (1, 1457809861))

    def test_search_channel(self):
        self.assertEqual(len(self.cdb.search_channels("another")), 1)
        self.assertEqual(len(self.cdb.search_channels("fancy")), 2)

    def test_get_channel(self):
        channel = self.cdb.get_channel(1)
        self.assertEqual(channel, (1, '1', u'Test Channel 1', u'Test', 3, 7, 5, 2, 1457795713, False))
        self.assertIsNone(self.cdb.get_channel(1234))

    def test_get_channels(self):
        channels = self.cdb.get_channels([1, 2, 3])
        self.assertEqual(len(channels), 3)

    def test_get_channels_by_cid(self):
        self.assertEqual(len(self.cdb.get_channels_by_cid(["3"])), 0)

    def test_get_all_channels(self):
        self.assertEqual(len(self.cdb.get_all_channels()), 8)

    def test_get_new_channels(self):
        self.assertEqual(len(self.cdb.get_new_channels()), 1)

    def test_get_latest_updated(self):
        res = self.cdb.get_latest_updated()
        self.assertEqual(res[0][0], 6)
        self.assertEqual(res[1][0], 7)
        self.assertEqual(res[2][0], 5)

    def test_get_most_popular_channels(self):
        res = self.cdb.get_most_popular_channels()
        self.assertEqual(res[0][0], 6)
        self.assertEqual(res[1][0], 7)
        self.assertEqual(res[2][0], 8)

    def test_get_my_subscribed_channels(self):
        res = self.cdb.get_my_subscribed_channels(include_dispersy=True)
        self.assertEqual(len(res), 1)
        res = self.cdb.get_my_subscribed_channels()
        self.assertEqual(len(res), 0)

    def test_get_channels_no_votecast(self):
        self.cdb.votecast_db = None
        self.assertFalse(self.cdb._get_channels("SELECT id FROM channels"))

    def test_get_my_channel_id(self):
        self.cdb._channel_id = 42
        self.assertEqual(self.cdb.get_my_channel_id(), 42)
        self.cdb._channel_id = None
        self.assertEqual(self.cdb.get_my_channel_id(), 1)

    def test_get_torrent_markings(self):
        res = self.cdb.get_torrent_markings(3)
        self.assertEqual(res, [[u'test', 2, True], [u'another', 1, True]])
        res = self.cdb.get_torrent_markings(1)
        self.assertEqual(res, [[u'test', 1, True]])

    def test_on_remove_playlist_torrent(self):
        self.assertEqual(len(self.cdb.get_torrents_from_playlist(1, ['Torrent.torrent_id'])), 1)
        self.cdb.on_remove_playlist_torrent(1, 1, str2bin('AA8cTG7ZuPsyblbRE7CyxsrKUCg='), False)
        self.assertEqual(len(self.cdb.get_torrents_from_playlist(1, ['Torrent.torrent_id'])), 0)
