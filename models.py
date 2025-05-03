from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()

class Horse(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    number   = db.Column(db.Integer, nullable=False, unique=True)
    name     = db.Column(db.String(60), nullable=False)
    jockey   = db.Column(db.String(60), nullable=False)
    odds     = db.Column(db.String(10))
    scratched = db.Column(db.Boolean, default=False)                 # use Float for 12.5-1 etc.

class Player(db.Model):
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), unique=True, nullable=False)

class Bet(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id",ondelete='CASCADE'))
    horse_id  = db.Column(db.Integer, db.ForeignKey("horse.id",ondelete='CASCADE'))
    pool      = db.Column(db.String(3))          # WIN / PLC / SHW
    chips     = db.Column(db.Integer, default=1)

class Result(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    first_id  = db.Column(db.Integer, db.ForeignKey("horse.id"))
    second_id = db.Column(db.Integer, db.ForeignKey("horse.id"))
    third_id  = db.Column(db.Integer, db.ForeignKey("horse.id"))

