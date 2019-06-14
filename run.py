"""
The CLI module is a small utility that can be used as an easy entry point for
creating and running bots/clients.
"""
import os
import subprocess
import sys
import six
import logging

from gevent import monkey

monkey.patch_all()

# Mapping of argument names to configuration overrides
CONFIG_OVERRIDE_MAPPING = {
    'token': 'token',
    'shard_id': 'shard_id',
    'shard_count': 'shard_count',
    'max_reconnects': 'max_reconnects',
    'log_level': 'log_level',
    'manhole': 'manhole_enable',
    'manhole_bind': 'manhole_bind',
    'encoder': 'encoder',
}
log = logging.getLogger(__name__)


def disco_main(run=False):
    """
    Parse config.json
    creating a new :class:`Client`.
    Returns
    -------
    :class:`Client`
        A new Client from the provided command line arguments
    """
    from disco.client import Client, ClientConfig
    from disco.bot import Bot, BotConfig
    from disco.util.logging import setup_logging, LOG_FORMAT

    from bot.base import bot

    args = bot.local.disco

    if sys.platform == "linux" or sys.platform == "linux2":
        print("Sudo access may be required to keep youtube-dl up to date.")
        if (any("voice" in plugin for plugin in bot.local.disco.plugin) or
                any("voice" in plugin for plugin in bot.local.disco.bot.plugins)):
            try:
                subprocess.call([
                    "sudo",
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "youtube-dl",
                ])
            except FileNotFoundError as e:
                if e.filename == "sudo":
                    subprocess.call([
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--upgrade",
                        "youtube-dl",
                    ])
                else:
                    raise e
    else:
        print(f"System {sys.platform} may not "
              "be supported, Linux is suggested.")

    # Create the base configuration object
    if args.config:
        config = ClientConfig.from_file(args.config)
    else:
        config = ClientConfig(args.to_dict())

    for arg_key, config_key in six.iteritems(CONFIG_OVERRIDE_MAPPING):
        if getattr(args, arg_key) is not None:
            setattr(config, config_key, getattr(args, arg_key))

    # Setup the auto-sharder
    if args.shard_auto:
        from disco.gateway.sharder import AutoSharder
        AutoSharder(config).run()
        return

    # Setup logging based on the configured level

    if not os.path.exists("logs"):
        os.makedirs("logs")

    file_handler = logging.FileHandler("logs/bot.log")
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    file_handler.setLevel(args.file_log_level.upper())
    stream_handler = logging.StreamHandler()
    setup_logging(
        handlers=(file_handler, stream_handler),
        level=getattr(logging, config.log_level.upper()),
    )

    # Build out client object
    client = Client(config)

    # If applicable, build the bot and load plugins
    bot = None
    if args.run_bot or hasattr(config, 'bot'):
        bot_config = BotConfig(config.bot.to_dict()) if hasattr(config, 'bot') else BotConfig()
        if not hasattr(bot_config, 'plugins'):
            bot_config.plugins = args.plugin
        else:
            bot_config.plugins += args.plugin

        bot = Bot(client, bot_config)

    if run:
        (bot or client).run_forever()

    return (bot or client)


if __name__ == '__main__':
    from bot.util.sql import handle_sql, db_session
    disco = disco_main(False)
    try:
        disco.run_forever()
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received, unloading plugins.")
        for plugin in disco.plugins.copy().values():
            log.info("Unloading plugin: " + plugin.__class__.__name__)
            disco.rmv_plugin(plugin.__class__)
            log.info("Successfully unloaded plugin: " + plugin.__class__.__name__)
        handle_sql(db_session.flush)
