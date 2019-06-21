from platform import python_version
import logging
import operator
import os
import yaml


from requests import __version__ as __Rversion__
try:
    from ujson import load
except ImportError:
    from json import load


from bot import __GIT__, __VERSION__
from bot.types.embed import generic_embed_values
from bot.util.react import reactors_handler

log = logging.getLogger(__name__)


class unset:
    def __init__(self, type, default=None):
        self.type = type
        self.default = default

    def __nonzero__(self):
        return False

    def __bool__(self):
        return False


class feed_dict:
    """Used for a config that takes in **kwargs"""
    __intake__ = dict


class feed_list:
    """Used for a config that takes in *args"""
    __intake__ = list


def optional(**kwargs):
    return {index: data for index, data in kwargs.items() if data is not None}


class config_template:
    __name__ = "Unset"
    __unsettable__ = True

    def __init__(self, **kwargs):
        arguments = [arg for arg in dir(self) if not arg.startswith("__") and
                     (not callable(getattr(self, arg)) or
                     getattr(getattr(self, arg), "__unsettable__", False))]
        for arg in arguments:
            value = kwargs.get(arg, unset)
            template = getattr(self, arg)
            if value is not unset:
                if issubclass(template.type, config_template):
                    if isinstance(value, template.type.__intake__):
                        if template.type.__intake__ is dict:
                            setattr(self, arg, template.type(**value))
                        elif template.type.__intake__ is list:
                            setattr(self, arg, template.type(*value))
                    elif isinstance(value, type(None)):
                        setattr(self, arg, template.type())
                    else:
                        setattr(self, arg, template.type())
                        log.warning(f"Invalid type for {self.__name__}.{arg}, "
                                    f"needs {template.type.__intake__}.")
                else:
                    if isinstance(value, template.type):
                        setattr(self, arg, value)
                    else:
                        setattr(self, arg, template.default)
                        if (not isinstance(value, type(template.default))
                                and not isinstance(value, type(None))):
                            log.warning(f"Invalid type for {self.__name__}"
                                        f".{arg}. Needs {template.type}")
            else:
                if issubclass(template.type, config_template):
                    setattr(self, arg, template.type())
                else:
                    setattr(self, arg, template.default)

    def get(self, context, *args):
        for arg in args:
            local = getattr(self, arg, unset)
            if local is not unset:
                setattr(context, arg, local)
            else:
                log.warning(f"Invalid or unset argument `{arg}` "
                            f"in get `{self.__name__}`.")

    def to_dict(self):
        return {key: value for key, value in self.__dict__.items()
                if value is not None}

    def __repr__(self):
        return f"<config {self.__name__}>"


class api(config_template, feed_dict):
    __name__ = "api"
    user_agent = unset(str, default=(f"Discord.FM @{__GIT__} {__VERSION__} "
                                     f"Python {python_version()} "
                                     f"requests/{__Rversion__}"))
    last_key = unset(str)
    google_key = unset(str)
    google_cse_engine_ID = unset(
        str,
        default="012985131236025862960:rhlblfpn4hc",
    )
    spotify_ID = unset(str)
    spotify_secret = unset(str)
    dbl_token = unset(str)
    discord_bots_gg = unset(str)
    discogs_key = unset(str)
    discogs_secret = unset(str)


class sql(config_template, feed_dict):
    __name__ = "sql"
    database = unset(str)
    server = unset(str)
    user = unset(str)
    password = unset(str, default="")
    adapter = unset(str, default="mysql+pymysql")
    args = unset(dict, default={})


class embed_values(config_template, feed_dict):
    __name__ = "embed_values"
    url = unset(str)
    color = unset(str)


class bot(config_template, feed_dict):
    levels = unset(dict, default={})
    commands_require_mention = unset(bool, default=True)
    commands_mention_rules = unset(dict)
    commands_prefix = unset(str)
    commands_allow_edit = unset(bool)
    commands_level_getter = unset(object)  # deal with
    commands_group_abbrev = unset(bool)
    plugin_config_provider = unset(object)  # same
    plugin_config_format = unset(str)
    plugin_config_dir = unset(str)
    http_enabled = unset(bool)
    http_host = unset(str)
    http_port = unset(int)
    plugins = unset(list, default=[
        "bot.disco.superuser",
        "bot.disco.core",
        "bot.disco.fm",
        "bot.disco.api",
        "bot.disco.voice",
        "bot.disco.discogs",
    ])


class disco(config_template, feed_dict):
    __name__ = "disco"
    token = unset(str)
    bot = unset(bot)
    config = unset(str)
    shard_id = unset(int)
    shard_count = unset(int)
    max_reconnects = unset(int)
    log_level = unset(str)
    file_log_level = unset(str, default="WARNING")
    manhole = unset(bool)  # manhole_enable
    manhole_bind = unset(int)
    plugin = unset(list, default=[])
    run_bot = unset(bool, default=False)
    encoder = unset(str)  # , default="etf" # etc has weird guild issues.
    shard_auto = unset(bool, default=False)


class config(config_template, feed_dict):
    __name__ = "config"
    exception_dms = unset(list)
    exception_channels = unset(dict)
    prefix = unset(str, default="fm.")
    api = unset(api)
    disco = unset(disco)
    sql = unset(sql)
    embed_values = unset(embed_values)


class bot_frame:
    triggers_set = set()
    local = config
    reactor = reactors_handler
    generic_embed_values = generic_embed_values

    def __init__(self, config_location="config.json"):
        if os.path.isfile(config_location):
            if config_location.lower().endswith(".json"):
                data = load(open(config_location, "r"))
                self.local = self.local(**data)
            elif config_location.lower().endswith(".yaml"):
                data = yaml.safe_load(open(config_location, "r"))
                self.local = self.local(**data)
            else:
                log.exception("Invalid config file format.")
        elif os.path.isfile("config.yaml"):
            self.local = self.local(**yaml.safe_load(open("config.yaml", "r")))
        elif not config_location:
            log.exception("Missing config file or invalid "
                          f"location given {config_location}")
        else:
            self.local = self.local()
        self.reactor = self.reactor()
        self.generic_embed_values = self.generic_embed_values(self.local)

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
                prefix = (self.local.disco.bot.commands_prefix or "fm.")
                self.help_embeds[array_name].add_field(
                    name=f"{prefix}**{command_name}** {args}",
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
                prefix = (self.local.disco.bot.commands_prefix or "fm.")
                field_name = f"{prefix}**{command.name}** {args}"
                if array_name in self.help_embeds:
                    matching_fields = [field for field in
                                       self.help_embeds[array_name].fields
                                       if field.name == field_name]
                    for field in matching_fields:
                        self.help_embeds[array_name].fields.remove(field)
                    if not self.help_embeds[array_name].fields:
                        del self.help_embeds[array_name]


bot = bot_frame()
