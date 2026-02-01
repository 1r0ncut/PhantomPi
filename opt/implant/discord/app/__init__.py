from flask import Flask
import os
import logging

def create_app():
    app = Flask(__name__)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("/opt/implant/discord/logs/server.log"),
            logging.StreamHandler()
        ]
    )

    app.logger.info("Implant server starting up...")

    # Dynamically register command routes
    commands_path = os.path.join(os.path.dirname(__file__), "commands")
    for fname in os.listdir(commands_path):
        if fname.endswith(".py") and fname != "__init__.py":
            mod = __import__(f"app.commands.{fname[:-3]}", fromlist=["register"])
            if hasattr(mod, "register"):
                mod.register(app)

    return app
