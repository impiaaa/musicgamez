from flask import abort
from flask import Blueprint
from flask import g
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for
from flask_babel import _
from flask_sqlalchemy import Pagination
import json
from mbdata.models import *
from musicgamez import db, translate_artist
from musicgamez.main.models import *
import oauthlib
import sqlalchemy
from sqlalchemy.sql import func, expression
from urllib.parse import urlparse, urlunparse

bp = Blueprint("main", __name__)


def recordinglist(q, page, pagetitle, pagelink=None, paginate=None):
    if request.method == "POST":
        if "game" in request.form:
            if request.form["game"] == "":
                if "game" in session:
                    del session["game"]
            else:
                session["game"] = request.form["game"]
        session["streamsafe"] = bool(request.form.get("streamsafe", False))
    if session.get("streamsafe", False):
        q = q.filter(expression.or_(MiniRecordingView.license_url != None,
            MiniRecordingView.permission_url != None,
            MiniRecordingView.selfpublish))
    if session.get("game", False):
        site = db.session.query(BeatSite).filter(BeatSite.short_name==session["game"]).one_or_none()
        if site is None:
            del session["game"]
        else:
            q = q.join(Beatmap).filter(Beatmap.external_site==site)
    q = q.order_by(MiniRecordingView.date.desc())
    if paginate is None:
        q = q.paginate(page, db.app.config["PERPAGE"], True)
        paginate = q
        items = q.items
    else:
        items = q
    return render_template("recordinglist.html", recordings=items,
        has_next=paginate.has_next, has_prev=paginate.has_prev,
        next_num=paginate.next_num, prev_num=paginate.prev_num,
        pagetitle=pagetitle, pagelink=pagelink,
        games=db.session.query(BeatSite))


@bp.route("/", methods={'GET', 'POST'})
@bp.route("/latest", defaults={"page": 1}, methods={'GET', 'POST'})
@bp.route("/latest/<int:page>", methods={'GET', 'POST'})
def latest(page=1):
    return recordinglist(db.session.query(MiniRecordingView), page, _("Latest"))


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


@bp.route("/tag/<tag>", defaults={"page": 1}, methods={'GET', 'POST'})
@bp.route("/tag/<tag>/<int:page>", methods={'GET', 'POST'})
def tag(tag, page=1):
    return recordinglist(db.session.query(MiniRecordingView)
                         .join(Track)
                         .join(Medium)
                         .join(Release)
                         .join(ReleaseTag)
                         .join(Tag)
                         .filter(Tag.name == tag),
                         page, tag,
                         "https://musicbrainz.org/tag/"+tag)


@bp.route("/release/<uuid:gid>", defaults={"page": 1}, methods={'GET', 'POST'})
@bp.route("/release/<uuid:gid>/<int:page>", methods={'GET', 'POST'})
def release(gid, page=1):
    r = db.session.query(Release).filter(Release.gid == str(gid)).one()
    return recordinglist(db.session.query(MiniRecordingView)
                         .join(Track).join(Medium)
                         .filter(Medium.release == r), page,
                         r.name,
                         "https://musicbrainz.org/release/"+str(gid))


@bp.route("/artist/<uuid:gid>", defaults={"page": 1}, methods={'GET', 'POST'})
@bp.route("/artist/<uuid:gid>/<int:page>", methods={'GET', 'POST'})
def artist(gid, page=1):
    a = db.session.query(Artist).filter(Artist.gid == str(gid)).one()
    return recordinglist(db.session.query(MiniRecordingView)
                         .join(ArtistCredit).join(ArtistCreditName)
                         .filter(ArtistCreditName.artist == a), page,
                         translate_artist(a),
                         "https://musicbrainz.org/artist/"+str(gid))


@bp.route("/label/<uuid:gid>", defaults={"page": 1}, methods={'GET', 'POST'})
@bp.route("/label/<uuid:gid>/<int:page>", methods={'GET', 'POST'})
def label(gid, page=1):
    l = db.session.query(Label).filter(Label.gid == str(gid)).one()
    return recordinglist(db.session.query(MiniRecordingView)
                         .join(Track).join(Medium).join(Release).join(ReleaseLabel)
                         .filter(ReleaseLabel.label == l), page,
                         l.name,
                         "https://musicbrainz.org/label/"+str(gid))


@bp.route("/release-group/<uuid:gid>", defaults={"page": 1}, methods={'GET', 'POST'})
@bp.route("/release-group/<uuid:gid>/<int:page>", methods={'GET', 'POST'})
def release_group(gid, page=1):
    r = db.session.query(ReleaseGroup).filter(ReleaseGroup.gid == str(gid)).one()
    return recordinglist(db.session.query(MiniRecordingView)
                         .join(Track).join(Medium).join(Release).join(ReleaseGroup)
                         .filter(ReleaseGroup.id == r.id), page,
                         r.name,
                         "https://musicbrainz.org/release-group/"+str(gid))


