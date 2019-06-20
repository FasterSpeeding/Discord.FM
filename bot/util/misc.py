from re import compile
from time import time
import logging


from disco.api.http import APIException
from disco.bot.command import CommandError
from requests import Session, Request
from requests.exceptions import ConnectionError

log = logging.getLogger(__name__)


def api_loop(command, *args, log_50007=True, **kwargs):
    init_time = time()
    while True:
        if time() - init_time > 10:
            raise CommandError("Command timed out.")
        try:
            return command(*args, **kwargs)
        except ConnectionError as e:
            log.info("Didn't catch error reset.")
        except APIException as e:
            if e.code == 50013:
                raise CommandError("Missing permissions to respond "
                                   "(possibly Embed Links).")
            else:
                if e.code != 50007 or log_50007:
                    log.critical(f"Api exception: {e.code}: {e}")
                raise e


def dm_default_send(event, dm_channel, *args, **kwargs):
    """
    Attempt to send a message to the user's DM
    defaults to the event channel if unable to send DM.
    """
    try:
        api_loop(dm_channel.send_message, log_50007=False, *args, **kwargs)
    except APIException as e:
        if e.code == 50007:  # Wasn't able to open a DM/send DM message
            api_loop(event.channel.send_message, *args, **kwargs)
        else:
            raise e


user_regex = compile(r"[<]?[@]?[!]?\d{18}[>]?")
api_key_regs = [
    compile(r"[\w\d]{20,50}"),  # 32 to 4? with some room given
    compile(r"[\w\d]{30,45}.{65,80}.{35,50}"),  # 36, 74, 43
]


def AT_to_id(id: str):
    id = str(id)
    if user_regex.fullmatch(id):
        for to_replace in (("<", ""), ("@", ""), ("!", ""), (">", "")):
            id = id.replace(*to_replace)
        return int(id)
    else:
        raise CommandError("Invalid @user.")


regex = compile(r"[\w\d]+\s{0,2}[=:]\s{0,2}[\w\d\s]+[,]?")
equal_seperate = compile(r"[\w\d]+\s{0,2}[=]\s{0,2}[\w\d\s]+")
colon_seperate = compile(r"[\w\d]+\s{0,2}[:]\s{0,2}[\w\d\s]+")


def dictify(intake):
    data = {}
    for match in regex.findall(intake):
        seperate = equal_seperate.match(match)
        if seperate:
            split = "="
        else:
            split = ":"
            seperate = colon_seperate.match(match)
        split = seperate.string.split(split)
        key = split.pop(0).strip(" ")
        value = ""
        for item in split:
            value += item
        value = (value[:-1] if value[-1] == "," else value).strip(" ")
        data[key] = value
    return data


def get_dict_item(data: dict, map: list):
    """
    Get the element embeded in layered dictionaries and lists
    based off a list of indexs and keys.
    """
    for index in map:
        data = data[index]
    return data


def get(
        self,
        params: dict = None,
        endpoint: str = "",
        url: str = None,
        item: str = "item"):
    url = (url or self.BASE_URL) + endpoint
    if params:
        params = {str(key): str(value) for key, value in params.items()}
    get = self.s.prepare_request(Request("GET", url, params=params))
    service = getattr(self, "SERVICE", None)
    try:
        r = self.s.send(get)
    except ConnectionError as e:
        log.warning(e)
        raise CommandError(f"{service} isn't available right now.")
    if r.status_code < 400:
        return r.json()
    elif r.status_code == 404:
        raise CommandError(f"404 - {item} doesn't exist.")
    elif r.status_code < 500:
        raise CommandError(f"{r.status_code} - {service} threw "
                           f"unexpected error: {r.text}")
    else:
        raise CommandError(f"{service} isn't available right now.")
