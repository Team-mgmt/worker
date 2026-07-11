from worker.core.config import Settings


def test_split_database_settings_override_database_url_and_require_ssl() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://stale:stale@localhost/stale",
        DATABASE_HOST="db.example.com",
        DATABASE_PORT=5432,
        DATABASE_USER="book_master",
        DATABASE_PASS="p@ss/word",
        DATABASE_NAME="shelfalignerdb",
        DATABASE_LOCAL=False,
    )

    assert settings.async_database_url == (
        "postgresql+psycopg://book_master:p%40ss%2Fword"
        "@db.example.com:5432/shelfalignerdb?sslmode=require"
    )