@bp.route("/collection/<uuid:gid>", defaults={ "page": 1}, methods={'GET', 'POST'})
@bp.route("/collection/<uuid:gid>/<int:page>", methods={'GET', 'POST'})
def collection(gid, page=1):
    from musicgamez import oauth_musicbrainz
    response = oauth_musicbrainz.session.get("collection/{}?fmt=json".format(gid))
    info = response.json()
    if 'error' in info:
        db.app.logger.error(info)
        abort(response.status_code)
    name = info['name']
    entity = info['entity-type']
    count = info[entity+'-count']
    perpage=db.app.config["PERPAGE"]
    if (page-1)*perpage > count:
        abort(404)
    plural = entity+'es' if entity.endswith('s') else entity+'s'
    # TODO: doing things this way means that some pages could be empty, and some
    # could be longer than perpage
    entities = oauth_musicbrainz.session.get("{}?collection={}&fmt=json&limit={}&offset={}".format(entity, gid, perpage, (page-1)*perpage)).json()[entity+'s']
    ids = [e['id'] for e in entities]
    q = db.session.query(MiniRecordingView)
    if entity == "recording":
        q = q.filter(MiniRecordingView.gid.in_(ids))
    elif entity == "release":
        q = q.join(Track).join(Medium).join(Release).filter(Release.gid.in_(ids))
    elif entity == "artist":
        q = q.join(ArtistCredit).join(ArtistCreditName).join(Artist).filter(Artist.gid.in_(ids))
    # don't want to confuse "recorded in area" with "artist is in area"
    #elif entity == "area":
    #    q = q.join(ArtistCredit).join(ArtistCreditName).join(Artist).join(Area).filter(Area.gid.in_(ids))
    elif entity == "label":
        q = q.join(Track).join(Medium).join(Release).join(ReleaseLabel).join(Label).filter(Label.gid.in_(ids))
    elif entity == "release-group":
        q = q.join(Track).join(Medium).join(Release).join(ReleaseGroup).filter(ReleaseGroup.gid.in_(ids))
    else:
        raise NotImplementedError()
    paginate = Pagination(q, page, perpage, count, q)
    return recordinglist(q, page, name, "https://musicbrainz.org/collection/"+str(gid), paginate)


def spotifylist(name, link, entities, page, count):
    isrcs = [item["external_ids"]["isrc"] for item in entities if "external_ids" in item and "isrc" in item["external_ids"]]
    urls = [url for item in entities for url in item.get("external_urls", {}).values()]
    q = db.session.query(MiniRecordingView).join(ISRC).filter(ISRC.isrc.in_(isrcs))
    paginate = Pagination(q, page, db.app.config["PERPAGE"], count, q)
    return recordinglist(q, page, name, link, paginate)


@bp.route("/spotify/playlist/<id>")
def spotify_playlist(id):
    from musicgamez import oauth_spotify
    response = oauth_spotify.session.get("playlists/{}?fields=name,external_urls,tracks.items(track(external_ids,external_urls,name,artists))".format(id))
    info = response.json()
    if 'error' in info:
        db.app.logger.error(info)
        abort(response.status_code)
    return spotifylist(info['name'], info['external_urls']['spotify'], [item['track'] for item in info['tracks']['items']], 0, 0)


@bp.route("/spotify/tracks", defaults={"page": 1}, methods={'GET', 'POST'})
@bp.route("/spotify/tracks/<int:page>", methods={'GET', 'POST'})
def spotify_tracks(page=1):
    from musicgamez import oauth_spotify
    response = oauth_spotify.session.get("me/tracks?limit={}&offset={}&fields=items(track(external_ids,external_urls,name,artists))".format(db.app.config["PERPAGE"], db.app.config["PERPAGE"]*(page-1)))
    info = response.json()
    if 'error' in info:
        db.app.logger.error(info)
        abort(response.status_code)
    return spotifylist(_("Saved tracks"), None, [item['track'] for item in info['items']], page, info['total'])


@bp.route("/spotify/albums", defaults={"page": 1}, methods={'GET', 'POST'})
@bp.route("/spotify/albums/<int:page>", methods={'GET', 'POST'})
def spotify_albums(page=1):
    from musicgamez import oauth_spotify
    response = oauth_spotify.session.get("me/albums?limit={}&offset={}&fields=items(album(external_ids,external_urls,name,artists))".format(db.app.config["PERPAGE"], db.app.config["PERPAGE"]*(page-1)))
    info = response.json()
    if 'error' in info:
        db.app.logger.error(info)
        abort(response.status_code)
    upcs = [item["album"]["external_ids"]["upc"] for item in info['items'] if "external_ids" in item["album"] and "upc" in item["album"]["external_ids"]]
    urls = [url for item in info['items'] for url in item["album"].get("external_urls", {}).values()]
    q = db.session.query(MiniRecordingView).join(Track).join(Medium).join(Release).filter(Release.barcode.in_(upcs))
    paginate = Pagination(q, page, db.app.config["PERPAGE"], info['total'], q)
    return recordinglist(q, page, _("Saved albums"), None, paginate)


