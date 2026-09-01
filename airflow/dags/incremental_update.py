from datetime import datetime

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator


with DAG(
    dag_id="idx_incremental_update",
    start_date=datetime(2026, 1, 1, tzinfo=pendulum.timezone("Asia/Jakarta")),
    schedule="0 18 * * 1-5",
    catchup=False,
    max_active_runs=1,
    tags=["idx", "daily"],
) as dag:
    BashOperator(
        task_id="daily_market_update",
        bash_command="/opt/airflow/idx-venv/bin/idx-platform daily",
    )
