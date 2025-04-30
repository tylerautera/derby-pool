import os, secrets
from flask import Flask, render_template, request, redirect, session, url_for, flash
from dotenv import load_dotenv
from models import db, Player, Horse, Bet, Result
import pandas as pd, pathlib


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
        chip_value = 1        # change here if chips ≠ $1
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

    return app





# ---------- helpers ----------

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
