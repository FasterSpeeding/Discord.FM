from datetime import datetime
import logging
import humanize
import pytz
import re


from disco.api.http import APIException
from disco.bot.command import CommandError
from requests import Request
from requests.exceptions import ConnectionError as requestsCError

log = logging.getLogger(__name__)


def api_loop(command, *args, log_50007=True, **kwargs):
    retries = 0
    while True:
        if retries >= 5:
            raise CommandError("Command timed out.")
        try:
            return command(*args, **kwargs)
        except requestsCError as e:
            log.info(f"Caught discord-request error {e}.")
        except APIException as e:
            if e.code == 50013:  # Missing permissions
                raise CommandError("Missing permissions to respond "
                                   "(possibly Embed Links).")
            if e.code != 50007 or log_50007:  # Cannot send messages to user
                log.critical(f"Api exception: {e.code}: {e}")
            raise e
        finally:
            retries += 1


def dm_default_send(event, dm_channel, *args, **kwargs):
    """
    Attempt to send a message to the user's DM
    defaults to the event channel if unable to send DM.
    """
    try:
        api_loop(dm_channel.send_message, log_50007=False, *args, **kwargs)
    except APIException as e:
        if e.code == 50007:  # Cannot send messages to user
            api_loop(event.channel.send_message, *args, **kwargs)
        else:
            raise e


user_regex = re.compile(r"[<]?[@]?[!]?\d+[>]?")
redact_regs = [
    re.compile(r"[-._\w\d]{30,45}.[-._\w\d]{65,80}.[-._\w\d]{35,50}"),
    re.compile(r"[-._\w\d]{20,140}"),
    re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
    re.compile(r"(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]"
               r"{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}"
               r"|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0"
               r"-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA"
               r"-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,"
               r"4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0"
               r"-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:)|fe80"
               r":(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|::(ffff(:0{1,4}"
               r"){0,1}:){0,1}((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.)"
               r"{3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])|([0-9a-fA-F]"
               r"{1,4}:){1,4}:((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.)"
               r"{3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9]))"),
]


def redact(data):
    for reg in redact_regs:
        data = reg.sub("<REDACTED>", data)
    return data


def AT_to_id(discord_id: str):
    discord_id = str(discord_id)
    if user_regex.fullmatch(discord_id):
        for to_replace in (("<", ""), ("@", ""), ("!", ""), (">", "")):
            discord_id = discord_id.replace(*to_replace)
        return int(discord_id)
    raise CommandError("Invalid @user.")


dictify_regex = re.compile(r"[\w\d]+\s{0,2}[=:]\s{0,2}[\w\d\s]+[,]?")
equal_seperate = re.compile(r"[\w\d]+\s{0,2}[=]\s{0,2}[\w\d\s]+")
colon_seperate = re.compile(r"[\w\d]+\s{0,2}[:]\s{0,2}[\w\d\s]+")


def dictify(intake):
    data = {}
    for match in dictify_regex.findall(intake):
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


def get_dict_item(data: dict, Dict_map: list):
    """
    Get the element embeded in layered dictionaries and lists
    based off a list of indexs and keys.
    """
    for index in Dict_map:
        try:
            data = data[index]
        except (IndexError, KeyError):
            return
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
    except requestsCError as e:
        log.warning(e)
        raise CommandError(f"{service} isn't available right now.")

    if r.status_code < 400:
        return r.json()

    if r.status_code == 404:
        raise CommandError(f"404 - {item} doesn't exist.")

    raise CommandError(f"{r.status_code} - {service} threw "
                       f"unexpected error: {redact(r.text)}")


def exception_webhooks(client, exception_webhooks, **kwargs):
    for webhook_id, token in exception_webhooks.copy().items():
        try:
            api_loop(
                client.api.webhooks_token_execute,
                webhook_id,
                token,
                data=kwargs,
            )
        except APIException as e:
            if e.code in (10015, 50001):
                log.warning("Unable to send exception "
                            f"webook - {webhook_id}: {e}")
                del exception_webhooks[webhook_id]
            else:
                raise e
        except CommandError as e:
            log.warning(e)


def exception_dms(client, exception_dms, *args, **kwargs):
    for target in exception_dms.copy():
        target_dm = client.api.users_me_dms_create(target)
        try:
            api_loop(target_dm.send_message, *args, **kwargs)
        except APIException as e:  # Missing permissions, Missing access,
            if e.code in (50013, 50001, 50007):  # Cannot send messages to this user
                log.warning("Unable to send exception DM - "
                            f"{target}: {e}")
                exception_dms.remove(target)
            else:
                raise e


def time_since(time_of_event: int, timezone=pytz.UTC, **kwargs):
    """
    A command used get the time passed since a unix time stamp
    and output it as a human readable string.
    """
    time_passed = (datetime.now(timezone) -
                   datetime.fromtimestamp(int(time_of_event), timezone))
    return humanize.naturaltime(time_passed)
