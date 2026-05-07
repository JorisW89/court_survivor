"""
Seed the database with test data for local development.

Test accounts (all passwords: testpass123):
  test@test.com    → testplayer  (picked correctly every round, 124 pts past)
  alice@test.com   → alice       (wrong pick in Final, 60 pts past)
  bob@test.com     → bob         (wrong pick in Semi Final, 28 pts past)
  charlie@test.com → charlie     (wrong pick in Quarter Final, 12 pts past)
"""

import secrets
from datetime import datetime, timedelta, timezone

from .auth import hash_password
from .database import SessionLocal
from .models import (
    Game, GameParticipant, Group, GroupMember, Match,
    Pick, Player, Round, Tournament, User,
)


PASSWORD = "testpass123"


def seed():
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == "test@test.com").first():
            print("[seed] Already seeded, skipping")
            return

        print("[seed] Seeding test data...")
        db.begin_nested()  # savepoint so a failure rolls back cleanly

        # ── Users ──────────────────────────────────────────────────────────
        test_user = _add_user(db, "test@test.com", "testplayer")
        alice     = _add_user(db, "alice@test.com", "alice")
        bob       = _add_user(db, "bob@test.com", "bob")
        charlie   = _add_user(db, "charlie@test.com", "charlie")

        # ── Players ────────────────────────────────────────────────────────
        # These mirror realistic PSA names
        MEN = [
            "M. Asal", "A. Gawad", "T. Abouelghar", "M. ElShorbagy",
            "S. Farag", "N. Elia", "K. Ghosal", "R. Kandra",
            "M. Marwan", "I. Basem", "O. Mosaad", "J. Willstrop",
            "G. Parker", "A. Sobhi", "Y. Soliman", "M. Hammo",
        ]
        WOMEN = [
            "N. El Tayeb", "C. Eyre", "H. Blundell", "N. David",
            "L. Serme", "S. Gilis", "A. Loutfy", "F. Dohy",
        ]

        players = {}
        for name in MEN + WOMEN:
            p = Player(name=name, normalized_name=name.lower())
            db.add(p)
            db.flush()
            players[name] = p

        # ══════════════════════════════════════════════════════════════════
        # PAST TOURNAMENT — El Gouna International 2026 (completed)
        # ══════════════════════════════════════════════════════════════════
        past = Tournament(
            psa_url="https://example.com/el-gouna-2026/",
            title="El Gouna International 2026",
            category="PSA World Tour Gold",
            start_date="2026-03-25",
            end_date="2026-04-01",
            status="completed",
            last_synced=datetime.now(timezone.utc),
        )
        db.add(past)
        db.flush()

        # Rounds (all completed)
        r32  = _round(db, past.id, "Men", "Round of 32",   3, "2026-03-26")
        l16  = _round(db, past.id, "Men", "Last 16",       4, "2026-03-27")
        qf   = _round(db, past.id, "Men", "Quarter Final", 5, "2026-03-28")
        sf   = _round(db, past.id, "Men", "Semi Final",    6, "2026-03-30")
        fin  = _round(db, past.id, "Men", "Final",         7, "2026-04-01")

        for r in [r32, l16, qf, sf, fin]:
            r.status = "completed"

        # Matches — build a logical bracket
        #   R32:  Asal✓  Gawad✓  Abouelghar✓  ElShorbagy✓
        #         Farag✓  Elia✓  Ghosal✓  Kandra✓
        _match(db, past, r32, "Men", players, "M. Asal",        "M. Marwan",     "M. Asal",        "r32-1")
        _match(db, past, r32, "Men", players, "A. Gawad",       "I. Basem",      "A. Gawad",       "r32-2")
        _match(db, past, r32, "Men", players, "T. Abouelghar",  "O. Mosaad",     "T. Abouelghar",  "r32-3")
        _match(db, past, r32, "Men", players, "M. ElShorbagy",  "J. Willstrop",  "M. ElShorbagy",  "r32-4")
        _match(db, past, r32, "Men", players, "S. Farag",       "G. Parker",     "S. Farag",       "r32-5")
        _match(db, past, r32, "Men", players, "N. Elia",        "A. Sobhi",      "N. Elia",        "r32-6")
        _match(db, past, r32, "Men", players, "K. Ghosal",      "Y. Soliman",    "K. Ghosal",      "r32-7")
        _match(db, past, r32, "Men", players, "R. Kandra",      "M. Hammo",      "R. Kandra",      "r32-8")

        #   L16: Asal✓  Abouelghar✓  Farag✓  Ghosal✓
        _match(db, past, l16, "Men", players, "M. Asal",       "A. Gawad",      "M. Asal",       "l16-1")
        _match(db, past, l16, "Men", players, "T. Abouelghar", "M. ElShorbagy", "T. Abouelghar", "l16-2")
        _match(db, past, l16, "Men", players, "S. Farag",      "N. Elia",       "S. Farag",      "l16-3")
        _match(db, past, l16, "Men", players, "K. Ghosal",     "R. Kandra",     "K. Ghosal",     "l16-4")

        #   QF: Asal✓  Farag✓
        _match(db, past, qf, "Men", players, "M. Asal",      "T. Abouelghar", "M. Asal",  "qf-1")
        _match(db, past, qf, "Men", players, "S. Farag",     "K. Ghosal",     "S. Farag", "qf-2")

        #   SF: Asal✓
        _match(db, past, sf, "Men", players, "M. Asal",  "S. Farag",      "M. Asal", "sf-1")

        #   Final: Asal wins the whole thing
        _match(db, past, fin, "Men", players, "M. Asal", "T. Abouelghar", "M. Asal", "fin-1")

        past_game = Game(tournament_id=past.id, division="Men", status="completed")
        db.add(past_game)
        db.flush()

        # test_user: correct every round — 4+8+16+32+64 = 124 pts
        _participant(db, past_game, test_user, 124)
        _pick(db, past_game, test_user, r32, players["M. Asal"],       True,  4)
        _pick(db, past_game, test_user, l16, players["M. Asal"],       True,  8)
        _pick(db, past_game, test_user, qf,  players["M. Asal"],       True,  16)
        _pick(db, past_game, test_user, sf,  players["M. Asal"],       True,  32)
        _pick(db, past_game, test_user, fin, players["M. Asal"],       True,  64)

        # alice: wrong in Final — 4+8+16+32 = 60 pts
        _participant(db, past_game, alice, 60)
        _pick(db, past_game, alice, r32, players["T. Abouelghar"], True,  4)
        _pick(db, past_game, alice, l16, players["T. Abouelghar"], True,  8)
        _pick(db, past_game, alice, qf,  players["T. Abouelghar"], True,  16)
        _pick(db, past_game, alice, sf,  players["S. Farag"],      True,  32)
        _pick(db, past_game, alice, fin, players["T. Abouelghar"], False, 0)

        # bob: wrong in Semi Final — 4+8+16 = 28 pts
        _participant(db, past_game, bob, 28)
        _pick(db, past_game, bob, r32, players["S. Farag"],  True,  4)
        _pick(db, past_game, bob, l16, players["S. Farag"],  True,  8)
        _pick(db, past_game, bob, qf,  players["S. Farag"],  True,  16)
        _pick(db, past_game, bob, sf,  players["S. Farag"],  False, 0)

        # charlie: wrong in Quarter Final — 4+8 = 12 pts
        _participant(db, past_game, charlie, 12)
        _pick(db, past_game, charlie, r32, players["K. Ghosal"], True,  4)
        _pick(db, past_game, charlie, l16, players["K. Ghosal"], True,  8)
        _pick(db, past_game, charlie, qf,  players["K. Ghosal"], False, 0)

        # ══════════════════════════════════════════════════════════════════
        # ACTIVE TOURNAMENT — PSA World Tour Silver (in progress)
        # Round of 32 completed, Last 16 OPEN — test_user can pick
        # ══════════════════════════════════════════════════════════════════
        now = datetime.now(timezone.utc)
        active = Tournament(
            psa_url="https://example.com/active-silver-2026/",
            title="Black Ball Open 2026",
            category="PSA World Tour Silver",
            start_date=(now - timedelta(days=3)).strftime("%Y-%m-%d"),
            end_date=(now + timedelta(days=5)).strftime("%Y-%m-%d"),
            status="active",
            last_synced=now,
        )
        db.add(active)
        db.flush()

        # Round of 32 — completed 2 days ago
        ar32 = Round(
            tournament_id=active.id, division="Men",
            name="Round of 32", round_order=3, status="completed",
            first_match_time=now - timedelta(days=3),
            pick_deadline=now - timedelta(days=4),
        )
        db.add(ar32)
        db.flush()

        # Last 16 — open, deadline in 2 days
        al16_deadline = now + timedelta(days=2)
        al16 = Round(
            tournament_id=active.id, division="Men",
            name="Last 16", round_order=4, status="open",
            first_match_time=now + timedelta(days=3),
            pick_deadline=al16_deadline,
        )
        db.add(al16)
        db.flush()

        # R32 matches and results
        _match(db, active, ar32, "Men", players, "M. Asal",       "M. Hammo",    "M. Asal",       "a-r32-1")
        _match(db, active, ar32, "Men", players, "A. Gawad",      "G. Parker",   "A. Gawad",      "a-r32-2")
        _match(db, active, ar32, "Men", players, "T. Abouelghar", "Y. Soliman",  "T. Abouelghar", "a-r32-3")
        _match(db, active, ar32, "Men", players, "S. Farag",      "I. Basem",    "S. Farag",      "a-r32-4")
        _match(db, active, ar32, "Men", players, "N. Elia",       "R. Kandra",   "N. Elia",       "a-r32-5")
        _match(db, active, ar32, "Men", players, "K. Ghosal",     "O. Mosaad",   "K. Ghosal",     "a-r32-6")
        _match(db, active, ar32, "Men", players, "M. ElShorbagy", "A. Sobhi",    "M. ElShorbagy", "a-r32-7")
        _match(db, active, ar32, "Men", players, "M. Marwan",     "J. Willstrop","M. Marwan",     "a-r32-8")

        # L16 matches — no winners yet, these are the upcoming matches to pick from
        _match(db, active, al16, "Men", players, "M. Asal",       "A. Gawad",      None, "a-l16-1")
        _match(db, active, al16, "Men", players, "T. Abouelghar", "S. Farag",      None, "a-l16-2")
        _match(db, active, al16, "Men", players, "N. Elia",       "K. Ghosal",     None, "a-l16-3")
        _match(db, active, al16, "Men", players, "M. ElShorbagy", "M. Marwan",     None, "a-l16-4")

        active_game = Game(tournament_id=active.id, division="Men", status="active")
        db.add(active_game)
        db.flush()

        # test_user: correct R32 (+8 pts), no L16 pick yet
        _participant(db, active_game, test_user, 8)
        _pick(db, active_game, test_user, ar32, players["M. Asal"], True, 8)

        # alice: wrong in R32 (picked Kandra who lost), 0 pts
        _participant(db, active_game, alice, 0)
        _pick(db, active_game, alice, ar32, players["R. Kandra"], False, 0)

        # bob: correct R32 (+8 pts), no L16 pick yet
        _participant(db, active_game, bob, 8)
        _pick(db, active_game, bob, ar32, players["S. Farag"], True, 8)

        # charlie: correct R32 (+8 pts), no L16 pick yet
        _participant(db, active_game, charlie, 8)
        _pick(db, active_game, charlie, ar32, players["M. ElShorbagy"], True, 8)

        # ── Shared group ───────────────────────────────────────────────────
        group = Group(
            name="The Squash Crew",
            invite_code=secrets.token_urlsafe(8),
            created_by=test_user.id,
        )
        db.add(group)
        db.flush()
        for u in [test_user, alice, bob, charlie]:
            db.add(GroupMember(group_id=group.id, user_id=u.id))

        db.commit()
        print("[seed] Done!")
        print("[seed] Test accounts (password: testpass123):")
        print("       test@test.com   → testplayer  (124 pts past, 8 pts active, L16 pick open)")
        print("       alice@test.com   → alice        (wrong pick in Final / wrong in R32, L16 open)")
        print("       bob@test.com     → bob          (wrong pick in SF / correct R32, L16 open)")
        print("       charlie@test.com → charlie      (wrong pick in QF / correct R32, L16 open)")

    except Exception as e:
        db.rollback()
        print(f"[seed] Failed: {e}")
    finally:
        db.close()


