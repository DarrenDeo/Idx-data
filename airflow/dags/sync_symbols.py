from datetime import datetime

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator


with DAG(
    dag_id="idx_sync_symbols",
    start_date=datetime(2026, 1, 1, tzinfo=pendulum.timezone("Asia/Jakarta")),
    schedule="0 17 * * 1-5",
    catchup=False,
    max_active_runs=1,
    tags=["idx", "symbols"],
) as dag:
    BashOperator(
        task_id="sync_symbols",
        bash_command="/opt/airflow/idx-venv/bin/idx-platform sync-symbols",
    )
