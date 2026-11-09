def register_blueprints(app):
    from .auth import bp as auth_bp
    from .borrower_portal import bp as portal_bp
    from .borrowers import bp as borrowers_bp
    from .dashboard import bp as dashboard_bp
    from .loans import bp as loans_bp
    from .me import bp as me_bp
    from .payments import bp as payments_bp

    for bp in (auth_bp, me_bp, borrowers_bp, loans_bp, payments_bp, dashboard_bp, portal_bp):
        app.register_blueprint(bp, url_prefix="/api")
