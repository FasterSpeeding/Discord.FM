from time import time, strftime, gmtime
from json.decoder import JSONDecodeError
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
    redact, user_regex as discord_regex,
    exception_webhooks, time_since
)
from bot.util.react import generic_react
from bot.util.sql import periods

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
        bot.config.api.get(
            self,
            "discogs_secret",
            "discogs_key",
        )
        self.cache = {}
        self.cool_downs = {"fulluser": {}, "friends": []}
        self.s = Session()
        self.s.params = {
            "api_key": bot.config.api.last_key,
            "format": "json",
        }
        self.s.headers.update({
            "User-Agent": bot.config.api.user_agent,
            "Content-Type": "application/json",
        })
        self.BASE_URL = "https://ws.audioscrobbler.com/2.0/"

    def unload(self, ctx):
        bot.unload_help_embeds(self)
        super(fmPlugin, self).unload(ctx)

    @staticmethod
    def __check__():
        return bot.config.api.last_key

    @Plugin.schedule(60)
    def purge_cache(self):
        log.debug("Purging cache.")
        for url, cache_obj in self.cache.copy().items():
            if cache_obj.expire > time():
                del self.cache[url]

    @Plugin.command("add", "<alias:str...>", group="alias", metadata={"help": "last.fm"})
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
        if (len(alias) > 20 or sanitize(alias, escape_codeblocks=True) != alias
                or alias.isdigit()):
            return api_loop(
                event.channel.send_message,
                ("Aliasas are limited to 20 characters and cannot "
                 "contain Discord's reserved special characters or "
                 "consist purely of numbers."),
            )

        data = bot.sql(bot.sql.aliases.query.filter(
            bot.sql.aliases.guild_id == event.guild.id,
            bot.sql.aliases.alias.like(alias),
        ).first)
        if data is None:
            self.get_user(event.author.id)
            if (bot.sql(bot.sql.aliases.query.filter_by(
                user_id=event.author.id,
                guild_id=event.guild.id,
            ).count) < 5):
                if not bot.sql(bot.sql.guilds.query.get, event.guild.id):
                    bot.sql.add(bot.sql.guilds(guild_id=event.guild.id))
                payload = bot.sql.aliases(
                    user_id=event.author.id,
                    guild_id=event.guild.id,
                    alias=alias,
                )
                bot.sql.add(payload)
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
                bot.sql.delete(data)
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

    @Plugin.command("list", "[target:str...]", group="alias", metadata={"help": "last.fm"})
    def on_alias_list_command(self, event, target=None):
        """
        Used to get a list of a user's aliases in a guild.
        This command will default to the author.
        But will target another user if their ID, @ or nickname is passed.
        Returns a list of the target's alises.
        """
        if event.channel.is_dm:
            return api_loop(
                event.channel.send_message,
                "Alias commands are guild specific.",
            )
        target = self.get_user_info(target or event.author.id, event.channel)
        data = [alias for alias in target.aliases
                if alias.guild_id == event.guild.id]
        if data:
            member = event.guild.get_member(target.user_id)
            embed, _ = self.generic_user_data(
                target.user_id,
                title_template=(f"{member.name}'s aliases "
                                f"in {event.guild.name}"),
                fields=[{"name": str(index + 1), "value": alias.alias,
                         "inline": False} for index, alias in enumerate(data)],
                #  thumbnail={"url": member.user.avatar_url},
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
        fields = [
            {"name": "Listeners", "value": artist_info["stats"]["listeners"]},
            {"name": "Play Count", "value": artist_info["stats"]["playcount"]},
            {"name": "On-Tour", "value": str(bool(artist_info["ontour"]))},
        ]
        artist_embed = bot.generic_embed(
            title=artist_info["name"],
            url=artist_info["url"],
            thumbnail={"url": self.get_artwork(artist, "artist")},
            fields=[{**field, "inline": False} for field in fields],
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
        user = bot.sql(bot.sql.users.query.get, event.author.id)
        if not user or not user.friends:
            api_loop(
                event.channel.send_message,
                ("You don't have any friends, use "
                 f"``{bot.prefix}friends add`` to catch some."),
            )
        else:
            kwargs = {
                "title": f"{event.author} friends.",
                "url": (f"https://www.last.fm/user/{user.last_username}"
                        if user.last_username else None),
                "thumbnail": {"url": event.author.avatar_url},
            }
            data = [f.slave_id for f in user.friends]
            content, embed = self.friends_search(
                data,
                0,
                owner=event.author.id,
                **kwargs,
            )
            reply = api_loop(event.channel.send_message, content, embed=embed)
            if len(data) > 5 and not event.channel.is_dm:
                bot.reactor.init_event(
                    message=reply,
                    owner=event.author.id,
                    data=data,
                    index=0,
                    amount=5,
                    edit_message=self.friends_search,
                    **kwargs
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
        embed = bot.generic_embed(**kwargs)
        if len(data) - index < limit:
            limit = len(data) - index
        for x in range(limit):
            current_index = index + x
            while True:
                user = self.state.users.get(int(data[current_index]))
                user = str(user) if user else data[current_index]
                friend = self.get_user_info(data[current_index])
                if not friend.last_username:
                    bot.sql(bot.sql.friends.query.filter_by(
                        master_id=owner,
                        slave_id=data[current_index]
                    ).delete)
                    bot.sql.flush()
                    data.pop(current_index)
                    if current_index >= len(data):
                        finished = True
                        break
                else:
                    finished = False
                    break
            if finished:
                break
            friend = friend.last_username
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
                    data_map=("recenttracks", "track"),
                    artist_map=("artist", "#text"),
                    name_format=(f"raw:[{current_index + 1}]"
                                 f" {user} ({friend})", ),
                    value_format=("ago", "artist"),
                    value_clamps=("ago", ),
                    limit=limit,
                )
            except CommandError:
                embed.add_field(
                    name=f"[{current_index + 1}] {user}",
                    value=f"Unable to access Last.fm account `{friend}`.",
                    inline=False,
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
        target = self.get_user_info(target, event.channel)
        if not target.last_username:
            raise CommandError("Target user doesn't have "
                               "a Last.FM account setup.")
        target = target.user_id
        name = self.state.users.get(int(target))
        name = str(name) if name else target
        user = bot.sql(bot.sql.users.query.get, event.author.id)
        if not user:
            user = bot.sql.users(user_id=event.author.id)
            bot.sql.add(user)
        if not any([f.slave_id == target for f in user.friends]):
            if (event.channel.is_dm or not
                    event.channel.guild.get_member(target)):
                raise CommandError("User not found in this guild.")
            friendship = bot.sql.friends(
                master_id=event.author.id,
                slave_id=target,
            )
            bot.sql(user.friends.append, friendship)
            api_loop(
                event.channel.send_message,
                f"Added user ``{name}`` to friends list.",
            )
        else:
            friendships = [f for f in user.friends if f.slave_id == target]
            for friend_obj in friendships:
                bot.sql(user.friends.remove, friend_obj)
            api_loop(
                event.channel.send_message,
                f"Removed user ``{name}`` from friends list.",
            )
        bot.sql.flush()

    @Plugin.command(
        "artists",
        "<search:str...>",
        group="search",
        metadata={"help": "last.fm"},
        context={
            "method": "artist.search",
            "data_map": ("results", "artistmatches", "artist"),
            "artwork_type": "Artist",
            "react": "search_artist_react",
            "meta_type": "artist",
        })
    @Plugin.command(
        "albums",
        "<search:str...>",
        group="search",
        metadata={"help": "last.fm"},
        context={
            "method": "album.search",
            "data_map": ("results", "albummatches", "album"),
            "artwork_type": "Album",
            "react": "search_album_react",
            "meta_type": "album",
        })
    @Plugin.command(
        "tracks",
        "<search:str...>",
        group="search",
        metadata={"help": "last.fm"},
        context={
            "method": "track.search",
            "data_map": ("results", "trackmatches", "track"),
            "artwork_type": "Track",
            "react": "search_track_react",
            "meta_type": "track",
        })
    def on_search_command(
            self,
            event,
            search,
            method,
            data_map,
            artwork_type,
            react,
            meta_type):
        """
        Search for an item on Last.fm.
        """
        data = self.get_cached({
                "method": method,
                meta_type: search.lower(),
            },
            cool_down=3600,
        )
        data = get_dict_item(data, data_map)
        if data:
            thumbnail = {"url": self.get_artwork(search, artwork_type)}
            content, embed = getattr(self, react)(
                data,
                0,
                thumbnail=thumbnail,
            )
            reply = api_loop(event.channel.send_message, content, embed=embed)
            if len(data) > 5 and not event.channel.is_dm:
                bot.reactor.init_event(
                    message=reply,
                    data=data,
                    index=0,
                    amount=5,
                    edit_message=getattr(self, react),
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
            api_loop(event.channel.send_message, f"No {meta_type}s found.")

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

    @Plugin.command(
        "albums",
        "[username:str...]",
        group="top",
        metadata={"help": "last.fm"},
        context={
            "method": "user.gettopalbums",
            "meta_type": "album",
            "secondary_kwargs": {
                "data_map": ("topalbums", "album"),
                "name_format": ("playcount", "raw:plays"),
                "value_format": ("artist", ),
                "artist_map": ("artist", "name"),
            }
        })
    @Plugin.command(
        "artists",
        "[username:str...]",
        group="top",
        metadata={"help": "last.fm"},
        context={
            "method": "user.gettopartists",
            "meta_type": "artist",
            "secondary_kwargs": {
                "data_map": ("topartists", "artist"),
                "name_format": ("playcount", "raw:plays"),
            }
        })
    @Plugin.command(
        "tracks",
        "[username:str...]",
        group="top",
        metadata={"help": "last.fm"},
        context={
            "method": "user.gettoptracks",
            "meta_type": "track",
            "secondary_kwargs": {
                "data_map": ("toptracks", "track"),
                "name_format": ("playcount", "raw:plays"),
                "value_format": ("artist", ),
                "artist_map": ("artist", "name"),
            }
        })
    def on_top_items_command(
            self,
            event,
            method,
            meta_type,
            secondary_kwargs,
            username=None):
        """
        Get an account's top played item.
        This command will default to the author.
        But will target another user if their ID, @ or nickname is passed.
        Returns the top items of the target user's Last.FM account.
        """
        limit = 5
        if username is None:
            username = event.author.id
        period = self.get_period(event.author.id)
        fm_embed, lastname = self.generic_user_data(
            username,
            channel=event.channel,
            description=(f"Top {meta_type}s "
                         f"{self.beautify_period(period, over=True)}."),
        )
        params = {
            "method": method,
            "user": lastname,
            "limit": limit,
            "period": period,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            limit=limit,
            singular=False,
            **secondary_kwargs,
        )
        api_loop(event.channel.send_message, embed=fm_embed)

    @Plugin.command("period", "[period:str...]", group="top", metadata={"help": "last.fm"})
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
                user = bot.sql(bot.sql.users.query.get, event.author.id)
                if not user:
                    user = bot.sql.users(
                        user_id=event.author.id,
                        period={y: x for x, y in periods.items()}[period],
                    )
                    bot.sql.add(user)
                else:
                    user.period = {y: x for x, y in periods.items()}[period]
                    bot.sql.flush()
                api_loop(
                    event.channel.send_message,
                    ("Default period for 'top' commands updated"
                     f" to ``{self.beautify_period(period)}``."),
                )
            else:
                api_loop(
                    event.channel.send_message,
                    (f"Invalid argument, see ``{bot.prefix}"
                     "help top period`` for more details."),
                )
        else:
            period = self.get_period(event.author.id)
            api_loop(
                event.channel.send_message,
                ("Your default 'top' period is currently "
                 f"set to ``{self.beautify_period(period)}``."),
            )

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
            user = bot.sql(bot.sql.users.query.get, event.author.id)
            if user:
                user.last_username = username
                bot.sql.flush()
            else:
                user = bot.sql.users(
                    user_id=event.author.id,
                    last_username=username,
                )
                bot.sql.add(user)
            api_loop(
                event.channel.send_message,
                f"Username for ``{event.author}`` changed to ``{username}``.",
            )
        else:
            username = self.get_user_info(event.author.id).last_username
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
        fm_embed, username = self.generic_user_data(
            username,
            channel=event.channel,
        )
        params = {
            "method": "user.getrecenttracks",
            "user": username,
            "limit": 2
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            data_map=("recenttracks", "track"),
            artist_map=("artist", "#text"),
            name_format=("raw:Recent activity (", "ago", "raw:)"),
            value_format=("artist", ),
            singular=False,
            cool_down=30,
            limit=2,
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
        fm_embed, username = self.generic_user_data(
            username,
            channel=event.channel,
            description="Recent tracks",
        )
        params = {
            "method": "user.getrecenttracks",
            "user": username,
            "limit": limit,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            data_map=("recenttracks", "track"),
            artist_map=("artist", "#text"),
            name_format=("ago", ),
            value_format=("artist", ),
            limit=limit,
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
        fm_embed, username = self.generic_user_data(
            username,
            channel=event.channel,
        )
        message = api_loop(event.channel.send_message, "Searching for user.")
        period = self.get_period(event.author.id)
        params = {
            "method": "user.getrecenttracks",
            "user": username,
            "limit": 3,
            "period": period,
        }
        self.get_fm_secondary(
            embed=fm_embed,
            params=params,
            data_map=("recenttracks", "track"),
            artist_map=("artist", "#text"),
            name_format=("raw:Recent tracks", ),
            value_format=("ago", "artist"),
            value_clamps=("ago", ),
            limit=3,
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
            artist_map=("artist", "name"),
            data_map=("toptracks", "track"),
            name_format=("raw:Top tracks "
                         f"{self.beautify_period(period, over=True)}", ),
            value_format=("playcount", "artist"),
            value_clamps=("playcount", ),
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
            data_map=("topartists", "artist"),
            name_format=("raw:Top artists "
                         f"{self.beautify_period(period, over=True)}", ),
            value_format=("playcount", ),
            value_clamps=("playcount", ),
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
            artist_map=("artist", "name"),
            data_map=("topalbums", "album"),
            name_format=("raw:Top albums "
                         f"{self.beautify_period(period, over=True)}", ),
            value_format=("playcount", "artist"),
            value_clamps=("playcount", ),
            seperator="\n",
        )
        try:
            api_loop(
                message.edit,
                " ",
                embed=fm_embed,
            )
        except APIException as e:
            if e.code in (10003, 10005, 10008):
                return
            raise e

    def generic_user_data(
            self,
            username,
            title_template="{}",
            channel=None,
            **kwargs):
        user_data = self.get_user(username, channel)
        username = user_data["name"]
        if username is None:
            raise CommandError("User should set a last.fm account "
                               f"using ``{bot.prefix}username``")
        registered = strftime(
            "%Y-%m-%dT%H:%M:%S",
            gmtime(user_data["registered"]["#text"]),
        )
    #    author = {
    #        "name": title_template.format(user_data["name"]),
    #        "url": user_data["url"],
    #        "icon": user_data["image"][-1]["#text"],
    #    }
        fm_embed = bot.generic_embed(
            title=title_template.format(user_data["name"]),
            url=user_data["url"],
            thumbnail={"url": user_data["image"][-1]["#text"]},
            #  author=author,
            footer={"text": (f"{user_data['playcount']} scrobbles, "
                             f"registered:")},
            timestamp=registered,
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

    class cached_object:
        __slots__ = (
            "exists",
            "expire",
            "data",
            "error",
        )

        def __init__(self, exists, expire, data=None, error=None):
            self.exists = exists
            self.expire = expire
            self.data = data
            self.error = error

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
                    self.cache[url] = self.cached_object(
                        exists=True,
                        expire=time() + cool_down,
                        data=r.json(),
                    )
                return r.json()

            if r.status_code == 404:
                self.cache[url] = self.cached_object(
                    exists=False,
                    expire=time() + 1800,
                    error=f"404 - {item} doesn't exist.",
                )
                raise fmEntryNotFound(self.cache[url].error)
            log.warning(f"Last.FM threw error {r.status_code}: {r.text}")
            if bot.config.exception_webhooks:
                exception_webhooks(
                    self.client,
                    bot.config.exception_webhooks,
                    content=(f"Last.FM threw error {r.status_code}: "
                             f"```{redact(r.text)[:1950]}```"),
                )
            try:
                message = ": " + r.json().get("message", ".")
            except JSONDecodeError:
                message = "."
            else:
                message = redact(message)
            raise fmEntryNotFound(f"{r.status_code} - Last.fm threw "
                                  f"unexpected HTTP status code{message}")
        if self.cache[url].exists and time() <= self.cache[url].expire:
            return self.cache[url].data
        raise fmEntryNotFound(self.cache[url].error)

    class fm_format_mapping:
        @staticmethod
        def playcount(data, **kwargs):
            count = data.get("playcount")
            return str(count) if count else "?"

        @staticmethod
        def artist(data, artist_map, **kwargs):
            try:
                artist = get_dict_item(data, artist_map)
            except (IndexError, KeyError):
                artist = "Unset"
            return f"{artist} -"

        @staticmethod
        def ago(data, time_map=("date", "uts"), **kwargs):
            try:
                delta = str(time_since(get_dict_item(data, time_map)))
            except (IndexError, KeyError):
                delta = "Now"
            return delta.capitalize()

        @staticmethod
        def count(index, **kwargs):
            return str({index + 1})

        @staticmethod
        def raw(method, **kwargs):
            return method.split(":", 1)[1]

    def get_fm_secondary(
            self,
            embed,
            params,
            data_map,
            url=None,
            name_format=None,
            value_format=None,
            value_clamps=None,
            limit=4,
            inline=False,
            cool_down=300,
            seperator="\n",
            singular=True,
            end_value_map=("name", ),
            **kwargs):
        data = self.get_cached(params, url=url, cool_down=cool_down)
        if len(get_dict_item(data, data_map)) < limit:
            limit = len(get_dict_item(data, data_map))
        if limit != 0:
            name = ""
            value = ""
            for index in range(limit):
                position = get_dict_item(data, data_map)[index]
                if not singular or not name:
                    for method in (name_format or ()):
                        function = getattr(
                            self.fm_format_mapping,
                            method.split(":", 1)[0],
                        )
                        name += function(
                            index=index,
                            data=position,
                            method=method,
                            **kwargs,
                        ) + " "
                for method in (value_format or ()):
                    function = getattr(
                        self.fm_format_mapping,
                        method.split(":", 1)[0],
                    )
                    current = function(
                        index=index,
                        data=position,
                        method=method,
                        **kwargs,
                    )
                    if method.split(":", 1)[0] in (value_clamps or ()):
                        current = "[" + current + "]"
                    value += current + " "
                if not name:
                    name = "Unset"
                value += get_dict_item(position, end_value_map) + seperator
                if not singular:
                    embed.add_field(
                        name=f"{name.strip(' ')}:",
                        value=value.strip(seperator),
                        inline=inline,
                    )
                    name = ""
                    value = ""
        else:
            name = "None"
            value = "None"
        if singular or value == "None":
            embed.add_field(
                name=f"{name.strip(' ')}:",
                value=value.strip(seperator),
                inline=inline,
            )

    def get_user(self, username: str, channel = None):
        username = str(username)
        result = None
        try:
            result = self.get_user_info(username, channel)
        except CommandError:
            pass
        else:
            if result.last_username:
                username = result.last_username
            elif discord_regex.match(username):
                raise CommandError("User should set a last.fm account "
                                   f"using ``{bot.prefix}username``")
        if result and channel and ((channel.is_dm and result.user_id !=
                                    list(channel.recipients.keys())[0]) or
                (not channel.is_dm and not
                 channel.guild.get_member(result.user_id))):
            raise CommandError("User not found in this guild.")
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
    def get_user_info(target: str, channel = None):
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
            user_id = AT_to_id(target)
        except CommandError as e:
            if channel and not channel.is_dm:
                data = bot.sql(bot.sql.aliases.query.filter(
                    bot.sql.aliases.guild_id == channel.guild_id,
                    bot.sql.aliases.alias.like(target)
                    ).first)
                if data:
                    user_id = data.user_id
                else:
                    raise CommandError("User alias not found.")
            elif channel:
                raise CommandError("User aliases aren't enabled in DMs.")
            else:
                raise e
        data = bot.sql(bot.sql.users.query.get, user_id)
        if data is None:
            return bot.sql.users(
                user_id=user_id,
            )
        return data

    @staticmethod
    def beautify_period(period, over=False):
        if period[0] != "1":
            period = period.replace("month", " months")
        else:
            period = period.replace("month", " month")
        if over:
            period = "over" + (" " + period).replace(" over", "")
        period = period.replace("day", " days")
        return period

    def get_period(self, user):
        user = self.get_user_info(user)
        period = periods.get(user.period, None)
        if period is None:
            period = periods.get(bot.config.api.default_period)
        return period

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
        fields = list()
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
            fields.append({
                "name": current_name,
                "value": current_value,
                "inline": False,
            })
    #    if not kwargs.get("thumbnail"):
    #        name = data[index].get("name")
    #        kwargs["thumbnail"] = self.get_artwork(name, item)
        return bot.generic_embed(
            title=f"{item} results.",
            url=get_dict_item(data[index], url_index),
            fields=fields,
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
            "User-Agent": bot.config.api.user_agent,
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
                return (data[0].get("thumb") if data else data)
            log.warning(f"{r.status_code} returned "
                        f"by Discogs: {r.text}")
