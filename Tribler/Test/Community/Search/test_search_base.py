from Tribler.Test.test_as_server import AbstractServer
from Tribler.community.search.community import SearchCommunity
from Tribler.dispersy.dispersy import Dispersy
from Tribler.dispersy.endpoint import ManualEnpoint
from Tribler.dispersy.member import DummyMember
from Tribler.dispersy.util import blocking_call_on_reactor_thread


class AbstractTestSearchCommunity(AbstractServer):

    # We have to initialize Dispersy and the search community on the reactor thread
    @blocking_call_on_reactor_thread
    def setUp(self):
        super(AbstractTestSearchCommunity, self).setUp()

        self.dispersy = Dispersy(ManualEnpoint(0), self.getStateDir())
        self.dispersy._database.open()
        self.master_member = DummyMember(self.dispersy, 1, "a" * 20)
        self.member = self.dispersy.get_new_member(u"curve25519")
        self.search_community = SearchCommunity(self.dispersy, self.master_member, self.member)
        self.search_community.initiate_meta_messages()
        self.search_community.initialize()

    def tearDown(self, annotate=True):
        self.search_community.cancel_all_pending_tasks()
        super(AbstractTestSearchCommunity, self).tearDown(annotate)
