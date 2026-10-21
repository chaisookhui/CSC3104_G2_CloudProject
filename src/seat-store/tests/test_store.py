import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import psycopg
import pytest

from conftest import ROOT
from db import Database
from store import SeatStore, StoreError


def ids(result):
    return [seat["seat_id"] for seat in result["seats"]]


def count(db, table):
    assert table in ("holds", "notification_outbox")
    with db.connect() as conn:
        return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def test_dev_map_and_non_destructive_initialization(db, store):
    assert [len(store.list_seats(s)) for s in "ABC"] == [30, 20, 10]
    original = store.hold("A", 4, "retained")
    db.migrate()
    db.seed("dev")
    assert store.hold("A", 4, "retained") == original
    with pytest.raises(ValueError, match="differs"):
        db.seed("eval")


def test_evaluation_map_uses_same_generator(db):
    # No holds exist in this disposable test schema.
    with db.connect() as conn:
        conn.execute("TRUNCATE notification_outbox, hold_seats, seats, holds, sections")
    db.seed("eval")
    evaluation = SeatStore(db)
    assert [len(evaluation.list_seats(s)) for s in "ABC"] == [200, 100, 50]


def test_leftmost_adjacency_never_crosses_rows(store):
    assert ids(store.hold("A", 4, "first")) == [f"A-1-{n}" for n in range(1, 5)]
    assert ids(store.hold("A", 4, "second")) == [f"A-1-{n}" for n in range(5, 9)]
    assert ids(store.hold("A", 3, "third")) == [f"A-2-{n}" for n in range(1, 4)]
    assert ids(store.hold("A", 2, "fourth")) == ["A-1-9", "A-1-10"]


def test_no_partial_party_on_full_section(db, store):
    for name, size in (("first", 4), ("second", 4), ("third", 2)):
        store.hold("C", size, name)
    assert store.hold("C", 1, "cannot-fit") == {"success": False}
    assert count(db, "holds") == 3


def test_fragmented_capacity_is_not_an_adjacent_block(store, make_due):
    bookings = [store.hold("C", 1, f"party-{n}") for n in range(10)]
    for n, booking in enumerate(bookings):
        if n % 2 == 0:
            make_due(booking["hold_id"])
            store.transition(booking["request_id"], "expire", booking["hold_id"])
        else:
            store.transition(booking["request_id"], "confirm", booking["hold_id"])
    assert sum(s["state"] == "AVAILABLE" for s in store.list_seats("C")) == 5
    assert store.hold("C", 2, "needs-two") == {"success": False}


def test_hold_retry_preserves_seats_and_deadline(db, store):
    first = store.hold("A", 3, "retry")
    assert store.hold("A", 3, "retry") == first
    assert count(db, "holds") == 1
    assert sum(s["state"] == "HELD" for s in store.list_seats("A")) == 3


@pytest.mark.parametrize("section,size", [("B", 2), ("A", 3)])
def test_request_id_cannot_change_booking_details(store, section, size):
    store.hold("A", 2, "same-request")
    with pytest.raises(StoreError, match="different booking details"):
        store.hold(section, size, "same-request")


def test_confirm_is_idempotent_and_cannot_expire(db, store, make_due):
    booking = store.hold("A", 4, "paid")
    confirmed = store.transition("paid", "confirm")
    assert confirmed["hold_status"] == "CONFIRMED"
    assert store.transition("paid", "confirm") == confirmed
    make_due(booking["hold_id"])
    assert store.expire_due() == 0
    with pytest.raises(StoreError) as error:
        store.transition("paid", "expire")
    assert error.value.code == "already_confirmed"
    assert all(s["state"] == "CONFIRMED" for s in confirmed["seats"])
    assert count(db, "notification_outbox") == 0


