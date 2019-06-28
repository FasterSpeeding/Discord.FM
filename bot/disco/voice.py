from decimal import Decimal
from random import shuffle
from time import sleep, time
from uuid import uuid4
import re
import threading


from disco.bot import Plugin
from disco.bot.command import CommandError, CommandLevels
from disco.types.base import Unset
from disco.util.logging import logging
from disco.voice.playable import YoutubeDLInput, BufferedOpusEncoderPlayable
from disco.voice.player import Player
from disco.voice.client import VoiceException
from fuzzywuzzy.fuzz import partial_ratio
from youtube_dl.utils import DownloadError


from bot.base import bot
from bot.util.misc import api_loop

log = logging.getLogger(__name__)


class MusicPlugin(Plugin):
    def load(self, ctx):
        super(MusicPlugin, self).load(ctx)
        bot.load_help_embeds(self)
        self.guilds = {}
        self.cool_down = {"general": {}, "playlist": {}}
        self.marked_for_delete = []

    def unload(self, ctx):
        for guild in self.guilds.copy().keys():
            self.remove_player(guild)
        bot.unload_help_embeds(self)
        super(MusicPlugin, self).unload(ctx)

    @Plugin.schedule(1)
    def queue_check(self):
        if getattr(self, "guilds", None):
            for guild in self.guilds.copy().keys():
                guild_object = self.guilds.get(guild, None)
                try:
                    guild_object.guild_check()
                except CommandError as e:
                    log.warning(f"CommandError occured during queue_check {e}")
                except Exception as e:
                    log.warning(f"Exception occured during queue_check {e}")
            #    except CommandError as e:
            #        self.channel.send_message  # was self.msg.reply(e)
            #    except IndexError:
            #        continue
            #    except Exception as e:
            #        log.warning(e)

    @Plugin.schedule(5)
    def lonely_check(self):
        if getattr(self, "guilds", None):
            for guild, player in self.guilds.copy().items():
                if not any(not user.bot and
                           user.get_voice_state() is not None and
                           user.get_voice_state().channel_id ==
                           player.player.client.channel_id
                           for user in self.state.guilds[
                               guild].members.copy().values()):
                    try:
                        self.remove_player(guild)
                    except CommandError:
                        continue
            if self.marked_for_delete:
                for guild in self.marked_for_delete.copy():
                    try:
                        self.remove_player(guild)
                    except CommandError:
                        continue
                    self.marked_for_delete.remove(guild)

    def pre_check(self, event):
        if event.channel.is_dm:
            raise CommandError("Voice commands cannot be used "
                               "in DMs.")

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
        return f"{minutes}.{seconds}"

    @Plugin.listen("GuildDelete")
    def on_guild_leave(self, event):
        if isinstance(event.unavailable, Unset):
            if event.id in self.guilds:
                if self.self.guilds[event.id].thread.isAlive():
                    self.self.guilds[event.id].thread_end = True
                    self.self.guilds[event.id].thread.join()
                del self.guilds[event.id]

    @Plugin.command("join", metadata={"help": "voice"})
    def on_join(self, event):
        """
        Make me join a voice channel.
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
                    f"Failed to connect to voice: `{e}`",
                )
            else:
                self.guilds[event.guild.id] = psuedo_queue(
                    self,
                    player=Player(client),
                    guild_id=event.guild.id,
                )
            return

    @Plugin.command("move")  # , metadata={"help": "voice"}
    def on_move(self, event):
        # """
        # Move me to another voice channel (this currently clears play queue).
        # Accepts no arguments.
        # """
        raise CommandError("NotImplemented")
        self.pre_check(event)
        if event.guild.id != 152559372126519296:
            return api_loop(
                event.channel.send_message,
                "This command is currently disabled.",
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

    def remove_player(self, guild_id):
        if guild_id not in self.guilds:
            raise CommandError("I'm not currently playing music here.")
        self.get_player(guild_id).player.disconnect()
        if self.get_player(guild_id).thread.isAlive():
            self.get_player(guild_id).thread_end = True
            self.get_player(guild_id).thread.join()
        del self.guilds[guild_id]

    def same_channel_check(self, event):
        try:
            user_state = event.guild.get_member(event.author).get_voice_state()
        except Exception as e:
            log.warning(e)
            user_state = None
        if user_state is None:
            raise CommandError("You need to be in a voice "
                               "channel to use this command.")
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
            raise CommandError("You need to be in the same "
                               "voice channel to use this command.")

    @Plugin.command("leave", metadata={"help": "voice"})
    def on_leave(self, event):
        """
        Make me leave a voice channel.
        Accepts no arguments.
        """
        self.pre_check(event)
        self.remove_player(event.guild.id)

    @Plugin.command("play", "[play_type:str] [content:str...]", metadata={"help": "voice"})
    def on_play(self, event, play_type="yt", content=None):
        """
        Make me play music from youtube or soundcloud in a voice chat.
        With the optional client argument being required
        when trying to search a client rather than inputting a link.
        If the first argument is in the list:
        "yt" or "youtube", "sc" or "soundcloud",
        then 2nd argument will be searched for and added to the queue.
        If a url fitting one of the supported url formats
        is passed as the first argument then it will be added to the queue.
        Otherwise, this will search youtube and then queue the result.
        """
        url_regs = {
            "yt": (r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)"
                   r"\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?(?P<id>"
                   r"[A-Za-z0-9\-=_]{11})"),
            "sc": (r"^(https?:\/\/)?(www.)?(m\.)?soundcloud"
                   r"\.com\/[\w\-\.]+(\/)+[\w\-\.]+/?$"),
        }
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
                url_found = False
                if play_type not in search_prefixs.keys():
                    if play_type == "override":
                        user_level = self.bot.get_level(event.author)
                        if user_level != CommandLevels.OWNER:
                            return api_loop(
                                event.channel.send_message,
                                "You don't own me",
                            )
                        video_url = content
                        url_found = True
                    elif content is not None:
                        content = f"{play_type} {content}"
                        play_type = "yt"
                    else:
                        content = play_type
                        play_type = "yt"
                elif play_type in search_prefixs.keys() and content is None:
                    return api_loop(
                        event.channel.send_message,
                        "Search argument missing.",
                    )
                for key, reg in url_regs.items():
                    if re.match(reg, content):
                        url_found = True
                        video_url = content
                        play_type = key
                        break
                if not url_found:
                    if play_type in search_prefixs:
                        video_url = search_prefixs[play_type].format(content)
                    else:
                        video_url = search_prefixs["yt"].format(content)
                youtubedl_object = YoutubeDLInput(video_url, command="ffmpeg")
                try:
                    yt_data = self.get_ytdl_values(youtubedl_object.info)
                except DownloadError as e:
                    return api_loop(
                        event.channel.send_message,
                        f"Video not avaliable: {e}",
                    )
                if yt_data["is_live"]:
                    return api_loop(
                        event.channel.send_message,
                        "Livestreams aren't supported",
                    )
                if yt_data["duration"] > 3620:
                    return api_loop(
                        event.channel.send_message,
                        "The maximum supported length is 1 hour.",
                    )
                self.get_player(event.guild.id).append(youtubedl_object)
                api_loop(
                    event.channel.send_message,
                    (f"Added ``{yt_data['title']}`` by ``"
                     f"{yt_data['uploader']}`` using ``{yt_data['source']}``.")
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
                f"Cool down: {cool} seconds left.",
            )

    @Plugin.command("playlist", "<to_shuffle:str> [url:str...]", metadata={"help": "voice"})
    def on_playlist_command(self, event, to_shuffle, url=""):
        """
        Used to load the music from a youtube playlist link.
        If the first argument is in the list:
        "shuffle" or "Shuffle",
        then the playlist will be shuffled before it's loaded.
        Only accepts links that match youtube's link formats.
        and will load the items of the playlist into the player queue.
        """
        self.pre_check(event)
        if to_shuffle != "shuffle" and to_shuffle != "Shuffle":
            url = f"{to_shuffle} {url}"
            to_shuffle = "no"
        if not re.match(r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)"
                        r"\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?(?P<id>"
                        r"[A-Za-z0-9\-=_]{11})", url):
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
                        f"Playlist not found: {e}",
                    )
                if to_shuffle == "shuffle" or to_shuffle == "Shuffle":
                    shuffle(many_object)
                message = api_loop(
                    event.channel.send_message,
                    "Adding music from playlist.",
                )
                for ytdl_object in many_object:
                    try:
                        yt_data = self.get_ytdl_values(ytdl_object.info)
                    except DownloadError as e:
                        continue
                    if yt_data["is_live"]:
                        continue
                    elif yt_data is None or yt_data["duration"] > 3620:
                        continue
                    try:
                        self.get_player(event.guild.id).append(ytdl_object)
                    except CommandError as e:
                        self.cool_down["playlist"][event.guild.id] = False
                        raise e
                    videos_added += 1
                dropped = len(many_object) - videos_added
                api_loop(
                    message.edit,
                    (f"Successfully added {videos_added} videos to queue "
                     f"from playlist and dropped {dropped} videos."),
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
                f"Cool down: {cool} seconds left.",
            )

    @Plugin.command("pause", metadata={"help": "voice"})
    def on_pause(self, event):
        """
        Pause the audio stream.
        Accepts no arguments.
        """
        self.pre_check(event)
        if not self.get_player(event.guild.id).paused:
            self.get_player(event.guild.id).pause()

    @Plugin.command("resume", metadata={"help": "voice"})
    def on_resume(self, event):
        """
        Resume the audio stream.
        Accepts no arguments.
        """
        self.pre_check(event)
        if self.get_player(event.guild.id).paused:
            self.get_player(event.guild.id).resume()

    @Plugin.command("kill", metadata={"help": "voice"})
    def on_kill(self, event):
        """
        Used to reset voice instance ws connection.
        """
        self.pre_check(event)
        self.get_player(event.guild.id).player.client.ws.sock.shutdown()
        api_loop(event.channel.send_message, ":thumbsup:")

    @Plugin.command("skip", metadata={"help": "voice"})
    def on_skip(self, event):
        """
        Play the next song in the queue.
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
                f"Cool down: {cool} seconds left.",
            )

    @Plugin.command("shuffle", metadata={"help": "voice"})
    def on_shuffle(self, event):
        """
        Shuffle the playing queue.
        Accepts no arguments.
        """
        self.pre_check(event)
        shuffle(self.get_player(event.guild.id).queue)
        api_loop(event.channel.send_message, "Queue shuffled.")

    @Plugin.command("playing", metadata={"help": "voice"})
    def on_playing_command(self, event):
        """
        Get information about currently playing song.
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
                (f"Currently playing ``{ytdata['title']}`` by "
                 f"``{ytdata['uploader']}`` with length "
                 f"``{ytdata['time_formated']}`` minutes "
                 f"using ``{ytdata['source']}``."),
            )

    @Plugin.command("next", metadata={"help": "voice"})
    def on_next_command(self, event):
        """
        Get information about next queued song.
        Accepts no arguments.
        """
        self.pre_check(event)
        if not self.get_player(event.guild.id).queue:
            return event.channel.send_message("There aren't any songs queued.")
        ytdata = self.get_ytdl_values(
            self.get_player(event.guild.id).queue[0].metadata,
        )
        event.channel.send_message(
            (f"Next in queue is ``{ytdata['title']}`` by "
             f"``{ytdata['uploader']}`` with length "
             f"``{ytdata['time_formated']}`` minutes "
             f"using ``{ytdata['source']}``.")
        )

    @Plugin.command("queue", "[index:str...]", aliases=["queued"], metadata={"help": "voice"})
    def on_queued_command(self, event, index=None):
        """
        Get information about the queue (search, entry info or length).
        If an integer argument is input, then this will return the queue entry.
        If a string is input, then this command will search the queue.
        Else, if no arguments are passed, this will return the queue's length
        """
        self.pre_check(event)
        player = self.get_player(event.guild.id)
        if not player.queue:
            api_loop(
                event.channel.send_message,
                "There aren't any songs queued right now.",
            )
        elif index is None:
            api_loop(
                event.channel.send_message,
                (f"There are {len(player.queue)} songs queued "
                 f"({self.minutes_format(player.queue_length)} minutes). To "
                 "get a specific song's info, just do this command + index."),
            )
        elif index.replace("-", "").strip(" ").isdigit():  # why replace - ?
            index = int(index.replace("-", "").strip(" "))
            if 0 <= index - 1 <= len(player.queue):
                track = player.queue[index - 1].metadata
                ytdata = self.get_ytdl_values(track)
                api_loop(
                    event.channel.send_message,
                    (f"The song at index ``{index}`` is ``{ytdata['title']}`` "
                     f"by ``{ytdata['uploader']}`` with length "
                     f"``{ytdata['time_formated']}`` minutes and is "
                     f"sourced from ``{ytdata['source']}``."),
                )
            else:
                api_loop(event.channel.send_message, "Invalid index input.")
        else:
            matched_list = dict()
            queue = player.queue
            for item in queue:
                ratio = partial_ratio(item.metadata["title"], index)
                if ratio >= 70:
                    key = f"#{queue.index(item)+1} ({ratio}% match)"
                    matched_list[key] = item.metadata["title"]
            if matched_list:
                footer = {
                    "text": f"Requested by {event.author}",
                    "img": event.author.get_avatar_url(size=32),
                }
                embed = bot.generic_embed_values(
                    title={"title": "Queue search results"},
                    footer=footer,
                    non_inlines={
                        k: matched_list[k] for k in list(matched_list)[-25:]
                    },
                    timestamp=event.msg.timestamp.isoformat(),
                )
                api_loop(event.channel.send_message, embed=embed)
            else:
                api_loop(
                    event.channel.send_message,
                    "No similar items found in queue.",
                )

    @Plugin.command("shift", "<index:int>", metadata={"help": "voice"})
    def on_queue_next_command(self, event, index):
        """
        Move an item that's already queued to the front of the queue by index.
        Only accepts a single integer argument (a queue index).
        """
        self.pre_check(event)
        self.same_channel_check(event)
        player = self.get_player(event.guild.id)
        if 1 < index <= len(player.queue):
            index -= 1
            player.queue.insert(0, player.queue.pop(index))
            ytdata = self.get_ytdl_values(player.queue[0].metadata)
            api_loop(
                event.channel.send_message,
                f"Moved ``{ytdata['title']}`` to the front of the queue."
            )
        else:
            api_loop(event.channel.send_message, "Invalid index input.")

    @Plugin.command("clear queue", metadata={"help": "voice"})
    def on_queue_clear_command(self, event):
        """
        Clear the current player's queue.
        Accepts no arguments.
        """
        self.pre_check(event)
        self.same_channel_check(event)
        if self.get_player(event.guild.id).queue:
            self.get_player(event.guild.id).queue.clear()
            api_loop(event.channel.send_message, "The queue has been cleared.")
        else:
            api_loop(event.channel.send_message, "The queue is already empty.")

    @Plugin.command("insert", "[index:int]")
    def on_queue_insert_command(self, event, index=1):
        pass

    @Plugin.command("remove", "<index:str>", metadata={"help": "voice"})
    def on_remove_command(self, event, index):
        """
        Remove a song from the queue by it's index.
        Accepts no arguments.
        """
        self.pre_check(event)
        self.same_channel_check(event)
        player = self.get_player(event.guild.id)
        if not player.queue:
            api_loop(
                event.channel.send_message,
                "There aren't any songs queued right now.",
            )
        elif str(index).lower() == "all":
            player.queue = list()
            api_loop(event.channel.send_message, "Cleared playing queue.")
        elif (str(index).isdigit() and
              0 <= (int(index) - 1) <= len(player.queue)):
            yt_dl_object = player.pop(int(index) - 1)
            ytdata = self.get_ytdl_values(yt_dl_object.metadata)
            api_loop(
                event.channel.send_message,
                f"Removed index ``{ytdata['title']}`` at index ``{index}``.",
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
        if self.queue:
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
        if self.queue:
            try:
                piped = self.queue[0].pipe(BufferedOpusEncoderPlayable)
                self.player.queue.append(piped)
            except AttributeError as e:
                if str(e) == "python3.6: undefined symbol: opus_strerror":
                    sleep(10)
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
            elif (not self.waiting and not self.queue and
                  time() - self.start_time
                  >= self.current_length + self.paused_length + 2):
                self.player.disconnect()
                self.thread_end = True
                if id not in self.bot.marked_for_delete:
                    self.bot.marked_for_delete.append(self.id)
            if self.thread_end:
                break
            sleep(self.interval)
