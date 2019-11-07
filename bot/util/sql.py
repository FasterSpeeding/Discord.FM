from time import sleep
import copy
import logging
import os


from disco.bot.command import CommandError
from disco.types.base import BitsetMap, BitsetValue
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


Base = declarative_base()


class SQLexception(CommandError):
    def __init__(self, msg, original_exception):
        self.msg = msg
        self.original_exception = original_exception


class BaseWrapper:
    __slots__ = ("sql_obj", "_found")

    def __init__(self, sql_obj):
        self.sql_obj = sql_obj

    def __repr__(self):
        return f"wrapped({self.sql_obj})"

    @property
    def found(self):
        try:
            return self._found
        except AttributeError:
            self._found = False

        return self._found


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

    def __init__(self, master_id: int, slave_id: int):
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
        USER: ("user", ("guilds", "get")),
        DM: ("channel", ("channels", "get")),
        GUILD: ("guild", ("guilds", "get")),
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


class cfilter(Base):
    __tablename__ = "cfilter"
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
        self.status = int(status)
        data = self._search_kwargs(channel=channel, guild=guild, user=user)
        self.target = data["target"]
        self.target_type = data["target_type"]

    @staticmethod
    def _search_kwargs(channel=None, guild=None, user=None, **kwargs):
        if not (channel or user or guild):
            raise TypeError("Missing targeted object.")

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


class wrappedfilter(BaseWrapper):
    __slots__ = ("sql_obj", "_status", "_found")

    @property
    def status(self):
        try:
            return self._status
        except AttributeError:
            if hasattr(self, "sql_obj") and self.sql_obj.status:
                value = self.sql_obj.status
            else:
                value = 0
            self._status = Filter_Status(value)

        return self._status

    def deletable(self):
        return self.sql_obj.status == 0

    def edit_status(self, value):
        self.sql_obj.status = int(value)
        self.status.value = int(value)

    def blacklist_status(self):
        return self.status.blacklisted

    def whitelist_status(self):
        if self.status.whitelisted:
            return True

        return not self.get_count(
            Filter_Status.map.WHITELISTED,
            target_type=self.sql_obj.target_type,
        )

    def get_count(self, status, target_type=None, sql_obj=None):
        return (sql_obj or self.sql_obj).query.filter(
            cfilter.status.op("&")(status) == status and
            (not target_type or filter.target_type == target_type)).count()


class Reference:
    defaulted_attrs = {}
    ignored_attrs = []
    renamed_attrs = {}
    type_conversion = {}

    def run_through_columns(self, source_table, target_table):
        # Hack around to let us spawn an empty instance.
        if hasattr(target_table, "__init__"):
            del target_table.__init__

        for column in source_table.query.all():
            new_column = target_table()
            self.run_through_attrs(column, new_column)
            target_table.query.session.add(new_column)

    def run_through_attrs(self, source_column, target_column):
        for attr in {*source_column.__table__.columns.keys(),
                     *self.defaulted_attrs.keys()}:
            if attr in self.ignored_attrs:
                continue

            target_attr = self.renamed_attrs.get(attr, attr)
            value = getattr(
                source_column, attr, self.defaulted_attrs.get(attr))
            # TODO: explicity continue on unset item
            converter = self.type_conversion.get(attr)
            if converter:
                value = converter(value)

            setattr(target_column, target_attr, value)


class sql_instance:
    __tables__ = (
        guilds,
        users,
        friends,
        aliases,
        cfilter,
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
            self, drivername=None, host=None,
            port=None, username=None, password=None,
            database=None, query=None, args=None, local_path=None):
        self.session, self.engine = self.create_engine_session_safe(
            drivername, host, port,
            username, password, database,
            query, args, local_path)
        self.check_tables()
        self.spwan_binded_tables()

    @property
    def tables(self):
        for table in self.__tables__:
            table = getattr(self, table.__tablename__, None)
            if table:
                yield table

    @property
    def log(self):
        try:
            return self._log
        except AttributeError:
            self._log = logging.getLogger(self.__class__.__name__)

        return self._log

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

    def check_tables(self):
        for table in self.__tables__:
            if not self.engine.dialect.has_table(
                    self.engine, table.__tablename__):
                self.log.info(f"Creating table {table.__tablename__}")
                table.__table__.create(self.engine)

    @staticmethod
    def softget(obj, *args, **kwargs):
        if hasattr(obj, "_search_kwargs"):
            search_kwargs = obj._search_kwargs(*args, **kwargs)
        else:
            search_kwargs = kwargs

        data = obj.query.filter_by(**search_kwargs).first()
        if data:
            obj = obj._wrap(data) if hasattr(obj, "_wrap") else data
            obj._found = True
            return

        obj = (getattr(obj, "_get_wrapped", None) or obj)(*args, **kwargs)
        obj._found = False
        return obj

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
            self.log.warning(f"Unknown engine {driver}, "
                             "unable to get ssl status")
            return

        position = self.session.connection()
        for attr in check_map:
            if not position:
                break

            position = getattr(position, attr, None)
        self.log.info(f"SQL SSL status: {position or 'unknown'}")
        return position

    @staticmethod
    def create_engine(
            drivername=None, host=None, port=None,
            username=None, password=None, database=None,
            query=None, args=None, local_path=None):

        # Pre_establish settings
        if host:
            settings = SQLurl(
                drivername, username, password,
                host, port, database, query)
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
            self, drivername=None, host=None, port=None,
            username=None, password=None, database=None,
            query=None, args=None, local_path=None):

        engine = self.create_engine(
            drivername, host, port,
            username, password, database,
            query, args, local_path)

        # Verify connection.
        try:
            engine.execute("SELECT 1")
        except exc.OperationalError as e:
            self.log.warning("Unable to connect to database, "
                             f"defaulting to sqlite: {e}")
            engine = self.create_engine(local_path=local_path)

        session = scoped_session(
            sessionmaker(
                autocommit=self.autocommit,
                autoflush=self.autoflush,
                bind=engine,
            ),
        )
        return session, engine

    @classmethod
    def spawn_disconnected_instance(cls, tables=None):
        if tables:
            cls.__tables__ = tables

        del cls.__init__
        return cls()

    def create_engine_table_strict(self, *args, tables=None, **kwargs):
        self.engine = self.create_engine(*args, **kwargs)
        try:
            self.engine.execute("SELECT 1")
        except exc.OperationalError as e:
            raise SQLexception(f"Unable to connect to source database {e}", e)

        self.session = scoped_session(
            sessionmaker(
                autocommit=self.autocommit,
                autoflush=self.autoflush,
                bind=self.engine,
            ),
        )

    def transfer_from_source(self, *args, tables=None, **kwargs):
        # Initalise the target db session.
        self.source_inst = self.spawn_disconnected_instance(tables=tables)
        self.source_inst.create_engine_table_strict(*args, **kwargs)
        self.source_inst.spwan_binded_tables()

        # Run through every initalised table.
        for table in self.source_inst.tables:
            if not self.source_inst.engine.dialect.has_table(
                self.source_inst.engine, table.__tablename__):
               continue

            getattr(table, "_reference", Reference()).run_through_columns(
                table, getattr(self, table.__tablename__))

if __name__ == "__main__":
    test_instance = sql_instance(local_path="data/test.db")
    test_instance.transfer_from_source()
    #        (self, drivername=None, host=None, port=None,
    #        username=None, password=None, database=None,
    #        query=None, args=None, local_path=None):
        