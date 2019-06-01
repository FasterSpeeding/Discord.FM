# hecking reacts don't work in dms
# write in checks for missing permissions like message embed etc
from time import sleep, time
import logging


from disco.api.http import APIException
from disco.bot.command import CommandError
from disco.types.channel import Channel
from disco.bot.command import CommandError
from disco.types.message import Message


from bot.util.misc import api_loop

log = logging.getLogger(__name__)


class reactor_condition:  # implement this as well.
    def __init__(
            self,
            reactor,
            function,
            owner_id:int,
            owner_only:bool=True,
            **kwargs):
        self.auth = owner_only  # rename that
        self.function = function
        self.owner_id = owner_id
        self.reactor = reactor
        self.kwargs = kwargs


class reactor_object:  # implement this
    def __init__(
            self,
            channel_id:int,
            message_id:int,
            end_time:int = None,
            conditions:list=None,
            **kwargs):
        """
        conditions: list
            An array of reactor_condition objects
        """
        self.channel_id = channel_id
        self.message_id = message_id
        self.conditions = (conditions or list())
        self.end_time = (end_time or time() + 30)
        self.kwargs = kwargs


class reactors_handler(object):
    def __init__(self):
        self.events = dict()
        self.__name__ = "reactor"

    def init_event(self, message, timing, id=None, **kwargs):
        end_time = time() + timing
        event_dict = {
            "channel_id": message.channel_id,
            "message_id": message.id,
            "end_time": end_time,
            "conditions": [],
            "kwargs": kwargs,
        }
        self.events[message.id] = type("message_id", (object,), event_dict)()

    def add_argument(
            self,
            id,
            reactor,
            function,
            owner_id,
            owner_only=True,
            **kwargs):
        if id in self.events:
            self.events[id].conditions.append(
                type(
                    "reactor condition",
                    (object, ),
                    {
                        "reactor": reactor,
                        "function": function,
                        "owner_id": owner_id,
                        "auth": owner_only,
                        "kwargs": kwargs,
                    },
                    )()
            )
        else:
            raise IndexError("ID not present in list.")

    def add_reactors(
            self,
            client,
            message,
            reaction,
            author_id,
            *args,
            channel=None,
            time:int=30):
        if isinstance(message, Message):
            if (message.id is None or message.channel is None or
                    message.channel.id is None):
                log.info("Failed to add reactors, either message.id or message.channel or message.channel.id was None.")
                return
            message_id = message.id
            channel_id = message.channel.id
        else:
            message_id = int(message)
            if channel_id is not None:
                if isinstance(channel_id, Channel):
                    if channel_id.id is None:
                        log.info("Failed to add reactors, channel_id.id was None.")
                        return
                    channel_id = channel_id.id
                else:
                    channel_id = int(channel_id)
            else:
                raise Exception("Unable to add reactor, either unable to work out channel id or missing channel id.")
        for reactor in args:
            self.add_argument(
                id=message_id,
                reactor=reactor,
                function=reaction,
                owner_id=author_id,
            )
        for reactor in args:
            try:
                client.client.api.channels_messages_reactions_create(
                    channel_id,
                    message_id,
                    reactor,
                )
            except APIException as e:
                if e.code == 10008:
                    if message_id in self.events:
                        # self.events.pop(message_id, None)
                        del self.events[message_id]
                    break
                elif e.code == 50001:
                    if message_id in self.events:
                        del self.events[message_id]
                    raise CommandError("Missing ``add reactions`` permission.")
                else:
                    raise e
        sleep(time)
        if message_id in self.events:
            del self.events[message_id]
            try:
                client.client.api.channels_messages_reactions_delete_all(
                    channel_id,
                    message_id,
                )
            except APIException as e:
                if e.code == 10008:
                    pass
                elif e.code == 50013:
                    client.client.api.channels_messages_create(
                        channel=channel_id,
                        content="Missing permission required to clear message reactions ``Manage Messages``.",
                    )
                else:
                    raise e


@classmethod
def generic_react(
        self,
        client,
        message_id,
        channel_id,
        reactor,
        index,
        data,
        edit_message,
        amount=1,
        limit=100,
        **kwargs):
    remainder = (len(data) % amount)
    if reactor == "\N{black rightwards arrow}":
        index = right_shift(
            index,
            len(data),
            amount=amount,
            limit=limit,
            remainder=remainder,
        )
    elif reactor == "\N{Cross Mark}":
        try:
            api_loop(
                client.client.api.channels_messages_delete,
                channel_id,
                message_id,
            )
        except APIException as e:
            if e.code == 10008:
                pass
            else:
                raise e
        return None
    elif reactor == "\N{leftwards black arrow}":
        index = left_shift(
            index,
            len(data),
            amount=amount,
            limit=limit,
            remainder=remainder,
        )
    else:
        return
    content, embed = edit_message(data=data, index=index, kwargs=kwargs)
    api_loop(
        client.client.api.channels_messages_modify,
        channel_id,
        message_id,
        content=content,
        embed=embed,
    )
    return index


def left_shift(index, list_len, remainder, amount=1, limit=100):
    if index == 0 or index < amount:
        if list_len >= limit:
            index = limit - amount
        else:
            if remainder == 0:
                index = list_len - amount
            else:
                index = list_len - remainder
    else:
        index -= amount
    return index


def length(item, limit=100):
    if len(item) >= limit:
        return limit
    else:
        return len(item)


def right_shift(index, list_len, remainder, amount=1, limit=100):
    if index >= limit - amount or index >= list_len - amount:
        index = 0
    else:
        index += amount
    return index
