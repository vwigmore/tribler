import json
from random import shuffle

from twisted.web import resource
from Tribler.Core.simpledefs import NTFY_TORRENTS, NTFY_CHANNELCAST


class TorrentsEndpoint(resource.Resource):

    def __init__(self, session):
        resource.Resource.__init__(self)

        child_handler_dict = {"random": TorrentsRandomEndpoint}

        for path, child_cls in child_handler_dict.iteritems():
            self.putChild(path, child_cls(session))


class TorrentsRandomEndpoint(resource.Resource):

    def __init__(self, session):
        resource.Resource.__init__(self)
        self.session = session
        self.channel_db_handler = self.session.open_dbhandler(NTFY_CHANNELCAST)
        self.torrents_db_handler = self.session.open_dbhandler(NTFY_TORRENTS)

    def render_GET(self, request):
        result_torrents_list = []
        popular_torrents = self.channel_db_handler.getRecentAndRandomTorrents()
        for _, infohashes in popular_torrents.iteritems():
            for infohash in infohashes:
                torrent = self.torrents_db_handler.getTorrent(infohash)

                if not torrent["name"]:
                    continue

                # We should fix the dictionary a bit here
                torrent['infohash'] = torrent['infohash'].encode('hex')
                torrent['id'] = torrent.pop('C.torrent_id')
                torrent['size'] = torrent.pop('length')
                torrent['num_seeders'] = 0 if not torrent['num_seeders'] else torrent['num_seeders']
                torrent['num_leechers'] = 0 if not torrent['num_leechers'] else torrent['num_leechers']
                torrent['added'] = torrent.pop('insert_time')

                result_torrents_list.append(torrent)

        shuffle(result_torrents_list)
        return json.dumps({"torrents": result_torrents_list})
