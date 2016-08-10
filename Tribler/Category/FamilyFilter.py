# Written by Jelle Roozenburg
# see LICENSE.txt for license information

import re
import os
import logging

from Tribler import LIBRARYNAME

WORDS_REGEXP = re.compile('[a-zA-Z0-9]+')


class XXXFilter(object):

    def __init__(self, install_dir):
        super(XXXFilter, self).__init__()
        self._logger = logging.getLogger(self.__class__.__name__)

        termfilename = os.path.join(install_dir, LIBRARYNAME, 'Category', 'filter_terms.filter')
        self.xxx_terms, self.xxx_searchterms = self.init_terms(termfilename)

    def init_terms(self, filename):
        terms = set()
        searchterms = set()

        try:
            f = file(filename, 'r')
            lines = f.read().lower().splitlines()

            for line in lines:
                if line.startswith('*'):
                    searchterms.add(line[1:])
                else:
                    terms.add(line)
            f.close()
        except IOError:
            self._logger.exception(u"Could not open %s, initTerms failed.", filename)

        self._logger.debug('Read %d XXX terms from file %s', len(terms) + len(searchterms), filename)
        return terms, searchterms

    def is_xxx_torrent(self, files_list, torrent_name, tracker, comment=None):
        if tracker:
            tracker = tracker.lower().replace('http://', '').replace('announce', '')
        else:
            tracker = ''
        terms = [a[0].lower() for a in files_list]
        is_xxx = (self.is_xxx(torrent_name, False) or
                  self.is_xxx(tracker, False) or
                  any(self.is_xxx(term) for term in terms) or
                  (comment and self.is_xxx(comment, False))
                  )
        tracker = repr(tracker)
        if is_xxx:
            self._logger.debug(u"Torrent is XXX: %s %s", torrent_name, tracker)
        else:
            self._logger.debug(u"Torrent is NOT XXX: %s %s", torrent_name, tracker)
        return is_xxx

    def is_xxx(self, s, is_filename=True):
        s = s.lower()
        if self.is_xxx_term(s):  # We have also put some full titles in the filter file
            return True
        if not self.is_audio(s) and self.found_xxx_term(s):
            return True
        words = [a.lower() for a in WORDS_REGEXP.findall(s)]
        words2 = [' '.join(words[i:i + 2]) for i in xrange(0, len(words) - 1)]
        num_xxx = len([w for w in words + words2 if self.is_xxx_term(w, s)])
        if is_filename and self.is_audio(s):
            return num_xxx > 2  # almost never classify mp3 as porn
        else:
            return num_xxx > 0

    def found_xxx_term(self, s):
        for term in self.xxx_searchterms:
            if term in s:
                self._logger.debug('XXXFilter: Found term "%s" in %s', term, s)
                return True
        return False

    def is_xxx_term(self, s, title=None):
        # check if term-(e)s is in xxx-terms
        s = s.lower()
        if s in self.xxx_terms:
            self._logger.debug('XXXFilter: "%s" is dirty%s', s, title and ' in %s' % title or '')
            return True
        if s.endswith('es') and s[:-2] in self.xxx_terms:
            self._logger.debug('XXXFilter: "%s" is dirty%s', s[:-2], title and ' in %s' % title or '')
            return True
        elif (s.endswith('s') or s.endswith('n')) and s[:-1] in self.xxx_terms:
            self._logger.debug('XXXFilter: "%s" is dirty%s', s[:-1], title and ' in %s' % title or '')
            return True

        return False

    audio_extensions = ['cda', 'flac', 'm3u', 'mp2', 'mp3', 'md5', 'vorbis', 'wav', 'wma', 'ogg']

    def is_audio(self, s):
        return s[s.rfind('.') + 1:] in self.audio_extensions
