from disco.types.message import MessageEmbed as DiscoMessageEmbed
from disco.util.logging import logging

log = logging.getLogger(__name__)


class generic_embed_values:
    def __init__(self, local):
        self.__local = local
        self.__fields = {attr: getattr(self, attr) for attr in
                         dir(self) if not attr.startswith("__")}

    def __call__(
            self,
            **kwargs):
        embed = DiscoMessageEmbed()
        if ("color" not in kwargs and
                self.__local.embed_values.color):
            self.color(
                embed,
                self.__local.embed_values.color,
            )
        for key, value in kwargs.items():
            function = getattr(self, key, None)
            if function:
                function(embed, value)
            else:
                log.warning("Invalid argument given to "
                            f"embed: '{key}'.")
        return embed

    def color(self, embed, data):
        embed.color = data

    def author(self, embed, data):
        embed.set_author(
            name=data.get("name", None),
            url=data.get("url", None),
            icon_url=data.get("icon", None),
        )

    def title(self, embed, data):
        embed.title = str(data["title"])[:256]
        if data.get("url", None):
            embed.url = data["url"]
        elif self.__local.embed_values.url:
            embed.url = self.__local.embed_values.url

    def thumbnail(self, embed, data):
        embed.set_thumbnail(url=data)

    def description(self, embed, data):
        embed.description = str(data)[:2048]

    def inlines(self, embed, data):
        self.__field(embed, data, True)

    def non_inlines(self, embed, data):
        self.__field(embed, data, False)

    def __field(self, embed, data, inline):
        skip = data.pop("skip_inlines", None)
        for key in list(data.keys())[:25]:
            value = data[key]
            if not value:
                if skip:
                    value = skip
                else:
                    continue
            embed.add_field(
                name=str(key)[:256],
                value=str(value)[:1024],
                inline=inline,
            )

    def image(self, embed, data):
        embed.set_image(url=data)

    def timestamp(self, embed, data):
        embed.timestamp = data

    def footer(self, embed, data):
        text = data.get("text", None)
        if text:
            text = str(text)[:2048]
        embed.set_footer(
            icon_url=data.get("img", None),
            text=text,
        )
