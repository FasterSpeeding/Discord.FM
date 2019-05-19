from decimal import Decimal
from random import shuffle
from time import sleep, time
from uuid import uuid4
import threading


from disco.bot import Plugin
from disco.bot.command import CommandError
from disco.types.base import Unset
from disco.util.logging import logging
from disco.voice.playable import YoutubeDLInput, BufferedOpusEncoderPlayable
from disco.voice.player import Player
from disco.voice.client import VoiceException
from fuzzywuzzy.fuzz import partial_ratio
from youtube_dl.utils import DownloadError
try:
    from ujson import load
except ImportError:
    from json import load


from bot.base.base import bot
from bot.util.misc import api_loop


log = logging.getLogger(__name__)


class Queue_handler_thread(object):
    def __init__(self, bot, interval):
        self.interval = interval
        self.bot = bot
        self.thread_end = bot.threads_end
        self.thread = threading.Thread(target=self.queue_check)
        self.thread.daemon = True
        self.thread.start()

    def queue_check(self):
        while True:
            for guild in list(self.bot.guilds):  # [:]
                guild_object = self.bot.guilds.get(guild, None)
                try:
                    guild_object.guild_check()
                except CommandError as e:
                    log.warning("CommandError occured during queue_check {}".format(e))
                    log.warning(dir(guild_object))
                except Exception as e:
                    log.warning("CommandError occured during queue_check {}".format(e))
            #    except CommandError as e:
            #        self.bot.channel.send_message  # was self.bot.msg.reply(e) ??? this is broken
            #    except IndexError:
            #        continue
            #    except Exception as e:
            #        log.warning(e)
            if self.thread_end:
                log.info("Ending queue_check thread.")
                break
            sleep(self.interval)


class lonely_thread_handler(object):
    def __init__(self, bot, interval):
        self.interval = interval
        self.bot = bot
        self.thread_end = bot.threads_end
        self.marked_for_delete = list()
        self.thread = threading.Thread(target=self.lonely_check)
        self.thread.daemon = True
        self.thread.start()

    def lonely_check(self):
        while True:  # do a copy of the guilds list to avoid issues plus index error check
            for guild in self.bot.guilds:
                to_pass = False
                for x, y in self.bot.state.guilds[guild].members.items():
                    if (y.get_voice_state() is not None and
                            y.id != self.bot.state.me.id and
                            y.get_voice_state().channel_id == self.bot.get_player(
                                self.bot.state.guilds[guild].id).player.client.channel_id):
                        to_pass = True
                        break
                if to_pass:
                    continue  # sometime, something, this isn't very scalable.
                if self.bot.guilds[guild].thread.isAlive():
                    self.bot.guilds[guild].thread_end = True
                    self.bot.guilds[guild].thread.join()
                self.bot.guilds[guild].player.disconnect()
                self.marked_for_delete.append(guild)
            to_delete = self.marked_for_delete[:]
            for guild in to_delete:
                if guild in self.bot.guilds:
                    if self.bot.guilds[guild].thread.isAlive():
                        self.bot.guilds[guild].thread_end = True
                        self.bot.guilds[guild].thread.join()
                    del self.bot.guilds[guild]
            self.marked_for_delete = list(
                set(
                    self.marked_for_delete
                ) - set(to_delete)
            )
            if self.thread_end:
                log.info("Ending lonely check thread.")
                break
            sleep(self.interval)


