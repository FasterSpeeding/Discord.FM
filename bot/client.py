# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2020-2024, Faster Speeding
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

import datetime
import pathlib
import typing

import hikari
import tanchan.components.config
import tanjun
import yuyo
import yuyo.asgi
import yuyo.modals

from . import config as config_
from . import utility

if typing.TYPE_CHECKING:
    from hikari import traits as hikari_traits

    class _GatewayBotProto(
        hikari.EventManagerAware, hikari.RESTAware, hikari.ShardAware, hikari.Runnable, typing.Protocol
    ):
        """Protocol of a cacheless Hikari Gateway bot."""


def build_gateway_bot(*, config: config_.FullConfig | None = None) -> tuple[_GatewayBotProto, tanjun.Client]:
    """Build a gateway bot with a bound Discord.FM client.

    Parameters
    ----------
    config
        The configuration to use.

    Returns
    -------
    tuple[hikari.impl.GatewayBot, tanjun.Client]
        The gateway bot and Discord.FM client.
    """
    if config is None:
        config = config_.FullConfig.from_env()

    print("Initiating with standard Hikari impl")  # noqa: T201
    bot = hikari.GatewayBot(
        config.tokens.bot,
        logs=config.log_level,
        intents=config.intents,
        cache_settings=hikari.impl.CacheSettings(components=config.cache),
    )

    client = _build(
        tanjun.Client.from_gateway_bot(
            bot,
            mention_prefix=config.mention_prefix,
            declare_global_commands=False if config.hot_reload else config.declare_global_commands,
        ),
        config,
    )
    return bot, client


def _build(client: tanjun.Client, config: config_.FullConfig) -> tanjun.Client:
    (
        client.set_hooks(tanjun.AnyHooks().set_on_parser_error(utility.on_parser_error).set_on_error(utility.on_error))
        .add_prefix(config.prefixes)
        .set_type_dependency(config_.FullConfig, config)
        .set_type_dependency(config_.Tokens, config.tokens)
    )

    tanchan.components.config.Config(enable_slash_command=True, eval_guild_ids=config.eval_guilds).add_to_client(client)
    yuyo.ComponentClient.from_tanjun(client)
    yuyo.ModalClient.from_tanjun(client)
    # TODO: support passing raw modules here?
    client.load_modules("tanchan.components")
    assert isinstance(client.rest.http_settings, hikari.impl.HTTPSettings)
    assert isinstance(client.rest.proxy_settings, hikari.impl.ProxySettings)
    utility.SessionManager(
        client.rest.http_settings, client.rest.proxy_settings, "Discord.FM discord bot"
    ).load_into_client(client)

    if config.ptf:
        ptf = config.ptf
        client.set_type_dependency(config_.PTFConfig, ptf)

    if config.owner_only:
        client.add_check(tanjun.checks.OwnerCheck(halt_execution=True))

    if client.shards:
        yuyo.ReactionClient.from_tanjun(client)

    components_dir = pathlib.Path(".") / "bot" / "components"
    if config.hot_reload:
        guilds = (
            config.declare_global_commands if isinstance(config.declare_global_commands, hikari.Snowflake) else None
        )
        redeclare = None if config.declare_global_commands is False else datetime.timedelta(seconds=10)
        (
            tanjun.HotReloader(commands_guild=guilds, redeclare_cmds_after=redeclare)
            .add_directory(components_dir, namespace="bot.components")
            .add_to_client(client)
        )

    else:
        client.load_directory(components_dir, namespace="bot.components")

    return client


def run_gateway_bot(*, config: config_.FullConfig | None = None) -> None:
    """Run a Discord.FM gateway bot.

    Parameters
    ----------
    config
        The configuration to use.
    """
    bot, _ = build_gateway_bot(config=config)
    bot.run()
