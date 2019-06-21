from datetime import datetime
from decimal import Decimal
from time import time
from traceback import extract_stack


from disco.bot import Plugin
from disco.api.http import APIException
from disco.bot.command import CommandError, CommandEvent, CommandLevels
from disco.types.base import Unset
from disco.util.sanitize import S as sanitize
from disco.util.logging import logging
try:
    from ujson import load
except ImportError:
    from json import load


from bot import __GIT__, __VERSION__
from bot.base import bot
from bot.util.misc import api_key_regs, api_loop, dm_default_send
from bot.util.sql import db_session, guilds, users, handle_sql
from bot.util.status import status_handler, guildCount

log = logging.getLogger(__name__)


class CorePlugin(Plugin):
    def load(self, ctx):
        super(CorePlugin, self).load(ctx)
        self.status = status_handler(
            self,
            db_token=bot.local.api.dbl_token,
            gg_token=bot.local.api.discord_bots_gg,
            user_agent=bot.local.api.user_agent,
        )
        self.register_schedule(
            self.status.update_stats,
            300,
            init=False,
        )
        self.register_schedule(
            self.status.setup_services,
            60,
            repeat=False,
            init=False,
        )
        bot.local.get(
            self,
            "exception_dms",
            "exception_channels",
        )
        self.command_prefix = (bot.local.prefix or
                               bot.local.disco.bot.commands_prefix or
                               "fm.")
        bot.load_help_embeds(self)
        self.cool_down = {"prefix": {}}
        self.cache = {"prefix": {}}
        self.prefixes = {}
        try:
            for guild in handle_sql(guilds.query.all):
                self.prefixes[guild.guild_id] = guild.prefix
        except CommandError as e:
            log.critical("Failed to load data from guild data "
                         "from SQL servers, they're probably down.")
            log.exception(e.original_exception)

    def unload(self, ctx):
        bot.unload_help_embeds(self)
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
                    log.warning("Api exception caught while "
                                f"unloading Core module: {e}")
            del bot.reactor.events[event.message_id]
        super(CorePlugin, self).unload(ctx)

    @Plugin.listen("MessageCreate")
    def on_message_create(self, event):
        try:
            self.custom_prefix(event)
        except Exception as e:
            log.exception(e)

    @Plugin.listen("GuildCreate")
    def on_guild_join(self, event):
        if type(event.unavailable) is Unset:
            if handle_sql(
                    guilds.query.get, event.guild.id
                    ) is None:
                guild = guilds(
                    guild_id=event.guild.id,
                    last_seen=datetime.now().isoformat(),
                    name=event.guild.name,
                )
                db_session.add(guild)
                handle_sql(db_session.flush)
                self.prefixes[event.guild.id] = self.command_prefix

    @Plugin.listen("GuildUpdate")
    def on_guild_update(self, event):
        try:
            guild = handle_sql(guilds.query.get, event.guild.id)
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
                        guilds.query.filter_by(
                            guild_id=event.guild.id,
                        ).update,
                        {
                            "name": event.guild.name,
                            "last_seen": datetime.now().isoformat(),
                        },
                    )
                    handle_sql(db_session.flush)
        except CommandError as e:
            log.warning("Failed to update guild "
                        f"{event.guild.id} SQL entry: {e.msg}")
            log.exception(e.original_exception)

    @Plugin.listen("GuildDelete")
    def on_guild_leave(self, event):
        if type(event.unavailable) is Unset:
            guild = handle_sql(guilds.query.get, event.id)
            if guild:
                handle_sql(db_session.delete, guild)
                handle_sql(db_session.flush)

    @Plugin.command("reset guild", metadata={"help": "data"})
    def on_guild_purge(self, event):
        """
        Used to reset any custom guild data stored by the bot (e.g. prefix)
        """
        if event.channel.is_dm:
            return api_loop(
                    event.channel.send_message,
                    "This command cannot be used in the forbidden lands.",
                )
        member = event.guild.get_member(event.author)
        if member.permissions.can(8):  # admin
            guild = handle_sql(guilds.query.get, event.guild.id)
            if guild:
                handle_sql(db_session.delete, guild)
                handle_sql(db_session.flush)
                api_loop(
                    event.channel.send_message,
                    "Guild data removed.",
                )
                self.prefixes.pop(event.guild.id, None)
        else:
            api_loop(
                event.channel.send_message,
                "This command can only be used by server admins.",
            )

    @Plugin.listen("MessageReactionAdd")
    def on_reaction_listen(self, trigger_event):
        """
        React to message reaction add.
        """
        if not trigger_event.guild.get_member(trigger_event.user_id).user.bot:
            message_id = trigger_event.message_id
            event = bot.reactor.events.get(message_id, None)
            if event and time() < event.end_time and event.conditions:
                for condition in event.conditions:
                    if (not condition.auth or
                            trigger_event.user_id == condition.owner_id and
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
            elif event and time() > event.end_time:
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
                            content=("Missing permission required "
                                     "to clear message reactions "
                                     "``Manage Messages``."),
                        )
                    else:
                        raise e
                if message_id in bot.reactor.events:
                    del bot.reactor.events[message_id]

    @Plugin.command("help", "[command:str...]", metadata={"help": "miscellaneous"})
    def on_help_command(self, event, command=None):
        """
        Get a list of the commands in a module.
        If an argument is passed, this will return the command or module info.
        Otherwise, this will just return a list of all the enabled commands.
        """
        if not event.channel.is_dm:
            channel = api_loop(event.author.open_dm)
        else:
            channel = event.channel
        if command is None:  # _attrs may not work in 1.0.0
            for name, embed in bot.help_embeds.copy().items():
                level = CommandLevels._attrs.get(name, None)
                if level and level > self.bot.get_level(event.author):
                    continue
                dm_default_send(event, channel, embed=embed)
        else:
            if command.startswith(self.command_prefix):
                command = command[len(self.command_prefix):]
            author_level = self.bot.get_level(event.author)

            # Check for module match.
            embed = bot.help_embeds.get(command.lower())
            if embed:
                level = CommandLevels._attrs.get(command.lower(), None)
                if not level or level <= self.bot.get_level(event.author):
                    return dm_default_send(event, channel, embed=embed)

            # Check for command match.
            for command_obj in self.bot.commands:
                match = command_obj.compiled_regex.match(command)
                if (match and (not command_obj.level or
                               author_level >= command_obj.level)):
                    break
            if match:
                if command_obj.raw_args is not None:
                    args = " " + command_obj.raw_args + ";"
                else:
                    args = str()
                array_name = command_obj.metadata.get("metadata", None)
                if array_name:
                    array_name = array_name.get("help", None)
                if array_name:
                    docstring = command_obj.get_docstring()
                    docstring = docstring.replace("    ", "").strip("\n")
                    triggers = "("
                    trigger_base = str()
                    if command_obj.group:
                        trigger_base += command_obj.group + " "
                    for trigger in command_obj.triggers:
                        triggers += f"**{trigger_base}{trigger}** | "
                    triggers = triggers[:-3] + "):"
                    title = {
                        "title": (f"{self.command_prefix}{triggers}{args} "
                                  f"a command in the {array_name} module."),
                    }
                    embed = bot.generic_embed_values(
                        title=title,
                        description=docstring,
                    )
                    dm_default_send(event, channel, embed=embed)
            else:
                command = sanitize(command, escape_codeblocks=True)
                dm_default_send(
                    event,
                    channel,
                    content=f"``{command}`` command not found.",
                )
        user_info = handle_sql(users.query.get, event.author.id)
        if user_info is None or user_info.last_username is None:
            dm_default_send(
                event,
                channel,
                content=("To get started with this bot, you can set "
                         "your default last.fm username using the command "
                         f"``{self.command_prefix}username <username>``.")
            )

    @Plugin.command("invite", metadata={"help": "miscellaneous"})
    def on_invite_command(self, event):
        """
        Get a bot invite link from me.
        This command will send the author a bot invite link in a DM.
        """
        if not event.channel.is_dm:
            channel = event.author.open_dm()
        else:
            channel = event.channel
        dm_default_send(
            event,
            channel,
            content=(f"https://discordapp.com/oauth2/authorize?client_id="
                     f"{self.state.me.id}&scope=bot&permissions={104197184}")
        )

    @Plugin.command("vote", metadata={"help": "miscellaneous"})
    def on_vote_command(self, event):
        """
        Get a link to upvote this bot on Discordbots.org.
        """
        if not event.channel.is_dm:
            channel = event.author.open_dm()
        else:
            channel = event.channel
        dm_default_send(
            event,
            channel,
            content=("You can upvote me at https://"
                     "discordbots.org/bot/560984860634644482/vote"),
        )

    @Plugin.command("git", metadata={"help": "miscellaneous"})
    def on_git_command(self, event):
        """
        Get a link to this bot's github repo.
        """
        if not event.channel.is_dm:
            channel = event.author.open_dm()
        else:
            channel = event.channel
        dm_default_send(
            event,
            channel,
            content=f"You can find me (v{__VERSION__}) at {__GIT__}",
        )

    @Plugin.command("prefix", "[prefix:str...]", metadata={"help": "miscellaneous"})
    def on_prefix_command(self, event, prefix=None):
        """
        Set a custom guild bot prefix (Manage Guild).
        This command will default to displaying the current prefix
        and ignore perms if no args are given.
        """
        if not event.channel.is_dm:
            if prefix is None:
                guild = handle_sql(guilds.query.get, event.guild.id)
                if guild is None:
                    prefix = self.command_prefix
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
                    f"Current prefix is ``{prefix}``",
                )
            member = event.guild.get_member(event.author)
            if member.permissions.can(32):  # manage server
                if (event.guild.id not in self.cool_down["prefix"] or
                        self.cool_down["prefix"][event.guild.id] <= time()):
                    if handle_sql(guilds.query.get, event.guild.id) is None:
                        guild = guilds(
                            guild_id=event.guild.id,
                            last_seen=datetime.now().isoformat(),
                            name=event.guild.name,
                            prefix=prefix,
                        )
                        handle_sql(db_session.add, guild)
                    else:
                        handle_sql(
                            guilds.query.filter_by(
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
                        f"Prefix changed to ``{prefix}``",
                    )
                    self.cool_down["prefix"][event.guild.id] = time() + 60
                else:
                    cooldown = self.cool_down["prefix"][event.guild.id]
                    cooldown = round(Decimal(cooldown - time()))
                    return api_loop(
                        event.channel.send_message,
                        f"Cool down: {cooldown} seconds left."
                    )
            else:
                api_loop(
                    event.channel.send_message,
                    ("You need to have the Guild Manage "
                     "permission to use this command."),
                )
        else:
            api_loop(
                event.channel.send_message,
                "This command can only be used in guilds.",
            )

    @Plugin.command("support", metadata={"help": "miscellaneous"})
    def on_support_command(self, event):
        """
        Get Support server invite.
        """
        if not event.channel.is_dm:
            channel = event.author.open_dm()
        else:
            channel = event.channel
        dm_default_send(
            event,
            channel,
            content=("To join my support server, use "
                     "https://discordapp.com/invite/jkEXqVd"),
        )

    @Plugin.command("update sites", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_update_sites_command(self, event):
        """
        Manually post the bot's stats to the enabled bot listing sites.
        """
        payload = guildCount(len(self.client.state.guilds))
        if self.status.services:
            for service in self.status.services:
                self.status.post(service, payload)
            guilds = [service.__name__ for service in self.status.services]
            api_loop(
                event.channel.send_message,
                f"Updated stats on {guilds}.",
            )
        else:
            api_loop(
                event.channel.send_message,
                "No status sites are enabled in config.",
            )

    @Plugin.command("update presence", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_update_presence_command(self, event):
        """
        Manually update the bot's presence.
        """
        self.status.update_presence(len(self.client.state.guilds))
        api_loop(event.channel.send_message, ":thumbsup:")

    def custom_prefix(self, event):
        if event.author.bot:
            return

        if ((not hasattr(event, "channel") or event.channel is None) and
                not isinstance(event.guild_id, Unset)):
            guild = getattr(event, "guild", None)
            if guild is None:
                event.guild = self.client.state.guilds.get(
                    event.guild_id,
                    None,
                )
                if event.guild is None:
                    self.client.state.guilds[event.guild_id] = api_loop(
                        self.client.api.guilds_get,
                        event.guild_id,
                    )
                    event.guild = self.client.state.guilds[event.guild_id]
            event.channel = event.guild.channels.get(event.channel_id, None)
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

        if event.channel.is_dm:
            prefix = self.command_prefix
        else:
            prefix = self.prefixes.get(event.guild_id, None)
            if prefix is None:
                guild = handle_sql(guilds.query.get, event.guild_id)
                if guild is None:
                    prefix = self.command_prefix
                    self.prefixes[event.guild_id] = prefix
                    guild = guilds(
                        guild_id=event.guild_id,
                        last_seen=datetime.now().isoformat(),
                        prefix=prefix,
                    )
                    handle_sql(db_session.add, guild)
                    handle_sql(db_session.flush)
                else:
                    preifx = guild.prefix
                    self.prefixes[event.guild_id] = guild.prefix

        if event.message.content and event.message.content.startswith(prefix):
            prefix_len = len(prefix)
            if (len(event.message.content) > prefix_len and
                    event.message.content[prefix_len] == " "):
                prefix += " "
            commands = list(self.bot.get_commands_for_message(
                False,
                {},
                prefix,
                event.message,
            ))
            for command, match in commands:
                if not self.bot.check_command_permissions(command, event):
                    continue
                try:
                    command.plugin.execute(CommandEvent(command, event, match))
                except Exception as e:
                    self.exception_response(event, e)
                break

    def exception_response(self, event, e, respond: bool = True):
        if respond:
            if not isinstance(e, APIException) or e.code != 50013:
                api_loop(
                    event.channel.send_message,
                    ("Oops, looks like we've blown a fuse back "
                     "here. Our technicians have been alerted and "
                     "will fix the problem as soon as possible."),
                )
        strerror = str(e)
        for reg in api_key_regs:
            strerror = reg.sub("<REDACTED>", strerror)
        if self.exception_dms:
            if event.channel.is_dm:
                footer_text = "DM"
            else:
                footer_text = f"{event.guild.name}: {event.guild.id}"
            author = {
                "name": str(event.author),
                "icon": event.author.get_avatar_url(size=32),
                "author_url": ("https://discordapp.com/"
                               f"users/{event.author.id}"),
            }
            embed = bot.generic_embed_values(
                    author=author,
                    title={"title": f"Exception occured: {strerror}"},
                    description=event.message.content,
                    footer={"text": footer_text},
                    timestamp=event.message.timestamp.isoformat(),
                )
            for target in self.exception_dms.copy():
                target_dm = self.client.api.users_me_dms_create(target)
                try:
                    api_loop(target_dm.send_message, embed=embed)
                except APIException as e:
                    if e.code == 50013:
                        log.warning(f"Unable to exception dm: {target}")
                        self.exception_dms.remove(guild)
                    else:
                        raise e
        if self.exception_channels:
            embed = bot.generic_embed_values(
                    title={"title": f"Exception occured: {strerror}"},
                    description=extract_stack(),
                    footer={"text": event.message.content},
                )
            for guild, channel in self.exception_channels.copy().items():
                guild_obj = self.client.state.guilds.get(int(guild), None)
                if guild_obj is not None:
                    channel_obj = guild_obj.channels.get(channel, None)
                    if channel_obj is not None:
                        try:
                            api_loop(
                                channel_obj.send_message,
                                embed=embed,
                            )
                        except APIException as e:
                            if e.code == 50013:
                                log.warning("Unable to post in "
                                            f"exception channel: {channel}")
                                del self.exception_channels[guild]
                            else:
                                raise e
                    else:
                        log.warning(f"Invalid exception channel: {channel}")
                        del self.exception_channels[guild]
                else:
                    log.warning(f"Invalid exception guild: {guild}")
                    del self.exception_channels[guild]
        log.exception(e)
