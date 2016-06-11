"""
This file contains some utility methods that are used by the API.
"""
from struct import unpack_from
import math
from Tribler.Core.Modules.restapi import VOTE_SUBSCRIBE
from Tribler.Core.simpledefs import NTFY_TORRENTS


def convert_torrent_to_json(torrent):
    """
    Converts a given torrent to a JSON dictionary. Note that the torrent might be either a result from the local
    database in which case it is a tuple or a remote search result in which case it is a dictionary.
    """
    if isinstance(torrent, dict):
        return convert_remote_torrent_to_json(torrent)
    return convert_db_torrent_to_json(torrent)


def convert_db_channel_to_json(channel):
    """
    This method converts a channel in the database to a JSON dictionary.
    """
    relevance_score = 0.0
    if len(channel) >= 10:  # The relevance score is not always present
        relevance_score = channel[9]

    return {"id": channel[0], "dispersy_cid": channel[1].encode('hex'), "name": channel[2], "description": channel[3],
            "votes": channel[5], "torrents": channel[4], "spam": channel[6], "modified": channel[8],
            "subscribed": (channel[7] == VOTE_SUBSCRIBE), "relevance_score": relevance_score}


def convert_db_torrent_to_json(torrent):
    """
    This method converts a torrent in the database to a JSON dictionary.
    """
    torrent_name = torrent[2] if torrent[2] is not None else "Unnamed torrent"

    relevance_score = 0.0
    if len(torrent) >= 10: # The relevance score is not always present
        relevance_score = torrent[9]

    return {"id": torrent[0], "infohash": torrent[1].encode('hex'), "name": torrent_name, "size": torrent[3],
            "category": torrent[4], "num_seeders": torrent[5] or 0, "num_leechers": torrent[6] or 0,
            "last_tracker_check": torrent[7] or 0, 'relevance_score': relevance_score}


def convert_remote_torrent_to_json(torrent):
    """
    This method converts a torrent that has been received by remote peers in the network to a JSON dictionary.
    """
    torrent_name = torrent['name'] if torrent['name'] is not None else "Unnamed torrent"
    relevance_score = relevance_score_remote_torrent(torrent_name)

    return {'id': torrent['torrent_id'], "infohash": torrent['infohash'].encode('hex'), "name": torrent_name,
            'size': torrent['length'], 'category': torrent['category'], 'num_seeders': torrent['num_seeders'],
            'num_leechers': torrent['num_leechers'], 'last_tracker_check': 0,
            'relevance_score': relevance_score}


def relevance_score_remote_torrent(torrent_name):
    """
    Calculate the relevance score of a remote torrent, based on the name and the matchinfo object
    of the last torrent from the database.
    """
    from Tribler.Core.Session import Session
    torrent_db = Session.get_instance().open_dbhandler(NTFY_TORRENTS)
    matchinfo, keywords = torrent_db.latest_matchinfo_torrent

    num_phrases, num_cols, num_rows, avg_len_swarmname, avg_len_filename, avg_len_exts, len_swarmname, len_filename, len_exts = unpack_from('IIIIIIIII', matchinfo)
    unpack_str = 'I' * (3 * num_cols * num_phrases)
    matchinfo = unpack_from('I' * 9 + unpack_str, matchinfo)[9:]

    score = 0
    for phrase_ind in xrange(num_phrases):
        rows_with_term = matchinfo[3 * (phrase_ind * num_cols) + 2]
        phrase_freq = torrent_name.lower().count(keywords[phrase_ind])

        idf = math.log((num_rows - rows_with_term + 0.5) / (rows_with_term + 0.5), 2)
        right_side = ((phrase_freq * (1.2 + 1)) / (phrase_freq + 1.2))

        score += idf * right_side

    return score
