from disco.types.message import MessageEmbed as DiscoMessageEmbed
from disco.util.logging import logging

log = logging.getLogger(__name__)

#class generic_embed_values(DiscoMessageEmbed):
#    def __init__(self, bot):
#        if "color" in bot.default_embed_properties:
#            self.color = bot.default_embed_properties["color"]
#
#    def __call__( # could probably do this but with the normal Embed cause lol, I'm stupid
#        author_name=None, 
#        author_url:str=None, 
#        author_icon:str=None, 
#        title:str=None, 
#        url:str=None, 
#        thumbnail:str=None, 
#        description:str=None, 
#        non_inlines:dict=None, 
#        skip_non_inlines=None, 
#        inlines:dict=None, 
#        skip_inlines=True, 
#        image:str=None, 
#        timestamp=None, 
#        footer_text:str=None, 
#        footer_img:str=None, 
#        **kwargs):
#            title = title
#            type = Field(str, default='rich')
#            description = Field(text)
#            url = Field(text)
#            timestamp = Field(datetime)
#            color = Field(int)
#            footer = Field(MessageEmbedFooter)
#            image = Field(MessageEmbedImage)
#            thumbnail = Field(MessageEmbedThumbnail)
#            video = Field(MessageEmbedVideo)
#            author = Field(MessageEmbedAuthor)
#            fields = ListField(MessageEmbedField)

class generic_embed_values:
    def __init__(self, local):
        self.local = local

    def __call__(
            self, # could probably do this but with the normal Embed cause lol, I'm stupid
            author_name=None,
            author_url:str=None,
            author_icon:str=None,
            title:str=None,
            url:str=None,
            thumbnail:str=None,
            description:str=None,
            non_inlines:dict=None,
            skip_non_inlines=None,
            inlines:dict=None,
            skip_inlines=True,
            image:str=None,
            timestamp=None,
            footer_text:str=None,
            footer_img:str=None,
            color:str=None,
            **kwargs):
        generic_embed = DiscoMessageEmbed()
        if color != None:
            generic_embed.color = color
        else:
            generic_embed.color = self.local.embed_values.color
        if author_name != None:
            generic_embed.set_author(name=author_name, url=author_url, icon_url=author_icon)
        if title != None:
            generic_embed.title = str(title)[:256]
            if url != None:
                generic_embed.url = url
        if thumbnail != None:
            generic_embed.set_thumbnail(url=thumbnail)
        if description != None:
            generic_embed.description = str(description)[:2048]
        if non_inlines != None:
            for non_inline_field, data in non_inlines.items():   # {k: mydict[k] for k in list(mydict)[:25]} for 25 entry limit
                if data == None:
                    if skip_non_inlines != None:
                        data = skip_non_inlines
                    else:
                        continue
                generic_embed.add_field(
                    name=str(non_inline_field)[:256],
                    value=str(data)[:1024],
                    inline=False,
                )
        if inlines != None:
            for inline_field, data in inlines.items():
                if data == None:
                    if not skip_inlines:
                        data = skip_inlines
                    #    generic_embed.add_field(name=inline_field[:256], value=data[:1024], inline=True)
                    else:
                        continue
                generic_embed.add_field(
                    name=str(inline_field)[:256],
                    value=str(data)[:1024],
                    inline=True,
                )
        if image != None:
            generic_embed.set_image(url=image)
        if timestamp != None:
            generic_embed.timestamp = timestamp #event.msg.timestamp.isoformat()
        if footer_text != None:
            generic_embed.set_footer(icon_url=footer_img, text=str(footer_text)[:2048])
        return generic_embed