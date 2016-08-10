from Tribler.Core.CacheDB.peer_db_handler import PeerDBHandler
from Tribler.Core.CacheDB.sqlitecachedb import str2bin
from Tribler.Test.Core.CacheDB.dbhandlers.test_sqlitecachedbhandler import AbstractDB
from Tribler.dispersy.util import blocking_call_on_reactor_thread


FAKE_PERMID_X = 'fake_permid_x' + '0R0\x10\x00\x07*\x86H\xce=\x02\x01\x06\x05+\x81\x04\x00\x1a\x03>\x00\x04'


class TestSqlitePeerDBHandler(AbstractDB):

    def setUp(self):
        super(TestSqlitePeerDBHandler, self).setUp()

        self.p1 = str2bin(
            'MFIwEAYHKoZIzj0CAQYFK4EEABoDPgAEAAA6SYI4NHxwQ8P7P8QXgWAP+v8SaMVzF5+fSUHdAMrs6NvL5Epe1nCNSdlBHIjNjEiC5iiwSFZhRLsr')
        self.p2 = str2bin(
            'MFIwEAYHKoZIzj0CAQYFK4EEABoDPgAEAABo69alKy95H7RHzvDCsolAurKyrVvtDdT9/DzNAGvky6YejcK4GWQXBkIoQGQgxVEgIn8dwaR9B+3U')

        self.pdb = PeerDBHandler(self.session)

        self.assertFalse(self.pdb.has_peer(FAKE_PERMID_X))

    def tearDown(self):
        self.pdb.close()
        self.pdb = None
        super(TestSqlitePeerDBHandler, self).tearDown()

    @blocking_call_on_reactor_thread
    def test_getList(self):
        peer1 = self.pdb.get_peer(self.p1)
        peer2 = self.pdb.get_peer(self.p2)
        self.assertIsInstance(peer1, dict)
        self.assertIsInstance(peer2, dict)
        self.assertEqual(peer1[u'peer_id'], 1)
        self.assertEqual(peer2[u'peer_id'], 2)

    @blocking_call_on_reactor_thread
    def test_addPeer(self):
        peer_x = {'permid': FAKE_PERMID_X, 'name': 'fake peer x'}
        oldsize = self.pdb.size()
        self.pdb.add_peer(FAKE_PERMID_X, peer_x)
        self.assertEqual(self.pdb.size(), oldsize + 1)

        p = self.pdb.get_peer(FAKE_PERMID_X)
        self.assertEqual(p['name'], 'fake peer x')

        self.assertEqual(self.pdb.get_peer(FAKE_PERMID_X, 'name'), 'fake peer x')

        self.pdb.delete_peer(FAKE_PERMID_X)
        p = self.pdb.get_peer(FAKE_PERMID_X)
        self.assertIsNone(p)
        self.assertEqual(self.pdb.size(), oldsize)

        self.pdb.add_peer(FAKE_PERMID_X, peer_x)
        self.pdb.add_peer(FAKE_PERMID_X, {'permid': FAKE_PERMID_X, 'name': 'faka peer x'})
        p = self.pdb.get_peer(FAKE_PERMID_X)
        self.assertEqual(p['name'], 'faka peer x')

    @blocking_call_on_reactor_thread
    def test_aa_hasPeer(self):
        self.assertTrue(self.pdb.has_peer(self.p1))
        self.assertTrue(self.pdb.has_peer(self.p1, check_db=True))
        self.assertTrue(self.pdb.has_peer(self.p2))
        self.assertFalse(self.pdb.has_peer(FAKE_PERMID_X))

    @blocking_call_on_reactor_thread
    def test_deletePeer(self):
        peer_x = {'permid': FAKE_PERMID_X, 'name': 'fake peer x'}
        oldsize = self.pdb.size()
        p = self.pdb.get_peer(FAKE_PERMID_X)
        self.assertIsNone(p)

        self.pdb.add_peer(FAKE_PERMID_X, peer_x)
        self.assertEqual(self.pdb.size(), oldsize + 1)
        self.assertTrue(self.pdb.has_peer(FAKE_PERMID_X))
        p = self.pdb.get_peer(FAKE_PERMID_X)
        self.assertIsNotNone(p)

        self.pdb.delete_peer(FAKE_PERMID_X)
        self.assertFalse(self.pdb.has_peer(FAKE_PERMID_X))
        self.assertEqual(self.pdb.size(), oldsize)

        p = self.pdb.get_peer(FAKE_PERMID_X)
        self.assertIsNone(p)

        self.assertFalse(self.pdb.delete_peer(FAKE_PERMID_X))

    @blocking_call_on_reactor_thread
    def test_add_or_get_peer(self):
        self.assertIsInstance(self.pdb.add_or_get_peer_id(FAKE_PERMID_X), int)
        self.assertIsInstance(self.pdb.add_or_get_peer_id(FAKE_PERMID_X), int)

    @blocking_call_on_reactor_thread
    def test_get_peer_by_id(self):
        self.assertEqual(self.pdb.get_peer_by_id(1, ['name']), 'Peer 1')
        p = self.pdb.get_peer_by_id(1)
        self.assertEqual(p['name'], 'Peer 1')
        self.assertFalse(self.pdb.get_peer_by_id(1234567))
