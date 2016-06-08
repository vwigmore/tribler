import json
from Tribler.Category.Category import Category
from Tribler.Core.Modules.restapi.channels.base_channels_endpoint import BaseChannelsEndpoint
from Tribler.Core.Modules.restapi.util import convert_db_channel_to_json
from Tribler.Core.simpledefs import ENABLE_FAMILY_FILTER


class ChannelsPopularEndpoint(BaseChannelsEndpoint):

    def render_GET(self, request):
        popular_channels = self.channel_db_handler.getMostPopularChannels(max_nr=20)
        results_json = []
        for channel in popular_channels:
            channel_json = convert_db_channel_to_json(channel)

            if ENABLE_FAMILY_FILTER and Category.getInstance().xxx_filter.isXXX(channel_json['name']):
                continue

            results_json.append(channel_json)

        return json.dumps({"channels": results_json})
