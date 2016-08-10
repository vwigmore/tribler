from copy import deepcopy
import os
from pprint import pformat
from struct import unpack_from
from time import time
from traceback import print_exc
from Tribler.Core.CacheDB.dbhandlers.basic_db_handler import BasicDBHandler, LimitedOrderedDict, DEFAULT_ID_CACHE_SIZE
from Tribler.Core.CacheDB.sqlitecachedb import bin2str, str2bin
from Tribler.Core.TorrentDef import TorrentDef
from Tribler.Core.Utilities.search_utils import split_into_keywords, filter_keywords
from Tribler.Core.Utilities.tracker_utils import get_uniformed_tracker_url
from Tribler.Core.simpledefs import NTFY_MYPREFERENCES, NTFY_VOTECAST, NTFY_CHANNELCAST, INFOHASH_LENGTH, NTFY_TORRENTS, \
    NTFY_INSERT, NTFY_UPDATE, NTFY_TRACKERINFO


class TorrentDBHandler(BasicDBHandler):

    def __init__(self, session):
        super(TorrentDBHandler, self).__init__(session, u"Torrent")

        self.torrent_dir = None

        self.keys = ['torrent_id', 'name', 'length', 'creation_date', 'num_files',
                     'insert_time', 'secret', 'relevance', 'category', 'status',
                     'num_seeders', 'num_leechers', 'comment', 'last_tracker_check']
        self.existed_torrents = set()

        self.value_name = ['C.torrent_id', 'category', 'status', 'name', 'creation_date', 'num_files',
                           'num_leechers', 'num_seeders', 'length', 'secret', 'insert_time',
                           'relevance', 'infohash', 'last_tracker_check']

        self.value_name_for_channel = ['C.torrent_id', 'infohash', 'name', 'length',
                                       'creation_date', 'num_files', 'insert_time', 'secret',
                                       'relevance', 'category', 'status',
                                       'num_seeders', 'num_leechers', 'comment']

        self.category = None
        self.mypref_db = self.votecast_db = self.channelcast_db = self._rtorrent_handler = None

        self.infohash_id = LimitedOrderedDict(DEFAULT_ID_CACHE_SIZE)

    def initialize(self, *args, **kwargs):
        super(TorrentDBHandler, self).initialize(*args, **kwargs)
        self.category = self.session.lm.cat
        self.mypref_db = self.session.open_dbhandler(NTFY_MYPREFERENCES)
        self.votecast_db = self.session.open_dbhandler(NTFY_VOTECAST)
        self.channelcast_db = self.session.open_dbhandler(NTFY_CHANNELCAST)
        self._rtorrent_handler = self.session.lm.rtorrent_handler

    def close(self):
        super(TorrentDBHandler, self).close()
        self.category = None
        self.mypref_db = None
        self.votecast_db = None
        self.channelcast_db = None
        self._rtorrent_handler = None

    def get_torrent_id(self, infohash):
        return self.get_torrent_ids([infohash, ]).get(infohash)

    def get_torrent_ids(self, infohashes):
        unique_infohashes = set(infohashes)

        to_return = {}

        to_select = []
        for infohash in unique_infohashes:
            assert isinstance(infohash, str), "INFOHASH has invalid type: %s" % type(infohash)
            assert len(infohash) == INFOHASH_LENGTH, "INFOHASH has invalid length: %d" % len(infohash)

            if infohash in self.infohash_id:
                to_return[infohash] = self.infohash_id[infohash]
            else:
                to_select.append(bin2str(infohash))

        parameters = '?,' * len(to_select)
        parameters = parameters[:-1]
        sql_stmt = u"SELECT torrent_id, infohash FROM Torrent WHERE infohash IN (%s)" % parameters
        torrents = self._db.fetchall(sql_stmt, to_select)
        for torrent_id, infohash in torrents:
            self.infohash_id[str2bin(infohash)] = torrent_id

        for infohash in unique_infohashes:
            if infohash not in to_return:
                to_return[infohash] = self.infohash_id.get(infohash)

        if __debug__ and len(to_return) != len(unique_infohashes):
            self._logger.error("to_return doesn't match infohashes:")
            self._logger.error("to_return:")
            self._logger.error(pformat(to_return))
            self._logger.error("infohashes:")
            self._logger.error(pformat([bin2str(infohash) for infohash in unique_infohashes]))
            assert len(to_return) == len(unique_infohashes), (len(to_return), len(unique_infohashes))

        return to_return

    def get_infohash(self, torrent_id):
        sql_get_infohash = "SELECT infohash FROM Torrent WHERE torrent_id==?"
        ret = self._db.fetchone(sql_get_infohash, (torrent_id,))
        if ret:
            ret = str2bin(ret)
        return ret

    def has_torrent(self, infohash):
        assert isinstance(infohash, str), "INFOHASH has invalid type: %s" % type(infohash)
        assert len(infohash) == INFOHASH_LENGTH, "INFOHASH has invalid length: %d" % len(infohash)
        if infohash in self.existed_torrents:  # to do: not thread safe
            return True
        infohash_str = bin2str(infohash)
        existed = self._db.get_one('CollectedTorrent', 'torrent_id', infohash=infohash_str)
        if existed is None:
            return False
        else:
            self.existed_torrents.add(infohash)
            return True

    def add_external_torrent(self, torrentdef, extra_info={}):
        assert isinstance(torrentdef, TorrentDef), "TORRENTDEF has invalid type: %s" % type(torrentdef)
        assert torrentdef.is_finalized(), "TORRENTDEF is not finalized"
        infohash = torrentdef.get_infohash()
        if not self.has_torrent(infohash):
            self.add_torrent_to_db(torrentdef, extra_info)
            self.notifier.notify(NTFY_TORRENTS, NTFY_INSERT, infohash)

    def add_external_torrent_no_def(self, infohash, name, files, trackers, timestamp, extra_info={}):
        if not self.has_torrent(infohash):
            metainfo = {'info': {}, 'encoding': 'utf_8'}
            metainfo['info']['name'] = name.encode('utf_8')
            metainfo['info']['piece length'] = -1
            metainfo['info']['pieces'] = ''

            if len(files) > 1:
                files_as_dict = []
                for filename, file_length in files:
                    filename = filename.encode('utf_8')
                    files_as_dict.append({'path': [filename], 'length': file_length})
                metainfo['info']['files'] = files_as_dict

            elif len(files) == 1:
                metainfo['info']['length'] = files[0][1]
            else:
                return

            if len(trackers) > 0:
                metainfo['announce'] = trackers[0]
            else:
                metainfo['nodes'] = []

            metainfo['creation date'] = timestamp

            try:
                torrentdef = TorrentDef.load_from_dict(metainfo)
                torrentdef.infohash = infohash

                torrent_id = self.add_torrent_to_db(torrentdef, extra_info)
                if self._rtorrent_handler:
                    self._rtorrent_handler.notify_possible_torrent_infohash(infohash)

                insert_files = [(torrent_id, unicode(path), length) for path, length in files]
                sql_insert_files = "INSERT OR IGNORE INTO TorrentFiles (torrent_id, path, length) VALUES (?,?,?)"
                self._db.executemany(sql_insert_files, insert_files)
            except:
                self._logger.error("Could not create a TorrentDef instance %r %r %r %r %r %r", infohash, timestamp, name, files, trackers, extra_info)
                print_exc()

    def add_or_get_torrent_id(self, infohash):
        assert isinstance(infohash, str), "INFOHASH has invalid type: %s" % type(infohash)
        assert len(infohash) == INFOHASH_LENGTH, "INFOHASH has invalid length: %d" % len(infohash)

        torrent_id = self.get_torrent_id(infohash)
        if torrent_id is None:
            self._db.insert('Torrent', infohash=bin2str(infohash), status=u'unknown')
            torrent_id = self.get_torrent_id(infohash)
        return torrent_id

    def add_or_get_torrent_ids_return(self, infohashes):
        to_be_inserted = set()
        torrent_id_results = self.get_torrent_ids(infohashes)
        for infohash, torrent_id in torrent_id_results.iteritems():
            if torrent_id is None:
                to_be_inserted.add(infohash)

        sql = "INSERT INTO Torrent (infohash, status) VALUES (?, ?)"
        self._db.executemany(sql, [(bin2str(infohash), u'unknown') for infohash in to_be_inserted])

        torrent_id_results = self.get_torrent_ids(infohashes)
        torrent_ids = []
        for infohash in infohashes:
            torrent_ids.append(torrent_id_results[infohash])
        assert all(torrent_id for torrent_id in torrent_ids), torrent_ids
        return torrent_ids, to_be_inserted

    def _get_database_dict(self, torrentdef, extra_info={}):
        assert isinstance(torrentdef, TorrentDef), "TORRENTDEF has invalid type: %s" % type(torrentdef)
        assert torrentdef.is_finalized(), "TORRENTDEF is not finalized"

        dict = {"infohash": bin2str(torrentdef.get_infohash()),
                "name": torrentdef.get_name_as_unicode(),
                "length": torrentdef.get_length(),
                "creation_date": torrentdef.get_creation_date(),
                "num_files": len(torrentdef.get_files()),
                "insert_time": long(time()),
                "secret": 1 if torrentdef.is_private() else 0,
                "relevance": 0.0,
                "category": self.category.calculate_category(torrentdef.metainfo, torrentdef.get_name_as_unicode()),
                "status": extra_info.get("status", "unknown"),
                "comment": torrentdef.get_comment_as_unicode(),
                "is_collected": extra_info.get('is_collected', 0)
                }

        if extra_info.get("seeder", -1) != -1:
            dict["num_seeders"] = extra_info["seeder"]
        if extra_info.get("leecher", -1) != -1:
            dict["num_leechers"] = extra_info["leecher"]

        return dict

    def add_torrent_to_db(self, torrentdef, extra_info):
        assert isinstance(torrentdef, TorrentDef), "TORRENTDEF has invalid type: %s" % type(torrentdef)
        assert torrentdef.is_finalized(), "TORRENTDEF is not finalized"

        infohash = torrentdef.get_infohash()
        swarmname = torrentdef.get_name_as_unicode()
        database_dict = self._get_database_dict(torrentdef, extra_info)

        # see if there is already a torrent in the database with this infohash
        torrent_id = self.get_torrent_id(infohash)
        if torrent_id is None:  # not in database
            self._db.insert("Torrent", **database_dict)
            torrent_id = self.get_torrent_id(infohash)

        else:  # infohash in db
            del database_dict["infohash"]  # no need for infohash, its already stored
            where = "torrent_id = %d" % torrent_id
            self._db.update('Torrent', where=where, **database_dict)

        if not torrentdef.is_multifile_torrent():
            swarmname, _ = os.path.splitext(swarmname)
        self._index_torrent(torrent_id, swarmname, torrentdef.get_files_as_unicode())

        self._add_torrent_tracker(torrent_id, torrentdef, extra_info)
        return torrent_id

    def _index_torrent(self, torrent_id, swarmname, files):
        existed = self._db.get_one('CollectedTorrent', 'infohash', torrent_id=torrent_id)
        if existed:
            return

        # Niels: new method for indexing, replaces invertedindex
        # Making sure that swarmname does not include extension for single file torrents
        swarm_keywords = " ".join(split_into_keywords(swarmname))

        filedict = {}
        fileextensions = set()
        for filename in files:
            filename, extension = os.path.splitext(filename)
            for keyword in split_into_keywords(filename, to_filter_stopwords=True):
                filedict[keyword] = filedict.get(keyword, 0) + 1

            fileextensions.add(extension[1:])

        filenames = filedict.keys()
        if len(filenames) > 1000:
            def pop_sort(a, b):
                return filedict[a] - filedict[b]
            filenames.sort(cmp=pop_sort, reverse=True)
            filenames = filenames[:1000]

        values = (torrent_id, swarm_keywords, " ".join(filenames), " ".join(fileextensions))
        try:
            # INSERT OR REPLACE not working for fts3 table
            self._db.execute_write(u"DELETE FROM FullTextIndex WHERE rowid = ?", (torrent_id,))
            self._db.execute_write(
                u"INSERT INTO FullTextIndex (rowid, swarmname, filenames, fileextensions) VALUES(?,?,?,?)", values)
        except:
            # this will fail if the fts3 module cannot be found
            print_exc()

    # ------------------------------------------------------------
    # Adds the trackers of a given torrent into the database.
    # ------------------------------------------------------------
    def _add_torrent_tracker(self, torrent_id, torrentdef, extra_info={}):
        # Set add_all to True if you want to put all multi-trackers into db.
        # In the current version (4.2) only the main tracker is used.

        announce = torrentdef.get_tracker()
        announce_list = torrentdef.get_tracker_hierarchy()

        # check if to use DHT
        new_tracker_set = set()
        if torrentdef.is_private():
            new_tracker_set.add(u'no-DHT')
        else:
            new_tracker_set.add(u'DHT')

        # get rid of junk trackers
        # prepare the tracker list to add
        if announce:
            tracker_url = get_uniformed_tracker_url(announce)
            if tracker_url:
                new_tracker_set.add(tracker_url)
        if announce_list:
            for tier in announce_list:
                for tracker in tier:
                    # TODO: check this. a limited tracker list
                    if len(new_tracker_set) >= 25:
                        break
                    tracker_url = get_uniformed_tracker_url(tracker)
                    if tracker_url:
                        new_tracker_set.add(tracker_url)

        # add trackers in batch
        self.add_torrent_tracker_mapping_batch(torrent_id, list(new_tracker_set))

    def update_torrent(self, infohash, notify=True, **kw):  # watch the schema of database
        if 'seeder' in kw:
            kw['num_seeders'] = kw.pop('seeder')
        if 'leecher' in kw:
            kw['num_leechers'] = kw.pop('leecher')

        for key in kw.keys():
            if key not in self.keys:
                kw.pop(key)

        if len(kw) > 0:
            infohash_str = bin2str(infohash)
            where = "infohash='%s'" % infohash_str
            self._db.update(self.table_name, where, **kw)

        if notify:
            self.notifier.notify(NTFY_TORRENTS, NTFY_UPDATE, infohash)

    def on_torrent_collect_response(self, infohashes):
        infohash_list = [bin2str(infohash) for infohash in infohashes]

        i_parameters = u"?," * len(infohash_list)
        i_parameters = i_parameters[:-1]

        sql = u"SELECT torrent_id, infohash FROM Torrent WHERE infohash in (%s)" % i_parameters
        results = self._db.fetchall(sql, infohash_list)

        info_dict = {}
        for torrent_id, infohash in results:
            if infohash:
                info_dict[infohash] = torrent_id

        to_be_inserted = []
        for infohash in infohash_list:
            if infohash in info_dict:
                continue
            to_be_inserted.append((infohash,))

        if len(to_be_inserted) > 0:
            sql = u"INSERT OR IGNORE INTO Torrent (infohash) VALUES (?)"
            self._db.executemany(sql, to_be_inserted)

    def on_search_response(self, torrents):
        status = u'unknown'

        torrents = [(bin2str(torrent[0]), torrent[1], torrent[2], torrent[3], torrent[4][0],
                     torrent[5]) for torrent in torrents]
        infohash = [(torrent[0],) for torrent in torrents]

        sql = u"SELECT torrent_id, infohash, is_collected, name FROM Torrent WHERE infohash == ?"
        results = self._db.executemany(sql, infohash) or []

        infohash_tid = {}

        tid_collected = set()
        tid_name = {}
        for torrent_id, infohash, is_collected, name in results:
            infohash = str(infohash)

            if infohash:
                infohash_tid[infohash] = torrent_id
            if is_collected:
                tid_collected.add(torrent_id)
            tid_name[torrent_id] = name

        insert = []
        update = []
        update_infohash = []
        to_be_indexed = []
        for infohash, swarmname, length, nrfiles, category, creation_date in torrents:
            tid = infohash_tid.get(infohash, None)

            if tid:  # we know this torrent
                if tid not in tid_collected and swarmname != tid_name.get(tid, ''):  # if not collected and name not equal then do fullupdate
                    update.append((swarmname, length, nrfiles, category, creation_date, infohash, status, tid))
                    to_be_indexed.append((tid, swarmname))

                elif infohash and infohash not in infohash_tid:
                    update_infohash.append((infohash, tid))
            else:
                insert.append((swarmname, length, nrfiles, category, creation_date, infohash, status))

        if len(update) > 0:
            sql = u"UPDATE Torrent SET name = ?, length = ?, num_files = ?, category = ?, creation_date = ?," \
                  u" infohash = ?, status = ? WHERE torrent_id = ?"
            self._db.executemany(sql, update)

        if len(update_infohash) > 0:
            sql = u"UPDATE Torrent SET infohash = ? WHERE torrent_id = ?"
            self._db.executemany(sql, update_infohash)

        if len(insert) > 0:
            sql = u"INSERT INTO Torrent (name, length, num_files, category, creation_date, infohash," \
                  u" status) VALUES (?, ?, ?, ?, ?, ?, ?)"
            try:
                self._db.executemany(sql, insert)

                were_inserted = [(inserted[5],) for inserted in insert]
                sql = u"SELECT torrent_id, name FROM Torrent WHERE infohash == ?"
                to_be_indexed = to_be_indexed + list(self._db.executemany(sql, were_inserted))
            except:
                print_exc()
                self._logger.error(u"infohashes: %s", insert)

        for torrent_id, swarmname in to_be_indexed:
            self._index_torrent(torrent_id, swarmname, [])

    def get_torrent_check_retries(self, torrent_id):
        sql = u"SELECT tracker_check_retries FROM Torrent WHERE torrent_id = ?"
        result = self._db.fetchone(sql, (torrent_id,))
        return result

    def update_torrent_check_result(self, torrent_id, infohash, seeders, leechers, last_check, next_check, status,
                                 retries):
        sql = u"UPDATE Torrent SET num_seeders = ?, num_leechers = ?, last_tracker_check = ?, next_tracker_check = ?," \
              u" status = ?, tracker_check_retries = ? WHERE torrent_id = ?"

        self._db.execute_write(sql, (seeders, leechers, last_check, next_check, status, retries, torrent_id))

        self._logger.debug(u"update result %d/%d for %s/%d", seeders, leechers, bin2str(infohash), torrent_id)

        # notify
        self.notifier.notify(NTFY_TORRENTS, NTFY_UPDATE, infohash)

    def add_torrent_tracker_mapping(self, torrent_id, tracker):
        self.add_torrent_tracker_mapping_batch(torrent_id, [tracker, ])

    def add_torrent_tracker_mapping_batch(self, torrent_id, tracker_list):
        if not tracker_list:
            return

        parameters = u"?," * len(tracker_list)
        parameters = parameters[:-1]
        sql = u"SELECT tracker FROM TrackerInfo WHERE tracker IN (%s)" % parameters

        found_tracker_list = self._db.fetchall(sql, tuple(tracker_list))
        found_tracker_list = [tracker[0] for tracker in found_tracker_list]

        # update tracker info
        not_found_tracker_list = [tracker for tracker in tracker_list if tracker not in found_tracker_list]
        for tracker in not_found_tracker_list:
            if self.session.lm.tracker_manager is not None:
                self.session.lm.tracker_manager.add_tracker(tracker)

        # update torrent-tracker mapping
        sql = 'INSERT OR IGNORE INTO TorrentTrackerMapping(torrent_id, tracker_id)'\
            + ' VALUES(?, (SELECT tracker_id FROM TrackerInfo WHERE tracker = ?))'
        new_mapping_list = [(torrent_id, tracker) for tracker in tracker_list]
        if new_mapping_list:
            self._db.executemany(sql, new_mapping_list)

        # add trackers into the torrent file if it has been collected
        if not self.session.get_torrent_store() or self.session.lm.torrent_store is None:
            return

        infohash = self.get_infohash(torrent_id)
        if infohash and self.session.has_collected_torrent(infohash):
            torrent_data = self.session.get_collected_torrent(infohash)
            tdef = TorrentDef.load_from_memory(torrent_data)

            new_tracker_list = []
            for tracker in tracker_list:
                if tdef.get_tracker() and tracker == tdef.get_tracker():
                    continue
                if tdef.get_tracker_hierarchy() and tracker in tdef.get_tracker_hierarchy():
                    continue
                if tracker in ('DHT', 'no-DHT'):
                    continue
                tracker = get_uniformed_tracker_url(tracker)
                if tracker and [tracker] not in new_tracker_list:
                    new_tracker_list.append([tracker])

            if tdef.get_tracker_hierarchy():
                new_tracker_list = tdef.get_tracker_hierarchy() + new_tracker_list
            if new_tracker_list:
                tdef.set_tracker_hierarchy(new_tracker_list)
                # have to use bencode to get around the TorrentDef.is_finalized() check in TorrentDef.encode()
                self.session.save_collected_torrent(infohash, bencode(tdef.metainfo))

    def get_torrents_on_tracker(self, tracker, current_time):
        sql = """
            SELECT T.torrent_id, T.infohash, T.last_tracker_check
              FROM Torrent T, TrackerInfo TI, TorrentTrackerMapping TTM
              WHERE TI.tracker = ?
              AND TI.tracker_id = TTM.tracker_id AND T.torrent_id = TTM.torrent_id
              AND next_tracker_check < ?
            """
        infohash_list = self._db.fetchall(sql, (tracker, current_time))
        return [(torrent_id, str2bin(infohash), last_tracker_check) for torrent_id, infohash, last_tracker_check in infohash_list]

    def get_tracker_list_by_torrent_id(self, torrent_id):
        sql = 'SELECT TR.tracker FROM TrackerInfo TR, TorrentTrackerMapping MP'\
            + ' WHERE MP.torrent_id = ?'\
            + ' AND TR.tracker_id = MP.tracker_id'
        tracker_list = self._db.fetchall(sql, (torrent_id,))
        return [tracker[0] for tracker in tracker_list]

    def get_tracker_list_by_infohash(self, infohash):
        torrent_id = self.get_torrent_id(infohash)
        return self.get_tracker_list_by_torrent_id(torrent_id)

    def add_tracker_info(self, tracker, to_notify=True):
        self.add_tracker_info_batch([tracker, ], to_notify)

    def add_tracker_info_batch(self, tracker_list, to_notify=True):
        sql = 'INSERT INTO TrackerInfo(tracker) VALUES(?)'
        self._db.executemany(sql, [(tracker,) for tracker in tracker_list])

        if to_notify:
            self.notifier.notify(NTFY_TRACKERINFO, NTFY_INSERT, tracker_list)

    def get_tracker_info_list(self):
        sql = 'SELECT tracker, last_check, failures, is_alive FROM TrackerInfo'
        tracker_info_list = self._db.fetchall(sql)
        return tracker_info_list

    def update_tracker_info(self, args):
        sql = 'UPDATE TrackerInfo SET'\
            + ' last_check = ?, failures = ?, is_alive = ?'\
            + ' WHERE tracker = ?'
        self._db.executemany(sql, args)

    def get_recently_alive_trackers(self, limit=10):
        sql = """
            SELECT DISTINCT tracker FROM TrackerInfo
              WHERE is_alive = 1
              AND tracker != 'no-DHT' AND tracker != 'DHT'
              ORDER BY last_check DESC LIMIT ?
            """
        trackers = self._db.fetchall(sql, (limit,))
        return [tracker[0] for tracker in trackers]

    def get_torrent(self, infohash, keys=None, include_mypref=True):
        assert isinstance(infohash, str), "INFOHASH has invalid type: %s" % type(infohash)
        assert len(infohash) == INFOHASH_LENGTH, "INFOHASH has invalid length: %d" % len(infohash)

        if keys is None:
            keys = deepcopy(self.value_name)
        else:
            keys = list(keys)

        res = self._db.get_one('Torrent C', keys, infohash=bin2str(infohash))

        if not res:
            return None
        torrent = dict(zip(keys, res))

        torrent['infohash'] = infohash

        if include_mypref:
            tid = torrent['C.torrent_id']
            stats = self.mypref_db.get_my_pref_stats(tid)

            if stats:
                torrent['myDownloadHistory'] = True
                torrent['destination_path'] = stats[tid]
            else:
                torrent['myDownloadHistory'] = False

        return torrent

    def get_library_torrents(self, keys):
        sql = u"SELECT " + u", ".join(keys) + u""" FROM MyPreference, Torrent LEFT JOIN ChannelTorrents
            ON Torrent.torrent_id = ChannelTorrents.torrent_id WHERE destination_path != ''
            AND MyPreference.torrent_id = Torrent.torrent_id"""
        data = self._db.fetchall(sql)

        fixed = TorrentDBHandler.__fix_torrents(keys, data)
        return fixed

    @staticmethod
    def __fix_torrents(keys, results):
        def fix_value(key):
            if key in keys:
                key_index = keys.index(key)
                for i in range(len(results)):
                    result = list(results[i])
                    if result[key_index]:
                        result[key_index] = str2bin(result[key_index])
                        results[i] = result
        fix_value('infohash')
        return results

    def get_number_collected_torrents(self):
        return self._db.get_one('CollectedTorrent', 'count(torrent_id)')

    def get_recently_collected_torrents(self, limit):
        sql = u"""
            SELECT CT.infohash, CT.num_seeders, CT.num_leechers, T.last_tracker_check, CT.insert_time
             FROM Torrent T, CollectedTorrent CT
             WHERE CT.torrent_id = T.torrent_id
             AND T.secret is not 1 ORDER BY CT.insert_time DESC LIMIT ?
             """
        results = self._db.fetchall(sql, (limit,))
        return [[str2bin(result[0]), result[1], result[2], result[3] or 0, result[4]] for result in results]

    def get_randomly_collected_torrents(self, insert_time, limit):
        sql = u"""
            SELECT CT.infohash, CT.num_seeders, CT.num_leechers, T.last_tracker_check
             FROM Torrent T, CollectedTorrent CT
             WHERE CT.torrent_id = T.torrent_id
             AND CT.insert_time < ?
             AND T.secret is not 1 ORDER BY RANDOM() DESC LIMIT ?
            """
        results = self._db.fetchall(sql, (insert_time, limit))
        return [[str2bin(result[0]), result[1], result[2], result[3] or 0] for result in results]

    def select_torrents_to_collect(self, hashes):
        parameters = '?,' * len(hashes)
        parameters = parameters[:-1]

        # TODO: bias according to votecast, popular first

        sql = u"SELECT infohash FROM Torrent WHERE is_collected == 0 AND infohash IN (%s)" % parameters
        results = self._db.fetchall(sql, map(bin2str, hashes))
        return [str2bin(infohash) for infohash, in results]

    def get_torrents_stats(self):
        return self._db.get_one('CollectedTorrent', ['count(torrent_id)', 'sum(length)', 'sum(num_files)'])

    def free_space(self, torrents2del):
        if self.channelcast_db and self.channelcast_db._channel_id:
            sql = U"""
                SELECT name, torrent_id, infohash, relevance,
                MIN(relevance, 2500) + MIN(500, num_leechers) + 4*MIN(500, num_seeders) - (MAX(0, MIN(500, (%d - creation_date)/86400)) ) AS weight
                FROM CollectedTorrent
                WHERE torrent_id NOT IN (SELECT torrent_id FROM MyPreference)
                AND torrent_id NOT IN (SELECT torrent_id FROM ChannelTorrents WHERE channel_id == %d)
                ORDER BY weight
                LIMIT %d
            """ % (int(time()), self.channelcast_db._channel_id, torrents2del)
        else:
            sql = u"""
                SELECT name, torrent_id, infohash, relevance,
                    min(relevance,2500) +  min(500,num_leechers) + 4*min(500,num_seeders) - (max(0,min(500,(%d-creation_date)/86400)) ) AS weight
                FROM CollectedTorrent
                WHERE torrent_id NOT IN (SELECT torrent_id FROM MyPreference)
                ORDER BY weight
                LIMIT %d
            """ % (int(time()), torrents2del)

        res_list = self._db.fetchall(sql)
        if len(res_list) == 0:
            return 0

        # delete torrents from db
        sql_del_torrent = u"UPDATE Torrent SET name = NULL, is_collected = 0 WHERE torrent_id = ?"

        tids = []
        for _name, torrent_id, infohash, _relevance, _weight in res_list:
            tids.append((torrent_id,))
            self.session.delete_collected_torrent(infohash)

        self._db.executemany(sql_del_torrent, tids)
        # self._db.executemany(sql_del_tracker, tids)
        deleted = self._db.connection.changes()
        # self._db.executemany(sql_del_pref, tids)

        # but keep the infohash in db to maintain consistence with preference db
        # torrent_id_infohashes = [(torrent_id,infohash_str,relevance) for torrent_file_name, torrent_id, infohash_str, relevance, weight in res_list]
        # sql_insert =  "insert into Torrent (torrent_id, infohash, relevance) values (?,?,?)"
        # self._db.executemany(sql_insert, torrent_id_infohashes)

        self._logger.info("Erased %d torrents", deleted)
        return deleted

    def search_names(self, kws, local=True, keys=None, do_sort=True):
        assert 'infohash' in keys
        assert not do_sort or ('num_seeders' in keys or 'T.num_seeders' in keys)

        infohash_index = keys.index('infohash')
        num_seeders_index = keys.index('num_seeders') if 'num_seeders' in keys else -1

        if num_seeders_index == -1:
            do_sort = False

        values = ", ".join(keys)
        mainsql = "SELECT " + values + ", C.channel_id, Matchinfo(FullTextIndex) FROM"
        if local:
            mainsql += " Torrent T"
        else:
            mainsql += " CollectedTorrent T"

        mainsql += """, FullTextIndex
                    LEFT OUTER JOIN _ChannelTorrents C ON T.torrent_id = C.torrent_id
                    WHERE t.name IS NOT NULL AND t.torrent_id = FullTextIndex.rowid AND C.deleted_at IS NULL AND FullTextIndex MATCH ?
                    """

        if not local:
            mainsql += "AND T.secret is not 1 LIMIT 250"

        query = " ".join(filter_keywords(kws))
        not_negated = [kw for kw in filter_keywords(kws) if kw[0] != '-']

        results = self._db.fetchall(mainsql, (query,))

        channels = set()
        channel_dict = {}
        for result in results:
            if result[-2]:
                channels.add(result[-2])

        if len(channels) > 0:
            # results are tuples of (id, str(dispersy_cid), name, description,
            # nr_torrents, nr_favorites, nr_spam, my_vote, modified, id ==
            # self._channel_id)
            for channel in self.channelcast_db.get_channels(channels):
                if channel[1] != '-1':
                    channel_dict[channel[0]] = channel

        my_channel_id = self.channelcast_db._channel_id or 0

        result_dict = {}

        # step 1, merge torrents keep one with best channel
        for result in results:
            channel_id = result[-2]
            channel = channel_dict.get(channel_id, None)

            infohash = result[infohash_index]
            if channel:
                # ignoring spam channels
                if channel[7] < 0:
                    continue

                # see if we have a better channel in torrents_dict
                if infohash in result_dict:
                    old_channel = channel_dict.get(result_dict[infohash][-2], False)
                    if old_channel:

                        # allways prefer my channel
                        if old_channel[0] == my_channel_id:
                            continue

                        # allways prefer channel with higher vote
                        if channel[7] < old_channel[7]:
                            continue

                        votes = (channel[5] or 0) - (channel[6] or 0)
                        oldvotes = (old_channel[5] or 0) - (old_channel[6] or 0)
                        if votes < oldvotes:
                            continue

                result_dict[infohash] = result

            elif infohash not in result_dict:
                result_dict[infohash] = result


        # step 2, fix all dict fields
        dont_sort_list = []
        results = [list(result) for result in result_dict.values()]
        for index in xrange(len(results) - 1, -1, -1):
            result = results[index]

            result[infohash_index] = str2bin(result[infohash_index])

            matches = {'swarmname': set(), 'filenames': set(), 'fileextensions': set()}

            # Matchinfo is documented at: http://www.sqlite.org/fts3.html#matchinfo
            matchinfo = str(result[-1])
            num_phrases, num_cols = unpack_from('II', matchinfo)
            unpack_str = 'I' * (3 * num_cols * num_phrases)
            matchinfo = unpack_from('II' + unpack_str, matchinfo)

            swarmnames, filenames, fileextensions = [
                [matchinfo[3 * (i + p * num_cols) + 2] for p in range(num_phrases)]
                for i in range(num_cols)
            ]

            for i, keyword in enumerate(not_negated):
                if swarmnames[i]:
                    matches['swarmname'].add(keyword)
                if filenames[i]:
                    matches['filenames'].add(keyword)
                if fileextensions[i]:
                    matches['fileextensions'].add(keyword)
            result[-1] = matches

            channel = channel_dict.get(result[-2], (result[-2], None, '', '', 0, 0, 0, 0, 0, False))
            result.extend(channel)

            if do_sort and result[num_seeders_index] <= 0:
                dont_sort_list.append((index, result))

        if do_sort:
            # Remove the items with 0 seeders from the results list so the sort is faster, append them to the
            # results list afterwards.
            for index, result in dont_sort_list:
                results.pop(index)

            def compare(a, b):
                return cmp(a[num_seeders_index], b[num_seeders_index])
            results.sort(compare, reverse=True)

            for index, result in dont_sort_list:
                results.append(result)

        if not local:
            results = results[:25]

        return results

    def get_autocomplete_terms(self, keyword, max_terms, limit=100):
        sql = "SELECT swarmname FROM FullTextIndex WHERE swarmname MATCH ? LIMIT ?"
        result = self._db.fetchall(sql, (keyword + '*', limit))

        all_terms = set()
        for line, in result:
            if len(all_terms) >= max_terms:
                break
            i1 = line.find(keyword)
            i2 = line.find(' ', i1 + len(keyword))
            all_terms.add(line[i1:i2] if i2 >= 0 else line[i1:])

        if keyword in all_terms:
            all_terms.remove(keyword)
        if '' in all_terms:
            all_terms.remove('')

        return list(all_terms)

    def get_search_suggestion(self, keywords, limit=1):
        match = [keyword.lower() for keyword in keywords if len(keyword) > 3]

        def lev(a, b):
            "Calculates the Levenshtein distance between a and b."
            n, m = len(a), len(b)
            if n > m:
                # Make sure n <= m, to use O(min(n,m)) space
                a, b = b, a
                n, m = m, n

            current = range(n + 1)
            for i in range(1, m + 1):
                previous, current = current, [i] + [0] * n
                for j in range(1, n + 1):
                    add, delete = previous[j] + 1, current[j - 1] + 1
                    change = previous[j - 1]
                    if a[j - 1] != b[i - 1]:
                        change = change + 1
                    current[j] = min(add, delete, change)

            return current[n]

        def levcollate(s1, s2):
            l1 = sum(sorted([lev(a, b) for a in s1.split() for b in match])[:len(match)])
            l2 = sum(sorted([lev(a, b) for a in s2.split() for b in match])[:len(match)])

            # return -1 if s1<s2, +1 if s1>s2 else 0
            if l1 < l2:
                return -1
            if l1 > l2:
                return 1
            return 0

        cursor = self._db.get_cursor()
        connection = cursor.getconnection()
        connection.createcollation("leven", levcollate)

        sql = "SELECT swarmname FROM FullTextIndex WHERE swarmname MATCH ? ORDER By swarmname collate leven ASC LIMIT ?"
        results = self._db.fetchall(sql, (' OR '.join(['*%s*' % m for m in match]), limit))
        connection.createcollation("leven", None)
        return [result[0] for result in results]
