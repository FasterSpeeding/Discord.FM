import dataclasses

import bot
from platform import python_version
import httpx



@dataclasses.dataclass()
class ApiConfig:
    user_agent: str = (f"Discord.FM @{bot.__version__} "
                       f"Python {python_version()} "
                       f"httpx/{httpx.__version__}")
    last_key: str = None
    google_key: str = None
    google_cse_engine_ID: str = ("0129851312360258"
                                 "62960:rhlblfpn4hc")
    spotify_id: str = None
    spotify_secret: str = None
    discordbots_org: str = None
    discord_bots_gg: str = None
    discordboats: str = None
    discogs_key: str = None
    discogs_secret: str = None
    default_lyrics_limit: int = 3
    default_period: int = 0


@dataclasses.dataclass()
class SqlConfig:
    drivername: str = "mysql+pymysql"
    database: str = None
    host: str = None
    port: int = None
    username: str = None
    password: str = None
    query: dict = {"charset": "utf8mb4"}
    args: dict = None
    local_path: str = "data/data.db"


@dataclasses.dataclass()
class EmbedValuesConfig:
    __name__ = "embed_values"
    url: str = None
    color: str = None
    type: str = None


class bot_data(custom_base):
    levels: dict = {}
    commands_enabled: bool = False
    commands_require_mention: bool = False
    commands_mention_rules: dict = None
    commands_prefix: str = "fm."
    commands_allow_edit: bool = None
    commands_level_getter: str = None
    commands_group_abbrev: bool = None
    plugin_config_provider: str = None
    plugin_config_format: str = None
    plugin_config_dir: str = None
    http_enabled: bool = None
    http_host: str = None
    http_port: int = None
    plugins: list = [
        "bot.plugins.superuser",
        "bot.plugins.core",
        "bot.plugins.fm",
        "bot.plugins.api",
        "bot.plugins.voice",
        #  "bot.plugins.discogs",
    ]


class disco(custom_base):
    token: str = None
    bot: bot_data = bot_data()
    config: str = None
    shard_id: int = None
    shard_count: int = None
    guild_subscriptions: bool = True
    max_reconnects: int = None
    log_level: str = None
    file_log_level: str = "WARNING"
    manhole: bool = None  # manhole_enable
    manhole_bind: int = None
    plugin: list = []
    run_bot: bool = True
    encoder: str = None  # etc has weird guild issues.
    shard_auto: bool = False


@dataclasses.dataclass()
class FullConfig:
    exception_dms: list = []
    exception_webhooks: dict = {}
    presence: str = "{count} guilds | {prefix}help"
    default_permissions: int = 104197184
    emoji_guild: int = None
    monitor_usage: int = None
    no_exception_response: bool = False
    about_links: dict = {}
    api: api = api()
    disco: disco = disco()
    sql: sql = sql()
    embed_values: embed_values = embed_values()

