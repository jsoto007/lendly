import os

from dotenv import find_dotenv, load_dotenv
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .extensions import db, migrate


def create_app(config_object=None):
    load_dotenv(find_dotenv(usecwd=True))
    from .config import Config

    app = Flask(__name__)
    app.config.from_object(config_object or Config)
    app.json.sort_keys = False

    db.init_app(app)
    migrate.init_app(app, db)

    from .routes import register_blueprints
    register_blueprints(app)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.errorhandler(HTTPException)
    def handle_http(e):
        return jsonify({"error": {"code": e.name.lower().replace(" ", "_"), "message": e.description}}), e.code

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        app.logger.exception("unhandled error")
        db.session.rollback()
        from .i18n import _
        return jsonify({"error": {"code": "server_error", "message": _("Something went wrong.")}}), 500

    return app
