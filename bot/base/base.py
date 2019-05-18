import operator


from disco.util.logging import logging
try:
    from ujson import load
except ImportError:
    from json import load


from bot.types.embed import generic_embed_values
from bot.util.react import reactors_handler

log = logging.getLogger(__name__)

class unset:
    def __init__(self, type, default=None):
        self.type = type
        self.default = default

class feed_dict:
    """Used for a config that takes in **kwargs"""
    type = dict

class feed_list:
    """Used for a config that takes in *args"""
    type = list

class config_template:
    __name__ = "Unset"
    __intake__ = feed_dict
    __unsettable__ = True
    def __init__(self, **kwargs):
        arguments = [arg for arg in dir(self) if not arg.startswith("__") and
                    not callable(getattr(self, arg)) or
                    getattr(getattr(self, arg), "__unsettable__", False) is True and
                    arg != "__class__"]
        for arg in arguments:
            value = kwargs.get(arg, unset)
            template = getattr(self, arg)
            if value is not unset:
                if issubclass(template.type, config_template):
                    if isinstance(value, template.type.__intake__.type):
                        if template.type.__intake__.type is dict:
                            setattr(self, arg, template.type(**value))
                        elif template.type.__intake__.type is list:
                            setattr(self, arg, template.type(*value))
                    elif isinstance(value, type(None)):
                        setattr(self, arg, template.type())
                    else:
                        log.warning("Invalid type for {}.{}, needs {}.".format(
                            self.__name__,
                            arg,
                            template.type.__intake__.type,
                        ))
                else:
                    if isinstance(value, template.type):
                        setattr(self, arg, value)
                    else:
                        setattr(self, arg, template.default)
                        if not isinstance(value, type(template.default)):
                            log.warning("Invalid type for {}.{}. Needs {}".format(
                                self.__name__,
                                arg,
                                template.type,
                            ))
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
                log.warning("Invalid argument {} in get {}.".format(
                    arg,
                    self.__name__
                ))

    def to_dict(self):
        return self.__dict__

class api(config_template):
    __name__ = "api"
    __intake__ = feed_dict
    user_agent = unset(str, default="Discord.FM")
    last_key = unset(str)
    google_key = unset(str)
    google_cse_engine_ID = unset(str, default="012985131236025862960:rhlblfpn4hc")
    spotify_ID = unset(str)
    spotify_secret = unset(str)
    dbl_token = unset(str)
    discord_bots_gg = unset(str)

class sql(config_template):
    __name__ = "sql"
    __intake__ = feed_dict
    database = unset(str)
    server = unset(str)
    user = unset(str)
    password = unset(str, default="")

class embed_values(config_template):
    __name__ = "embed_values"
    __intake__ = feed_dict
    url = unset(str)
    color = unset(str) # , default="000089")


class config(config_template):
    __name__ = "config"
    __intake__ = feed_dict
    exception_dm = unset(bool, default=False)
    exception_channel = unset(int)
    default_prefix = unset(str, default="fm.")
    owners = unset(list, list())
    api = unset(api)
    sql = unset(sql)
    embed_values = unset(embed_values)


class bot_frame:
    commands_list = dict()
    local = None
    reactor = None
    generic_embed_values = None

    def __init__(self, config_location="config.json"):
        self.local = config(**load(open(config_location)))
        self.reactor = reactors_handler()
        self.generic_embed_values = generic_embed_values(self.local)

    def custom_prefix_init(self, context):
        """
        Generate a dictionary of command triggers (keys)
        by command function (values).
        """
        for command in iter(context.commands):
            for trigger in command.triggers:
                if trigger not in self.commands_list:
                    self.commands_list[trigger] = command
                else:
                    log.warning("Duplicate command trigger '{}' not loaded from {}.".format(
                        trigger,
                        context.name,
                    ))
        return context

    def init_help_embeds(self, bot):
        """
        Generate embeds used in the help command response
        based off @Plugin.command function docstrings.
        Uses the first word as the module,
        The rest of the first line is the short explentation
        that's given in the general help response (with no arguments).
        With the rest of the docstring being reserved
        for when the user calls 'fm.help [command]'.
        """
        if "help_embeds" not in dir(self):
            self.help_embeds = dict()
        help_embeds = self.help_embeds
        arrays_to_sort = list()
        for command in bot.commands:
            doc_string = command.get_docstring().strip("\n").strip("    ")
            if len(command.get_docstring()) != 0:
                array_name = doc_string.split(" ", 1)[0].lower()
                if array_name not in help_embeds:
                    url = getattr(self.local.embed_values, "url")
                    help_embeds[array_name] = self.generic_embed_values(
                        title="{} module commands.".format(
                            array_name.capitalize(),
                        ),
                        url=url,
                        description="Argument key: <required> [optional], with '...' specifying a multi-word argument and optional usernames defaulting to a user specific username."
                    )
                if command.raw_args is not None:
                    args = command.raw_args
                else:
                    args = str()
                help_embeds[array_name].add_field(
                    name="fm.**{}** {}".format(command.name, args),
                    value="{}".format(
                        doc_string[len(array_name) + 1:].split(
                            "\n",
                            1,
                        )[0],
                    ),
                    inline=False
                )
                arrays_to_sort.append(array_name)
        for array in arrays_to_sort:
            help_embeds[array].fields = sorted(
                help_embeds[array].fields,
                key=operator.attrgetter("name"),
            )


bot = bot_frame()

if __name__ == "__main__":
    local = config(**load(open("config.json")))
    print(local.to_dict())
    print(local.sql.to_dict())
    print(local.embed_values.to_dict())
    print(local.api.to_dict())
    print(dir(local.api))
