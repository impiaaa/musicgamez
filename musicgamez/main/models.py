from musicgamez import db
from musicgamez.views import view
from mbdata.models import *
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy import event, select
from sqlalchemy.sql.expression import subquery
from enum import Enum

class BeatSite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    short_name = db.Column(db.String(8), nullable=False, index=True, unique=True)
    url_base = db.Column(db.String)
    url_suffix = db.Column(db.String, server_default='')

@event.listens_for(BeatSite.__table__, 'after_create')
def insert_basic(target, connection, **kw):
    db.session.add(BeatSite(name='Beat Saber',
                            short_name='bs',
                            url_base='https://beatsaver.com/beatmap/'))
    db.session.add(BeatSite(name='osu!',
                            short_name='osu',
                            url_base='https://osu.ppy.sh/beatmapsets/'))
    db.session.commit()

class Beatmap(db.Model):
    class State(Enum):
        ERROR = -1
        INITIAL = 0
        MATCHED_WITH_STRING = 1
        WAITING_FOR_FINGERPRINT = 2
        HAS_FINGERPRINT = 3
        MATCHED_WITH_FINGERPRINT = 4
        TOO_MANY_MATCHES = 5
        NO_MATCH = 6
    
    id = db.Column(db.Integer, primary_key=True)
    
    artist = db.Column(db.String)
    title = db.Column(db.String)
    
    external_id = db.Column(db.String(255))
    external_site_id = db.Column(db.Integer, db.ForeignKey(BeatSite.id), nullable=False)
    external_site = db.relationship(BeatSite, innerjoin=True, lazy='joined')
    i = db.Index('external_ref', external_id, external_site_id, unique=True)
    choreographer = db.Column(db.String)
    date = db.Column(db.DateTime)
    
    state = db.Column(db.Enum(State), default=State.INITIAL)
    last_checked = db.Column(db.DateTime, server_default=func.now())
    duration = db.Column(db.Float)
    fingerprint = db.Column(db.String)
    track_id = db.Column(UUID)
    recording_gid = db.Column(UUID, db.ForeignKey(Recording.gid))
    recording = db.relationship(Recording, backref='beatmaps')
    
    def validate_state(self):
        if self.state == self.State.INITIAL:
            assert self.duration is None
            assert self.fingerprint is None
            assert self.track_id is None
            assert self.recording is None
        elif self.state == self.State.MATCHED_WITH_STRING:
            assert self.duration is None
            assert self.fingerprint is None
            assert self.track_id is None
            assert self.recording is not None
        elif self.state == self.State.WAITING_FOR_FINGERPRINT:
            assert self.duration is None
            assert self.fingerprint is None
            assert self.track_id is None
        elif self.state == self.State.HAS_FINGERPRINT:
            assert self.duration is not None
            assert self.fingerprint is not None
            assert self.track_id is None
        elif self.state == self.State.MATCHED_WITH_FINGERPRINT:
            assert self.duration is not None
            assert self.fingerprint is not None
            assert self.track_id is not None
            assert self.recording is not None
        elif self.state == self.State.TOO_MANY_MATCHES or self.state == self.State.NO_MATCH:
            assert self.duration is not None
            assert self.fingerprint is not None
            assert self.track_id is not None
        else:
            assert False

class MiniRecordingView(db.Model):
    __table__ = view("mini_recording_view", db.metadata,
        select([Recording.id.label("id"),
                Recording.gid.label("gid"),
                Recording.name.label("name"),
                Recording.artist_credit_id.label("artist_credit_id"),
                select([URL.url])\
                    .select_from(\
                        URL.__table__.join(LinkRecordingURL)\
                        .join(Link)\
                        .join(LinkType)\
                    )\
                    .where(LinkRecordingURL.recording_id==Recording.id)\
                    .where(LinkType.gid=='f25e301d-b87b-4561-86a0-5d2df6d26c0a')\
                    .union(select([URL.url])\
                        .select_from(\
                            URL.__table__.join(LinkReleaseURL)
                            .join(Link)\
                            .join(LinkType)\
                            .join(Release)\
                            .join(Medium)\
                            .join(Track)\
                        )\
                        .where(Track.recording_id==Recording.id)\
                        .where(LinkType.gid=='004bd0c3-8a45-4309-ba52-fa99f3aa3d50')
                    )\
                    .limit(1)\
                    .label("license_url"),
                select([Release.gid.concat('/').concat(CoverArt.id)])\
                    .select_from(\
                        Release.__table__.join(CoverArt)\
                        .join(Medium)\
                        .join(Track)\
                        .join(CoverArtType)\
                        .join(ArtType)
                    )\
                    .where(Track.recording_id==Recording.id)\
                    .where(ArtType.gid=='ac337166-a2b3-340c-a0b4-e2b00f1d40a2')\
                    .order_by(func.random())\
                    .limit(1)\
                    .label("cover_id")
               ])\
        .select_from(Recording.__table__.join(Beatmap))\
        .group_by(Recording.id, Recording.gid, Recording.name, Recording.artist_credit_id)\
        .order_by(func.max(Beatmap.date).desc())
    )
    artist_credit = db.relationship(ArtistCredit)
    beatmaps = db.relationship(Beatmap)

