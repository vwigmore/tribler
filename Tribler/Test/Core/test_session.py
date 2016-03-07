import socket

from nose.tools import raises

from Tribler.Core.Session import Session
from Tribler.Test.Core.base_test import TriblerCoreSessionTest


class TestSession(TriblerCoreSessionTest):

    def test_session_nickname(self):
        config = self.get_config()
        config.set_nickname(socket.gethostname())
        session = Session(config)
        self.assertNotEqual(session.sessconfig.get(u'general', u'nickname'), socket.gethostname())

    @raises(RuntimeError)
    def test_session_singleton(self):
        session = Session()
        session2 = Session()

    def test_session_prestart(self):
        session = Session()
        self.assertFalse(session.sqlite_db)
        session.prestart()
        self.assertTrue(session.sqlite_db)

    def test_create_session_through_get_instance(self):
        session = Session.get_instance()
        self.assertTrue(session)
        self.assertTrue(Session.has_instance())

    def test_session_get_instance(self):
        session = Session()
        self.assertEqual(Session.get_instance(), session)