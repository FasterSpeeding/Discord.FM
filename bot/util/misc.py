from re import compile
from time import time
# ECONNABORTED


from disco.api.http import APIException
from disco.bot.command import CommandError
from disco.util.logging import logging
from requests.exceptions import ConnectionError

log = logging.getLogger(__name__)

def api_loop(command, *args, **kwargs):
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
                raise CommandError("Missing permissions to respond (possibly Embed Links).")
            else:
                log.critical("Api exception: {}: {}".format(e.code, e))
                raise e

def dm_default_send(event, dm_channel, *args, **kwargs):
    """
    Attempt to send a message to the user's DM
    defaults to the event channel if unable to send DM.
    """
    try:
        api_loop(dm_channel.send_message, *args, **kwargs)
    except APIException as e:
        if e.code == 50007:  # Wasn't able to open a DM/send DM message
            api_loop(event.channel.send_message, *args, **kwargs)
        else:
            raise e


discord_user_reg = compile("[<][@]\\d{18}[>]")
discord_nick_reg = compile("[<][@][!]\\d{18}[>]")
discord_id_reg = compile("\\d{18}")


def AT_to_id(id:str):
    if (discord_user_reg.match(str(id)) or discord_nick_reg.match(str(id)) or
            discord_id_reg.match(str(id))):
        return int(str(id).replace("<", "").replace("@", "").replace("!", "").replace(">", ""))
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
