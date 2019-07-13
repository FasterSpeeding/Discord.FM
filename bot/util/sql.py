from time import sleep
import copy
import logging
import os


from disco.bot.command import CommandError
from sqlalchemy import (
    create_engine as spawn_engine, PrimaryKeyConstraint,
    Column, exc, ForeignKey)
from sqlalchemy.dialects.mysql import (
    TEXT, BIGINT, INTEGER, VARCHAR,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import (
    scoped_session, sessionmaker, relationship)
# from pymysql import err



log = logging.getLogger(__name__)


Base = declarative_base()


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
        default="fm.",
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
            prefix: str = "fm.",
            last_seen: str = None,
            name: str = None,
            lyrics_limit: int = 3):
        self.guild_id = guild_id
        self.prefix = prefix
        self.last_seen = last_seen
        self.name = name
        self.lyrics_limit = lyrics_limit

    def __repr__(self):
        return (f"users({self.guild_id}: {self.name})")


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
        return f"users({self.user_id}: {self.last_username})"


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
        return f"aliases({self.guild_id}: {self.alias})"


class sql_instance:
    __tables__ = (
        guilds,
        users,
        friends,
        aliases,
    )
    tables = {}
    session = None
    engine = None

    def __init__(
            self,
            adapter=None,
            server=None,
            username=None,
            password=None,
            database=None,
            args=None):
        self.session, self.engine = self.create_engine_session_safe(
            adapter,
            server,
            username,
            password,
            database,
            args,
        )
        self.check_tables()
        self.spwan_binded_tables()

    @staticmethod
    def __call__(function, *args, **kwargs):
        tries = 0
        root_exception = None
        while True:
            if tries >= 5:
                raise SQLTimeout(
                    "Failed to access data.",
                    root_exception,
                )
            try:
                return function(*args, **kwargs)
            except exc.OperationError as e:
                sleep(2)
                tries += 1
                root_exception = e

    def spwan_binded_tables(self):
        for table in self.__tables__:
            table_copy = copy.deepcopy(table)
            table_copy.query = self.session.query_property()
            setattr(self, table.__tablename__, table_copy)

    @staticmethod
    def check_engine_tables(tables, engine):
        for table in tables:
            if not engine.dialect.has_table(engine, table.__tablename__):
                log.info(f"Creating table {table.__tablename__}")
                table.__table__.create(engine)

    def check_tables(self):
        return self.check_engine_tables(self.__tables__, self.engine)

    def add(self, object):
        self(self.session.add, object)
        self.flush()

    def delete(self, object):
        self(self.session.delete, object)
        self.flush()

    def flush(self):
        self(self.session.flush)

    @staticmethod
    def create_engine(
            adapter="mysql+pymysql",
            server=None,
            username=None,
            password=None,
            database=None,
            args=None):

        # Pre_establish settings
        if server:
            settings = (f"{adapter}://{username}:{password}"
                        f"@{server}/{database}?charset=utf8mb4")
            args = (args or {})
        else:
            if not os.path.exists("data"):
                os.makedirs("data")
            args = {}
            settings = "sqlite+pysqlite:///data/data.db"

        # Connect to server
        return spawn_engine(
            settings,
            encoding="utf8",
            pool_recycle=3600,
            pool_pre_ping=True,
            echo=False,
            connect_args=args,
        )

    def create_engine_session_safe(
            self,
            adapter="mysql+pymysql",
            server=None,
            username=None,
            password=None,
            database=None,
            args=None):

        engine = self.create_engine(
            adapter,
            server,
            username,
            password,
            database,
            args,
        )

        # Verify connection.
        try:
            engine.execute("SELECT 1")
        except exc.OperationalError as e:
            log.warning("Unable to connect to database, "
                        "defaulting to sqlite: " + str(e))
            engine = self.create_engine()

        session = scoped_session(
            sessionmaker(
                autocommit=True,
                autoflush=True,
                bind=engine,
            ),
        )
        return session, engine
