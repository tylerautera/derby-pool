import os, secrets, string, math
from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask import request, jsonify
import random
from dotenv import load_dotenv
from models import db, Player, Horse, Bet, Result
import pandas as pd, pathlib
import re, unicodedata
from flask import url_for, jsonify
from datetime import datetime, timedelta
import pytz
from flask import abort

load_dotenv()                                           # .env for local dev

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pool.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = secrets.token_hex(16)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        _load_horses_from_excel()

    # ------------ routes -------------
    @app.route('/', methods=['GET', 'POST'])
    def login():

        default_code = request.args.get("code", "").strip()

        if request.method == 'POST':
            name  = request.form['name'].strip()
            code  = request.form['code'].strip()
            if code != os.getenv('EVENT_CODE'):
                flash('Wrong event code', 'danger')
                return redirect(url_for('login'))

            player = Player.query.filter_by(name=name).first()
            if not player:
                player = Player(name=name)
                db.session.add(player)
                db.session.commit()
            session['player_id'] = player.id
            return redirect(url_for('dashboard'))
        return render_template('login.html', default_code=default_code,lock_code=bool(default_code))
    
    @app.route("/players")
    def players():
        _require_login()
        totals = (
            db.session.query(
                Player.name,
                db.func.coalesce(db.func.sum(Bet.chips), 0).label("chips")
            )
            .outerjoin(Bet)
            .group_by(Player.id)
            .order_by(Player.name)
            .all()
        )
        chip_value = int(os.getenv("CHIP_VALUE", 1))      # change here if chips ≠ $1
        return render_template(
            "players.html",
            totals=totals,
            chip_value=chip_value
        )
    
    @app.route("/logout")
    def logout():
        """
        Clear the current player’s session cookie and
        bounce back to the login screen.
        """
        session.clear()                      # wipes everything for this client :contentReference[oaicite:0]{index=0}
        return redirect(url_for("login"))

    @app.route('/dashboard', methods=['GET', 'POST'])
    def dashboard():
        _require_login()
        if request.method == 'POST':
            require_betting_open()
            horse_id  = int(request.form['horse'])
            pool      = request.form['pool']          # WIN / PLC / SHW
            chips     = int(request.form['chips'])
            bet = Bet(player_id=session['player_id'],
                      horse_id=horse_id, pool=pool, chips=chips)
            db.session.add(bet)
            db.session.commit()
            return redirect(url_for('dashboard'))

        player = Player.query.get(session['player_id'])
        horses = Horse.query.order_by(Horse.number).all()
        display_map = {
            h.id: f"{h.number:02d} – {h.name} ({h.jockey}) │ {h.odds}" for h in horses
        }
        bets   = Bet.query.all()
        totals = _totals_by_pool()
        return render_template('dashboard.html',
                               horses=horses, display_map=display_map, bets=bets, totals=totals,player_name=player.name)

    @app.route('/results', methods=['GET', 'POST'])
    def results():
        _require_login()
        horses = Horse.query.order_by(Horse.number).all()
        res    = Result.query.first()

        if request.method == 'POST':
            first, second, third = (int(request.form[f'p{i}']) for i in '123')
            if res:
                res.first_id, res.second_id, res.third_id = first, second, third
            else:
                res = Result(first_id=first, second_id=second, third_id=third)
                db.session.add(res)
            db.session.commit()
            return redirect(url_for('results'))

        payouts = _calc_payouts(res) if res else {}
        return render_template('results.html',
                               horses=horses, res=res, payouts=payouts)
    
    @app.route("/viz")
    def viz():
        return render_template("viz.html")
    
    @app.route("/mybets", methods=["GET", "POST"])
    def mybets():
        _require_login()
        pid = session["player_id"]

        # handle delete clicks
        if request.method == "POST":
            require_betting_open()
            bet_id = int(request.form["delete_id"])
            Bet.query.filter_by(id=bet_id, player_id=pid).delete()
            db.session.commit()
            return redirect(url_for("mybets"))

        bets = (db.session.query(Bet, Horse)
                .join(Horse, Bet.horse_id == Horse.id)
                .filter(Bet.player_id == pid)
                .order_by(Bet.id.desc())
                .all())
        return render_template("mybets.html", bets=bets)
    
    @app.route("/betsimulator", methods=['GET', 'POST'])
    def bet_simulator():
        people = int(request.args.get("people", 10))
        bets   = int(request.args.get("bets",   20))

        # build player objects ---------------------------------------------------
        players = [Player(name=player_name_from_index(i)) for i in range(people)]
        db.session.bulk_save_objects(players, return_defaults=True)   # ← fetch PKs
        db.session.flush()                                       # get primary keys

        horse_ids = [h.id for h in Horse.query.all()]
        pools     = ["WIN", "PLC", "SHW"]

        # create random bets ------------------------------------------------------
        bet_objs = []
        rng = random.SystemRandom()                             # crypto-strong but just as fast
        for p in players:
            for _ in range(bets):
                bet_objs.append(
                    Bet(player_id = p.id,
                        horse_id  = rng.choice(horse_ids),      # uniform random :contentReference[oaicite:3]{index=3}
                        pool      = rng.choice(pools),          # WIN / PLC / SHW :contentReference[oaicite:4]{index=4}
                        chips     = rng.randint(1, 5) ))
            
        db.session.bulk_save_objects(bet_objs)
        db.session.commit()

        return jsonify({"players_created": people,
                        "bets_created":    len(bet_objs)})
    
    @app.get("/api/leader_horse")
    def leader_horse():
        chip_value = int(os.getenv("CHIP_VALUE", 1))
        q = (db.session.query(Horse, db.func.sum(Bet.chips).label("chips"))
            .outerjoin(Bet).group_by(Horse.id)
            .order_by(db.desc("chips"))
            .limit(10))
        rows = []
        for h, chips in q:
            dollars = (chips or 0) * chip_value
            rows.append({
                "horse":  h.name,
                "odds":   h.odds,
                "dollars": dollars,
                "silk":   url_for("static", filename=f"silks/{h.name}.png")
            })
        return jsonify(rows)
      

    @app.get("/api/leader_player")
    def leader_player():
        chip_value = int(os.getenv("CHIP_VALUE", 1))
        rows = (db.session.query(Player.name,
                                db.func.coalesce(db.func.sum(Bet.chips),0).label("chips"))
                .outerjoin(Bet)
                .group_by(Player.id)
                .order_by(db.desc("chips"))
                .limit(10))
        return jsonify([{"player": n, "dollars": c * chip_value} for n, c in rows])


    @app.get("/api/pools")
    def pools():
        d = dict(_pool_totals())
        return {"WIN": d.get("WIN", 0), "PLC": d.get("PLC", 0), "SHW": d.get("SHW", 0)}
    

    @app.context_processor
    def inject_venmo_link():
        venmo_user   = os.getenv("VENMO_USER", "greg rothermel")
        chip_value   = int(os.getenv("CHIP_VALUE", 1))
        total_bet    = 0
        if session.get("player_id"):
            total_bet = (db.session.query(
                            db.func.coalesce(db.func.sum(Bet.chips), 0))
                        .filter(Bet.player_id == session["player_id"])
                        .scalar() or 0) * chip_value

        deeplink = (f"venmo://paycharge?txn=pay&recipients={venmo_user}"
                    f"&amount={total_bet}&note=Derby%20Pool")
        # fallback for desktop browsers
        web_fallback = (f"https://venmo.com/{venmo_user}"
                        f"?txn=pay&amount={total_bet}&note=Derby%20Pool")
        return {
            "my_total_bet": total_bet,
            "venmo_deeplink": deeplink if total_bet else web_fallback
        }
        
    admin = Admin(app, name="Derby Admin", template_mode="bootstrap4")