@bp.route("/collection")
def mycollection():
    from musicgamez import oauth_musicbrainz, oauth_spotify
    if oauth_musicbrainz.session.authorized:
        try:
            response = oauth_musicbrainz.session.get("collection?fmt=json")
            info = response.json()
            if 'error' in info:
                db.app.logger.error(info)
                abort(response.status_code)
            mb_collections = info['collections']
        except oauthlib.oauth2.rfc6749.errors.TokenExpiredError:
            mb_collections = None
            del oauth_musicbrainz.token
    else:
        mb_collections = None
    if oauth_spotify.session.authorized:
        try:
            response = oauth_spotify.session.get("me/playlists?limit=50")
            info = response.json()
            if 'error' in info:
                db.app.logger.error(info)
                abort(response.status_code)
            spotify_playlists = info['items']
        except oauthlib.oauth2.rfc6749.errors.TokenExpiredError:
            spotify_playlists = None
            del oauth_spotify.token
    else:
        spotify_playlists = None
    return render_template("mycollection.html",
        mb_collections=mb_collections, spotify_playlists=spotify_playlists)


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
        .limit(5)\
        .all()
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
    links = db.session.query(URL, LinkType)\
        .select_from(URL)\
        .join(LinkRecordingURL)\
        .join(Link)\
        .join(LinkType)\
        .filter(LinkRecordingURL.recording==rec)\
        .filter(LinkType.gid != 'f25e301d-b87b-4561-86a0-5d2df6d26c0a')\
        .union(db.session.query(URL, LinkType)\
            .select_from(URL)\
            .join(LinkReleaseURL)\
            .join(Link)\
            .join(LinkType)\
            .join(Release)\
            .join(Medium)\
            .join(Track)\
            .filter(Track.recording == rec)\
            .filter(LinkType.gid != '004bd0c3-8a45-4309-ba52-fa99f3aa3d50')
        )\
        .order_by(LinkType.link_phrase)\
        .distinct()
    selfpublish = db.session.query("157afde4-4bf5-4039-8ad2-5a15acc85176" == expression.all_(db.session.query(Label.gid)\
                        .select_from(Track)\
                        .join(Medium)\
                        .join(Release)\
                        .outerjoin(ReleaseLabel)\
                        .outerjoin(Label)\
                        .filter(Track.recording == rec).subquery())).one_or_none()
    selfpublish = False if selfpublish is None else selfpublish[0]
    return render_template("recording.html",
                           recording=rec,
                           covers=covers,
                           rec_licenses=rec_licenses,
                           rel_licenses=rel_licenses,
                           artist_perms=artist_perms,
                           label_perms=label_perms,
                           links=links,
                           State=Beatmap.State,
                           selfpublish=selfpublish)


@bp.route("/beatmap/<sitename>/<extid>", methods={'GET', 'POST'})
def beatmap(sitename, extid):
    site = db.session.query(BeatSite).filter(
        BeatSite.short_name == sitename).one()
    try:
        bm = db.session.query(Beatmap).filter(
            Beatmap.external_site == site,
            Beatmap.external_id == extid).one()
    except sqlalchemy.orm.exc.NoResultFound:
        from musicgamez.main.tasks import fetch_single
        from urllib.error import URLError
        bm = None
        try:
            bm = fetch_single(site, db.session, extid)
        except URLError:
            pass
        if bm is None:
            raise
    if request.method == 'POST':
        if 'action' not in request.form:
            abort(400)
        if request.form['action'] == 'rematch':
            if bm.state != Beatmap.State.MATCHED_WITH_STRING:
                abort(400)
            bm.state = Beatmap.State.WAITING_FOR_FINGERPRINT
        elif request.form['action'] == 'incorrect':
            # TODO could be a vector for abuse
            if bm.recording_gid is None:
                abort(400)
            bm.recording_gid = None
        else:
            abort(400)
        db.session.commit()
    if bm.recording_gid is None:
        return render_template("beatmap-standalone.html", beatmap=bm, State=Beatmap.State)
    else:
        return redirect(url_for('main.recording', gid=bm.recording_gid))


@bp.route("/lookup", methods={'GET', 'POST'})
def lookup():
    if request.method == 'POST':
        if 'exturl' in request.form:
            exturl = urlunparse(urlparse(request.form['exturl'])._replace(fragment=''))
            site = db.session.query(BeatSite)\
                .filter(expression.literal(exturl)\
                    .like(BeatSite.url_base+'%'+BeatSite.url_suffix)
                )\
                .one()
            sitename = site.short_name
            if len(site.url_suffix) == 0:
                extid = exturl[len(site.url_base):]
            else:
                extid = exturl[len(site.url_base):-len(site.url_suffix)]
        elif 'sitename' in request.form and 'extid' in request.form:
            sitename = request.form['sitename']
            extid = request.form['extid']
        else:
            abort(400)
        return redirect(url_for('main.beatmap', sitename=sitename, extid=extid))
    elif request.method == 'GET':
        return render_template("lookup.html", beatsites=db.session.query(BeatSite))


@bp.route("/coffee", methods={'BREW', 'POST'})
def coffee():
    abort(418)


@bp.route("/about")
def about():
    return render_template("about.html")
