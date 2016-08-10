from Tribler.Core.CacheDB.my_preference_db_handler import MyPreferenceDBHandler
from Tribler.Core.CacheDB.torrent_db_handler import TorrentDBHandler
from Tribler.Core.CacheDB.sqlitecachedb import str2bin
from Tribler.Test.Core.CacheDB.dbhandlers.test_sqlitecachedbhandler import AbstractDB
from Tribler.dispersy.util import blocking_call_on_reactor_thread


class TestMyPreferenceDBHandler(AbstractDB):

    def setUp(self):
        super(TestMyPreferenceDBHandler, self).setUp()

        self.tdb = TorrentDBHandler(self.session)
        self.mdb = MyPreferenceDBHandler(self.session)
        self.mdb._torrent_db = self.tdb

    def tearDown(self):
        self.mdb.close()
        self.mdb = None
        self.tdb.close()
        self.tdb = None

        super(TestMyPreferenceDBHandler, self).tearDown()

    @blocking_call_on_reactor_thread
    def test_getPrefList(self):
        pl = self.mdb.get_my_pref_list_infohash()
        self.assertEqual(len(pl), 12)

    @blocking_call_on_reactor_thread
    def test_addMyPreference_deletePreference(self):
        p = self.mdb.get_one(('torrent_id', 'destination_path', 'creation_time'), torrent_id=126)
        torrent_id = p[0]
        infohash = self.tdb.get_infohash(torrent_id)
        destpath = p[1]
        creation_time = p[2]
        self.mdb.delete_preference(torrent_id)
        pl = self.mdb.get_my_pref_list_infohash()
        self.assertEqual(len(pl), 12)
        self.assertIn(infohash, pl)

        data = {'destination_path': destpath}
        self.mdb.add_my_preference(torrent_id, data)
        p2 = self.mdb.get_one(('torrent_id', 'destination_path', 'creation_time'), torrent_id=126)
        self.assertTrue(p2[0] == p[0])
        self.assertTrue(p2[1] == p[1])

        self.mdb.delete_preference(torrent_id)
        pl = self.mdb.get_my_pref_list_infohash(return_deleted=False)
        self.assertEqual(len(pl), 11)
        self.assertNotIn(infohash, pl)

        data = {'destination_path': destpath, 'creation_time': creation_time}
        self.mdb.add_my_preference(torrent_id, data)
        p3 = self.mdb.get_one(('torrent_id', 'destination_path', 'creation_time'), torrent_id=126)
        self.assertEqual(p3, p)

    @blocking_call_on_reactor_thread
    def test_getMyPrefListInfohash(self):
        preflist = self.mdb.get_my_pref_list_infohash()
        for p in preflist:
            self.assertTrue(not p or len(p) == 20)
        self.assertEqual(len(preflist), 12)

    @blocking_call_on_reactor_thread
    def test_get_my_pref_stats(self):
        res = self.mdb.get_my_pref_stats()
        self.assertEqual(len(res), 12)
        for k in res:
            data = res[k]
            self.assertIsInstance(data, basestring, "data is not destination_path: %s" % type(data))

        res = self.mdb.get_my_pref_stats(torrent_id=126)
        self.assertEqual(len(res), 1)

    @blocking_call_on_reactor_thread
    def test_my_pref_stats_infohash(self):
        infohash = str2bin('AB8cTG7ZuPsyblbRE7CyxsrKUCg=')
        self.assertIsNone(self.mdb.get_my_pref_stats_infohash(infohash))
        infohash = str2bin('ByJho7yj9mWY1ORWgCZykLbU1Xc=')
        self.assertTrue(self.mdb.get_my_pref_stats_infohash(infohash))

    @blocking_call_on_reactor_thread
    def test_get_my_pref_list_infohash_limit(self):
        self.assertEqual(len(self.mdb.get_my_pref_list_infohash(limit=10)), 10)

    @blocking_call_on_reactor_thread
    def test_add_my_preference(self):
        self.assertTrue(self.mdb.add_my_preference(127, {'destination_path': 'C:/mytorrent'}))
        self.assertTrue(self.mdb.add_my_preference(12345678, {'destination_path': 'C:/mytorrent'}))
        self.assertFalse(self.mdb.add_my_preference(12345678, {'destination_path': 'C:/mytorrent'}))

    def test_delete_my_preference(self):
        self.mdb.delete_preference(126)
        res = self.mdb.get_my_pref_stats(126)
        self.assertFalse(res[126])
        self.mdb.delete_preference(12348934)

    def test_update_dest_dir(self):
        self.mdb.update_dest_dir(126, 'C:/mydest')
        res = self.mdb.get_my_pref_stats(126)
        self.assertEqual(res[126], 'C:/mydest')
        self.mdb.update_dest_dir(126, {})
        self.assertEqual(res[126], 'C:/mydest')
