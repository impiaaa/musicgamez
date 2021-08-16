from acoustid import fingerprint_file, lookup, WebServiceError
from argparse import Namespace
from bs4 import BeautifulSoup
import codecs
import csv
from datetime import datetime
import json
from mbdata.models import ArtistCredit, Recording
from mbdata.models import Artist, Label
from mbdata.replication import mbslave_sync_main, Config
from musicgamez import scheduler, db, oauth_osu_noauth
from musicgamez.main.models import *
import os
import psycopg2
import sqlalchemy
from sqlalchemy.sql import func
from tempfile import TemporaryFile, NamedTemporaryFile
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from zipfile import ZipFile


def urlopen_with_ua(u, **kwargs):
    headers = {"User-Agent": db.app.config["USER_AGENT"]}
    if "headers" in kwargs:
        headers.update(kwargs.pop("headers"))
    return urlopen(Request(u, headers=headers, **kwargs))


def fetch_beatsaber_single(site, session, gametrack_or_id):
    if isinstance(gametrack_or_id, str):
        gametrack = json.load(urlopen_with_ua("https://beatsaver.com/api/maps/id/" + gametrack_or_id))
    else:
        gametrack = gametrack_or_id
    meta = gametrack['metadata']
    songName = meta['songName']
    mapperName = meta['levelAuthorName']
    if meta['songAuthorName'].casefold() == mapperName.casefold():
        artistName = meta['songSubName']
    else:
        artistName = meta['songAuthorName']

    q = session.query(Beatmap).filter(Beatmap.external_site == site,
                                      Beatmap.external_id == gametrack['id'])
    if q.count() > 0:
        return

    bm = Beatmap(artist=artistName,
                 title=songName,
                 external_id=gametrack['id'],
                 external_site=site,
                 choreographer=mapperName,
                 date=gametrack['uploaded'],
                 duration=meta['duration'],
                 extra=gametrack)

    session.add(bm)
    session.commit()

    return bm


def fetch_beatsaber_dump():
    with db.app.app_context():
        imported = 0
        session = db.create_scoped_session()

        site = session.query(BeatSite).filter(
            BeatSite.short_name == 'bs').one()

        for gametrack in json.load(urlopen_with_ua("https://github.com/andruzzzhka/BeatSaberScrappedData/raw/master/beatSaverScrappedData.json")):
            if fetch_beatsaber_single(site, session, gametrack) is not None:
                imported += 1

        db.app.logger.info(
            "Imported {} beatmaps for {}".format(
                imported, site.name))
        session.remove()


@scheduler.task('interval', id='fetch_beatsaber', hours=1, jitter=60)
def fetch_beatsaber():
    with db.app.app_context():
        imported = 0
        session = db.create_scoped_session()

        site = session.query(BeatSite).filter(
            BeatSite.short_name == 'bs').one()
        before = None

        for page in range(10):
            url = "https://beatsaver.com/api/maps/latest?automapper=false"
            if before is not None:
                url += "&before="+before
            response = json.load(urlopen_with_ua(url))

            lastPage = False
            for gametrack in response['docs']:
                if fetch_beatsaber_single(site, session, gametrack) is None:
                    lastPage = True
                    break
                imported += 1
                before = gametrack['uploaded']

            if lastPage:
                break

        db.app.logger.info(
            "Imported {} beatmaps for {}".format(
                imported, site.name))
        session.remove()


def osu_auth():
    oauth_osu_noauth.session.client_id = db.app.config["OSU_CLIENT_ID"]
    oauth_osu_noauth.session.scope="public"
    oauth_osu_noauth.session.fetch_token(oauth_osu_noauth.token_url, include_client_id=True, client_secret=db.app.config["OSU_CLIENT_SECRET"], scope="public")


def fetch_osu_single(site, db_session, gametrack_or_id):
    if isinstance(gametrack_or_id, str):
        if not oauth_osu_noauth.session.authorized:
            osu_auth()
        gametrack = oauth_osu_noauth.session.get("https://osu.ppy.sh/api/v2/beatmapsets/"+gametrack_or_id).json()
        extId = gametrack_or_id
    else:
        gametrack = gametrack_or_id
        extId = str(gametrack['id'])
    q = db_session.query(Beatmap).filter(Beatmap.external_site == site,
                                         Beatmap.external_id == extId)
    if q.count() > 0:
        return

    bm = Beatmap(artist=gametrack['artist_unicode'],
                 title=gametrack['title_unicode'],
                 external_id=extId,
                 external_site=site,
                 choreographer=gametrack['creator'],
                 date=gametrack['submitted_date'],
                 duration=max([variant['total_length'] for variant in gametrack['beatmaps']], default=None),
                 extra=gametrack)

    db_session.add(bm)
    db_session.commit()
    
    return bm


