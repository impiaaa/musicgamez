from musicgamez import scheduler, db
from musicgamez.main.models import *
from urllib.request import urlopen, Request
import sqlalchemy, json

USER_AGENT = "musicgamez/0.0"

def urlopen_with_ua(u, **kwargs):
    headers = {"User-Agent": USER_AGENT}
    if "headers" in kwargs:
        headers.update(kwargs.pop("headers"))
    return urlopen(Request(u, headers=headers, **kwargs))

@scheduler.task('interval', id='fetch_beatsaber', hours=1, jitter=60)
def fetch_beatsaber():
    with db.app.app_context():
        imported = 0
        session = db.create_scoped_session()
        
        site = session.query(BeatSite).filter(BeatSite.short_name=='bs').one()
        
        for page in range(10):
            response = json.load(urlopen_with_ua("https://beatsaver.com/api/maps/latest/"+str(page)))
            
            lastPage = False
            for gametrack in response['docs']:
                meta = gametrack['metadata']
                songName = meta['songName']
                mapperName = meta['levelAuthorName']
                if meta['songAuthorName'].casefold() == mapperName.casefold():
                    artistName = meta['songSubName']
                else:
                    artistName = meta['songAuthorName']
                
                q = session.query(Beatmap).filter(Beatmap.external_site==site,
                                                  Beatmap.external_id==gametrack['key'])
                if q.count() > 0:
                    lastPage = True
                    break
                    #continue
                
                bm = Beatmap(artist=artistName,
                             title=songName,
                             external_id=gametrack['key'],
                             external_site=site,
                             choreographer=mapperName,
                             date=gametrack['uploaded'])
                
                session.add(bm)
                session.commit()
                imported += 1
            
            if lastPage:
                break
        
        if imported > 0:
            scheduler.resume_job('match_with_string')
            scheduler.modify_job('match_with_string', trigger='date')
        db.app.logger.info("Imported {} beatmaps for {}".format(imported, site.name))
        session.remove()

from urllib.parse import urlencode

@scheduler.task('interval', id='fetch_osu', hours=1, jitter=60)
def fetch_osu():
    with db.app.app_context():
        imported = 0
        session = db.create_scoped_session()
        
        site = session.query(BeatSite).filter(BeatSite.short_name=='osu').one()
        
        token = json.load(urlopen_with_ua("https://osu.ppy.sh/oauth/token", data=urlencode({"client_id": db.app.config["OSU_CLIENT_ID"], "client_secret": db.app.config["OSU_CLIENT_SECRET"], "grant_type": "client_credentials", "scope": "public"}).encode()))["access_token"]
        
        cursor = {}
        for page in range(1):
            response = json.load(urlopen_with_ua("https://osu.ppy.sh/api/v2/beatmapsets/search?sort=updated_desc&s=any&"+urlencode(cursor), headers={"Authorization": "Bearer {}".format(token)}))
            cursor = {"cursor[{}]".format(k): v for k, v in response['cursor'].items()}
            
            lastPage = False
            for gametrack in response['beatmapsets']:
                extId = str(gametrack['id'])
                q = session.query(Beatmap).filter(Beatmap.external_site==site,
                                                  Beatmap.external_id==extId)
                if q.count() > 0:
                    lastPage = True
                    break
                
                bm = Beatmap(artist=gametrack['artist_unicode'],
                             title=gametrack['title_unicode'],
                             external_id=extId,
                             external_site=site,
                             choreographer=gametrack['creator'],
                             date=gametrack['submitted_date'])
                
                session.add(bm)
                session.commit()
                imported += 1
            
            if lastPage:
                break
        
        if imported > 0:
            scheduler.resume_job('match_with_string')
            scheduler.modify_job('match_with_string', trigger='date')
        db.app.logger.info("Imported {} beatmaps for {}".format(imported, site.name))
        session.remove()

