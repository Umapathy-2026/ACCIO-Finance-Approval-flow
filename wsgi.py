from flask import Flask
app = Flask(__name__)

@app.route('/')
def hello():
    return '<h1>Azure is working!</h1>'