def test_expiry_releases_whole_party_and_enqueues_once(db, store, make_due):
    booking = store.hold("A", 4, "unpaid")
    make_due(booking["hold_id"])
    result = store.transition("unpaid", "expire")
    assert result["hold_status"] == "EXPIRED"
    assert store.transition("unpaid", "expire") == result
    assert len([s for s in store.list_seats("A") if s["state"] == "AVAILABLE"]) == 30
    assert count(db, "notification_outbox") == 1
    with db.connect() as conn:
        event = conn.execute("SELECT payload FROM notification_outbox").fetchone()["payload"]
    assert set(event["seats"]) == set(ids(booking))
    assert event["hold_id"] == booking["hold_id"]


def test_early_expiry_is_rejected(store):
    store.hold("A", 2, "not-due")
    with pytest.raises(StoreError) as error:
        store.transition("not-due", "expire")
    assert error.value.code == "hold_not_due"


def test_late_confirmation_releases_and_commits_notification(db, store, make_due):
    booking = store.hold("A", 3, "late")
    make_due(booking["hold_id"])
    with pytest.raises(StoreError) as error:
        store.transition("late", "confirm")
    assert error.value.code == "hold_expired"
    assert count(db, "notification_outbox") == 1
    assert all(s["state"] == "AVAILABLE" for s in store.list_seats("A"))


def test_expired_retry_cannot_silently_create_a_new_hold(store, make_due):
    booking = store.hold("A", 2, "expired")
    make_due(booking["hold_id"])
    store.transition("expired", "expire")
    with pytest.raises(StoreError) as error:
        store.hold("A", 2, "expired")
    assert error.value.code == "hold_expired"


def test_reoffers_are_idempotent_and_stale_callbacks_are_safe(store, make_due):
    old = store.hold("A", 2, "reoffered")
    make_due(old["hold_id"])
    store.transition("reoffered", "expire")
    new = store.hold("A", 2, "reoffered", reoffer_key="offer-two")
    assert new["hold_id"] != old["hold_id"]
    assert store.hold("A", 2, "reoffered", reoffer_key="offer-two") == new
    for action in ("confirm", "expire"):
        with pytest.raises(StoreError) as error:
            store.transition("reoffered", action)
        assert error.value.code == "hold_id_required"
    with pytest.raises(StoreError):
        store.transition("reoffered", "confirm", old["hold_id"])
    store.transition("reoffered", "expire", old["hold_id"])
    assert store.hold("A", 2, "reoffered", reoffer_key="offer-two") == new
    assert store.transition("reoffered", "confirm", new["hold_id"])["hold_status"] == "CONFIRMED"


def test_invalid_reoffers_are_rejected(store):
    with pytest.raises(StoreError) as error:
        store.hold("A", 1, "new", reoffer_key="not-yet")
    assert error.value.code == "invalid_reoffer"
    store.hold("A", 1, "active")
    with pytest.raises(StoreError) as error:
        store.hold("A", 1, "active", reoffer_key="too-soon")
    assert error.value.code == "booking_exists"


def test_database_failure_rolls_back_entire_party(db, store):
    with db.connect() as conn:
        conn.execute("""
            CREATE FUNCTION reject_hold_seat() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'simulated storage failure'; END $$;
            CREATE TRIGGER reject_hold_seat BEFORE INSERT ON hold_seats
            FOR EACH ROW EXECUTE FUNCTION reject_hold_seat();
        """)
    with pytest.raises(psycopg.Error):
        store.hold("A", 4, "rollback")
    assert count(db, "holds") == 0
    assert all(s["state"] == "AVAILABLE" for s in store.list_seats("A"))


def test_outbox_failure_rolls_back_release(db, store, make_due):
    booking = store.hold("A", 4, "rollback-expiry")
    make_due(booking["hold_id"])
    with db.connect() as conn:
        conn.execute("""
            CREATE FUNCTION reject_event() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'simulated outbox failure'; END $$;
            CREATE TRIGGER reject_event BEFORE INSERT ON notification_outbox
            FOR EACH ROW EXECUTE FUNCTION reject_event();
        """)
    with pytest.raises(psycopg.Error):
        store.transition("rollback-expiry", "expire")
    assert sum(s["state"] == "HELD" for s in store.list_seats("A")) == 4
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM holds").fetchone()["status"] == "ACTIVE"


