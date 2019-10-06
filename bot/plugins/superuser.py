from time import time
import re
import textwrap


from disco.api.http import APIException
from disco.bot import Plugin
from disco.bot.command import CommandError, CommandLevels
from disco.types.permissions import Permissions
from requests import get


from bot.base import bot
from bot.util.misc import api_loop, beautify_json, get_base64_image
from bot.util.sql import Filter_Status, filter_types
from bot.util.status import status_handler, guildCount


class superuserPlugin(Plugin):
    def load(self, ctx):
        super(superuserPlugin, self).load(ctx)
        bot.load_help_embeds(self)
        self.register_schedule(
            self.__check__,
            5,
            repeat=False,
            init=False,
        )
        presence = bot.config.presence.format(
            count="{count}",
            shardcount="{shardcount}",
            prefix=bot.prefix,
        )
        self.status = status_handler(
            self,
            db_token=bot.config.api.discordbots_org,
            gg_token=bot.config.api.discord_bots_gg,
            boats_token=bot.config.api.discordboats,
            user_agent=bot.config.api.user_agent,
            presence=presence,
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

    def unload(self, ctx):
        bot.unload_help_embeds(self)
        super(superuserPlugin, self).unload(ctx)

    def __check__(self):
        for plug in self.bot.plugins.copy().values():
            if issubclass(plug.__class__, self.__class__):
                continue

            if hasattr(plug, "__check__") and not plug.__check__():
                self.bot.rmv_plugin(plug.__class__)
                self.log.info(plug.__class__.__name__ +
                              " failed check and has been unloaded.")

    @Plugin.command("restart", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_restart_command(self, event):
        """
        Used to reload all the bot's modules.
        """
        api_loop(event.channel.send_message, "Restarting")
        self.log.info("Soft restart initiated.")
        self.register_schedule(
            self.restart,
            0,
            repeat=False,
            init=False,
        )

    def restart(self):
        for plugin in self.bot.plugins.copy().values():
            if not issubclass(plugin.__class__, self.__class__):
                self.log.info("Reloading plugin: " + plugin.__class__.__name__)
                plugin.reload()  # check this
                self.log.info("Successfully reloaded plugin: "
                              + plugin.__class__.__name__)

    @Plugin.command("shutdown", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_shutdown_command(self, event):
        """
        Used to unload all the bot's modules and end the script.
        """
        api_loop(event.channel.send_message, "Shutting down.")
        self.log.info("Soft shutdown initiated.")
        self.register_schedule(
            self.shutdown,
            0,
            repeat=False,
            init=False,
        )

    def shutdown(self):
        for plugin in self.bot.plugins.copy().values():
            if not issubclass(plugin.__class__, self.__class__):
                self.log.info("Unloading plugin: " + plugin.__class__.__name__)
                self.bot.rmv_plugin(plugin.__class__)
                self.log.info("Successfully unloaded plugin: "
                              + plugin.__class__.__name__)
            else:
                self.log.info("Caught self")
        bot.sql.flush()
        exit(0)

    @Plugin.command("unload", "<plugin_name:str>", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_plugin_unload(self, event, plugin_name):
        """
        Used to unload a specific plugin.
        """
        plugin = self.bot.plugins.get(plugin_name)
        if plugin is None:
            return api_loop(
                event.channel.send_message,
                f"{plugin_name} does not exist.",
            )

        self.bot.rmv_plugin(plugin.__class__)
        api_loop(event.channel.send_message, ":thumbsup:")

    @Plugin.command("reload", "<plugin_name:str>", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_plugin_reload(self, event, plugin_name):
        """
        Used to reload a specific plugin.
        """
        plugin = self.bot.plugins.get(plugin_name)

        if plugin is None:
            return api_loop(event.msg.reply, f"{plugin_name} does not exist.")

        self.bot.reload_plugin(plugin.__class__)
        api_loop(event.channel.send_message, ":thumbsup:")

    @Plugin.command("load", "<plugin:str>", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_plugin_load(self, event, plugin, plugin_location="bot.disco"):
        """
        Used to load a specific plugin. (Not working.)
        """
        try:
            self.bot.add_plugin_module(plugin)
        except Exception as e:
            api_loop(event.channel.send_message, str(e))
        else:
            api_loop(event.channel.send_message, ":thumbsup:")

    @Plugin.command("modules", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_modules_command(self, event):
        """
        Used to get a list of the currently loaded plugins.
        """
        api_loop(
            event.channel.send_message,
            str([plugin.name for plugin in self.bot.plugins.values()]),
        )

    @Plugin.command("except", "<message:str...>", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_except_command(self, event, message):
        """
        Used to test exception handling.
        """
        raise Exception(message)

    @Plugin.command("sites", level=CommandLevels.OWNER, group="update", metadata={"help": "owner"})
    def on_update_sites_command(self, event):
        """
        Manually post the bot's stats to the enabled bot listing sites.
        """
        if not self.status.services and self.status._tokens:
            self.status.setup_services()
        elif not self.status.services:
            return api_loop(
                event.channel.send_message,
                "No status sites are enabled in config.",
            )
        guild_count = len(self.client.state.guilds)
        shard_id = self.bot.client.config.shard_id
        shard_count = self.bot.client.config.shard_count
        payload = guildCount(guild_count, shard_count, shard_id)

        for service in self.status.services:
            self.status.post(service, payload)
        guilds = [service.__name__ for service in self.status.services]
        api_loop(
            event.channel.send_message,
            f"Updated stats on {guilds}.",
        )

    @Plugin.command("presence", level=CommandLevels.OWNER, group="update", metadata={"help": "owner"})
    def on_update_presence_command(self, event):
        """
        Manually update the bot's presence.
        """
        guild_count = len(self.client.state.guilds)
        shard_count = self.bot.client.config.shard_count
        payload = guildCount(guild_count, shard_count)
        self.status.update_presence(payload)
        api_loop(event.channel.send_message, ":thumbsup:")

    @Plugin.command("eval", level=CommandLevels.OWNER,
                    metadata={"help": "owner", "perms": Permissions.ATTACH_FILES})
    def on_eval_command(self, event):
        """
        Used to evaluate raw python3 code.
        The available classes are:
        "bot", "client", "config", "event", "plugins",
        "prefix_cache", "sql" and "state".
        To get an output, you have to assign the data to a variable
        with "out"/"output" being preferred over other variables.
        """
        ctx = {
            "bot": self.bot,
            "client": self.bot.client,
            "config": bot.config,
            "event": event,
            "plugins": self.bot.plugins,
            "prefix_cache": bot.prefix_cache,
            "sql": bot.sql,
            "state": self.bot.client.state,
        }
        response_block = "```python\n{}\n```"
        code = event.codeblock.replace("py\n", "").replace("python\n", "")
        code = (f"def func(ctx):\n  try:\n{textwrap.indent(code, '    ')}"
                "\n  finally:\n    ctx['results'] = locals()")
        attachments = None

        try:
            exec(code, ctx)
            ctx["func"](ctx)
        except Exception as e:
            response = response_block.format(
                (type(e).__name__ + ": " + str(e))
            )
        else:
            del ctx["results"]["ctx"]
            result = ctx["results"].get("output") or ctx["results"].get("out")
            if (not result and {key for key in ctx["results"]
                                if not key.startswith("_")}):
                result = list(ctx["results"].values())[0]  # assumptions have
            elif not result:  # been made about how python populates local()
                result = "None"
            response = response_block.format(str(result))
        if len(response) > 2000:
            attachments = [["the_full_response.txt", str(result)], ]
            response = ("It's dangerous to go without "
                        "the full response! Take this.")
        api_loop(event.channel.send_message, response, attachments=attachments)

    @Plugin.command(
        "blacklist",
        "<target:snowflake> [target_type:str]",
        level=CommandLevels.OWNER,
        metadata={"help": "owner"},
        context={"status": Filter_Status.map.BLACKLISTED})
    @Plugin.command(
        "whitelist",
        "<target:snowflake>  [target_type:str]",
        level=CommandLevels.OWNER,
        metadata={"help": "owner"},
        context={"status": Filter_Status.map.WHITELISTED})
    def add_to_filter(self, event, target, status, target_type="guild"):
        key, target  = filter_types.get(self.state, target, target_type)
        data, present = bot.sql.softget(
            bot.sql.filter, **{key: target})

        if present:
            if data.status.check(status):
                data.status.sub(status)
                api_loop(event.channel.send_message, "Target removed from list.")
            else:
                data.status.add(status)
                api_loop(event.channel.send_message, "Target added to list.")

            data.edit_status(data.status)
            bot.sql.flush()
        else:
            data.status.add(status)
            data.edit_status(data.status)
            bot.sql.add(data.filter)
            api_loop(event.channel.send_message, "Target added. :thumbsup:")

        if data.status.value == 0:
            bot.sql.filter.query.filter_by(
                target=data.filter.target,
                target_type=data.filter.target_type).delete()

    @Plugin.command(
        "query",
        "[target:snowflake] [target_type:str]",
        group="filter", level=CommandLevels.OWNER,
        metadata={"help": "owner"})
    def on_filter_query_command(self, event, target=None, target_type="guild"):
        """
        Used to retrieve the status of a guild or DMs in the filter.
        """
        if target:
            key, target = filter_types.get(self.state, target, target_type)
            data = bot.sql.softget(
                bot.sql.filter, **{key: target})[0].status.to_dict()
        else:
            data = {}
            status = bot.sql.filter._wrap(bot.sql.filter)
            for item, value in Filter_Status.map._all.items():
                data[item] = status.get_count(value)

            data["Total"] = bot.sql.filter.query.count()

        return api_loop(event.channel.send_message,
                        f"Current status:\n```json\n{beautify_json(data)}```")

    @Plugin.command("echo", "<payload:str...>", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_echo_command(self, event, payload):
        """
        Get's the bot to repeat a message.
        """
        api_loop(
            event.channel.send_message,
            payload,
        )

    @Plugin.command("permission check",
                    metadata={"help": "miscellaneous", "perms": bot.config.default_permissions})
    def on_permission_check(self, event):
        """
        Check if this bot has the right permissions in this channel.
        """
        api_loop(
            event.channel.send_message,
            "Looks good to me :thumbsup:",
        )

    @Plugin.command("ping", metadata={"help": "miscellaneous"})
    def on_ping_command(self, event):
        """
        Test delay command.
        Accepts no arguments.
        """
        websocket_ping = time()
        try:
            self.client.gw.ws.sock.ping()
        except Exception as e:
            self.log.warning(f"Websocket exception on ping: {e}")
            websocket_ping = None
        message_ping = time()
        bot_message = api_loop(
            event.channel.send_message,
            "***RADIO STATIC***",
        )
        message_ping = round((time() - message_ping) * 1000)
        if websocket_ping:
            websocket_ping = self.client.gw.ws.last_pong_tm - websocket_ping
            websocket_ping = round(websocket_ping * 1000)
        message = f"Pong! :ping_pong:\nAPI: {message_ping} ms"
        if websocket_ping and 0 < websocket_ping < 1000:
            message += f"\nGateway: {websocket_ping} ms "
        api_loop(
            bot_message.edit,
            message,
        )

    @Plugin.command("register error webhook", level=CommandLevels.OWNER,
                    metadata={"help": "owner", "perms": Permissions.MANAGE_WEBHOOKS})
    def on_register_error_webhook_command(self, event):
        """
        Used to register a webhook in the current channel for error messages.
        """
        #  attempt to get bot's current avatar as base64.
        url = self.state.me.get_avatar_url(still_format="png")
        try:
            avatar = get_base64_image(url)
        except Exception as e:
            self.log.warning(f"failed to get webhook image {e}")
            avatar = None

        #  create webhook
        try:
            webhook = api_loop(
                event.channel.create_webhook,
                self.state.me.username,
                avatar,
            )
        except (APIException, CommandError) as e:
            api_loop(
                event.channel.send_message,
                f"Unable to make webhook: ``{e.msg}``",
            )
        else:
            #  save webhook to config
            config = bot.get_config()
            if "exception_webhooks" not in config:
                config["exception_webhooks"] = {}
            config["exception_webhooks"][webhook.id] = webhook.token
            bot.config.exception_webhooks[webhook.id] = webhook.token
            bot.overwrite_config(config)
            api_loop(
                event.channel.send_message,
                f":thumbsup:",
            )

    @Plugin.command("register error dm", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_register_error_dm_command(self, event):
        """
        Used to register the current user's DMs for error messages.
        """
        if event.author.id in bot.config.exception_dms:
            api_loop(
                event.channel.send_message,
                f"You're already registered :ok_hand:",
            )
        else:
            config = bot.get_config()
            if "exception_dms" not in config:
                config["exception_dms"] = []
            config["exception_dms"].append(event.author.id)
            bot.overwrite_config(config)
            bot.config.exception_dms.append(event.author.id)
            api_loop(
                event.channel.send_message,
                f":thumbsup:",
            )

    @Plugin.command("steal", "<message:snowflake> [channel:snowflake]",
                    level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_steal_command(self, event, message, channel=None):
        if channel:
            channel = self.state.channels.get(channel)
        else:
            channel = event.channel
        if not channel:
            raise CommandError("Channel not found.")

        try:
            message = channel.get_message(message)
        except APIException as e:
            raise CommandError(str(e))

        animated_emojis = re.findall(r"<a:\w{2,}:\d+>", message.content)
        emojis = re.findall(r"<\w{2,}:\d+>", message.content)
        if not emojis and not animated_emojis:
            raise CommandError("No emojis found in message.")

        def get_emoji_info(emoji, file_type):
            name = re.search(r"\w{2,}", emoji).group()
            url = ("https://cdn.discordapp.com/emojis/" +
                   re.search(r"\d+", emoji).group() + f".{file_type}?v=1")
            return name, url

        results = {}
        for emoji in emojis:
            info = get_emoji_info(emoji, "png")
            results[info[0]] = info[1]

        for emoji in animated_emojis:
            info = get_emoji_info(emoji, "gif")
            results[info[0]] = info[1]

        exceptions = []
        for name, url in results.items():
            try:
                self.client.api.guilds_emojis_create(
                    bot.config.emoji_guild,
                    reason=f"Stolen from {channel.id}:{message.id}",
                    name=name,
                    image=get_base64_image(url),
                )
            except APIException as e:
                exceptions.append(str(e))

        if exceptions:
            return api_loop(
                event.channel.send_message,
                (f"{len(exceptions)} emoji(s) failed: ```python\n"
                 f"{[exception for exception in exceptions]}```")
            )

        api_loop(event.channel.send_message, f":thumbsup: ({len(results)})")