class MusicPlugin(Plugin):
    def load(self, ctx):
        super(MusicPlugin, self).load(ctx)
        bot.local.get(
            self,
            "owners",
        )
        bot.init_help_embeds(self)
        bot.custom_prefix_init(self)
        self.guilds = {}
        self.cool_down = {"general": {}, "playlist": {}}
        self.recursive = False
        self.threads_end = False
        self.ok = Queue_handler_thread(self, interval=1)
        self.lonely = lonely_thread_handler(self, interval=5)

    def unload(self, ctx):
        self.threads_end = True
        self.thread.join()
        for guild in self.guilds.values():
            guild.thread_end = True
            guild.thread.join()
        self.status_thread.thread.join()

    def pre_check(self, event):
        if event.channel.is_dm:
            raise CommandError("Voice commands aren't allowed in the forbidden lands.")

    def get_ytdl_values(self, data):
        duration = data.get("duration", None)
        if duration is not None:
            time_formated = self.minutes_format(duration)
        else:
            time_formated = "N/A"
        title = data.get("title", None)
        uploader = data.get("uploader", "N/A")
        yt_source = data.get("extractor", "N/A")
        is_live = data.get("is_live", False)
        return {
            "duration": duration,
            "title": title,
            "uploader": uploader,
            "source": yt_source,
            "is_live": is_live,
            "time_formated": time_formated,
        }

    def minutes_format(self, seconds):
        time_formated = Decimal(seconds)/60
        minutes = round(time_formated - (time_formated % 1), 0)
        seconds = format(int(round(time_formated % 1 * 60, 0)), "02d")
        return "{}.{}".format(minutes, seconds)

    @Plugin.listen("GuildDelete")
    def on_guild_leave(self, event):
        if type(event.unavailable) is Unset:
            if guild_id in self.guilds:
                if self.self.guilds[event.id].thread.isAlive():
                    self.self.guilds[event.id].thread_end = True
                    self.self.guilds[event.id].thread.join()
                del self.guilds[event.id]

    @Plugin.command("join")
    def on_join(self, event):
        """
        Voice Make me join a voice channel.
        Accepts no arguments.
        """
        self.pre_check(event)
        state = event.guild.get_member(event.author).get_voice_state()
        if not state:
            return api_loop(
                event.channel.send_message,
                "You must be in a voice channel to use that command.",
            )
        if event.guild.id not in self.guilds:
            try:
                client = state.channel.connect(mute=False)
            except VoiceException as e:
                return api_loop(
                    event.channel.send_message,
                    "Failed to connect to voice: `{}`".format(e),
                )
            else:
                self.guilds[event.guild.id] = psuedo_queue(
                    self,
                    player=Player(client),
                    guild_id=event.guild.id,
                )
            return

    @Plugin.command("move")
    def on_move(self, event):
        # """
        # Voice Move me to another voice channel (this currently clears play queue).
        # Accepts no arguments.
        # """
        raise CommandError("NotImplemented")
        self.pre_check(event)
        if event.guild.id != 152559372126519296:
            return api_loop(
                event.channel.send_message,
                "This command is currently B R O K E and crippingly out of date.",
            )
        self.get_player(event.guild.id).thread.isAlive()
        state = event.guild.get_member(event.author).get_voice_state()
        if not state:
            return api_loop(
                event.channel.send_message,
                "You must be in a voice channel to use that command.",
            )

    def get_player(self, guild_id):
        if guild_id not in self.guilds:
            raise CommandError("I'm not currently playing music here.")
        return self.guilds.get(guild_id)

    def same_channel_check(self, event):
        try:
            user_state = event.guild.get_member(event.author).get_voice_state()
        except Exception as e:
            log.warning(e)
            user_state = None
        if user_state is None:
            raise CommandError("You need to be in a voice channel to use this command.")
        else:
            bot_state = self.get_player(
                event.guild.id,
            ).player.client.channel_id
            try:
                same_channel = bot_state == user_state.channel_id
            except CommandError as e:
                raise e
            except Exception as e:
                log.warning(e)
            if not same_channel:
                raise CommandError("You need to be in the same voice channel to use this command.")

    @Plugin.command("leave")
    def on_leave(self, event):
        """
        Voice Make me leave a voice channel.
        Accepts no arguments.
        """
        self.pre_check(event)
        self.get_player(event.guild.id).thread_end = True
        if self.get_player(event.guild.id).thread.isAlive():
            self.get_player(event.guild.id).thread.join()
        self.get_player(event.guild.id).player.disconnect()
        self.lonely.marked_for_delete.append(int(event.guild.id))

    @Plugin.command("play", "[type:str] [content:str...]")
    def on_play(self, event, type="yt", content=None):
        """
        Voice Make me play the audio stream from youtube or soundcloud in a voice chat.
        With the optional client argument being required when trying to search a client rather than inputting a link.
        If the first argument is in the list:
        "yt" or "youtube", "sc" or "soundcloud",
        then 2nd argument will be searched for on the relevant site before being piped into the player queue.
        If a url fitting either the youtube or soundcloud formats.
        is passed as the first argument then it will be piped into the player queue.
        Otherwise, this will search youtube and then pipe the result into the player queue.
        """
        urls = {
            "https://www.youtube.com/watch?v=": "yt",
            "https://youtube.com/watch?v=": "yt",
            "https://youtu.be": "yt",
            "https://soundcloud.com": "sc",
        }  # /watch?v= /watch?v=
        search_prefixs = {
            "youtube": "ytsearch:{}",
            "yt": "ytsearch:{}",
            "soundcloud": "scsearch:{}",
            "sc": "scsearch:{}",
        }
        self.pre_check(event)
        if event.guild.id not in self.cool_down:
            self.cool_down[event.guild.id] = {}
        if (event.author.id not in self.cool_down["general"] or
                time() - self.cool_down["general"][event.author.id] >= 1):
            if (event.guild.id not in self.cool_down["playlist"] or
                    not self.cool_down["playlist"][event.guild.id]):
                self.cool_down["general"][event.author.id] = time()
                if event.guild.get_member(event.author).get_voice_state():
                    self.on_join(event)
                self.same_channel_check(event)
                if type not in search_prefixs.keys():
                    if type == "override":
                        if event.author.id not in self.owners:
                            return api_loop(
                                event.channel.send_message,
                                "You don't own me",
                            )
                        video_url = content
                        url_found = True
                        pass
                    elif content is not None:
                        content = "{} {}".format(type, content)
                        type = "yt"
                    else:
                        content = type
                        type = "yt"
                elif type in search_prefixs.keys() and content is None:
                    return api_loop(
                        event.channel.send_message,
                        "Search (content) argument missing.",
                    )
                if "url_found" not in locals():
                    url_found = False
                for url, index in urls.items():
                    if url in content:
                        url_found = True
                        video_url = content
                        type = index
                if not url_found:
                    if type in search_prefixs:
                        video_url = search_prefixs[type].format(content)
                    else:
                        video_url = search_prefixs["yt"].format(content)
                youtubedl_object = YoutubeDLInput(video_url, command="ffmpeg")
                try:
                    yt_data = self.get_ytdl_values(youtubedl_object.info)
                except DownloadError as e:
                    return api_loop(
                        event.channel.send_message,
                        "Video not avaliable: {}".format(e),
                    )
                if yt_data["is_live"]:
                    return api_loop(
                        event.channel.send_message,
                        "Livestreams aren't supported",
                    )
                elif yt_data["duration"] > 3620:
                    return api_loop(
                        event.channel.send_message,
                        "The maximum supported length is 1 hour.",
                    )
                self.get_player(event.guild.id).append(youtubedl_object)
                api_loop(
                    event.channel.send_message,
                    "Added ``{}`` by ``{}`` using ``{}``.".format(
                        yt_data["title"],
                        yt_data["uploader"],
                        yt_data["source"],
                    ),
                )
            else:
                api_loop(
                    event.channel.send_message,
                    "Currently adding playlist, please wait.",
                )
        else:
            cool = round(
                Decimal(
                    1 - (time() - self.cool_down["general"][event.author.id]),
                ),
            )
            api_loop(
                event.channel.send_message,
                "Cool down: {} seconds left.".format(cool),
            )

    @Plugin.command("playlist", "<to_shuffle:str> [url:str...]")
    def on_playlist_command(self, event, to_shuffle, url=""):
        """
        Voice Used to load the music from a youtube playlist link.
        If the first argument is in the list:
        "shuffle" or "Shuffle",
        then the playlist will be shuffled before it's loaded.
        Only accepts links that match youtube's link formats.
        and will load the items of the playlist into the player queue.
        """
        self.pre_check(event)
        if to_shuffle != "shuffle" and to_shuffle != "Shuffle":
            url = "{} {}".format(to_shuffle, url)
            to_shuffle = "no"
        url_not_found = False
        for url_format in ("https://www.youtube.com/playlist?list=",
                "https://youtube.com/playlist?list=", "https://youtu.be"):
            if url_format in url:
                url_not_found = True
        if not url_not_found:
            return api_loop(
                event.channel.send_message,
                "Invalid youtube playlist link.",
            )
        if event.guild.get_member(event.author).get_voice_state():
            self.on_join(event)
        self.same_channel_check(event)
        if (event.author.id not in self.cool_down["general"] or
                time() - self.cool_down["general"][event.author.id] >= 1):
            if (event.guild.id not in self.cool_down["playlist"] or
                    not self.cool_down["playlist"][event.guild.id]):
                self.cool_down["playlist"][event.guild.id] = True
                self.cool_down["general"][event.author.id] = time()
                videos_added = 0
                many_object = YoutubeDLInput.many(url, command="ffmpeg")
                try:
                    many_object = list(many_object)
                except Exception as e:
                    return api_loop(
                        event.channel.send_message,
                        "Playlist not found: {}".format(e),
                    )
                if to_shuffle == "shuffle" or to_shuffle == "Shuffle":
                    shuffle(many_object)
                message = api_loop(
                    event.channel.send_message,
                    "Adding music from playlist.",
                )
                for youtubedl_object in many_object:
                    try:
                        yt_data = self.get_ytdl_values(youtubedl_object.info)
                    except DownloadError as e:
                        continue
                    if yt_data["is_live"]:
                        continue
                    elif yt_data is None or yt_data["duration"] > 3620:
                        continue
                    try:
                        self.get_player(event.guild.id).append(youtubedl_object)
                    except CommandError as e:
                        self.cool_down["playlist"][event.guild.id] = False
                        raise e
                    videos_added += 1
                message.edit(
                    "Successfully added {} videos to queue from playlist and dropped {} videos.".format(
                        videos_added,
                        len(many_object) - videos_added,
                    ),
                )
                self.cool_down["playlist"][event.guild.id] = False
            else:
                api_loop(
                    event.channel.send_message,
                    "Still adding previous playlist, please wait.",
                )
        else:
            cool = round(
                Decimal(
                    1 - (time() - self.cool_down["general"][event.author.id]),
                ),
            )
            api_loop(
                event.channel.send_message,
                "Cool down: {} seconds left.".format(cool),
            )

    @Plugin.command("pause")
    def on_pause(self, event):
        """
        Voice Pause the audio stream.
        Accepts no arguments.
        """
        self.pre_check(event)
        if not self.get_player(event.guild.id).paused:
            self.get_player(event.guild.id).pause()

    @Plugin.command("resume")
    def on_resume(self, event):
        """
        Voice Resume the audio stream.
        Accepts no arguments.
        """
        self.pre_check(event)
        if self.get_player(event.guild.id).paused:
            self.get_player(event.guild.id).resume()

    @Plugin.command("kill")
    def on_kill(self, event):
        if event.channel.is_dm:
            return api_loop(
                event.channel.send_message,
                "Voice commands aren't allowed in the forbidden lands.",
            )
        self.get_player(event.guild.id).client.ws.sock.shutdown()

    @Plugin.command("skip")
    def on_skip(self, event):
        """
        Voice Play the next song in the playing queue.
        Accepts no arguments.
        """
        self.pre_check(event)
        if (event.author.id not in self.cool_down["general"] or
                time() - self.cool_down["general"][event.author.id] >= 2):
            self.get_player(event.guild.id).skip()
            self.cool_down["general"][event.author.id] = time()
        else:
            cool = round(
                Decimal(
                    2 - (time() - self.cool_down["general"][event.author.id]),
                ),
            )
            return event.channel.send_message(
                "Cool down: {} seconds left.".format(cool),
            )

    @Plugin.command("shuffle")
    def on_shuffle(self, event):
        """
        Voice Shuffle the playing queue.
        Accepts no arguments.
        """
        self.pre_check(event)
        shuffle(self.get_player(event.guild.id).queue)
        api_loop(event.channel.send_message, "Queue shuffled.")

    @Plugin.command("playing")
    def on_playing_command(self, event):
        """
        Voice Get information about currently playing song.
        Accepts no arguments.
        """
        self.pre_check(event)
        now_playing = self.get_player(event.guild.id).player.now_playing
        if now_playing is None:
            api_loop(
                event.channel.send_message,
                "Not currently playing anything",
            )
        else:
            ytdata = self.get_ytdl_values(
                self.get_player(event.guild.id).player.now_playing.metadata,
            )
            api_loop(
                event.channel.send_message,
                "Currently playing ``{}`` by ``{}`` with length ``{}`` minutes using ``{}``.".format(
                    ytdata["title"],
                    ytdata["uploader"],
                    ytdata["time_formated"],
                    ytdata["source"],
                ),
            )

    @Plugin.command("next")
    def on_next_command(self, event):
        """
        Voice Get information about next queued song.
        Accepts no arguments.
        """
        self.pre_check(event)
        if len(self.get_player(event.guild.id).queue) == 0:
            return event.channel.send_message("There aren't any songs queued.")
        ytdata = self.get_ytdl_values(
            self.get_player(event.guild.id).queue[0].metadata,
        )
        event.channel.send_message(
            "Next in queue is ``{}`` by ``{}`` with length ``{}`` minutes using ``{}``.".format(
                ytdata["title"],
                ytdata["uploader"],
                ytdata["time_formated"],
                ytdata["source"],
            ),
        )

    @Plugin.command("queue", "[index:str...]", aliases=("queued", ))
    def on_queued_command(self, event, index=None):
        """
        Voice Get the information of a certain song in the queue or the amount of songs in the queue.
        If an integer argument is input, then this will return the relevant queue entry.
        If a string is input, then the string will be used to search for queue entry titles.
        Otherwise, if no arguments are passed, this will return the current length of the queue.
        """
        self.pre_check(event)
        if len(self.get_player(event.guild.id).queue) == 0:
            api_loop(
                event.channel.send_message,
                "There aren't any songs queued right now.",
            )
        elif index is None:
            api_loop(
                event.channel.send_message,
                "There are {} songs queued ({} minutes). To get a specific song's info, just do this command + index.".format(
                    len(self.get_player(event.guild.id).queue),
                    self.minutes_format(self.get_player(
                        event.guild.id,
                    ).queue_length),
                ),
            )
        elif (index.replace("-", "").strip(" ").isdigit() and
              0 <= (int(index.replace("-", "").strip(" ")) - 1) <=
                len(self.get_player(event.guild.id).queue)):
            ytdata = self.get_ytdl_values(
                self.get_player(event.guild.id).queue[
                    int(index.replace("-", "").strip(" ")) - 1
                ].metadata,
            )
            api_loop(
                event.channel.send_message,
                "The song at index ``{}`` is ``{}`` by ``{}`` with length ``{}`` minutes and is sourced from ``{}``.".format(
                    int(index.replace("-", "").strip(" ")),
                    ytdata["title"],
                    ytdata["uploader"],
                    ytdata["time_formated"],
                    ytdata["source"],
                ),
            )
        elif index.replace("-", "").isdigit():
            api_loop(event.channel.send_message, "Invalid index input.")
        else:
            matched_list = dict()
            for item in self.get_player(event.guild.id).queue:
                ratio = partial_ratio(item.metadata["title"], index)
                if ratio >= 70:
                    matched_list["#{} ({}% match)".format(
                        self.get_player(event.guild.id).queue.index(item)+1,
                        ratio,
                    )] = item.metadata["title"]
            if len(matched_list) != 0:
                embed = bot.generic_embed_values(
                    title="Queue search results",
                    footer_text="Requested by {}".format(event.author),
                    non_inlines={
                        k: matched_list[k] for k in list(matched_list)[-25:]
                    },
                    footer_img=event.author.get_avatar_url(size=32),
                    timestamp=event.msg.timestamp.isoformat(),
                )
                api_loop(event.channel.send_message, embed=embed)
            else:
                api_loop(
                    event.channel.send_message,
                    "No similar items found in queue.",
                )

    @Plugin.command("shift", "<index:int>")
    def on_queue_next_command(self, event, index):
        """
        Voice Move an item that's already queued to the front of the queue by index.
        Only accepts a single integer argument (the index of the target queue item).
        """
        self.pre_check(event)
        self.same_channel_check(event)
        if 1 < index <= len(self.get_player(event.guild.id).queue):
            index -= 1
            self.get_player(event.guild.id).queue.insert(
                0,
                self.get_player(event.guild.id).queue.pop(index),
            )
            ytdata = self.get_ytdl_values(
                self.get_player(event.guild.id).queue[0].metadata,
            )
            api_loop(
                event.channel.send_message,
                "Moved ``{}`` to the front of the queue.".format(
                    ytdata["title"],
                    ytdata["uploader"],
                    ytdata["time_formated"],
                    ytdata["source"],
                ),
            )
        else:
            api_loop(event.channel.send_message, "Invalid index input.")

    @Plugin.command("clear queue")
    def on_queue_clear_command(self, event):
        """
        Voice Clear the current player's queue.
        Accepts no arguments.
        """
        self.pre_check(event)
        self.same_channel_check(event)
        if len(self.get_player(event.guild.id).queue) != 0:
            self.get_player(event.guild.id).queue.clear()
            api_loop(event.channel.send_message, "The queue has been cleared.")
        else:
            api_loop(event.channel.send_message, "The queue is already empty.")

    @Plugin.command("insert", "[index:int]")
    def on_queue_insert_command(self, event, index=1):
        pass

    @Plugin.command("remove", "<index:str>")
    def on_remove_command(self, event, index):
        """
        Voice Remove a song from the queue by it's index.
        Accepts no arguments.
        """
        self.pre_check(event)
        self.same_channel_check(event)
        if len(self.get_player(event.guild.id).queue) == 0:
            api_loop(
                event.channel.send_message,
                "There aren't any songs queued right now.",
            )
        elif str(index).lower() == "all":
            self.get_player(event.guild.id).queue = list()
            api_loop(event.channel.send_message, "Cleared playing queue.")
        elif (str(index).isdigit() and
              0 <= (int(index) - 1) <=
                len(self.get_player(event.guild.id).queue)):
            yt_dl_object = self.get_player(event.guild.id).pop(int(index) - 1)
            ytdata = self.get_ytdl_values(yt_dl_object.metadata)
            api_loop(
                event.channel.send_message,
                "Removed index ``{}`` at index ``{}``.".format(
                    ytdata["title"],
                    index,
                ),
            )
        else:
            api_loop(event.channel.send_message, "Invalid index input.")


