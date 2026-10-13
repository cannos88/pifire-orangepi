from flask import Blueprint

wifi_bp = Blueprint('wifi_bp', __name__,
                     template_folder='templates',
                     static_folder='static',
                     url_prefix='/wifi')

from . import routes