def test_sixteen_simultaneous_requests_for_last_two_seats(db, store):
    store.hold("C", 4, "occupied-one")
    store.hold("C", 4, "occupied-two")
    barrier = Barrier(16)

    def compete(number):
        independent_store = SeatStore(Database(db.dsn, db.schema))
        barrier.wait(timeout=15)
        return independent_store.hold("C", 1, f"competitor-{number}")

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(compete, range(16)))
    winners = [result for result in results if result["success"]]
    assert len(winners) == 2
    assert len({seat for result in winners for seat in ids(result)}) == 2
    assert all(s["state"] == "HELD" for s in store.list_seats("C"))


def test_concurrent_duplicate_requests_share_one_hold(db):
    barrier = Barrier(10)

    def retry(_):
        barrier.wait(timeout=15)
        return SeatStore(Database(db.dsn, db.schema)).hold("A", 4, "duplicate")

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(retry, range(10)))
    assert len({result["hold_id"] for result in results}) == 1
    assert count(db, "holds") == 1


@pytest.mark.parametrize("overdue", [False, True])
def test_confirmation_and_expiry_compete_without_mixed_state(db, store, make_due, overdue):
    booking = store.hold("A", 4, "race")
    if overdue:
        make_due(booking["hold_id"])
    barrier = Barrier(2)

    def compete(action):
        barrier.wait(timeout=15)
        try:
            return store.transition("race", action)["hold_status"]
        except StoreError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(compete, ("confirm", "expire")))
    with db.connect() as conn:
        status = conn.execute("SELECT status FROM holds").fetchone()["status"]
    assert status == ("EXPIRED" if overdue else "CONFIRMED")
    state = "AVAILABLE" if overdue else "CONFIRMED"
    block = [s for s in store.list_seats("A") if s["seat_id"] in ids(booking)]
    assert len(block) == 4 and {s["state"] for s in block} == {state}
    assert count(db, "notification_outbox") == int(overdue)


def test_section_b_does_not_wait_for_section_a_lock(db, store):
    with db.connect() as conn:
        conn.execute("SELECT 1 FROM sections WHERE section = 'A' FOR UPDATE")
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(store.hold, "B", 2, "independent").result(timeout=3)
    assert result["success"]


def test_confirmation_checks_deadline_after_waiting_for_section_lock(db):
    short_store = SeatStore(db, hold_ttl=1)
    short_store.hold("A", 2, "waited-past-deadline")
    started = Event()

    def confirm():
        started.set()
        return short_store.transition("waited-past-deadline", "confirm")

    with ThreadPoolExecutor(max_workers=1) as executor:
        with db.connect() as conn:
            conn.execute("SELECT 1 FROM sections WHERE section = 'A' FOR UPDATE")
            pending = executor.submit(confirm)
            assert started.wait(timeout=2)
            conn.execute("SELECT pg_sleep(1.2)")
        with pytest.raises(StoreError) as error:
            pending.result(timeout=5)
        assert error.value.code == "hold_expired"
    assert count(db, "notification_outbox") == 1
    assert all(s["state"] == "AVAILABLE" for s in short_store.list_seats("A"))


def test_committed_hold_survives_abrupt_process_exit(db, make_due):
    script = """
import os
from db import Database
from store import SeatStore
store = SeatStore(Database(os.environ['TEST_DATABASE_URL'], os.environ['TEST_SCHEMA']))
store.hold('A', 4, 'crash-survivor')
os._exit(0)
"""
    environment = dict(os.environ, TEST_DATABASE_URL=db.dsn, TEST_SCHEMA=db.schema)
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=environment,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode()
    restarted = SeatStore(Database(db.dsn, db.schema))
    booking = restarted.hold("A", 4, "crash-survivor")
    assert len(booking["seats"]) == 4
    make_due(booking["hold_id"])
    assert restarted.expire_due() == 1
    assert count(db, "notification_outbox") == 1

