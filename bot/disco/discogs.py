from decimal import Decimal
from re import compile
from time import time, strftime, gmtime


from disco.bot import Plugin
from disco.bot.command import CommandError
from disco.util.logging import logging
from disco.util.sanitize import S as sanitize
from requests import Session, Request
from requests.exceptions import ConnectionError


from bot.base import bot, optional
from bot.util.misc import (
    api_loop, AT_to_id, dictify, get,
    get_dict_item, user_regex as discord_regex
)
from bot.util.react import generic_react


log = logging.getLogger(__name__)
# Pagination


class discogsPlugin(Plugin):
    def load(self, ctx):
        super(discogsPlugin, self).load(ctx)
        secret = bot.local.api.discogs_secret
        key = bot.local.api.discogs_key
        bot.load_help_embeds(self)
        self.prefix = (bot.local.prefix or
                       bot.local.disco.bot.commands_prefix or
                       "fm.")
        self.s = Session()
        self.s.headers.update({
            "Authorization": f"Discogs key={key}, secret={secret}",
            "Content-Type": "application/json",
            "User-Agent": bot.local.api.user_agent,
        })
        self.BASE_URL = "https://api.discogs.com/"
        self.SERVICE = "discogs"

    def unload(self, ctx):
        bot.unload_help_embeds(self)
        super(discogsPlugin, self).unload(ctx)

    def __check__(self):
        return bot.local.api.discogs_key and bot.local.api.discogs_secret

    @Plugin.command("search", "<raw_params:str...>", group="discogs", metadata={"help": "discogs"})
    def on_search_command(self, event, raw_params):
        """
        Used to search Discogs' database
        This command accepts 1 multi-word argument
        which is split into separate parameters,
        with comas being used to separate entries where a format similar to
        `parameter = value,` or `parameter : value,` is found.
        The first argument does not accept a parameter or equals sign/colon
        and is the only required argument (the query).
        The optional parameters are:
        "type", "title", "release_title", "credit", "artist",
        "anv", "label", "genre", "style", "country", "year",
        "format", "catno", "barcode", "track", "submitter", "contributor",
        """
        optional_params = [
            "type",
            "title",
            "release_title",
            "credit",
            "artist",
            "anv",
            "label",
            "genre",
            "style",
            "country",
            "year",
            "format",
            "catno",
            "barcode",
            "track",
            "submitter",
            "contributor",
        ]
        params = {"query": raw_params.split(",", 1)[0]}
        if len(params["query"]) < len(raw_params):
            raw_params = dictify(raw_params[len(params["query"]):])
        else:
            raw_params = {}
        params.update({key: index for key, index in raw_params.items()
                       if key in optional_params})
        data = get(self, params, "database/search")
        print(data)
        event.channel.send_message(":thumbsup:")

    @Plugin.command("release info", "<release_id:int> [currency:str]", group="discogs", metadata={"help": "discogs"})
    def on_release_info_command(self, event, release_id, currency=None):
        params = {}
        if currency and currency.upper() in [
                    "USD",
                    "GBP",
                    "EUR",
                    "CAD",
                    "AUD",
                    "JPY",
                    "CHF",
                    "MXN",
                    "BRL",
                    "NZD",
                    "SEK",
                    "ZAR",
                ]:
            params.update({"curr_abbr": currency.upper()})
        data = get(self, params, f"releases/{release_id}")
        genres = ""
        for g in data["genres"]:
            genres += g + " "
        currency = (currency or "USD")
        released = data.get("released_formatted", None)
        if not released:
            released = data.get("released", "Unknown")
        if data.get("lowest_price", None):
            price = f"{data['lowest_price']} {currency}"
        else:
            price = "Unknown"
        tracks = len(data["tracklist"]) if data.get("tracklist") else 0
        fields = {
            "Status": data.get("status", "Unknown"),
            "Released": released,
            "Tracks": tracks,
            "Genres": genres,
            "Country": data.get("country", "Unknown"),
            "Number for sale": data.get("num_for_sale", "0"),
            "Lowest price": price,
            "Master": data.get("master_id", "N/A"),
        }
        footer = {
            "text": f"Requested by {event.author}",
            "img": event.author.get_avatar_url(size=32),
        }
        title = {
            "title": f"[{data['id']}] {data['artists_sort']}: {data['title']}",
            "url": f"{data['uri']}",
        }
        embed = bot.generic_embed_values(title=title, thumbnail=data["images"][0]["uri"], inlines=fields, footer=footer)
        event.channel.send_message(embed=embed)

    @Plugin.command("release rating", "<release_id:int>", group="discogs", metadata={"help": "discogs"})
    def on_release_rating_command(self, event, release_id):
        data = get(self, endpoint=f"releases/{release_id}/rating")["rating"]
        event.channel.send_message(f"Release ``{release_id}`` has an average rating of "
                                   "``{data['average']}`` from ``{data['count']}`` ratings.")

    @Plugin.command("user rating", "<username:str> <release_id:int>", group="discogs", metadata={"help": "discogs"})
    def on_user_rating_command(self, event, release_id, username):
        rating = get(self, endpoint=f"releases/{release_id}/rating/{username}")["rating"]
        star = ":star2:"
        no_star = ":x:"
        if rating:
            thumb = (" :thumbsup:" if rating > 2 else " :thumbsdown:")
        else:
            thumb = " :shrug:"
        event.channel.send_message(star * rating + no_star * (5 - rating) + thumb)

    @Plugin.command("master info", "<master_id:int>", group="discogs", metadata={"help": "discogs"})
    def on_master_info_command(self, event, master_id):
        data = get(self, endpoint=f"masters/{master_id}")
        print(data)

    @Plugin.command("master versions", "<master_id:int> [raw_params:str...]", group="discogs", metadata={"help": "discogs"})
    def on_master_versions_command(self, event, master_id, raw_params=None):
        optional_params = [
            #"page",
            #"per_page",  # nope
            "format",
            "label",
            "released",
            "country",
            "sort",  # "released", "title", "format", "label", "catno", country"
            "sort_order",  # "asc, desc
        ]
        if raw_params:
            raw_params = dictify(raw_params)
        else:
            raw_params = {}
        params = {key: value for key, value in raw_params.items()
                  if key in optional_params}
        data = get(self, params, f"masters/{master_id}/versions")
        print(data)

    @Plugin.command("artist info", "<artist_id:int>", group="discogs", metadata={"help": "discogs"})
    def on_artist_info_command(self, event, artist_id):
        data = get(self, endpoint=f"artists/{artist_id}")
        print(data)

    @Plugin.command("artist releases", "<artist_id:int> [raw_params:str...]", group="discogs", metadata={"help": "discogs"})
    def on_artist_releases_command(self, event, artist_id, raw_params=None):
        optional_params = [
            "sort",
            "sort_order",
        ]
        if raw_params:
            raw_params = dictify(raw_params)
        else:
            raw_params = {}
        params = {key: value for key, value in raw_params.items()
                  if key in optional_params}
        data = get(self, params, f"artists/{artist_id}/releases")
        print(data)

    @Plugin.command("label info", "<label_id:int>", group="discogs", metadata={"help": "discogs"})
    def on_label_info_command(self, event, label_id):
        data = get(self, endpoint=f"labels/{label_id}")
        print(data)

    @Plugin.command("label releases", "<label_id:int> [raw_params:str...]", group="discogs", metadata={"help": "discogs"})
    def on_label_releases_command(self, event, label_id, raw_params=None):
        optional_params = [
            "page",
            "per_page",
        ]
        if raw_params:
            raw_params = dictify(raw_params)
        else:
            raw_params = {}
        params = {key: value for key, value in raw_params.items()
                  if key in optional_params}
        data = get(self, endpoint=f"labels/{label_id}/releases")
        print(data)

    @Plugin.command("user lists", "<username:str>", group="discogs", metadata={"help": "discogs"})
    def on_label_info_command(self, event, label_id):
        data = get(self, endpoint=f"users/{username}/lists")
        print(data)

    @Plugin.command("list", "<list_id:int>", group="discogs", metadata={"help": "discogs"})
    def on_label_info_command(self, event, label_id):
        data = get(self, endpoint=f"lists/{list_id}")
        print(data)
