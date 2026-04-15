def register(app):
    @app.route("/alive")
    def ping():
        return "", 200
