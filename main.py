"""
The CLI module is a small utility that can be used as an easy entry point for
creating and running bots/clients.
"""
import os
import subprocess
import logging

from gevent import monkey

monkey.patch_all()


def disco_main():
    """
    Parse config.json
    creating a new :class:`Client`.
    Returns
    -------
    :class:`Client`
        A new Client from the provided command line arguments
    """
    from disco.cli import CONFIG_OVERRIDE_MAPPING
    from disco.client import Client, ClientConfig
    from disco.bot import Bot, BotConfig
    from disco.util.logging import setup_logging, LOG_FORMAT

    from bot.base import bot

    args = bot.config.disco

    # Create the base configuration object
    config = ClientConfig(args.to_dict())

    for arg_key, config_key in CONFIG_OVERRIDE_MAPPING.items():
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

    bot_config = BotConfig(args.bot.to_dict())
    bot_config.plugins += args.plugin
    return Bot(client, bot_config)


if __name__ == '__main__':
    from bot.base import bot
    disco = disco_main()
    try:
        disco.run_forever()
    except KeyboardInterrupt:
        log = logging.getLogger(__name__)
        log.info("Keyboard interrupt received, unloading plugins.")
        for plugin in disco.plugins.copy().values():
            log.info("Unloading plugin: " + plugin.__class__.__name__)
            disco.rmv_plugin(plugin.__class__)
            log.info("Successfully unloaded plugin: "
                     + plugin.__class__.__name__)
        bot.sql.flush()
