# Written by Jie Yang
# see LICENSE.txt for license information
# Note for Developers: Please write a unittest in Tribler/Test/test_sqlitecachedbhandler.py
# for any function you add to database.
# Please reuse the functions in sqlitecachedb as much as possible
import logging
from collections import OrderedDict

from Tribler.dispersy.taskmanager import TaskManager

VOTECAST_FLUSH_DB_INTERVAL = 15

DEFAULT_ID_CACHE_SIZE = 1024 * 5


class LimitedOrderedDict(OrderedDict):

    def __init__(self, limit, *args, **kargs):
        super(LimitedOrderedDict, self).__init__(*args, **kargs)
        self._limit = limit

    def __setitem__(self, *args, **kargs):
        super(LimitedOrderedDict, self).__setitem__(*args, **kargs)
        if len(self) > self._limit:
            self.popitem(last=False)


class BasicDBHandler(TaskManager):

    def __init__(self, session, table_name):
        super(BasicDBHandler, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)

        self.session = session
        self._db = self.session.sqlite_db
        self.table_name = table_name
        self.notifier = session.notifier

    def initialize(self, *args, **kwargs):
        """
        Initializes this DBHandler.
        """
        pass

    def close(self):
        self.cancel_all_pending_tasks()

    def size(self):
        return self._db.size(self.table_name)

    def get_one(self, value_name, where=None, conj=u"AND", **kw):
        return self._db.get_one(self.table_name, value_name, where=where, conj=conj, **kw)

    def get_all(self, value_name, where=None, group_by=None, having=None, order_by=None, limit=None, offset=None, conj=u"AND", **kw):
        return self._db.get_all(self.table_name, value_name, where=where, group_by=group_by, having=having, order_by=order_by, limit=limit, offset=offset, conj=conj, **kw)


