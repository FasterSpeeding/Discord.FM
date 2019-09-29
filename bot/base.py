from platform import python_version
import logging
import operator
import os


from disco.types.message import MessageEmbed
from requests import __version__ as __Rversion__
from pydantic import BaseModel
try:
    import yaml
except ImportError:
    yaml = None
try:
    import ujson as json
except ImportError:
    import json


from bot import __GIT__
from bot.util.react import reactors_handler
from bot.util.sql import sql_instance

log = logging.getLogger(__name__)


def optional(**kwargs):
    return {index: data for index, data in kwargs.items() if data is not None}


class unset:
    def __nonzero__(self):
        return False

    def __bool__(self):
        return False


class custom_base(BaseModel):
    def get(self, context, *args):
        for arg in args:
            local = getattr(self, arg, unset)
            if local is not unset:
                setattr(context, arg, local)
            else:
                log.warning(f"Invalid or unset argument `{arg}` "
                            f"in get `{self.__name__}`.")

    def to_dict(self):
        return {key: value for key, value in self.dict().items()
                if value is not None}

    def __repr__(self):
        return f"<PydanticModel {self.__class__.__name__}>"

    def __str__(self):
        return f"<PydanticModel {self.__class__.__name__}>"


class api(custom_base):
    user_agent: str = (f"Discord.FM @{__GIT__} "
                       f"Python {python_version()} "
                       f"requests/{__Rversion__}")
    last_key: str = None
    google_key: str = None
    google_cse_engine_ID: str = ("0129851312360258"
                                 "62960:rhlblfpn4hc")
    spotify_ID: str = None
    spotify_secret: str = None
    discordbots_org: str = None
    discord_bots_gg: str = None
    discordboats: str = None
    discogs_key: str = None
    discogs_secret: str = None
    default_lyrics_limit: int = 3
    default_period: int = 0


class sql(custom_base):
    drivername: str = "mysql+pymysql"
    database: str = None
    host: str = None
    port: int = None
    username: str = None
    password: str = None
    query: dict = {"charset": "utf8mb4"}
    args: dict = None
    local_path: str = "data/data.db"


class embed_values(custom_base):
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


class config(custom_base):
    exception_dms: list = []
    exception_webhooks: dict = {}
    presence: str = "{count} guilds | {prefix}help"
    default_permissions: int = 104197184
    monitor_usage: int = None
    whitelist: list = []
    blacklist: list = []
    uservetos: list = []
    about_links: dict = {}
    api: api = api()
    disco: disco = disco()
    sql: sql = sql()
    embed_values: embed_values = embed_values()


class bot_frame:
    __slots__ = (
        "config",
        "config_meta",
        "help_embeds",
        "prefix_cache",
        "reactor",
        "sql",
    )
    cfg_read = {
        ".yaml": yaml.safe_load if yaml else None,
        ".json": json.load,
    }
    cfg_write = {
        ".yaml": yaml.dump if yaml else None,
        ".json": json.dump,
    }
    cfg_paths = ("config.json", "config.yaml")

    def __init__(self, config_path=None, raw_config=None):
        self.config = config(**(raw_config or self.get_config(config_path)))
        self.sql = sql_instance(**self.config.sql.to_dict())
        self.reactor = reactors_handler()
        self.prefix_cache = {}

    def generic_embed(self, **kwargs):
        for key, value in self.config.embed_values.to_dict().items():
            if key not in kwargs:
                kwargs[key] = value
        timestamp = kwargs.pop("timestamp", None)
        embed = MessageEmbed(kwargs)
    #    for field in embed.field:
    #        field.name = field.name[:256]
    #        field.value = field.value[:2048]
        if timestamp:
            embed.timestamp = timestamp
        return embed

    def get_config(self, config_path=None):
        meta_path = getattr(self, "config_meta", None)
        if (not (config_path or meta_path) or
                not os.path.isfile(config_path or meta_path)):
            locations = [path for path in self.cfg_paths
                         if os.path.isfile(path)]
            if not locations:
                raise Exception("Config location not found.")

            config_path = locations[0]
        else:
            config_path = config_path or meta_path
        handlers = [handler for type, handler in self.cfg_read.items()
                    if config_path.endswith(type)]
        if not handlers:
            raise Exception("Invalid config type.")

        if not handlers[0]:
            raise Exception("Handler for file type "
                            f"'{config_path.split('.')[-1]}' is not present.")

        data = handlers[0](open(config_path, "r"))
        self.config_meta = config_path
        return data

    def overwrite_config(self, data, location_overwrite=None):
        config_path = location_overwrite or self.config_meta
        if not os.path.isfile(config_path):
            raise Exception("Config location not found.")
        handlers = [handler for type, handler in self.cfg_write.items()
                    if config_path.endswith(type)]
        if not handlers or not handlers[0]:
            raise Exception("Invalid config type of handler for file type "
                            f"'{config_path.split('.')[-1]}' is not present.")

        with open(config_path, "w") as file:
            handlers[0](data, file, indent=4)

    @property
    def prefix(self):
        return self.config.disco.bot.commands_prefix or "fm."

    def load_help_embeds(self, bot):
        """
        Generate embeds used in the help command response
        based off @Plugin.command function docstrings.
        Uses the metadata entry 'help' as the module
        The the first line is the short explentation
        that's given in the general help response (with no arguments).
        With the rest of the docstring being reserved
        for when the user calls 'fm.help [command]'.
        """
        if not hasattr(self, "help_embeds"):
            self.help_embeds = dict()
        arrays_to_sort = list()
        for command in bot.commands:
            array_name = command.metadata.get("metadata", None)
            if array_name:
                array_name = array_name.get("help", None)
            doc_string = command.get_docstring().strip("\n").strip("    ")
            if array_name:
                if not doc_string:
                    doc_string = "Null"
                if array_name not in self.help_embeds:
                    self.help_embeds[array_name] = self.generic_embed(
                        title=f"{array_name.capitalize()} module commands.",
                        description=("Argument key: <required> [optional], "
                                     "with '...'specifying a multi-word "
                                     "argument and optional usernames "
                                     "defaulting to a user's set username."),
                    )
                args = command.raw_args if command.raw_args else ""
                if command.group:
                    command_name = command.group + " " + command.name
                else:
                    command_name = command.name
                self.help_embeds[array_name].add_field(
                    name=f"{self.prefix}**{command_name}** {args}",
                    value=doc_string.split("\n", 1)[0],
                    inline=False
                )
                arrays_to_sort.append(array_name)
        for array in arrays_to_sort:
            self.help_embeds[array].fields = sorted(
                self.help_embeds[array].fields,
                key=operator.attrgetter("name"),
            )
        self.help_embeds = {key: self.help_embeds[key] for
                            key in sorted(self.help_embeds.keys())}

    def unload_help_embeds(self, bot):
        for command in bot.commands:
            array_name = command.metadata.get("metadata", None)
            if array_name:
                array_name = array_name.get("help", None)
            if array_name:
                if command.raw_args is not None:
                    args = command.raw_args
                else:
                    args = str()
                field_name = f"{self.prefix}**{command.name}** {args}"
                if array_name in self.help_embeds:
                    matching_fields = [field for field in
                                       self.help_embeds[array_name].fields
                                       if field.name == field_name]
                    for field in matching_fields:
                        self.help_embeds[array_name].fields.remove(field)
                    if not self.help_embeds[array_name].fields:
                        del self.help_embeds[array_name]


bot = bot_frame()
