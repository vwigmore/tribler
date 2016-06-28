# -*- mode: python -*-

block_cipher = None


a = Analysis(['Tribler/Main/tribler.py'],
             pathex=['/Users/martijndevos/Documents/tribler_package'],
             binaries=None,
datas=[('Tribler/dispersy/libnacl/libnacl', 'libnacl'), ('Tribler/Main/vwxGUI/images', 'images')],
             hiddenimports=['csv'],
             hookspath=['.\\hooks\\'],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name='tribler',
          debug=False,
          strip=False,
          upx=True,
          console=False )
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               name='tribler')
app = BUNDLE(coll,
             name='tribler.app',
             icon=None,
             bundle_identifier=None)