class psuedo_queue(object):
    def __init__(self, bot, player, guild_id):
        self.bot = bot
        self.player = player
        self.id = guild_id
        self.clear()
        self.thread = threading.Thread(name=guild_id, target=self.wait_task)
        self.thread.daemon = True
        self.interval = 1
        self.thread_end = False

    def clear(self):
        self.start_time = 0
        self.current_length = 0
        self.paused = False
        self.paused_length = 0
        self.paused_time = 0
        self.queue = list()
        self.current = None
        self.waiting = False
        self.queue_length = 0

    def append(self, yt_dl_object):
        yt_dl_object.id = uuid4()
        yt_dl_object.metadata["OWO_ID"] = yt_dl_object.id
        self.queue.append(yt_dl_object)
        self.queue_length += yt_dl_object.metadata["duration"]

    def pop(self, index):
        yt_object = self.queue.pop(index)
        self.queue_length -= yt_object.metadata["duration"]
        return yt_object

    def guild_check(self):
        if len(self.queue) != 0:
            if (not self.waiting and not self.paused and
                  (self.start_time == 0 or self.current_length < 5 or
                    time() - self.start_time >=
                    self.current_length + self.paused_length - 10)):
                try:
                    piped = self.queue[0].pipe(BufferedOpusEncoderPlayable)
                    self.player.queue.append(piped)
                except AttributeError as e:
                    if str(e) == "python3.6: undefined symbol: opus_strerror":
                        log.warning(e)
                        sleep(10)
                        pass
                    else:
                        log.exception(e)
                except CommandError as e:
                    raise e
                # except MemoryErrors as e:
                except Exception as e:
                    log.exception(e)
                else:
                    self.waiting = True
                if not self.thread.isAlive():
                    log.info("Initiating thread")
                    self.thread.start()

    def skip(self):
        if len(self.queue) != 0:
            try:
                piped = self.queue[0].pipe(BufferedOpusEncoderPlayable)
                self.player.queue.append(piped)
            except AttributeError as e:
                if str(e) == "python3.6: undefined symbol: opus_strerror":
                    sleep(10)
                    pass
                else:
                    log.exception(e)
            except CommandError as e:
                raise e
            #    except MemoryErrors as e:
            except Exception as e:
                log.exception(e)
            else:
                self.waiting = True
                self.player.skip()
        else:
            self.player.skip()

    def pause(self):
        self.player.pause()
        self.paused_time = time()
        self.paused = True

    def resume(self):
        self.player.resume()
        self.paused_length = + time() - self.paused_time
        self.paused = False

    def wait_task(self):
        while True:
            if self.waiting and self.player.now_playing is not None:
                current = self.player.now_playing
                if current.metadata["OWO_ID"] == self.queue[0].id:
                    self.queue_length -= current.metadata["duration"]
                    self.waiting = False
                    self.current = self.queue[0]
                    self.start_time = time()
                    self.current_length = self.current.info["duration"]
                    self.paused = False
                    self.paused_length = 0
                    del self.queue[0]
            elif (not self.waiting and len(self.queue) == 0 and
                  time() - self.start_time
                  >= self.current_length + self.paused_length + 2):
                self.player.disconnect()
                self.thread_end = True
                if int(self.id) not in self.bot.lonely.marked_for_delete:
                    self.bot.lonely.marked_for_delete.append(int(self.id))
            if self.thread_end:
                break
            sleep(self.interval)
