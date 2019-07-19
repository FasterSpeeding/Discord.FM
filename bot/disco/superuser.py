from time import time


from disco.bot import Plugin
from disco.bot.command import CommandLevels
from disco.util.logging import logging


from bot.base import bot
from bot.util.misc import api_loop
from bot.util.status import status_handler, guildCount


log = logging.getLogger(__name__)


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
        self.status = status_handler(
            self,
            db_token=bot.config.api.discordbots_org,
            gg_token=bot.config.api.discord_bots_gg,
            user_agent=bot.config.api.user_agent,
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
                log.info(plug.__class__.__name__ +
                         " failed check and has been unloaded.")

    @Plugin.command("restart", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_restart_command(self, event):
        """
        Used to reload all the bot's modules.
        """
        api_loop(event.channel.send_message, "Restarting")
        log.info("Soft restart initiated.")
        self.register_schedule(
            self.restart,
            0,
            repeat=False,
            init=False,
        )

    def restart(self):
        for plugin in self.bot.plugins.copy().values():
            if not issubclass(plugin.__class__, self.__class__):
                log.info("Reloading plugin: " + plugin.__class__.__name__)
                plugin.reload()  # check this
                log.info("Successfully reloaded plugin: "
                         + plugin.__class__.__name__)

    @Plugin.command("shutdown", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_shutdown_command(self, event):
        """
        Used to unload all the bot's modules and end the script.
        """
        api_loop(event.channel.send_message, "Shutting down.")
        log.info("Soft shutdown initiated.")
        self.register_schedule(
            self.shutdown,
            0,
            repeat=False,
            init=False,
        )

    def shutdown(self):
        for plugin in self.bot.plugins.copy().values():
            if not issubclass(plugin.__class__, self.__class__):
                log.info("Unloading plugin: " + plugin.__class__.__name__)
                self.bot.rmv_plugin(plugin.__class__)
                log.info("Successfully unloaded plugin: "
                         + plugin.__class__.__name__)
            else:
                log.info("Caught self")
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
        self.status.update_presence(len(self.client.state.guilds))
        api_loop(event.channel.send_message, ":thumbsup:")

    @Plugin.command("eval", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_eval_command(self, event):
        """
        Used to evaluate raw python3 code.
        """
        ctx = {
            "bot": self.bot,
            "state": self.bot.client.state,
            "client": self.bot.client,
            "event": event,
            "sql": bot.sql,
            "config": bot.config,
        }
        response_block = "```python\n{}\n```"

        code = event.codeblock
        if (code.split("\n", 1)[0].count("python") or
                code.split("\n", 1)[0].count("py")):
            code = code.split("\n", 1)[1]

        try:
            result = eval(code, ctx)
        except Exception as e:
            response = response_block.format(
                (type(e).__name__ + ": " + str(e))[:1980]
            )
        else:
            response = response_block.format(str(result)[:1980])
        return api_loop(event.channel.send_message, response)

    @Plugin.command(
        "dms",
        aliases=("DMs", "dm", "DM",),
        group="block",
        level=CommandLevels.OWNER,
        metadata={"help": "owner"},
        context={"guild": "DM", "list": bot.config.blacklist})
    @Plugin.command(
        "blacklist",
        "<guild:snowflake>",
        level=CommandLevels.OWNER,
        metadata={"help": "owner"},
        context={"list": bot.config.blacklist})
    @Plugin.command(
        "whitelist",
        "<guild:snowflake>",
        level=CommandLevels.OWNER,
        metadata={"help": "owner"},
        context={"list": bot.config.whitelist})
    def on_filter_command(self, event, guild, list):
        """
        Used to add or remove an item from the guild/DM filter.
        """
        if guild in list:
            list.remove(guild)
            return api_loop(
                event.channel.send_message,
                "Guild removed from filter :ok_hand:",
            )
        if guild != "DM" and not self.client.state.guilds.get(guild):
            return api_loop(
                event.channel.send_message,
                "Guild not found :shrug:",
            )
        list.append(guild)
        api_loop(
            event.channel.send_message,
            "Guild added to filter :thumbsup:",
        )

    @Plugin.command("veto", "<target:snowflake>", group="filter", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_veto_command(self, event, target=None):
        """
        Used to whitelist a user from the guild/DM filter.
        """
        if not target:
            target = event.author.id
        if target in bot.config.uservetos:
            bot.config.uservetos.remove(target)
            api_loop(
                event.channel.send_message,
                f"User removed from veto list :ok_hand:",
            )
        else:
            bot.config.uservetos.append(target)
            api_loop(
                event.channel.send_message,
                f"User added to veto list :thumbsup:",
            )

    @Plugin.command("reset", group="filter", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_filter_reset(self, event):
        """
        Used to reset the guild filter (including the DM block).
        """
        bot.config.whitelist.clear()
        bot.config.blacklist.clear()
        api_loop(event.channel.send_message, ":thumbsup:")

    @Plugin.command(
        "dms",
        aliases=("DMs", "dm", "DM"),
        group="filter",
        level=CommandLevels.OWNER,
        metadata={"help": "owner"},
        context={"guild": "DM"})
    @Plugin.command("query", "[guild:snowflake]", group="filter", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_filter_query_command(self, event, guild=None):
        """
        Used to retrieve the status of a guild or DMs in the filter.
        """
        if guild:
            whitelisted = guild in bot.config.whitelist
            blacklisted = guild in bot.config.blacklist
            api_loop(
                event.channel.send_message,
                (f"Guild status:```Whitelisted: {whitelisted}\n"
                 f"Blacklisted: {blacklisted}```"),
            )
        else:
            api_loop(
                event.channel.send_message,
                (f"There are currently ``{len(bot.config.whitelist)}`` "
                 f"guilds whitelisted, and ``{len(bot.config.blacklist)}``"
                 " guilds blacklisted."),
            )

    @Plugin.command("echo", "<payload:str...>", level=CommandLevels.OWNER, metadata={"help": "owner"})
    def on_echo_command(self, event, payload):
        """
        Get's the bot to repeat a message.
        """
        api_loop(
            event.channel.send_message,
            payload,
        )

    @Plugin.command("ping", metadata={"help": "miscellaneous"})
    def on_ping_command(self, event):
        """
        Test delay command.
        Accepts no arguments.
        """
        init_time = time()
        bot_message = api_loop(
            event.channel.send_message,
            "***RADIO STATIC***",
        )
        passed_time = time()
        api_loop(
            bot_message.edit,
            f"Pong! {round((passed_time - init_time) * 1000)} ms",
        )
