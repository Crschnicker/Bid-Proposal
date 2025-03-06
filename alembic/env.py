from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Import your Flask app and db from app.py
from app import app, db  # Ensure this matches the path to your app and db

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)

# Provide the target metadata to Alembic
target_metadata = db.metadata

# Define the run_migrations_offline function
def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )

    with context.begin_transaction():
        context.run_migrations()

# Define the run_migrations_online function
def run_migrations_online():
    """Run migrations in 'online' mode."""

    # Callback to handle the process_revision_directives
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                print("No changes in schema detected.")

    connectable = engine_from_config(
        config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=process_revision_directives,
            **app.extensions["migrate"].configure_args
        )

        with context.begin_transaction():
            context.run_migrations()

# Determine which mode to run in
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
