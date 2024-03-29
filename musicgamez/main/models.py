import enum
from mbdata.models import *
from musicgamez import db
from musicgamez.views import view
from sqlalchemy import event, select, DDL
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.schema import FetchedValue
from sqlalchemy.sql import func, expression
from sqlalchemy.orm import backref


class BeatSite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    short_name = db.Column(
        db.String(8),
        nullable=False,
        index=True,
        unique=True)
    url_base = db.Column(db.String)
    url_suffix = db.Column(db.String, server_default='')


@event.listens_for(BeatSite.__table__, 'after_create')
def insert_basic(target, connection, **kw):
    db.session.add(BeatSite(name='Beat Saber',
                            short_name='bs',
                            url_base='https://beatsaver.com/maps/'))
    db.session.add(BeatSite(name='osu!',
                            short_name='osu',
                            url_base='https://osu.ppy.sh/beatmapsets/'))
    db.session.commit()


class Beatmap(db.Model):
    class State(enum.Enum):
        ERROR = -1
        INITIAL = 0
        MATCHED_WITH_STRING = 1
        WAITING_FOR_FINGERPRINT = 2
        HAS_FINGERPRINT = 3
        MATCHED_WITH_FINGERPRINT = 4
        TOO_MANY_MATCHES = 5
        NO_MATCH = 6
        MATCHED_WITH_STRING_MULTIPLE = 7

    id = db.Column(db.Integer, primary_key=True)

    artist = db.Column(db.String, nullable=False)
    title = db.Column(db.String, nullable=False)

    external_id = db.Column(db.String(255), nullable=False)
    external_site_id = db.Column(
        db.Integer, db.ForeignKey(
            BeatSite.id), nullable=False)
    external_site = db.relationship(BeatSite, innerjoin=True, lazy='joined')
    i = db.Index('external_ref', external_id, external_site_id, unique=True)
    choreographer = db.Column(db.String)
    date = db.Column(db.DateTime)
    extra = db.Column(JSONB)

    state = db.Column(db.Enum(State), default=State.INITIAL, nullable=False)
    last_checked = db.Column(db.DateTime, server_default=func.now(), nullable=False, server_onupdate=FetchedValue())
    duration = db.Column(db.Float)
    fingerprint = db.Column(db.String)
    track_id = db.Column(UUID)
    recording_gid = db.Column(UUID, db.ForeignKey(Recording.gid))
    recording = db.relationship(Recording, backref=backref('beatmaps', order_by=date))

    def validate_state(self):
        if self.state == self.State.INITIAL:
            assert self.duration is None
            assert self.fingerprint is None
            assert self.track_id is None
            assert self.recording is None
        elif self.state == self.State.MATCHED_WITH_STRING or self.state == self.State.MATCHED_WITH_STRING_MULTIPLE:
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


event.listen(
    Beatmap.__table__,
    'after_create',
    DDL(
        "CREATE FUNCTION update_last_checked() "
        "RETURNS TRIGGER AS $$ "
        "BEGIN "
        "NEW.last_checked = NOW(); "
        "RETURN NEW; "
        "END; $$ LANGUAGE PLPGSQL"
    )
)

event.listen(
    Beatmap.__table__,
    'after_create',
    DDL(
        "CREATE TRIGGER update_last_checked "
        "BEFORE UPDATE ON beatmap "
        "FOR EACH ROW EXECUTE PROCEDURE update_last_checked();"
    )
)


class ArtistStreamPermission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    artist_gid = db.Column(UUID, db.ForeignKey(Artist.gid), unique=True)
    artist = db.relationship(Artist, backref='stream_permission')
    url = db.Column(db.String)
    source = db.Column(db.String)


class LabelStreamPermission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    label_gid = db.Column(UUID, db.ForeignKey(Label.gid), unique=True)
    label = db.relationship(Label, backref='stream_permission')
    url = db.Column(db.String)
    source = db.Column(db.String)


