from datetime import date, datetime

import pendulum
from airflow import DAG
from airflow.models.param import Param
from airflow.operators.bash import BashOperator


with DAG(
    dag_id="idx_backfill_ohlcv",
    start_date=datetime(2026, 1, 1, tzinfo=pendulum.timezone("Asia/Jakarta")),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["idx", "backfill"],
    params={
        "start_date": Param("2000-01-01", type="string", format="date"),
        "end_date": Param(date.today().isoformat(), type="string", format="date"),
    },
) as dag:
    BashOperator(
        task_id="backfill_ohlcv",
        bash_command=(
            "/opt/airflow/idx-venv/bin/idx-platform backfill "
            "--start '{{ params.start_date }}' --end '{{ params.end_date }}'"
        ),
    )
