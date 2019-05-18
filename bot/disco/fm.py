from decimal import Decimal
from re import compile
from time import time, strftime, gmtime
from urllib.parse import quote_plus


from disco.bot import Plugin
from disco.bot.command import CommandError
from disco.util.logging import logging
from disco.util.sanitize import S as sanitize
from requests import get
from urllib.parse import quote_plus


from bot.base.base import bot
from bot.util.misc import api_loop, AT_to_id, get_dict_item
from bot.util.react import generic_react
from bot.util.sql import aliases, db_session, handle_sql, friends, users

log = logging.getLogger(__name__)


class fmEntryNotFound(CommandError):
    """Last.fm entry not found."""


class fmPlugin(Plugin):
    def load(self, ctx):
        super(fmPlugin, self).load(ctx)
        bot.local.api.get(
            self,
            "last_key",
            "user_agent",
        )
        bot.init_help_embeds(self)
        bot.custom_prefix_init(self)
        self.user_reg = compile("[a-zA-Z0-9_-]+")
        self.mbid_reg = compile(
            "[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}",
        )
        self.replace_reg = compile("[{][}]")
        self.cache = {}
        self.cool_downs = {"fulluser": {}, "friends": []}

    def unload(self, ctx):
        pass

    @Plugin.command("alias set", "<alias:str...>")
    def on_alias_set_command(self, event, alias):
        """
        Last.fm Used to add or remove a user alias in a guild.
        Users are limited to 5 alises in a guild.
        Alises are limited to 20 characters and cannot contain Discord's reserved special characters (e.g. '@', '#').
        """
        if event.channel.is_dm:
            api_loop(event.channel.send_message, "Alias commands are guild specific.")
        else:
            if len(alias) > 20 or sanitize(alias) != alias:
                api_loop(
                    event.channel.send_message,
                    "Aliasas are limited to 20 characters and cannot contain Discord's reserved special characters.",
                )
            else:
                data = handle_sql(db_session.query(aliases).filter(
                    aliases.user_id == event.author.id,
                    aliases.guild_id == event.guild.id,
                    aliases.alias.like(alias),
                ).first)
                if data is None:
                    if (handle_sql(db_session.query(aliases).filter_by(
                        user_id=event.author.id,
                        guild_id=event.guild.id,
                    ).count) < 5):
                        payload = aliases(user_id=event.author.id, guild_id=event.guild.id, alias=alias)
                        payload.alias = alias  # THIS IS JUST FUCKING BROKEN AND I@M TOO PISSED OFF TO FIX IT
                        handle_sql(db_session.add, payload)
                        handle_sql(db_session.flush)
                        api_loop(
                            event.channel.send_message,
                            "Added alias ``{}``.".format(alias),
                        )
                    else:
                        api_loop(
                            event.channel.send_message,
                            "You've reached the 5 alias limit for this guild.".format(
                                data.alias,
                            ),
                        )
                else:
                    if data.user_id == event.author.id:
                        handle_sql(db_session.query(aliases).filter_by(
                            user_id=event.author.id,
                            guild_id=event.guild.id,
                            alias=data.alias,
                        ).delete)
                        handle_sql(db_session.flush)
                        api_loop(
                            event.channel.send_message,
                            "Removed alias ``{}``.".format(data.alias),
                        )
                    else:
                        api_loop(
                            event.channel.send_message,
                            "Alias ``{}`` is already taken in this guild.".format(data.alias),
                        )

    @Plugin.command("alias list", "[target:str...]")
    def on_alias_list_command(self, event, target=None):
        """
        Last.fm Used to get a list of a user's aliases in a guild.
        When no arguments are given, this will return the author's aliases.
        Otherwise, this accepts one argument (a target user's @, ID or alias) and will return a list of the target's alises.
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
                except CommandError as e:
                    data = handle_sql(db_session.query(aliases).filter(
                        aliases.guild_id == event.guild.id,
                        aliases.alias.like(target),
                    ).first)
                    if data is None:
                        raise CommandError("User alias not found in this guild.")
                    else:
                        target = data.user_id
            data = handle_sql(db_session.query(aliases).filter_by(
                user_id=target,
                guild_id=event.guild.id,
            ).all)
            user = self.client.api.guilds_members_get(event.guild.id, target)
            if len(data) != 0:
                inline = {
                    str(index + 1): alias.alias for
                    index, alias in enumerate(data)}
                embed = bot.generic_embed_values(
                    title="{}'s aliases in {}".format(
                        user.name,
                        event.guild.name,
                    ),
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

    @Plugin.command("artist info", "<artist:str...>")
    def on_artist_command(self, event, artist):
        """
        Last.fm Get an artist's info on Last.fm.
        """
        artist_info = self.get_artist(artist)
        inline = {
            "Listeners": artist_info["stats"]["listeners"],
            "Play Count": artist_info["stats"]["playcount"],
            "On-Tour": str(bool(artist_info["ontour"])),
            }
        artist_embed = bot.generic_embed_values(
            title=artist_info["name"],
            url=artist_info["url"],
            thumbnail=artist_info["image"][len(artist_info["image"]) - 1]["#text"],
            inlines=inline,
            skip_inlines="N/A",
        )
        api_loop(event.channel.send_message, embed=artist_embed)

    @Plugin.command("chart")
    def on_chart_command(self, event):
        raise CommandError("Not implemented yet, coming soon.")

    @Plugin.command("friends")
    def on_friends_command(self, event):
        """
        Last.fm Get a list of what your friends have recently listened to.
        Accepts no arguments.
        """
        data = handle_sql(db_session.query(friends).filter_by(
            master_id=event.author.id,
        ).all)
        if len(data) == 0:
            api_loop(
                event.channel.send_message,
                "You don't have any friends, use ``fm.friends add @`` to get some.",
            )
        else:
            data = [x.slave_id for x in data]
            content, embed = self.friends_search(
                data,
                0,
                author=event.author.id,
                title="{} friends.".format(event.author),
                thumbnail=event.author.avatar_url,
            )
            reply = api_loop(event.channel.send_message, embed=embed)
            if len(data) > 5 and not event.channel.is_dm:
                bot.reactor.init_event(
                    message=reply,
                    timing=30,
                    author=event.author.id,
                    data=data,
                    index=0,
                    amount=5,
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

    def friends_search(self, data, index, author, limit=5, **kwargs):
        embed = bot.generic_embed_values(**kwargs)
        if len(data) - index < limit:
            limit = len(data) - index
        for x in range(limit):
            current_index = index + x
            while True:
                user = self.state.users.get(int(data[current_index]))
                if user is not None:
                    user = str(user)
                else:
                    user = data[current_index]
                try:
                    friend = self.get_user_info(data[current_index])
                except CommandError:
                    handle_sql(
                        db_session.query(friends).filter_by(
                            master_id=author,
                            slave_id=data[current_index]).delete,
                        )
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
            limit = 2
            url = "https://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user={}&api_key={}&format=json&limit={}".format(
                friend["username"],
                self.last_key,
                limit,
            )
            try:
                self.get_fm_secondary(
                    embed=embed,
                    url=url,
                    name="[{}] {} ({})".format(
                        current_index + 1, user, friend["username"],
                    ),
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
                    name="[{}] {}".format(current_index + 1, user),
                    value=("Last.fm account `{}` was not found.".format(
                        friend["username"],
                    )),
                    inline=True,
                )
            if current_index >= len(data) - 1:
                break
        return None, embed

    @Plugin.command("friends add", "<friend:str>")
    def on_friends_add_command(self, event, friend):
        """
        Last.fm Add another user to your friends list.
        This command will either add the user if they're not in your friend's list or remove them otherwise
        and won't target users that haven't setup a last.fm username.
        This command accepts either a Discord user ID or @user
        """
        # friend = AT_to_id(friend)
        # username = self.get_user_info(friend, event.guild.id)["username"]
        friend = self.get_user_info(friend, event.guild.id)["user_id"]
        user = self.state.users.get(int(friend))
        if user is not None:
            user = str(user)
        else:
            user = friend
        friendship = handle_sql(
            db_session.query(friends).filter_by(
                master_id=event.author.id,
                slave_id=friend,
                ).first
            )
        if friendship is None:
            friendship = friends(master_id=event.author.id, slave_id=friend)
            handle_sql(db_session.add, friendship)
            api_loop(
                event.channel.send_message,
                "Added user ``{}`` to friends list.".format(friend),
            )
        else:
            handle_sql(
                db_session.query(friends).filter_by(
                    master_id=event.author.id,
                    slave_id=friend
                ).delete
            )
            api_loop(
                event.channel.send_message,
                "Removed user ``{}`` from friends list.".format(friend),
            )
        handle_sql(db_session.flush)

    @Plugin.command("search artist", "<artist:str...>")
    def on_search_artist_command(self, event, artist):
        """
        Last.fm Search for an artist on Last.fm.
        """
        artist_data = self.get_cached(
            "https://ws.audioscrobbler.com/2.0/?method=artist.search&artist={}&api_key={}&format=json".format(
                quote_plus(artist.lower()),
                self.last_key,
            ),
            cool_down=3600,
        )
        artist_data = artist_data["results"]["artistmatches"]["artist"]
        if len(artist_data) != 0:
            content, embed = self.search_artist_react(artist_data, 0)
            reply = api_loop(event.channel.send_message, embed=embed)
            if len(artist_data) > 5 and not event.channel.is_dm:
                bot.reactor.init_event(
                    message=reply,
                    timing=30,
                    data=artist_data,
                    index=0,
                    amount=5,
                    edit_message=self.search_artist_react,
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

    def search_artist_react(self, data, index, kwargs=None):
        return None, self.search_embed(
            data=data,
            index=index,
            names=(("name", ), ),
            name_format="[{}]: {}",
            values=(("listeners", ), ("mbid", )),
            value_format="Listeners: {}, MBID: {}",
            item="Artist"
        )

    @Plugin.command("search album", "<album:str...>")
    def on_search_album_command(self, event, album):
        """
        Last.fm Search for an album on Last.fm.
        """
        album_data = self.get_cached(
            "https://ws.audioscrobbler.com/2.0/?method=album.search&album={}&api_key={}&format=json&limit=30".format(
                quote_plus(album.lower()),
                self.last_key,
            ),
            cool_down=3600,
        )
        album_data = album_data["results"]["albummatches"]["album"]
        if len(album_data) != 0:
            content, embed = self.search_album_react(album_data, 0)
            reply = api_loop(event.channel.send_message, embed=embed)
            if len(album_data) > 5 and not event.channel.is_dm:
                bot.reactor.init_event(
                    message=reply,
                    timing=30,
                    data=album_data,
                    index=0,
                    amount=5,
                    edit_message=self.search_album_react,
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

    def search_album_react(self, data, index, kwargs=None):
        return None, self.search_embed(
            data,
            index=index,
            names=(("artist", ), ("name", )),
            name_format="[{}]: {} - {}",
            values=(("mbid", ), ),
            value_format="MBID: {}",
            item="Album",
        )

    @Plugin.command("search track", "<track:str...>")
    def on_search_track_command(self, event, track):
        """
        Last.fm Search for a track on Last.fm.
        """
        track_data = self.get_cached(
            "http://ws.audioscrobbler.com/2.0/?method=track.search&track={}&api_key={}&format=json&limit=30".format(
                quote_plus(track.lower()),
                self.last_key,
            ),
            cool_down=3600,
        )
        track_data = track_data["results"]["trackmatches"]["track"]
        if len(track_data) != 0:
            content, embed = self.search_track_react(track_data, 0)
            reply = api_loop(event.channel.send_message, embed=embed)
            if len(track_data) > 5 and not event.channel.is_dm:
                bot.reactor.init_event(
                    message=reply,
                    timing=30,
                    data=track_data,
                    index=0,
                    amount=5,
                    edit_message=self.search_track_react,
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

    def search_track_react(self, data, index, kwargs=None):
        return None, self.search_embed(
            data,
            index=index,
            names=(("artist", ), ("name", )),
            name_format="[{}]: {} - {}",
            values=(("listeners", ), ("mbid", )),
            value_format="Listeners: {}, MBID: {}",
            item="Track",
        )

    @Plugin.command("top albums", "[username:str...]")
    def on_top_albums_command(self, event, username=None):
        """
        Last.fm Get an account's top albums.
        If no argument is passed, this command will return the top albums of the author's set Last.FM account.
        Otherwise, this command accepts either a Discord user ID, user nickname or @user as a single argument.
        Returns the top albums of the target user's Last.FM account.
        """
        limit = 5
        if username is None:
            username = event.author.id
        period = self.get_user_info(event.author.id)["period"]
        fm_embed, lastname = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            title_template=("Top albums for {} over " +
                            (" " + period).replace(" over", "")),
            footer_text="Requested by {}".format(event.author),
            footer_img=event.author.get_avatar_url(size=32),
            timestamp=event.msg.timestamp.isoformat(),
        )
        url = "https://ws.audioscrobbler.com/2.0/?method=user.gettopalbums&user={}&api_key={}&format=json&limit={}&period={}".format(
            lastname,
            self.last_key,
            limit,
            period,
        )
        self.get_fm_secondary(
            embed=fm_embed,
            url=url,
            name="Album #{}",
            primary_index="topalbums",
            secondary_index="album",
            artists=True,
            entry_format="amount",
            limit=limit,
            inline=False,
        )
        api_loop(event.channel.send_message, embed=fm_embed)

    @Plugin.command("top artists", "[username:str...]")
    def on_top_artists_command(self, event, username=None):
        """
        Last.fm Get an account's top artists.
        If no argument is passed, this command will return the top artists of the author's set Last.FM account.
        Otherwise, this command accepts either a Discord user ID, nickname or @user as a single argument.
        Returns the top artists of the target user's Last.FM account.
        """
        limit = 5
        if username is None:
            username = event.author.id
        period = self.get_user_info(event.author.id)["period"]
        fm_embed, lastname = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            title_template=("Top artists for {} over" +
                            (" " + period).replace(" over", "")),
            footer_text="Requested by {}".format(event.author),
            footer_img=event.author.get_avatar_url(size=32),
            timestamp=event.msg.timestamp.isoformat(),
        )
        url = "https://ws.audioscrobbler.com/2.0/?method=user.gettopartists&user={}&api_key={}&format=json&limit={}&period={}".format(
            lastname,
            self.last_key,
            limit,
            period,
        )
        self.get_fm_secondary(
            embed=fm_embed,
            url=url,
            name="Artist #{}",
            primary_index="topartists",
            secondary_index="artist",
            entry_format="amount",
            limit=limit,
            inline=False,
        )
        api_loop(event.channel.send_message, embed=fm_embed)

    @Plugin.command("top period", "[period:str...]")
    def on_top_period_command(self, event, period=None):
        """
        Last.fm Used to set the default period for the 'top' group of commands.
        Accepts a string argument with the supported arguments being displayed allow.
            Overall
            7 days
            1 months
            3 months
            6 months
            12 months
        The argument isn't case sensative (capital letters don't matter) and spaces are ignored.
        If no arguments are passed, the command will respond with the author's current default period.
        """
        if period is not None:
            period = period.replace(" ", "").strip("s").lower()
            if period in (
                    "overall",
                    "7day",
                    "1month",
                    "3month",
                    "6month",
                    "12month"):
                data = self.get_user_info(event.author.id)
                handle_sql(
                    db_session.query(users).filter_by(
                        user_id=event.author.id,
                    ).update,
                    {"period": period},
                )
                handle_sql(db_session.flush)
                api_loop(
                    event.channel.send_message,
                    "Default period for 'top' commands updated to ``{}``.".format(period),
                )
            else:
                api_loop(
                    event.channel.send_message,
                    "Invalid argument, see ``fm.help top period`` for more details.",
                )
        else:
            data = self.get_user_info(event.author.id)
            api_loop(
                event.channel.send_message,
                "Your default 'top' period is currently set to ``{}``".format(data["period"]),
            )

    @Plugin.command("top tracks", "[username:str...]")
    def on_top_tracks_command(self, event, username=None):
        """
        Last.fm Get an account's top tracks.
        If no argument is passed, this command will return the top tracks of the author's set Last.FM account.
        Otherwise, this command accepts either a Discord user ID, nickname or @user as a single argument.
        Returns the top tracks of the target user's Last.FM account.
        """
        limit = 5
        if username is None:
            username = event.author.id
        period = self.get_user_info(event.author.id)["period"]
        fm_embed, lastname = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            title_template=("Top tracks for {} over " +
                            (" " + period).replace(" over", "")),
            footer_text="Requested by {}".format(event.author),
            footer_img=event.author.get_avatar_url(size=32),
            timestamp=event.msg.timestamp.isoformat(),
        )
        url = "https://ws.audioscrobbler.com/2.0/?method=user.gettoptracks&user={}&api_key={}&format=json&limit={}&period={}".format(
            lastname,
            self.last_key,
            limit,
            period,
        )
        self.get_fm_secondary(
            embed=fm_embed,
            url=url,
            name="Track #{}",
            primary_index="toptracks",
            secondary_index="track",
            artists=True,
            entry_format="amount",
            limit=limit,
            inline=False,
        )
        api_loop(event.channel.send_message, embed=fm_embed)

    @Plugin.command("username", "[username:str]")
    def on_username_command(self, event, username:str=None):
        """
        Last.fm Set user default last.fm account.
        This command accepts a username that fits Last.FM's username format as of 2019/04/11 and will assign that as the author's Last.FM account.
        If no arguments are passed, it will return the author's assigned Last.FM username.
        """
        if username is not None:
            username = self.get_last_account(username)["user"]["name"]
            handle_sql(
                db_session.query(users).filter_by(
                    user_id=event.author.id,
                ).update,
                {"last_username": username},
            )
            handle_sql(db_session.flush)
            api_loop(
                event.channel.send_message,
                "Username for ``{}`` changed to ``{}``.".format(event.author, username),
            )
        else:
            try:
                current_username = self.get_user_info(event.author.id)["username"]
            except CommandError:
                api_loop(
                    event.channel.send_message,
                    "Username not set for ``{}``".format(event.author),
                )
            else:
                api_loop(
                    event.channel.send_message,
                    "Username for ``{}`` currently set to ``{}``.".format(
                        event.author, current_username,
                    )
                )

    @Plugin.command("user", "[username:str...]", aliases=("np", "now"))
    def on_user_command(self, event, username=None):
        """
        Last.fm Get basic stats from last.fm account.
        If no argument is passed, this command will return the basic info of the author's set Last.FM account.
        Otherwise, this command accepts either a Discord user ID, nickname or @user as a single argument.
        Returns the basic info of the target user's Last.FM account.
        """
        if username is None:
            username = event.author.id
        fm_embed, username = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            footer_text="Requested by {}".format(event.author),
            footer_img=event.author.get_avatar_url(size=32),
            timestamp=event.msg.timestamp.isoformat(),
        )
        url = "https://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user={}&api_key={}&format=json&limit=3".format(
            username,
            self.last_key,
        )
        self.get_fm_secondary(
            embed=fm_embed,
            url=url,
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

    @Plugin.command("user recent", "[username:str...]", aliases=("recent", ))
    def on_user_recent_command(self, event, username=None):
        """
        Last.fm Get an account's recent tracks.
        If no argument is passed, this command will return the recent tracks of the author's set Last.FM account.
        Otherwise, this command accepts either a Discord user ID, nickname or @user as a single argument.
        Returns the recent tracks of the target user's Last.FM account.
        """
        limit = 5
        if username is None:
            username = event.author.id
        fm_embed, username = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            footer_text="Requested by {}".format(event.author),
            footer_img=event.author.get_avatar_url(size=32),
            timestamp=event.msg.timestamp.isoformat(),
        )
        url = "https://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user={}&api_key={}&format=json&limit={}".format(
            username,
            self.last_key,
            limit,
            )
        self.get_fm_secondary(
            embed=fm_embed,
            url=url,
            name="Track #{}",
            primary_index="recenttracks",
            secondary_index="track",
            artists=True,
            artist_name="#text",
            entry_format="ago",
            limit=limit,
            inline=False,
            cool_down=120,
        )
        api_loop(event.channel.send_message, embed=fm_embed)

    @Plugin.command("user full", "[username:str...]")
    def on_user_full_command(self, event, username=None):
        """
        Last.fm Get stats from a last.fm account.
        If no argument is passed, this command will return the stats of the author's set Last.FM account.
        Otherwise, this command accepts either a Discord user ID, nickname or @user as a single argument.
        Returns the stats of the target user's Last.FM account.
        """
        if username is None:
            username = event.author.id
        test = time()
        fm_embed, username = self.generic_user_data(
            username,
            guild=(event.channel.is_dm or event.guild.id),
            footer_text="Requested by {}".format(event.author),
            footer_img=event.author.get_avatar_url(size=32),
            timestamp=event.msg.timestamp.isoformat(),
        )
        message = api_loop(event.channel.send_message, "Searching for user.")
        url = "https://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user={}&api_key={}&format=json&limit=3&period={}".format(
            username,
            self.last_key,
            self.get_user_info(event.author.id)["period"],
        )
        self.get_fm_secondary(
            embed=fm_embed,
            url=url,
            name="Recent tracks",
            primary_index="recenttracks",
            secondary_index="track",
            artists=True,
            artist_name="#text",
            entry_format="ago",
            seperator="\n",
            limit=3,
        )
        url = "https://ws.audioscrobbler.com/2.0/?method=user.gettoptracks&user={}&api_key={}&format=json&limit=3&period={}".format(
            username,
            self.last_key,
            self.get_user_info(event.author.id)["period"],
        )
        self.get_fm_secondary(
            embed=fm_embed,
            url=url,
            name="Top tracks",
            primary_index="toptracks",
            secondary_index="track",
            artists=True,
            entry_format="amount",
            seperator="\n",
        )
        url = "https://ws.audioscrobbler.com/2.0/?method=user.gettopartists&user={}&api_key={}&format=json&limit=3&period={}".format(
            username, self.last_key,
            self.get_user_info(event.author.id)["period"],
        )
        self.get_fm_secondary(
            embed=fm_embed,
            url=url,
            name="Top artists",
            primary_index="topartists",
            secondary_index="artist",
            entry_format="amount",
            seperator="\n",
        )
        url = "https://ws.audioscrobbler.com/2.0/?method=user.gettopalbums&user={}&api_key={}&format=json&limit=3&period={}".format(
            username,
            self.last_key,
            self.get_user_info(event.author.id)["period"],
        )
        self.get_fm_secondary(
            embed=fm_embed,
            url=url,
            name="Top albums",
            primary_index="topalbums",
            secondary_index="album",
            artists=True,
            entry_format="amount",
            seperator="\n",
        )
        fm_embed.set_footer(
            text="{} ms".format(round(Decimal(time() - test) * 1000)),
        )
        api_loop(message.edit, " ", embed=fm_embed)

#    @Plugin.command("user reset", "[username:str...]")
#    def on_user_reset_command(self, event):

    def generic_user_data(
            self,
            username,
            title_template="{}",
            guild=None,
            **kwargs):
        user_data = self.get_user(username, guild)
        username = user_data["name"]
        if username is None:
            raise CommandError("User should set a last.fm account using ``fm.username``")
        inline = {
            "Playcount": user_data["playcount"],
            "Registered": strftime(
                "%Y-%m-%d %H:%M",
                gmtime(user_data["registered"]["#text"]),
            ),
        }
        fm_embed = bot.generic_embed_values(
            title=title_template.format(user_data["name"]),
            url=user_data["url"],
            thumbnail=user_data["image"][len(user_data["image"]) - 1]["#text"],
            inlines=inline,
            skip_inlines="N/A",
            **kwargs,
        )
        return fm_embed, user_data["name"]

    def get_artist(self, artist: str):
        if self.mbid_reg.match(artist):
            url = "https://ws.audioscrobbler.com/2.0/?method=artist.getinfo&mbid={}&api_key={}&format=json".format(
                quote_plus(artist.lower()),
                self.last_key,
            )
        else:
            url = "https://ws.audioscrobbler.com/2.0/?method=artist.getinfo&artist={}&api_key={}&format=json".format(
                quote_plus(artist.lower()), self.last_key,
            )
        artist_data = self.get_cached(url, cool_down=3600, item="artist")
        return artist_data["artist"]

    def get_cached(self, url:str, cool_down:int=300, item:str="item"):
        if (url not in self.cache or self.cache[url].exists and
                time() >= self.cache[url].expire):
            r = get(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Content-Type": "application/json",
                }
            )
            if r.status_code == 200:
                if cool_down is not None:
                    self.cache[url] = type(
                        "cached_object",
                        (object, ),
                        {  #  proper class object
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
                    {  #  proper class object
                        "exists": False,
                        "expire": time(),
                        "data": None,
                        "error": "404 - {} doesn't exist.".format(item),
                    },
                )()
                raise fmEntryNotFound(self.cache[url].error)
            else:
                raise fmEntryNotFound("{} - Last.fm threw unexpected HTTP status code.".format(r.status_code))
        elif self.cache[url].exists and time() <= self.cache[url].expire:
            return self.cache[url].data
        else:
            raise fmEntryNotFound(self.cache[url].error)

    def get_fm_secondary(
            self,
            embed,
            url,
            name,
            primary_index,
            secondary_index,
            artists=None,
            artist_name="name",
            entry_format=None,
            limit=4,
            inline=True,
            cool_down=300,
            payload_prefix="",
            seperator="; "):
        data = self.get_cached(url, cool_down=cool_down)
        if len(data[primary_index][secondary_index]) < limit:
            limit = len(data[primary_index][secondary_index])
        payload = payload_prefix + ""
        if limit != 0:
            for index in range(limit):
                if entry_format is None:
                    pass
                elif entry_format == "ago":
                    if "date" in data[primary_index][secondary_index][index]:
                        payload += self.time_since_passed(
                            data[primary_index][secondary_index][index]["date"]["uts"]
                        )
                    else:
                        payload += "[Now] "
                elif entry_format == "amount":
                    payload += "[{}] ".format(
                        data[primary_index][secondary_index][index]["playcount"]
                    )
                if artists is not None:
                    payload += "{} - ".format(
                        data[primary_index][secondary_index][index]["artist"][artist_name]
                    )
                payload += "{}{}".format(
                    data[primary_index][secondary_index][index]["name"],
                    seperator,
                )
                if not inline:
                    embed.add_field(
                        name="{}:".format(name.format(index + 1)),
                        value=payload.strip(seperator),
                        inline=inline,
                    )
                    payload = str()
        else:
            payload = "None"
        if inline or payload == "None":
            embed.add_field(
                name="{}:".format(name),
                value=payload.strip(seperator),
                inline=inline,
            )

    def get_user(self, username:str, guild:int=None):
        username = self.get_user_info(username, guild=guild)["username"]
        username = quote_plus(username.lower())
        return self.get_last_account(username)["user"]

    def get_last_account(self, username:str):
        if self.user_reg.match(username) and 2 <= len(username) <= 15:
            url = "https://ws.audioscrobbler.com/2.0/?method=user.getinfo&user={}&api_key={}&format=json".format(
                username,
                self.last_key,
            )
            user_data = self.get_cached(url, cool_down=1800, item="user")
            return user_data
        else:
            raise CommandError("Invalid username format.")

    @Plugin.command("testicles", "<username:str...>")
    def on_testicles_command(self, event, username):
        return self.get_last_account(username)

    def get_user_info(self, target:str, guild:int=None):
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
                                '12month'
                            ]
                The period which 'Top' commands should use.
            "guild": int
                The guild id used for alias lookup.
        """
        try:
            target = AT_to_id(target)
        except CommandError as e:
            if guild is not None and not isinstance(guild, int):
                data = handle_sql(db_session.query(aliases).filter(
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
        data = handle_sql(db_session.query(users).filter_by(
            user_id=target,
        ).first)
        if data is None:
            user = users(user_id=target)
            handle_sql(db_session.add, user)
            handle_sql(db_session.flush)
            data = {"user_id": target, "username": None, "period": "overall"}
        else:
            data = {
                "user_id": data.user_id,
                "username": data.last_username,
                "period": data.period,
            }
        if data["username"] is None:
            raise CommandError("User should set a last.fm account using ``fm.username``")
        return data

    def search_embed(
            self,
            data:dict,
            index:int,
            names:list,
            name_format:str,
            values:list,
            value_format:str,
            item:str="item",
            url_index:list=("url", ),
            thumbnail_index:list=("image", -1, "#text"),
            limit:int=5,
            **kwargs):  # "last"
        non_inlines = dict()
        if len(data) - index < limit:
            limit = len(data) - index
        for x in range(limit):
            current_index = index + x
            braces = name_format.count("{}")
            current_name = self.replace_reg.sub(
                str(current_index + 1),
                name_format[:], 1,
            )
            current_value = value_format[:]
            for index_list in names:
                current_name = self.replace_reg.sub(
                    get_dict_item(
                        data[current_index],
                        index_list
                    ),
                    current_name,
                    1,
                )
            for index_list in values:
                current_value = self.replace_reg.sub(
                    get_dict_item(
                        data[current_index],
                        index_list,
                    ),
                    current_value,
                    1,
                )
            non_inlines[current_name] = current_value
        return bot.generic_embed_values(
            title="{} results.".format(item),
            url=get_dict_item(data[index], url_index),
            thumbnail=get_dict_item(data[index], thumbnail_index),
            non_inlines=non_inlines,
            **kwargs,
        )

    def time_since_passed(self, time_of_event:int):
        """
        A command used get the time passed since a unix time stamp
        and output it as a human readable string.
        """
        time_passed = Decimal(round(time()) - int(time_of_event))
        if time_passed < 0:
            payload = "[Unknown] "
        if time_passed < 60:  # a minute
            payload = "[{} seconds ago] ".format(time_passed)
        elif time_passed < 3600:  # an hour
            time_formated = round(time_passed/60, 2)
            payload = "[{}.{} minutes ago] ".format(
                round(time_formated - (time_formated % 1), 0),
                format(int(round(time_formated % 1 *60, 0)), "02d"),
            )  # int(x, 0)
        elif time_passed < 86400:  # a day
            time_formated = round(time_passed/3600, 2)
            payload = "[{}.{} hours ago] ".format(
                round(time_formated - (time_formated % 1), 0),
                format(int(round(time_formated % 1 *60, 0)), "02d"),
            )  # int(x, 0)
        elif time_passed < 2629800:  # an average month
            payload = "[{} days ago] ".format(round(time_passed/86400, 2))
        elif time_passed < 31557600:  # 365.25 days
            payload = "[{} months ago] ".format(round(time_passed/2629800, 2))
        else:
            payload = "[{} years] ".format(round(time_passed/31557600, 2))
        return payload
