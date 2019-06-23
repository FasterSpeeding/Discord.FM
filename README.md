# Discord.FM
[![CodeFactor](https://www.codefactor.io/repository/github/lmbyrne/discord.fm/badge)](https://www.codefactor.io/repository/github/lmbyrne/discord.fm)
[![Codacy Badge](https://api.codacy.com/project/badge/Grade/2f11838ea1b241aa84df62826b897a4b)](https://www.codacy.com/app/LMByrne/Discord.FM?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=LMByrne/Discord.FM&amp;utm_campaign=Badge_Grade)
[![Total alerts](https://img.shields.io/lgtm/alerts/g/LMByrne/Discord.FM.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/LMByrne/Discord.FM/alerts/)
[![Python 3.6](https://img.shields.io/badge/python-3.6-blue.svg)](https://www.python.org/downloads/release/python-360/)

Discord.FM is a Discord bot designed for retrieving statistics and data from Last.fm, whilst facilitating more community elements by allowing people to link their Last.FM accounts.

## Installation

### Prerequisites

This bot is designed primarily with Python 3.6 and a Linux environment in mind, and may not function properly in other conditions.

To install the necessary Python modules, use the following command in the bot's folder (with `sudo` not being required in all environments): 

``sudo pip3 install -r requirements.txt``

In-order to enable voice functionality, you need to install ffmpeg3 and keep youtube-dl up-to-date using:

``sudo apt-get install ffmpeg3`` | ``pip3 install --upgrade youtube-dl``

Whilst you could just randomly run ``pip3 install --upgrade youtube-dl`` to keep youtube-dl up-to-date, this bot is designed to update youtube-dl on startup and I'd recommend following the releases at their [github repository](https://github.com/ytdl-org/youtube-dl).

### Setup

#### Discord access
To enable the bot, you will have to create a new Discord application [here](https://discordapp.com/developers/applications/me), create and setup a bot user under it, and take its token and put that into the following disco entry in config.json.

```json
"disco": {
    "token": "INSERT_TOKEN_HERE"
  },
```

#### API access
In-order enable the relevant API functions, you will have to setup accounts and get api keys or IDs and secrets from the relative websites, enable access to the relevant end points and put them into the relevant api entries in config.json.

```json
"api": {
  "last_key": "https://www.last.fm/api/account/create",
  "google_key": "https://console.developers.google.com/apis/library/youtube.googleapis.com",
  "spotify_ID": "https://developer.spotify.com/dashboard/",
  "spotify_secret": "https://developer.spotify.com/dashboard/"
},
```

### Optional

Whilst this bot will default to running off an automatically generated local SQLite database (``data/database.db``), you can hook it up to an SQL server by adding the example seen below to config.json with your own data inserted.
For this to function, the SQL server will need to have a database with the name entered in config pre-created, but the bot will automatically create the necessary tables.

```json
"sql": {
  "database": "database_name",
  "server": "ip_address:port",
  "user": "root",
  "password": "password"
}
```

In-order to enable SQL access over SSL, you can pass through the certificate paths to the SQL adapter in the `args` dictionary in `config.json.sql`, with the key for each certificate type varying for custom SQL adapters but being the following for the default adapter.

```json
"sql": {
   "args": {
      "ca": "path/to/certificate/authority/public/key.pem",
      "cert": "path/to/client/certificate/path/private/certificate.pem",
      "key": "path/to/client/public/key.pem"
   }
}
```

\* Whenever `config.json` is mentioned in this document, this is interchangeable with `config.yaml`.

## Discord

You can add a public version of this bot to your server using this [invite link](https://discordapp.com/oauth2/authorize?client_id=560984860634644482&scope=bot&permissions=104197184) and can stop by our support server using this [invite link](https://discordapp.com/invite/jkEXqVd) if you'd like to chat or have any issues.
