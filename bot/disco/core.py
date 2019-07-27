from datetime import datetime
from time import time
from traceback import extract_stack
import psutil


from disco import VERSION as DISCO_VERSION
from disco.bot import Plugin
from disco.api.http import APIException
from disco.bot.command import CommandError, CommandEvent, CommandLevels
from disco.types.base import Unset
from disco.types.channel import ChannelType
from disco.types.permissions import Permissions
from disco.util.sanitize import S as sanitize
from disco.util.logging import logging


from bot import __GIT__
from bot.base import bot
from bot.util.misc import (
    api_loop, dm_default_send, exception_channels,
    exception_dms, redact
)

log = logging.getLogger(__name__)


class CorePlugin(Plugin):
    def load(self, ctx):
        super(CorePlugin, self).load(ctx)
        bot.load_help_embeds(self)
        self.process = psutil.Process()
        try:
            for guild in bot.sql(bot.sql.guilds.query.all):
                if guild.prefix is not None:
                    bot.prefix_cache[guild.guild_id] = guild.prefix
                else:
                    bot.prefix_cache[guild.guild_id] = bot.prefix
        except CommandError as e:
            log.critical("Failed to load guild data from SQL "
                         "servers, they're probably down.")
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
            except APIException as e:  # Unknown message, Missing permissions
                if e.code not in (10008, 50013):
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
        if isinstance(event.unavailable, Unset):
            guild = bot.sql(bot.sql.guilds.query.get, event.guild.id)
            if not guild or guild.prefix is None:
                bot.prefix_cache[event.guild.id] = bot.prefix
            else:
                bot.prefix_cache[event.guild.id] = guild.prefix

    @Plugin.listen("GuildDelete")
    def on_guild_leave(self, event):
        if isinstance(event.unavailable, Unset):
            bot.prefix_cache.pop(event.id, None)
            guild = bot.sql(bot.sql.guilds.query.get, event.id)
            if guild:
                bot.sql.delete(guild)

    @Plugin.command("guild", group="reset", metadata={"help": "miscellaneous"})
    def on_guild_purge(self, event):
        """
        Used to reset any custom guild data stored by the bot (e.g. prefix)
        """
        if event.channel.is_dm:
            return api_loop(
                    event.channel.send_message,
                    "This command cannot be used in DMs.",
                )
        member = event.guild.get_member(event.author)
        if member.permissions.can(Permissions.ADMINISTRATOR):
            guild = bot.sql(bot.sql.guilds.query.get, event.guild.id)
            if guild:
                bot.sql.delete(guild)
                api_loop(
                    event.channel.send_message,
                    "Guild data removed.",
                )
                bot.prefix_cache.pop(event.guild.id, None)
        else:
            api_loop(
                event.channel.send_message,
                "This command can only be used by server admins.",
            )

    @Plugin.command("user", group="reset", metadata={"help": "miscellaneous"})
    def on_user_reset_command(self, event):
        """
        Used to reset any user data stored by the bot (e.g. Last.fm username)
        """
        user = bot.sql(bot.sql.users.query.get, event.author.id)
        if user:
            bot.sql.delete(user)
            api_loop(event.channel.send_message, "Removed user data.")
        else:
            api_loop(
                event.channel.send_message,
                ":thumbsup: Nothing to see here.",
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
                            if e.code == 10008:  # Unknown message
                                if message_id in bot.reactor.events:
                                    del bot.reactor.events[message_id]
                                return

                            if e.code != 50013:  # Missing permissions
                                raise e
                        index = condition.function(
                            client=self,
                            message_id=message_id,
                            channel_id=event.channel_id,
                            reactor=condition.reactor,
                            **event.kwargs,
                            **condition.kwargs,
                        )
                        if (index is not None and
                                message_id in bot.reactor.events):
                            bot.reactor.events[
                                message_id
                            ].kwargs["index"] = index
                            event.end_time += 10
                        elif message_id in bot.reactor.events:
                            del bot.reactor.events[message_id]
            elif event and time() > event.end_time:
                try:
                    self.client.api.channels_messages_reactions_delete_all(
                        channel=event.channel_id,
                        message=message_id,
                    )
                except APIException as e:  # Unknown message, Missing permissions
                    if e.code not in (10008, 50013):
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
            if command.startswith(bot.prefix):
                command = command[len(bot.prefix):]
            author_level = self.bot.get_level(event.author)

            # Check for module match.
            embed = bot.help_embeds.get(command.lower())
            if embed:
                level = CommandLevels._attrs.get(command.lower(), None)
                if not level or level <= self.bot.get_level(event.author):
                    return dm_default_send(event, channel, embed=embed)

            # Check for command match.
            command_obj = None
            for command_obj in self.bot.commands:
                match = command_obj.compiled_regex.match(command)
                if (match and (not command_obj.level or
                               author_level >= command_obj.level)):
                    break

            if match:
                if command_obj.raw_args is not None:
                    args = " " + command_obj.raw_args + "; "
                else:
                    args = str()
                array_name = command_obj.metadata.get("metadata", None)
                if array_name:
                    array_name = array_name.get("help", None)
                if array_name:
                    docstring = command_obj.get_docstring()
                    docstring = docstring.replace("    ", "").strip("\n")
                    if command_obj.group:
                        triggers_formatted = command_obj.group + " ("
                    else:
                        triggers_formatted = "("

                    for trigger in command_obj.triggers:
                        triggers_formatted += f"**{trigger}** | "
                    triggers_formatted = triggers_formatted[:-3] + "):"
                    title = {
                        "title": (f"{bot.prefix}{triggers_formatted}{args} "
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
        user_info = bot.sql(bot.sql.users.query.get, event.author.id)
        if user_info is None or user_info.last_username is None:
            dm_default_send(
                event,
                channel,
                content=("To get started with this bot, you can set "
                         "your default last.fm username using the command "
                         f"``{bot.prefix}username <username>``.")
            )

    @Plugin.command("invite", metadata={"help": "miscellaneous"})
    def on_invite_command(self, event):
        """
        Get a bot invite link from me.
        This command will send the author a bot invite link in a DM.
        """
        api_loop(
            event.channel.send_message,
            ("https://discordapp.com/oauth2/authorize?client_id="
             f"{self.state.me.id}&scope=bot&permissions={104197184}"),
        )

    @Plugin.command("vote", metadata={"help": "miscellaneous"})
    def on_vote_command(self, event):
        """
        Get a link to upvote this bot on a bot listing site.
        """
        if not bot.config.vote_link:
            return api_loop(
                event.channel.send_message,
                "No vote link is currently setup."
            )

        api_loop(
            event.channel.send_message,
            f"You can upvote me at {bot.config.vote_link}",
        )

    @Plugin.command("git", metadata={"help": "miscellaneous"})
    def on_git_command(self, event):
        """
        Get a link to this bot's github repo.
        """
        api_loop(
            event.channel.send_message,
            f"You can find me at {__GIT__}",
        )

    @Plugin.command("prefix", "[prefix:str...]", metadata={"help": "miscellaneous"})
    def on_prefix_command(self, event, prefix=None):
        """
        Set a custom guild bot prefix (Manage Guild).
        This command will default to displaying the current prefix
        and ignore perms if no args are given.
        """
        if event.channel.is_dm:
            return api_loop(
                event.channel.send_message,
                "This command can only be used in guilds.",
            )
        if prefix is None:
            guild = bot.sql(bot.sql.guilds.query.get, event.guild.id)
            if not guild or guild.prefix is None:
                prefix = bot.prefix
            else:
                prefix = guild.prefix
            api_loop(
                event.channel.send_message,
                f"The prefix is set to ``{prefix}``",
            )
        else:
            member = event.guild.get_member(event.author)
            if not member.permissions.can(Permissions.MANAGE_GUILD):
                return api_loop(
                    event.channel.send_message,
                    ("You need to have Guild Manage "
                     "permission to use this command."),
                )

            guild = bot.sql(bot.sql.guilds.query.get, event.guild.id)
            if guild is None:
                guild = bot.sql.guilds(
                    guild_id=event.guild.id,
                    prefix=prefix,
                )
                bot.sql.add(guild)
            else:
                guild.prefix = prefix
            bot.sql.flush()
            bot.prefix_cache[event.guild.id] = prefix
            api_loop(
                event.channel.send_message,
                f"Prefix changed to ``{prefix}``",
            )

    @Plugin.command("support", metadata={"help": "miscellaneous"})
    def on_support_command(self, event):
        """
        Get Support server invite.
        """
        if not bot.config.support_invite:
            return api_loop(
                event.channel.send_message,
                "No support server is currently setup.",
            )

        api_loop(
            event.channel.send_message,
            f"To join my support server, use {bot.config.support_invite}",
        )

    @Plugin.command("_instance")
    def on_info_command(self, event):
        shard_id = self.bot.client.config.shard_id
        shard_count = self.bot.client.config.shard_count
        author = {
            "name": (f"Discord.FM: Shard {shard_id} of {shard_count}"),
            "icon": self.client.state.me.get_avatar_url(),
            "url": __GIT__,
        }
        start_date = datetime.fromtimestamp(self.process.create_time())
        uptime = datetime.now() - start_date
        uptime = ":".join(str(uptime).split(":")[:2])

        member_count = 0
        for guild in self.client.state.guilds.copy().values():
            member_count += guild.member_count

        online_count = 0
        for user in self.client.state.users.copy().values():
            if user.presence:
                online_count += 1
        online = f"\n{online_count} unique online" if online_count else ""

        other_count = text_count = voice_count = 0
        for channel in self.client.state.channels.copy().values():
            if channel.type == ChannelType.GUILD_TEXT:
                text_count += 1
            elif channel.type == ChannelType.GUILD_VOICE:
                voice_count += 1
            elif channel.type != ChannelType.DM:
                other_count += 1

        memory_usage = self.process.memory_full_info().uss / 1024**2
        cpu_usage = self.process.cpu_percent() / psutil.cpu_count()
        memory_percent = self.process.memory_percent()

        inline_fields = {
            "Guilds": str(len(self.client.state.guilds)),
            "Voice Instances": str(len(self.client.state.voice_clients)),
            "Uptime": uptime,
            "Process": (f"{memory_usage:.2f} MiB ({memory_percent:.0f}%)"
                        f"\n{cpu_usage:.2f}% CPU"),
            "Members": (f"{member_count} total\n"
                        f"{len(self.client.state.users)} unique" + online),
            "Channels": (f"{len(self.client.state.channels)} total\n"
                         f"{voice_count} voice\n{text_count} text\n"
                         f"{len(self.client.state.dms)} open "
                         f"DMs\n{other_count} other"),
        }
        footer = {
            "text": f"Made with Disco v{DISCO_VERSION}",
            "img": "http://i.imgur.com/5BFecvA.png",
        }
        embed = bot.generic_embed_values(
            author=author,
            inlines=inline_fields,
            footer=footer,
        )
        api_loop(event.channel.send_message, embed=embed)

    def custom_prefix(self, event):
        if event.author.bot:
            return

        if ((event.channel.is_dm and "DM" in bot.config.blacklist or
             bot.config.whitelist and event.guild_id not in bot.config.whitelist
             or bot.config.blacklist and event.guild_id in bot.config.blacklist)
                and event.author.id not in bot.config.uservetos):
            return

        if event.channel.is_dm:
            prefix = bot.prefix
        else:
            prefix = bot.prefix_cache.get(event.guild_id, None)
            if prefix is None:
                guild = bot.sql(bot.sql.guilds.query.get, event.guild_id)
                if not guild or guild.prefix is None:
                    prefix = bot.prefix
                    bot.prefix_cache[event.guild_id] = prefix
                else:
                    prefix = guild.prefix
                    bot.prefix_cache[event.guild_id] = guild.prefix

        require_mention = self.bot.config.commands_require_mention
        if not event.message.content.startswith(prefix):
            require_mention = True
            prefix = ""
        elif (len(event.message.content) > len(prefix) and
                event.message.content[len(prefix)] == " "):
            prefix += " "
        commands = list(self.bot.get_commands_for_message(
            require_mention,
            self.bot.config.commands_mention_rules,
            prefix,
            event.message,
        ))
        if not commands:
            return
        for command, match in commands:
            if not self.bot.check_command_permissions(command, event):
                continue
            try:
                command.plugin.execute(CommandEvent(command, event, match))
            except Exception as e:
                self.exception_response(event, e)
            break

    def exception_response(self, event, exception, respond: bool = True):
        if isinstance(exception, APIException) and exception.code == 50013:
            return

        if respond:
            api_loop(
                event.channel.send_message,
                ("Oops, looks like we've blown a fuse back "
                 "here. Our technicians have been alerted and "
                 "will fix the problem as soon as possible."),
            )

        strerror = redact(str(exception))
        if bot.config.exception_dms:
            if event.channel.is_dm:
                footer_text = "DM"
            else:
                footer_text = f"{event.guild.name}: {event.guild.id}"
            author = {
                "name": str(event.author),
                "icon": event.author.get_avatar_url(size=32),
                "url": ("https://discordapp.com/"
                        f"users/{event.author.id}"),
            }
            embed = bot.generic_embed_values(
                author=author,
                title={"title": f"Exception occured: {strerror}"},
                description=event.message.content,
                footer={"text": footer_text},
                timestamp=event.message.timestamp.isoformat(),
            )
            exception_dms(
                self.client,
                bot.config.exception_dms,
                embed=embed,
            )
        if bot.config.exception_channels:
            embed = bot.generic_embed_values(
                title={"title": f"Exception occured: {strerror}"},
                description=extract_stack(),
                footer={"text": event.message.content},
            )
            exception_channels(
                self.client,
                bot.config.exception_channels,
                embed=embed,
            )
        log.exception(exception)


def event_channel_guild_check(self, event):
    """
    Used to work around a bug with the etf encoder
    where certain guilds will stop returning
    Guild objects in Message Create Events at seemingly random intervals.
    """
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
