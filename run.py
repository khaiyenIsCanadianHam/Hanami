"""Flask and WSGI entrypoint: flask --app run:create_app run."""
from app import create_app

if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000)
