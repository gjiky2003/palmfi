"""WSGI entry for Render / Gunicorn. Run: gunicorn wsgi:app"""
import os, sys, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.join(HERE, "platform")
APP_PATH = os.path.join(PLATFORM, "app.py")
sys.path.insert(0, PLATFORM)
sys.path.insert(0, HERE)
# Critical: chdir into platform/ so Flask's relative template_folder='templates' resolves
os.chdir(PLATFORM)
spec = importlib.util.spec_from_file_location("palmfi_app", APP_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
app = mod.app
