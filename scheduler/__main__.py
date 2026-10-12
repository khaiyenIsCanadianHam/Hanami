"""One scheduler process per instance; database jobs survive worker restarts."""

import fcntl
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

from app import create_app
from app.services.automation_service import scheduler_tick


def main():
    app = create_app()
    lock_path = Path(app.instance_path) / "scheduler.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(
                "Another scheduler already owns this instance. Run exactly one worker."
            )
        scheduler = BlockingScheduler(timezone="UTC")

        def tick():
            with app.app_context():
                try:
                    scheduler_tick()
                finally:
                    from app.extensions import db

                    db.session.remove()

        scheduler.add_job(
            tick,
            "interval",
            seconds=30,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        tick()
        print(
            "WebDev CRM scheduler running; durable jobs are processed every 30 seconds."
        )
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            if scheduler.running:
                scheduler.shutdown(wait=True)


if __name__ == "__main__":
    main()
