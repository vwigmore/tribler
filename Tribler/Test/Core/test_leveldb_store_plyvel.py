import sys
from Tribler.Core.leveldbstore import get_write_batch_plyvel
from Tribler.Test.Core.test_leveldb_store import ClockedAbstractLevelDBStore, AbstractTestLevelDBStore


# TODO Martijn: compile and enable Plyvel tests on Windows
if sys.platform != "win32":
    class TestPlyvelStore(AbstractTestLevelDBStore):

        __test__ = True

        class ClockedPlyvelStore(ClockedAbstractLevelDBStore):
            from Tribler.Core.plyveladapter import LevelDB
            _leveldb = LevelDB
            _writebatch = get_write_batch_plyvel

        _storetype = ClockedPlyvelStore
