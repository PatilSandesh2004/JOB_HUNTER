"""A tiny local job site so browser automation is tested without contacting real employers."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FORM = """<!doctype html><html><body>
<h1>Backend Engineer</h1>
<form action="/thanks" method="post" enctype="multipart/form-data">
  <label for="fn">First Name *</label><input id="fn" name="first_name" required>
  <label for="ln">Last Name *</label><input id="ln" name="last_name" required>
  <label for="em">Email *</label><input id="em" type="email" name="email" required>
  <label for="cc">Phone</label><input id="cc" name="phone_country_search">
  <label for="ph">Phone *</label><input id="ph" type="tel" name="phone" required>
  <label for="comp">What are your compensation requirements for this location?</label><input id="comp" name="comp">
  <label for="li">LinkedIn Profile</label><input id="li" name="urls[LinkedIn]">
  <label for="cv">Resume/CV *</label><input id="cv" type="file" name="resume" required>
  <label for="cl">Cover Letter</label><textarea id="cl" name="cover_letter"></textarea>
  <label for="sp">Will you now or in the future require visa sponsorship? *</label>
  <select id="sp" name="q1" required><option value="">Select...</option><option>Yes</option><option>No</option></select>
  <label for="rc">Company name of your referrer</label><input id="rc" name="ref_company">
  {extra}
  <button type="submit">Submit Application</button>
</form></body></html>"""

CONSENT = '<label><input type="checkbox" name="consent" required> I agree to the privacy policy</label>'
LANDING = '<html><body><h1>Data Engineer</h1><a href="/apply">Apply for this job</a></body></html>'
THANKS = "<html><body><h1>Thank you for applying!</h1><p>We have received your application.</p></body></html>"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        pages = {
            "/apply": FORM.format(extra=""),
            "/apply-consent": FORM.format(extra=CONSENT),
            "/landing": LANDING,
            "/no-form": "<html><body><p>Closed.</p></body></html>",
        }
        self._send(pages.get(self.path, "not found"), 200 if self.path in pages else 404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.server.submissions.append(self.rfile.read(length))  # type: ignore[attr-defined]
        self._send(THANKS)

    def _send(self, body: str, code: int = 200) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class FixtureSite:
    def __enter__(self) -> "FixtureSite":
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.submissions = []  # type: ignore[attr-defined]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    @property
    def submissions(self) -> list[bytes]:
        return self.server.submissions  # type: ignore[attr-defined]

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
