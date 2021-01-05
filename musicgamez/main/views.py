from flask import Blueprint
from flask import flash
from flask import g
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from math import ceil
from werkzeug.exceptions import abort
from sqlalchemy.sql import func

from musicgamez import db
from musicgamez.main.models import *
from mbdata.models import *

bp = Blueprint("main", __name__)

perpage = 36

def recordinglist(q, page, pagetitle=None):
    if pagetitle is None: pagetitle = request.endpoint.split('.')[-1].title()
    return render_template("recordinglist.html", recordings=q.limit(perpage).offset(perpage*page), page=page, pages=ceil(q.count()/perpage), pagetitle=pagetitle)

@bp.route("/")
@bp.route("/latest", defaults={"page": 0})
@bp.route("/latest/<int:page>")
def latest(page=0):
    return recordinglist(db.session.query(MiniRecordingView), page)

@bp.route("/browse/genre")
def genres():
    return render_template("genres.html", genres=db.session.query(Genre.name, func.count(Beatmap.id))\
        .select_from(Genre)\
        .join(Tag, Tag.name==Genre.name)\
        .join(ReleaseTag)\
        .join(Release)\
        .join(Medium)\
        .join(Track)\
        .join(Recording)\
        .join(Beatmap)\
        .group_by(Genre.name)\
        .order_by(func.random()))

@bp.route("/tag/<tag>", defaults={"page": 0})
@bp.route("/tag/<tag>/<int:page>")
def tag(tag, page=0):
    return recordinglist(db.session.query(MiniRecordingView)\
        .join(Track)\
        .join(Medium)\
        .join(Release)\
        .join(ReleaseTag)\
        .join(Tag)\
        .filter(Tag.name==tag), page, tag)