@scheduler.task('interval', id='fetch_osu', hours=1, jitter=60)
def fetch_osu():
    with db.app.app_context():
        imported = 0
        session = db.create_scoped_session()

        site = session.query(BeatSite).filter(
            BeatSite.short_name == 'osu').one()
        
        osu_auth()

        cursor = {}
        for page in range(1):
            response = oauth_osu_noauth.session.get(
                    "https://osu.ppy.sh/api/v2/beatmapsets/search?sort=updated_desc&s=any&" +
                    urlencode(cursor)).json()
            cursor = {
                "cursor[{}]".format(k): v for k,
                v in response['cursor'].items()}

            for gametrack in response['beatmapsets']:
                if fetch_osu_single(site, session, gametrack) is not None:
                    imported += 1

        db.app.logger.info(
            "Imported {} beatmaps for {}".format(
                imported, site.name))
        session.remove()


def fetch_single(site, session, gametrack_or_id):
    return {
        'bs': fetch_beatsaber_single,
        'osu': fetch_osu_single
    }[site.short_name](site, session, gametrack_or_id)


def import_partybus_stream_permission():
    """Import artist streaming permissions from PartyBus's spreadsheet"""
    with urlopen_with_ua("https://docs.google.com/spreadsheets/d/1QjLWvGHCslmupJKRn5JWnymK4Hxtq_O71JYXGw4yq5g/export?format=csv") as csvfile:
        reader = csv.reader(codecs.iterdecode(csvfile, 'utf-8'))
        for row in reader:
            if len(row) > 0 and row[0] == "Name":
                break
        for row in reader:
            name, genre, type, whereToAcquire, platform, permission, screenshot = row
            try:
                if type == "Artist":
                    e = db.session.query(Artist).filter(func.lower(
                        Artist.name, type_=db.String) == name.lower()).one()
                    if db.session.query(ArtistStreamPermission).filter(
                            ArtistStreamPermission.artist_gid == e.gid).count() == 0:
                        db.session.add(
                            ArtistStreamPermission(
                                artist=e,
                                url=permission,
                                source="PartyBus"))
                elif type == "Label/Group":
                    e = db.session.query(Label).filter(func.lower(
                        Label.name, type_=db.String) == name.lower()).one()
                    if db.session.query(LabelStreamPermission).filter(
                            LabelStreamPermission.label_gid == e.gid).count() == 0:
                        db.session.add(
                            LabelStreamPermission(
                                label=e,
                                url=permission,
                                source="PartyBus"))
            except sqlalchemy.orm.exc.NoResultFound as err:
                db.app.logger.error("Can't find %s %r: %s" % (type, name, err))
                continue
            except sqlalchemy.orm.exc.MultipleResultsFound as err:
                db.app.logger.error("Can't find %s %r: %s" % (type, name, err))
                continue
            db.app.logger.info("Added %s %r as %s" % (type, name, e.gid))
        db.session.commit()


def import_creatorhype_stream_permission():
    """Import artist streaming permissions from creatorhype.com's spreadsheet"""
    for row in json.load(urlopen_with_ua(
            "https://creatorhype.com/wp-admin/admin-ajax.php?action=wp_ajax_ninja_tables_public_action&table_id=3665&target_action=get-all-data&default_sorting=old_first")):
        soup = BeautifulSoup(
            row["value"]["proof_of_permission"],
            "html.parser")
        if not soup or not soup.a or not soup.a['href']:
            continue
        name = row["value"]["source"]
        url = soup.a['href']
        try:
            a = db.session.query(Artist).filter(func.lower(
                Artist.name, type_=db.String) == name.lower()).one()
        except sqlalchemy.orm.exc.NoResultFound as e:
            db.app.logger.error("Can't find artist %r: %s" % (name, e))
            continue
        except sqlalchemy.orm.exc.MultipleResultsFound as e:
            db.app.logger.error("Can't find artist %r: %s" % (name, e))
            continue
        if db.session.query(ArtistStreamPermission).filter(
                ArtistStreamPermission.artist_gid == a.gid).count() > 0:
            continue
        db.session.add(
            ArtistStreamPermission(
                artist=a,
                url=url,
                source="Creator Hype"))
        db.app.logger.info("Added artist %r as %s" % (name, a.gid))
    db.session.commit()


