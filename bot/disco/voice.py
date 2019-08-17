from disco.bot import Plugin
from disco.util.logging import logging


from bot.base import bot
from bot.util.misc import api_loop

log = logging.getLogger(__name__)


class MusicPlugin(Plugin):
    def load(self, ctx):
        super(MusicPlugin, self).load(ctx)
        bot.load_help_embeds(self)

    def unload(self, ctx):
        bot.unload_help_embeds(self)
        super(MusicPlugin, self).unload(ctx)

    @Plugin.command("play", metadata={"help": "voice"})
    def on_play(self, event):
        """
        Voice has been temporarily disabled due to technical issues
        and will be back when it reaches a more stable condition.
        """
        api_loop(
            event.channel.send_message,
            ("Voice has been temporarily disabled due to technical issues"
             " and will be back when it's in more stable condition.")
        )
