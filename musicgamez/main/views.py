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

from mbdata.models import Recording, Track, Medium, Release, CoverArt, CoverArtType, ArtType, ArtistCreditName

bp = Blueprint("main", __name__)

def augment_with_coverart(recording):
    result = db.session.query(Release, CoverArt).\
            select_from(Track, Medium, CoverArtType, ArtType).\
            filter(Track.recording==recording,
                   Medium.id==Track.medium_id,
                   Medium.release_id==Release.id,
                   Medium.release_id==CoverArt.release_id,
                   CoverArtType.id==CoverArt.id,
                   CoverArtType.type_id==ArtType.id,
                   ArtType.gid=='ac337166-a2b3-340c-a0b4-e2b00f1d40a2').\
            order_by(func.random()).\
            first()
    if result is None:
        release = None
        coverart = None
    else:
        release, coverart = result
    return recording, release, coverart

@bp.route("/")
def index():
    return render_template("index.html",
                           recordings=map(augment_with_coverart, \
                                db.session.query(Recording).\
                                join(Beatmap).\
                                group_by(Recording).\
                                order_by(func.max(Beatmap.date).desc()).\
                                limit(10)
                                ))

