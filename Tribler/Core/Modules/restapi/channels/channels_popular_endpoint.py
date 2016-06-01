import json
from Tribler.Core.Modules.restapi.channels.base_channels_endpoint import BaseChannelsEndpoint
from Tribler.Core.Modules.restapi.util import convert_db_channel_to_json


class ChannelsPopularEndpoint(BaseChannelsEndpoint):

    def render_GET(self, request):
        popular_channels = self.channel_db_handler.getMostPopularChannels(max_nr=10)
        results_json = [convert_db_channel_to_json(channel) for channel in popular_channels]
        return json.dumps({"channels": results_json})
