from musicgamez import db
#import mbdata.config
#mbdata.config.configure(base_class=db.Model)
from mbdata.models import Recording
from sqlalchemy.dialects.postgresql import UUID
from enum import Enum

class BeatSite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    url_base = db.Column(db.String)
    url_suffix = db.Column(db.String)

class Beatmap(db.Model):
    class State(Enum):
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
    external_site_id = db.Column(db.Integer, db.ForeignKey(BeatSite.id))
    external_site = db.relationship(BeatSite)
    choreographer = db.Column(db.String)
    date = db.Column(db.DateTime)
    
    state = db.Column(db.Enum(State))
    last_checked = db.Column(db.DateTime)
    fingerprint = db.Column(db.String)
    track_id = db.Column(UUID)
    recording_id = db.Column(db.Integer, db.ForeignKey(Recording.id))
    recording = db.relationship(Recording)
    
    def validate_state(self):
        if self.state == self.State.INITIAL:
            assert self.fingerprint is None
            assert self.track_id is None
            assert self.recording is None
        elif self.state == self.State.MATCHED_WITH_STRING:
            assert self.fingerprint is None
            assert self.track_id is None
            assert self.recording is not None
        elif self.state == self.State.WAITING_FOR_FINGERPRINT:
            assert self.fingerprint is None
            assert self.track_id is None
            assert self.recording is None
        elif self.state == self.State.HAS_FINGERPRINT:
            assert self.fingerprint is not None
            assert self.track_id is None
            assert self.recording is None
        elif self.state == self.State.MATCHED_WITH_FINGERPRINT:
            assert self.fingerprint is not None
            assert self.track_id is not None
            assert self.recording is not None
        elif self.state == self.State.TOO_MANY_MATCHES or self.state == self.State.NO_MATCH:
            assert self.fingerprint is not None
            assert self.track_id is not None
            assert self.recording is None

