from flask import Flask
import sys
sys.path.append("..")  # ensure modulens is importable

import modulens

from app_logic.helpers import greet_user, farewell

app = Flask(__name__)

@app.route("/")
def home():
    return greet_user("World")

@app.route("/bye")
def bye():
    return farewell()

if __name__ == "__main__":
    modulens.start(include=['app'])
    app.run()