# ── Helpers ────────────────────────────────────────────────────────────────

def _add_user(db, email, username):
    u = User(email=email, username=username, password_hash=hash_password(PASSWORD))
    db.add(u)
    db.flush()
    return u


def _round(db, tournament_id, division, name, order, date_str):
    from dateutil import parser as dp
    dt = dp.parse(date_str).replace(hour=17, minute=0, second=0)
    deadline = dt.replace(hour=23, minute=59, second=59) - timedelta(days=1)
    r = Round(
        tournament_id=tournament_id, division=division,
        name=name, round_order=order, status="completed",
        first_match_time=dt, pick_deadline=deadline,
    )
    db.add(r)
    db.flush()
    return r


def _match(db, tournament, round_obj, division, players, p1, p2, winner, raw_id):
    m = Match(
        tournament_id=tournament.id, round_id=round_obj.id, division=division,
        player1_id=players[p1].id, player2_id=players[p2].id,
        winner_id=players[winner].id if winner else None,
        score="3-1" if winner else None,
        match_time=round_obj.first_match_time,
        psa_raw_id=raw_id,
    )
    db.add(m)
    db.flush()
    return m


def _participant(db, game, user, points):
    p = GameParticipant(game_id=game.id, user_id=user.id, total_points=points)
    db.add(p)
    db.flush()
    return p


def _pick(db, game, user, round_obj, player, is_correct, points):
    p = Pick(
        game_id=game.id, user_id=user.id, round_id=round_obj.id,
        player_id=player.id, is_correct=is_correct, points_awarded=points,
    )
    db.add(p)
    db.flush()
    return p
