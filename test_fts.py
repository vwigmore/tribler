from itertools import chain
import os
import time
from struct import unpack_from
from twisted.internet import reactor
from Tribler.Core.CacheDB.sqlitecachedb import SQLiteCacheDB
from Tribler.Core.Utilities.search_utils import split_into_keywords


db = SQLiteCacheDB("/Users/martijndevos/Documents/fts_test/tribler.sdb")


def create_vtable():
    db.execute("BEGIN TRANSACTION create_table;"
                "CREATE VIRTUAL TABLE FullTextIndexMultiple USING fts4(swarmname, filenames, fileextensions);"
                "COMMIT TRANSACTION create_table;")


def reindex_torrents():
    time_begin = time.time()
    results = db.fetchall("SELECT torrent_id, name FROM Torrent")
    for torrent_result in results:
        if torrent_result[1] is None:
            continue

        swarmname = split_into_keywords(torrent_result[1])
        files_results = db.fetchall("SELECT path FROM TorrentFiles WHERE torrent_id = ?", (torrent_result[0],))
        filenames = ""
        fileexts = ""
        for file_result in files_results:
            filename, ext = os.path.splitext(file_result[0])
            parts = split_into_keywords(filename)
            filenames += " ".join(parts) + " "
            fileexts += ext[1:] + " "

        db.execute_write(u"INSERT INTO FullTextIndexMultiple (rowid, swarmname, filenames, fileextensions) VALUES(?,?,?,?)", (torrent_result[0], " ".join(swarmname), filenames[:-1], fileexts[:-1]))

    print "Reindexing took %d sec" % (time.time() - time_begin)


def search_in_db(query):
    search_results_torrents = search_in_torrents_db(query)
    search_results_channels = search_in_channels_db(query)

    all_search_results = search_results_torrents + search_results_channels
    all_search_results.sort(cmp=cmp_scores)

    for result in all_search_results:
        print "[%s] %s - %f" % ('T' if result[2] == 'torrent' else 'C', result[0], result[1])

    print "Results: %d" % (len(search_results_torrents) + len(search_results_channels))


def cmp_scores(res1, res2):
    if res1[1] == res2[1]:
        return len(split_into_keywords(res1[0])) - len(split_into_keywords(res2[0]))
    elif res2[1] < res1[1]:
        return -1
    return 1


def search_in_channels_db(query):
    search_results = []
    keywords = split_into_keywords(query, to_filter_stopwords=True)
    sql = "SELECT name, description FROM Channels WHERE "
    for _ in xrange(len(keywords)):
        sql += " name LIKE ? OR description LIKE ? OR "
    sql = sql[:-4]

    bindings = list(chain.from_iterable(['%%%s%%' % keyword] * 2 for keyword in keywords))
    results = db.fetchall(sql, bindings)

    for result in results:
        scores = []

        for col_ind in xrange(2):
            score = 0
            for keyword in keywords:
                phrase_freq = result[col_ind].lower().count(keyword)

                rightSide = ((phrase_freq * (1.2 + 1)) / (phrase_freq + 1.2))
                score += rightSide

            scores.append(score)

        search_results.append((result[0], 0.8 * scores[0] + 0.2 * scores[1], 'channel'))

    search_results.sort(cmp=cmp_scores)
    return search_results[:1000]


def search_in_torrents_db(query):
    search_results = []

    results = db.fetchall("SELECT DISTINCT T.name, T.infohash, Matchinfo(FullTextIndexMultiple, 'pcnalx') FROM Torrent T, FullTextIndexMultiple LEFT OUTER JOIN _ChannelTorrents C ON T.torrent_id = C.torrent_id WHERE t.name IS NOT NULL AND t.torrent_id = FullTextIndexMultiple.rowid AND C.deleted_at IS NULL AND FullTextIndexMultiple MATCH ?", (" OR ".join(split_into_keywords(query, to_filter_stopwords=True)),))

    for result in results:
        matchinfo = result[2]
        num_phrases, num_cols, num_rows, avg_len_swarmname, avg_len_filename, avg_len_exts, len_swarmname, len_filename, len_exts = unpack_from('IIIIIIIII', matchinfo)

        unpack_str = 'I' * (3 * num_cols * num_phrases)
        matchinfo = unpack_from('I' * 9 + unpack_str, matchinfo)[9:]

        scores = []

        for col_ind in xrange(num_cols):
            score = 0
            for phrase_ind in xrange(num_phrases):

                phrase_freq = matchinfo[3 * (col_ind + phrase_ind * num_cols)]

                rightSide = ((phrase_freq * (1.2 + 1)) / (phrase_freq + 1.2))

                score += rightSide

            scores.append(score)

        search_results.append((result[0], 0.8 * scores[0] + 0.1 * scores[1] + 0.1 * scores[2], 'torrent'))

    search_results.sort(cmp=cmp_scores)
    return search_results[:1000]


def do_db_stuff():

    db.initialize()
    #create_vtable()
    #reindex_torrents()
    search_in_db("regression")
    db.close()

    reactor.stop()

reactor.callWhenRunning(do_db_stuff)
reactor.run()
