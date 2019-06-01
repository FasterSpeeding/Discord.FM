"""
The CLI module is a small utility that can be used as an easy entry point for
creating and running bots/clients.
"""
import os
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


def disco_main(run=False):
    """
    Creates an argument parser and parses a standard set of command line arguments,
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
    file_handler.setLevel(config.log_level.upper())
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
    disco_main(True) # KeyboardInterrupt
