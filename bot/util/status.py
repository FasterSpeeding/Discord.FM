import logging


from disco.types.user import Activity, Status, ActivityTypes
from requests import post, RequestException


from bot.base import optional

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
            "shard_id": guildCount.shardId,
        })


class discordbotsgg(api_basis):
    __name__ = "discord.bots.gg"
    url = "https://discord.bots.gg/api/v1/bots/{id}/stats"

    def __call__(self, guildCount):
        return optional(**{
            "server_count": guildCount.Count,
            "shards": guildCount.shardCount,
            "shard_id": guildCount.shardId,
        })


class discordboats(api_basis):
    __name__ = "discord.boats"
    url = "https://discord.boats/api/v2/bot/{id}"

    def __call__(self, guildCount):
        return optional(**{
            "server_count": guildCount.Count,
        })


class guildCount:
    __slots__ = (
        "Count",
        "shardCount",
        "shardId",
    )

    def __init__(self, Count, shardCount=None, shardId=None):
        setattr(self, "Count", Count)
        setattr(self, "shardCount", shardCount)
        setattr(self, "shardId", shardId)

    def to_dict(self):
        return {key.lower(): getattr(self, key, None)
                for key in self.__slots__}


class status_handler(object):
    services = []

    def __init__(
            self,
            bot,
            db_token=None,
            gg_token=None,
            boats_token=None,
            user_agent="Discord.FM",
            bot_id=None,
            presence="{count} guilds."):
        self.bot = bot
        self.bot_id = bot_id
        self.user_agent = user_agent
        self.presence = presence
        self._tokens = {
            discordbotsorg: db_token,
            discordbotsgg: gg_token,
            discordboats: boats_token,
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
            log.debug("Failed to post server count "
                      f"to {service.__name__}: {e}")
        else:
            if r.status_code == 200:
                log.debug("Posted guild count "
                          f"({guilds_payload.Count}) to {service.__name__}")
            else:
                log.debug("Failed to post guild count to "
                          f"{service.__name__} ({r.status_code}): {r.text}")

    def update_presence(self, guilds_payload):
        if self.presence:
            presence = self.presence.format(**guilds_payload.to_dict())
            self.bot.client.update_presence(
                Status.online,
                Activity(
                    type=ActivityTypes.listening,
                    name=presence,
                )
            )

    def setup_services(self):
        """
        this exists to counter the fact that state.me isn't present at start.
        """
        self.bot_id = (self.bot_id or self.bot.state.me.id)
        for obj, token in self._tokens.copy().items():
            if token is not None:
                self.services.append(obj(
                    url={"id": self.bot_id},
                    auth=token,
                    headers={"User-Agent": self.user_agent},
                ))
            del self._tokens[obj]

    def update_stats(self):
        """
        This function updates the server amount status per interval
        and ensures the integrity of the guild data.
        """
        log.debug("Updating stats.")
        guild_count = len(self.bot.client.state.guilds)
        shard_id = self.bot.bot.client.config.shard_id
        shard_count = self.bot.bot.client.config.shard_count
        guilds_payload = guildCount(guild_count, shard_count, shard_id)
        self.update_presence(guilds_payload)
        for service in self.services:
            self.post(service, guilds_payload)