import csv, codecs
from mbdata.models import Artist, Label
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
                    e = db.session.query(Artist).filter(func.lower(Artist.name, type_=db.String)==name.lower()).one()
                    if db.session.query(ArtistStreamPermission).filter(ArtistStreamPermission.artist_gid==e.gid).count() == 0:
                        db.session.add(ArtistStreamPermission(artist=e, url=permission, source="PartyBus"))
                elif type == "Label/Group":
                    e = db.session.query(Label).filter(func.lower(Label.name, type_=db.String)==name.lower()).one()
                    if db.session.query(LabelStreamPermission).filter(LabelStreamPermission.label_gid==e.gid).count() == 0:
                        db.session.add(LabelStreamPermission(label=e, url=permission, source="PartyBus"))
            except sqlalchemy.orm.exc.NoResultFound as err:
                db.app.logger.error("Can't find %s %r: %s"%(type, name, err))
                continue
            except sqlalchemy.orm.exc.MultipleResultsFound as err:
                db.app.logger.error("Can't find %s %r: %s"%(type, name, err))
                continue
            db.app.logger.info("Added %s %r as %s"%(type, name, e.gid))
        db.session.commit()

from bs4 import BeautifulSoup
def import_creatorhype_stream_permission():
    """Import artist streaming permissions from creatorhype.com's spreadsheet"""
    for row in json.load(urlopen_with_ua("https://creatorhype.com/wp-admin/admin-ajax.php?action=wp_ajax_ninja_tables_public_action&table_id=3665&target_action=get-all-data&default_sorting=old_first")):
        soup = BeautifulSoup(row["value"]["proof_of_permission"], "html.parser")
        if not soup or not soup.a or not soup.a['href']:
            continue
        name = row["value"]["source"]
        url = soup.a['href']
        try:
            a = db.session.query(Artist).filter(func.lower(Artist.name, type_=db.String)==name.lower()).one()
        except sqlalchemy.orm.exc.NoResultFound as e:
            db.app.logger.error("Can't find artist %r: %s"%(name, e))
            continue
        except sqlalchemy.orm.exc.MultipleResultsFound as e:
            db.app.logger.error("Can't find artist %r: %s"%(name, e))
            continue
        if db.session.query(ArtistStreamPermission).filter(ArtistStreamPermission.artist_gid==a.gid).count() > 0:
            continue
        db.session.add(ArtistStreamPermission(artist=a, url=url, source="Creator Hype"))
        db.app.logger.info("Added artist %r as %s"%(name, a.gid))
    db.session.commit()

from datetime import datetime
from sqlalchemy.sql import func
from mbdata.models import ArtistCredit, Recording

@scheduler.task('interval', id='match_with_string', next_run_time=None, seconds=60)
def match_with_string():
    with db.app.app_context():
        matched = 0
        session = db.create_scoped_session()
        total = 0
        for bm in session.query(Beatmap).filter(Beatmap.state == Beatmap.State.INITIAL):
            # TODO use normalize(nfkc) once on PosgreSQL 13
            # TODO use aliases
            q = session.query(Recording).filter(func.lower(Recording.name, type_=db.String) == bm.title.lower(),
                                                Recording.artist_credit.has(func.lower(ArtistCredit.name, type_=db.String) == bm.artist.lower()))
            try:
                rec = q.one()
            except sqlalchemy.orm.exc.NoResultFound as e:
                rec = None
            except sqlalchemy.orm.exc.MultipleResultsFound as e:
                rec = None
            if rec is None:
                bm.state = Beatmap.State.WAITING_FOR_FINGERPRINT
            else:
                bm.recording = rec
                bm.state = Beatmap.State.MATCHED_WITH_STRING
                matched += 1
            total += 1
            bm.last_checked = datetime.now()
            session.commit()
        session.remove()
        s = "Matched {} beatmaps using string".format(matched)
        if matched > 0:
            db.app.logger.info(s)
        else:
            db.app.logger.debug(s)
        if total == 0:
            scheduler.pause_job('match_with_string')

from zipfile import ZipFile
from tempfile import TemporaryFile, NamedTemporaryFile
from acoustid import fingerprint_file, lookup, WebServiceError

def zipopen_lower(z, fname):
    for info in z.infolist():
        if info.filename.casefold() == fname:
            return z.open(info)
    return z.open(fname)

