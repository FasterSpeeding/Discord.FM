from time import sleep
import copy
import logging
import os


from disco.bot.command import CommandError
from disco.types.base import BitsetMap, BitsetValue, enum
from sqlalchemy import (
    create_engine as spawn_engine, PrimaryKeyConstraint,
    Column, exc, ForeignKey,
)
from sqlalchemy.dialects.mysql import (
    TEXT, BIGINT, INTEGER, VARCHAR,
)
from sqlalchemy.engine.url import URL as SQLurl
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import (
    scoped_session, sessionmaker, relationship,
)


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
        nullable=True,
    )
    lyrics_limit = Column(
        "lyrics_limit",
        INTEGER,
        nullable=True,
    )
    alias_list = relationship(
        "aliases",
        cascade="all, delete-orphan",
        backref="guilds",
    )

    def __init__(
            self,
            guild_id: int,
            prefix: str = None,
            lyrics_limit: int = None):
        self.guild_id = guild_id
        self.prefix = prefix
        self.lyrics_limit = lyrics_limit

    def __repr__(self):
        return (f"guilds {self.guild_id}")


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
        nullable=True,
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
            period: int = None):
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


class Filter_Status(BitsetValue):
    class map(BitsetMap):
        WHITELISTED = 1 << 0
        BLACKLISTED = 1 << 1
        _all = {"WHITELISTED": WHITELISTED, "BLACKLISTED": BLACKLISTED}

    def __int__(self):
        return self.value


class filter_types:
    USER = 0
    GUILD = 1
    DM = 2
    _type_associations = {
        USER: ["user", ["guilds", "get"]],
        DM: ["channel", ["channels", "get"]],
        GUILD: ["guild", ["guilds", "get"]],
    }

    @staticmethod
    def get(state, target, target_type):
        target_type = getattr(filter_types, target_type.upper(), None)

        result = filter_types._type_associations.get(target_type, None)
        if not result:
            raise CommandError("Invalid type.")

        key, path = result
        for attr in path:
            state = getattr(state, attr)

        target = state(target)
        if not target:
            raise CommandError(f"{key.capitalize()} not found.")

        return key, target


class filter(Base):
    __tablename__ = "filter"
    __table_args__ = (
        PrimaryKeyConstraint(
            "target",
            "target_type",
        ),
    )
    target = Column(
        "target",
        BIGINT(18, unsigned=True),
        nullable=False,
    )
    target_type = Column(
        "target_type",
        INTEGER(1, unsigned=True),
        nullable=False,
    )
    status = Column(
        "status",
        INTEGER(1, unsigned=True),
        nullable=False,
    )

    def __init__(self, status=0, channel=None, guild=None, user=None):
        data = self._search_kwargs(channel=channel, guild=guild, user=user)
        self.target = data["target"]
        self.target_type = data["target_type"]
        self.status = int(status)

    @staticmethod
    def _search_kwargs(channel=None, guild=None, user=None, **kwargs):
        assert channel or user or guild
        if channel:
            if channel.is_dm:
                target = channel.id
                target_type = filter_types.DM
            else:
                target = channel.guild_id
                target_type = filter_types.GUILD
        elif user:
            target = user.id
            target_type = filter_types.USER
        elif guild:
            target = guild.id
            target_type = filter_types.GUILD

        return {"target": target, "target_type": target_type}

    @classmethod
    def _get_wrapped(cls, *args, **kwargs):
        return wrappedfilter(cls(*args, **kwargs))

    @staticmethod    
    def _wrap(obj):
        return wrappedfilter(obj)

    def __repr__(self):
        return f"filter_status({self.target})"


class wrappedfilter:
    __slots__ = ("filter", "_status")

    def __init__(self, filter):
        self.filter = filter

    def __call__(self, *args, **kwargs):
        return self.filter(*args, **kwargs)

    def __repr__(self):
        return f"wrapped({self.filter})"

    @property
    def status(self):
        if not hasattr(self, "_status"):
            self._status = Filter_Status(self.filter.status or 0)

        return self._status

    def edit_status(self, value):
        self.filter.status = int(value)
        self._status = Filter_Status(int(value))

    def blacklist_status(self):
        return self.status.blacklisted

    def whitelist_status(self):
        if self.status.whitelisted:
           return True

        return not bool(self.get_count(Filter_Status.map.WHITELISTED))

    def get_count(self, status, sql_obj=None):
        return (sql_obj or self.filter).query.filter(
            filter.status.op("&")(status) == status).count()


