import os

import click
from flask import Flask
from flask.cli import with_appcontext
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ProcessPoolExecutor
from sqlalchemy.schema import MetaData

db = SQLAlchemy(metadata=MetaData(schema='public'))
scheduler = APScheduler()

def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        SQLALCHEMY_TRACK_MODIFICATIONS = False,
        SCHEDULER_API_ENABLED = True,
        SCHEDULER_EXECUTORS = {
            'default': ProcessPoolExecutor()
        }
    )

    os.makedirs(app.instance_path, exist_ok=True)

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    db.init_app(app)
    
    app.config.from_mapping(
        SCHEDULER_JOBSTORES = {
            'default': SQLAlchemyJobStore(url=app.config.get('SQLALCHEMY_DATABASE_URI'))
        },
    )
    scheduler.init_app(app)
    scheduler.start()
    
    from musicgamez import main
    app.register_blueprint(main.bp)
    app.add_url_rule("/", endpoint="index")
    
    @app.before_first_request
    def load_tasks():
        from musicgamez.main import tasks

    app.cli.add_command(init_db_command)

    return app

def init_db():
    db.drop_all()
    db.create_all()
    from musicgamez.main.models import BeatSite
    db.session.add(BeatSite(name='Beat Saber',
                            url_base='https://beatsaver.com/beatmap/',
                            url_suffix=''))
    db.session.add(BeatSite(name='osu!',
                            url_base='https://osu.ppy.sh/beatmapsets/',
                            url_suffix=''))
    db.session.commit()

@click.command("init-db")
@with_appcontext
def init_db_command():
    """Clear existing data and create new tables."""
    init_db()
    click.echo("Initialized the database.")

