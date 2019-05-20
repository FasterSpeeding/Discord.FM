from datetime import datetime
from decimal import Decimal
from time import time
from traceback import extract_stack
import os


from disco.bot import Plugin
from disco.api.http import APIException
from disco.bot.command import CommandError
from disco.types.base import Unset
from disco.util.logging import logging, LOG_FORMAT
try:
    from ujson import load 
except ImportError:
    from json import load


from bot.base.base import bot
from bot.util.misc import api_loop, dm_default_send
from bot.util.sql import db_session, guilds, users, handle_sql
from bot.util.status import status_thread_handler

#if not os.path.exists("logs"):
#    os.makedirs("logs")
log = logging.getLogger(__name__)
#file_handler = logging.FileHandler("logs/bot.log")
#file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
#log.addHandler(file_handler)


class CorePlugin(Plugin):
    def load(self, ctx):
        super(CorePlugin, self).load(ctx)
        bot.custom_prefix_init(self)
        self.status_thread = status_thread_handler(
            self,
            db_token=bot.local.api.dbl_token,
            gg_token=bot.local.api.discord_bots_gg,
            user_agent=bot.local.api.user_agent,
        )
        bot.local.get(
            self,
            "owners",
            "exception_dm",
            "exception_channel",
        )
        self.command_prefix = (bot.local.disco.bot.commands_prefix or "fm.")
        bot.init_help_embeds(self)
        self.cool_down = {"prefix": {}}
        self.cache = {"prefix": {}}
        self.prefixes = {}
        try:
            for guild in handle_sql(db_session.query(guilds).all):
                self.prefixes[guild.guild_id] = guild.prefix
        except CommandError as e:
            log.critical("Failed to load data from guild data from SQL servers, they're probably down.")
            log.exception(e.original_exception)

    def unload(self, ctx):
        self.status_thread.thread_end = True
        self.status_thread.thread.join()
        while bot.reactor.events:
            event = list(bot.reactor.events.values())[0]
            try:
                self.bot.client.api.channels_messages_reactions_delete_all(
                    channel=event.channel_id,
                    message=event.message_id,
                )
            except APIException as e:
                if e.code == 1008 or e.code == 50013:
                    pass
                else:
                    log.warning("Api exception caught while unloading Core module: {}".format(e))
            del bot.reactor.events[event.message_id]

    @Plugin.listen("MessageCreate")
    def on_message_create(self, event):
        try:
            self.custom_prefix(event)
        except Exception as e:
            log.exception(e)

    @Plugin.listen("GuildCreate")
    def on_guild_join(self, event):
        if type(event.unavailable) is Unset:
            if handle_sql(db_session.query(guilds).filter_by(
                guild_id=event.guild.id).first,
                    ) is None:
                guild = guilds(
                    guild_id=event.guild.id,
                    last_seen=datetime.now().isoformat(),
                    name=event.guild.name,
                )
                db_session.add(guild)
                handle_sql(db_session.flush)
                self.prefixes[event.guild.id] = (self.command_prefix or "fm.")

    @Plugin.listen("GuildUpdate")
    def on_guild_update(self, event):
        try:
            guild = handle_sql(db_session.query(guilds).filter_by(
                guild_id=event.guild.id,
            ).first)
            if guild is None:
                guild = guilds(
                    guild_id=event.guild.id,
                    last_seen=datetime.now().isoformat(),
                    name=event.guild.name,
                )
                handle_sql(db_session.add, guild)
                handle_sql(db_session.flush)
            else:
                if guild.name != event.guild.name:
                    handle_sql(
                        db_session.query(guilds).filter_by(
                            guild_id=event.guild.id,
                        ).update,
                        {
                            "name": event.guild.name,
                            "last_seen": datetime.now().isoformat(),
                        },
                    )
                    handle_sql(db_session.flush)
        except CommandError as e:
            log.warning("Failed to update guild {} SQL entry: {}".format(event.guild.id, e.msg))
            log.exception(e.original_exception)

    @Plugin.listen("GuildDelete")
    def on_guild_leave(self, event):
        if type(event.unavailable) is Unset:
            try:
                handle_sql(db_session.query(guilds).filter_by(
                    guild_id=event.id,
                ).delete)
                handle_sql(db_session.flush)
            except CommandError as e:
                log.warning("Failed to remove guild {} from SQL database: {}".format(event.id, e.msg))
                log.exception(e.original_exception)

    @Plugin.listen("MessageReactionAdd")
    def on_reaction_listen(self, trigger_event):
        """
        React to reaction add.
        """
        if not trigger_event.guild.get_member(trigger_event.user_id).user.bot:
            message_id = trigger_event.message_id
            if message_id in bot.reactor.events:
                event = bot.reactor.events[message_id]
                if time() < event.end_time:
                    if len(event.conditions) != 0:
                        for condition in event.conditions:
                            if (not condition.auth or trigger_event.user_id == condition.owner_id and
                                    trigger_event.emoji.name == condition.reactor):
                                try:
                                    self.client.api.channels_messages_reactions_delete(
                                        channel=event.channel_id,
                                        message=message_id,
                                        emoji=condition.reactor,
                                        user=condition.owner_id,
                                    )
                                except APIException as e:
                                    if e.code == 10008:
                                        if message_id in bot.reactor.events:
                                            del bot.reactor.events[message_id]
                                    else:
                                        #log.warning(e)
                                        raise e
                                else:
                                    index = condition.function(
                                        client=self,
                                        message_id=message_id,
                                        channel_id=event.channel_id,
                                        reactor=condition.reactor,
                                        **event.kwargs,
                                    )
                                    if index is not None:
                                        bot.reactor.events[
                                            message_id
                                        ].kwargs["index"] = index
                                        event.end_time += 6
                                    else:
                                        if message_id in bot.reactor.events:
                                            del bot.reactor.events[message_id]
                else:
                    try:
                        self.client.api.channels_messages_reactions_delete_all(
                            channel=event.channel_id,
                            message=message_id,
                        )
                    except APIException as e:
                        if e.code == 10008:
                            pass
                        elif e.code == 50013:
                            self.client.api.channels_messages_create(
                                channel=event.channel_id,
                                content="Missing permission required to clear message reactions ``Manage Messages``.",
                            )
                        else:
                            raise e
                    if message_id in bot.reactor.events:
                        del bot.reactor.events[message_id]

    @Plugin.command("help", "[command:str...]")
    def on_help_command(self, event, command=None):
        """
        Miscellaneous Get a list of the commands in a module.
        If arg is passed, will try to return the info for the relevant command.
        Otherwise, it will just return a list of all the enabled commands.
        """
        if not event.channel.is_dm:
            channel = api_loop(event.author.open_dm)
        else:
            channel = event.channel
        if command is None:
            for help_embed in bot.help_embeds.values():
                dm_default_send(event, channel, embed=help_embed)
        elif command in bot.commands_list:
            if bot.commands_list[command].raw_args is not None:
                args = " " + bot.commands_list[command].raw_args + ";"
            else:
                args = str()
            docstring = bot.commands_list[command].get_docstring().replace("    ", "").strip("\n")
            embed = bot.generic_embed_values(
                title="fm.{}{} a command in the {} module.".format(
                    str(bot.commands_list[command].triggers).replace("[", "(").replace("'", "**").replace(",", " |").replace("]", ")") + ":",
                    args,
                    docstring.split(" ", 1)[0]),
                url=bot.local.embed_values.url,
                description=docstring.split(" ", 1)[1],
                )
            dm_default_send(event, channel, embed=embed)
        else:
            dm_default_send(
                event,
                channel,
                content="``{}`` command not found.".format(command),
            )
        user_info = handle_sql(
            db_session.query(users).filter_by(user_id=event.author.id).first,
        )
        if user_info is None or user_info.last_username is None:
            dm_default_send(
                event,
                channel,
                content="To get started with this bot, you can set your default last.fm username using the command ``fm.username <username>``.",
            )

    @Plugin.command("invite")
    def on_invite_command(self, event):
        """
        Miscellaneous Get a bot invite link from me.
        This command will send the author a bot invite link in a DM.
        """
        if not event.channel.is_dm:
            channel = event.author.open_dm()
        else:
            channel = event.channel
        dm_default_send(
            event,
            channel,
            content="https://discordapp.com/oauth2/authorize?client_id={}&scope=bot&permissions={}".format(
                self.state.me.id,
                104197184,
            ),
        )

    @Plugin.command("vote")
    def on_vote_command(self, event):
        """
        Miscellaneous Get a link to upvote this bot on Discordbots.org
        """
        if not event.channel.is_dm:
            channel = event.author.open_dm()
        else:
            channel = event.channel
        dm_default_send(
            event,
            channel,
            content="You can upvote me at https://discordbots.org/bot/560984860634644482/vote"
        )

    @Plugin.command("prefix", "[prefix:str...]")
    def on_prefix_command(self, event, prefix=None):
        """
        Miscellaneous Set a custom guild bot prefix (Manage Guild).
        This command will default to displaying the current prefix
        and ignore perms if no args are given.
        """
        if not event.channel.is_dm:
            if prefix is None:
                guild = handle_sql(
                    db_session.query(guilds).filter_by(
                        guild_id=event.guild.id,
                    ).first,
                )
                if guild is None:
                    prefix = (self.command_prefix or "fm.")
                    guild = guilds(
                        guild_id=event.guild.id,
                        last_seen=datetime.now().isoformat(),
                        name=event.guild.name,
                    )
                    handle_sql(db_session.add, guild)
                    handle_sql(db_session.flush)
                else:
                    prefix = guild.prefix
                return api_loop(
                    event.channel.send_message,
                    "Current prefix is ``{}``".format(prefix),
                )
            user_perms = event.guild.get_member(
                event.author,
            ).permissions.to_dict()
            if user_perms["manage_guild"] or user_perms["administrator"]:
                if (event.guild.id not in self.cool_down["prefix"] or
                        self.cool_down["prefix"][event.guild.id] <= time()):
                    if handle_sql(
                        db_session.query(guilds).filter_by(
                            guild_id=event.guild.id
                        ).first,
                    ) is None:
                        guild = guilds(
                            guild_id=event.guild.id,
                            last_seen=datetime.now().isoformat(),
                            name=event.guild.name,
                            prefix=prefix,
                        )
                        handle_sql(db_session.add, guild)
                    else:
                        handle_sql(
                            db_session.query(guilds).filter_by(
                                guild_id=event.guild.id
                            ).update,
                            {
                                "name": event.guild.name,
                                "prefix": prefix
                            },
                        )
                    handle_sql(db_session.flush)
                    self.prefixes[event.guild.id] = prefix
                    api_loop(
                        event.channel.send_message,
                        "Prefix changed to ``{}``".format(prefix),
                    )
                    self.cool_down["prefix"][event.guild.id] = time() + 60
                else:
                    cooldown = self.cool_down["prefix"][event.guild.id]
                    return api_loop(
                        event.channel.send_message,
                        "Cool down: {} seconds left.".format(
                            round(Decimal(cooldown - time())),
                        ),
                    )
            else:
                api_loop(
                    event.channel.send_message,
                    "You need to have the Guild Manage permission to use this command.",
                )
        else:
            api_loop(
                event.channel.send_message,
                "This command can only be used in guilds.",
            )

    @Plugin.command("ping")
    def on_ping_command(self, event):
        """
        Miscellaneous Test delay command.
        Accepts no arguments.
        """
        bot_message = api_loop(
            event.channel.send_message,
            "***RADIO STATIC***",
        )
        message_time = bot_message.timestamp.timestamp()
        event_time = event.msg.timestamp.timestamp()
        api_loop(
            bot_message.edit,
            "Pong! {} ms".format(
                round(Decimal((message_time - event_time)*1000)),
            ),
        )

    @Plugin.command("support")
    def on_support_command(self, event):
        """
        Miscellaneous Get Support server invite.
        """
        if not event.channel.is_dm:
            channel = event.author.open_dm()
        else:
            channel = event.channel
        dm_default_send(
            event,
            channel,
            content="To join my support server, use https://discordapp.com/invite/jkEXqVd",
        )

    @Plugin.command("restart")
    def on_restart_command(self, event):
        if event.author.id in self.owners:
            api_loop(event.channel.send_message, "Restarting")
            log.info("Soft restart initiated.")
            # do restarting stuff

    @Plugin.command("shutdown")
    def on_shutdown_command(self, event):
        if event.author.id in self.owners:
            message = api_loop(event.channel.send_message, "Shutting down.")
            log.info("Soft shutdown initiated.")
            # do shutting down stuff

    def custom_prefix(self, event):
        if not event.author.bot:  # further investigation needed
            if ((not hasattr(event, "channel") or event.channel is None) and
                    not isinstance(event.guild_id, Unset)):
                if (event.guild_id in self.client.state.guilds and
                        event.channel_id in self.client.state.guilds[
                            event.guild_id
                        ].channels):
                    event.channel = self.client.state.guilds[
                        event.guild_id
                    ].channels[event.channel_id]
                else:
                    self.client.state.guilds[event.guild_id] = api_loop(
                        self.client.api.guilds_get,
                        event.guild_id,
                    )
                    event.guild = self.client.state.guilds[event.guild_id]
                    event.channel = self.client.state.guilds[event.guild_id].channels.get(
                        event.channel_id,
                        None,
                    )
                    if event.channel is None:
                        event.channel = api_loop(
                            self.client.api.channels_get,
                            event.channel_id,
                        )
            elif ((not hasattr(event, "channel") or event.channel is None) and
                    isinstance(event.guild_id, Unset)):
                event.channel = api_loop(
                    self.client.api.channels_get,
                    event.message.channel_id,
                )
            if isinstance(event.guild_id, Unset) and event.channel.is_dm:
                prefix = (self.command_prefix or "fm.")
            else:
                if event.guild_id not in self.prefixes:
                    guild = handle_sql(
                        db_session.query(guilds).filter_by(
                            guild_id=event.guild_id,
                        ).first,
                    )
                    if guild is None:
                        prefix = (self.command_prefix or "fm.")
                        self.prefixes[event.guild_id] = prefix
                        guild = guilds(
                            guild_id=event.guild_id,
                            last_seen=datetime.now().isoformat(),
                        )
                        handle_sql(db_session.add, guild)
                        handle_sql(db_session.flush)
                    else:
                        preifx = guild.prefix
                        self.prefixes[event.guild_id] = guild.prefix
                else:
                    prefix = self.prefixes[event.guild_id]
            if event.message.content[:len(prefix)] == prefix:
                if (len(event.message.content[len(prefix):]) > 0 and
                        event.message.content[len(prefix):][0] == " "):
                    prefix_len = len(prefix) + 1
                    message_dict = event.message.content[
                        prefix_len:
                    ].split(" ")
                else:
                    prefix_len = len(prefix)
                    message_dict = event.message.content[
                        prefix_len:
                    ].split(" ")
                if len(message_dict) == 0:
                    return
                command = message_dict[0]
                two_word_command = None
                if len(message_dict) > 1:
                    two_word_command = command + " " + message_dict[1]
                if (command in bot.commands_list or
                        two_word_command in bot.commands_list):
                    if two_word_command in bot.commands_list:
                        command = two_word_command
                    event.args = event.message.content[prefix_len:][
                        len(command):
                    ].split()
                    event.name = command
                    event.msg = event.message
                #    if ((not hasattr(event, "guild") or event.guild is None)
                #            and not isinstance(event.guild_id, Unset)):
                #        event.guild = self.client.state.guilds.get(
                #            event.guild_id,
                #            None,
                #        )
                #        if event.guild is None:
                        #    self.client.state.guilds[event.guild_id] = api_loop(
                        #        self.client.api.guilds_get,
                        #        event.guild_id,
                        #    )  # could use cached
                        #    event.guild = self.client.state.guilds[event.guild_id]
                    try:
                        bot.commands_list[command].execute(event)
                    except CommandError as e:
                        api_loop(event.channel.send_message, str(e))
                    except Exception as e:
                        self.exception_message(event, e)

    def exception_message(self, event, e, response:bool=True):
        if response:
            api_loop(
                event.channel.send_message,
                "Oops, looks like we've blown a fuse back here. Our technicians have been alerted and will fix the problem as soon as possible.",
            )
        if (self.owners is not None and len(self.owners) != 0 and
                self.exception_dm):
            dm = self.client.api.users_me_dms_create(int(self.owners[0]))
            if event.channel.is_dm:
                footer_text = "DM"
            else:
                footer_text = "{}: {}".format(event.guild.name, event.guild.id)
            embed = bot.generic_embed_values(
                author_name=str(event.author),
                author_icon=event.author.get_avatar_url(size=32),
                author_url="https://discordapp.com/users/{}".format(
                    event.author.id,
                ),
                title="Exception occured: {}".format(str(e)),
                description=event.message.content,
                footer_text=footer_text,
                timestamp=event.message.timestamp.isoformat(),
            )
            api_loop(dm.send_message, embed=embed)
        if self.exception_channel is not None:
            embed = bot.generic_embed_values(
                title="Exception occured: {}".format(str(e)),
                description=extract_stack(),
                footer_text=event.message.content,
            )
            self.client.api.channels_messages_create(
                self.exception_channel,
                embed=embed,
            )
        log.exception(e)
