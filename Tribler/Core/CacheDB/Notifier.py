# Written by Jelle Roozenburg
# see LICENSE.txt for license information

import logging
import threading

from Tribler.Core.Utilities.twisted_utils import call_in_thread_pool
from Tribler.Core.simpledefs import (NTFY_TORRENTS, NTFY_PLAYLISTS, NTFY_COMMENTS,
                                     NTFY_MODIFICATIONS, NTFY_MODERATIONS, NTFY_MARKINGS, NTFY_MYPREFERENCES,
                                     NTFY_ACTIVITIES, NTFY_REACHABLE, NTFY_CHANNELCAST, NTFY_VOTECAST, NTFY_DISPERSY,
                                     NTFY_TRACKERINFO, NTFY_UPDATE, NTFY_INSERT, NTFY_DELETE, NTFY_TUNNEL,
                                     NTFY_STARTUP_TICK, NTFY_CLOSE_TICK,NTFY_UPGRADER,
                                     SIGNAL_ALLCHANNEL_COMMUNITY, SIGNAL_SEARCH_COMMUNITY, SIGNAL_TORRENT,
                                     SIGNAL_CHANNEL, SIGNAL_CHANNEL_COMMUNITY, SIGNAL_RSS_FEED,
                                     NTFY_WATCH_FOLDER_CORRUPT_TORRENT, NTFY_NEW_VERSION, NTFY_TRIBLER,
                                     NTFY_UPGRADER_TICK, NTFY_TORRENT, NTFY_CHANNEL)


class Notifier(object):

    SUBJECTS = [NTFY_TORRENTS, NTFY_PLAYLISTS, NTFY_COMMENTS, NTFY_MODIFICATIONS, NTFY_MODERATIONS, NTFY_MARKINGS,
                NTFY_MYPREFERENCES, NTFY_ACTIVITIES, NTFY_REACHABLE, NTFY_CHANNELCAST, NTFY_CLOSE_TICK, NTFY_DISPERSY,
                NTFY_STARTUP_TICK, NTFY_TRACKERINFO, NTFY_TUNNEL, NTFY_UPGRADER, NTFY_VOTECAST,
                SIGNAL_ALLCHANNEL_COMMUNITY, SIGNAL_CHANNEL, SIGNAL_CHANNEL_COMMUNITY, SIGNAL_RSS_FEED,
                SIGNAL_SEARCH_COMMUNITY, SIGNAL_TORRENT, NTFY_WATCH_FOLDER_CORRUPT_TORRENT, NTFY_NEW_VERSION,
                NTFY_TRIBLER, NTFY_UPGRADER_TICK, NTFY_TORRENT, NTFY_CHANNEL]

    def __init__(self, use_pool):
        self._logger = logging.getLogger(self.__class__.__name__)

        self.use_pool = use_pool

        self.observers = []
        self.observerscache = {}
        self.observertimers = {}
        self.observer_lock = threading.Lock()

    def add_observer(self, func, subject, change_types=[NTFY_UPDATE, NTFY_INSERT, NTFY_DELETE], id=None, cache=0):
        """
        Add observer function which will be called upon certain event
        Example:
        addObserver(NTFY_TORRENTS, [NTFY_INSERT,NTFY_DELETE]) -> get callbacks
                    when peers are added or deleted
        addObserver(NTFY_TORRENTS, [NTFY_SEARCH_RESULT], 'a_search_id') -> get
                    callbacks when peer-searchresults of of search
                    with id=='a_search_id' come in
        """
        assert isinstance(change_types, list)
        assert subject in self.SUBJECTS, 'Subject %s not in SUBJECTS' % subject

        obs = (func, subject, change_types, id, cache)
        self.observer_lock.acquire()
        self.observers.append(obs)
        self.observer_lock.release()

    def remove_observer(self, func):
        """ Remove all observers with function func
        """
        with self.observer_lock:
            i = 0
            while i < len(self.observers):
                ofunc = self.observers[i][0]
                if ofunc == func:
                    del self.observers[i]
                else:
                    i += 1

    def remove_observers(self):
        with self.observer_lock:
            for timer in self.observertimers.values():
                timer.cancel()
            self.observerscache = {}
            self.observertimers = {}
            self.observers = []

    def notify(self, subject, change_type, obj_id, *args):
        """
        Notify all interested observers about an event with threads from the pool
        """
        def do_queue(ofunc):
            self.observer_lock.acquire()
            if ofunc in self.observerscache:
                events = self.observerscache[ofunc]
                del self.observerscache[ofunc]
                del self.observertimers[ofunc]
            else:
                events = []
            self.observer_lock.release()

            if events:
                if self.use_pool:
                    call_in_thread_pool(ofunc, events)
                else:
                    ofunc(events)

        tasks = []
        assert subject in self.SUBJECTS, 'Subject %s not in SUBJECTS' % subject

        args = [subject, change_type, obj_id] + list(args)

        self.observer_lock.acquire()
        for ofunc, osubject, ochange_types, oid, cache in self.observers:
            try:
                if subject == osubject and change_type in ochange_types and (oid is None or oid == obj_id):
                    if not cache:
                        tasks.append(ofunc)
                        continue

                    if ofunc not in self.observerscache:
                        t = threading.Timer(cache, do_queue, (ofunc,))
                        t.setName("Notifier-timer-%s" % subject)
                        t.start()

                        self.observerscache[ofunc] = []
                        self.observertimers[ofunc] = t

                    self.observerscache[ofunc].append(args)
            except:
                self._logger.exception("OIDs were %s %s", repr(oid), repr(obj_id))

        self.observer_lock.release()
        for task in tasks:
            if self.use_pool:
                call_in_thread_pool(task, *args)
            else:
                task(*args)  # call observer function in this thread
