from platform import python_version
import logging
import operator
import os


from requests import __version__ as __Rversion__
from pydantic import BaseModel
from yaml import safe_load
try:
    from ujson import load
except ImportError:
    from json import load


from bot import __GIT__, __VERSION__
from bot.types.embed import generic_embed_values
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


class api(custom_base):
    user_agent : str = (f"Discord.FM @{__GIT__} {__VERSION__} "
                        f"Python {python_version()} "
                        f"requests/{__Rversion__}")
    last_key : str = None
    google_key : str = None
    google_cse_engine_ID : str = ("0129851312360258"
                                  "62960:rhlblfpn4hc")
    spotify_ID : str = None
    spotify_secret : str = None
    discordbots_org : str = None
    discord_bots_gg : str = None
    discogs_key : str = None
    discogs_secret : str = None


class sql(custom_base):
    database : str = None
    server : str = None
    user : str = None
    password : str = ""
    adapter : str = "mysql+pymysql"
    args : dict = {}


class embed_values(custom_base):
    __name__ = "embed_values"
    url : str = None
    color : str = None


class bot_data(custom_base):
    levels : dict = {}
    commands_require_mention : bool = True
    commands_mention_rules : dict = None
    commands_prefix : str = None
    commands_allow_edit : bool = None
    commands_level_getter : str = None
    commands_group_abbrev : bool = None
    plugin_config_provider : str = None
    plugin_config_format : str = None
    plugin_config_dir : str = None
    http_enabled : bool =None
    http_host : str = None
    http_port : int = None
    plugins : list = [
        "bot.disco.superuser",
        "bot.disco.core",
        "bot.disco.fm",
        "bot.disco.api",
        "bot.disco.voice",
        #  "bot.disco.discogs",
    ]


class disco(custom_base):
    token : str = None
    bot : bot_data = bot_data()
    config: str = None
    shard_id: int = None
    shard_count: int = None
    max_reconnects: int = None
    log_level: str = None
    file_log_level: str = "WARNING"
    manhole: bool = None  # manhole_enable
    manhole_bind: int = None
    plugin: list = []
    run_bot: bool = True
    encoder: str = None  # , default="etf" # etc has weird guild issues.
    shard_auto: bool = False


class config(custom_base):
    exception_dms: list = None
    exception_channels: dict = None
    prefix: str = "fm."
    api: api = api()
    disco: disco = disco()
    sql: sql = sql()
    embed_values: embed_values = embed_values()


bindings = {
    ".yaml": safe_load,
    ".json": load,
    }
default_configs = ("config.json", "config.yaml")


def get_config(config="config.json"):
    if not os.path.isfile(config):
        locations = [path for path in default_configs
                     if os.path.isfile(path)]
        if not locations:
            raise Exception("Config location not found.")
        config = locations[0]
    handlers = [handler for type, handler in bindings.items()
                if config.endswith(type)]
    if not handlers:
        raise Exception("Invalid config type.")
    return handlers[0](open(config, "r"))


class bot_frame:
    triggers_set = set()
    config = config
    reactor = reactors_handler
    sql = sql_instance
    generic_embed_values = generic_embed_values

    def __init__(self, config_location=None):
        self.config = self.config(**get_config())
        self.sql = self.sql(self.config.sql.to_dict())
        self.reactor = self.reactor()
        self.generic_embed_values = self.generic_embed_values(self.config)

    def prefix(self):
        return (self.config.prefix or
                self.config.disco.bot.commands_prefix or
                "fm.")

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
        if "help_embeds" not in dir(self):
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
                    title = {
                        "title": f"{array_name.capitalize()} module commands.",
                    }
                    self.help_embeds[array_name] = self.generic_embed_values(
                        title=title,
                        description=("Argument key: <required> [optional], "
                                     "with '...'specifying a multi-word "
                                     "argument and optional usernames "
                                     "defaulting to a user's set username.")
                    )
                if command.raw_args is not None:
                    args = command.raw_args
                else:
                    args = str()
                if command.group:
                    command_name = command.group + " " + command.name
                else:
                    command_name = command.name
                self.help_embeds[array_name].add_field(
                    name=f"{self.prefix()}**{command_name}** {args}",
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
                field_name = f"{self.prefix()}**{command.name}** {args}"
                if array_name in self.help_embeds:
                    matching_fields = [field for field in
                                       self.help_embeds[array_name].fields
                                       if field.name == field_name]
                    for field in matching_fields:
                        self.help_embeds[array_name].fields.remove(field)
                    if not self.help_embeds[array_name].fields:
                        del self.help_embeds[array_name]


bot = bot_frame()
