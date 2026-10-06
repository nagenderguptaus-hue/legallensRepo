"""Alembic environment. Runs at app startup (``run_migrations``) and from the CLI."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from legallens.db.models import Base

config = context.config
target_metadata = Base.metadata

if not config.get_main_option("sqlalchemy.url"):
    # CLI use (`uv run alembic ...`): take the database path from the app settings.
    from legallens.config import Settings
    from legallens.db.engine import sync_url

    settings = Settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    config.set_main_option("sqlalchemy.url", sync_url(settings.db_path))


def include_object(obj, name, type_, reflected, compare_to):
    # chunks_fts (FTS5) and its shadow tables are managed by raw SQL, not the ORM models.
    return not (type_ == "table" and name is not None and name.startswith("chunks_fts"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
