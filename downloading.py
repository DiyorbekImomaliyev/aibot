import os
import whisper
import ssl
import certifi
# Fix SSL for Mac
os.environ['SSL_CERT_FILE'] = certifi.where()
ssl._create_default_https_context = ssl._create_unverified_context
# This downloads and caches the model
model = whisper.load_model("base")
print("✅")