from app.monitoring.health_check import database_available


def test_health_check_accepts_reachable_sqlite_database():
    assert database_available(":memory:")
