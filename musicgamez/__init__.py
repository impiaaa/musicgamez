import logging


class ColorFormatter(logging.Formatter):
    def format(self, record):
        record.color = {logging.CRITICAL: 35,  # magenta
                        logging.ERROR:    31,  # red
                        logging.WARNING:  33,  # yellow
                        logging.INFO:     32,  # green
                        logging.DEBUG:    34   # blue
                        }.get(record.levelno, 0)
        return super().format(record)


h = logging.StreamHandler()
h.setFormatter(
    ColorFormatter(
        fmt='{asctime} {name}[{threadName}] \033[{color}m{levelname}\033[0m: {message}',
        style='{'))
logging.basicConfig(handlers=[h])
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)


import apscheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
import click
from flask_apscheduler import APScheduler
from flask_babel import Babel, get_locale
from flask.cli import with_appcontext
from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
import os
from sqlalchemy import orm, event
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import MetaData
from werkzeug.exceptions import HTTPException
from flask_babel import _


metadata = MetaData(schema='public')
db = SQLAlchemy(metadata=metadata)
scheduler = APScheduler()
babel = Babel()


def render_error(e):
    return render_template('error.html', name=e.name,
                           code=e.code, description=e.description), e.code


def entity_not_found(e):
    return render_template('error.html', name="Not Found", code=404,
                           description=_("The requested entity was not found. If you entered the URL manually please check your spelling and try again.")), 404


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SCHEDULER_API_ENABLED=True,
        SCHEDULER_EXECUTORS={
            # This is going to bite me later. Threads in Python are bound by the
            # Global Interpreter Lock, which means threads can only be preempted
            # during OS calls like I/O or sleep, not execution. Normally this
            # isn't too much of a problem, but fingerprinting will take
            # significant non-I/O processing time, so web requests could be
            # delayed while fingerprinting occurs.
            # There is a work-around to the GIL: multiprocessing, using
            # processes instead of threads. Unfortunately, too much
            # infrastructure (APScheduler, SQLAlchemy connection pools) depend
            # on a shared memory space between threads.
            'default': ThreadPoolExecutor()
        },
        LANGUAGES=['en']
    )
    app.jinja_options['trim_blocks'] = True
    app.jinja_options['lstrip_blocks'] = True
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

    os.makedirs(app.instance_path, exist_ok=True)

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    db.app = app
    db.init_app(app)

    app.config.from_mapping(
        SCHEDULER_JOBSTORES={
            #SQLAlchemyJobStore(url=app.config.get('SQLALCHEMY_DATABASE_URI'))
            'default': MemoryJobStore()
        },
    )
    if scheduler.running:
        scheduler.shutdown()
    scheduler.init_app(app)
    scheduler.start()

    from musicgamez import main
    app.register_blueprint(main.bp)

    app.register_error_handler(HTTPException, render_error)
    app.register_error_handler(orm.exc.NoResultFound, entity_not_found)

    @app.before_first_request
    def load_tasks():
        from musicgamez.main import tasks

    babel.init_app(app)

    app.jinja_env.filters['translate_artist'] = translate_artist
    app.jinja_env.filters['translate_recording'] = translate_recording

    app.cli.add_command(init_db_command)
    app.cli.add_command(import_partybus_stream_permission)
    app.cli.add_command(import_creatorhype_stream_permission)
    app.cli.add_command(fetch_beatsaber_command)
    app.cli.add_command(fetch_beastsaber_command)
    app.cli.add_command(fetch_beatsaber_single_command)
    app.cli.add_command(fetch_osu_command)

    return app


@babel.localeselector
def select_locale():
    return request.accept_languages.best_match(db.app.config['LANGUAGES'])


def translate_entity(type, typetype, idcol, id, typegid, name):
    result = db.session.query(type)\
        .join(typetype)\
        .filter(idcol==id,
            type.locale==get_locale().language,
            type.primary_for_locale==True,
            typetype.gid==typegid)\
        .one_or_none()
    return result.name if result else name


def translate_artist(artist):
    from mbdata.models import ArtistAlias, ArtistAliasType, ArtistCreditName
    if isinstance(artist, ArtistCreditName):
        artist_id = artist.artist_id
    else:
        artist_id = artist.id
    return translate_entity(ArtistAlias,
        ArtistAliasType,
        ArtistAlias.artist_id,
        artist_id,
        '894afba6-2816-3c24-8072-eadb66bd04bc',
        artist.name)


def translate_recording(recording):
    from mbdata.models import Recording, RecordingAlias, RecordingAliasType
    return translate_entity(RecordingAlias,
        RecordingAliasType,
        RecordingAlias.recording_id,
        recording.id,
        '5d564c8f-97de-3572-94bb-7f40ad661499',
        recording.name)


def init_db():
    #db.drop_all()
    db.create_all()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Clear existing data and create new tables."""
    init_db()
    click.echo("Initialized the database.")


@click.command("import-partybus-stream-permission")
@with_appcontext
def import_partybus_stream_permission():
    """Import artist streaming permissions from Partybus's spreadsheet"""
    from musicgamez.main.tasks import import_partybus_stream_permission
    import_partybus_stream_permission()


@click.command("import-creatorhype-stream-permission")
@with_appcontext
def import_creatorhype_stream_permission():
    """Import artist streaming permissions from creatorhype.com's spreadsheet"""
    from musicgamez.main.tasks import import_creatorhype_stream_permission
    import_creatorhype_stream_permission()


@click.command("fetch-beatsaber")
@with_appcontext
def fetch_beatsaber_command():
    """Manually import maps from Beat Saber."""
    scheduler.shutdown()
    from musicgamez.main.tasks import fetch_beatsaber, match_with_string
    fetch_beatsaber()
    try:
        scheduler.shutdown()
    except apscheduler.schedulers.SchedulerNotRunningError:
        pass
    match_with_string()


@click.command("fetch-osu")
@with_appcontext
def fetch_osu_command():
    """Manually import maps from osu!."""
    scheduler.shutdown()
    from musicgamez.main.tasks import fetch_osu, match_with_string
    fetch_osu()
    try:
        scheduler.shutdown()
    except apscheduler.schedulers.SchedulerNotRunningError:
        pass
    match_with_string()


@click.command("fetch-beatsaber-single")
@click.option('-i', '--id')
@with_appcontext
def fetch_beatsaber_single_command(id):
    scheduler.shutdown()
    from musicgamez.main.tasks import fetch_beatsaber_single, match_with_string, urlopen_with_ua
    import json
    session = db.create_scoped_session()
    gametrack = json.load(
        urlopen_with_ua(
            "https://beatsaver.com/api/maps/detail/" +
            id))
    fetch_beatsaber_single(session, gametrack)
    try:
        scheduler.shutdown()
    except apscheduler.schedulers.SchedulerNotRunningError:
        pass
    match_with_string()

@click.command("fetch-beastsaber")
@with_appcontext
def fetch_beastsaber_command():
    scheduler.shutdown()
    from musicgamez.main.tasks import fetch_beastsaber, match_with_string
    fetch_beastsaber()
    try:
        scheduler.shutdown()
    except apscheduler.schedulers.SchedulerNotRunningError:
        pass
    match_with_string()

