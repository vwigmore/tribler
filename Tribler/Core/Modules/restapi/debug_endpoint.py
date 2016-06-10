import json
from twisted.web import resource
from Tribler.Core.simpledefs import NTFY_TORRENTS, NTFY_CHANNELCAST


class DebugEndpoint(resource.Resource):
    """
    This class is responsible for dispatching various requests to debug endpoints.
    """

    def __init__(self, session):
        resource.Resource.__init__(self)
        self.session = session

        child_handler_dict = {"communities": DebugCommunitiesEndpoint, "statistics": DebugStatisticsEndpoint,
                              "dispersy": DebugDispersyEndpoint}

        for path, child_cls in child_handler_dict.iteritems():
            self.putChild(path, child_cls(self.session))


class DebugCommunitiesEndpoint(resource.Resource):
    """
    A GET request to this endpoint will return statistics about the loaded communities in Tribler.

    Example response (partially since the full response it too large to display):
    {
        "communities": {
            "<ChannelCommunity>: b9754da88799ff2dc4042325bd8640d3a5685100": {
                "Sync bloom created": "8",
                "Statistics": {
                    "outgoing": {
                        "-caused by missing-proof-": "1",
                        "dispersy-puncture-request": "8",
                        ...
                    },
                "Sync bloom reused":"0",
                ...
            },
            ...
        }
    }
    """

    def __init__(self, session):
        resource.Resource.__init__(self)
        self.session = session

    def render_GET(self, request):
        return json.dumps(self.session.get_statistics())


class DebugStatisticsEndpoint(resource.Resource):

    def __init__(self, session):
        resource.Resource.__init__(self)
        self.session = session

    def render_GET(self, request):
        torrent_db_handler = self.session.open_dbhandler(NTFY_TORRENTS)
        channel_db_handler = self.session.open_dbhandler(NTFY_CHANNELCAST)

        torrent_stats = torrent_db_handler.getTorrentsStats()
        torrent_total_size = 0 if torrent_stats[1] is None else torrent_stats[1]
        torrent_queue_stats = self.session.lm.rtorrent_handler.get_queue_stats()
        torrent_queue_size_stats = self.session.lm.rtorrent_handler.get_queue_size_stats()
        torrent_queue_bandwidth_stats = self.session.lm.rtorrent_handler.get_bandwidth_stats()

        return json.dumps({"torrents": {"num_collected": torrent_stats[0], "total_size": torrent_total_size,
                                        "num_files": torrent_stats[2]},
                           "torrent_queue_stats": torrent_queue_stats,
                           "torrent_queue_size_stats": torrent_queue_size_stats,
                           "torrent_queue_bandwidth_stats": torrent_queue_bandwidth_stats,
                           "num_channels": channel_db_handler.getNrChannels()})


class DebugDispersyEndpoint(resource.Resource):

    def __init__(self, session):
        resource.Resource.__init__(self)
        self.session = session

    def render_GET(self, request):
        dispersy_stats = self.session.get_dispersy_instance().statistics
        dispersy_stats.update(database=True)

        return json.dumps({"summary": {"wan_address": "%s:%s" % dispersy_stats.wan_address,
                                       "lan_address": "%s:%s" % dispersy_stats.lan_address,
                                       "connection": unicode(dispersy_stats.connection_type),
                                       "runtime": (dispersy_stats.timestamp - dispersy_stats.start)}})