class MiniRecordingView(db.Model):
    __table__ = view(
        "mini_recording_view",
        db.metadata,
        select(
            [
                Recording.id.label("id"),
                Recording.gid.label("gid"),
                Recording.name.label("name"),
                Recording.artist_credit_id.label("artist_credit_id"),
                select([URL.url])
                    .select_from(
                        URL.__table__.join(LinkRecordingURL).join(Link).join(LinkType)
                    )
                    .where(LinkRecordingURL.recording_id == Recording.id)
                    .where(LinkType.gid == "f25e301d-b87b-4561-86a0-5d2df6d26c0a")
                    .union(
                        select([URL.url])
                        .select_from(
                            URL.__table__
                            .join(LinkReleaseURL)
                            .join(Link)
                            .join(LinkType)
                            .join(Release)
                            .join(Medium)
                            .join(Track)
                        )
                        .where(Track.recording_id == Recording.id)
                        .where(LinkType.gid == "004bd0c3-8a45-4309-ba52-fa99f3aa3d50")
                    )
                    .limit(1)
                    .label("license_url"),
                select([ArtistStreamPermission.url])
                    .select_from(
                        ArtistStreamPermission
                        .__table__.join(Artist)
                        .join(ArtistCreditName)
                        .join(ArtistCredit)
                    )
                    .where(ArtistCredit.id == Recording.artist_credit_id)
                    .union(
                        select([LabelStreamPermission.url])
                        .select_from(
                            LabelStreamPermission.__table__.join(Label)
                            .join(ReleaseLabel)
                            .join(Release)
                            .join(Medium)
                            .join(Track)
                        )
                        .where(Track.recording_id == Recording.id)
                    )
                    .limit(1)
                    .label("permission_url"),
                select([Release.gid.concat("/").concat(CoverArt.id)])
                    .select_from(
                        Release.__table__
                        .join(CoverArt)
                        .join(Medium)
                        .join(Track)
                        .join(CoverArtType)
                        .join(ArtType)
                    )
                    .where(Track.recording_id == Recording.id)
                    .where(ArtType.gid == "ac337166-a2b3-340c-a0b4-e2b00f1d40a2")
                    .order_by(func.random())
                    .limit(1)
                    .label("cover_id"),
                select(
                    [
                        "157afde4-4bf5-4039-8ad2-5a15acc85176"
                        == expression.all_(
                            select([Label.gid])
                            .select_from(
                                Track.__table__
                                .join(Medium)
                                .join(Release)
                                .outerjoin(ReleaseLabel)
                                .outerjoin(Label)
                            )
                            .where(Track.recording_id == expression.text("musicbrainz.recording.id"))
                        )
                    ]
                ).label("selfpublish"),
                func.max(Beatmap.date).label("date")
            ]
        )
        .select_from(Recording.__table__.join(Beatmap))
        .group_by(
            Recording.id, Recording.gid, Recording.name, Recording.artist_credit_id
        ),
        material=True
    )
    artist_credit = db.relationship(ArtistCredit)
    beatmaps = db.relationship(Beatmap)
    id_index = db.Index('ix_public_mini_recording_view_id', __table__.c.id, unique=True)
    gid_index = db.Index('ix_public_mini_recording_view_gid', __table__.c.gid, unique=True)

event.listen(
    db.metadata,
    'after_create',
    DDL("CREATE UNIQUE INDEX IF NOT EXISTS ix_public_mini_recording_view_id ON mini_recording_view (id)")
)

event.listen(
    db.metadata,
    'after_create',
    DDL("CREATE UNIQUE INDEX IF NOT EXISTS ix_public_mini_recording_view_gid ON mini_recording_view (gid)")
)


class GenreCloud(db.Model):
    __table__ = view(
        "genre_cloud",
        db.metadata,
        select([
            Genre.id.label("id"),
            Genre.gid.label("gid"),
            Genre.name.label("name"),
            func.count(Beatmap.id).label("count")
        ])\
        .select_from(
            Genre.__table__
            .join(Tag, Tag.name == Genre.name)
            .join(ReleaseTag)
            .join(Release)
            .join(Medium)
            .join(Track)
            .join(Recording)
            .join(Beatmap)
        )
        .group_by(Genre.id, Genre.gid, Genre.name),
        material=True
    )
    id_index = db.Index('ix_public_genre_cloud_view_id', __table__.c.id, unique=True)
    gid_index = db.Index('ix_public_genre_cloud_view_gid', __table__.c.gid, unique=True)

event.listen(
    db.metadata,
    'after_create',
    DDL("CREATE UNIQUE INDEX IF NOT EXISTS ix_public_genre_cloud_id ON genre_cloud (id)")
)

event.listen(
    db.metadata,
    'after_create',
    DDL("CREATE UNIQUE INDEX IF NOT EXISTS ix_public_genre_cloud_gid ON genre_cloud (gid)")
)
