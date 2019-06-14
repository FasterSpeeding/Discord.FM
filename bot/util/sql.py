from time import sleep
import logging
import os


from disco.bot.command import CommandError
from sqlalchemy import (
    create_engine, PrimaryKeyConstraint,
    create_engine, Column, exc, ForeignKey)
from sqlalchemy.dialects.mysql import *
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import (
    scoped_session, sessionmaker, relationship)
# from pymysql import err


from bot.base import bot

log = logging.getLogger(__name__)

if bot.local.sql.server:
    sql = bot.local.sql
    server_payload = (f"mysql+pymysql://{sql.user}:"
                      f"{sql.password}@{sql.server}/{sql.database}")
    log.info(f"Connecting to SQL server @{sql.server}.")
    args = sql.args
else:
    if not os.path.exists("logs"):
        os.makedirs("data")
    log.info("Defaulting to local SQL database.")
    args = {}
    server_payload = "sqlite+pysqlite:///data/database.db"
engine = create_engine(
    server_payload,
    encoding="utf8",
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False,
    connect_args=args,
)
try:
    engine.execute("SELECT 1")
except exc.OperationalError as e:
    log.warning(f"Failed to access server, defaulting to local instance: {e}")
    if not os.path.exists("data"):
        os.makedirs("data")
    engine = create_engine(
        "sqlite+pysqlite:///data/database.db",
        encoding="utf8",
        pool_recycle=3600,
        pool_pre_ping=True,
        echo=False,
    )
db_session = scoped_session(
    sessionmaker(
        autocommit=True,
        autoflush=True,
        bind=engine,
    ),
)

Base = declarative_base()
Base.query = db_session.query_property()


class SQLexception(CommandError):
    def __init__(self, msg, original_exception):
        self.msg = msg
        self.original_exception = original_exception


class guilds(Base):
    __tablename__ = "guilds"
    guild_id = Column(
        "guild_id",
        BIGINT(18, unsigned=True),
        nullable=False,
        primary_key=True,
    )
    prefix = Column(
        "prefix",
        TEXT,
        nullable=False,
        default=(bot.local.disco.bot.commands_prefix or "fm."),
    )
    last_seen = Column(
        "last_seen",
        TEXT,
        nullable=True,
    )
    name = Column(
        "name",
        TEXT,
        nullable=True,
    )
    lyrics_limit = Column(
        "lyrics_limit",
        INTEGER,
        nullable=False,
        default=3,
    )
    alias_list = relationship(
        "aliases",
        cascade="all, delete-orphan",
        backref="guilds",
    )

    def __init__(
            self,
            guild_id: int,
            prefix: str = (bot.local.disco.bot.commands_prefix or "fm."),
            last_seen: str = None,
            name: str = None,
            lyrics_limit: int = 3):
        self.guild_id = guild_id
        self.prefix = prefix
        self.last_seen = last_seen
        self.name = name
        self.lyrics_limit = lyrics_limit

    def __repr__(self):
        return (f"users({self.guild_id}, {self.prefix}, "
                f"{self.last_seen}, {self.name})")


periods = {
    0: "overall",
    7: "7day",
    1: "1month",
    3: "3month",
    6: "6month",
    12: "12month",
}


class users(Base):
    __tablename__ = "users"
    user_id = Column(
        "user_id",
        BIGINT(18, unsigned=True),
        nullable=False,
        primary_key=True,
    )
    last_username = Column(
        "last_username",
        TEXT,
        nullable=True,
    )
    period = Column(
        "period",
        INTEGER,
        nullable=False,
        default=0,
    )
    friends = relationship(
        "friends",
        cascade="all, delete-orphan",
        backref="users",
    )
    aliases = relationship(
        "aliases",
        cascade="all, delete-orphan",
        backref="users",
    )

    def __init__(
            self,
            user_id: int,
            last_username: str = None,
            period: int = 0):
        self.user_id = user_id
        self.last_username = last_username
        self.period = period

    def __repr__(self):
        return f"users({self.user_id}, {self.last_username}, {self.period})"


class friends(Base):
    __tablename__ = "friends"
    __table_args__ = (
        PrimaryKeyConstraint(
            "master_id",
            "slave_id",
        ),
    )

    master_id = Column(
        "master_id",
        BIGINT(18, unsigned=True),
        ForeignKey(users.user_id, ondelete="CASCADE"),
        nullable=False,
    )
    slave_id = Column(
        "slave_id",
        BIGINT(18, unsigned=True),
        nullable=False,
    )

    def __init__(self, master_id: int, slave_id: int, index: int = None):
        self.master_id = master_id
        self.slave_id = slave_id

    def __repr__(self):
        return f"users({self.master_id} : {self.slave_id})"


class aliases(Base):
    __tablename__ = "aliases"
    __table_args__ = (
        PrimaryKeyConstraint(
            "guild_id",
            "alias",
        ),
    )
    user_id = Column(
        "user_id",
        BIGINT(18, unsigned=True),
        ForeignKey(users.user_id, ondelete="CASCADE"),
        nullable=False,
    )
    guild_id = Column(
        "guild_id",
        BIGINT(18, unsigned=True),
        ForeignKey(guilds.guild_id, ondelete="CASCADE"),
        nullable=False,
    )
    alias = Column(
        "alias",
        VARCHAR(30),
        nullable=False,
    )

    def __init__(self, user_id, guild_id, alias):
        self.user_id = user_id
        self.guild_id = guild_id
        self.alias = alias

    def __repr__(self):
        return f"aliases({self.guild_id}, {self.user_id}, {self.alias})"


def handle_sql(f, *args, **kwargs):
    fail = 0
    while True:
        if fail >= 10:
            raise SQLexception(
                "Failed at accessing data, please try again later.",
                previous_exception,
            )
        try:
            return f(*args, **kwargs)
        except exc.OperationalError as e:
            log.warning(f"SQL call failed: {e}")
            sleep(2)
            fail += 1
            previous_exception = e


for table in (friends, guilds, users, aliases):
    if not engine.dialect.has_table(engine, table.__tablename__):
        log.info(f"Didn't find {table.__tablename__} "
                 "table, creating new instance.")
        table.__table__.create(engine)

if __name__ == "__main__":
    conn = engine.connect()
    print(dir(conn))