@scheduler.task('interval', id='match_with_string', seconds=10)
def match_with_string():
    with db.app.app_context():
        matched = 0
        session = db.create_scoped_session()
        total = 0
        for bm in session.query(Beatmap)\
                         .filter(Beatmap.state == Beatmap.State.INITIAL)\
                         .order_by(Beatmap.last_checked)\
                         .limit(10):
            # TODO use normalize(nfkc) once on PosgreSQL 13
            # TODO use aliases
            stmt = sqlalchemy.select([func.count()])\
                             .select_from(Track.__table__)\
                             .where(Track.recording_id == Recording.id)\
                             .correlate(Recording.__table__)
            q = session.query(Recording)\
                       .filter(func.lower(Recording.name, type_=db.String) == bm.title.lower(),
                               Recording.artist_credit.has(func.lower(ArtistCredit.name, type_=db.String) == bm.artist.lower()))\
                       .order_by(func.abs(Recording.length-((bm.duration or 0)*1000)), sqlalchemy.desc(stmt))\
                       .limit(2)
            recs = q.all()
            if len(recs) > 0:
                bm.recording = recs[0]
                matched += 1
                if len(recs) == 1:
                    bm.state = Beatmap.State.MATCHED_WITH_STRING
                else:
                    bm.state = Beatmap.State.MATCHED_WITH_STRING_MULTIPLE
            else:
                bm.state = Beatmap.State.WAITING_FOR_FINGERPRINT
            total += 1
            #session.commit()
        if matched > 0:
            db.app.logger.info("Matched {} beatmaps using string".format(matched))
        if total > 0:
            session.commit()
        session.remove()


def zipopen_lower(z, fname):
    for info in z.infolist():
        if info.filename.casefold() == fname:
            return z.open(info)
    return z.open(fname)


@scheduler.task('interval', id='generate_fingerprint', minutes=1)
def generate_fingerprint():
    with db.app.app_context():
        session = db.create_scoped_session()
        # TODO support osu! (download requires user grant)
        bm = session.query(Beatmap)\
            .filter(Beatmap.state == Beatmap.State.WAITING_FOR_FINGERPRINT)\
            .filter(Beatmap.external_site.has(BeatSite.short_name == 'bs'))\
            .order_by(Beatmap.last_checked)\
            .first()
        if bm is None and session.query(Beatmap)\
                                 .filter(Beatmap.state == Beatmap.State.HAS_FINGERPRINT)\
                                 .count() == 0:
            # After all songs have a match, go back and get higher-quality
            # matches with fingerprints
            bm = session.query(Beatmap)\
                 .filter(Beatmap.state == Beatmap.State.MATCHED_WITH_STRING_MULTIPLE)\
                 .filter(Beatmap.external_site.has(BeatSite.short_name == 'bs'))\
                 .order_by(Beatmap.last_checked)\
                 .first()
            if bm is None:
                bm = session.query(Beatmap)\
                     .filter(Beatmap.state == Beatmap.State.MATCHED_WITH_STRING)\
                     .filter(Beatmap.external_site.has(BeatSite.short_name == 'bs'))\
                     .order_by(Beatmap.last_checked)\
                     .first()
        if bm is None:
            session.remove()
            return
        db.app.logger.debug(
            "Generating fingerprint for beatmap ID {}".format(
                bm.id))
        try:
            if bm.external_site.short_name == 'bs':
                if bm.extra is not None and 'versions' in bm.extra:
                    mapinfo = bm.extra
                else:
                    mapinfo = json.load(urlopen_with_ua("https://beatsaver.com/api/maps/id/" + bm.external_id))
                dl_url = mapinfo['versions'][0]['downloadURL']
            elif bm.external_site.short_name == 'osu':
                dl_url = "https://osu.ppy.sh/api/v2/beatmapsets/" + bm.external_id + "/download"
            else:
                assert False
            url_file = urlopen_with_ua(dl_url)
            if bm.external_site.short_name == 'bs':
                t = TemporaryFile()
                t.write(url_file.read())
                z = ZipFile(t)
                url_file.close()
                url_file = t
                info = json.load(zipopen_lower(z, "info.dat"))
                songfile = z.open(info['_songFilename'])
            elif bm.external_site.short_name == 'osu':
                t = TemporaryFile()
                t.write(url_file.read())
                z = ZipFile(t)
                url_file.close()
                url_file = t
                songfile = zipopen_lower(z, "audio.mp3")
            t = NamedTemporaryFile()
            t.write(songfile.read())
            t.flush()
            songfile.close()
            url_file.close()

            # TODO change force_fpcalc to False once multiprocessing is
            # possible
            bm.duration, fp = fingerprint_file(t.name, force_fpcalc=True)
            bm.fingerprint = fp.decode('ascii')
            bm.state = Beatmap.State.HAS_FINGERPRINT
            session.commit()
        except Exception as e:
            db.app.logger.error(
                "Error generating fingerprint for beatmap {}: {}".format(
                    bm.id, e))
            bm.state = Beatmap.State.ERROR
            session.commit()
        session.remove()


