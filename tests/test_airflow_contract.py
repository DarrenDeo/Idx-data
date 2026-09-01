from pathlib import Path


DAGS = Path("airflow/dags")


def test_airflow_dags_do_not_import_sqlalchemy2_application_at_parse_time():
    for path in DAGS.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from app." not in source
        assert "BashOperator" in source
        assert "/opt/airflow/idx-venv/bin/idx-platform" in source


def test_incremental_schedule_is_1800_jakarta_weekdays():
    source = (DAGS / "incremental_update.py").read_text(encoding="utf-8")
    assert 'schedule="0 18 * * 1-5"' in source
    assert 'pendulum.timezone("Asia/Jakarta")' in source

