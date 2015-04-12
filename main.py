#!/usr/bin/env python3.4

from collections.abc import Mapping, Sequence
from configparser import ConfigParser
from functools import partial
import json
from logging import basicConfig, getLogger
from os.path import expanduser
import requests

from PyIRC.io.socket import IRCSocket
from PyIRC.extensions import bot_recommended
from PyIRC.hook import hook


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
    'join': ['#music'],
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
    'Stelpa', 'Stelpa6',
    'mc680x0', 'HorstBurkhardt',
    'mc68030', 'HorstBurkhardt',
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


###################
# pretty PyIRC
###################

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
        if hasattr(user, 'nick'):
            user = user.nick

        if user in nick2lastfm:
            user = nick2lastfm[user]

        doc = api_endpoint('user.getRecentTracks', {'limit': 1, 'user': user})
        ret = json.loads(doc.text)
        if 'recenttracks' not in ret or 'track' not in ret['recenttracks']:
            self.error(target, "Sorry... Last.FM may be broken...")
            return

        tracks = ret['recenttracks']['track']
        if tracks is None or len(tracks) == 0:
            error = "Doesn't look like anything's been playing in a while!"
            self.error(target, error)
            return

        if isinstance(tracks, Mapping):
            our_track = tracks
            np = ('@attr' in our_track and 'nowplaying' in our_track['@attr'])
        elif isinstance(tracks, Sequence):
            our_track = tracks[0]
            np = False
            for t in tracks:
                if '@attr' in t and 'nowplaying' in t['@attr']:
                    our_track = t
                    np = True
                    break
        else:
            error = "Last.FM gave me something I don't understand :("
            self.error(target, error)
            return

        if np:
            fmt = "{} is listening to {} by {}."
        else:
            fmt = "{} last listened to {} by {}."

        msg = fmt.format(user, our_track['name'], our_track['artist']['#text'])
        self.send('PRIVMSG', [target, msg])

        return

    def follow(self, target, params, user):
        return

    def unfollow(self, target, params, user):
        return

    def on_auth(self, dispatch, target, params, user):
        """ Authentication callback. """
        if not user:
            return  # they probably don't exist any more.

        if not user.account:
            error = 'Sorry {}; you have to be authenticated.'.format(user.nick)
            self.error(target, error)
            return

        if user.account not in admins:
            error = "Don't violate me, {}, I'm just a little fox ._."
            self.error(target, error.format(user.nick))
            return

        return dispatch(target, params, user)

    @hook("commands", "PRIVMSG")
    def on_message(self, event):
        """ Handle a PRIVMSG """
        sender = event.line.hostmask
        if not (sender and sender.nick):
            return  # what is this, glorircd?

        me = self.extensions.get_extension('BasicRFC').nick
        msg = event.line.params[-1]
        if not msg.startswith(me):
            return  # it isn't for me :(

        msg = msg[len(me):]
        if msg[0].isalnum():
            return  # probably someone else with a similar nick to me :(

        msg = msg[msg.index(' '):]
        msg = msg.lstrip()

        target = event.line.params[0]
        if target == me:
            target = sender.nick

        (command, _, params) = msg.partition(' ')
        if command not in self.dispatch:
            self.error(target, "Unknown command '{}'.".format(command))
            return

        disp = self.dispatch[command]
        if disp[0]:
            usertrack = self.extensions.get_extension('UserTrack')
            p = partial(self.on_auth, disp[1], target, params)
            usertrack.authenticate(sender.nick, p)
        else:
            disp[1](target, params, sender)

i = Orinoco(**arguments)

try:
    i.loop()
except KeyboardInterrupt:
    i.send('QUIT', ["Interrupted!"])
