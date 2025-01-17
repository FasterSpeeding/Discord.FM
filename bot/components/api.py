from base64 import urlsafe_b64encode
from time import time
import urllib.parse

import datetime
import typing
import alluka
import tanchan
import httpx

import hikari
import asyncio
import tanjun
from tanjun import annotations
import lyrics_extractor
import yuyo
from requests import get, post


from .. import config
from .. import util
from ...base import bot
from ..util.misc import api_loop, exception_webhooks, redact
from ..util.react import generic_react


api_component = tanjun.Component(name="api", strict=True)


@tanjun.with_own_permission_check(hikari.Permissions.EMBED_LINKS, follow_wrapped=True)
@tanjun.with_str_slash_option("name", "Name of the song to search for")
@tanchan.doc_parse.as_slash_command(name="lyrics")
@tanjun.as_message_command("lyrics")
async def on_lyrics_command(
    ctx: tanjun.abc.SlashContext | tanjun.abc.MessageContext,
    name: str = "",
    *,
    components: alluka.Injected[yuyo.ComponentClient],
    config: alluka.Injected[config.ApiConfig],
    lyrics_api: alluka.Injected[lyrics_extractor.SongLyrics],
) -> None:
    """
    Return lyrics for a song.
    """
    if isinstance(ctx, tanjun.abc.MessageContext):
        name = ctx.content

    if not config.google_key or not config.google_cse_engine_ID:
        raise tanjun.CommandError("This command is disabled")

    message = await ctx.respond(
        "Searching for lyrics...", ensure_result=True
    )
    event_loop = asyncio.get_running_loop()
    title, lyrics = event_loop.run_in_executor(None, lyrics_api.get_lyrics, urllib.parse.quote_plus(name))

    if not lyrics:
        await ctx.edit_last_response(
            f"No lyrics found for ``{name}``",
        )
        return

    if len(lyrics) > 46300:
        await ctx.edit_last_response("I doubt that's a song.")
        return

    embeds = (
        hikari.Embed(
            title=title,
            timestamp=ctx.created_at,
            description=description
        ).set_footer(f"Requested by {ctx.author}", icon=ctx.author.make_avatar_url(size=32))
        for description in yuyo.sync_paginate_string(lyrics)
    )
    embeds = map(yuyo.Page, embeds)
    paginator = yuyo.ComponentPaginator(embeds, authors=[ctx.author])
    response = await paginator.get_next_entry()
    components.register_executor(paginator, message=message, timeout=yuyo.SlidingTimeout(datetime.timedelta(minutes=2)))
    assert response
    await ctx.edit_last_response(**response.to_kwargs())


def _build_spotify_auth(
    config: alluka.Injected[config.ApiConfig], ctx: alluka.Injected[tanjun.abc.Context]
) -> util.ClientCredentialsOauth2:
    if not config.spotify_id or not config.spotify_secret:
        raise tanjun.MissingDependencyError("Missing spotify secret and/or client id", None)

    return util.ClientCredentialsOauth2(
        "https://accounts.spotify.com/api/token", config.spotify_id, config.spotify_secret
    )


class SpotifyType(str, enum.Enum):
    Track = "track"
    Album = "album"
    Artist = "artist"
    Playlist = "playlist"


@Plugin.command("spotify", "<sp_type:str> [search:str...]", metadata={"help": "api"})
@tanjun.as_message_command("spotify")
@tanchan.doc_parse.as_slash_command(name="spotify")
async def on_spotify_command(
    ctx: tanjun.abc.Context,
    search: annotations.Str,
    sp_type: str = annotations.str_field(choices={key.capitalize(): key for key in _SPOTIFY_TYPES}),
    *,
    config: alluka.Injected[config.ApiConfig],
    rest: alluka.Injected[httpx.AsyncClient],
):
    """
    Search for an item on Spotify.
    """
    if not config.spotify_id or not config.spotify_secret:
        raise tanjun.CommandError("This command is disabled.")

    spotify_auth = getattr(self, "spotify_auth", None)
    if not spotify_auth or time() >= self.spotify_auth_expire:
        self.get_spotify_auth()
    if not search or sp_type not in _SPOTIFY_TYPES:
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
                self.client,
                reply,
                generic_react,
                event.author.id,
                "\N{leftwards black arrow}",
                "\N{Cross Mark}",
                "\N{black rightwards arrow}",
            )
    else:
        self.log.warning(r.text)
        if bot.config.exception_webhooks:
            exception_webhooks(
                self.client,
                bot.config.exception_webhooks,
                content=(f"Spotify threw error {r.status_code}: "
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
        self.log.warning(redact(str(r.text)))
        if bot.config.exception_webhooks:
            exception_webhooks(
                self.client,
                bot.config.exception_webhooks,
                content=(f"Spotify OAUTH threw error {r.status_code}: "
                            f"```{redact(r.text)[:1950]}```"),
            )
        raise tanjun.CommandError(
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
                    self.client,
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
        self.log.warning(r.text)
        if bot.config.exception_webhooks:
            exception_webhooks(
                self.client,
                bot.config.exception_webhooks,
                content=(f"Youtube threw error {r.status_code}: "
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
