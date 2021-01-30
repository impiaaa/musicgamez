# musicgamez
Bringing smarts to your rhythm games

MusicGamez is a tool to help you find maps for your favorite rhythm
game. MusicGamez matches game levels to
[MusicBrainz](https://musicbrainz.org/) metadata, and uses the in-depth
knowledge from MusicBrainz to group maps by artist, label, genre,
license, and more.

## Developing

MusicGamez is a Python [Flask](https://flask.palletsprojects.com/en/1.1.x/) app.
In addition to everything in the Pipfile (I recommend pipenv), pyacoustid
requires the [Chromaprint](http://acoustid.org/chromaprint) library (normally
available in system package managers), and the app itself requires a PostgreSQL
database. No sample data is currently available, so you'll need to [download the
MusicBrainz database](http://ftp.musicbrainz.org/pub/musicbrainz/data/fullexport/)
and import it [with
mbslave](https://github.com/lalinsky/mbdata/blob/v25.0.4/README.rst).
