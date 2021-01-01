from flask import Blueprint
from flask import flash
from flask import g
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from werkzeug.exceptions import abort
from sqlalchemy.sql import func

from musicgamez import db
from musicgamez.main.models import *

bp = Blueprint("main", __name__)

@bp.route("/")
def index():
    return render_template("index.html", recordings=db.session.query(MiniRecordingView))

