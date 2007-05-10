import os
import sys
from traceback import print_exc
from base64 import encodestring
from Tribler.utilities import friendly_time, sort_dictlist, remove_torrent_from_list
from Tribler.unicode import str2unicode, dunno2unicode
from Utility.constants import * #IGNORE:W0611
from Tribler.Category.Category import Category
from Tribler.CacheDB.SynDBHandler import SynTorrentDBHandler
from Tribler.CacheDB.CacheDBHandler import OwnerDBHandler
from copy import deepcopy
from traceback import print_exc
from time import time
from bisect import insort

DEBUG = False

class TorrentDataManager:
    # Code to make this a singleton
    __single = None
   
    def __init__(self, utility):
        if TorrentDataManager.__single:
            raise RuntimeError, "TorrentDataManager is singleton"
        TorrentDataManager.__single = self
        self.done_init = False
        self.utility = utility
        self.rankList = []
        self.loadData()
        self.dict_FunList = {}
        self.done_init = True
        self.searchkeywords = []
        print 'torrentManager: ready init'
        
    def getInstance(*args, **kw):
        if TorrentDataManager.__single is None:
            TorrentDataManager(*args, **kw)       
        return TorrentDataManager.__single
    getInstance = staticmethod(getInstance)

    def loadData(self):
        self.torrent_db = SynTorrentDBHandler(updateFun=self.updateFun)
        self.owner_db = OwnerDBHandler()
        self.data = self.torrent_db.getRecommendedTorrents(light=False,all=True) #gets torrents with mypref
        self.category = Category.getInstance()
        updated = self.category.checkResort(self)        
        if updated:
            self.data = self.torrent_db.getRecommendedTorrents(light=False,all=True)
        self.prepareData()
        
    def prepareData(self):
        # initialize the cate_dict
        self.info_dict = {}    # reverse map
        
        for torrent in self.data:      
            # prepare to display
            torrent = self.prepareItem(torrent)
            self.info_dict[torrent["infohash"]] = torrent    

    def getDownloadHistCount(self):
        #[mluc]{26.04.2007} ATTENTION: data is not updated when a new download starts, although it should
        def isDownloadHistory(torrent):
            return torrent.has_key('myDownloadHistory')
        return len(filter(isDownloadHistory,self.data))
    
    def getRecommendFilesCount(self):
        count = 0
        for torrent in self.data:
            if torrent.has_key('relevance'):
                if torrent['relevance']> 5: #minmal value for a file to be considered tasteful
                    count = count + 1
        return count
        
    def getCategory(self, categorykey):
        if not self.done_init:
            return
        
        categorykey = categorykey.lower()
        def noDownloadHistory(torrent):
            return not torrent.has_key('myDownloadHistory')
        
        if categorykey == "all":
            return filter(noDownloadHistory, self.data)
        
        if categorykey == "search":
            return self.search()
        
        # See downloaded files also as category
        if (categorykey == self.utility.lang.get('mypref_list_title').lower()):
            def myfilter(a):
                return a.get('myDownloadHistory', False) and a.get('eventComingUp', '') != 'notDownloading'
            rlist = filter(myfilter, self.data) 
            print '>>>getCategory: returns mydlhistory: %s' % str([t['content_name'] for t in rlist])
            return rlist
        
        rlist = []
        
        for idata in self.data:
            if not idata:
                continue
            categories = idata.get("category", [])
            if not categories:
                categories = ["other"]
            if categorykey in [cat.lower() for cat in categories]:
                rlist.append(idata)
                
        return filter(noDownloadHistory, rlist)

    def getTorrents(self, hash_list):
        """builds a list with torrents that have the infohash in the list provided as an input parameter"""
        torrents_list = []
        for torrent_data in self.data:
            if torrent_data['infohash'] in hash_list:
                torrents_list.append(torrent_data)
        return torrents_list
            
    def getTorrent(self, infohash):
        return self.torrent_db.getTorrent(infohash)

    def deleteTorrent(self, infohash, delete_file=False):
        self.torrent_db.deleteTorrent(infohash, delete_file=False, updateFlag=True)

    # register update function
    def register(self, fun, key):
        print 'Registered for key: %s' % key
        try:
            key = key.lower()
            self.dict_FunList[key].index(fun)
            # if no exception, fun already exist!
            print "DBObserver register error. " + str(fun.__name__) + " already exist!"
            return
        except KeyError:
            self.dict_FunList[key] = []
            self.dict_FunList[key].append(fun)
        except ValueError:
            self.dict_FunList[key].append(fun)
        except Exception, msg:
            print "TorrentDataManager register error.", Exception, msg
            print_exc()
        
        
    def unregister(self, fun, key):
        print 'Unregistered for key: %s' % key
        try:
            key = key.lower()
            self.dict_FunList[key].remove(fun)
        except Exception, msg:
            print "TorrentDataManager unregister error.", Exception, msg
            print_exc()
        
    def updateFun(self, infohash, operate):
        if not self.done_init:    # don't call update func before init finished
            return
        if DEBUG:
            print "abcfileframe: torrentdatamanager updateFun called, param", operate
        if self.info_dict.has_key(infohash):
            if operate == 'add':
                self.addItem(infohash)
            elif operate == 'update':
                self.updateItem(infohash)
            elif operate == 'delete':
                self.deleteItem(infohash)
        else:
            if operate == 'update' or operate == 'delete':
                return
            else:
                self.addItem(infohash)
                
    def notifyView(self, torrent, operate):        
