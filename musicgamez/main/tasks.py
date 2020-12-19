from musicgamez import scheduler, db
from musicgamez.main.models import *
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from mbdata.models import Artist, ArtistCredit, Recording
import sqlalchemy, json

USER_AGENT = "musicgamez/0.0"

@scheduler.task('interval', id='fetch_beatsaber', hours=1, jitter=60)
def fetch_beatsaber():
    with db.app.app_context():
        imported = 0
        session = db.create_scoped_session()
        
        site = session.query(BeatSite).filter(BeatSite.short_name=='bs').one()
        
        for page in range(1):
            response = json.load(urlopen(Request("https://beatsaver.com/api/maps/latest/"+str(page), headers={"User-Agent": USER_AGENT})))
            
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
            scheduler.add_job('match_with_string', match_with_string, trigger='date', replace_existing=True)
        db.app.logger.info("Imported {} beatmaps for {}".format(imported, site.name))
        session.remove()

@scheduler.task('interval', id='fetch_osu', hours=1, jitter=60)
def fetch_osu():
    with db.app.app_context():
        imported = 0
        session = db.create_scoped_session()
        
        site = session.query(BeatSite).filter(BeatSite.short_name=='osu').one()
        
        cursor = {}
        for page in range(1):
            response = json.load(urlopen(Request("https://osu.ppy.sh/beatmapsets/search?"+urlencode(cursor), headers={"User-Agent": USER_AGENT})))
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
            scheduler.add_job('match_with_string', match_with_string, trigger='date', replace_existing=True)
        db.app.logger.info("Imported {} beatmaps for {}".format(imported, site.name))
        session.remove()

def match_with_string():
    with db.app.app_context():
        matched = 0
        session = db.create_scoped_session()
        for bm in session.query(Beatmap).filter(Beatmap.state == Beatmap.State.INITIAL):
            q = session.query(Recording).filter(Recording.name.ilike(bm.title),
                                                Recording.artist_credit.has(ArtistCredit.name.ilike(bm.artist)))
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
            session.commit()
        session.remove()
        s = "Matched {} beatmaps using string".format(matched)
        if matched > 0:
            db.app.logger.info(s)
        else:
            db.app.logger.debug(s)

