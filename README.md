# Discord.FM
Discord.FM is a Discord designed for retrieving statistics and data from Last.fm whilest facilitating more community elements through allowing people to link their Last.FM accounts.

# Installation

## Prerequisites

This bot is designed primarily with Python 3.6 in mind in a Linux environment.

To install the neccessary Python modules use the following command in the bot's folder: 

``pip3 install -r requirements.txt``

In-order to enable voice functionality, you need to install ffmpeg3 and keep youtube-dl up-to-date for voice functionality to work using:

``sudo apt-get install ffmpeg3`` | ``pip3 install --upgrade youtube-dl``

Whilest you could just randomly run ``pip3 install --upgrade youtube-dl`` to keep youtube-dl up-to-date, this bot is designed to update youtube-dl on startup and I'd recommend following the releases at their [github repository](https://github.com/ytdl-org/youtube-dl).

## Setup

### Discord access
To enable the bot, you will have to create a new Discord application [here](https://discordapp.com/developers/applications/me), create and setup a bot user under it, and take it's token and put that into the following disco entry in config.json.

```
"disco": {
    "token": "INSERT_TOKEN_HERE"
  },
```

### API access
In-order enable the relevant API functions, you will have to setup accounts and get api keys or IDs and secrets from the relative websites, enable access to the relevent end points and put them into the relevant api entries in config.json.

```
"api": {
  "last_key": "https://www.last.fm/api/account/create",
  "google_key": "https://console.developers.google.com/apis/library/youtube.googleapis.com",
  "spotify_ID": "https://developer.spotify.com/dashboard/",
  "spotify_secret": "https://developer.spotify.com/dashboard/"
},
```

## Optional

Whilest this bot will default to making and running off an sqlite database (``data/sql_database.db``), you can hock this bot up to an SQL server by adding the following to config.json with your own data inserted:

```json
"sql": {
  "database": "database_name",
  "server": "ip_address:port",
  "user": "root",
  "password": "password"
}
```

In-order to enable SQL access over SSL, you can add a combination of the following values and the paths to the relative files to sql in config.json.

```json
"ca_path": "path/to/certificate/authority/public/key.pem",
"cert_path": "path/to/client/certificate/path/private/certificate.pem",
"key_path": "path/to/client/public/key.pem
```

\* Whenever `config.json` is mentioned in this document, this is interchangable with `config.yaml`.

# Discord

You can add a public version of this bot to your server using this [invite link](https://discordapp.com/oauth2/authorize?client_id=560984860634644482&scope=bot&permissions=104197184) and can stop by our support server using this [invite link](https://discordapp.com/invite/jkEXqVd) if you'd like to chat or have any issues.
