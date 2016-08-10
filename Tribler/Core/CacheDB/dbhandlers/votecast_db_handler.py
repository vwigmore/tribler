from twisted.internet.task import LoopingCall
from Tribler.Core.CacheDB.dbhandlers.basic_db_handler import BasicDBHandler, VOTECAST_FLUSH_DB_INTERVAL
from Tribler.Core.simpledefs import NTFY_CHANNELCAST, NTFY_VOTECAST, NTFY_UPDATE


class VoteCastDBHandler(BasicDBHandler):

    def __init__(self, session):
        super(VoteCastDBHandler, self).__init__(session, u"VoteCast")

        self.my_votes = None
        self.updatedChannels = set()

        self.channelcast_db = None

    def initialize(self, *args, **kwargs):
        self.channelcast_db = self.session.open_dbhandler(NTFY_CHANNELCAST)
        self.session.sqlite_db.register_task(u"flush to database",
                                             LoopingCall(self._flush_to_database))\
            .start(VOTECAST_FLUSH_DB_INTERVAL, now=False)

    def close(self):
        super(VoteCastDBHandler, self).close()
        self.channelcast_db = None

    def on_votes_from_dispersy(self, votes):
        insert_vote = "INSERT OR REPLACE INTO _ChannelVotes (channel_id, voter_id, dispersy_id, vote, time_stamp) VALUES (?,?,?,?,?)"
        self._db.executemany(insert_vote, votes)

        for channel_id, voter_id, _, vote, _ in votes:
            if voter_id is None:
                self.notifier.notify(NTFY_VOTECAST, NTFY_UPDATE, channel_id, voter_id is None)
                if self.my_votes is not None:
                    self.my_votes[channel_id] = vote
            self.updatedChannels.add(channel_id)

    def on_remove_votes_from_dispersy(self, votes, contains_my_vote):
        remove_vote = "UPDATE _ChannelVotes SET deleted_at = ? WHERE channel_id = ? AND dispersy_id = ?"
        self._db.executemany(remove_vote, votes)

        if contains_my_vote:
            for _, channel_id, _ in votes:
                self.notifier.notify(NTFY_VOTECAST, NTFY_UPDATE, channel_id, contains_my_vote)

        for _, channel_id, _ in votes:
            self.updatedChannels.add(channel_id)

    def _flush_to_database(self):
        channel_ids = list(self.updatedChannels)
        self.updatedChannels.clear()

        if channel_ids:
            parameters = ",".join("?" * len(channel_ids))
            sql = "Select channel_id, vote FROM ChannelVotes WHERE channel_id in (" + parameters + ")"
            positive_votes = {}
            negative_votes = {}
            for channel_id, vote in self._db.fetchall(sql, channel_ids):
                if vote == 2:
                    positive_votes[channel_id] = positive_votes.get(channel_id, 0) + 1
                elif vote == -1:
                    negative_votes[channel_id] = negative_votes.get(channel_id, 0) + 1

            updates = [(positive_votes.get(channel_id, 0), negative_votes.get(channel_id, 0), channel_id)
                       for channel_id in channel_ids]
            self._db.executemany("UPDATE OR IGNORE _Channels SET nr_favorite = ?, nr_spam = ? WHERE id = ?", updates)

            for channel_id in channel_ids:
                self.notifier.notify(NTFY_VOTECAST, NTFY_UPDATE, channel_id)

    def get_latest_vote_dispersy_id(self, channel_id, voter_id):
        if voter_id:
            select_vote = """SELECT dispersy_id FROM ChannelVotes
            WHERE channel_id = ? AND voter_id = ? AND dispersy_id != -1
            ORDER BY time_stamp DESC Limit 1"""
            return self._db.fetchone(select_vote, (channel_id, voter_id))

        select_vote = """SELECT dispersy_id FROM ChannelVotes
        WHERE channel_id = ? AND voter_id ISNULL AND dispersy_id != -1
        ORDER BY time_stamp DESC Limit 1"""
        return self._db.fetchone(select_vote, (channel_id,))

    def get_pos_neg_votes(self, channel_id):
        sql = 'select nr_favorite, nr_spam from Channels where id = ?'
        result = self._db.fetchone(sql, (channel_id,))
        if result:
            return result
        return 0, 0

    def get_vote_on_channel(self, channel_id, voter_id):
        """ return the vote status if such record exists, otherwise None  """
        if voter_id:
            sql = "select vote from ChannelVotes where channel_id = ? and voter_id = ?"
            return self._db.fetchone(sql, (channel_id, voter_id))
        sql = "select vote from ChannelVotes where channel_id = ? and voter_id ISNULL"
        return self._db.fetchone(sql, (channel_id,))

    def get_vote_for_my_channel(self, voter_id):
        return self.get_vote_on_channel(self.channelcast_db._channel_id, voter_id)

    def get_dispersy_id(self, channel_id, voter_id):
        """ return the dispersy_id for this vote """
        if voter_id:
            sql = "select dispersy_id from ChannelVotes where channel_id = ? and voter_id = ?"
            return self._db.fetchone(sql, (channel_id, voter_id))
        sql = "select dispersy_id from ChannelVotes where channel_id = ? and voter_id ISNULL"
        return self._db.fetchone(sql, (channel_id,))

    def get_timestamp(self, channel_id, voter_id):
        """ return the timestamp for this vote """
        if voter_id:
            sql = "select time_stamp from ChannelVotes where channel_id = ? and voter_id = ?"
            return self._db.fetchone(sql, (channel_id, voter_id))
        sql = "select time_stamp from ChannelVotes where channel_id = ? and voter_id ISNULL"
        return self._db.fetchone(sql, (channel_id,))

    def get_my_votes(self):
        if not self.my_votes:
            sql = "SELECT channel_id, vote FROM ChannelVotes WHERE voter_id ISNULL"

            self.my_votes = {}
            for channel_id, vote in self._db.fetchall(sql):
                self.my_votes[channel_id] = vote
        return self.my_votes
