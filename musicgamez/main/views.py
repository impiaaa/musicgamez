from flask import Blueprint
from flask import flash
from flask import g
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from werkzeug.exceptions import abort
from sqlalchemy.sql import func

from musicgamez import db
from musicgamez.main.models import *

bp = Blueprint("main", __name__)

@bp.route("/")
def index():
    return render_template("index.html", recordings=db.session.query(MiniRecordingView))

@bp.route("/browse/genre")
def genres():
    return render_template("genres.html", genres="select musicbrainz.genre.name, count(beatmap.id) from musicbrainz.genre join musicbrainz.tag on musicbrainz.genre.name=musicbrainz.tag.name join musicbrainz.release_tag on musicbrainz.tag.id=musicbrainz.release_tag.tag join musicbrainz.release on musicbrainz.release_tag.release=musicbrainz.release.id join musicbrainz.medium on musicbrainz.release.id=musicbrainz.medium.release join musicbrainz.track on musicbrainz.medium.id=musicbrainz.track.medium join musicbrainz.recording on musicbrainz.track.recording=musicbrainz.recording.id join beatmap on musicbrainz.recording.gid=beatmap.recording_gid group by musicbrainz.genre.name;")