@scheduler.task('interval', id='generate_fingerprint', minutes=3)
def generate_fingerprint():
    with db.app.app_context():
        session = db.create_scoped_session()
        # TODO support osu! (download requires user grant)
        bm = session.query(Beatmap)\
             .filter(Beatmap.state == Beatmap.State.WAITING_FOR_FINGERPRINT)\
             .filter(Beatmap.external_site.has(BeatSite.short_name == 'bs'))\
             .order_by(Beatmap.last_checked)\
             .first()
        '''if bm is None and session.query(Beatmap)\
                                 .filter(Beatmap.state == Beatmap.State.HAS_FINGERPRINT)\
                                 .count() == 0:
            # After all songs have a match, go back and get higher-quality
            # matches with fingerprints
            bm = session.query(Beatmap)\
                 .filter(Beatmap.state == Beatmap.State.MATCHED_WITH_STRING)\
                 .filter(Beatmap.external_site.has(BeatSite.short_name == 'bs'))\
                 .order_by(Beatmap.last_checked)\
                 .first()'''
        if bm is None:
            session.remove()
            return
        db.app.logger.debug("Generating fingerprint for beatmap ID {}".format(bm.id))
        try:
            if bm.external_site.short_name == 'bs':
                dl_url = "https://beatsaver.com/api/download/key/"+bm.external_id
            elif bm.external_site.short_name == 'osu':
                dl_url = "https://osu.ppy.sh/api/v2/beatmapsets/"+bm.external_id+"/download"
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
            
            # TODO change force_fpcalc to False once multiprocessing is possible
            bm.duration, fp = fingerprint_file(t.name, force_fpcalc=True)
            bm.fingerprint = fp.decode('ascii')
            bm.state = Beatmap.State.HAS_FINGERPRINT
            bm.last_checked = datetime.now()
            session.commit()
        except Exception as e:
            db.app.logger.error("Error generating fingerprint for beatmap {}: {}".format(bm.id, e))
            bm.state = Beatmap.State.ERROR
            bm.last_checked = datetime.now()
            session.commit()
        session.remove()

@scheduler.task('interval', id='lookup_fingerprint', minutes=3)
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
        db.app.logger.debug("Looking up fingerprint for beatmap ID {}".format(bm.id))
        try:
            response = lookup(db.app.config.get('ACOUSTID_API_KEY'), bm.fingerprint, bm.duration, timeout=30)
            if response['status'] != 'ok':
                db.app.logger.debug("{}".format(response))
                raise WebServiceError("status: %s" % response['status'])
            if 'results' not in response:
                db.app.logger.debug("{}".format(response))
                raise WebServiceError("results not included")
            
            if len(response['results']) == 0:
                bm.state = Beatmap.State.NO_MATCH
                bm.last_checked = datetime.now()
                db.app.logger.debug("No matches for beatmap {}".format(bm.id))
                session.commit()
                session.remove()
                return
            elif len(response['results']) > 1:
                db.app.logger.warning("Beatmap {} has more than one track ID, using first".format(bm.id))
            
            track = response['results'][0]
            bm.track_id = track['id']
            if 'recordings' not in track or len(track['recordings']) == 0:
                bm.state = Beatmap.State.NO_MATCH
                db.app.logger.debug("No matches for beatmap {} track {}".format(bm.id, bm.track_id))
            elif len(track['recordings']) == 1:
                bm.recording_gid = track['recordings'][0]['id']
                bm.state = Beatmap.State.MATCHED_WITH_FINGERPRINT
                db.app.logger.info("Matched beatmap {} with recording {}".format(bm.id, bm.recording_gid))
            else:
                bm.state = Beatmap.State.TOO_MANY_MATCHES
                db.app.logger.debug("Too many matches for beatmap {} track {}".format(bm.id, bm.track_id))
            bm.last_checked = datetime.now()
            session.commit()
        except Exception as e:
            db.app.logger.error("Error looking up fingerprint for beatmap {}: {}".format(bm.id, e))
            bm.state = Beatmap.State.ERROR
            bm.last_checked = datetime.now()
            session.commit()
        session.remove()

from mbdata.replication import mbslave_sync_main, Config
from argparse import Namespace
import os

@scheduler.task('cron', id='mbsync', minute=2)
def mbsync():
    config_paths = [os.path.join(db.app.instance_path, "mbslave.conf")]
    if "MBSLAVE_CONFIG" in os.environ:
        config_paths.append(os.environ["MBSLAVE_CONFIG"])
    args = Namespace()
    args.keep_running = False
    mbslave_sync_main(Config(config_paths), args)

