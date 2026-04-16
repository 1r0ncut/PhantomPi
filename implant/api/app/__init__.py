from flask import Flask
import os
import logging

def create_app():
    app = Flask(__name__)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("/opt/implant/api/logs/server.log"),
            logging.StreamHandler()
        ]
    )

    app.logger.info("Implant API server starting up...")

    # Dynamically register route modules
    routes_path = os.path.join(os.path.dirname(__file__), "routes")
    for fname in os.listdir(routes_path):
        if fname.endswith(".py") and fname != "__init__.py":
            mod = __import__(f"app.routes.{fname[:-3]}", fromlist=["register"])
            if hasattr(mod, "register"):
                mod.register(app)

    return app
