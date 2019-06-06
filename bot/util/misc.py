from re import compile
from time import time
import logging


from disco.api.http import APIException
from disco.bot.command import CommandError
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


def AT_to_id(id:str):
    id = str(id)
    if user_regex.fullmatch(id):
        for to_replace in (("<", ""), ("@", ""), ("!", ""), (">", "")):
            id = id.replace(*to_replace)
        return int(id)
    else:
        raise CommandError("Invalid @user.")


def get_dict_item(data:dict, map:list):
    """
    Get the element embeded in layered dictionaries and lists
    based off a list of indexs and keys.
    """
    for index in map:
        data = data[index]
    return data
