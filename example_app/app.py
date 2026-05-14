from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load_env import load_env_file

load_env_file(Path(__file__).resolve().parent / ".env")

from flask import Flask
import modulens

from app_logic.helpers import greet_user, farewell, checkout_config

app = Flask(__name__)

@app.route("/")
def home():
    return greet_user("World")

@app.route("/bye")
def bye():
    return farewell()

@app.route("/checkout")
def checkout():
    return str(checkout_config())

if __name__ == "__main__":
    modulens.start(include=['app', 'app_logic'])
    app.run()
