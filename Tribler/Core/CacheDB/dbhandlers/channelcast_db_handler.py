from collections import defaultdict
import json
from time import time
from twisted.internet.task import LoopingCall
from Tribler.Core.CacheDB.dbhandlers.basic_db_handler import BasicDBHandler
from Tribler.Core.CacheDB.sqlitecachedb import str2bin, bin2str
from Tribler.Core.Utilities.search_utils import split_into_keywords
from Tribler.Core.simpledefs import NTFY_VOTECAST, NTFY_TORRENTS, NTFY_CHANNELCAST, NTFY_UPDATE, NTFY_INSERT, \
    NTFY_CREATE, NTFY_MODIFIED, SIGNAL_CHANNEL_COMMUNITY, SIGNAL_ON_TORRENT_UPDATED, NTFY_COMMENTS, NTFY_DELETE, \
    NTFY_PLAYLISTS, NTFY_MODIFICATIONS, NTFY_MODERATIONS, NTFY_MARKINGS, NTFY_STATE


class ChannelCastDBHandler(BasicDBHandler):

    def __init__(self, session):
        super(ChannelCastDBHandler, self).__init__(session, u"_Channels")

        self._channel_id = None
        self.my_dispersy_cid = None

        self.votecast_db = None
        self.torrent_db = None

    def initialize(self, *args, **kwargs):
        self._channel_id = self.get_my_channel_id()
        self._logger.debug(u"Channels: my channel is %s", self._channel_id)

        self.votecast_db = self.session.open_dbhandler(NTFY_VOTECAST)
        self.torrent_db = self.session.open_dbhandler(NTFY_TORRENTS)

        def update_nr_torrents():
            rows = self.get_channel_nr_torrents(50)
            update = "UPDATE _Channels SET nr_torrents = ? WHERE id = ?"
            self._db.executemany(update, rows)

            rows = self.get_channel_nr_torrents_latest_update(50)
            update = "UPDATE _Channels SET nr_torrents = ?, modified = ? WHERE id = ?"
            self._db.executemany(update, rows)

        self.register_task(u"update_nr_torrents", LoopingCall(update_nr_torrents)).start(300, now=False)

    def close(self):
        super(ChannelCastDBHandler, self).close()
        self._channel_id = None
        self.my_dispersy_cid = None

        self.votecast_db = None
        self.torrent_db = None

    def get_metadata_torrents(self, is_collected=True, limit=20):
        stmt = u"""
SELECT T.torrent_id, T.infohash, T.name, T.length, T.category, T.status, T.num_seeders, T.num_leechers, CMD.value
FROM MetaDataTorrent, ChannelTorrents AS CT, ChannelMetaData AS CMD, Torrent AS T
WHERE CT.id == MetaDataTorrent.channeltorrent_id
  AND CMD.id == MetaDataTorrent.metadata_id
  AND T.torrent_id == CT.torrent_id
  AND CMD.type == 'metadata-json'
  AND CMD.value LIKE '%thumb_hash%'
  AND T.is_collected == ?
ORDER BY CMD.time_stamp DESC LIMIT ?;
"""
        result_list = self._db.fetchall(stmt, (int(is_collected), limit)) or []
        torrent_list = []
        for torrent_id, info_hash, name, length, category, status, num_seeders, num_leechers, metadata_json in result_list:
            torrent_dict = {'id': torrent_id,
                            'info_hash': str2bin(info_hash),
                            'name': name,
                            'length': length,
                            'category': category,
                            'status': status,
                            'num_seeders': num_seeders,
                            'num_leechers': num_leechers,
                            'metadata-json': metadata_json}
            torrent_list.append(torrent_dict)

        return torrent_list

    # dispersy helper functions
    def _get_my_dispersy_cid(self):
        if not self.my_dispersy_cid:
            from Tribler.community.channel.community import ChannelCommunity

            for community in self.session.lm.dispersy.get_communities():
                if isinstance(community, ChannelCommunity) and community.master_member and community.master_member.private_key:
                    self.my_dispersy_cid = community.cid
                    break

        return self.my_dispersy_cid

    def get_torrent_metadata(self, channel_torrent_id):
        stmt = u"""SELECT ChannelMetadata.value FROM ChannelMetadata, MetaDataTorrent
                   WHERE type = 'metadata-json'
                   AND ChannelMetadata.id = MetaDataTorrent.metadata_id
                   AND MetaDataTorrent.channeltorrent_id = ?"""
        result = self._db.fetchone(stmt, (channel_torrent_id,))
        if result:
            metadata_dict = json.loads(result)
            metadata_dict['thumb_hash'] = metadata_dict['thumb_hash'].decode('hex')
            return metadata_dict

    def get_dispersy_cid_from_cid(self, channel_id):
        return self._db.fetchone(u"SELECT dispersy_cid FROM Channels WHERE id = ?", (channel_id,))

    def get_channel_id_from_dispersy_cid(self, dispersy_cid):
        return self._db.fetchone(u"SELECT id FROM Channels WHERE dispersy_cid = ?", (dispersy_cid,))

    def get_count_max_from_cid(self, channel_id):
        sql = u"SELECT COUNT(*), MAX(inserted) FROM ChannelTorrents WHERE channel_id = ? LIMIT 1"
        return self._db.fetchone(sql, (channel_id,))

    def on_channel_from_dispersy(self, dispersy_cid, peer_id, name, description):
        if isinstance(dispersy_cid, str):
            _dispersy_cid = buffer(dispersy_cid)
        else:
            _dispersy_cid = dispersy_cid

        # merge channels if we detect upgrade from old-channelcast to new-dispersy-channelcast
        get_channel = "SELECT id FROM Channels Where peer_id = ? and dispersy_cid == -1"
        channel_id = self._db.fetchone(get_channel, (peer_id,))

        if channel_id:  # update this channel
            update_channel = "UPDATE _Channels SET dispersy_cid = ?, name = ?, description = ? WHERE id = ?"
            self._db.execute_write(update_channel, (_dispersy_cid, name, description, channel_id))

            self.notifier.notify(NTFY_CHANNELCAST, NTFY_UPDATE, channel_id)

        else:
            get_channel = "SELECT id FROM Channels Where dispersy_cid = ?"
            channel_id = self._db.fetchone(get_channel, (_dispersy_cid,))

            if channel_id:
                update_channel = "UPDATE _Channels SET name = ?, description = ?, peer_id = ? WHERE dispersy_cid = ?"
                self._db.execute_write(update_channel, (name, description, peer_id, _dispersy_cid))

            else:
                # insert channel
                insert_channel = "INSERT INTO _Channels (dispersy_cid, peer_id, name, description) VALUES (?, ?, ?, ?); SELECT last_insert_rowid();"
                channel_id = self._db.fetchone(insert_channel, (_dispersy_cid, peer_id, name, description))

            self.notifier.notify(NTFY_CHANNELCAST, NTFY_INSERT, channel_id)

        if not self._channel_id and self._get_my_dispersy_cid() == dispersy_cid:
            self._channel_id = channel_id
            self.notifier.notify(NTFY_CHANNELCAST, NTFY_CREATE, channel_id)
        return channel_id

    def on_channel_modification_from_dispersy(self, channel_id, modification_type, modification_value):
        if modification_type in ['name', 'description']:
            update_channel = "UPDATE _Channels Set " + modification_type + " = ?, modified = ? WHERE id = ?"
            self._db.execute_write(update_channel, (modification_value, long(time()), channel_id))

            self.notifier.notify(NTFY_CHANNELCAST, NTFY_MODIFIED, channel_id)

    def on_torrents_from_dispersy(self, torrentlist):
        infohashes = [torrent[3] for torrent in torrentlist]
        torrent_ids, inserted = self.torrent_db.add_or_get_torrent_ids_return(infohashes)

        insert_data = []
        updated_channels = {}

        for i, torrent in enumerate(torrentlist):
            channel_id, dispersy_id, peer_id, infohash, timestamp, name, files, trackers = torrent
            torrent_id = torrent_ids[i]

            # if new or not yet collected
            if infohash in inserted:
                self.torrent_db.add_external_torrent_no_def(
                    infohash, name, files, trackers, timestamp, {'dispersy_id': dispersy_id})

            insert_data.append((dispersy_id, torrent_id, channel_id, peer_id, name, timestamp))
            updated_channels[channel_id] = updated_channels.get(channel_id, 0) + 1

        if len(insert_data) > 0:
            sql_insert_torrent = "INSERT INTO _ChannelTorrents (dispersy_id, torrent_id, channel_id, peer_id, name, time_stamp) VALUES (?,?,?,?,?,?)"
            self._db.executemany(sql_insert_torrent, insert_data)

        updated_channel_torrent_dict = defaultdict(list)
        for torrent in torrentlist:
            channel_id, dispersy_id, peer_id, infohash, timestamp, name, files, trackers = torrent
            channel_torrent_id = self.get_channel_torrent_id(channel_id, infohash)
            updated_channel_torrent_dict[channel_id].append({u'info_hash': infohash,
                                                             u'channel_torrent_id': channel_torrent_id})

        sql_update_channel = "UPDATE _Channels SET modified = strftime('%s','now'), nr_torrents = nr_torrents+? WHERE id = ?"
        update_channels = [(new_torrents, channel_id) for channel_id, new_torrents in updated_channels.iteritems()]
        self._db.executemany(sql_update_channel, update_channels)

        for channel_id in updated_channels.keys():
            self.notifier.notify(NTFY_CHANNELCAST, NTFY_UPDATE, channel_id)

        for channel_id, item in updated_channel_torrent_dict.items():
            # inform the channel_manager about new channel torrents
            self.notifier.notify(SIGNAL_CHANNEL_COMMUNITY, SIGNAL_ON_TORRENT_UPDATED, channel_id, item)

    def on_remove_torrent_from_dispersy(self, channel_id, dispersy_id, redo):
        sql = "UPDATE _ChannelTorrents SET deleted_at = ? WHERE channel_id = ? and dispersy_id = ?"

        if redo:
            deleted_at = None
        else:
            deleted_at = long(time())
        self._db.execute_write(sql, (deleted_at, channel_id, dispersy_id))

        self.notifier.notify(NTFY_CHANNELCAST, NTFY_UPDATE, channel_id)

    def on_torrent_modification_from_dispersy(self, channeltorrent_id, modification_type, modification_value):
        if modification_type in ['name', 'description']:
            update_torrent = "UPDATE _ChannelTorrents SET " + modification_type + " = ?, modified = ? WHERE id = ?"
            self._db.execute_write(update_torrent, (modification_value, long(time()), channeltorrent_id))

            sql = "Select infohash From Torrent, ChannelTorrents Where Torrent.torrent_id = ChannelTorrents.torrent_id And ChannelTorrents.id = ?"
            infohash = self._db.fetchone(sql, (channeltorrent_id,))

            if infohash:
                infohash = str2bin(infohash)
                self.notifier.notify(NTFY_TORRENTS, NTFY_UPDATE, infohash)

        elif modification_type in ['swift-url']:
            sql = "Select infohash From Torrent, ChannelTorrents Where Torrent.torrent_id = ChannelTorrents.torrent_id And ChannelTorrents.id = ?"
            infohash = self._db.fetchone(sql, (channeltorrent_id,))

    def add_or_get_channel_torrent_id(self, channel_id, infohash):
        torrent_id = self.torrent_db.add_or_get_torrent_id(infohash)

        sql = "SELECT id FROM _ChannelTorrents WHERE torrent_id = ? AND channel_id = ?"
        channeltorrent_id = self._db.fetchone(sql, (torrent_id, channel_id))
        if not channeltorrent_id:
            insert_torrent = "INSERT OR IGNORE INTO _ChannelTorrents (dispersy_id, torrent_id, channel_id, time_stamp) VALUES (?,?,?,?);"
            self._db.execute_write(insert_torrent, (-1, torrent_id, channel_id, -1))

            channeltorrent_id = self._db.fetchone(sql, (torrent_id, channel_id))
        return channeltorrent_id

    def get_channel_torrent_id(self, channel_id, info_hash):
        torrent_id = self.torrent_db.get_torrent_id(info_hash)
        if torrent_id:
            sql = "SELECT id FROM ChannelTorrents WHERE torrent_id = ? and channel_id = ?"
            channeltorrent_id = self._db.fetchone(sql, (torrent_id, channel_id))
            return channeltorrent_id

    def has_torrent(self, channel_id, infohash):
        return True if self.get_channel_torrent_id(channel_id, infohash) else False

    def has_torrents(self, channel_id, infohashes):
        return_ar = []
        torrent_id_results = self.torrent_db.get_torrent_ids(infohashes)

        for infohash in infohashes:
            if torrent_id_results[infohash] is None:
                return_ar.append(False)
            else:
                torrent_id = torrent_id_results[infohash]
                sql = "SELECT id FROM ChannelTorrents WHERE torrent_id = ? AND channel_id = ? AND dispersy_id <> -1"
                channeltorrent_id = self._db.fetchone(sql, (torrent_id, channel_id))
                return_ar.append(True if channeltorrent_id else False)
        return return_ar

    def playlist_has_torrent(self, playlist_id, channeltorrent_id):
        sql = "SELECT id FROM PlaylistTorrents WHERE playlist_id = ? AND channeltorrent_id = ?"
        playlisttorrent_id = self._db.fetchone(sql, (playlist_id, channeltorrent_id))
        if playlisttorrent_id:
            return True
        return False

    # dispersy receiving comments
    def on_comment_from_dispersy(self, channel_id, dispersy_id, mid_global_time, peer_id, comment, timestamp,
                                 reply_to, reply_after, playlist_dispersy_id, infohash):
        # both reply_to and reply_after could be loose pointers to not yet received dispersy message
        if isinstance(reply_to, str):
            reply_to = buffer(reply_to)

        if isinstance(reply_after, str):
            reply_after = buffer(reply_after)
        mid_global_time = buffer(mid_global_time)

        sql = """INSERT OR REPLACE INTO _Comments
        (channel_id, dispersy_id, peer_id, comment, reply_to_id, reply_after_id, time_stamp)
        VALUES (?, ?, ?, ?, ?, ?, ?); SELECT last_insert_rowid();"""
        comment_id = self._db.fetchone(
            sql, (channel_id, dispersy_id, peer_id, comment, reply_to, reply_after, timestamp))

        if playlist_dispersy_id or infohash:
            if playlist_dispersy_id:
                sql = "SELECT id FROM Playlists WHERE dispersy_id = ?"
                playlist_id = self._db.fetchone(sql, (playlist_dispersy_id,))

                sql = "INSERT INTO CommentPlaylist (comment_id, playlist_id) VALUES (?, ?)"
                self._db.execute_write(sql, (comment_id, playlist_id))

            if infohash:
                channeltorrent_id = self.add_or_get_channel_torrent_id(channel_id, infohash)

                sql = "INSERT INTO CommentTorrent (comment_id, channeltorrent_id) VALUES (?, ?)"
                self._db.execute_write(sql, (comment_id, channeltorrent_id))

        # try fo fix loose reply_to and reply_after pointers
        sql = "UPDATE _Comments SET reply_to_id = ? WHERE reply_to_id = ?"
        self._db.execute_write(sql, (dispersy_id, mid_global_time))
        sql = "UPDATE _Comments SET reply_after_id = ? WHERE reply_after_id = ?"
        self._db.execute_write(sql, (dispersy_id, mid_global_time))

        self.notifier.notify(NTFY_COMMENTS, NTFY_INSERT, channel_id)
        if playlist_dispersy_id:
            self.notifier.notify(NTFY_COMMENTS, NTFY_INSERT, playlist_id)
        if infohash:
            self.notifier.notify(NTFY_COMMENTS, NTFY_INSERT, infohash)

    # dispersy removing comments
    def on_remove_comment_from_dispersy(self, channel_id, dispersy_id, infohash=None, redo=False):
        sql = "UPDATE _Comments SET deleted_at = ? WHERE dispersy_id = ?"

        if redo:
            deleted_at = None
            self._db.execute_write(sql, (deleted_at, dispersy_id))

            self.notifier.notify(NTFY_COMMENTS, NTFY_INSERT, channel_id)
            if infohash:
                self.notifier.notify(NTFY_COMMENTS, NTFY_INSERT, infohash)
        else:
            deleted_at = long(time())
            self._db.execute_write(sql, (deleted_at, dispersy_id))

            self.notifier.notify(NTFY_COMMENTS, NTFY_DELETE, channel_id)
            if infohash:
                self.notifier.notify(NTFY_COMMENTS, NTFY_DELETE, infohash)

    # dispersy receiving, modifying playlists
    def on_playlist_from_dispersy(self, channel_id, dispersy_id, peer_id, name, description):
        sql = "INSERT OR REPLACE INTO _Playlists (channel_id, dispersy_id,  peer_id, name, description) VALUES (?, ?, ?, ?, ?)"
        self._db.execute_write(sql, (channel_id, dispersy_id, peer_id, name, description))

        self.notifier.notify(NTFY_PLAYLISTS, NTFY_INSERT, channel_id)

    def on_remove_playlist_from_dispersy(self, channel_id, dispersy_id, redo):
        sql = "UPDATE _Playlists SET deleted_at = ? WHERE channel_id = ? and dispersy_id = ?"

        if redo:
            deleted_at = None
            self._db.execute_write(sql, (deleted_at, channel_id, dispersy_id))
            self.notifier.notify(NTFY_PLAYLISTS, NTFY_INSERT, channel_id)

        else:
            deleted_at = long(time())
            self._db.execute_write(sql, (deleted_at, channel_id, dispersy_id))
            self.notifier.notify(NTFY_PLAYLISTS, NTFY_DELETE, channel_id)

    def on_playlist_modification_from_dispersy(self, playlist_id, modification_type, modification_value):
        if modification_type in ['name', 'description']:
            update_playlist = "UPDATE _Playlists Set " + modification_type + " = ?, modified = ? WHERE id = ?"
            self._db.execute_write(update_playlist, (modification_value, long(time()), playlist_id))

            self.notifier.notify(NTFY_PLAYLISTS, NTFY_UPDATE, playlist_id)

    def on_playlist_torrent(self, dispersy_id, playlist_dispersy_id, peer_id, infohash):
        get_playlist = "SELECT id, channel_id FROM _Playlists WHERE dispersy_id = ?"
        playlist_id, channel_id = self._db.fetchone(get_playlist, (playlist_dispersy_id,))

        channeltorrent_id = self.add_or_get_channel_torrent_id(channel_id, infohash)
        sql = "INSERT INTO _PlaylistTorrents (dispersy_id, playlist_id, peer_id, channeltorrent_id) VALUES (?,?,?,?)"
        self._db.execute_write(sql, (dispersy_id, playlist_id, peer_id, channeltorrent_id))

        self.notifier.notify(NTFY_PLAYLISTS, NTFY_UPDATE, playlist_id, infohash)

    def on_remove_playlist_torrent(self, channel_id, playlist_dispersy_id, infohash, redo):
        get_playlist = "SELECT id FROM _Playlists WHERE dispersy_id = ? AND channel_id = ?"
        playlist_id = self._db.fetchone(get_playlist, (playlist_dispersy_id, channel_id))

        if playlist_id:
            get_channeltorent_id = """SELECT _ChannelTorrents.id FROM _ChannelTorrents, Torrent, _PlaylistTorrents
            WHERE _ChannelTorrents.torrent_id = Torrent.torrent_id AND _ChannelTorrents.id =
            _PlaylistTorrents.channeltorrent_id AND playlist_id = ? AND Torrent.infohash = ?"""
            channeltorrent_id = self._db.fetchone(get_channeltorent_id, (playlist_id, bin2str(infohash)))

            if channeltorrent_id:
                sql = "UPDATE _PlaylistTorrents SET deleted_at = ? WHERE playlist_id = ? AND channeltorrent_id = ?"

                if redo:
                    deleted_at = None
                else:
                    deleted_at = long(time())
                self._db.execute_write(sql, (deleted_at, playlist_id, channeltorrent_id))

            self.notifier.notify(NTFY_PLAYLISTS, NTFY_UPDATE, playlist_id)

    def on_metadata_from_dispersy(self, type, channeltorrent_id, playlist_id, channel_id, dispersy_id, peer_id,
                                  mid_global_time, modification_type, modification_value, timestamp,
                                  prev_modification_id, prev_modification_global_time):
        if isinstance(prev_modification_id, str):
            prev_modification_id = buffer(prev_modification_id)

        sql = """INSERT OR REPLACE INTO _ChannelMetaData
        (dispersy_id, channel_id, peer_id, type, value, time_stamp, prev_modification, prev_global_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?); SELECT last_insert_rowid();"""
        metadata_id = self._db.fetchone(sql, (dispersy_id, channel_id, peer_id,
                                              modification_type,
                                              modification_value, timestamp,
                                              prev_modification_id,
                                              prev_modification_global_time))

        if channeltorrent_id:
            sql = "INSERT INTO MetaDataTorrent (metadata_id, channeltorrent_id) VALUES (?,?)"
            self._db.execute_write(sql, (metadata_id, channeltorrent_id))

            self.notifier.notify(NTFY_MODIFICATIONS, NTFY_INSERT, channeltorrent_id)

        if playlist_id:
            sql = "INSERT INTO MetaDataPlaylist (metadata_id, playlist_id) VALUES (?,?)"
            self._db.execute_write(sql, (metadata_id, playlist_id))

            self.notifier.notify(NTFY_MODIFICATIONS, NTFY_INSERT, playlist_id)
        self.notifier.notify(NTFY_MODIFICATIONS, NTFY_INSERT, channel_id)

        # try fo fix loose reply_to and reply_after pointers
        sql = "UPDATE _ChannelMetaData SET prev_modification = ? WHERE prev_modification = ?;"
        self._db.execute_write(sql, (dispersy_id, buffer(mid_global_time)))

    def on_remove_metadata_from_dispersy(self, channel_id, dispersy_id, redo):
        sql = "UPDATE _ChannelMetaData SET deleted_at = ? WHERE dispersy_id = ? AND channel_id = ?"

        if redo:
            deleted_at = None
        else:
            deleted_at = long(time())
        self._db.execute_write(sql, (deleted_at, dispersy_id, channel_id))

    def on_moderation(self, channel_id, dispersy_id, peer_id, by_peer_id, cause, message, timestamp, severity):
        sql = """INSERT OR REPLACE INTO _Moderations
        (dispersy_id, channel_id, peer_id, by_peer_id, message, cause, time_stamp, severity)
        VALUES (?,?,?,?,?,?,?,?)"""
        self._db.execute_write(sql, (dispersy_id, channel_id, peer_id, by_peer_id, message, cause, timestamp, severity))

        self.notifier.notify(NTFY_MODERATIONS, NTFY_INSERT, channel_id)

    def on_remove_moderation(self, channel_id, dispersy_id, redo):
        sql = "UPDATE _Moderations SET deleted_at = ? WHERE dispersy_id = ? AND channel_id = ?"
        if redo:
            deleted_at = None
        else:
            deleted_at = long(time())
        self._db.execute_write(sql, (deleted_at, dispersy_id, channel_id))

    def on_mark_torrent(self, channel_id, dispersy_id, global_time, peer_id, infohash, type, timestamp):
        channeltorrent_id = self.add_or_get_channel_torrent_id(channel_id, infohash)

        if peer_id:
            select = "SELECT global_time FROM TorrentMarkings WHERE channeltorrent_id = ? AND peer_id = ?"
            prev_global_time = self._db.fetchone(select, (channeltorrent_id, peer_id))
        else:
            select = "SELECT global_time FROM TorrentMarkings WHERE channeltorrent_id = ? AND peer_id IS NULL"
            prev_global_time = self._db.fetchone(select, (channeltorrent_id,))

        if prev_global_time:
            if global_time > prev_global_time:
                if peer_id:
                    sql = "DELETE FROM _TorrentMarkings WHERE channeltorrent_id = ? AND peer_id = ?"
                    self._db.execute_write(sql, (channeltorrent_id, peer_id))
                else:
                    sql = "DELETE FROM _TorrentMarkings WHERE channeltorrent_id = ? AND peer_id IS NULL"
                    self._db.execute_write(sql, (channeltorrent_id,))
            else:
                return

        sql = """INSERT INTO _TorrentMarkings (dispersy_id, global_time, channeltorrent_id, peer_id, type, time_stamp)
        VALUES (?,?,?,?,?,?)"""
        self._db.execute_write(sql, (dispersy_id, global_time, channeltorrent_id, peer_id, type, timestamp))
        self.notifier.notify(NTFY_MARKINGS, NTFY_INSERT, channeltorrent_id)

    def on_remove_mark_torrent(self, channel_id, dispersy_id, redo):
        sql = "UPDATE _TorrentMarkings SET deleted_at = ? WHERE dispersy_id = ?"

        if redo:
            deleted_at = None
        else:
            deleted_at = long(time())
        self._db.execute_write(sql, (deleted_at, dispersy_id))

    def on_dynamic_settings(self, channel_id):
        self.notifier.notify(NTFY_CHANNELCAST, NTFY_STATE, channel_id)

    def get_nr_torrents_downloaded(self, channel_id):
        sql = """select count(*) from MyPreference, ChannelTorrents
        WHERE MyPreference.torrent_id = ChannelTorrents.torrent_id and ChannelTorrents.channel_id = ? LIMIT 1"""
        return self._db.fetchone(sql, (channel_id,))

    def get_channel_nr_torrents(self, limit=None):
        if limit:
            sql = """select count(torrent_id), channel_id from Channels, ChannelTorrents
            WHERE Channels.id = ChannelTorrents.channel_id AND dispersy_cid <> -1
            GROUP BY channel_id ORDER BY RANDOM() LIMIT ?"""
            return self._db.fetchall(sql, (limit,))

        sql = """SELECT count(torrent_id), channel_id FROM Channels, ChannelTorrents
        WHERE Channels.id = ChannelTorrents.channel_id AND dispersy_cid <>  -1 GROUP BY channel_id"""
        return self._db.fetchall(sql)

    def get_channel_nr_torrents_latest_update(self, limit=None):
        if limit:
            sql = """SELECT count(CollectedTorrent.torrent_id), max(ChannelTorrents.time_stamp),
            channel_id from Channels, ChannelTorrents, CollectedTorrent
            WHERE ChannelTorrents.torrent_id = CollectedTorrent.torrent_id
            AND Channels.id = ChannelTorrents.channel_id AND dispersy_cid == -1
            GROUP BY channel_id ORDER BY RANDOM() LIMIT ?"""
            return self._db.fetchall(sql, (limit,))

        sql = """SELECT count(CollectedTorrent.torrent_id), max(ChannelTorrents.time_stamp), channel_id from Channels,
        ChannelTorrents, CollectedTorrent
        WHERE ChannelTorrents.torrent_id = CollectedTorrent.torrent_id
        AND Channels.id = ChannelTorrents.channel_id AND dispersy_cid == -1 GROUP BY channel_id"""
        return self._db.fetchall(sql)

    def get_nr_channels(self):
        sql = "select count(DISTINCT id) from Channels LIMIT 1"
        return self._db.fetchone(sql)

    def get_recent_and_random_torrents(self, num_own_recent_torrents=15, num_own_random_torrents=10,
                                       num_others_recent_torrents=15, num_others_random_torrents=10,
                                       num_others_downloaded=5):
        torrent_dict = {}

        least_recent = -1
        sql = """SELECT dispersy_cid, infohash, time_stamp from ChannelTorrents, Channels, Torrent
        WHERE ChannelTorrents.torrent_id = Torrent.torrent_id AND Channels.id = ChannelTorrents.channel_id
        AND ChannelTorrents.channel_id==? and ChannelTorrents.dispersy_id <> -1 order by time_stamp desc limit ?"""
        myrecenttorrents = self._db.fetchall(sql, (self._channel_id, num_own_recent_torrents))
        for cid, infohash, timestamp in myrecenttorrents:
            torrent_dict.setdefault(str(cid), set()).add(str2bin(infohash))
            least_recent = timestamp

        if len(myrecenttorrents) == num_own_recent_torrents and least_recent != -1:
            sql = """SELECT dispersy_cid, infohash from ChannelTorrents, Channels, Torrent
            WHERE ChannelTorrents.torrent_id = Torrent.torrent_id AND Channels.id = ChannelTorrents.channel_id
            AND ChannelTorrents.channel_id==? AND time_stamp<?
            AND ChannelTorrents.dispersy_id <> -1 order by random() limit ?"""
            myrandomtorrents = self._db.fetchall(sql, (self._channel_id, least_recent, num_own_random_torrents))
            for cid, infohash, _ in myrecenttorrents:
                torrent_dict.setdefault(str(cid), set()).add(str2bin(infohash))

            for cid, infohash in myrandomtorrents:
                torrent_dict.setdefault(str(cid), set()).add(str2bin(infohash))

        nr_records = sum(len(torrents) for torrents in torrent_dict.values())
        additional_space = (num_own_recent_torrents + num_own_random_torrents) - nr_records

        if additional_space > 0:
            num_others_recent_torrents += additional_space / 2
            num_others_random_torrents += additional_space - (additional_space / 2)

            # Niels 6-12-2011: we should substract additionalspace from recent and
            # random, otherwise the totals will not be correct.
            num_own_recent_torrents -= additional_space / 2
            num_own_random_torrents -= additional_space - (additional_space / 2)

        least_recent = -1
        sql = """SELECT dispersy_cid, infohash, time_stamp from ChannelTorrents, Channels, Torrent
        WHERE ChannelTorrents.torrent_id = Torrent.torrent_id AND Channels.id = ChannelTorrents.channel_id
        AND ChannelTorrents.channel_id in (select channel_id from ChannelVotes
        WHERE voter_id ISNULL AND vote=2) and ChannelTorrents.dispersy_id <> -1 ORDER BY time_stamp desc limit ?"""
        othersrecenttorrents = self._db.fetchall(sql, (num_others_recent_torrents,))
        for cid, infohash, timestamp in othersrecenttorrents:
            torrent_dict.setdefault(str(cid), set()).add(str2bin(infohash))
            least_recent = timestamp

        if othersrecenttorrents and len(othersrecenttorrents) == num_others_recent_torrents and least_recent != -1:
            sql = """SELECT dispersy_cid, infohash FROM ChannelTorrents, Channels, Torrent
            WHERE ChannelTorrents.torrent_id = Torrent.torrent_id AND Channels.id = ChannelTorrents.channel_id
            AND ChannelTorrents.channel_id in (select channel_id from ChannelVotes
            WHERE voter_id ISNULL and vote=2) and time_stamp < ?
            AND ChannelTorrents.dispersy_id <> -1 order by random() limit ?"""
            othersrandomtorrents = self._db.fetchall(sql, (least_recent, num_others_random_torrents))
            for cid, infohash in othersrandomtorrents:
                torrent_dict.setdefault(str(cid), set()).add(str2bin(infohash))

        twomonthsago = long(time() - 5259487)
        nr_records = sum(len(torrents) for torrents in torrent_dict.values())
        additional_space = (num_own_recent_torrents + num_own_random_torrents +
                           num_others_recent_torrents + num_others_random_torrents) - nr_records
        num_others_downloaded += additional_space

        sql = """SELECT dispersy_cid, infohash from ChannelTorrents, Channels, Torrent
        WHERE ChannelTorrents.torrent_id = Torrent.torrent_id AND Channels.id = ChannelTorrents.channel_id
        AND ChannelTorrents.channel_id in (select distinct channel_id from ChannelTorrents
        WHERE torrent_id in (select torrent_id from MyPreference))
        AND ChannelTorrents.dispersy_id <> -1 and Channels.modified > ? order by time_stamp desc limit ?"""
        interesting_records = self._db.fetchall(sql, (twomonthsago, num_others_downloaded))
        for cid, infohash in interesting_records:
            torrent_dict.setdefault(str(cid), set()).add(str2bin(infohash))

        return torrent_dict

    def get_random_torrents(self, channel_id, limit=15):
        sql = """SELECT infohash FROM ChannelTorrents, Torrent WHERE ChannelTorrents.torrent_id = Torrent.torrent_id
        AND channel_id = ? ORDER BY RANDOM() LIMIT ?"""

        returnar = []
        for infohash, in self._db.fetchall(sql, (channel_id, limit)):
            returnar.append(str2bin(infohash))
        return returnar

    def get_torrent_from_channel_id(self, channel_id, infohash, keys):
        sql = "SELECT " + ", ".join(keys) + """ FROM Torrent, ChannelTorrents
              WHERE Torrent.torrent_id = ChannelTorrents.torrent_id AND channel_id = ? AND infohash = ?"""
        result = self._db.fetchone(sql, (channel_id, bin2str(infohash)))

        return ChannelCastDBHandler.__fix_torrent(keys, result)

    def get_channel_torrents(self, infohash, keys):
        sql = "SELECT " ", ".join(keys) + """ FROM Torrent, ChannelTorrents
              WHERE Torrent.torrent_id = ChannelTorrents.torrent_id AND infohash = ?"""
        results = self._db.fetchall(sql, (bin2str(infohash),))

        return ChannelCastDBHandler.__fix_torrents(keys, results)

    def get_random_channel_torrents(self, keys, limit=10):
        """
        Return some random (channel) torrents from the database.
        """
        sql = "SELECT %s FROM ChannelTorrents, Torrent " \
              "WHERE ChannelTorrents.torrent_id = Torrent.torrent_id AND Torrent.name IS NOT NULL " \
              "ORDER BY RANDOM() LIMIT ?" % ", ".join(keys)
        results = self._db.fetchall(sql, (limit,))
        return ChannelCastDBHandler.__fix_torrents(keys, results)

    def get_torrent_from_channel_torrent_id(self, channeltorrent_id, keys):
        sql = "SELECT " + ", ".join(keys) + """ FROM Torrent, ChannelTorrents
              WHERE Torrent.torrent_id = ChannelTorrents.torrent_id AND ChannelTorrents.id = ?"""
        result = self._db.fetchone(sql, (channeltorrent_id,))
        if not result:
            self._logger.info("COULD NOT FIND CHANNELTORRENT_ID %s", channeltorrent_id)
        else:
            return ChannelCastDBHandler.__fix_torrent(keys, result)

    def get_torrents_from_channel_id(self, channel_id, is_dispersy, keys, limit=None):
        if is_dispersy:
            sql = "SELECT " + ", ".join(keys) + """ FROM Torrent, ChannelTorrents
                  WHERE Torrent.torrent_id = ChannelTorrents.torrent_id"""
        else:
            sql = "SELECT " + ", ".join(keys) + """ FROM CollectedTorrent as Torrent, ChannelTorrents
                  WHERE Torrent.torrent_id = ChannelTorrents.torrent_id"""

        if channel_id:
            sql += " AND channel_id = ?"
        sql += " ORDER BY time_stamp DESC"

        if limit:
            sql += " LIMIT %d" % limit

        if channel_id:
            results = self._db.fetchall(sql, (channel_id,))
        else:
            results = self._db.fetchall(sql)

        if limit is None and channel_id:
            # use this possibility to update nrtorrent in channel

            if 'time_stamp' in keys and len(results) > 0:
                update = "UPDATE _Channels SET nr_torrents = ?, modified = ? WHERE id = ?"
                self._db.execute_write(update, (len(results), results[0][keys.index('time_stamp')], channel_id))
            else:
                # use this possibility to update nrtorrent in channel
                update = "UPDATE _Channels SET nr_torrents = ? WHERE id = ?"
                self._db.execute_write(update, (len(results), channel_id))

        return ChannelCastDBHandler.__fix_torrents(keys, results)

    def get_recent_received_torrents_from_channel_id(self, channel_id, keys, limit=None):
        sql = "SELECT " + ", ".join(keys) + " FROM Torrent, ChannelTorrents " + \
              "WHERE Torrent.torrent_id = ChannelTorrents.torrent_id AND channel_id = ? ORDER BY inserted DESC"
        if limit:
            sql += " LIMIT %d" % limit
        results = self._db.fetchall(sql, (channel_id,))
        return ChannelCastDBHandler.__fix_torrents(keys, results)

    def get_recent_modifications_from_channel_id(self, channel_id, keys, limit=None):
        sql = "SELECT " + ", ".join(keys) + """ FROM ChannelMetaData
              LEFT JOIN MetaDataTorrent ON ChannelMetaData.id = MetaDataTorrent.metadata_id
              LEFT JOIN Moderations ON Moderations.cause = ChannelMetaData.dispersy_id
              WHERE ChannelMetaData.channel_id = ?
              ORDER BY -Moderations.time_stamp ASC, ChannelMetaData.inserted DESC"""
        if limit:
            sql += " LIMIT %d" % limit
        return self._db.fetchall(sql, (channel_id,))

    def get_recent_moderations_from_channel(self, channel_id, keys, limit=None):
        sql = "SELECT " + ", ".join(keys) + """ FROM Moderations, MetaDataTorrent, ChannelMetaData
              WHERE Moderations.cause = ChannelMetaData.dispersy_id
              AND ChannelMetaData.id = MetaDataTorrent.metadata_id
              AND Moderations.channel_id = ?
              ORDER BY Moderations.inserted DESC"""
        if limit:
            sql += " LIMIT %d" % limit
        return self._db.fetchall(sql, (channel_id,))

    def get_recent_markings_from_channel(self, channel_id, keys, limit=None):
        sql = "SELECT " + ", ".join(keys) + """ FROM TorrentMarkings, ChannelTorrents
              WHERE TorrentMarkings.channeltorrent_id = ChannelTorrents.id
              AND ChannelTorrents.channel_id = ?
              ORDER BY TorrentMarkings.time_stamp DESC"""
        if limit:
            sql += " LIMIT %d" % limit
        return self._db.fetchall(sql, (channel_id,))

    def get_torrents_from_playlist(self, playlist_id, keys, limit=None):
        sql = "SELECT " + ", ".join(keys) + """ FROM Torrent, ChannelTorrents, PlaylistTorrents
              WHERE Torrent.torrent_id = ChannelTorrents.torrent_id
              AND ChannelTorrents.id = PlaylistTorrents.channeltorrent_id
              AND playlist_id = ? ORDER BY time_stamp DESC"""
        if limit:
            sql += " LIMIT %d" % limit
        results = self._db.fetchall(sql, (playlist_id,))
        return ChannelCastDBHandler.__fix_torrents(keys, results)

    def get_torrent_from_playlist(self, playlist_id, infohash, keys):
        sql = "SELECT " + ", ".join(keys) + """ FROM Torrent, ChannelTorrents, PlaylistTorrents
              WHERE Torrent.torrent_id = ChannelTorrents.torrent_id
              AND ChannelTorrents.id = PlaylistTorrents.channeltorrent_id
              AND playlist_id = ? AND infohash = ?"""
        result = self._db.fetchone(sql, (playlist_id, bin2str(infohash)))

        return ChannelCastDBHandler.__fix_torrent(keys, result)

    def get_recent_torrents_from_playlist(self, playlist_id, keys, limit=None):
        sql = "SELECT " + ", ".join(keys) + """ FROM Torrent, ChannelTorrents, PlaylistTorrents
              WHERE Torrent.torrent_id = ChannelTorrents.torrent_id
              AND ChannelTorrents.id = PlaylistTorrents.channeltorrent_id
              AND playlist_id = ? ORDER BY inserted DESC"""
        if limit:
            sql += " LIMIT %d" % limit
        results = self._db.fetchall(sql, (playlist_id,))
        return ChannelCastDBHandler.__fix_torrents(keys, results)

    def get_recent_modifications_from_playlist(self, playlist_id, keys, limit=None):
        playlist_keys = keys[:]
        if 'MetaDataTorrent.channeltorrent_id' in playlist_keys:
            playlist_keys[playlist_keys.index('MetaDataTorrent.channeltorrent_id')] = '""'

        sql = "SELECT " + ", ".join(playlist_keys) + """ FROM MetaDataPlaylist, ChannelMetaData
              LEFT JOIN Moderations ON Moderations.cause = ChannelMetaData.dispersy_id
              WHERE MetaDataPlaylist.metadata_id = ChannelMetaData.id AND playlist_id = ?"""
        if limit:
            sql += " LIMIT %d" % limit
        playlist_modifications = self._db.fetchall(sql, (playlist_id,))

        sql = "SELECT " + ", ".join(keys) + """ FROM MetaDataTorrent, ChannelMetaData, PlaylistTorrents
              LEFT JOIN Moderations ON Moderations.cause = ChannelMetaData.dispersy_id
              WHERE MetaDataTorrent.metadata_id = ChannelMetaData.id
              AND PlaylistTorrents.channeltorrent_id = MetaDataTorrent.channeltorrent_id AND playlist_id = ?"""
        if limit:
            sql += " LIMIT %d" % limit
        torrent_modifications = self._db.fetchall(sql, (playlist_id,))

        # merge two lists
        order_index = keys.index('ChannelMetaData.time_stamp')
        revert_index = keys.index('Moderations.time_stamp')
        data = [(row[revert_index], row[order_index], row) for row in playlist_modifications]
        data += [(row[revert_index], row[order_index], row) for row in torrent_modifications]
        data.sort(reverse=True)

        if limit:
            data = data[:limit]
        data = [item for _, _, item in data]
        return data

    def get_recent_moderations_from_playlist(self, playlist_id, keys, limit=None):
        sql = "SELECT " + ", ".join(keys) + """ FROM Moderations, MetaDataTorrent, ChannelMetaData, PlaylistTorrents
              WHERE Moderations.cause = ChannelMetaData.dispersy_id
              AND ChannelMetaData.id = MetaDataTorrent.metadata_id
              AND MetaDataTorrent.channeltorrent_id = PlaylistTorrents.channeltorrent_id
              AND PlaylistTorrents.playlist_id = ? ORDER BY Moderations.inserted DESC"""
        if limit:
            sql += " LIMIT %d" % limit
        return self._db.fetchall(sql, (playlist_id,))

    def get_recent_markings_from_playlist(self, playlist_id, keys, limit=None):
        sql = "SELECT " + ", ".join(keys) + """ FROM TorrentMarkings, PlaylistTorrents, ChannelTorrents
              WHERE TorrentMarkings.channeltorrent_id = PlaylistTorrents.channeltorrent_id
              AND ChannelTorrents.id = PlaylistTorrents.channeltorrent_id
              AND PlaylistTorrents.playlist_id = ?
              AND ChannelTorrents.dispersy_id <> -1 ORDER BY TorrentMarkings.time_stamp DESC"""
        if limit:
            sql += " LIMIT %d" % limit
        return self._db.fetchall(sql, (playlist_id,))

    def get_torrents_not_in_playlist(self, channel_id, keys):
        sql = "SELECT " + ", ".join(keys) + " FROM Torrent, ChannelTorrents " + \
              "WHERE Torrent.torrent_id = ChannelTorrents.torrent_id " + \
              "AND channel_id = ? " + \
              "And ChannelTorrents.id NOT IN (Select channeltorrent_id From PlaylistTorrents) " + \
              "ORDER BY time_stamp DESC"
        results = self._db.fetchall(sql, (channel_id,))
        return ChannelCastDBHandler.__fix_torrents(keys, results)

    def get_playlist_for_torrent(self, channeltorrent_id, keys):
        sql = "SELECT " + ", ".join(keys) + \
              ", count(DISTINCT channeltorrent_id) FROM Playlists, PlaylistTorrents " + \
              "WHERE Playlists.id = PlaylistTorrents.playlist_id AND channeltorrent_id = ?"
        result = self._db.fetchone(sql, (channeltorrent_id,))
        # Niels: 29-02-2012 due to the count this always returns one row, check
        # count to return None if playlist was actually not found.
        if result[-1]:
            return result

    def get_playlists_for_torrents(self, torrent_ids, keys):
        torrent_ids = " ,".join(map(str, torrent_ids))

        sql = "SELECT channeltorrent_id, " + ", ".join(keys) + \
              ", count(DISTINCT channeltorrent_id) FROM Playlists, PlaylistTorrents " + \
              "WHERE Playlists.id = PlaylistTorrents.playlist_id AND channeltorrent_id IN (" + \
            torrent_ids + ") GROUP BY Playlists.id"
        return self._db.fetchall(sql)

    @staticmethod
    def __fix_torrent(keys, torrent):
        if len(keys) == 1:
            if keys[0] == 'infohash':
                return str2bin(torrent)
            return torrent

        def fix_value(key, torrent):
            if key in keys:
                key_index = keys.index(key)
                if torrent[key_index]:
                    torrent[key_index] = str2bin(torrent[key_index])
        if torrent:
            torrent = list(torrent)
            fix_value('infohash', torrent)
        return torrent

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

    def get_playlists_from_channel_id(self, channel_id, keys):
        sql = "SELECT " + ", ".join(keys) + \
              ", count(DISTINCT ChannelTorrents.id) FROM Playlists " + \
              "LEFT JOIN PlaylistTorrents ON Playlists.id = PlaylistTorrents.playlist_id " + \
              "LEFT JOIN ChannelTorrents ON PlaylistTorrents.channeltorrent_id = ChannelTorrents.id " + \
              "WHERE Playlists.channel_id = ? GROUP BY Playlists.id ORDER BY Playlists.name DESC"
        return self._db.fetchall(sql, (channel_id,))

    def get_playlist(self, playlist_id, keys):
        sql = "SELECT " + ", ".join(keys) + \
              ", count(DISTINCT ChannelTorrents.id) FROM Playlists " + \
              "LEFT JOIN PlaylistTorrents ON Playlists.id = PlaylistTorrents.playlist_id " + \
              "LEFT JOIN ChannelTorrents ON PlaylistTorrents.channeltorrent_id = ChannelTorrents.id " + \
              "WHERE Playlists.id = ? GROUP BY Playlists.id"
        return self._db.fetchone(sql, (playlist_id,))

    def get_comments_from_channel_id(self, channel_id, keys, limit=None):
        sql = "SELECT " + ", ".join(keys) + " FROM Comments " + \
              "LEFT JOIN Peer ON Comments.peer_id = Peer.peer_id " + \
              "LEFT JOIN CommentPlaylist ON Comments.id = CommentPlaylist.comment_id " + \
              "LEFT JOIN CommentTorrent ON Comments.id = CommentTorrent.comment_id " + \
              "WHERE channel_id = ? ORDER BY time_stamp DESC"
        if limit:
            sql += " LIMIT %d" % limit
        return self._db.fetchall(sql, (channel_id,))

    def get_comments_from_playlist_id(self, playlist_id, keys, limit=None):
        playlist_keys = keys[:]
        if 'CommentTorrent.channeltorrent_id' in playlist_keys:
            playlist_keys[playlist_keys.index('CommentTorrent.channeltorrent_id')] = '""'

        sql = "SELECT " + ", ".join(playlist_keys) + " FROM Comments " + \
              "LEFT JOIN Peer ON Comments.peer_id = Peer.peer_id " + \
              "LEFT JOIN CommentPlaylist ON Comments.id = CommentPlaylist.comment_id WHERE playlist_id = ?"
        if limit:
            sql += " LIMIT %d" % limit

        playlist_comments = self._db.fetchall(sql, (playlist_id,))

        sql = "SELECT " + ", ".join(keys) + " FROM Comments, CommentTorrent, PlaylistTorrents " + \
              "LEFT JOIN Peer ON Comments.peer_id = Peer.peer_id " + \
              "WHERE Comments.id = CommentTorrent.comment_id " + \
              "AND PlaylistTorrents.channeltorrent_id = CommentTorrent.channeltorrent_id AND playlist_id = ?"
        if limit:
            sql += " LIMIT %d" % limit

        torrent_comments = self._db.fetchall(sql, (playlist_id,))

        # merge two lists
        order_index = keys.index('time_stamp')
        data = [(row[order_index], row) for row in playlist_comments]
        data += [(row[order_index], row) for row in torrent_comments]
        data.sort(reverse=True)

        if limit:
            data = data[:limit]
        data = [item for _, item in data]
        return data

    def get_comments_from_channel_torrent_id(self, channeltorrent_id, keys, limit=None):
        sql = "SELECT " + ", ".join(keys) + " FROM Comments, CommentTorrent " + \
              "LEFT JOIN Peer ON Comments.peer_id = Peer.peer_id WHERE Comments.id = CommentTorrent.comment_id " + \
              "AND channeltorrent_id = ? ORDER BY time_stamp DESC"
        if limit:
            sql += " LIMIT %d" % limit

        return self._db.fetchall(sql, (channeltorrent_id,))

    def search_channels_torrent(self, keywords, limit_channels=None, limit_torrents=None, dispersy_only=False):
        # search channels based on keywords
        keywords = split_into_keywords(keywords)
        keywords = [keyword for keyword in keywords if len(keyword) > 1]

        if len(keywords) > 0:
            sql = "SELECT distinct id, dispersy_cid, name FROM Channels WHERE"
            for keyword in keywords:
                sql += " name like '%" + keyword + "%' and"

            if dispersy_only:
                sql += " dispersy_cid != '-1'"
            else:
                sql = sql[:-3]

            if limit_channels:
                sql += " LIMIT %d" % limit_channels

            channels = self._db.fetchall(sql)
            select_torrents = "SELECT infohash, ChannelTorrents.name, Torrent.name, time_stamp " + \
                              "FROM Torrent, ChannelTorrents " + \
                              "WHERE Torrent.torrent_id = ChannelTorrents.torrent_id AND channel_id = ? " + \
                              "ORDER BY num_seeders DESC LIMIT ?"

            limit_torrents = limit_torrents or 20

            results = []
            for channel_id, dispersy_cid, name in channels:
                dispersy_cid = str(dispersy_cid)
                torrents = self._db.fetchall(select_torrents, (channel_id, limit_torrents))
                for infohash, chtname, cotname, time_stamp in torrents:
                    infohash = str2bin(infohash)
                    results.append((channel_id, dispersy_cid, name, infohash, chtname or cotname, time_stamp))
            return results
        return []

    def search_channels(self, keywords):
        sql = "SELECT id, name, description, dispersy_cid, modified, nr_torrents, nr_favorite, nr_spam " + \
              "FROM Channels WHERE"
        for keyword in keywords:
            sql += " name like '%" + keyword + "%' and"
        sql = sql[:-3]
        return self._get_channels(sql)

    def get_channel(self, channel_id):
        sql = "Select id, name, description, dispersy_cid, modified, nr_torrents, nr_favorite, nr_spam " + \
              "FROM Channels WHERE id = ?"
        channels = self._get_channels(sql, (channel_id,))
        if len(channels) > 0:
            return channels[0]

    def get_channels(self, channel_ids):
        channel_ids = "','".join(map(str, channel_ids))
        sql = "Select id, name, description, dispersy_cid, modified, " + \
              "nr_torrents, nr_favorite, nr_spam FROM Channels " + \
              "WHERE id IN ('" + \
            channel_ids + \
            "')"
        return self._get_channels(sql)

    def get_channels_by_cid(self, channel_cids):
        parameters = '?,' * len(channel_cids)
        parameters = parameters[:-1]

        channel_cids = map(buffer, channel_cids)
        sql = "Select id, name, description, dispersy_cid, modified, nr_torrents, nr_favorite, nr_spam " + \
              "FROM Channels WHERE dispersy_cid IN (" + \
            parameters + \
            ")"
        return self._get_channels(sql, channel_cids)

    def get_all_channels(self):
        """ Returns all the channels """
        sql = "Select id, name, description, dispersy_cid, modified, nr_torrents, nr_favorite, nr_spam FROM Channels"
        return self._get_channels(sql)

    def get_new_channels(self, updated_since=0):
        """ Returns all newest unsubscribed channels, ie the ones with no votes (positive or negative)"""
        sql = "Select id, name, description, dispersy_cid, modified, nr_torrents, nr_favorite, nr_spam " + \
              "FROM Channels WHERE nr_favorite = 0 AND nr_spam = 0 AND modified > ?"
        return self._get_channels(sql, (updated_since,))

    def get_latest_updated(self, max_nr=20):
        def channel_sort(a, b):
            # first compare local vote, spam -> return -1
            if a[7] == -1:
                return 1
            if b[7] == -1:
                return -1

            # then compare latest update
            if a[8] < b[8]:
                return 1
            if a[8] > b[8]:
                return -1
            # finally compare nr_torrents
            return cmp(a[4], b[4])

        sql = "Select id, name, description, dispersy_cid, modified, nr_torrents, nr_favorite, nr_spam " + \
              "FROM Channels Order By modified DESC Limit ?"
        return self._get_channels(sql, (max_nr,), cmp_f=channel_sort)

    def get_most_popular_channels(self, max_nr=20):
        sql = "Select id, name, description, dispersy_cid, modified, nr_torrents, nr_favorite, nr_spam " + \
              "FROM Channels ORDER BY nr_favorite DESC, modified DESC LIMIT ?"
        return self._get_channels(sql, (max_nr,), include_spam=False)

    def get_my_subscribed_channels(self, include_dispersy=False):
        sql = "SELECT id, name, description, dispersy_cid, modified, nr_torrents, nr_favorite, nr_spam " + \
              "FROM Channels, ChannelVotes " + \
              "WHERE Channels.id = ChannelVotes.channel_id AND voter_id ISNULL AND vote == 2"
        if not include_dispersy:
            sql += " AND dispersy_cid == -1"

        return self._get_channels(sql)

    def _get_channels(self, sql, args=None, cmp_f=None, include_spam=True):
        """Returns the channels based on the input sql, if the number of positive votes
        is less than maxvotes and the number of torrent > 0"""
        if self.votecast_db is None:
            return []

        channels = []
        results = self._db.fetchall(sql, args)

        my_votes = self.votecast_db.get_my_votes()
        for id, name, description, dispersy_cid, modified, nr_torrents, nr_favorites, nr_spam in results:
            my_vote = my_votes.get(id, 0)
            if not include_spam and my_vote < 0:
                continue
            if name.strip() == '':
                continue

            channels.append((id, str(dispersy_cid), name, description, nr_torrents,
                            nr_favorites, nr_spam, my_vote, modified, id == self._channel_id))

        def channel_sort(a, b):
            # first compare local vote, spam -> return -1
            if a[7] == -1:
                return 1
            if b[7] == -1:
                return -1

            # then compare nr_favorites
            if a[5] < b[5]:
                return 1
            if a[5] > b[5]:
                return -1

            # then compare latest update
            if a[8] < b[8]:
                return 1
            if a[8] > b[8]:
                return -1

            # finally compare nr_torrents
            return cmp(a[4], b[4])

        if cmp_f is None:
            cmp_f = channel_sort
        channels.sort(cmp_f)
        return channels

    def get_my_channel_id(self):
        if self._channel_id:
            return self._channel_id
        return self._db.fetchone('SELECT id FROM Channels WHERE peer_id ISNULL LIMIT 1')

    def get_torrent_markings(self, channeltorrent_id):
        counts = {}
        sql = "SELECT type, peer_id FROM TorrentMarkings WHERE channeltorrent_id = ?"
        for type, peer_id in self._db.fetchall(sql, (channeltorrent_id,)):
            if type not in counts:
                counts[type] = [type, 0, False]
            counts[type][1] += 1
            if not peer_id:
                counts[type][2] = True
        return counts.values()

    def get_torrent_modifications(self, channeltorrent_id, keys):
        sql = "SELECT " + ", ".join(keys) + """ FROM MetaDataTorrent, ChannelMetaData
              LEFT JOIN Moderations ON Moderations.cause = ChannelMetaData.dispersy_id
              WHERE metadata_id = ChannelMetaData.id AND channeltorrent_id = ?
              ORDER BY -Moderations.time_stamp ASC, prev_global_time DESC"""
        return self._db.fetchall(sql, (channeltorrent_id,))

    def get_most_popular_channel_from_torrent(self, infohash):
        """Returns channel id, name, nrfavorites of most popular channel if any"""
        sql = """SELECT Channels.id, Channels.dispersy_cid, Channels.name, Channels.description,
              Channels.nr_torrents, Channels.nr_favorite, Channels.nr_spam, Channels.modified,
              ChannelTorrents.id
              FROM Channels, ChannelTorrents, Torrent
              WHERE Channels.id = ChannelTorrents.channel_id
              AND ChannelTorrents.torrent_id = Torrent.torrent_id AND infohash = ?"""
        channels = self._db.fetchall(sql, (bin2str(infohash),))

        if len(channels) > 0:
            channel_ids = set()
            for result in channels:
                channel_ids.add(result[0])

            my_votes = self.votecast_db.get_my_votes()

            best_channel = None
            for id, dispersy_cid, name, description, nr_torrents, nr_favorites, nr_spam, modified, channeltorrent_id in channels:
                channel = id, dispersy_cid, name, description, nr_torrents, nr_favorites, nr_spam, my_votes.get(
                    id, 0), modified, id == self._channel_id, channeltorrent_id

                # allways prefer mychannel
                if channel[-1]:
                    return channel

                if not best_channel or channel[5] > best_channel[5] or\
                        (channel[5] == best_channel[5] and channel[4] > best_channel[4]):
                    best_channel = channel
            return best_channel

    def get_torrent_ids_from_playlist(self, playlist_id):
        """
        Returns the torrent dispersy IDs from a specified playlist.
        """
        sql = "SELECT dispersy_id FROM PlaylistTorrents WHERE playlist_id = ?"
        return self._db.fetchall(sql, (playlist_id,))
