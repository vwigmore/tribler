from twisted.internet import reactor
from twisted.internet.task import LoopingCall

from Tribler.dispersy.dispersy import Dispersy
from Tribler.dispersy.endpoint import StandaloneEndpoint
from Tribler.dispersy.payload import Payload


class PlebMessage(Payload):
    '''
    Send a text message. When a message is received, the text property is 
    available at message.payload.text

    The payload defines individual messages send across the network.
    More attributes can be added by adding parameters to the init function
    and more properties.
    '''

    class Implementation(Payload.Implementation):
        def __init__(self, meta, text):
            assert isinstance(text, str)
            super(PlebMessage.Implementation, self).__init__(meta)
            self._text = text

        @property
        def text(self):
            return self._text


from Tribler.Core.Utilities.encoding import encode, decode
from Tribler.dispersy.conversion import BinaryConversion
from Tribler.dispersy.message import DropPacket


class PlebConversion(BinaryConversion):
    '''
    A conversion is used to transform Message.Implementation instances to
    binary string representations transferred over the wire. It also allows 
    to convert between different versions of the community
    '''

    def __init__(self, community):
        super(PlebConversion, self).__init__(community, '\x01')
        self.define_meta_message(chr(1), community.get_meta_message(u'heymessage'), self._encode_message,
                                 self._decode_message)

    def _encode_message(self, message):
        packet = encode(message.payload.text)
        return packet,

    def _decode_message(self, placeholder, offset, data):
        try:
            offset, payload = decode(data, offset)
        except ValueError:
            raise DropPacket('Unable to decode the message payload')

        if not isinstance(payload, str):
            raise DropPacket('Invalid text payload type')

        text = payload

        return offset, placeholder.meta.payload.implement(text)


from Tribler.dispersy.authentication import MemberAuthentication
from Tribler.dispersy.community import Community
from Tribler.dispersy.conversion import DefaultConversion
from Tribler.dispersy.destination import CommunityDestination
from Tribler.dispersy.distribution import DirectDistribution
from Tribler.dispersy.message import Message, DelayMessageByProof
from Tribler.dispersy.resolution import PublicResolution


class PlebCommunity(Community):
    '''
    A community defines the overlay used for the communication used within the network
    '''

    @classmethod
    def get_master_members(cls, dispersy):
        master_key = '3081a7301006072a8648ce3d020106052b81040027038192000407ddea19755af82d6e144dd8a8c860980fbcb632ac00a580e37bfd75fc9412e02619dcea0690b69e5cdfddfadc107d711dbb5953c57feca8d932a85be579af22ceb65d4d517785700500e6a44b1c31519ab9d68669102456940d291367469ebc614f0d0c7587036513075337b8c6576ce091808094bb055e766a9fa502db29d94f5cf20688c6aa1ceb5abb00bebb882b'.decode(
            'HEX')
        master = dispersy.get_member(public_key=master_key)
        return [master]

    def __init__(self, *args, **kwargs):
        super(PlebCommunity, self).__init__(*args, **kwargs)
        self.gather = False

    def initialize(self, gather=False):
        super(PlebCommunity, self).initialize()
        self.gather = gather
        print "PlebCommunity initialized"

    def initiate_meta_messages(self):
        return super(PlebCommunity, self).initiate_meta_messages() + [
            Message(self, u'heymessage',
                    MemberAuthentication(encoding='sha1'),
                    PublicResolution(),
                    DirectDistribution(),
                    CommunityDestination(node_count=100),
                    PlebMessage(),
                    self.check_message,
                    self.on_message),
        ]

    def initiate_conversions(self):
        return [DefaultConversion(self), PlebConversion(self)]

    def check_message(self, messages):
        for message in messages:
            allowed, _ = self._timeline.check(message)
            if allowed:
                yield message
            else:
                yield DelayMessageByProof(message)

    def send_plebmessage(self, text, store=True, update=True, forward=True):
        meta = self.get_meta_message(u'heymessage')
        message = meta.impl(authentication=(self.my_member,),
                            distribution=(self.claim_global_time(),),
                            payload=(text,))
        self.dispersy.store_update_forward([message], store, update, forward)

    def on_message(self, messages):
        # Do nothing with incoming messages
        if self.gather:
            with open('/root/plebmail.log', 'a') as f:
                for message in messages:
                    print '{0}: {1}'.format('received plebmail', message.payload.text)
                    f.write('{0}\n'.format(message.payload.text.strip()))
        else:
            pass


def start_dispersy():
    dispersy = Dispersy(StandaloneEndpoint(14333, '0.0.0.0'), unicode('.'), u'dispersy.db')
    dispersy.statistics.enable_debug_statistics(True)
    dispersy.start(autoload_discovery=True)

    my_member = dispersy.get_new_member()
    master_member = PlebCommunity.get_master_members(dispersy)[0]
    community = PlebCommunity.init_community(dispersy, master_member, my_member, gather=True)

    #Not necessary
    #LoopingCall(lambda: community.send_plebmessage('HELLO')).start(60.0)


def main():
    reactor.callWhenRunning(start_dispersy)
    reactor.run()


if __name__ == '__main__':
    main()
