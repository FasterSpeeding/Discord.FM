from datetime import datetime
import logging


from disco.types.user import Game, Status, GameType
from requests import post, RequestException


from bot.base import optional
from bot.util.sql import (
    db_session, guilds, handle_sql,
    SQLexception,
)

log = logging.getLogger(__name__)


class api_basis:
    __name__ = "Unset"
    headers = {"Content-Type": "application/json"}
    payload = {}
    auth_header = "Authorization"

    def __init__(
            self,
            url: dict,
            auth: str,
            headers: dict = None,
            payload: dict = None):
        self.url = self.url.format(**url)
        self.headers = {
            **self.headers,
            self.auth_header: auth,
            **(headers or {}),
        }
        self.payload = {**self.payload, **(payload or {})}

    def to_dict(self):
        return self.__dict__


class discordbotsorg(api_basis):
    __name__ = "discordbots.org"
    url = "https://discordbots.org/api/bots/{id}/stats"

    def __call__(self, guildCount):
        return optional(**{
            "server_count": guildCount.Count,
            "shard_count": guildCount.shardCount,
            "shard_id": guildCount.shardId
        })


class discordbotsgg(api_basis):
    __name__ = "discord.bots.gg"
    url = "https://discord.bots.gg/api/v1/bots/{id}/stats"

    def __call__(self, guildCount):
        return optional(**{
            "server_count": guildCount.Count,
            "shards": guildCount.shardCount,
            "shard_id": guildCount.shardId
        })


class guildCount:
    def __init__(self, Count, shardCount=None, shardId=None):
        setattr(self, "Count", Count)
        setattr(self, "shardCount", shardCount)
        setattr(self, "shardId", shardId)


class status_handler(object):
    services = []

    def __init__(
            self,
            bot,
            db_token=None,
            gg_token=None,
            user_agent="Discord.FM",
            bot_id=None):
        self.bot = bot
        self.bot_id = bot_id
        self.user_agent = user_agent
        self.__tokens = {
            discordbotsorg: db_token,
            discordbotsgg: gg_token,
        }

    @staticmethod
    def post(service, guilds_payload):
        try:
            r = post(
                service.url,
                json=service(guilds_payload),
                headers=service.headers,
            )
        except RequestException as e:
            log.warning("Failed to post server count "
                        f"to {service.__name__}: {e}")
        else:
            if r.status_code == 200:
                log.debug("Posted guild count "
                          f"({guilds_payload.Count}) to {service.__name__}")
            else:
                log.warning("Failed to post guild count to "
                            f"{service.__name__} ({r.status_code}): {r.text}")

    def update_presence(self, guilds_len):
        self.bot.client.update_presence(
            Status.online,
            Game(
                type=GameType.listening,
                name=f"{guilds_len} guilds.",
            )
        )

    def setup_services(self):
        """
        this exists to counter the fact that state.me isn't present at start.
        """
        self.bot_id = (self.bot_id or self.bot.state.me.id)
        for obj, token in self.__tokens.items():
            if token is not None:
                self.services.append(obj(
                        url={"id": self.bot_id},
                        auth=token,
                        headers={"User-Agent": self.user_agent},
                ))

    def sql_guilds_refresh(self):
        for guild in self.bot.client.state.guilds.copy().keys():
            try:
                guild_object = self.bot.client.state.guilds.get(guild, None)
                if guild_object is not None:
                    sql_guild = handle_sql(guilds.query.get, guild)
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
                                guilds.query.filter_by(
                                    guild_id=guild,
                                ).update,
                                {
                                    "last_seen": datetime.now().isoformat(),
                                    "name": guild_object.name
                                },
                            )
                        except SQLexception as e:
                            log.warning("Failed to post server to SQL server "
                                        f"in status: {e.previous_exception}")
                        else:
                            handle_sql(db_session.flush)
            except SQLexception as e:
                log.warning(f"Failed to call SQL server: {e.msg}")
                log.warning(str(e.original_exception))
                break

    def update_stats(self):
        """
        This function updates the server amount status per interval
        and ensures the integrity of the guild data.
        """
        guilds_len = len(self.bot.client.state.guilds)
        guilds_payload = guildCount(guilds_len)
        self.update_presence(guilds_len)
        for service in self.services:
            self.post(service, guilds_payload)
        self.sql_guilds_refresh()
