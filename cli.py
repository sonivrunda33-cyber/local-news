"""Command line helpers:  flask --app app <command>"""
import json
from pathlib import Path

import click
from flask import current_app

from database import connect
from services import citizen_verification, locations


def register(app):
    @app.cli.command("init-db")
    def init_db_command():
        """(Re)apply schema.sql and seed locations / dev citizens (idempotent)."""
        from database import init_db
        init_db(current_app)
        click.echo("Database initialised.")

    @app.cli.command("import-citizens")
    @click.argument("csv_file", type=click.Path(exists=True, dir_okay=False))
    def import_citizens(csv_file):
        """Securely import citizen records from CSV (Citizen_ID,Citizen_ID_Code,Citizen_Name)."""
        db = connect(current_app.config["DATABASE"])
        added, skipped = citizen_verification.import_citizens_csv(
            db, csv_file, current_app.config["CITIZEN_PEPPER"], current_app.config["HASH_METHOD"])
        click.echo(f"Imported {added} citizens, skipped {skipped} existing. "
                   "Delete the CSV now - it contains plain-text codes.")

    @app.cli.command("import-locations")
    @click.argument("csv_file", type=click.Path(exists=True, dir_okay=False))
    def import_locations(csv_file):
        """Import/update locations from CSV (state,city,area). Existing rows are kept."""
        db = connect(current_app.config["DATABASE"])
        added = locations.import_locations_csv(db, csv_file)
        click.echo(f"Added: {added}")

    @app.cli.command("show-dev-credentials")
    def show_dev_credentials():
        """DEVELOPMENT ONLY: print the dummy test credentials."""
        if current_app.config["ENV_NAME"] != "development":
            raise click.ClickException("Refusing to print dummy credentials outside development.")
        path = Path(current_app.config["DUMMY_CITIZENS_FILE"])
        records = json.loads(path.read_text(encoding="utf-8"))["citizens"]
        click.echo("DUMMY / TEST DATA - fictional, local testing only")
        for r in records:
            click.echo(f"{r['Citizen_Name']:<22} ID {r['Citizen_ID']}  CODE {r['Citizen_ID_Code']}")