@scheduler.task('interval', id='lookup_fingerprint', minutes=1)
def lookup_fingerprint():
    with db.app.app_context():
        session = db.create_scoped_session()
        bm = session.query(Beatmap)\
            .filter(Beatmap.state == Beatmap.State.HAS_FINGERPRINT)\
            .order_by(Beatmap.last_checked)\
            .first()
        if bm is None:
            session.remove()
            return
        db.app.logger.debug(
            "Looking up fingerprint for beatmap ID {}".format(
                bm.id))
        try:
            response = lookup(
                db.app.config.get('ACOUSTID_API_KEY'),
                bm.fingerprint,
                bm.duration,
                timeout=30)
            if response['status'] != 'ok':
                db.app.logger.debug("{}".format(response))
                raise WebServiceError("status: %s" % response['status'])
            if 'results' not in response:
                db.app.logger.debug("{}".format(response))
                raise WebServiceError("results not included")

            if len(response['results']) == 0:
                bm.state = Beatmap.State.NO_MATCH
                db.app.logger.debug("No matches for beatmap {}".format(bm.id))
                session.commit()
                session.remove()
                return
            elif len(response['results']) > 1:
                db.app.logger.warning(
                    "Beatmap {} has more than one track ID, using first".format(
                        bm.id))

            track = response['results'][0]
            bm.track_id = track['id']
            if 'recordings' not in track or len(track['recordings']) == 0:
                bm.state = Beatmap.State.NO_MATCH
                db.app.logger.debug(
                    "No matches for beatmap {} track {}".format(
                        bm.id, bm.track_id))
            elif len(track['recordings']) == 1:
                gid = track['recordings'][0]['id']
                redir = session.query(RecordingGIDRedirect).filter(RecordingGIDRedirect.gid==gid).one_or_none()
                if redir is not None:
                    gid = redir.redirect.gid
                if session.query(Recording).filter(Recording.gid==gid).count() == 0:
                    bm.state = Beatmap.State.NO_MATCH
                    db.app.logger.warning(
                        "Match beatmap {} track {} recording {} not found".format(
                            bm.id, bm.track_id, gid))
                else:
                    bm.recording_gid = gid
                    bm.state = Beatmap.State.MATCHED_WITH_FINGERPRINT
                    db.app.logger.info(
                        "Matched beatmap {} with recording {}".format(
                            bm.id, bm.recording_gid))
            else:
                bm.state = Beatmap.State.TOO_MANY_MATCHES
                db.app.logger.debug(
                    "Too many matches for beatmap {} track {}".format(
                        bm.id, bm.track_id))
            session.commit()
        except Exception as e:
            db.app.logger.error(
                "Error looking up fingerprint for beatmap {}: {}".format(
                    bm.id, e))
            bm.state = Beatmap.State.ERROR
            session.commit()
        session.remove()


@scheduler.task('cron', id='mbsync', minute=2, second=0, jitter=30)
def mbsync():
    config_paths = ['/etc/mbslave.conf', os.path.join(db.app.instance_path, "mbslave.conf")]
    if "MBSLAVE_CONFIG" in os.environ:
        config_paths.append(os.environ["MBSLAVE_CONFIG"])
    args = Namespace()
    args.keep_running = False
    try:
        mbslave_sync_main(Config(config_paths), args)
    except psycopg2.errors.ForeignKeyViolation:
        with db.app.app_context():
            session = db.create_scoped_session()
            session.execute("ALTER TABLE public.beatmap DROP CONSTRAINT beatmap_recording_gid_fkey")
            session.commit()
            mbslave_sync_main(Config(config_paths), args)
            for bm, redir in session.query(Beatmap, RecordingGIDRedirect).filter(Beatmap.recording_gid==RecordingGIDRedirect.gid):
                bm.recording_gid = redir.recording.gid
            session.commit()
            session.execute("ALTER TABLE public.beatmap ADD CONSTRAINT beatmap_recording_gid_fkey FOREIGN KEY (recording_gid) REFERENCES musicbrainz.recording(gid)")
            session.commit()
            session.remove()


@scheduler.task('interval', id='update_mini_recording_view', minutes=15)
def update_mini_recording_view():
    with db.app.app_context():
        session = db.create_scoped_session()
        session.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mini_recording_view")
        session.commit()
        session.remove()


@scheduler.task('interval', id='update_genre_cloud', minutes=60)
def update_genre_cloud():
    with db.app.app_context():
        session = db.create_scoped_session()
        session.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY genre_cloud")
        session.commit()
        session.remove()
