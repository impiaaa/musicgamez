from flask import Blueprint
from flask import flash
from flask import g
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from math import ceil
from mbdata.models import *
from musicgamez import db, translate_artist
from musicgamez.main.models import *
import sqlalchemy
from sqlalchemy.sql import func

bp = Blueprint("main", __name__)

perpage = 36


def recordinglist(q, page, pagetitle=None):
    if pagetitle is None:
        pagetitle = request.endpoint.split('.')[-1].title()
    return render_template("recordinglist.html", recordings=q.limit(perpage).offset(
        perpage * page), page=page, pages=ceil(q.count() / perpage), pagetitle=pagetitle)


@bp.route("/")
@bp.route("/latest", defaults={"page": 0})
@bp.route("/latest/<int:page>")
def latest(page=0):
    return recordinglist(db.session.query(MiniRecordingView), page)


@bp.route("/browse/genre")
def genres():
    g = db.session.query(Genre.name, func.count(Beatmap.id))\
        .select_from(Genre)\
        .join(Tag, Tag.name == Genre.name)\
        .join(ReleaseTag)\
        .join(Release)\
        .join(Medium)\
        .join(Track)\
        .join(Recording)\
        .join(Beatmap)\
        .group_by(Genre.name)\
        .order_by(func.random())\
        .all()
    mn = min(g, key=lambda a: a[1])[1]
    mx = max(g, key=lambda a: a[1])[1]
    h = [(genre, (64 * (count - mn) / (mx - mn)) + 8) for genre, count in g]
    return render_template("genres.html", genres=h)


@bp.route("/tag/<tag>", defaults={"page": 0})
@bp.route("/tag/<tag>/<int:page>")
def tag(tag, page=0):
    return recordinglist(db.session.query(MiniRecordingView)
                         .join(Track)
                         .join(Medium)
                         .join(Release)
                         .join(ReleaseTag)
                         .join(Tag)
                         .filter(Tag.name == tag), page, tag)


@bp.route("/artist/<uuid:gid>", defaults={"page": 0})
@bp.route("/artist/<uuid:gid>/<int:page>")
def artist(gid, page=0):
    a = db.session.query(Artist).filter(Artist.gid == str(gid)).one()
    return recordinglist(db.session.query(MiniRecordingView)
                         .join(ArtistCredit)
                         .join(ArtistCreditName)
                         .filter(ArtistCreditName.artist == a), page, translate_artist(a))


@bp.route("/recording/<uuid:gid>")
def recording(gid):
    rec = db.session.query(Recording).filter(Recording.gid == str(gid)).one()
    covers = db.session.query(CoverArt)\
        .join(Release)\
        .join(Medium)\
        .join(Track)\
        .join(CoverArtType)\
        .join(ArtType)\
        .filter(Track.recording == rec)\
        .filter(ArtType.gid == 'ac337166-a2b3-340c-a0b4-e2b00f1d40a2')\
        .order_by(func.random())\
        .limit(5)
    rec_licenses = db.session.query(URL)\
        .join(LinkRecordingURL)\
        .join(Link)\
        .join(LinkType)\
        .filter(LinkRecordingURL.recording == rec)\
        .filter(LinkType.gid == 'f25e301d-b87b-4561-86a0-5d2df6d26c0a')
    rel_licenses = db.session.query(Release, URL)\
        .select_from(URL)\
        .join(LinkReleaseURL)\
        .join(Link)\
        .join(LinkType)\
        .join(Release)\
        .join(Medium)\
        .join(Track)\
        .filter(Track.recording == rec)\
        .filter(LinkType.gid == '004bd0c3-8a45-4309-ba52-fa99f3aa3d50')
    artist_perms = db.session.query(Artist, ArtistStreamPermission)\
        .select_from(ArtistStreamPermission)\
        .join(Artist)\
        .join(ArtistCreditName)\
        .join(ArtistCredit)\
        .filter(ArtistCredit.id == rec.artist_credit_id)\
        .distinct(Artist.id)
    label_perms = db.session.query(Release, Label, LabelStreamPermission)\
                    .select_from(LabelStreamPermission)\
                    .join(Label)\
                    .join(ReleaseLabel)\
                    .join(Release)\
                    .join(Medium)\
                    .join(Track)\
                    .filter(Track.recording == rec)\
                    .distinct(Label.id)
    return render_template("recording.html",
                           recording=rec,
                           covers=covers,
                           rec_licenses=rec_licenses,
                           rel_licenses=rel_licenses,
                           artist_perms=artist_perms,
                           label_perms=label_perms)


@bp.route("/beatmap/<sitename>/<extid>")
def beatmap(sitename, extid):
    site = db.session.query(BeatSite).filter(
        BeatSite.short_name == sitename).one()
    bm = db.session.query(Beatmap).filter(
        Beatmap.external_site == site,
        Beatmap.external_id == extid).one()
    if bm.recording_gid is None:
        return render_template("beatmap-standalone.html", beatmap=bm)
    else:
        return redirect(url_for('main.recording', gid=bm.recording_gid))
