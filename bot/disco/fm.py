from decimal import Decimal
from time import time, strftime, gmtime
import re


from disco.bot import Plugin
from disco.bot.command import CommandError
from disco.util.logging import logging
from disco.util.sanitize import S as sanitize
from requests import get, Session, Request
from requests.exceptions import ConnectionError as requestCError


from bot.base import bot
from bot.util.misc import (
    api_loop, AT_to_id, get_dict_item,
    user_regex as discord_regex,
)
from bot.util.react import generic_react
from bot.util.sql import (
    aliases, db_session, friends,
    handle_sql, periods, users
)

log = logging.getLogger(__name__)


class fmEntryNotFound(CommandError):
    """Last.fm entry not found."""


class fmPlugin(Plugin):
    def load(self, ctx):
        super(fmPlugin, self).load(ctx)
        bot.load_help_embeds(self)
        self.user_reg = re.compile("[a-zA-Z]{1}[a-zA-Z0-9_-]{1,14}")
        self.mbid_reg = re.compile(
            "[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}",
        )
        bot.local.api.get(
            self,
            "discogs_secret",
            "discogs_key",
        )
        self.cache = {}
        self.cool_downs = {"fulluser": {}, "friends": []}
        self.prefix = (bot.local.prefix or
                       bot.local.disco.bot.commands_prefix or
                       "fm.")
        self.s = Session()
        self.s.params = {
            "api_key": bot.local.api.last_key,
            "format": "json",
        }
        self.s.headers.update({
            "User-Agent": bot.local.api.user_agent,
            "Content-Type": "application/json",
        })
        self.BASE_URL = "https://ws.audioscrobbler.com/2.0/"

    def unload(self, ctx):
        bot.unload_help_embeds(self)
        super(fmPlugin, self).unload(ctx)

    @staticmethod
    def __check__():
        return bot.local.api.last_key

    @Plugin.schedule(60)
    def purge_cache(self):
        log.debug("Purging cache.")
        for url, cache_obj in self.cache.copy().items():
            if cache_obj.expire > time():
                del self.cache[url]

    @Plugin.command("alias add", "<alias:str...>", metadata={"help": "last.fm"})
    def on_alias_set_command(self, event, alias):
        """
        Used to add or remove a user alias in a guild.
        Users are limited to 5 alises in a guild.
        Alises are limited to 20 characters
        and cannot contain Discord's reserved special characters (e.g. '@').
        """
        if event.channel.is_dm:
            return api_loop(
                event.channel.send_message,
                "Alias commands are guild specific.",
            )
        if len(alias) > 20 or sanitize(alias, escape_codeblocks=True) != alias:
            api_loop(
                event.channel.send_message,
                ("Aliasas are limited to 20 characters and cannot "
                 "contain Discord's reserved special characters."),
            )
        else:
            data = handle_sql(aliases.query.filter(
                aliases.guild_id == event.guild.id,
                aliases.alias.like(alias),
            ).first)
            if data is None:
                if (handle_sql(aliases.query.filter_by(
                    user_id=event.author.id,
                    guild_id=event.guild.id,
                ).count) < 5):
                    payload = aliases(
                        user_id=event.author.id,
                        guild_id=event.guild.id,
                        alias=alias,
                    )
                    handle_sql(db_session.add, payload)
                    handle_sql(db_session.flush)
                    api_loop(
                        event.channel.send_message,
                        f"Added alias ``{alias}``.",
                    )
                else:
                    api_loop(
                        event.channel.send_message,
                        "You've reached the 5 alias limit for this guild."
                    )
            else:
                if data.user_id == event.author.id:
                    handle_sql(aliases.query.filter_by(
                        user_id=event.author.id,
                        guild_id=event.guild.id,
                        alias=data.alias,
                    ).delete)
                    handle_sql(db_session.flush)
                    api_loop(
                        event.channel.send_message,
                        f"Removed alias ``{data.alias}``.",
                    )
                else:
                    api_loop(
                        event.channel.send_message,
                        (f"Alias ``{data.alias}`` is "
                         "already taken in this guild."),
                    )

    @Plugin.command("alias list", "[target:str...]", metadata={"help": "last.fm"})
    def on_alias_list_command(self, event, target=None):
        """
        Used to get a list of a user's aliases in a guild.
        This command will default to the author.
        But will target another user if their ID, @ or nickname is passed.
        Returns a list of the target's alises.
        """
        if event.channel.is_dm:
            api_loop(
                event.channel.send_message,
                "Alias commands are guild specific.",
            )
        else:
            if target is None:
                target = event.author.id
            else:
                try:
                    target = AT_to_id(target)
                except CommandError:
                    data = handle_sql(aliases.query.filter(
                        aliases.guild_id == event.guild.id,
                        aliases.alias.like(target),
                    ).first)
                    if data is None:
                        raise CommandError("User alias not "
                                           "found in this guild.")
                    target = data.user_id
            data = handle_sql(aliases.query.filter_by(
                user_id=target,
                guild_id=event.guild.id,
            ).all)
            user = self.client.api.guilds_members_get(event.guild.id, target)
            if data:
                inline = {
                    str(index + 1): alias.alias for
                    index, alias in enumerate(data)}
                embed = bot.generic_embed_values(
                    title={"title": f"{user.name}'s aliases "
                           "in {event.guild.name}"},
                    non_inlines=inline,
                )
                api_loop(
                    event.channel.send_message,
                    embed=embed,
                )
            else:
                api_loop(
                    event.channel.send_message,
                    "User doesn't have any aliases set in this guild.",
                )

    @Plugin.command("artist info", "<artist:str...>", metadata={"help": "last.fm"})
    def on_artist_command(self, event, artist):
        """
        Get an artist's info on Last.fm.
        """
        artist = self.get_artist(artist)
        artist_info = artist.get("artist")
        if not artist_info:
            response = artist.get("message")
            if not response:
                response = f"Unknown error occured {code}."
                log.warning(f"Failed to get artist error: {artist}")
            return api_loop(event.channel.send_message, response)
        inline = {
            "Listeners": artist_info["stats"]["listeners"],
            "Play Count": artist_info["stats"]["playcount"],
            "On-Tour": str(bool(artist_info["ontour"])),
            "skip_inlines": "N/A",
        }
        title = {
            "title": artist_info["name"],
            "url": artist_info["url"],
        }
        artist_embed = bot.generic_embed_values(
            title=title,
            thumbnail=artist_info["image"][-1]["#text"],
            inlines=inline,
        )
        api_loop(event.channel.send_message, embed=artist_embed)

    @Plugin.command("chart")
    def on_chart_command(self, event):
        raise CommandError("Not implemented yet, coming soon.")

    @Plugin.command("friends", metadata={"help": "last.fm"})
    def on_friends_command(self, event):
        """
        Get a list of what your friends have recently listened to.
        Accepts no arguments.
        """
        user = handle_sql(users.query.get, event.author.id)
        if not user or not user.friends:
            api_loop(
                event.channel.send_message,
                ("You don't have any friends, use "
                 f"``{self.prefix}friends add`` to catch some."),
            )
        else:
            title = {
                "title": f"{event.author} friends.",
                "url": ("https://www.last.fm/user/{user.last_username}"
                        if user.last_username else None),
            }
            data = [f.slave_id for f in user.friends]
            content, embed = self.friends_search(
                data,
                0,
                owner=event.author.id,
                title=title,
                thumbnail=event.author.avatar_url,
            )
            reply = api_loop(event.channel.send_message, content, embed=embed)
            if len(data) > 5 and not event.channel.is_dm:
                bot.reactor.init_event(
                    message=reply,
                    timing=30,
                    owner=event.author.id,
                    data=data,
                    index=0,
                    amount=5,
                    title=title,
                    thumbnail=event.author.avatar_url,
                    edit_message=self.friends_search,
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

    def friends_search(self, data, index, owner, limit=5, **kwargs):
        embed = bot.generic_embed_values(**kwargs)
        if len(data) - index < limit:
            limit = len(data) - index
        for x in range(limit):
            current_index = index + x
            while True:
                user = self.state.users.get(int(data[current_index]))
                user = str(user) if user else data[current_index]
                friend = self.get_user_info(data[current_index])
                if not friend["username"]:
                    handle_sql(friends.query.filter_by(
                        master_id=owner,
                        slave_id=data[current_index]
                    ).delete)
                    handle_sql(db_session.flush)
                    data.pop(current_index)
                    if current_index >= len(data) - 1:
                        finished = True
                        break
                else:
                    finished = False
                    break
            if finished:
                break
            friend = friend["username"]
            limit = 2
            params = {
                "method": "user.getrecenttracks",
                "user": friend,
                "limit": limit,
            }
            try:
                self.get_fm_secondary(
                    embed=embed,
                    params=params,
                    name=f"[{current_index + 1}] {user} ({friend})",
                    primary_index="recenttracks",
                    secondary_index="track",
                    artists=True,
                    artist_name="#text",
                    entry_format="ago",
                    seperator="\n",
                    limit=limit,
                )
            except CommandError:
                embed.add_field(
                    name=f"[{current_index + 1}] {user}",
                    value=f"Unable to access Last.fm account `{friend}`.",
                    inline=True,
                )
            if current_index >= len(data) - 1:
                break
        return None, embed

    @Plugin.command("friends add", "<target:str...>", metadata={"help": "last.fm"})
    def on_friends_add_command(self, event, target):
        """
        Add another user to your friends list.
        This command will add or remove a target user from your friend's list
        and won't target users that haven't setup a last.fm username.
        This command accepts either a Discord user ID or @user
        """
        target = self.get_user_info(target, event.guild.id)
        if not target["username"]:
            raise CommandError("Target user doesn't have "
                               "a Last.FM account setup.")
        target = target["user_id"]
        name = self.state.users.get(int(target))
        name = str(name) if name else target
        user = handle_sql(users.query.get, event.author.id)
        if not user:
            user = users(user_id=event.author.id)
            handle_sql(db_session.add, user)
        if not any([f.slave_id == target for f in user.friends]):
            friendship = friends(master_id=event.author.id, slave_id=target)
            user.friends.append(friendship)
            api_loop(
                event.channel.send_message,
                f"Added user ``{name}`` to friends list.",
            )
        else:
            friendships = [f for f in user.friends if f.slave_id == target]
            for friend_obj in friendships:
                user.friends.remove(friend_obj)
            api_loop(
                event.channel.send_message,
                f"Removed user ``{name}`` from friends list.",
            )
        handle_sql(db_session.flush)

    @Plugin.command("search artists", "<artist:str...>", metadata={"help": "last.fm"})
    def on_search_artist_command(self, event, artist):
        """
        Search for an artist on Last.fm.
        """
        artist_data = self.get_cached({
                "method": "artist.search",
                "artist": artist.lower(),
            },
            cool_down=3600,
        )
        artist_data = artist_data["results"]["artistmatches"]["artist"]
        if artist_data:
            thumbnail = self.get_artwork(artist, "Artist")
            content, embed = self.search_artist_react(
                artist_data,
                0,
                thumbnail=thumbnail,
            )
            reply = api_loop(event.channel.send_message, content, embed=embed)
            if len(artist_data) > 5 and not event.channel.is_dm:
                bot.reactor.init_event(
                    message=reply,
                    timing=30,
                    data=artist_data,
                    index=0,
                    amount=5,
                    edit_message=self.search_artist_react,
                    thumbnail=thumbnail
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
            api_loop(event.channel.send_message, "No artists found.")

    def search_artist_react(self, data, index, **kwargs):
        return None, self.search_embed(
            data=data,
            index=index,
            names=(("name", ), ),
            name_format="[{}]: {}",
            values=(("listeners", ), ("mbid", )),
            value_format="Listeners: {}, MBID: {}",
            item="Artist",
            **kwargs
        )

    @Plugin.command("search albums", "<album:str...>", metadata={"help": "last.fm"})
    def on_search_album_command(self, event, album):
        """
        Search for an album on Last.fm.
        """
        album_data = self.get_cached({
                "method": "album.search",
                "album": album.lower(),
                "limit": 30,
            },
            cool_down=3600,
        )
        album_data = album_data["results"]["albummatches"]["album"]
        if album_data:
            thumbnail = self.get_artwork(album, "Album")
            content, embed = self.search_album_react(
                album_data,
                0,
                thumbnail=thumbnail,
            )
            reply = api_loop(event.channel.send_message, content, embed=embed)
            if len(album_data) > 5 and not event.channel.is_dm:
                bot.reactor.init_event(
                    message=reply,
                    timing=30,
                    data=album_data,
                    index=0,
                    amount=5,
                    edit_message=self.search_album_react,
                    thumbnail=thumbnail,
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
            api_loop(event.channel.send_message, "No albums found.")

    def search_album_react(self, data, index, **kwargs):
        return None, self.search_embed(
            data,
            index=index,
            names=(("artist", ), ("name", )),
            name_format="[{}]: {} - {}",
            values=(("mbid", ), ),
            value_format="MBID: {}",
            item="Album",
            **kwargs,
        )

    @Plugin.command("search tracks", "<track:str...>", metadata={"help": "last.fm"})
    def on_search_track_command(self, event, track):
        """
        Search for a track on Last.fm.
        """
        track_data = self.get_cached({
                "method": "track.search",
                "track": track.lower(),
                "limit": 30,
             },
            cool_down=3600,
        )
        track_data = track_data["results"]["trackmatches"]["track"]
        if track_data:
            thumbnail = self.get_artwork(track, "Track")
            content, embed = self.search_track_react(
                track_data,
                0,
                thumbnail=thumbnail,
            )
            reply = api_loop(event.channel.send_message, content, embed=embed)
            if len(track_data) > 5 and not event.channel.is_dm:
                bot.reactor.init_event(
                    message=reply,
                    timing=30,
                    data=track_data,
                    index=0,
                    amount=5,
                    edit_message=self.search_track_react,
                    thumbnail=thumbnail,
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
            api_loop(event.channel.send_message, "No tracks found.")

    def search_track_react(self, data, index, **kwargs):
        return None, self.search_embed(
            data,
            index=index,
            names=(("artist", ), ("name", )),
            name_format="[{}]: {} - {}",
            values=(("listeners", ), ("mbid", )),
            value_format="Listeners: {}, MBID: {}",
            item="Track",
            **kwargs,
        )

    @Plugin.command("top albums", "[username:str...]", metadata={"help": "last.fm"})
    def on_top_albums_command(self, event, username=None):
        """
        Get an account's top albums.
        This command will default to the author.
        But will target another user if their ID, @ or nickname is passed.
        Returns the top albums of the target user's Last.FM account.
        """
        limit = 5
        if username is None:
            username = event.author.id
        period = self.get_user_info(event.author.id)["period"]
        footer = {
            "text": f"Requested by {event.author}",
            "img": event.author.get_avatar_url(size=32),
        }
        fm_embed, lastname = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            title_template=("Top albums for {} over " +
                            (" " + period).replace(" over", "")),
            footer=footer,
            timestamp=event.msg.timestamp.isoformat(),
        )
        params = {
            "method": "user.gettopalbums",
            "user": lastname,
            "limit": limit,
            "period": period,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            name="Album #{}",
            primary_index="topalbums",
            secondary_index="album",
            artists=True,
            entry_format="amount",
            limit=limit,
            inline=False,
            singular=False,
        )
        api_loop(event.channel.send_message, embed=fm_embed)

    @Plugin.command("top artists", "[username:str...]", metadata={"help": "last.fm"})
    def on_top_artists_command(self, event, username=None):
        """
        Get an account's top artists.
        This command will default to the author.
        But will target another user if their ID, @ or nickname is passed.
        Returns the top artists of the target user's Last.FM account.
        """
        limit = 5
        if username is None:
            username = event.author.id
        period = self.get_user_info(event.author.id)["period"]
        footer = {
            "text": f"Requested by {event.author}",
            "img": event.author.get_avatar_url(size=32),
        }
        fm_embed, lastname = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            title_template=("Top artists for {} over" +
                            (" " + period).replace(" over", "")),
            footer=footer,
            timestamp=event.msg.timestamp.isoformat(),
        )
        params = {
            "method": "user.gettopartists",
            "user": lastname,
            "limit": limit,
            "period": period,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            name="Artist #{}",
            primary_index="topartists",
            secondary_index="artist",
            entry_format="amount",
            limit=limit,
            inline=False,
            singular=False,
        )
        api_loop(event.channel.send_message, embed=fm_embed)

    @Plugin.command("top period", "[period:str...]", metadata={"help": "last.fm"})
    def on_top_period_command(self, event, period=None):
        """
        Used to set the user's period for the `top` group of commands.
        Accepts a string argument from one of the options below.
            Overall
            7 days
            1 months
            3 months
            6 months
            12 months
        The argument isn't case sensative and spaces are ignored.
        If no arguments are passed, the bot will output the user's set period.
        """
        if period is not None:
            period = period.replace(" ", "").strip("s").lower()
            if period in periods.values():
                self.get_user_info(event.author.id)
                handle_sql(
                    users.query.filter_by(
                        user_id=event.author.id,
                    ).update,
                    {"period": {y: x for x, y in periods.items()}[period]},
                )
                handle_sql(db_session.flush)
                api_loop(
                    event.channel.send_message,
                    ("Default period for 'top' commands "
                     f"updated to ``{period}``."),
                )
            else:
                api_loop(
                    event.channel.send_message,
                    (f"Invalid argument, see ``{self.prefix}"
                     "help top period`` for more details."),
                )
        else:
            data = self.get_user_info(event.author.id)
            api_loop(
                event.channel.send_message,
                ("Your default 'top' period is "
                 f"currently set to ``{data['period']}``"),
            )

    @Plugin.command("top tracks", "[username:str...]", metadata={"help": "last.fm"})
    def on_top_tracks_command(self, event, username=None):
        """
        Get an account's top tracks.
        This command will default to the author.
        But will target another user if their ID, @ or nickname is passed.
        Returns the top tracks of the target user's Last.FM account.
        """
        limit = 5
        if username is None:
            username = event.author.id
        period = self.get_user_info(event.author.id)["period"]
        footer = {
            "text": f"Requested by {event.author}",
            "img": event.author.get_avatar_url(size=32),
        }
        fm_embed, lastname = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            title_template=("Top tracks for {} over" +
                            (" " + period).replace(" over", "")),
            footer=footer,
            timestamp=event.msg.timestamp.isoformat(),
        )
        params = {
            "method": "user.gettoptracks",
            "user": lastname,
            "limit": limit,
            "period": period,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            name="Track #{}",
            primary_index="toptracks",
            secondary_index="track",
            artists=True,
            entry_format="amount",
            limit=limit,
            inline=False,
            singular=False,
        )
        api_loop(event.channel.send_message, embed=fm_embed)

    @Plugin.command("username", "[username:str]", metadata={"help": "last.fm"})
    def on_username_command(self, event, username: str = None):
        """
        Set user default last.fm account.
        This command accepts a username fitting Last.FM's username format
        as of 2019/04/11 and will assign that as the author's Last.FM account.
        If no arguments are passed, this will return the user's set username.
        """
        if username is not None:
            username = self.get_last_account(username)["user"]["name"]
            user = handle_sql(users.query.get, event.author.id)
            if user:
                handle_sql(
                    users.query.filter_by(
                        user_id=event.author.id,
                    ).update,
                    {"last_username": username},
                )
            else:
                user = users(
                    user_id=event.author.id,
                    last_username=username,
                )
                handle_sql(db_session.add, user)
            handle_sql(db_session.flush)
            api_loop(
                event.channel.send_message,
                f"Username for ``{event.author}`` changed to ``{username}``.",
            )
        else:
            username = self.get_user_info(event.author.id)["username"]
            if not username:
                api_loop(
                    event.channel.send_message,
                    f"Username not set for ``{event.author}``",
                )
            else:
                api_loop(
                    event.channel.send_message,
                    (f"Username for ``{event.author}`` currently "
                     f"set to ``{username}``."),
                )

    @Plugin.command("user", "[username:str...]", aliases=["np", "now"], metadata={"help": "last.fm"})
    def on_user_command(self, event, username=None):
        """
        Get basic stats from last.fm account.
        This command will default to the author.
        But will target another user if their ID, @ or nickname is passed.
        Returns the basic info of the target user's Last.FM account.
        """
        if username is None:
            username = event.author.id
        footer = {
            "text": f"Requested by {event.author}",
            "img": event.author.get_avatar_url(size=32),
        }
        fm_embed, username = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            footer=footer,
            timestamp=event.msg.timestamp.isoformat(),
        )
        params = {
            "method": "user.getrecenttracks",
            "user": username,
            "limit": 3
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            name="Recent tracks",
            primary_index="recenttracks",
            secondary_index="track",
            artists=True,
            artist_name="#text",
            entry_format="ago",
            cool_down=30,
            seperator="\n",
            limit=3,
        )
        api_loop(event.channel.send_message, embed=fm_embed)

    @Plugin.command("recent", "[username:str...]", metadata={"help": "last.fm"})
    def on_user_recent_command(self, event, username=None):
        """
        Get an account's recent tracks.
        This command will default to the author.
        But will target another user if their ID, @ or nickname is passed.
        Returns the recent tracks of the target user's Last.FM account.
        """
        limit = 5
        if username is None:
            username = event.author.id
        footer = {
            "text": f"Requested by {event.author}",
            "img": event.author.get_avatar_url(size=32),
        }
        fm_embed, username = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            footer=footer,
            timestamp=event.msg.timestamp.isoformat(),
        )
        params = {
            "method": "user.getrecenttracks",
            "user": username,
            "limit": limit,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            name="Track #{}",
            primary_index="recenttracks",
            secondary_index="track",
            artists=True,
            artist_name="#text",
            entry_format="ago",
            limit=limit,
            inline=False,
            cool_down=120,
            singular=False,
        )
        api_loop(event.channel.send_message, embed=fm_embed)

    @Plugin.command("full", "[username:str...]", metadata={"help": "last.fm"})
    def on_user_full_command(self, event, username=None):
        """
        Get stats from a last.fm account.
        This command will default to the author.
        But will target another user if their ID, @ or nickname is passed.
        Returns the stats of the target user's Last.FM account.
        """
        if username is None:
            username = event.author.id
        test = time()
        footer = {
            "text": f"Requested by {event.author}",
            "img": event.author.get_avatar_url(size=32),
        }
        fm_embed, username = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            footer=footer,
            timestamp=event.msg.timestamp.isoformat(),
        )
        message = api_loop(event.channel.send_message, "Searching for user.")
        period = self.get_user_info(event.author.id)["period"]
        params = {
            "method": "user.getrecenttracks",
            "user": username,
            "limit": 3,
            "period": period,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            name="Recent tracks",
            primary_index="recenttracks",
            secondary_index="track",
            artists=True,
            artist_name="#text",
            entry_format="ago",
            seperator="\n",
            limit=3,
            inline=False,
        )
        params = {
            "method": "user.gettoptracks",
            "user": username,
            "limit": 3,
            "period": period,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            name="Top tracks",
            primary_index="toptracks",
            secondary_index="track",
            artists=True,
            entry_format="amount",
            seperator="\n",
            inline=False,
        )
        params = {
            "method": "user.gettopartists",
            "user": username,
            "limit": 3,
            "period": period,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            name="Top artists",
            primary_index="topartists",
            secondary_index="artist",
            entry_format="amount",
            seperator="\n",
            inline=False,
        )
        params = {
            "method": "user.gettopalbums",
            "user": username,
            "limit": 3,
            "period": period,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            name="Top albums",
            primary_index="topalbums",
            secondary_index="album",
            artists=True,
            entry_format="amount",
            seperator="\n",
            inline=False,
        )
        fm_embed.set_footer(
            text=f"{round(Decimal(time() - test) * 1000)} ms",
        )
        api_loop(message.edit, " ", embed=fm_embed)

    @Plugin.command("reset user", metadata={"help": "data"})
    def on_user_reset_command(self, event):
        """
        Used to reset any user data stored by the bot (e.g. Last.fm username)
        """
        user = handle_sql(users.query.get, event.author.id)
        if user:
            handle_sql(db_session.delete, user)
            handle_sql(db_session.flush)
            api_loop(event.channel.send_message, "Removed user data.")
        else:
            api_loop(
                event.channel.send_message,
                ":thumbsup: Nothing to see here.",
            )

    def generic_user_data(
            self,
            username,
            title_template="{}",
            guild=None,
            **kwargs):
        user_data = self.get_user(username, guild)
        username = user_data["name"]
        if username is None:
            raise CommandError("User should set a last.fm account "
                               f"using ``{self.prefix}username``")
        inline = {
            "Playcount": user_data["playcount"],
            "Registered": strftime(
                "%Y-%m-%d %H:%M",
                gmtime(user_data["registered"]["#text"]),
            ),
            "skip_inlines": "N/A",
        }
        title = {
            "title": title_template.format(user_data["name"]),
            "url": user_data["url"],
        }
        fm_embed = bot.generic_embed_values(
            title=title,
            thumbnail=user_data["image"][len(user_data["image"]) - 1]["#text"],
            inlines=inline,
            **kwargs,
        )
        return fm_embed, user_data["name"]

    def get_artist(self, artist: str):
        params = {"method": "artist.getinfo"}
        if self.mbid_reg.fullmatch(artist):
            params.update({"mbid": artist.lower()})
        else:
            params.update({"artist": artist.lower()})
        artist_data = self.get_cached(params, cool_down=3600, item="artist")
        return artist_data

    def get_cached(
            self,
            params: dict,
            url: str = None,
            cool_down: int = 300,
            item: str = "item"):
        url = (url or self.BASE_URL)
        params = {str(key): str(value) for key, value in params.items()}
        get = self.s.prepare_request(Request("GET", url, params=params))
        url = get.url
        if (url not in self.cache or self.cache[url].exists and
                time() >= self.cache[url].expire):
            try:
                r = self.s.send(get)
            except requestCError as e:
                log.warning(e)
                raise CommandError("Last.FM isn't available right now.")
            if r.status_code == 200:
                if cool_down is not None:
                    self.cache[url] = type(
                        "cached_object",
                        (object, ),
                        {
                            "exists": True,
                            "expire": time() + cool_down,
                            "data": r.json(),
                            "error": None,
                        }
                    )()
                return r.json()
            elif r.status_code == 404:
                self.cache[url] = type(
                    "cached_object",
                    (object, ),
                    {
                        "exists": False,
                        "expire": time() + cool_down,
                        "data": None,
                        "error": f"404 - {item} doesn't exist.",
                    },
                )()
                raise fmEntryNotFound(self.cache[url].error)
            raise fmEntryNotFound(f"{r.status_code} - Last.fm "
                                      "threw unexpected HTTP status code.")
        elif self.cache[url].exists and time() <= self.cache[url].expire:
            return self.cache[url].data
        raise fmEntryNotFound(self.cache[url].error)

    def get_fm_secondary(
            self,
            embed,
            params,
            name,
            primary_index,
            secondary_index,
            url=None,
            artists=None,
            artist_name="name",
            entry_format=None,
            limit=4,
            inline=True,
            cool_down=300,
            payload_prefix="",
            seperator="; ",
            singular=True):
        data = self.get_cached(params, url=url, cool_down=cool_down)
        if len(data[primary_index][secondary_index]) < limit:
            limit = len(data[primary_index][secondary_index])
        payload = payload_prefix + ""
        if limit != 0:
            for index in range(limit):
                position = data[primary_index][secondary_index][index]
                if entry_format is None:
                    pass
                elif entry_format == "ago":
                    if "date" in data[primary_index][secondary_index][index]:
                        payload += self.time_since(position['date']['uts'])
                    else:
                        payload += "[Now] "
                elif entry_format == "amount":
                    payload += f"[{position['playcount']}] "
                if artists is not None:
                    payload += f"{position['artist'][artist_name]} - "
                payload += position["name"] + seperator
                if not singular:
                    embed.add_field(
                        name=f"{name.format(index + 1)}:",
                        value=payload.strip(seperator),
                        inline=inline,
                    )
                    payload = str()
        else:
            payload = "None"
        if singular or payload == "None":
            embed.add_field(
                name=f"{name}:",
                value=payload.strip(seperator),
                inline=inline,
            )

    def get_user(self, username: str, guild: int = None):
        username = str(username)
        try:
            result = self.get_user_info(username, guild=guild)["username"]
        except CommandError:
            pass
        else:
            if result:
                username = result
            elif discord_regex.match(username):
                raise CommandError("User should set a last.fm account "
                                   f"using ``{self.prefix}username``")
        return self.get_last_account(username)["user"]

    def get_last_account(self, username: str):
        if self.user_reg.fullmatch(username):
            params = {
                "method": "user.getinfo",
                "user": username,
            }
            user_data = self.get_cached(params, cool_down=1800, item="user")
            return user_data
        raise CommandError("Invalid username format.")

    @staticmethod
    def get_user_info(target: str, guild: int = None):
        """
        Used to get a Discord user's information from the SQL server.

        Args:
            target: int/str
                The target user's Discord id or their name/alias.

        Return dict format:
            "user_id": int
                The user's Discord id.
            "username": 2 <= string <= 15
                The user's Last.FM username.
            "period": string [
                                'overall',
                                '7day',
                                '1month',
                                '3month',
                                '6month',
                                '12month',
                            ]
                The period which 'Top' commands should use.
            "guild": int
                The guild id used for alias lookup.
        """
        try:
            target = AT_to_id(target)
        except CommandError as e:
            if guild is not None and not isinstance(guild, bool):
                data = handle_sql(aliases.query.filter(
                    aliases.guild_id == guild,
                    aliases.alias.like(target)
                    ).first)
                if data:
                    target = data.user_id
                else:
                    raise CommandError("User alias not found.")
            elif isinstance(guild, bool):
                raise CommandError("User aliases aren't enabled in DMs.")
            else:
                raise e
        data = handle_sql(users.query.get, target)
        if data is None:
            user = users(user_id=target)
            handle_sql(db_session.add, user)
            handle_sql(db_session.flush)
            data = {"user_id": target, "username": None, "period": periods[0]}
        else:
            data = {
                "user_id": data.user_id,
                "username": data.last_username,
                "period": periods[data.period],
            }
        return data

    @staticmethod
    def search_embed(
            data: dict,
            index: int,
            names: list,
            name_format: str,
            values: list,
            value_format: str,
            item: str,
            url_index: list = ("url", ),
            limit: int = 5,
            **kwargs):  # "last"
        non_inlines = dict()
        if len(data) - index < limit:
            limit = len(data) - index
        for x in range(limit):
            current_index = index + x
            current_name = name_format[:].replace(
                "{}",
                str(current_index + 1),
                1,
            )
            current_value = value_format[:]
            for index_list in names:
                current_name = current_name.replace(
                    "{}",
                    get_dict_item(
                        data[current_index],
                        index_list
                    ),
                    1,
                )
            for index_list in values:
                current_value = current_value.replace(
                    "{}",
                    get_dict_item(
                        data[current_index],
                        index_list,
                    ),
                    1,
                )
            non_inlines[current_name] = current_value
        title = {
            "title": f"{item} results.",
            "url": get_dict_item(data[index], url_index),
        }
    #    if not kwargs.get("thumbnail"):
    #        name = data[index].get("name")
    #        kwargs["thumbnail"] = self.get_artwork(name, item)
        return bot.generic_embed_values(
            title=title,
            non_inlines=non_inlines,
            **kwargs,
        )

    def get_artwork(self, name, art_type):
        type_match = {
            "track": "release",
            "album": "release",
            "artist": "artist",
        }
        art_type = type_match.get(art_type.lower())
        if not (art_type and self.discogs_secret and self.discogs_key):
            return
        endpoint = "https://api.discogs.com/database/search"
        headers = {
            "Authorization": (f"Discogs key={self.discogs_key},"
                              f" secret={self.discogs_secret}"),
            "User-Agent": bot.local.api.user_agent,
            "Content-Type": "application/json",
        }
        params = {
            "query": name,
            "type": art_type,
        }
        try:
            r = get(endpoint, headers=headers, params=params)
        except requestCError as e:
            log.warning(e)
        else:
            if r.status_code < 400:
                data = r.json().get("results")
                data = (data[0].get("thumb") if data else data)
                return data
            log.warning(f"{r.status_code} returned "
                        f"by Discogs: {r.text}")

    @staticmethod
    def time_since(time_of_event: int):
        """
        A command used get the time passed since a unix time stamp
        and output it as a human readable string.
        """
        time_passed = Decimal(round(time()) - int(time_of_event))
        if time_passed < 0:
            payload = "[Unknown] "
        if time_passed < 60:  # a minute
            payload = f"[{time_passed} seconds ago] "
        elif time_passed < 3600:  # an hour
            time_formated = round(time_passed/60, 2)
            minutes = round(time_formated - (time_formated % 1), 0)
            seconds = format(int(round(time_formated % 1 * 60, 0)), "02d")
            payload = f"[{minutes}.{seconds} minutes ago] "
        elif time_passed < 86400:  # a day
            time_formated = round(time_passed/3600, 2)
            minutes = round(time_formated - (time_formated % 1), 0)
            seconds = format(int(round(time_formated % 1 * 60, 0)), "02d")
            payload = f"[{minutes}.{seconds} hours ago] "
        elif time_passed < 2629800:  # an average month
            payload = f"[{round(time_passed/86400, 2)} days ago] "
        elif time_passed < 31557600:  # 365.25 days
            payload = f"[{round(time_passed/2629800, 2)} months ago] "
        else:
            payload = f"[{round(time_passed/31557600, 2)} years] "
        return payload
