from Tribler.Core.CacheDB.dbhandlers.basic_db_handler import BasicDBHandler, LimitedOrderedDict, DEFAULT_ID_CACHE_SIZE
from Tribler.Core.CacheDB.sqlitecachedb import bin2str, str2bin
from Tribler.Core.Utilities.unicode import dunno2unicode


class PeerDBHandler(BasicDBHandler):

    def __init__(self, session):
        super(PeerDBHandler, self).__init__(session, u"Peer")

        self.permid_id = LimitedOrderedDict(DEFAULT_ID_CACHE_SIZE)

    def get_peer_id(self, permid):
        return self.get_peer_ids([permid, ])[0]

    def get_peer_ids(self, permids):
        to_select = []

        for permid in permids:
            assert isinstance(permid, str), permid

            if permid not in self.permid_id:
                to_select.append(bin2str(permid))

        if len(to_select) > 0:
            parameters = u", ".join(u'?' * len(to_select))
            sql_get_peer_ids = u"SELECT peer_id, permid FROM Peer WHERE permid IN (%s)" % parameters
            peerids = self._db.fetchall(sql_get_peer_ids, to_select)
            for peer_id, permid in peerids:
                self.permid_id[str2bin(permid)] = peer_id

        to_return = []
        for permid in permids:
            if permid in self.permid_id:
                to_return.append(self.permid_id[permid])
            else:
                to_return.append(None)
        return to_return

    def add_or_get_peer_id(self, permid):
        peer_id = self.get_peer_id(permid)
        if peer_id is None:
            self.add_peer(permid, {})
            peer_id = self.get_peer_id(permid)

        return peer_id

    def get_peer(self, permid, keys=None):
        if keys is not None:
            res = self.get_one(keys, permid=bin2str(permid))
            return res
        else:
            # return a dictionary
            # make it compatible for calls to old bsddb interface
            value_name = (u'peer_id', u'permid', u'name')

            item = self.get_one(value_name, permid=bin2str(permid))
            if not item:
                return None
            peer = dict(zip(value_name, item))
            peer['permid'] = str2bin(peer['permid'])
            return peer

    def get_peer_by_id(self, peer_id, keys=None):
        if keys is not None:
            res = self.get_one(keys, peer_id=peer_id)
            return res
        else:
            # return a dictionary
            # make it compatible for calls to old bsddb interface
            value_name = (u'peer_id', u'permid', u'name')

            item = self.get_one(value_name, peer_id=peer_id)
            if not item:
                return None
            peer = dict(zip(value_name, item))
            peer['permid'] = str2bin(peer['permid'])
            return peer

    def add_peer(self, permid, value):
        # add or update a peer
        # ARNO: AAARGGH a method that silently changes the passed value param!!!
        # Jie: deepcopy(value)?

        _permid = None
        if 'permid' in value:
            _permid = value.pop('permid')

        peer_id = self.get_peer_id(permid)
        if 'name' in value:
            value['name'] = dunno2unicode(value['name'])
        if peer_id is not None:
            where = u'peer_id == %d' % peer_id
            self._db.update('Peer', where, **value)
        else:
            self._db.insert_or_ignore('Peer', permid=bin2str(permid), **value)

        if _permid is not None:
            value['permid'] = permid

    def has_peer(self, permid, check_db=False):
        if not check_db:
            return bool(self.get_peer_id(permid))
        else:
            permid_str = bin2str(permid)
            sql_get_peer_id = u"SELECT peer_id FROM Peer WHERE permid == ?"
            peer_id = self._db.fetchone(sql_get_peer_id, (permid_str,))
            if peer_id is None:
                return False
            else:
                return True

    def delete_peer(self, permid=None, peer_id=None):
        # don't delete friend of superpeers, except that force is True
        if peer_id is None:
            peer_id = self.get_peer_id(permid)
        if peer_id is None:
            return

        self._db.delete(u"Peer", peer_id=peer_id)
        deleted = not self.has_peer(permid, check_db=True)
        if deleted and permid in self.permid_id:
            self.permid_id.pop(permid)
