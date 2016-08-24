from Tribler.community.tunnel.hidden_community import HiddenTunnelCommunity


class WebCommunity(HiddenTunnelCommunity):

    @classmethod
    def get_master_members(cls, dispersy):
        master_key = "3081a7301006072a8648ce3d020106052b81040027038192000400a2bf0a058e1c7149635af7377c2db206ae4061841117be52bec79abd93c7e7a04d31e2a8f91b6695ea5b425850deee47373cf4558147dabf440dd348338ee640910f89c7d3cd9e01e3d9a1305023709b2dd062ace94f10fe601b118d0e3921fea20ed67167ad2bb6fe5a24b5023fc9ad19c8c5ec012fd2711dc5b0138a1a897453d172a41de276a24af8742b3927a0"
        master_key_hex = master_key.decode("HEX")
        master = dispersy.get_member(public_key=master_key_hex)
        return [master]
