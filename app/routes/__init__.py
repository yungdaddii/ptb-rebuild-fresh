from .main import bp as main_bp
from .opportunities import bp as opportunities_bp

def init_app(app):
    app.register_blueprint(main_bp)
    app.register_blueprint(opportunities_bp, url_prefix='/opportunities')

def init_routes(app):
    app.register_blueprint(opportunities_bp, url_prefix='/api/opportunities') 