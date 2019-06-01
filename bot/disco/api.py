from base64 import urlsafe_b64encode
from time import time
from urllib.parse import quote_plus


from disco.bot import Plugin
from disco.bot.command import CommandError
from disco.util.logging import logging
from disco.util.sanitize import S as sanitize
from lyrics_extractor import Song_Lyrics as get_lyrics
from requests import get, post


from bot.base import bot
from bot.util.misc import api_loop
from bot.util.react import generic_react

log = logging.getLogger(__name__)


class ApiPlugin(Plugin):
    def load(self, ctx):
        super(ApiPlugin, self).load(ctx)
        bot.local.api.get(
            self,
            "user_agent",
            "google_key",
            "spotify_ID",
            "spotify_secret",
            "google_cse_engine_ID",
            "user_agent",
        )
        bot.init_help_embeds(self)
        bot.custom_prefix_init(self)

    def unload(self, ctx):
        pass

    @Plugin.command("lyrics", "<content:str...>")
    def on_lyrics_command(self, event, content):
        """
        Api Return lyrics for a song.
        """
        self.pre_check("google_key", "google_cse_engine_ID")
        first_message = api_loop(
            event.channel.send_message,
            "Searching for lyrics...",
        )
        title, lyrics = get_lyrics(
            self.google_key,
            self.google_cse_engine_ID,
        ).get_lyrics(quote_plus(content))
        if len(lyrics) > 46300:
            return first_message.edit("I doubt that's a song.")
        if not lyrics:
            return first_message.edit("No Lyrics found for ``{}``".format(
                sanitize(
                    content,
                    escape_codeblocks=True,
                )
            ))
        lyrics_embed = bot.generic_embed_values(
            title=title,
            footer_text="Requested by {}".format(event.author),
            footer_img=event.author.get_avatar_url(size=32),
            timestamp=event.msg.timestamp.isoformat(),
        )
        first_message.delete()
        responses = 1
        while lyrics and responses < 4:
            lyrics_embed.description = lyrics[:2048]
            lyrics = lyrics[2048:]
            if lyrics:
                tmp_to_shift = lyrics_embed.description.splitlines()[-1]
                lyrics = tmp_to_shift + lyrics
                lyrics_embed.description = lyrics_embed.description[
                    :-len(tmp_to_shift)
                ]
            api_loop(event.channel.send_message, embed=lyrics_embed)
            responses += 1

    @Plugin.command("spotify", "<type:str> [search:str...]")
    def on_spotify_command(self, event, type, search=""):
        """
        Api Search for an item on Spotify.
        If the first argument is in the list
            "track", "album", "artist" or "playlist",
            then the relevant search point will be used.
        Otherwise, it will assume the user wants to find a track.
        """
        self.pre_check("spotify_ID", "spotify_secret")
        auth = urlsafe_b64encode("{}:{}".format(
            self.spotify_ID,
            self.spotify_secret
        ).encode()).decode()

        spotify_auth = getattr(self, "spotify_auth", None)
        if spotify_auth is not None and ((time() - self.spotify_auth_time)
                >= self.spotify_auth_expire):
            get_auth = True
        else:
            get_auth = False
        if spotify_auth is None or get_auth:
            self.get_spotify_auth(auth)
        if type not in ("track", "album", "artist", "playlist"):
            search = "{} {}".format(type, search)
            type = "track"
        elif search == "":
            return api_loop(
                event.channel.send_message,
                "Missing search argument.",
            )
        r = get(
            "https://api.spotify.com/v1/search?q={}&type={}".format(
                quote_plus(search),
                type,
            ),
            headers={
                "Authorization": "Bearer {}".format(self.spotify_auth),
                "User-Agent": self.user_agent,
                "Content-Type": "application/json",
            },
        )
        if r.status_code == 200:
            if not r.json()[type+"s"]["items"]:
                return api_loop(
                    event.channel.send_message,
                    "{}: ``{}`` not found.".format(
                        type,
                        sanitize(search, escape_codeblocks=True)
                    )
                )
            url = r.json()[type+"s"]["items"][0]["external_urls"]["spotify"]
            reply = api_loop(event.channel.send_message, url)
            if (len(r.json()[type+"s"]["items"]) > 1 and
                    not event.channel.is_dm):
                bot.reactor.init_event(
                    message=reply,
                    timing=30,
                    data=r.json()[type+"s"]["items"],
                    index=0,
                    amount=1,
                    edit_message=self.spotify_react,
                )
                bot.reactor.add_reactors(
                    self,
                    reply,
                    generic_react,
                    event.author.id,
                    "\N{leftwards black arrow}",
                    "\N{Cross Mark}",
                    "\N{black rightwards arrow}",
                )
        else:
            log.warning(r.text)
            api_loop(
                event.channel.send_message,
                "Error code {} returned".format(r.status_code),
            )

    def get_spotify_auth(self, auth):
        access_time = time()
        r = post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": "Basic {}".format(auth),
                "User-Agent": self.user_agent,
            },
        )
        if r.status_code != 200:
            log.warning(r.text)
            raise CommandError(
                "Error code {} returned by initial".format(
                    r.status_code,
                )
            )
        self.spotify_auth = r.json()["access_token"]
        self.spotify_auth_expire = r.json()["expires_in"]
        self.spotify_auth_time = access_time

    def spotify_react(self, data, index, kwargs):
        return data[index]["external_urls"]["spotify"], None

    @Plugin.command(
        "youtube",
        "<yt_type:str> [content:str...]",
        aliases=("yt", )
    )
    def on_youtube_command(self, event, yt_type, content=None):
        """
        Api Search for a Youtube video.
        If the first argument is in the list
            "video", "channel" or "playlist"
            then it will use the relevant search point.
        Otherwise, it will assume the user wants to find a video.
        """
        self.pre_check("google_key")
        yt_types_indexs = {
            "video": {
                "index": "videoId",
                "url": "https://www.youtube.com/watch?v={}",
            },
            "channel": {
                "index": "channelId",
                "url": "https://www.youtube.com/channel/{}",
            },
            "playlist": {
                "index": "playlistId",
                "url": "https://www.youtube.com/playlist?list={}",
            },
        }
        if content is None:
            content = yt_type
            yt_type = "video"
        elif yt_type not in yt_types_indexs:
            content = "{} {}".format(yt_type, content)
            yt_type = "video"
        r = get(
            "https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=50&key={}&type={}&q={}".format(
                self.google_key,
                yt_type,
                quote_plus(content),
            ),
            headers={
                "User-Agent": self.user_agent,
                "Content-Type": "application/json",
            },
        )
        if r.status_code == 200:
            if r.json()["pageInfo"]["totalResults"] != 0:
                response = r.json()["items"][0]["id"][
                    yt_types_indexs[yt_type]["index"]
                ]
                reply = api_loop(
                    event.channel.send_message,
                    yt_types_indexs[yt_type]["url"].format(response)
                )
                if (r.json()["pageInfo"]["totalResults"] > 1 and
                        not event.channel.is_dm):
                    bot.reactor.init_event(
                        message=reply,
                        timing=30,
                        data=r.json()["items"],
                        index=0, amount=1,
                        index_type=yt_types_indexs[yt_type]["index"],
                        url_format=yt_types_indexs[yt_type]["url"],
                        edit_message=self.youtube_react,
                    )
                    bot.reactor.add_reactors(
                        self,
                        reply,
                        generic_react,
                        event.author.id,
                        "\N{leftwards black arrow}",
                        "\N{Cross Mark}",
                        "\N{black rightwards arrow}",
                    )
            else:
                api_loop(event.channel.send_message, "Video not found.")
        else:
            log.warning(r.text)
            api_loop(
                event.channel.send_message,
                "Error code {} returned.".format(r.status_code),
            )

    def youtube_react(self, data, index, kwargs):
        return kwargs["url_format"].format(
                data[index]["id"][kwargs["index_type"]],
            ), None

    def pre_check(self, *args):
        """
        Checks to see if api keys are available.
        returns a CommandError if not present
        """
        for key in args:
            if getattr(self, key, None) == None:
                raise CommandError("This function is disabled.")
