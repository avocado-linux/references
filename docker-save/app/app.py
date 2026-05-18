import sys

from flask import Flask

# Phase 2, change this to 2.0
APP_VERSION = "1.0"

app = Flask(__name__)


@app.route("/")
def index():
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Hello from Avocado</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
      max-width: 640px;
      margin: 4em auto;
      padding: 0 1.5em;
      line-height: 1.6;
      color: #1a1a1a;
    }}
    h1 {{ margin-bottom: 0.25em; }}
    .badge {{
      display: inline-block;
      background: #1a7f37;
      color: white;
      padding: 0.15em 0.5em;
      border-radius: 3px;
      font-size: 0.6em;
      font-weight: 600;
      vertical-align: middle;
      margin-left: 0.25em;
    }}
    code {{
      background: #f4f4f4;
      padding: 0.1em 0.3em;
      border-radius: 3px;
      font-size: 0.9em;
    }}
    .meta {{ color: #666; font-size: 0.9em; }}
  </style>
</head>
<body>
  <h1>Hello from Avocado <span class="badge">v{APP_VERSION}</span></h1>
  <p class="meta">Served by a Python + Flask container running as a systemd service.</p>
  <p>This page is served by a Docker container that was built locally on a developer machine, saved to a tarball with <code>docker save</code>, baked into the application&rsquo;s sysext during <code>avocado build</code>, and loaded into the engine on first merge via <code>docker load</code>. No registry was involved &mdash; the device works fully offline.</p>
  <p>Container Python: <code>{sys.version}</code></p>
</body>
</html>
"""

# @app.route("/healthz")
# def healthz():
#     return {"status": "ok", "version": APP_VERSION}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
