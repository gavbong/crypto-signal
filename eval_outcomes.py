"""
eval_outcomes.py — Walk-forward outcome evaluator.
Runs every hour via APScheduler.
"""
import sys
from datetime import datetime, timezone
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from utils.config import env, get as cfg
from utils.ccxt_wrapper import _make_exchange
from db.schema import init_db, get_conn
from eval.outcomes import run_evaluation


logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")
logger.add("logs/eval_outcomes.log", rotation="1 day", retention="7 days", level="DEBUG")


def job(exchange) -> None:
    with get_conn() as conn:
        result = run_evaluation(conn, exchange)
        logger.info(f"Evaluation run complete | resolved={result['resolved']}")


def main() -> None:
    import os
    os.makedirs("logs", exist_ok=True)

    init_db()
    c = cfg()

    exchange = _make_exchange(env("MEXC_API_KEY"), env("MEXC_SECRET"))

    logger.info("Outcome evaluator starting | runs every 1 hour")

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        job,
        "interval",
        hours=1,
        args=[exchange],
        next_run_time=datetime.now(timezone.utc),
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Evaluator stopped by user")


if __name__ == "__main__":
    main()