#        if torrent["category"] == ["?"]:
#            torrent["category"] = self.category.calculateCategory(torrent["info"], torrent["info"]['name'])
        
        if torrent.get('myDownloadHistory'):
            categories = [self.utility.lang.get('mypref_list_title')]
        else:
            categories = torrent.get('category', ['other']) + ["All"]
                                            
        for key in categories:
#            if key == '?':
#                continue
            try:
                key = key.lower()
                for fun in self.dict_FunList[key]: # call all functions for a certain key
                    fun(torrent, operate)     # lock is used to avoid dead lock
            except Exception, msg:
                #print >> sys.stderr, "abcfileframe: TorrentDataManager update error. Key: %s" % (key), Exception, msg
                #print_exc()
                pass
        
    def addItem(self, infohash):
        if self.info_dict.has_key(infohash):
            return
        torrent = self.torrent_db.getTorrent(infohash, num_owners=True)
        if not torrent:
            return
        torrent['infohash'] = infohash
        item = self.prepareItem(torrent)
        self.data.append(item)
        self.updateRankList(item, 'add')
        self.info_dict[infohash] = item
        self.notifyView(item, 'add')
    
    
    def setBelongsToMyDowloadHistory(self, infohash, b):
        """Set a certain new torrent to be in the download history or not"
        Should not be changed by updateTorrent calls"""
        old_torrent = self.info_dict.get(infohash, None)
        if not old_torrent:
            return
        
        # EventComing up, to let the detailPanel update already
        if b:    # add to my pref
            old_torrent['eventComingUp'] = 'downloading'
        else:    # remove from my pref
            old_torrent['eventComingUp'] = 'notDownloading'
        
        self.notifyView(old_torrent, 'delete')
        
        del old_torrent['eventComingUp']
        if b:
            old_torrent['myDownloadHistory'] = True
        else:
            if old_torrent.has_key('myDownloadHistory'):
                del old_torrent['myDownloadHistory']
            
        self.notifyView(old_torrent, 'add')
        
        if b:    # update buddycast after view was updated
            #self.utility.buddycast.addMyPref(infohash)    # will be called somewhere
            pass
        else:
            self.utility.buddycast.delMyPref(infohash)

                
    def addNewPreference(self, infohash): 
        if self.info_dict.has_key(infohash):
            return
        torrent = self.torrent_db.getTorrent(infohash, num_owners=True)
        if not torrent:
            return
        torrent['infohash'] = infohash
        item = self.prepareItem(torrent)
        torrent['myDownloadHistory'] = True
        self.data.append(item)
        self.info_dict[infohash] = item
        self.notifyView(item, 'add')
        
    def updateItem(self, infohash):
        old_torrent = self.info_dict.get(infohash, None)
        if not old_torrent:
            return
        torrent = self.torrent_db.getTorrent(infohash, num_owners=True)
        if not torrent:
            return
        torrent['infohash'] = infohash
        item = self.prepareItem(torrent)
        
        #old_torrent.update(item)
        for key in torrent.keys():    # modify reference
            old_torrent[key] = torrent[key]
    
        self.updateRankList(torrent, 'update')
        self.notifyView(old_torrent, 'update')
    
    def deleteItem(self, infohash):
        old_torrent = self.info_dict.get(infohash, None)
        if not old_torrent:
            return
        self.info_dict.pop(infohash)
        # Replaces remove() function because of unicode error
        #self.data.remove(old_torrent)
        remove_torrent_from_list(self.data, old_torrent)
        self.updateRankList(old_torrent, 'delete')
        self.notifyView(old_torrent, 'delete')

    def prepareItem(self, torrent):    # change self.data
        info = torrent['info']
        torrent['length'] = info.get('length', 0)
        torrent['content_name'] = dunno2unicode(info.get('name', '?'))
        if torrent['torrent_name'] == '':
            torrent['torrent_name'] = '?'
        torrent['num_files'] = int(info.get('num_files', 0))
        torrent['date'] = info.get('creation date', 0) 
        torrent['tracker'] = info.get('announce', '')
        torrent['leecher'] = torrent.get('leecher', -1)
        torrent['seeder'] = torrent.get('seeder', -1)
        torrent['swarmsize'] = torrent['seeder'] + torrent['leecher']
        
        self.updateRankList(torrent, 'add')
        # Thumbnail is read from file only when it is shown on screen by
        # thumbnailViewer or detailsPanel
        return torrent
         
    def updateRankList(self, torrent, operate):
        "Update the ranking list, so that it always shows the top20 most similar torrents"
        print 'UpdateRankList called for: %s' % torrent
        sim = torrent.get('relevance')
        good = torrent.get('status') == 'good' and not torrent.get('myDownloadHistory', False)
        infohash = torrent.get('infohash')
        updated = False
        
        if operate == 'add' and good:
            insort(self.rankList, (sim, infohash))
            
        
        elif operate == 'update':
            # Check if not already there
            for (s, infohashRanked) in self.rankList:
                if infohash == infohashRanked:
                    self.rankList.remove((s, infohashRanked))
                    self.recompleteRankList()
                    
            if not good:
                sim  = 0
            # Now insort the new item
            insort(self.rankList, (sim, infohash))
            
        elif operate == 'delete':
            for (s, infohashRanked) in self.rankList:
                if infohash == infohashRanked:
                    updated = True
                    self.rankList.remove((s, infohashRanked))
                    self.recompleteRankList()
                    break
                
                
        # Always leave rankList with <=20 items
        while len(self.rankList) > 20:
                self.rankList.pop(0)
        
        if updated or (sim, infohash) in self.rankList:
            # Only update the items when something changed in the ranking list
            self.updateRankedItems()
            print 'RankList is now: %s' % self.rankList
        
    def updateRankedItems(self):
        rank = 20
        for (sim, infohash) in self.rankList:
            if self.info_dict.has_key(infohash):
                torrent = self.info_dict[infohash]
                torrent['simRank'] = rank
                self.notifyView(torrent, 'update')
            else:
                print 'Not found infohash: %s in info_dict.' % repr(infohash)
            rank -= 1
            
    def recompleteRankList(self):
        """
        Get most similar item with status=good, not in library and not in ranklist 
        and insort it in ranklist
        """
        highest_sim = 0
        for torrent in self.data:
            sim = torrent.get('relevance')
            good = torrent.get('status') == 'good' and not torrent.get('myDownloadHistory', False)
            infohash = torrent.get('infohash')
            
            if sim > 0 and good and (sim, infohash) not in self.rankList:
                # item is not in rankList
                if sim > highest_sim:
                    highest_sim = sim
                    highest_infohash = infohash
                    
        insort(self.rankList, (highest_sim, highest_infohash))
        
    def getRank(self, torrent):
        infohash = torrent['infohash']
        rank = 20
        for (s, infohashRanked) in self.rankList:
                if infohash == infohashRanked:
                    return rank
                rank -= 1
        return -1
                    
    def setSearchKeywords(self,wantkeywords):
        self.searchkeywords = wantkeywords
         
    def search(self):
        print >>sys.stderr,"tdm: search: Want",self.searchkeywords
        hits = []
        if len(self.searchkeywords) == 0:
            return hits
        for torrent in self.data:
            if torrent.has_key('myDownloadHistory'):
                continue
            low = torrent['content_name'].lower()
            for wantkw in self.searchkeywords:
                # only search in alive torrents
                if low.find(wantkw) != -1 and torrent['status'] == 'good':
                    print "tdm: search: Got hit",`wantkw`,"found in",`torrent['content_name']`
                    hits.append(torrent)
        return hits

    def getFromSource(self,source):
        hits = []
        for torrent in self.data:
            if torrent['source'] == source:
                hits.append(torrent)
        return hits
    
    def getSimItems(self, infohash, num=15):
        return self.owner_db.getSimItems(infohash, num)
