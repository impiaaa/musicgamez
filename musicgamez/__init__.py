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
logging.getLogger('requests_oauthlib.oauth2_session').setLevel(logging.INFO)


import apscheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
import click
from flask import Flask, render_template, request, url_for, redirect
from flask.cli import with_appcontext
from flask_apscheduler import APScheduler
from flask_babel import _, Babel, Domain, get_locale
from flask_dance.consumer import OAuth2ConsumerBlueprint, OAuth2Session
from flask_dance.consumer.storage import MemoryStorage
from flask_sqlalchemy import SQLAlchemy
from mbdata.models import ArtistAlias, ArtistAliasType, ArtistCreditName
from mbdata.models import Recording, RecordingAlias, RecordingAliasType
from oauthlib.oauth2 import BackendApplicationClient
import os
from sqlalchemy import orm, event
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import MetaData
from werkzeug.exceptions import HTTPException


metadata = MetaData(schema='public')
db = SQLAlchemy(metadata=metadata)
scheduler = APScheduler()
babel = Babel()
relationship_domain = Domain(domain="relationships")


class OAuth2SessionWithUserAgent(OAuth2Session):
    def __init__(self, *args, **kwargs):
        super(OAuth2SessionWithUserAgent, self).__init__(*args, **kwargs)
        from musicgamez import db
        self.headers["User-Agent"] = db.app.config["USER_AGENT"]


class OAuth2ConsumerBlueprintWithLogout(OAuth2ConsumerBlueprint):
    def __init__(self, *args, **kwargs):
        super(OAuth2ConsumerBlueprintWithLogout, self).__init__(*args, **kwargs)
        self.add_url_rule(
            rule="/{bp.name}/logout".format(bp=self),
            endpoint="logout",
            view_func=self.logout
        )
    
    def logout(self):
        del self.token
        if self.redirect_url:
            next_url = self.redirect_url
        elif self.redirect_to:
            next_url = url_for(self.redirect_to)
        else:
            next_url = "/"
        logging.getLogger("flask_dance.consumer.oauth2").debug("next_url = %s", next_url)
        return redirect(next_url)


oauth_osu = OAuth2ConsumerBlueprintWithLogout('osu', __name__,
    base_url="https://osu.ppy.sh/api/v2/",
    token_url="https://osu.ppy.sh/oauth/token",
    authorization_url="https://osu.ppy.sh/oauth/authorize",
    scope="public",
    session_class=OAuth2SessionWithUserAgent
)
oauth_osu.from_config = {
    "session.client_id": "OSU_CLIENT_ID",
    "session.client_secret": "OSU_CLIENT_SECRET"
}
oauth_osu_noauth = OAuth2ConsumerBlueprint('osu-noauth', __name__,
    base_url="https://osu.ppy.sh/api/v2/",
    token_url="https://osu.ppy.sh/oauth/token",
    scope="public",
    session_class=OAuth2SessionWithUserAgent,
    client=BackendApplicationClient(None),
    storage=MemoryStorage
)
oauth_osu_noauth.from_config = {
    "session.client_id": "OSU_CLIENT_ID",
    "session.client_secret": "OSU_CLIENT_SECRET"
}
oauth_musicbrainz = OAuth2ConsumerBlueprintWithLogout('musicbrainz', __name__,
    base_url="https://musicbrainz.org/ws/2/",
    token_url="https://musicbrainz.org/oauth2/token",
    authorization_url="https://musicbrainz.org/oauth2/authorize",
    scope="collection",
    session_class=OAuth2SessionWithUserAgent,
    token_url_params={"include_client_id": True},
    redirect_to='main.mycollection'
)
oauth_musicbrainz.from_config = {
    "session.client_id": "MUSICBRAINZ_CLIENT_ID",
    "session.client_secret": "MUSICBRAINZ_CLIENT_SECRET",
    "client_secret": "MUSICBRAINZ_CLIENT_SECRET"
}
oauth_spotify = OAuth2ConsumerBlueprintWithLogout(
    "spotify",
    __name__,
    scope="playlist-read-collaborative user-library-read playlist-read-private",
    base_url="https://api.spotify.com/v1/",
    authorization_url="https://accounts.spotify.com/authorize",
    token_url="https://accounts.spotify.com/api/token",
    redirect_to='main.mycollection',
    session_class=OAuth2SessionWithUserAgent,
)
oauth_spotify.from_config["client_id"] = "SPOTIFY_OAUTH_CLIENT_ID"
oauth_spotify.from_config["client_secret"] = "SPOTIFY_OAUTH_CLIENT_SECRET"

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
        LANGUAGES=['en'],
        USER_AGENT="MusicGamez/0.1 ( https://musicgamez.info )",
        PERPAGE=36
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

    app.register_blueprint(oauth_osu, url_prefix="/oauth")
    app.register_blueprint(oauth_musicbrainz, url_prefix="/oauth")
    app.register_blueprint(oauth_spotify, url_prefix="/oauth")

    app.jinja_env.filters['translate_artist'] = translate_artist
    app.jinja_env.filters['translate_recording'] = translate_recording
    app.jinja_env.filters['translate_relationship'] = translate_relationship
    app.jinja_env.globals['get_locale'] = get_locale
    
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
    return translate_entity(RecordingAlias,
        RecordingAliasType,
        RecordingAlias.recording_id,
        recording.id,
        '5d564c8f-97de-3572-94bb-7f40ad661499',
        recording.name)


def translate_relationship(link_type):
    return relationship_domain.gettext(link_type.link_phrase)


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

