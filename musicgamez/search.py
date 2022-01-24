import mbdata
import mbdata.search
from mbdata.search import Entity, Field, CustomArtist
from mbdata.models import Artist, ArtistCredit, ArtistCreditName, Recording
from sqlalchemy.orm import relationship, backref
from lxml import etree as ET

# mbdata includes integration with Solr, a search engine. Which is nice!
# Unfortunately, the way it sets up the search index is not very useful to us.
# For example, we don't need to search any tables other than Recording. Again
# unfortunately, mbdata hard-codes its "search schema," which dictates both the
# search index layout as well as how to get data into the search index. Luckily,
# this is Python, so we can just override that. We just have to be careful to
# always import this module when using mbdata.search. Another benefit to rolling
# our own schema is that we can add in more field aliases, like artist aliases
# and track names.

class CustomArtistCredit(ArtistCredit):
    pass

class CustomArtistCreditName(ArtistCreditName):
    artist = relationship(CustomArtist, foreign_keys=[ArtistCreditName.artist_id], innerjoin=True)
    artist_credit = relationship(CustomArtistCredit, foreign_keys=[ArtistCreditName.artist_credit_id], innerjoin=True, backref=backref('artists_custom', order_by="ArtistCreditName.position"))

class CustomRecording(Recording):
    redirect_gids = relationship("RecordingGIDRedirect")
    tracks = relationship("Track")
    artist_credit = relationship(CustomArtistCredit, foreign_keys=[Recording.artist_credit_id], innerjoin=True)
    aliases = relationship("RecordingAlias")

mbdata.search.schema = mbdata.search.Schema([
    Entity('recording', CustomRecording, [
        Field('mbid', 'gid', type='string'),
        Field('mbid', 'redirect_gids.gid', type='string'),
        Field('name', 'name'),
        Field('name', 'aliases.name'),
        Field('name', 'tracks.name'),
        Field('artist', 'artist_credit.name'),
        Field('artist', 'artist_credit.artists_custom.artist.name'),
        Field('artist', 'artist_credit.artists_custom.artist.aliases.name'),
        Field('artist', 'tracks.artist_credit.name'),
        Field('dur', 'length'), # for standalone recordings
        Field('dur', 'tracks.length') # for recordings in albums
    ])
])

SEARCH_SCHEMA_XML = """<schema name="musicbrainz" version="1.1">
  <types>
    <fieldType name="string" class="solr.StrField" sortMissingLast="true" omitNorms="true"/>
    <fieldType name="long" class="solr.LongField" positionIncrementGap="0" />
    <fieldType name="mbid" class="solr.UUIDField" omitNorms="true" />
    <fieldType name="text_mult" class="solr.TextField" positionIncrementGap="1">
      <analyzer type="index">
        <tokenizer class="solr.StandardTokenizerFactory"/>
        <filter class="solr.LowerCaseFilterFactory"/>
        <filter class="solr.ASCIIFoldingFilterFactory"/>
      </analyzer>
      <analyzer type="query">
        <tokenizer class="solr.StandardTokenizerFactory"/>
        <filter class="solr.LowerCaseFilterFactory"/>
        <filter class="solr.ASCIIFoldingFilterFactory"/>
      </analyzer>
    </fieldType>
  </types>
  <fields>
    <field name="id" type="string" indexed="true" stored="true" required="true"/>
    <field name="kind" type="string" indexed="true" stored="true" required="true"/>
    <field name="mbid" type="mbid" indexed="true" stored="false" required="true" multiValued="true"/>
    <field name="name" type="text_mult" indexed="true" stored="false" multiValued="true"/>
    <field name="artist" type="text_mult" indexed="true" stored="false" required="true" multiValued="true"/>
    <field name="dur" type="long" indexed="true" stored="false" multiValued="true"/>
  </fields>
  <uniqueKey>id</uniqueKey>
  <defaultSearchField>name</defaultSearchField>
  <solrQueryParser defaultOperator="OR"/>
</schema>
"""

# to start:
# /usr/lib/jvm/java-1.8.0-openjdk-amd64/bin/java -Dsolr.solr.home=<mbdata_solr> -jar start.jar