# Lock the UI so only you can access it
    class SecureModelView(ModelView):
        can_view_details = True                  # add “details” button
        def is_accessible(self):
            # Allow only when you're logged in AND flagged admin; adapt to your logic
            return True   # 1 == Tyler Autera
        def inaccessible_callback(self, name, **kw):
            return redirect(url_for("login"))

    # One line per model
    admin.add_view(SecureModelView(Player,  db.session, category="Data"))
    admin.add_view(SecureModelView(Horse,   db.session, category="Data"))
    admin.add_view(SecureModelView(Bet,     db.session, category="Data"))
    admin.add_view(SecureModelView(Result,  db.session, category="Data"))

    return app





# ---------- helpers ----------

POST_TIME = datetime(2025, 5, 3, 17, 24, tzinfo=pytz.timezone("US/Eastern"))


def _pool_totals():
    return (db.session.query(
              Bet.pool,
              db.func.sum(Bet.chips).label("chips"))
            .group_by(Bet.pool).all())  

def slug(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_').lower()

def betting_open() -> bool:
    return datetime.now(POST_TIME.tzinfo) < POST_TIME - timedelta(minutes=5)

def require_betting_open():
    if not betting_open() and not session.get("is_admin"):
        abort(403)  


def _load_horses_from_excel(path="horses.xlsx"):
    """
    Read Number | Horse | Jockey | Odds  and bulk-insert into Horse table
    if the DB is empty.  Uses pandas.read_excel for robust XLSX parsing.
    """
    file = pathlib.Path(path)
    if not file.exists() or Horse.query.count():
        return                                      # already seeded or file missing

    df = pd.read_excel(file)                       # columns auto-matched by header
    required = {"Number", "Horse", "Jockey", "Odds"}
    if not required.issubset(df.columns):
        raise ValueError(f"Missing columns in {path}")

    horses = [
        Horse(
            number=int(row["Number"]),
            name=str(row["Horse"]).strip(),
            jockey=str(row["Jockey"]).strip(),
            odds=str(row["Odds"]),
        )
        for _, row in df.iterrows()
    ]
    db.session.bulk_save_objects(horses)
    db.session.commit()


def player_name_from_index(i: int) -> str:
    """
    0 → 'Player A', 25 → 'Player Z',
    26 → 'Player AA', 51 → 'Player ZZ',
    52 → 'Player AAA', … (repeats of same letter).
    """
    letters = string.ascii_uppercase                       # 26 chars  :contentReference[oaicite:0]{index=0}
    n       = len(letters)

    # how many repeats? 0-based
    repeat  = i // n                                       # every 26 players, bump repeat
    letter  = letters[i % n]
    return f"Player {letter * (repeat + 1)}"


def _require_login():
    from flask import abort
    if 'player_id' not in session:
        abort(401)

def _seed_horses_if_empty():
    if Horse.query.count() == 0:
        default = [
            "Fierceness", "Sierra Leone", "Forever Young",
            "Catching Freedom", "Just a Touch"
        ]
        db.session.bulk_save_objects([Horse(name=h) for h in default])
        db.session.commit()

def _totals_by_pool():
    pools = {'WIN':0,'PLC':0,'SHW':0}
    for pool, total in db.session.query(Bet.pool, db.func.sum(Bet.chips)).group_by(Bet.pool):
        pools[pool] = total
    return pools

def _calc_payouts(res: Result):
    """Return {player_name: net_winnings} dict."""
    if not res: return {}
    winning_map = {
        'WIN':  [res.first_id],
        'PLC':  [res.first_id, res.second_id],
        'SHW':  [res.first_id, res.second_id, res.third_id],
    }
    # pool sizes
    pool_size = {p: db.session.query(db.func.sum(Bet.chips)).filter_by(pool=p).scalar() or 0
                 for p in ('WIN','PLC','SHW')}

    payouts = {}
    for bet in Bet.query.all():
        if bet.horse_id in winning_map[bet.pool]:
            share = pool_size[bet.pool] / \
                    sum(b.chips for b in Bet.query.filter(Bet.pool==bet.pool,
                                                          Bet.horse_id.in_(winning_map[bet.pool])))
            player = Player.query.get(bet.player_id).name
            payouts[player] = payouts.get(player,0) + bet.chips * share
    return payouts


# ---------- entrypoint ----------
app = create_app()
