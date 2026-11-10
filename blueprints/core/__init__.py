def register_blueprints(app):
    from .auth import auth_bp
    from .central import central_bp
    from .family import family_bp
    from .preferences import preferences_bp
    from .site_admin import site_admin_bp

    for blueprint in (auth_bp, central_bp, family_bp, preferences_bp, site_admin_bp):
        app.register_blueprint(blueprint)
