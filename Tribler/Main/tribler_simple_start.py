import time

from Tribler.Core.Utilities.twisted_thread import reactor

from Tribler.Core.Session import Session
from Tribler.Core.SessionConfig import SessionStartupConfig


def start_tribler():
    sscfg = SessionStartupConfig()
    session = Session(sscfg)
    session.prestart()
    session.start()
    print "Tribler started"

start_tribler()

while(True):
    time.sleep(1)
