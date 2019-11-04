from datetime import datetime
from traceback import extract_stack
import os
import psutil
import csv


from disco import VERSION as DISCO_VERSION
from disco.bot import Plugin
from disco.api.http import APIException
from disco.bot.command import CommandError, CommandEvent, CommandLevels
from disco.types.base import UNSET
from disco.types.channel import ChannelType
from disco.types.permissions import Permissions
from disco.util.sanitize import S as sanitize


from bot import __GIT__
from bot.base import bot
from bot.util.misc import (
    api_loop, dm_default_send, exception_webhooks,
    exception_dms, redact
)


class CorePlugin(Plugin):
    def load(self, ctx):
        super(CorePlugin, self).load(ctx)
        bot.load_help_embeds(self)
        self.process = psutil.Process()
        try:
            for guild in bot.sql(bot.sql.guilds.query.all):
                bot.prefix_cache[guild.guild_id] = guild.prefix

        except CommandError as e:
            self.log.critical("Failed to load guild data from SQL "
                              "servers, they're probably down.")
            log.exception(e.original_exception)

        if bot.config.monitor_usage:
            if not os.path.exists("data/status/"):
                os.makedirs("data/status/")
            self.register_schedule(
                self.log_stats,
                bot.config.monitor_usage,
                repeat=True,
                init=False,
            )
        if "Github repo" not in bot.config.about_links:
            bot.config.about_links["Github repo"] = __GIT__

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
                    self.log.warning("Api exception caught while "
                                     f"unloading Core module: {e}")
            del bot.reactor.events[event.message_id]
        super(CorePlugin, self).unload(ctx)

    @Plugin.listen("MessageCreate")
    def on_message_create(self, event):
        try:
            self.custom_prefix(event)
        except Exception as e:
            self.exception_response(event, e)
            self.log.exception(e)

    @Plugin.listen("GuildCreate")
    def on_guild_join(self, event):
        if event.unavailable is UNSET:
            guild = bot.sql(bot.sql.guilds.query.get, event.guild.id)
            bot.prefix_cache[event.guild.id] = guild.prefix if guild else None

    @Plugin.listen("GuildDelete")
    def on_guild_leave(self, event):
        if event.unavailable is UNSET:
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
        if self.client.state.users.get(trigger_event.user_id).bot:
            return

        message_id = trigger_event.message_id
        event = bot.reactor.events.get(message_id, None)
        if not event:
            return

        self_perms = trigger_event.channel.get_permissions(
            self.bot.client.state.me,
        )
        if event.del_check():
            if self_perms.can(int(Permissions.MANAGE_MESSAGES)):
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

            return

        condition = event.get_condition(trigger_event)
        if condition:
            if self_perms.can(int(Permissions.MANAGE_MESSAGES)):
                try:
                    self.client.api.channels_messages_reactions_delete(
                        channel=event.channel_id,
                        message=message_id,
                        emoji=trigger_event.emoji.name,
                        user=trigger_event.user_id,
                    )
                except APIException as e:
                    if e.code == 10008:  # Unknown message
                        if message_id in bot.reactor.events:
                            del bot.reactor.events[message_id]
                        return

                    if e.code != 50013:  # Missing permissions
                        raise e

            index = condition.function(
                client=self.client,
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

    @Plugin.command("help", "[command:str...]",
                    metadata={"help": "miscellaneous"})  # , "perms": Permissions.EMBED_LINKS})
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
        if command is None:
            for name, embed in bot.help_embeds.copy().items():
                level = getattr(CommandLevels, name.upper(), None)
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
                level = getattr(CommandLevels, command.upper(), None)
                if not level or level <= self.bot.get_level(event.author):
                    return dm_default_send(event, channel, embed=embed)

            # Check for command match.
            command_obj = None
            for command_obj in self.bot.commands:
                match = command_obj.compiled_regex.match(command)
                if (match and (not command_obj.level or
                               author_level >= command_obj.level)
                        and command_obj.metadata.get("help", None)):
                    break

            data = bot.generate_command_info(command_obj, all_triggers=True)
            if match and data:
                embed = bot.generic_embed(
                    title=data[0] + f" a command in the {data[3]} module.",
                    description=data[2],
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
        Get a link to invite me to a guild.
        """
        api_loop(
            event.channel.send_message,
            (f"https://discordapp.com/oauth2/authorize?client_id={self.state.me.id}"
             f"&scope=bot&permissions={bot.config.default_permissions}"),
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

            new_prefix = prefix if prefix != bot.prefix else None
            guild = bot.sql(bot.sql.guilds.query.get, event.guild.id)
            if guild is None and new_prefix is not None:
                guild = bot.sql.guilds(
                    guild_id=event.guild.id,
                    prefix=new_prefix,
                )
                bot.sql.add(guild)
            elif guild:
                guild.prefix = new_prefix
                bot.sql.flush()
            bot.prefix_cache[event.guild.id] = new_prefix
            api_loop(
                event.channel.send_message,
                f"Prefix changed to ``{prefix}``",
            )

    @Plugin.command("about", metadata={"help": "miscellaneous", "perms": Permissions.EMBED_LINKS})
    def on_info_command(self, event):
        """
        Get information about this bot's instance.
        """
        shard_id = self.bot.client.config.shard_id
        shard_count = self.bot.client.config.shard_count
        author = {
            "name": (f"Discord.FM: Shard {shard_id} of {shard_count}"),
            "icon_url": self.client.state.me.get_avatar_url(),
            "url": __GIT__,
        }
        start_date = datetime.fromtimestamp(self.process.create_time())
        uptime = datetime.now() - start_date
        uptime = ":".join(str(uptime).split(":")[:2])
        description = ""
        for name, link in bot.config.about_links.items():
            description += f"[{name}]({link})\n"

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

        fields = (
            ("Guilds", str(len(self.client.state.guilds))),
            ("Voice Instances", str(len(self.client.state.voice_clients))),
            ("Uptime", uptime),
            ("Process", (f"{memory_usage:.2f} MiB ({memory_percent:.0f}%)"
                         f"\n{cpu_usage:.2f}% CPU")),
            ("Users", (f"{member_count} total\n"
                       f"{len(self.client.state.users)} unique" + online)),
            ("Channels", (f"{len(self.client.state.channels)} total\n"
                          f"{voice_count} voice\n{text_count} text\n"
                          f"{len(self.client.state.dms)} open "
                          f"DMs\n{other_count} other")),
        )
        footer = {
            "text": f"Made with Disco v{DISCO_VERSION}",
            "icon_url": "http://i.imgur.com/5BFecvA.png",
        }
        embed = bot.generic_embed(
            author=author,
            description=description,
            fields=[{"name": field[0], "value": field[1], "inline": True}
                    for field in fields],
            footer=footer,
        )
        api_loop(event.channel.send_message, embed=embed)

    def log_stats(self):
        start_date = datetime.fromtimestamp(self.process.create_time())
        uptime = datetime.now() - start_date
        member_count = 0
        cached_member_count = 0
        for guild in self.client.state.guilds.copy().values():
            member_count += guild.member_count
            cached_member_count += len(guild.members)
        fields = {
            "Uptime": uptime.seconds,
            "Voice Instances": len(self.client.state.voice_clients),
            "Memory usage": self.process.memory_full_info().uss / 1024**2,
            "Memory %": self.process.memory_percent(),
            "CPU %": self.process.cpu_percent() / psutil.cpu_count(),
            "Guilds": len(self.client.state.guilds),
            "Users": len(self.client.state.users),
            "Member Count": member_count,
            "Cached Member Count": cached_member_count,
            "Channels": len(self.client.state.channels),
            "DMs": len(self.client.state.dms),
        }
        try:
            with open(f"data/status/{start_date}.csv", mode="a+") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=fields.keys())
                writer.writerow(fields)
        except (IOError, OSError) as e:
            self.log.warning(f"Unable to log status to csv: {e}")

    def custom_prefix(self, event):
        def get_prefix(event):
            if event.channel.is_dm:
                return bot.prefix

            #  check prefix cache return default prefix if is None
            prefix = bot.prefix_cache.get(event.guild_id, UNSET)
            if prefix is not UNSET:
                return bot.prefix if prefix is None else prefix

            #  check sql and cache value returned or default
            guild = bot.sql(bot.sql.guilds.query.get, event.guild_id)
            bot.prefix_cache[event.guild_id] = guild.prefix if guild else None
            return bot.prefix if not guild or guild.prefix is None else guild.prefix

        def get_missing_perms(PermissionValue, self_perms):
            perms = [perm for perm in Permissions.keys()
                     if (int(PermissionValue) & getattr(Permissions, perm))
                     == getattr(Permissions, perm)]
            return [perm for perm in perms
                    if not self_perms.can(getattr(Permissions, perm))]

        if event.author.bot:
            return

        prefix = get_prefix(event)
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

            if not event.channel.is_dm:
                self_perms = event.channel.get_permissions(
                    self.bot.client.state.me,
                )
                PermissionValue = command.metadata.get("perms", None)
                if PermissionValue and not self_perms.can(int(PermissionValue)):
                    return api_loop(
                        event.channel.send_message,
                        ("Missing permission(s) required to respond: `" +
                         f"{get_missing_perms(PermissionValue, self_perms)}`"),
                    )

            #  Enforce guild/channel and user whitelist.
            CStatus = bot.sql.softget(
                bot.sql.cfilter, channel=event.channel)
            AStatus = bot.sql.softget(bot.sql.cfilter, user=event.author)
            if (CStatus.blacklist_status() or AStatus.blacklist_status()
                    or not CStatus.whitelist_status()
                    or not AStatus.whitelist_status()):
                return

            command.plugin.execute(CommandEvent(command, event, match))
            break

    def exception_response(self, event, exception, respond: bool = True):
        if isinstance(exception, APIException) and exception.code == 50013:
            return

        if bot.config.no_exception_response:
            raise exception

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
                "icon_url ": event.author.get_avatar_url(size=32),
                "url": ("https://discordapp.com/"
                        f"users/{event.author.id}"),
            }
            embed = bot.generic_embed(
                author=author,
                title=f"Exception occured: {strerror}"[:256],
                description=event.message.content,
                footer={"text": footer_text},
                timestamp=event.message.timestamp.isoformat(),
            )
            exception_dms(
                self.client,
                bot.config.exception_dms,
                embed=embed,
            )
        if bot.config.exception_webhooks:
            embed = bot.generic_embed(
                title=f"Exception occured: {strerror}"[:256],
                description=extract_stack()[:2048],
                footer={"text": event.message.content},
            )
            exception_webhooks(
                self.client,
                bot.config.exception_webhooks,
                embeds=[embed.to_dict(), ],
            )
        self.log.exception(exception)
