from base64 import urlsafe_b64encode
from time import time
from urllib.parse import quote_plus


from disco.bot import Plugin
from disco.bot.command import CommandError
from disco.types.permissions import Permissions
from disco.util.logging import logging
from disco.util.sanitize import S as sanitize
from lyrics_extractor import Song_Lyrics
from requests import get, post


from bot.base import bot
from bot.util.misc import api_loop, exception_channels, redact
from bot.util.react import generic_react

log = logging.getLogger(__name__)


class ApiPlugin(Plugin):
    def load(self, ctx):
        super(ApiPlugin, self).load(ctx)
        bot.config.api.get(
            self,
            "user_agent",
            "google_key",
            "spotify_ID",
            "spotify_secret",
            "google_cse_engine_ID",
        )
        bot.load_help_embeds(self)
        self.lyrics = Song_Lyrics(
            self.google_key,
            self.google_cse_engine_ID,
        )

    def unload(self, ctx):
        bot.unload_help_embeds(self)
        super(ApiPlugin, self).unload(ctx)

    @Plugin.command("lyrics", "<content:str...>", metadata={"help": "api"})
    def on_lyrics_command(self, event, content):
        """
        Return lyrics for a song.
        """
        self.pre_check("google_key", "google_cse_engine_ID")
        if event.channel.is_dm:
            limit = 6
        else:
            guild = bot.sql(bot.sql.guilds.query.get, event.guild.id)
            if not guild:
                guild = bot.sql.guilds(
                    guild_id=event.guild.id,
                    prefix=bot.prefix,
                )
                bot.sql.add(guild)
            elif guild.lyrics_limit <= 0:
                return api_loop(
                    event.channel.send_message,
                    "This command has been disabled in this guild.",
                )
            limit = guild.lyrics_limit
        first_message = api_loop(
            event.channel.send_message,
            "Searching for lyrics...",
        )
        title, lyrics = self.lyrics.get_lyrics(quote_plus(content))

        if not lyrics:
            content = sanitize(content, escape_codeblocks=True)
            return api_loop(
                first_message.edit,
                f"No Lyrics found for ``{content}``",
            )
        elif len(lyrics) > 46300:
            return first_message.edit("I doubt that's a song.")
        footer = {
            "text": f"Requested by {event.author}",
            "img": event.author.get_avatar_url(size=32),
        }
        lyrics_embed = bot.generic_embed_values(
            title={"title": title},
            footer=footer,
            timestamp=event.msg.timestamp.isoformat(),
        )
        first_message.delete()
        responses = 0
        limit = limit if limit is not None else 3
        while lyrics and responses < limit:
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

    @Plugin.command("limit lyrics", "[limit:int]", metadata={"help": "api"})
    def on_lyrics_limit_command(self, event, limit=None):
        """
        Used to set the maximum amount of embeds sent by the lyrics command.
        Only argument is an integer that must be between 0 and 8.
        When set to 0, the lyrics command will be disabled.
        """
        if event.channel.is_dm:
            return api_loop(
                event.channel.send_message,
                "This command cannot be used in DMs.",
            )
        if limit is not None:
            member = event.guild.get_member(event.author)
            if member.permissions.can(Permissions.MANAGE_GUILD):
                if not 0 <= limit <= 8:
                    return api_loop(
                        event.channel.send_message,
                        "The limit can only be between 0 and 8.",
                    )
                guild = bot.sql(bot.sql.guilds.query.get, event.guild.id)
                if not guild:
                    guild = bot.sql.guilds(
                        guild_id=event.guild_id,
                        lyrics_limit=limit,
                        prefix=bot.prefix,
                    )
                    bot.sql.add(guild)
                else:
                    bot.sql(
                        bot.sql.guilds.query.filter_by(
                            guild_id=event.guild.id,
                        ).update,
                        {"lyrics_limit": limit},
                    )
                api_loop(
                    event.channel.send_message,
                    f"Changed lyric response embed limit to {limit}.",
                )
            else:
                api_loop(
                    event.channel.send_message,
                    "This command is limited to server admins.",
                )
        else:
            guild = bot.sql(bot.sql.guilds.query.get, event.guild.id)
            limit = guild.lyrics_limit if guild.lyrics_limit is not None else 3
            api_loop(
                    event.channel.send_message,
                    f"The current limit is set to {limit}",
                )

    @Plugin.command("spotify", "<sp_type:str> [search:str...]", metadata={"help": "api"})
    def on_spotify_command(self, event, sp_type, search=""):
        """
        Search for an item on Spotify.
        If the first argument is in the list
            "track", "album", "artist" or "playlist",
            then the relevant search point will be used.
        Otherwise, it will assume the user wants to find a track.
        """
        self.pre_check("spotify_ID", "spotify_secret")
        spotify_auth = getattr(self, "spotify_auth", None)
        if not spotify_auth or time() >= self.spotify_auth_expire:
            self.get_spotify_auth()
        if not search or sp_type not in ("track", "album", "artist", "playlist"):
            search = f"{sp_type} {search}".strip(" ")
            sp_type = "track"
        r = get(
            "https://api.spotify.com/v1/search",
            params={
                "q": search,
                "type": sp_type,
            },
            headers={
                "Authorization": f"Bearer {self.spotify_auth}",
                "User-Agent": self.user_agent,
                "Content-Type": "application/json",
            },
        )
        if r.status_code == 200:
            if not r.json()[sp_type+"s"]["items"]:
                search = sanitize(search, escape_codeblocks=True)
                return api_loop(
                    event.channel.send_message,
                    f"{sp_type}: ``{search}`` not found."
                )
            url = r.json()[sp_type+"s"]["items"][0]["external_urls"]["spotify"]
            reply = api_loop(event.channel.send_message, url)
            if (len(r.json()[sp_type+"s"]["items"]) > 1 and
                    not event.channel.is_dm):
                bot.reactor.init_event(
                    message=reply,
                    data=r.json()[sp_type+"s"]["items"],
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
            if bot.config.exception_channels:
                exception_channels(
                    self.client,
                    bot.config.exception_channels,
                    (f"Spotify threw error {r.status_code}: "
                     f"```{redact(r.text)[:1950]}```"),
                )
            api_loop(
                event.channel.send_message,
                f"Error code {r.status_code} returned.",
            )

    def get_spotify_auth(self):
        auth = urlsafe_b64encode(
            f"{self.spotify_ID}:{self.spotify_secret}".encode()
        ).decode()
        r_time = time()
        r = post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {auth}",
                "User-Agent": self.user_agent,
            },
        )
        if r.status_code != 200:
            log.warning(redact(str(r.text)))
            if bot.config.exception_channels:
                exception_channels(
                    self.client,
                    bot.config.exception_channels,
                    (f"Spotify OAUTH threw error {r.status_code}: "
                     f"```{redact(r.text)[:1950]}```"),
                )
            raise CommandError(
                f"Error code {r.status_code} returned by oauth flow"
            )
        self.spotify_auth = r.json()["access_token"]
        self.spotify_auth_expire = r_time + r.json()["expires_in"]

    @staticmethod
    def spotify_react(data, index, **kwargs):
        return data[index]["external_urls"]["spotify"], None

    @Plugin.command("youtube", "<yt_type:str> [content:str...]", aliases=["yt"], metadata={"help": "api"})
    def on_youtube_command(self, event, yt_type, content=""):
        """
        Search for a Youtube video.
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
        if not content or yt_type not in yt_types_indexs:
            content = f"{yt_type} {content}".strip(" ")
            yt_type = "video"
        r = get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "maxResults": 50,
                "key": self.google_key,
                "type": yt_type,
                "q": content,
            },
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
            if bot.config.exception_channels:
                exception_channels(
                    self.client,
                    bot.config.exception_channels,
                    (f"Youtube threw error {r.status_code}: "
                     f"```{redact(r.text)[:1950]}```"),
                )
            api_loop(
                event.channel.send_message,
                f"Error code {r.status_code} returned.",
            )

    @staticmethod
    def youtube_react(data, index, **kwargs):
        return kwargs["url_format"].format(
                data[index]["id"][kwargs["index_type"]],
            ), None

    def pre_check(self, *args):
        """
        Checks to see if api key(s) are available.
        raises a CommandError if not present
        """
        for key in args:
            if not getattr(self, key, None):
                raise CommandError("This function is disabled.")
