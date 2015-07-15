#!/usr/bin/env python3.4

from collections.abc import Mapping, Sequence
from configparser import ConfigParser
from functools import partial
import json
from logging import basicConfig, getLogger
from os.path import expanduser
import requests
import xml.dom
from xml.dom import minidom

from PyIRC.io.socket import IRCSocket
from PyIRC.extensions import bot_recommended
from PyIRC.signal import event


###################
# really disgusting config crap I have to do
###################

basicConfig(level="DEBUG")
logger = getLogger('Orinoco')

config = ConfigParser()
config.read(['orinoco.cfg', expanduser('~/orinoco.cfg')])

if 'server' not in config or 'lastfm' not in config:
    raise Exception('You must configure Orinoco before running him.')

server_port = (
    config['server'].get('address', 'dookie.interlinked.me'),
    int(config['server'].get('port', '9999'))
)

arguments = {
    'serverport': server_port,
    'ssl': True,
    'username': config['server'].get('username', 'poopy'),
    'nick': config['server'].get('nick', 'Orinoco'),
    'gecos': 'Back with a new rhyme.',
    'extensions': bot_recommended,
    'sasl_username': config['server']['username'],
    'sasl_password': config['server']['password'],
    'join': ['#PyIRC'],
}

admins = ['CorgiDude', 'Missingno', 'aji']

nick2lastfm = {
    'aji': 'theta4',
    'kitty': 'theta4',
    'TheWilfox': 'CorgiDude',
    'Elizafox': 'therealelizacat',
    'rwg': 'rwgfx',
    'lstarnes': 'lstarnes1024',
    'Allie': 'foxiepaws',
    'alyx': 'alyxw',
    # shmibs is herself
    'Stelpa': 'Stelpa6',
    'mc680x0': 'HorstBurkhardt',
    'mc68030': 'HorstBurkhardt',
    # TODO: make this sqlite or something
}


def api_endpoint(func, params):
    url = "http://ws.audioscrobbler.com/2.0/"
    params.update({
        'format': 'json',
        'api_key': config['lastfm']['apikey'],
        'method': func
    })
    return requests.get(url, params=params)


class Track:
    __slots__ = ['artist', 'title', 'album',
                 'genres', 'duration', 'loved', 'mbid', 'playing']

    def __init__(self, artist, title, **kwargs):
        self.artist = artist
        self.title = title
        self.album = kwargs.get('album', None)
        self.genres = kwargs.get('genres', None)
        self.duration = kwargs.get('duration', None)
        self.loved = kwargs.get('loved', None)
        self.mbid = kwargs.get('mbid', None)
        self.playing = kwargs.get('playing', None)

    def __str__(self):
        return "{title} by {artist}".format(title=self.title,
                                            artist=self.artist)

    def format(self, fmt, **props):
        props.update({name: getattr(self, name) for name in self.__slots__ if getattr(self, name, None) is not None})
        return fmt.format(**props)

    @classmethod
    def from_json(cls, json):
        assert isinstance(json, Mapping)

        kw = {}

        print(repr(json))

        assert 'name' in json
        assert 'artist' in json

        if '#text' in json['artist']:
            artist = json['artist']['#text']
        else:
            artist = str(json['artist'])

        title = json['name']

        if 'album' in json:
            if '#text' in json['album']:
                kw['album'] = json['album']['#text']
            else:
                kw['album'] = str(json['album'])

        if '@attr' in json:
            kw['playing'] = ('nowplaying' in json['@attr'])

        return cls(artist, title, **kw)

    @classmethod
    def from_xml(cls, xml):
        assert isinstance(xml, xml.dom.Document)
        # TODO


###################
# pretty PyIRC
###################

class LastFM:
    @staticmethod
    def _most_recent_track_json(ret):
        if 'recenttracks' not in ret or 'track' not in ret['recenttracks']:
            return None

        tracks = ret['recenttracks']['track']
        if tracks is None or len(tracks) == 0:
            return None

        if isinstance(tracks, Mapping):
            return Track.from_json(tracks)
        elif isinstance(tracks, Sequence):
            our_track = Track.from_json(tracks[0])
            for t in tracks:
                if '@attr' in t and 'nowplaying' in t['@attr']:
                    our_track = Track.from_json(t)
            return our_track
        else:
            return None

    @staticmethod
    def _most_recent_track_xml(ret):
        return None

    @staticmethod
    def most_recent_track(acct):
        doc = api_endpoint('user.getRecentTracks', {'limit': 1, 'user': acct})
        logger.debug('response: %r', doc.text)

        methods = {
            json.loads: LastFM._most_recent_track_json,
            minidom.parseString: LastFM._most_recent_track_xml,
        }

        for deser, ctor in methods.items():
            try:
                raw = deser(doc.text)
                return ctor(raw)
            except:
                logger.exception('Swallowing Last.FM deserialisation exception')
                continue

        logger.warning('No appropriate deserialisation method for response.')
        return None

class Orinoco(IRCSocket):
    def __init__(self, *args, **kwargs):
        super(Orinoco, self).__init__(*args, **kwargs)
        self.dispatch = {
            'np': (False, self.get_np),
            'follow': (True, self.follow),
            'unfollow': (True, self.unfollow),
        }

    def error(self, target, error):
        """ Give the user an error. """
        self.send('PRIVMSG', [target, error])
        return

    def get_np(self, target, params, user):
        acct = user.nick

        if user.nick in nick2lastfm:
            acct = nick2lastfm[user.nick]

        if params:
            acct = params.split(' ')[0]

        track = LastFM.most_recent_track(acct)
        if track is None:
            self.error(target, "Sorry... Last.FM may be broken...")
            return

        if track.playing:
            fmt = "{acct} is listening to {title} by {artist}."
        else:
            fmt = "{acct} last listened to {title} by {artist}."

        msg = track.format(fmt, acct=acct)
        self.send('PRIVMSG', [target, msg])

        return

    def follow(self, target, params, user):
        return

    def unfollow(self, target, params, user):
        return

    def on_auth(self, target, params, admin, dispatch, user):
        """ Authentication callback. """
        if not user:
            return  # they probably don't exist any more.

        if not user.account and dispatch[0]:
            error = 'Sorry {}; you have to be authenticated.'.format(user.nick)
            self.error(target, error)
            return

        if user.account not in admins and admin:
            error = "Don't violate me, {}, I'm just a little fox ._."
            self.error(target, error.format(user.nick))
            return

        return dispatch(target, params, user)

    @event("commands", "PRIVMSG")
    def on_message(self, caller, line):
        """ Handle a PRIVMSG """
        sender = line.hostmask
        if not (sender and sender.nick):
            return  # what is this, glorircd?

        me = self.extensions.get_extension('BasicRFC').nick
        msg = line.params[-1]
        if not msg.startswith(me):
            return  # it isn't for me :(

        msg = msg[len(me):]
        if msg[0].isalnum():
            return  # probably someone else with a similar nick to me :(

        msg = msg[msg.index(' '):]
        msg = msg.lstrip()

        target = line.params[0]
        if target == me:
            target = sender.nick

        (command, _, params) = msg.partition(' ')
        if command not in self.dispatch:
            self.error(target, "Unknown command '{}'.".format(command))
            return

        disp = self.dispatch[command]
        usertrack = self.extensions.get_extension('UserTrack')
        p = partial(self.on_auth, target, params, *disp)
        usertrack.authenticate(sender.nick, p)

i = Orinoco(**arguments)

try:
    i.loop()
except KeyboardInterrupt:
    i.send('QUIT', ['Interrupted!'])
