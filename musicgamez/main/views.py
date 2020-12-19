from flask import Blueprint
from flask import flash
from flask import g
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from werkzeug.exceptions import abort

from musicgamez import db
from musicgamez.main.models import *

from mbdata.models import ArtistCreditName

bp = Blueprint("main", __name__)

@bp.route("/")
def index():
    return render_template("index.html",
                           maps=db.session.query(Beatmap) \
                                .filter(Beatmap.recording!=None) \
                                .order_by(Beatmap.date.desc()))

'''
from mbdata.models import URL, Track, Medium, Release
from mbdata.models import LinkType, Link, LinkRecordingURL, LinkRecordingRelease, LinkReleaseURL
recordingUrlLicenseLinkType = session.query(LinkType).filter(LinkType.gid=='f25e301d-b87b-4561-86a0-5d2df6d26c0a').one()
releaseUrlLicenseLinkType = session.query(LinkType).filter(LinkType.gid=='004bd0c3-8a45-4309-ba52-fa99f3aa3d50').one()
recordingUrlLicenseLink = session.query(Link).filter(Link.link_type==recordingUrlLicenseLinkType).one()
releaseUrlLicenseLink = session.query(Link).filter(Link.link_type==releaseUrlLicenseLinkType).one()
'''

