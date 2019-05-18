from datetime import datetime
from time import sleep
import threading


from disco.bot.command import CommandError
from disco.types.user import Game, Status, GameType
from disco.util.logging import logging
from requests import post, RequestException


from bot.util.sql import db_session, guilds, handle_sql

log = logging.getLogger(__name__)


def optional(**kwargs):
    return {index: data for index, data in kwargs.items() if data is not None}
# this is a dumpster fire, can't do positional


class api_basis:
    __name__ = "Unset"
    headers = {"Content-Type": "application/json"}
    payload = {}
    auth_header = "Authorization"

    def __init__(
            self,
            url: dict,
            auth: str,
            headers: dict = {},
            payload: dict = {}):
        self.url = self.url.format(**url)
        self.headers.update({**headers, self.auth_header: auth})
        self.payload.update(payload)


class discordbotsorg(api_basis):
    __name__ = "discordbots.org"
    url = "https://discordbots.org/api/bots/{id}/stats"

    def __call__(self, guildCount):
        return optional({
            "guildCount": guildCount.guildCount,
            "shardCount": guildCount.shardCount,
            "shardID": guildCount.shardId
        })


class discordbotsgg(api_basis):
    __name__ = "discord.bots.gg"
    url = "https://discord.bots.gg/api/v1/bots/{id}/stats"

    def __call__(self, guildCount):
        return optional({
            "server_count": guildCount.guildCount,
            "shards": guildCount.shardCount,
            "shard_id": guildCount.shardId
        })


class guildCount:
    def __init__(self, guildCount, shardCount=1, shardId=0):
        self.guildCount = guildCount,
        self.shardCount = shardCount,
        self.shardId = shardId


class status_thread_handler(object):
    def __init__(
            self,
            bot,
            interval=1800,
            db_token=None,
            gg_token=None,
            user_agent="Discord.FM"):  # better default user_agent
        self.bot = bot
        self.user_agent = user_agent
        self.interval = interval
        self.status_services = []
        self.__services__ = {
            db_token: discordbotsorg,
            gg_token: discordbotsgg
        }
        self.thread_end = False
        self.thread = threading.Thread(target=self.update_stats)
        self.thread.daemon = True
        self.thread.start()

    def update_stats(self):
        """
        This function updates the server amount status per interval
        and ensures the integrity of the guild data.
        """
        sleep(60)
        for token, object in self.__services__.items():
            if token is not None:
                self.status_services.append(
                    object(
                        url={"id": self.bot.state.me.id},
                        auth=token,
                        headers={"User-Agent": self.user_agent},
                    )
                )
        while True:
            guilds_len = len(self.bot.client.state.guilds)
            guilds_payload = guildCount(guilds_len)
            for service in self.status_services:
                try:
                    r = post(
                        service.url,
                        data=service(guilds_payload),
                        headers=service.headers,
                    )
                except RequestException as e:
                    log.warning("Failed to post server count to {}: {}".format(
                        service.__name__,
                        e,
                    ))
                else:
                    if r.status_code == 200:
                        log.info("Posted guild count ({}) to {}".format(
                            guilds_len,
                            service.__name__,
                        ))
                    else:
                        log.warning("Failed to post guild count to {} ({}): {}".format(
                            service.__name__,
                            r.status_code,
                            r.text,
                        ))
            self.bot.client.update_presence(
                Status.online,
                Game(
                    type=GameType.listening,
                    name="{} guilds.".format(guilds_len),
                )
            )
            guilds_copy = list(self.bot.client.state.guilds)[:]
            for guild in guilds_copy:
                try:
                    guild_object = self.bot.client.state.guilds.get(guild, None)
                    if guild_object is not None:
                        sql_guild = handle_sql(
                            db_session.query(guilds).filter_by(
                                guild_id=guild,
                            ).first,
                        )
                        if sql_guild is None:
                            sql_guild = guilds(
                                guild_id=guild,
                                last_seen=datetime.now().isoformat(),
                                name=guild_object.name,
                            )
                            handle_sql(db_session.add, sql_guild)
                        else:
                            try:
                                handle_sql(
                                    db_session.query(guilds).filter_by(
                                        guild_id=guild,
                                    ).update,
                                    {
                                        "last_seen": datetime.now().isoformat(),
                                        "name": guild_object.name
                                    },
                                )
                            except SQLexception as e:
                                log.warning(
                                    "Failed to post server to SQL server in status: {}".format(
                                        e.previous_exception)
                                )
                            else:
                                handle_sql(db_session.flush)
                except CommandError as e:
                    log.warning("Failed to call SQL server: {}".format(e.msg))
                    log.warning(str(e.original_exception))
                    break
            if self.thread_end:
                break
            sleep(self.interval)