class sql_instance:
    __tables__ = (
        guilds,
        users,
        friends,
        aliases,
        filter,
    )
    autocommit = True
    autoflush = True
    session = None
    engine = None
    _driver_ssl_checks = {  # starts from self.session.connection()
        "pymysql": ("connection", "connection", "ssl"),
        "psycopg2": ("connection", "connection", "info", "ssl_in_use"),
    }

    def __init__(
            self,
            drivername=None,
            host=None,
            port=None,
            username=None,
            password=None,
            database=None,
            query=None,
            args=None,
            local_path=None):
        self.session, self.engine = self.create_engine_session_safe(
            drivername,
            host,
            port,
            username,
            password,
            database,
            query,
            args,
            local_path,
        )
        self.check_tables()
        self.spwan_binded_tables()

    @staticmethod
    def __call__(function, *args, **kwargs):
        tries = 0
        root_exception = None
        while True:
            if tries >= 5:
                raise SQLexception(
                    "Failed to access data.",
                    root_exception,
                )
            try:
                return function(*args, **kwargs)
            except exc.OperationalError as e:
                sleep(2)
                tries += 1
                root_exception = e

    def spwan_binded_tables(self):
        for table in self.__tables__:
            table_copy = copy.deepcopy(table)
            table_copy.query = self.session.query_property()
            setattr(self, table.__tablename__, table_copy)

    @staticmethod
    def check_engine_table(table, engine):
        if not engine.dialect.has_table(engine, table.__tablename__):
            log.info(f"Creating table {table.__tablename__}")
            table.__table__.create(engine)

    def check_tables(self):
        for table in self.__tables__:
            self.check_engine_table(table, self.engine)

    @staticmethod
    def softget(obj, *args, **kwargs):
        if hasattr(obj, "_search_kwargs"):
            search_kwargs = obj._search_kwargs(*args, **kwargs)
        else:
            search_kwargs = kwargs

        data = obj.query.filter_by(**search_kwargs).first()
        if data:
            return obj._wrap(data) if hasattr(obj, "_wrap") else data, True

        obj = (getattr(obj, "_get_wrapped", None) or obj)(*args, **kwargs)
        return obj, False

    def add(self, object):
        self(self.session.add, object)
        self.flush()

    def delete(self, object):
        self(self.session.delete, object)
        self.flush()

    def flush(self):
        self(self.session.flush)

    def commit(self):
        self(self.session.commit)
        self.flush()

    def ssl_check(self):
        driver = self.session.connection().engine.driver
        check_map = self._driver_ssl_checks.get(driver)
        if not check_map:
            log.warning(f"Unknown engine {driver}, unable to get sql")
            return

        position = self.session.connection()
        for attr in check_map:
            if not position:
                break

            position = getattr(position, attr, None)
        log.info(f"SQL SSL status: {position or 'unknown'}")
        return position

    @staticmethod
    def create_engine(
            drivername=None,
            host=None,
            port=None,
            username=None,
            password=None,
            database=None,
            query=None,
            args=None,
            local_path=None):

        # Pre_establish settings
        if host:
            settings = SQLurl(
                drivername,
                username,
                password,
                host,
                port,
                database,
                query,
            )
            args = (args or {})
        else:
            if not os.path.exists("data"):
                os.makedirs("data")
            args = {}
            settings = f"sqlite+pysqlite:///{local_path or 'data/data.db'}"

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
            drivername=None,
            host=None,
            port=None,
            username=None,
            password=None,
            database=None,
            query=None,
            args=None,
            local_path=None):

        engine = self.create_engine(
            drivername,
            host,
            port,
            username,
            password,
            database,
            query,
            args,
            local_path,
        )

        # Verify connection.
        try:
            engine.execute("SELECT 1")
        except exc.OperationalError as e:
            log.warning("Unable to connect to database, "
                        "defaulting to sqlite: " + str(e))
            engine = self.create_engine(local_path=local_path)

        session = scoped_session(
            sessionmaker(
                autocommit=self.autocommit,
                autoflush=self.autoflush,
                bind=engine,
            ),
        )
        return session, engine
