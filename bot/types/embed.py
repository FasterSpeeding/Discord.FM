from disco.types.message import MessageEmbed as DiscoMessageEmbed
from disco.util.logging import logging

log = logging.getLogger(__name__)


class generic_embed_values:
    def __init__(self, local):
        self.local = local

    def __call__(
            self,
            author_name=None,
            author_url: str = None,
            author_icon: str = None,
            title: str = None,
            url: str = None,
            thumbnail: str = None,
            description: str = None,
            non_inlines: dict = None,
            skip_non_inlines: bool = None,
            inlines: dict = None,
            skip_inlines: bool = True,
            image: str = None,
            timestamp=None,
            footer_text: str = None,
            footer_img: str = None,
            color: str = None,
            **kwargs):
        generic_embed = DiscoMessageEmbed()
        if color:
            generic_embed.color = color
        else:
            generic_embed.color = self.local.embed_values.color
        if author_name:
            generic_embed.set_author(
                name=author_name,
                url=author_url,
                icon_url=author_icon,
            )
        if title:
            generic_embed.title = str(title)[:256]
            if url:
                generic_embed.url = url
        if thumbnail:
            generic_embed.set_thumbnail(url=thumbnail)
        if description:
            generic_embed.description = str(description)[:2048]
        if non_inlines:
            for non_inline_field, data in non_inlines.items():  # [:25]
                if data is None:
                    if skip_non_inlines:
                        data = skip_non_inlines
                    else:
                        continue
                generic_embed.add_field(
                    name=str(non_inline_field)[:256],
                    value=str(data)[:1024],
                    inline=False,
                )
        if inlines:
            for inline_field, data in inlines.items():  # [:25]
                if data is None:
                    if not skip_inlines:
                        data = skip_inlines
                    else:
                        continue
                generic_embed.add_field(
                    name=str(inline_field)[:256],
                    value=str(data)[:1024],
                    inline=True,
                )
        if image:
            generic_embed.set_image(url=image)
        if timestamp:
            generic_embed.timestamp = timestamp
        if footer_text:
            generic_embed.set_footer(
                icon_url=footer_img,
                text=str(footer_text)[:2048],
            )
        return generic_embed
