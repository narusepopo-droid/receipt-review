import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/t.db"
os.environ["OPS_EMAILS"] = "ops@test.com"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["INTERNAL_SECRET"] = "internal-test"
os.environ["FIREBASE_API_KEY"] = "fake"
os.environ["FIREBASE_PROJECT_ID"] = "fake-proj"
os.environ["TOSS_CLIENT_KEY"] = ""
os.environ["TOSS_SECRET_KEY"] = ""
os.environ["ALIGO_KEY"] = ""
