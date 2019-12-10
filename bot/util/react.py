from time import sleep, time


from disco.api.http import APIException
from disco.types.permissions import Permissions


from bot.util.misc import api_loop


class ReactorCondition:
    __slots__ = (
        "auth",
        "function",
        "owner_id",
        "reactor",
        "kwargs",
    )

    def __init__(
        self, reactor, function, owner_id: int, owner_only: bool = True, **kwargs
    ):
        self.auth = owner_only
        self.function = function
        self.owner_id = owner_id
        self.reactor = reactor
        self.kwargs = kwargs


class ReactorObject:
    __slots__ = (
        "channel_id",
        "message_id",
        "end_time",
        "conditions",
        "kwargs",
    )

    def __init__(
        self,
        channel_id: int,
        message_id: int,
        end_time: int = None,
        conditions: list = None,
        **kwargs
    ):
        """
        conditions: list
            An array of ReactorCondition objects
        """
        self.channel_id = channel_id
        self.message_id = message_id
        self.conditions = conditions or list()
        self.end_time = end_time or time() + 30
        self.kwargs = kwargs

    def get_condition(self, trigger_event):
        if not self.del_check() and self.conditions:
            for condition in self.conditions:
                if trigger_event.emoji.name == condition.reactor and (
                    not condition.auth or trigger_event.user_id == condition.owner_id
                ):
                    return condition

    def del_check(self):
        return time() > self.end_time


class ReactorsHandler(object):
    def __init__(self):
        self.events = dict()

    def init_event(self, message, timing=45, conditions=None, **kwargs):
        end_time = time() + timing
        if "reactor_map" not in kwargs:
            kwargs["reactor_map"] = REACTOR_FUNCTION_MAP
        self.events[message.id] = ReactorObject(
            channel_id=message.channel_id,
            message_id=message.id,
            end_time=end_time,
            conditions=conditions,
            **kwargs,
        )

    def add_argument(
        self, message_id, reactor, function, owner_id, owner_only=True, **kwargs
    ):
        if message_id in self.events:
            self.events[message_id].conditions.append(
                ReactorCondition(
                    reactor=reactor,
                    function=function,
                    owner_id=owner_id,
                    auth=owner_only,
                    **kwargs,
                )
            )
        else:
            raise IndexError("Message ID not present in list.")

    def add_reactors(self, client, message, reaction, author_id, *args, duration=30):
        for reactor in args:
            self.add_argument(
                message.id, reactor, reaction, author_id,
            )
        self_perms = message.channel.get_permissions(client.state.me)
        if self_perms.can(int(Permissions.ADD_REACTIONS)):
            for reactor in args:
                try:
                    client.api.channels_messages_reactions_create(
                        message.channel.id, message.id, reactor,
                    )
                except APIException as exception:
                    if exception.code == 10008:  # Unknown message
                        if message.id in self.events:
                            del self.events[message.id]
                        return

                    if exception.code in (30010, 50001, 50013, 90001):  # max reacts
                        break  # access, permission error, react blocked

                    raise exception
        sleep(duration)
        if message.id in self.events:
            del self.events[message.id]
            if self_perms.can(int(Permissions.MANAGE_MESSAGES)):
                try:
                    client.api.channels_messages_reactions_delete_all(
                        message.channel.id, message.id,
                    )
                except APIException as exception:
                    if exception.code not in (10008, 50001, 50013):
                        raise exception  # Unknown message, missing access, permission


def generic_react(
    client,
    message_id,
    channel_id,
    reactor,
    index,
    data,
    edit_message,
    reactor_map,
    amount=1,
    limit=100,
    **kwargs
):
    remainder = len(data) % amount
    function = reactor_map.get(reactor)
    if function:
        index = function(
            index=index,
            list_len=len(data),
            amount=amount,
            limit=limit,
            remainder=remainder,
            client=client,
            message_id=message_id,
            channel_id=channel_id,
        )
    else:
        return

    if index is not None:
        content, embed = edit_message(data=data, index=index, **kwargs)
        api_loop(
            client.api.channels_messages_modify,
            channel_id,
            message_id,
            content=content,
            embed=embed,
        )
    return index


def left_shift(index, list_len, remainder, amount=1, limit=100, **kwargs):
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
    if len(item) < limit:
        limit = len(item)
    return limit


def right_shift(index, list_len, *, amount=1, limit=100, **kwargs):
    if index >= limit - amount or index >= list_len - amount:
        index = 0
    else:
        index += amount
    return index


def end_event(client, message_id, channel_id, **kwargs):
    try:
        api_loop(
            client.api.channels_messages_delete, channel_id, message_id,
        )
    except APIException as exception:
        if exception.code == 10008:  # Unknown message
            pass
        else:
            raise exception


REACTOR_FUNCTION_MAP = {
    "\N{leftwards black arrow}\N{VARIATION SELECTOR-16}": left_shift,
    "\N{black rightwards arrow}\N{VARIATION SELECTOR-16}": right_shift,
    "\N{Cross Mark}\N{VARIATION SELECTOR-16}": end_event,
}
