"""Database initialization and a standalone housekeeping process for WSGI deployments."""

import argparse
import logging

from db import Database
from settings import settings
from store import SeatStore
from workers import BackgroundTasks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init-db", "migrate", "seed", "worker"))
    args = parser.parse_args()
    config = settings()
    db = Database(config["DATABASE_URL"])
    if args.command in ("init-db", "migrate"):
        db.migrate()
    if args.command in ("init-db", "seed"):
        db.seed(config["SEAT_MAP_TIER"])
    if args.command == "worker":
        db.seed(config["SEAT_MAP_TIER"])
        tasks = BackgroundTasks(SeatStore(db, config["HOLD_TTL_SECONDS"]), config).start()
        try:
            while True:
                tasks.stop_event.wait(1)
        except KeyboardInterrupt:
            tasks.stop()
    else:
        print(f"{args.command}: complete (seat map: {config['SEAT_MAP_TIER']})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

