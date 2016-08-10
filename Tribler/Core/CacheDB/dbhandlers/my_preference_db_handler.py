import threading
from time import time
from Tribler.Core.CacheDB.dbhandlers.basic_db_handler import BasicDBHandler
from Tribler.Core.CacheDB.sqlitecachedb import str2bin
from Tribler.Core.simpledefs import NTFY_TORRENTS, NTFY_MYPREFERENCES, NTFY_UPDATE, NTFY_INSERT, NTFY_DELETE


class MyPreferenceDBHandler(BasicDBHandler):

    def __init__(self, session):
        super(MyPreferenceDBHandler, self).__init__(session, u"MyPreference")

        self.rlock = threading.RLock()

        self.recent_preflist = None
        self._torrent_db = None

    def initialize(self, *args, **kwargs):
        self._torrent_db = self.session.open_dbhandler(NTFY_TORRENTS)

    def close(self):
        super(MyPreferenceDBHandler, self).close()
        self._torrent_db = None

    def get_my_pref_list_infohash(self, return_deleted=True, limit=None):
        # Arno, 2012-08-01: having MyPreference (the shorter list) first makes
        # this faster.
        sql = u"SELECT infohash FROM MyPreference, Torrent WHERE Torrent.torrent_id == MyPreference.torrent_id"
        if not return_deleted:
            sql += u' AND destination_path != ""'

        if limit:
            sql += u" ORDER BY creation_time DESC LIMIT %d" % limit

        res = self._db.fetchall(sql)
        res = [item for sublist in res for item in sublist]
        return [str2bin(p) if p else '' for p in res]

    def get_my_pref_stats(self, torrent_id=None):
        value_name = ('torrent_id', 'destination_path',)
        if torrent_id is not None:
            where = 'torrent_id == %s' % torrent_id
        else:
            where = None
        res = self.get_all(value_name, where)
        mypref_stats = {}
        for torrent_id, destination_path in res:
            mypref_stats[torrent_id] = destination_path
        return mypref_stats

    def get_my_pref_stats_infohash(self, infohash):
        torrent_id = self._torrent_db.get_torrent_id(infohash)
        if torrent_id is not None:
            return self.get_my_pref_stats(torrent_id)[torrent_id]

    def add_my_preference(self, torrent_id, data):
        # keys in data: destination_path, creation_time, torrent_id
        if self.get_one('torrent_id', torrent_id=torrent_id) is not None:
            # Arno, 2009-03-09: Torrent already exists in myrefs.
            # Hack for hiding from lib while keeping in myprefs.
            # see standardOverview.removeTorrentFromLibrary()
            #
            self.update_dest_dir(torrent_id, data.get('destination_path'))
            infohash = self._torrent_db.get_infohash(torrent_id)
            if infohash:
                self.notifier.notify(NTFY_MYPREFERENCES, NTFY_UPDATE, infohash)
            return False

        d = {'destination_path': data.get('destination_path'),
             'creation_time': data.get('creation_time', int(time())),
             'torrent_id': torrent_id}

        self._db.insert(self.table_name, **d)

        infohash = self._torrent_db.get_infohash(torrent_id)
        if infohash:
            self.notifier.notify(NTFY_MYPREFERENCES, NTFY_INSERT, infohash)

        return True

    def delete_preference(self, torrent_id):
        # Preferences are never actually deleted from the database, only their destdirs get reset.
        # self._db.delete(self.table_name, **{'torrent_id': torrent_id})
        self.update_dest_dir(torrent_id, "")

        infohash = self._torrent_db.get_infohash(torrent_id)
        if infohash:
            self.notifier.notify(NTFY_MYPREFERENCES, NTFY_DELETE, infohash)

    def update_dest_dir(self, torrent_id, destdir):
        if not isinstance(destdir, basestring):
            self._logger.info('DESTDIR IS NOT STRING: %s', destdir)
            return
        self._db.update(self.table_name, 'torrent_id=%d' % torrent_id, destination_path=destdir)
